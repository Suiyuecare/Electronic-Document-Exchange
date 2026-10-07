"""Offline-only privileged probe transport and report safety contracts."""
from __future__ import annotations

import contextlib
import io
import json
import os
import socket
import urllib.error
from unittest import mock
import unittest

from tools import live_editor_launch_acceptance as editor
from tools import live_five_account_sso_acceptance as sso


PROJECT = "a" * 20
OTHER_PROJECT = "b" * 20
PROJECT_ORIGIN = f"https://{PROJECT}.supabase.co"
STORAGE_ORIGIN = f"https://{PROJECT}.storage.supabase.co"


class SignedProbeTransportTest(unittest.TestCase):
    def setUp(self):
        # An accidentally unmocked network operation must fail this suite.
        self.network = mock.patch.object(socket, "socket", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.environment = mock.patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_failure_allowlist_rejects_provider_suffixes_and_sensitive_text(self):
        self.assertEqual("handoff_exchange_http_403", sso.safe_failure_code("handoff_exchange_http_403"))
        self.assertEqual("editor_acceptance_http_409", sso.safe_failure_code("editor_acceptance_http_409"))
        for value in ("handoff_exchange_http_403_private_suffix", "Bearer synthetic-token",
                      "editor_secret_synthetic", "person@example.invalid", "https://private.example.invalid",
                      "editor_acceptance_http_999", "missing_environment_private_secret"):
            with self.subTest(value=value):
                self.assertEqual("acceptance_unexpected_failure", sso.safe_failure_code(value))

    def test_both_main_reports_drop_arbitrary_failure_values_and_never_claim_human_oauth(self):
        accounts = {f"synthetic-{number}@example.invalid": f"SYNTHETIC-{number}" for number in range(5)}
        marker = "synthetic-private-marker-do-not-print"
        for module, operation in ((sso, "acceptance_for_account"), (editor, "_acceptance_for_account")):
            output = io.StringIO()
            with (
                self.subTest(module=module.__name__),
                mock.patch.dict(os.environ, {"EDOC_ALLOW_SIGNED_IDENTITY_PROBE": "1", "PORTAL_HANDOFF_SIGNING_SECRET": "X" * 32}),
                mock.patch.object(sso, "portal_google_accounts", return_value=accounts),
                mock.patch.object(sso, "active_finance_emails", return_value=set(accounts)),
                mock.patch.object(sso, operation, side_effect=sso.AcceptanceError(marker)),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(1, module.main())
            report = json.loads(output.getvalue())
            self.assertNotIn(marker, output.getvalue())
            self.assertFalse(report["humanGoogleLoginExercised"])
            self.assertFalse(report["piiPrinted"])
            self.assertTrue(report["failureCodes"])

    def test_json_transport_rejects_unapproved_origins_before_request(self):
        for url in (sso.EDOC_ORIGIN.replace("https://", "http://") + "/api/auth/me", "https://untrusted.example.invalid/api",
                    sso.EDOC_ORIGIN + ":444/api", sso.EDOC_ORIGIN.replace("https://", "https://user@") + "/api",
                    f"https://{OTHER_PROJECT}.supabase.co/auth/v1/admin/users", sso.EDOC_ORIGIN + "/api#secret"):
            with self.subTest(url=url), mock.patch.object(sso.urllib.request, "build_opener") as opener:
                with self.assertRaisesRegex(sso.AcceptanceError, "origin_invalid"):
                    sso.request_json(url, headers={"Authorization": "Bearer synthetic-session"})
                opener.assert_not_called()

    def test_exact_configured_supabase_origin_allowed_but_other_project_denied(self):
        response = mock.MagicMock(status=200, headers={})
        response.__enter__.return_value = response
        response.read.return_value = b'{"users":[]}'
        with mock.patch.dict(os.environ, {"SUPABASE_URL": PROJECT_ORIGIN}), \
             mock.patch.object(sso.urllib.request, "build_opener") as builder:
            builder.return_value.open.return_value = response
            self.assertEqual((200, {"users": []}), sso.request_json(PROJECT_ORIGIN + "/auth/v1/admin/users", headers={"apikey": "synthetic-key"}))
            self.assertTrue(any(isinstance(handler, sso.NoRedirect) for handler in builder.call_args.args))
            before = builder.call_count
            with self.assertRaisesRegex(sso.AcceptanceError, "origin_invalid"):
                sso.request_json(f"https://{OTHER_PROJECT}.supabase.co/auth/v1/admin/users", headers={"apikey": "synthetic-key"})
            self.assertEqual(before, builder.call_count)

    def test_malformed_project_configuration_never_reads_service_key_or_sends_request(self):
        for origin in ("http://project.supabase.co", "https://untrusted.example.invalid", PROJECT_ORIGIN + "/auth", "https://user@" + PROJECT + ".supabase.co"):
            with self.subTest(origin=origin), mock.patch.dict(os.environ, {"SUPABASE_URL": origin}), \
                 mock.patch.object(sso.urllib.request, "build_opener") as builder:
                with self.assertRaisesRegex(sso.AcceptanceError, "origin_invalid"):
                    sso.portal_google_accounts()
                builder.assert_not_called()

    def test_no_redirect_handlers_never_replay_any_credentialed_request(self):
        request = sso.urllib.request.Request(sso.EDOC_ORIGIN + "/api/auth/me", headers={"Authorization": "Bearer synthetic-session"})
        for handler in (sso.NoRedirect(), editor.NoRedirect()):
            for target in (sso.EDOC_ORIGIN + "/other", "https://untrusted.example.invalid", sso.EDOC_ORIGIN.replace("https://", "http://")):
                with self.subTest(handler=type(handler).__name__, target=target):
                    self.assertIsNone(handler.redirect_request(request, None, 302, "Found", {}, target))

    def test_json_http_redirect_is_returned_without_second_request(self):
        redirect = urllib.error.HTTPError(sso.EDOC_ORIGIN + "/api/auth/me", 302, "Found", {"Location": "https://untrusted.example.invalid"}, io.BytesIO(b""))
        with mock.patch.object(sso.urllib.request, "build_opener") as builder:
            builder.return_value.open.side_effect = redirect
            self.assertEqual((302, {}), sso.request_json(sso.EDOC_ORIGIN + "/api/auth/me", headers={"Authorization": "Bearer synthetic-session"}))
            self.assertEqual(1, builder.return_value.open.call_count)
            self.assertTrue(any(isinstance(handler, sso.NoRedirect) for handler in builder.call_args.args))

    def test_handoff_cross_origin_location_is_rejected_before_session_exchange(self):
        with mock.patch.object(sso, "request_bytes", return_value=(303, {"Location": "https://untrusted.example.invalid/"}, b"")), \
             mock.patch.object(sso, "request_json") as request:
            with self.assertRaisesRegex(sso.AcceptanceError, "origin_invalid"):
                sso._acceptance_for_account("synthetic@example.invalid", "SYNTHETIC", "X" * 32, 1, [])
            request.assert_not_called()

    def test_handoff_accepts_303_cookie_without_following_root_page(self):
        issued = []
        with mock.patch.object(sso.http.cookiejar, "CookieJar", return_value=[object()]), \
             mock.patch.object(sso, "request_bytes", return_value=(303, {"Location": "/"}, b"")) as raw, \
             mock.patch.object(sso, "request_json", side_effect=[
                 (200, {"token": "T" * 32, "user": {"account_source": "finance"}}),
                 (200, {"user": {"account_source": "finance"}}),
                 (200, {"currentCompanyId": "SYNTHETIC-COMPANY", "departments": [{}]}),
             ]):
            result = sso._acceptance_for_account("synthetic@example.invalid", "SYNTHETIC", "X" * 32, 1, issued)
        self.assertEqual(1, result["handoff303"])
        self.assertEqual(1, raw.call_count)
        self.assertTrue(raw.call_args.args[0].endswith("/api/auth/handoff"))
        self.assertEqual("POST", raw.call_args.kwargs["method"])
        self.assertEqual(["T" * 32], issued)

    def test_handoff_upstream_error_is_not_in_failure_code(self):
        with mock.patch.object(sso.http.cookiejar, "CookieJar", return_value=[object()]), \
             mock.patch.object(sso, "request_bytes", return_value=(303, {"Location": "/"}, b"")), \
             mock.patch.object(sso, "request_json", return_value=(403, {"error": "Bearer synthetic-private-marker"})):
            with self.assertRaises(sso.AcceptanceError) as failure:
                sso._acceptance_for_account("synthetic@example.invalid", "SYNTHETIC", "X" * 32, 1, [])
        self.assertEqual("handoff_exchange_http_403", str(failure.exception))

    def test_editor_api_does_not_echo_prefixed_provider_detail(self):
        with mock.patch.object(editor, "raw_request", return_value=(403, {}, b'{"detail":"editor_private_secret_marker"}')):
            with self.assertRaises(sso.AcceptanceError) as failure:
                editor.api("synthetic", "GET", "/api/official-documents/OD-TEST", 200)
        self.assertEqual("editor_acceptance_http_403", str(failure.exception))

    def test_editor_storage_transport_is_exactly_project_bound(self):
        response = mock.MagicMock(status=204, headers={"Upload-Offset": "0"})
        response.__enter__.return_value = response
        response.read.return_value = b""
        with mock.patch.dict(os.environ, {"EDOC_STORAGE_SUPABASE_URL": PROJECT_ORIGIN}), \
             mock.patch.object(editor.urllib.request, "build_opener") as builder:
            builder.return_value.open.return_value = response
            self.assertEqual(204, editor.raw_request(STORAGE_ORIGIN + "/storage/v1/upload/resumable/sign", "POST", headers={"x-signature": "synthetic-capability"})[0])
            self.assertTrue(any(isinstance(handler, editor.NoRedirect) for handler in builder.call_args.args))
            before = builder.call_count
            for url in (f"https://{OTHER_PROJECT}.storage.supabase.co/storage/v1/upload/resumable/sign", "http://" + PROJECT + ".storage.supabase.co/storage/v1/upload/resumable/sign", "https://untrusted.example.invalid"):
                with self.subTest(url=url), self.assertRaisesRegex(sso.AcceptanceError, "origin_invalid"):
                    editor.raw_request(url, headers={"x-signature": "synthetic-capability"})
                self.assertEqual(before, builder.call_count)

    def test_editor_storage_origin_requires_configuration_not_arbitrary_intent_host(self):
        with mock.patch.object(editor.urllib.request, "build_opener") as builder:
            with self.assertRaisesRegex(sso.AcceptanceError, "origin_invalid"):
                editor.raw_request(STORAGE_ORIGIN + "/storage/v1/upload/resumable/sign", headers={"x-signature": "synthetic-capability"})
            builder.assert_not_called()

    def test_editor_http_redirect_is_returned_without_forwarding_signature(self):
        redirect = urllib.error.HTTPError(editor.ORIGIN + "/api/official-documents/OD-TEST", 302, "Found", {"Location": "https://untrusted.example.invalid"}, io.BytesIO(b""))
        with mock.patch.object(editor.urllib.request, "build_opener") as builder:
            builder.return_value.open.side_effect = redirect
            self.assertEqual(302, editor.raw_request(editor.ORIGIN + "/api/official-documents/OD-TEST", headers={"Authorization": "Bearer synthetic-session"})[0])
            self.assertEqual(1, builder.return_value.open.call_count)
            self.assertTrue(any(isinstance(handler, editor.NoRedirect) for handler in builder.call_args.args))

    def test_finance_inventory_uses_guarded_transport_not_urlopen(self):
        with mock.patch.dict(os.environ, {"FINANCE_SOURCE_SUPABASE_URL": PROJECT_ORIGIN, "FINANCE_SOURCE_SECRET_KEY": "synthetic-key"}), \
             mock.patch.object(sso, "request_bytes", return_value=(200, {}, b'[{"email":"synthetic@example.invalid"}]')) as request, \
             mock.patch.object(sso.urllib.request, "urlopen") as legacy:
            self.assertEqual({"synthetic@example.invalid"}, sso.active_finance_emails())
        self.assertTrue(request.call_args.args[0].startswith(PROJECT_ORIGIN + "/rest/v1/finance_users?"))
        self.assertEqual("synthetic-key", request.call_args.kwargs["headers"]["apikey"])
        legacy.assert_not_called()

    def test_sso_main_exact_opt_in_precedes_secret_and_inventory_reads(self):
        for flag in ("", "0", "true"):
            with self.subTest(flag=flag), mock.patch.dict(os.environ, {"EDOC_ALLOW_SIGNED_IDENTITY_PROBE": flag}), \
                 mock.patch.object(sso, "required_environment") as secret, \
                 mock.patch.object(sso, "portal_google_accounts") as inventory:
                with self.assertRaisesRegex(sso.AcceptanceError, "not_human_sso"):
                    sso.main()
            secret.assert_not_called()
            inventory.assert_not_called()

    def test_editor_cleanup_failure_is_safe_and_later_session_cleanup_still_runs(self):
        revoked = set()
        def issue(email, _identity, _secret, ordinal, issued):
            issued.append(f"synthetic-session-{ordinal}")
        def request(url, *, headers, method="GET", **_kwargs):
            token = headers["Authorization"].split()[-1]
            if method == "POST":
                if token.endswith("-1"):
                    raise urllib.error.URLError("synthetic-private-marker")
                revoked.add(token)
                return 200, {"ok": True}
            return (401, {}) if token in revoked else (200, {"user": {"company_id": "SYNTHETIC-COMPANY"}, "permissions": ["official_documents.compose"]})
        accounts = {f"synthetic-{number}@example.invalid": f"SYNTHETIC-{number}" for number in range(2)}
        output = io.StringIO()
        with mock.patch.dict(os.environ, {"EDOC_ALLOW_SIGNED_IDENTITY_PROBE": "1", "PORTAL_HANDOFF_SIGNING_SECRET": "X" * 32}), \
             mock.patch.object(sso, "portal_google_accounts", return_value=accounts), \
             mock.patch.object(sso, "active_finance_emails", return_value=set(accounts)), \
             mock.patch.object(sso, "_acceptance_for_account", side_effect=issue), \
             mock.patch.object(sso, "request_json", side_effect=request), \
             mock.patch.object(editor, "run_editor_checks"), contextlib.redirect_stdout(output):
            self.assertEqual(1, editor.main())
        report = json.loads(output.getvalue())
        self.assertEqual(1, report["sessionsRevoked"])
        self.assertEqual(["editor_acceptance_session_cleanup_failed"], report["failureCodes"])
        self.assertNotIn("synthetic-private-marker", output.getvalue())


if __name__ == "__main__":
    unittest.main()
