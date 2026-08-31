import io
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import backend
import finance_bridge


REDIRECT_CODES = (301, 302, 307, 308)
SECRET_TEXT = "private-pdf-content bearer-secret@example.test"


def tracking_http_error(code: int, body: bytes | None = None):
    stream = io.BytesIO(body or (SECRET_TEXT.encode("utf-8") * 1024))
    error = urllib.error.HTTPError(
        "https://upstream.example.test/private",
        code,
        "upstream response deliberately contains private content",
        {},
        stream,
    )
    return error, stream


class _Response:
    status = 200
    headers = {}

    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=-1):
        return self.body


class SensitiveTransportHardeningTests(unittest.TestCase):
    POSTGREST_PT409_CONFLICTS = {
        "finance_member_sync_event_id_conflict",
        "finance_organization_revision_conflict",
        "editor_upload_new_intent_required",
        "editor_revision_conflict",
        "editor_finalize_operation_conflict",
        "editor_file_object_conflict",
        "editor_official_file_conflict",
        "official_document_submit_stale",
        "official_submission_operation_conflict",
        "official_workflow_existing_steps_invalid",
        "official_document_resubmit_generation_conflict",
        "official_document_resubmit_idempotency_conflict",
        "official_document_resubmit_audit_idempotency_conflict",
        "official_document_approval_claim_conflict",
        "official_document_approval_evidence_conflict",
        "official_document_next_step_activation_conflict",
        "official_document_rejection_claim_conflict",
        "official_document_rejection_evidence_conflict",
        "official_document_rejection_correction_conflict",
        "official_dispatch_route_conflict",
        "official_dispatch_completion_conflict",
        "official_workflow_delegation_revoke_conflict",
        "inbound_idempotency_conflict",
        "inbound_version_conflict",
        "inbound_registration_state_conflict",
        "inbound_mutation_state_conflict",
    }
    POSTGREST_23505_CONFLICTS = {
        "finance_member_sync_event_id_conflict",
        "finance_organization_revision_conflict",
        "editor_revision_conflict",
        "editor_finalize_operation_conflict",
        "editor_file_object_conflict",
        "editor_official_file_conflict",
        "official_submission_operation_conflict",
        "official_workflow_existing_steps_invalid",
        "official_document_resubmit_idempotency_conflict",
        "official_document_resubmit_audit_idempotency_conflict",
        "official_dispatch_route_conflict",
    }

    def test_backend_and_finance_transports_reject_every_redirect_without_second_hop(self):
        hits = []

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler contract
                hits.append((self.path, self.headers.get("Authorization", "")))
                if self.path.startswith("/redirect/"):
                    code = int(self.path.rsplit("/", 1)[-1])
                    self.send_response(code)
                    self.send_header("Location", "/credential-sink")
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            for transport in (backend._urlopen_no_redirect, finance_bridge._urlopen_no_redirect):
                for code in REDIRECT_CODES:
                    with self.subTest(transport=transport.__module__, code=code):
                        request = urllib.request.Request(
                            f"http://127.0.0.1:{server.server_port}/redirect/{code}",
                            headers={"Authorization": "Bearer must-stay-on-first-hop"},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as raised:
                            transport(request, timeout=1)
                        self.assertEqual(raised.exception.code, code)
                        raised.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

        self.assertEqual(len(hits), len(REDIRECT_CODES) * 2)
        self.assertFalse(any(path == "/credential-sink" for path, _auth in hits))

    def test_supabase_request_uses_positive_no_redirect_transport(self):
        response = _Response(b'[{"id":"OD-1"}]')
        with (
            mock.patch.object(backend, "SUPABASE_URL", "https://project-ref.supabase.co"),
            mock.patch.object(backend, "SUPABASE_SERVICE_ROLE_KEY", "sb_secret_" + "s" * 40),
            mock.patch.object(backend, "_urlopen_no_redirect", return_value=response) as safe_open,
            mock.patch.object(backend.urllib.request, "urlopen") as default_open,
        ):
            rows = backend.supabase_request("GET", "official_documents?select=id&limit=1")

        self.assertEqual(rows, [{"id": "OD-1"}])
        safe_open.assert_called_once()
        default_open.assert_not_called()
        request = safe_open.call_args.args[0]
        self.assertEqual(request.full_url, "https://project-ref.supabase.co/rest/v1/official_documents?select=id&limit=1")
        self.assertEqual(request.get_header("Apikey"), "sb_secret_" + "s" * 40)

    def test_large_postgrest_error_is_closed_and_only_machine_code_survives(self):
        body = json.dumps(
            {
                "code": "PGRST202",
                "message": SECRET_TEXT * 1000,
                "details": "full official document contents must not escape",
            }
        ).encode("utf-8")
        error, stream = tracking_http_error(400, body)
        with (
            mock.patch.object(backend, "SUPABASE_URL", "https://project-ref.supabase.co"),
            mock.patch.object(backend, "SUPABASE_SERVICE_ROLE_KEY", "sb_secret_" + "s" * 40),
            mock.patch.object(backend, "_urlopen_no_redirect", side_effect=error),
        ):
            with self.assertRaises(RuntimeError) as raised:
                backend.supabase_request("POST", "rpc/private", {"document": SECRET_TEXT})

        self.assertEqual(str(raised.exception), "supabase_request_failed:400:PGRST202")
        self.assertNotIn(SECRET_TEXT, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertTrue(stream.closed)

    def test_allowlisted_postgrest_pt409_conflicts_reach_application_as_409(self):
        self.assertEqual(
            set(backend.POSTGREST_PT409_BUSINESS_CONFLICT_CODES),
            self.POSTGREST_PT409_CONFLICTS,
        )
        for conflict in sorted(self.POSTGREST_PT409_CONFLICTS):
            with self.subTest(conflict=conflict):
                body = json.dumps(
                    {
                        "code": "PT409",
                        "message": conflict,
                        "details": SECRET_TEXT,
                        "hint": "private document data must stay upstream",
                    }
                ).encode("utf-8")
                error, stream = tracking_http_error(409, body)
                with (
                    mock.patch.object(backend, "SUPABASE_URL", "https://project-ref.supabase.co"),
                    mock.patch.object(backend, "SUPABASE_SERVICE_ROLE_KEY", "sb_secret_" + "s" * 40),
                    mock.patch.object(backend, "_urlopen_no_redirect", side_effect=error),
                ):
                    with self.assertRaises(ValueError) as raised:
                        backend.supabase_request("POST", "rpc/private", {"document": SECRET_TEXT})

                self.assertEqual(str(raised.exception), conflict)
                self.assertEqual(backend.api_value_error_status(str(raised.exception)), 409)
                self.assertNotIn(SECRET_TEXT, str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertTrue(stream.closed)

    def test_postgrest_pt409_unknown_or_spoofed_message_stays_opaque(self):
        cases = (
            (409, "PT409", f"unknown_conflict:{SECRET_TEXT}"),
            (409, "PGRST116", "editor_revision_conflict"),
            (400, "PT409", "editor_revision_conflict"),
            (409, "23505", f"unknown_constraint:{SECRET_TEXT}"),
            (400, "23505", "editor_finalize_operation_conflict"),
        )
        for http_status, provider_code, message in cases:
            with self.subTest(
                http_status=http_status,
                provider_code=provider_code,
                message=message,
            ):
                body = json.dumps(
                    {
                        "code": provider_code,
                        "message": message,
                        "details": SECRET_TEXT,
                    }
                ).encode("utf-8")
                error, stream = tracking_http_error(http_status, body)
                with (
                    mock.patch.object(backend, "SUPABASE_URL", "https://project-ref.supabase.co"),
                    mock.patch.object(backend, "SUPABASE_SERVICE_ROLE_KEY", "sb_secret_" + "s" * 40),
                    mock.patch.object(backend, "_urlopen_no_redirect", side_effect=error),
                ):
                    with self.assertRaises(RuntimeError) as raised:
                        backend.supabase_request("POST", "rpc/private", {"document": SECRET_TEXT})

                self.assertEqual(
                    str(raised.exception),
                    f"supabase_request_failed:{http_status}:{provider_code}",
                )
                self.assertNotIn(message, str(raised.exception))
                self.assertNotIn(SECRET_TEXT, str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertTrue(stream.closed)

        self.assertEqual(backend.api_value_error_status("unknown_conflict"), 422)

    def test_allowlisted_legacy_23505_business_conflicts_reach_application_as_409(self):
        self.assertEqual(
            set(backend.POSTGREST_23505_BUSINESS_CONFLICT_CODES),
            self.POSTGREST_23505_CONFLICTS,
        )
        for conflict in sorted(self.POSTGREST_23505_CONFLICTS):
            with self.subTest(conflict=conflict):
                body = json.dumps(
                    {
                        "code": "23505",
                        "message": conflict,
                        "details": SECRET_TEXT,
                        "hint": "native constraint details must stay upstream",
                    }
                ).encode("utf-8")
                error, stream = tracking_http_error(409, body)
                with (
                    mock.patch.object(backend, "SUPABASE_URL", "https://project-ref.supabase.co"),
                    mock.patch.object(backend, "SUPABASE_SERVICE_ROLE_KEY", "sb_secret_" + "s" * 40),
                    mock.patch.object(backend, "_urlopen_no_redirect", side_effect=error),
                ):
                    with self.assertRaises(ValueError) as raised:
                        backend.supabase_request("POST", "rpc/private", {"document": SECRET_TEXT})

                self.assertEqual(str(raised.exception), conflict)
                self.assertEqual(backend.api_value_error_status(str(raised.exception)), 409)
                self.assertNotIn(SECRET_TEXT, str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertTrue(stream.closed)

    def test_api_handler_returns_409_and_logs_only_stable_conflict_code(self):
        handler = object.__new__(backend.Handler)
        responses = []
        handler.bearer_token = lambda: "t" * 48
        handler.read_json = lambda: {"sha256": "A" * 64}
        handler.send_json = lambda payload, status=200, *_headers: responses.append(
            (payload, status)
        )
        session = {"user": {"id": "USER-DEIDENTIFIED"}, "permissions": []}
        with (
            mock.patch.object(backend, "USE_SUPABASE", True),
            mock.patch.object(backend, "supabase_current_session", return_value=session),
            mock.patch.object(
                backend,
                "supabase_finalize_official_editor_upload",
                side_effect=ValueError("editor_upload_new_intent_required"),
            ),
            mock.patch.object(backend, "log_structured") as log,
        ):
            handler.handle_api(
                "POST",
                "/api/official-documents/OD-DEIDENTIFIED/editor-uploads/UP-DEIDENTIFIED/finalize",
                {},
            )

        self.assertEqual(
            responses,
            [
                (
                    {
                        "error": "request_rejected",
                        "detail": "editor_upload_new_intent_required",
                    },
                    409,
                )
            ],
        )
        log.assert_called_once_with(
            "warning",
            "api_request_rejected",
            path="/api/official-documents/OD-DEIDENTIFIED/editor-uploads/UP-DEIDENTIFIED/finalize",
            method="POST",
            error="editor_upload_new_intent_required",
        )
        self.assertNotIn(SECRET_TEXT, repr(log.call_args))

    def test_api_handler_keeps_unknown_pt409_opaque_and_returns_500(self):
        handler = object.__new__(backend.Handler)
        responses = []
        handler.bearer_token = lambda: "t" * 48
        handler.read_json = lambda: {"sha256": "A" * 64}
        handler.send_json = lambda payload, status=200, *_headers: responses.append(
            (payload, status)
        )
        session = {"user": {"id": "USER-DEIDENTIFIED"}, "permissions": []}
        opaque_marker = "supabase_request_failed:409:PT409"
        with (
            mock.patch.object(backend, "USE_SUPABASE", True),
            mock.patch.object(backend, "is_production", return_value=True),
            mock.patch.object(backend, "supabase_current_session", return_value=session),
            mock.patch.object(
                backend,
                "supabase_finalize_official_editor_upload",
                side_effect=RuntimeError(opaque_marker),
            ),
            mock.patch.object(backend, "log_structured") as log,
        ):
            handler.handle_api(
                "POST",
                "/api/official-documents/OD-DEIDENTIFIED/editor-uploads/UP-DEIDENTIFIED/finalize",
                {},
            )

        self.assertEqual(
            responses,
            [
                (
                    {"error": "server_error", "detail": "internal_server_error"},
                    500,
                )
            ],
        )
        log.assert_called_once_with(
            "error",
            "api_request_failed",
            path="/api/official-documents/OD-DEIDENTIFIED/editor-uploads/UP-DEIDENTIFIED/finalize",
            method="POST",
            error=opaque_marker,
        )
        self.assertNotIn(SECRET_TEXT, repr(log.call_args))

    def test_large_storage_error_is_closed_without_body_or_cause(self):
        error, stream = tracking_http_error(413)
        with (
            mock.patch.object(backend, "supabase_storage_object_url", return_value="https://project-ref.supabase.co/storage/v1/object/private/a.pdf"),
            mock.patch.object(backend, "supabase_storage_headers", return_value={"apikey": "redacted"}),
            mock.patch.object(backend, "_urlopen_no_redirect", side_effect=error),
        ):
            with self.assertRaises(ValueError) as raised:
                backend.supabase_storage_upload("private/a.pdf", b"private bytes", "application/pdf")

        self.assertEqual(str(raised.exception), "supabase_storage_upload_failed:413")
        self.assertNotIn(SECRET_TEXT, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertTrue(stream.closed)

    def test_readiness_http_error_is_closed_without_body_or_cause(self):
        error, stream = tracking_http_error(503)
        with mock.patch.object(backend, "_urlopen_no_redirect", side_effect=error):
            with self.assertRaises(RuntimeError) as raised:
                backend._readiness_http_json(
                    "https://project-ref.supabase.co/rest/v1/official_documents?limit=1",
                    headers={"apikey": "server-only"},
                    timeout=1,
                    allow_redirects=False,
                )

        self.assertEqual(str(raised.exception), "readiness_http_error")
        self.assertNotIn(SECRET_TEXT, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertTrue(stream.closed)

    def test_all_sensitive_callers_close_redirect_responses_and_return_fixed_errors(self):
        for code in REDIRECT_CODES:
            with self.subTest(provider="finance", code=code):
                error, stream = tracking_http_error(code)
                with mock.patch.object(finance_bridge, "_urlopen_no_redirect", side_effect=error):
                    with self.assertRaises(finance_bridge.FinanceBridgeUnavailable) as raised:
                        finance_bridge.fetch_finance_bridge_snapshot(
                            url="https://finance.example.test/snapshot",
                            secret="f" * 48,
                            timeout_seconds=1,
                            email="worker@example.test",
                            request_id="REQ-1",
                        )
                self.assertEqual(str(raised.exception), "finance_bridge_unavailable")
                self.assertIsNone(raised.exception.__cause__)
                self.assertTrue(stream.closed)

            with self.subTest(provider="antivirus", code=code):
                error, stream = tracking_http_error(code)
                with (
                    mock.patch.object(backend, "is_production", return_value=True),
                    mock.patch.object(backend, "EDOC_AV_ENDPOINT", "https://scanner.example.test/v1/scan"),
                    mock.patch.object(backend, "EDOC_AV_PROVIDER", "edoc-clamav-https-v1"),
                    mock.patch.dict(os.environ, {"EDOC_AV_API_KEY": "a" * 48}),
                    mock.patch.object(backend, "_urlopen_no_redirect", side_effect=error),
                ):
                    with self.assertRaises(ValueError) as raised:
                        backend.editor_scan_bytes_for_threats(b"%PDF private", "document.pdf")
                self.assertEqual(str(raised.exception), "editor_antivirus_scan_failed")
                self.assertIsNone(raised.exception.__cause__)
                self.assertTrue(stream.closed)

            with self.subTest(provider="signature", code=code):
                error, stream = tracking_http_error(code)
                with (
                    mock.patch.object(backend, "EDOC_SIGNATURE_MAX_RETRIES", 0),
                    mock.patch.object(backend, "_urlopen_no_redirect", side_effect=error),
                ):
                    with self.assertRaises(backend.SignatureProviderError) as raised:
                        backend.provider_json_request(
                            "https://signature.example.test/sign",
                            {"request_id": "SIG-1", "digest": "a" * 64},
                            "provider-secret",
                        )
                self.assertEqual(str(raised.exception), f"provider_http_{code}")
                self.assertEqual(raised.exception.event["error"], f"provider_http_{code}")
                self.assertNotIn(SECRET_TEXT, repr(raised.exception.event))
                self.assertIsNone(raised.exception.__cause__)
                self.assertTrue(stream.closed)

            with self.subTest(provider="resend", code=code):
                error, stream = tracking_http_error(code)
                with (
                    mock.patch.dict(os.environ, {"RESEND_API_KEY": "resend-secret", "MAIL_FROM": "edoc@example.test"}),
                    mock.patch.object(backend, "_urlopen_no_redirect", side_effect=error),
                ):
                    result = backend.send_resend_email_notification(
                        "worker@example.test", "待簽核", "private document text", "NOTIFY-1"
                    )
                self.assertEqual(result["error"], f"Resend HTTP {code}")
                self.assertNotIn(SECRET_TEXT, repr(result))
                self.assertTrue(stream.closed)

            with self.subTest(provider="line", code=code):
                error, stream = tracking_http_error(code)
                with (
                    mock.patch.dict(os.environ, {"LINE_WEBHOOK_URL": "https://line.example.test/hook"}),
                    mock.patch.object(backend, "_urlopen_no_redirect", side_effect=error),
                ):
                    result = backend.send_line_notification("private document text")
                self.assertEqual(result["error"], f"HTTP {code}")
                self.assertNotIn(SECRET_TEXT, repr(result))
                self.assertTrue(stream.closed)

            with self.subTest(provider="openai", code=code):
                error, stream = tracking_http_error(code)
                with (
                    mock.patch.object(backend, "OPENAI_API_KEY", "openai-secret"),
                    mock.patch.object(backend, "_urlopen_no_redirect", side_effect=error),
                    mock.patch.object(backend, "record_ai_compose_audit") as audit,
                ):
                    result = backend.ai_compose_official_draft(
                        None,
                        {"plainText": "請協助辦理年度資料更新", "recipient": "主管機關"},
                    )
                self.assertFalse(result.get("usedOpenAI", False))
                self.assertIn(f"openai_http_{code}", repr(audit.call_args))
                self.assertNotIn(SECRET_TEXT, repr(audit.call_args))
                self.assertTrue(stream.closed)

            with self.subTest(provider="monitoring", code=code):
                error, stream = tracking_http_error(code)
                with (
                    mock.patch.object(backend, "MONITORING_WEBHOOK_URL", "https://monitor.example.test/hook"),
                    mock.patch.object(backend, "_urlopen_no_redirect", side_effect=error),
                ):
                    result = backend.post_monitoring_webhook(
                        {"status": "critical", "checkedAt": "2026-08-27T00:00:00", "alerts": [], "deployment": {}}
                    )
                self.assertEqual(result["error"], f"monitoring_webhook_http_{code}")
                self.assertNotIn(SECRET_TEXT, repr(result))
                self.assertTrue(stream.closed)

            with self.subTest(provider="restore-runner", code=code):
                error, stream = tracking_http_error(code)
                with (
                    mock.patch.object(backend, "SUPABASE_URL", "https://source-project.supabase.co"),
                    mock.patch.object(backend, "EDOC_RESTORE_DRILL_ENDPOINT", "https://restore.example.test/run"),
                    mock.patch.object(backend, "EDOC_RESTORE_DRILL_TOKEN", "restore-secret"),
                    mock.patch.object(backend, "_urlopen_no_redirect", side_effect=error),
                    mock.patch.object(backend, "supabase_insert", side_effect=lambda _table, row: row),
                ):
                    result = backend.supabase_backup_restore_drill({})
                self.assertEqual(result["error_code"], f"restore_runner_http_{code}")
                self.assertNotIn(SECRET_TEXT, repr(result))
                self.assertTrue(stream.closed)


if __name__ == "__main__":
    unittest.main()
