"""Late anonymous probes must not erase a newer HttpOnly handoff cookie."""
from email.message import Message
from http.cookiejar import CookieJar
from types import SimpleNamespace
from urllib.request import Request
import unittest
from unittest import mock

import backend


class HandoffCookieRaceTest(unittest.TestCase):
    token = "synthetic_0123456789_abcdefghijklmnopqrstuvwxyz"

    def exchange(self, *, cookie=None, exchange_header="1", fetch_site="same-origin", session=None, error=None):
        handler = object.__new__(backend.Handler)
        handler.headers = {
            "X-EDOC-Handoff-Exchange": exchange_header,
            "Sec-Fetch-Site": fetch_site,
        }
        if cookie is not None:
            handler.headers["Cookie"] = cookie
        # Exercise the real Handler route, cookie parser and cookie-header builder.
        # Only the HTTP serialization boundary and backend session lookup are mocked.
        handler.send_json = mock.Mock()
        handler.log_handoff_failure = mock.Mock()
        lookup = mock.Mock()
        if error is not None:
            lookup.side_effect = error
        elif session is not None:
            lookup.return_value = session
        else:
            lookup.side_effect = AssertionError("A missing or rejected cookie must not query sessions")
        with (
            mock.patch.object(backend, "USE_SUPABASE", True),
            mock.patch.object(backend, "supabase_current_session", lookup),
            mock.patch.object(backend, "connect", side_effect=AssertionError("No database connection is allowed")),
        ):
            handler.handle_handoff_session_exchange()
        return (*handler.send_json.call_args.args, lookup)

    def cookie_jar_with_new_handoff(self):
        jar = CookieJar()
        request = Request("https://edoc.example.test" + backend.EDOC_HANDOFF_COOKIE_PATH)

        def deliver(headers):
            message = Message()
            for name, value in headers:
                message.add_header(name, value)
            jar.extract_cookies(SimpleNamespace(info=lambda: message), request)

        deliver(backend.Handler.handoff_cookie_headers(self.token))
        self.assertEqual(len(jar), 2)
        self.assertTrue(all(cookie.secure and not cookie.domain_specified for cookie in jar))
        return jar, request, deliver

    def assert_no_store(self, headers):
        values = dict(headers)
        self.assertEqual(values["Cache-Control"], "no-store, max-age=0")
        self.assertEqual(values["Pragma"], "no-cache")
        self.assertEqual(values["Referrer-Policy"], "no-referrer")

    def assert_clears_handoff(self, headers):
        jar, _request, deliver = self.cookie_jar_with_new_handoff()
        deliver(headers)
        self.assertEqual(len(jar), 0)
        self.assert_no_store(headers)

    def test_late_missing_cookie_response_preserves_new_same_tuple_handoff(self):
        payload, status, late_headers, lookup = self.exchange()
        # Request A had no cookie. Request B delivers a new handoff before A's
        # response arrives: the browser must keep both B cookies after A's 401.
        jar, request, deliver = self.cookie_jar_with_new_handoff()
        before = {(cookie.name, cookie.path, cookie.domain): cookie.value for cookie in jar}
        deliver(late_headers)
        after = {(cookie.name, cookie.path, cookie.domain): cookie.value for cookie in jar}
        self.assertEqual(after, before)
        jar.add_cookie_header(request)
        self.assertIn(self.token, request.get_header("Cookie"))
        self.assertEqual(status, 401)
        self.assertEqual(payload, {"error": "handoff_session_missing"})
        self.assertFalse(any(name.lower() == "set-cookie" for name, _value in late_headers))
        self.assert_no_store(late_headers)
        lookup.assert_not_called()

    def test_empty_cookie_and_unrelated_cookie_also_preserve_new_handoff_without_database(self):
        for cookie in (
            backend.EDOC_HANDOFF_COOKIE_NAME + "=",
            backend.EDOC_HANDOFF_COOKIE_NAME + '=""',
            "unrelated_cookie=synthetic",
        ):
            with self.subTest(cookie=cookie):
                payload, status, headers, lookup = self.exchange(cookie=cookie)
                jar, _request, deliver = self.cookie_jar_with_new_handoff()
                deliver(headers)
                self.assertEqual(len(jar), 2)
                self.assertEqual(status, 401)
                self.assertEqual(payload, {"error": "handoff_session_missing"})
                self.assertFalse(any(name.lower() == "set-cookie" for name, _value in headers))
                self.assert_no_store(headers)
                lookup.assert_not_called()

    def test_nonempty_malformed_token_still_clears_cookie_and_never_queries_database(self):
        for value in ("short", "x" * 31, "x" * 257, '"invalid token"'):
            with self.subTest(value=value):
                payload, status, headers, lookup = self.exchange(cookie=backend.EDOC_HANDOFF_COOKIE_NAME + "=" + value)
                self.assertEqual(status, 401)
                self.assertEqual(payload, {"error": "handoff_session_missing"})
                self.assert_clears_handoff(headers)
                lookup.assert_not_called()

    def test_forbidden_exchange_keeps_existing_cookie_clear_behavior(self):
        for options in ({"exchange_header": ""}, {"fetch_site": "cross-site"}):
            with self.subTest(options=options):
                payload, status, headers, lookup = self.exchange(**options)
                self.assertEqual(status, 403)
                self.assertEqual(payload, {"error": "handoff_exchange_forbidden"})
                self.assert_clears_handoff(headers)
                lookup.assert_not_called()

    def test_expired_or_invalid_session_still_clears_cookie(self):
        payload, status, headers, lookup = self.exchange(
            cookie=backend.EDOC_HANDOFF_COOKIE_NAME + "=" + self.token,
            session={},
        )
        self.assertEqual(status, 401)
        self.assertEqual(payload, {"error": "handoff_session_invalid"})
        self.assert_clears_handoff(headers)
        lookup.assert_called_once_with(self.token)

    def test_success_still_returns_session_once_and_clears_handoff_cookie(self):
        session = {"user": {"id": "synthetic-user", "name": "Synthetic Employee"}}
        payload, status, headers, lookup = self.exchange(
            cookie=backend.EDOC_HANDOFF_COOKIE_NAME + "=" + self.token,
            session=session,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload, {**session, "token": self.token})
        self.assert_clears_handoff(headers)
        lookup.assert_called_once_with(self.token)

    def test_transient_503_retains_cookie_and_permanent_failures_still_clear(self):
        cases = (
            (backend.FinanceBridgeUnavailable("synthetic_unavailable"), 503, True),
            (backend.FinanceBridgeDenied("synthetic_denied"), 401, False),
            (RuntimeError("synthetic_integrity_error"), 503, False),
        )
        for error, expected_status, retryable in cases:
            with self.subTest(error=type(error).__name__):
                payload, status, headers, lookup = self.exchange(
                    cookie=backend.EDOC_HANDOFF_COOKIE_NAME + "=" + self.token,
                    error=error,
                )
                self.assertEqual(status, expected_status)
                self.assertEqual(payload["retryable"], retryable)
                self.assert_no_store(headers)
                if retryable:
                    jar, _request, deliver = self.cookie_jar_with_new_handoff()
                    deliver(headers)
                    self.assertEqual(len(jar), 2)
                    self.assertFalse(any(name.lower() == "set-cookie" for name, _value in headers))
                else:
                    self.assert_clears_handoff(headers)
                lookup.assert_called_once_with(self.token)


if __name__ == "__main__":
    unittest.main()
