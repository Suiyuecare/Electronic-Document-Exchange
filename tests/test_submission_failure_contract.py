"""Safe, endpoint-scoped diagnostics for an atomic submit rejection."""
import io
import json
import unittest
import urllib.error
from unittest import mock

import backend


class SubmissionFailureContractTest(unittest.TestCase):
    def transport(self, *, path="rpc/edoc_commit_official_document_submission",
                  method="POST", status=400, code="22023",
                  message="official_submission_invalid_payload"):
        stream = io.BytesIO(json.dumps({
            "code": code, "message": message,
            "detail": "PRIVATE-DOCUMENT person@example.invalid secret-token",
        }).encode())
        error = urllib.error.HTTPError("https://fixture.supabase.co/rest/v1/", status, "private", {}, stream)
        with mock.patch.object(backend, "SUPABASE_URL", "https://fixture.supabase.co"), \
             mock.patch.object(backend, "SUPABASE_SERVICE_ROLE_KEY", "synthetic-test-key"), \
             mock.patch.object(backend, "supabase_headers", return_value={}), \
             mock.patch.object(backend, "_urlopen_no_redirect", side_effect=error):
            try:
                backend.supabase_request(method, path, {})
            except Exception as actual:
                self.assertTrue(stream.closed)
                for forbidden in ("PRIVATE", "example.invalid", "secret-token"):
                    self.assertNotIn(forbidden, str(actual))
                return actual
        self.fail("Expected the rejected RPC to raise")

    def test_exact_atomic_validation_error_is_typed_without_sensitive_body(self):
        error = self.transport()
        self.assertIsInstance(error, backend.OfficialSubmissionValidationError)
        self.assertEqual(str(error), "official_submission_validation_failed")

    def test_wrong_route_method_status_code_or_message_stays_opaque(self):
        for override in (
            {"path": "rpc/unrelated"}, {"method": "GET"}, {"status": 500},
            {"code": "23502"}, {"message": "official_submission_invalid_payload PRIVATE"},
        ):
            with self.subTest(override=override):
                error = self.transport(**override)
                self.assertIsInstance(error, RuntimeError)
                self.assertNotIsInstance(error, backend.OfficialSubmissionValidationError)
                self.assertTrue(str(error).startswith("supabase_request_failed:"))

    def test_general_error_contract_does_not_enable_submission_allowlist(self):
        stream = io.BytesIO(b'{"code":"22023","message":"official_submission_invalid_payload"}')
        error = urllib.error.HTTPError("https://fixture.invalid", 400, "invalid", {}, stream)
        marker, exposed = backend._safe_http_error_contract(error, "readiness")
        self.assertEqual((marker, exposed), ("readiness:400:22023", ""))

    def test_actual_handler_preserves_correlation_and_distinguishes_unknown(self):
        for error, status, state, code in (
            (backend.OfficialSubmissionValidationError(), 500, "not_submitted", "official_submission_validation_failed"),
            (backend.OfficialSubmissionOutcomeUnknownError(), 503, "unknown", "official_document_submit_commit_state_unknown"),
        ):
            with self.subTest(state=state):
                handler = object.__new__(backend.Handler)
                handler.command = "POST"
                handler.path = "/api/official-documents/SYNTHETIC/submit"
                handler.wfile = io.BytesIO()
                handler.headers = {}
                handler.client_address = ("127.0.0.1", 0)
                handler.send_response = mock.Mock()
                headers = {}
                handler.send_header = lambda name, value: headers.update({name: value})
                handler.end_headers = mock.Mock()
                handler.bearer_token = lambda: "synthetic"
                handler.read_json = lambda: {}
                handler.require_table_access = lambda *args, **kwargs: True
                output = io.StringIO()
                with mock.patch.object(backend, "USE_SUPABASE", True), \
                     mock.patch.object(backend, "supabase_current_session", return_value={"user": {"id": "SYNTHETIC"}}), \
                     mock.patch.object(backend, "supabase_submit_official_document", side_effect=error), \
                     mock.patch("sys.stderr", output):
                    handler.handle_api("POST", handler.path, {})
                payload = json.loads(handler.wfile.getvalue())
                handler.send_response.assert_called_with(status)
                self.assertEqual(payload["detail"], code)
                self.assertEqual(payload["submissionStatus"], state)
                self.assertFalse(payload["retryable"])
                self.assertEqual(payload["errorId"], headers["X-EDOC-Error-ID"])
                self.assertNotIn("SYNTHETIC", output.getvalue())


if __name__ == "__main__":
    unittest.main()
