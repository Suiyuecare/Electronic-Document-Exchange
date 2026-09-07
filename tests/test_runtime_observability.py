import io
import json
import unittest
from unittest import mock

from runtime_observability import capture_runtime_error, error_tracking_status, route_group


class RuntimeObservabilityTests(unittest.TestCase):
    def test_handler_exposes_same_reference_in_header_body_and_log(self):
        import backend
        handler = object.__new__(backend.Handler)
        handler.command = "POST"
        handler.path = "/api/official-documents/PRIVATE-DOCUMENT"
        handler.wfile = io.BytesIO()
        headers = {}
        handler.send_response = mock.Mock()
        handler.send_header = lambda name, value: headers.update({name: value})
        handler.end_headers = mock.Mock()
        output = io.StringIO()
        with mock.patch("sys.stderr", output):
            try:
                raise RuntimeError("PRIVATE-PDF-CONTENT")
            except RuntimeError:
                handler.send_json({"error": "server_error", "detail": "internal_server_error"}, 500)
        payload = json.loads(handler.wfile.getvalue())
        event = json.loads(output.getvalue())
        self.assertEqual(payload["errorId"], headers["X-EDOC-Error-ID"])
        self.assertEqual(payload["errorId"], event["eventId"])
        self.assertEqual(int(headers["Content-Length"]), len(handler.wfile.getvalue()))
        self.assertNotIn("PRIVATE", output.getvalue())

    def test_never_captures_personal_data_secrets_or_dynamic_routes(self):
        output = io.StringIO()
        error = ValueError("PRIVATE-PDF-TEXT person@example.test Bearer SECRET")
        event_id = capture_runtime_error(method="POST", path="/api/official-documents/PRIVATE-ID?token=SECRET",
                                         status=500, exception=error, stream=output)
        event = json.loads(output.getvalue())
        self.assertEqual(event["route"], "/api/official-documents")
        self.assertEqual(event["eventId"], event_id)
        self.assertRegex(event_id, r"^ERR-[A-F0-9]{24}$")
        for forbidden in ["PRIVATE", "SECRET", "example.test", "Bearer", "ValueError"]:
            self.assertNotIn(forbidden, output.getvalue())

    def test_same_failure_groups_but_has_distinct_reference(self):
        events = []
        for value in ["one", "two"]:
            output = io.StringIO()
            capture_runtime_error(method="GET", path="/api/documents/" + value, status=503,
                                  exception=TimeoutError(value), stream=output)
            events.append(json.loads(output.getvalue()))
        self.assertEqual(events[0]["fingerprint"], events[1]["fingerprint"])
        self.assertNotEqual(events[0]["eventId"], events[1]["eventId"])

    def test_untrusted_resource_and_method_are_not_logged(self):
        output = io.StringIO()
        capture_runtime_error(method="private", path="/api/private@email.test", status=500, stream=output)
        self.assertNotIn("private", output.getvalue())
        self.assertEqual(route_group("//[invalid"), "/api/other")

    def test_log_failure_does_not_hide_original_failure(self):
        stream = mock.Mock()
        stream.write.side_effect = OSError("disk error")
        self.assertRegex(capture_runtime_error(method="GET", path="/api/healthz", status=503,
                                               stream=stream), r"^ERR-")

    def test_sentry_presence_is_not_claimed_as_a_connection(self):
        with mock.patch.dict("os.environ", {"SENTRY_DSN": "https://invalid.example/1"}):
            self.assertFalse(error_tracking_status()["sentryConnected"])
            self.assertTrue(error_tracking_status()["correlationId"])
