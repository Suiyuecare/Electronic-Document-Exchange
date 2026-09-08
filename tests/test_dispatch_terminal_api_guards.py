from __future__ import annotations

import unittest
import sqlite3
from contextlib import ExitStack
from urllib.parse import parse_qs
from unittest import mock

import backend


class DispatchTerminalApiGuardsTest(unittest.TestCase):
    """Supabase transport doubles verify guards without touching hosted data."""

    def official_fixture(self, stack, record):
        user = {"id": "TEST-GA", "company_id": "TEST-CO"}
        document = {"id": "TEST-OD", "company_id": "TEST-CO", "dispatch_method": "email_by_general_affairs"}
        steps = [{"step_key": "general_affairs_review", "approver_user_id": user["id"]}]
        for name, value in (
            ("supabase_official_session_user", user),
            ("supabase_official_document_row", document),
            ("supabase_official_document_steps", steps),
            ("supabase_official_document_actor_snapshots", []),
            ("supabase_official_dispatch_record", record),
        ):
            stack.enter_context(mock.patch.object(backend, name, return_value=value))
        return {"user": user, "permissions": ["official_documents.all_records"]}

    @staticmethod
    def record(status):
        return {"id": "TEST-REC", "dispatch_owner_type": "general_affairs", "dispatch_owner_user_id": "TEST-GA", "dispatch_status": status, "completed_at": "2026-09-09 00:00:00" if status == "dispatched" else ""}

    def test_completed_supabase_dispatch_rejects_before_any_write_or_upload(self):
        for operation in (backend.supabase_update_official_dispatch_record, backend.supabase_upload_official_dispatch_proof_file):
            with self.subTest(operation=operation.__name__), ExitStack() as stack:
                session = self.official_fixture(stack, self.record("dispatched"))
                request = stack.enter_context(mock.patch.object(backend, "supabase_request"))
                upload = stack.enter_context(mock.patch.object(backend, "supabase_store_file_object"))
                with self.assertRaisesRegex(ValueError, "^official_dispatch_record_locked$"):
                    operation("TEST-OD", {"recipient": "不可覆寫", "content_base64": "cGRm"}, session)
                request.assert_not_called()
                upload.assert_not_called()

    def test_pending_metadata_patch_is_conditional_and_detects_completion_race(self):
        for changed in ([], [{"id": "TEST-REC"}]):
            with self.subTest(changed=bool(changed)), ExitStack() as stack:
                session = self.official_fixture(stack, self.record("pending"))
                request = stack.enter_context(mock.patch.object(backend, "supabase_request", return_value=changed))
                log = stack.enter_context(mock.patch.object(backend, "supabase_insert_official_log"))
                if changed:
                    backend.supabase_update_official_dispatch_record("TEST-OD", {"recipient": "隔離收文單位"}, session)
                    log.assert_called_once()
                else:
                    with self.assertRaisesRegex(ValueError, "^official_dispatch_record_locked$"):
                        backend.supabase_update_official_dispatch_record("TEST-OD", {"recipient": "隔離收文單位"}, session)
                    log.assert_not_called()
                method, path, payload = request.call_args.args
                self.assertEqual(method, "PATCH")
                self.assertEqual(path.split("?")[0], "official_document_dispatch_records")
                self.assertEqual(parse_qs(path.split("?", 1)[1]), {"id": ["eq.TEST-REC"], "dispatch_status": ["eq.pending"], "or": ["(completed_at.is.null,completed_at.eq.)"]})
                self.assertEqual(payload["recipient"], "隔離收文單位")

    def test_supabase_proof_binding_detects_completion_during_file_upload(self):
        for changed in ([], [{"id": "TEST-REC"}]):
            with self.subTest(changed=bool(changed)), ExitStack() as stack:
                session = self.official_fixture(stack, self.record("pending"))
                for name, value in (
                    ("scan_official_upload_bytes", ("clean", "isolated-fixture")),
                    ("supabase_store_file_object", {"id": "TEST-OBJECT"}),
                    ("supabase_persist_file_object_scan_result", {"id": "TEST-OBJECT"}),
                    ("supabase_insert_official_document_file", {"id": "TEST-PROOF", "file_hash": "test-hash"}),
                    ("official_file_metadata", {}),
                ):
                    stack.enter_context(mock.patch.object(backend, name, return_value=value))
                request = stack.enter_context(mock.patch.object(backend, "supabase_request", return_value=changed))
                patch = stack.enter_context(mock.patch.object(backend, "supabase_patch"))
                log = stack.enter_context(mock.patch.object(backend, "supabase_insert_official_log"))
                if changed:
                    backend.supabase_upload_official_dispatch_proof_file("TEST-OD", {"content_base64": "cGRm"}, session)
                    log.assert_called_once()
                else:
                    with self.assertRaisesRegex(ValueError, "^official_dispatch_record_locked$"):
                        backend.supabase_upload_official_dispatch_proof_file("TEST-OD", {"content_base64": "cGRm"}, session)
                    log.assert_not_called()
                patch.assert_not_called()
                method, path, payload = request.call_args.args
                self.assertEqual(method, "PATCH")
                self.assertEqual(path.split("?", 1)[0], "official_document_dispatch_records")
                self.assertEqual(parse_qs(path.split("?", 1)[1]), {"id": ["eq.TEST-REC"], "dispatch_status": ["eq.pending"], "or": ["(completed_at.is.null,completed_at.eq.)"]})
                self.assertEqual(payload["proof_file_id"], "TEST-PROOF")

    def test_sqlite_proof_binding_preserves_completed_record_on_stale_read(self):
        for concurrent_completion in (False, True):
            with self.subTest(concurrent_completion=concurrent_completion), ExitStack() as stack:
                conn = sqlite3.connect(":memory:")
                stack.callback(conn.close)
                conn.execute("CREATE TABLE file_objects(id TEXT, mime_type TEXT)")
                conn.execute("CREATE TABLE official_document_dispatch_records(id TEXT, dispatch_status TEXT, completed_at TEXT, proof_file_id TEXT, updated_at TEXT)")
                conn.execute("INSERT INTO official_document_dispatch_records VALUES ('TEST-REC', 'pending', '', 'EXISTING-PROOF', '')")
                user = {"id": "TEST-GA", "company_id": "TEST-CO"}
                document = {"id": "TEST-OD", "company_id": "TEST-CO", "dispatch_method": "email_by_general_affairs"}
                for name, value in (
                    ("official_session_user", user),
                    ("official_document_row", document),
                    ("official_document_steps", [{"step_key": "general_affairs_review", "approver_user_id": "TEST-GA"}]),
                    ("official_dispatch_record", self.record("pending")),
                    ("scan_official_upload_bytes", ("clean", "isolated-fixture")),
                    ("store_file_object", {"id": "TEST-OBJECT"}),
                    ("persist_file_object_scan_result", {"id": "TEST-OBJECT"}),
                    ("official_file_metadata", {}),
                ):
                    stack.enter_context(mock.patch.object(backend, name, return_value=value))

                def insert_file(*_args):
                    if concurrent_completion:
                        conn.execute("UPDATE official_document_dispatch_records SET dispatch_status='dispatched', completed_at='2026-09-09 00:00:00'")
                    return {"id": "NEW-PROOF", "file_hash": "test-hash"}

                stack.enter_context(mock.patch.object(backend, "insert_official_document_file", side_effect=insert_file))
                log = stack.enter_context(mock.patch.object(backend, "insert_official_log"))
                session = {"user": user, "permissions": ["official_documents.all_records"]}
                if concurrent_completion:
                    with self.assertRaisesRegex(ValueError, "^official_dispatch_record_locked$"):
                        backend.upload_official_dispatch_proof_file(conn, "TEST-OD", {"content_base64": "cGRm"}, session)
                    log.assert_not_called()
                else:
                    backend.upload_official_dispatch_proof_file(conn, "TEST-OD", {"content_base64": "cGRm"}, session)
                    log.assert_called_once()
                bound = conn.execute("SELECT proof_file_id FROM official_document_dispatch_records").fetchone()[0]
                self.assertEqual(bound, "EXISTING-PROOF" if concurrent_completion else "NEW-PROOF")

    def test_closed_supabase_internal_dispatch_rejects_before_insert(self):
        user = {"id": "TEST-RECIPIENT"}
        detail = {"status": "closed", "closed_at": "2026-09-09 00:00:00", "recipients": [{"recipient_user_id": user["id"], "action_required": True}]}
        with mock.patch.object(backend, "supabase_official_session_user", return_value=user), mock.patch.object(backend, "supabase_internal_dispatch_detail", return_value=detail), mock.patch.object(backend, "supabase_insert") as insert, mock.patch.object(backend, "supabase_store_file_object") as upload:
            with self.assertRaisesRegex(ValueError, "^internal_dispatch_closed$"):
                backend.supabase_reply_internal_dispatch("TEST-IDISP", {"reply_text": "不得重開案件"}, {"user": user})
            insert.assert_not_called()
            upload.assert_not_called()

    def test_internal_reply_completion_never_reopens_concurrently_closed_case(self):
        user = {"id": "TEST-RECIPIENT"}
        recipient = {"id": "TEST-R", "recipient_user_id": user["id"], "action_required": True, "status": "pending"}
        initial = {"status": "sent", "closed_at": "", "reply_required": True, "recipients": [recipient]}
        closed = {**initial, "status": "closed", "closed_at": "2026-09-09 00:00:00", "recipients": [{**recipient, "status": "replied"}]}
        with mock.patch.object(backend, "supabase_official_session_user", return_value=user), mock.patch.object(backend, "supabase_internal_dispatch_detail", side_effect=[initial, closed, closed]), mock.patch.object(backend, "supabase_insert", side_effect=lambda _table, row: row), mock.patch.object(backend, "supabase_patch") as patch, mock.patch.object(backend, "supabase_request", return_value=[]) as request, mock.patch.object(backend, "supabase_internal_dispatch_log"):
            result = backend.supabase_reply_internal_dispatch("TEST-IDISP", {"reply_text": "隔離回覆"}, {"user": user})
            self.assertEqual(result["status"], "closed")
            self.assertTrue(all(call.args[0] != "internal_dispatches" for call in patch.call_args_list))
            query = parse_qs(request.call_args.args[1].split("?", 1)[1])
            self.assertEqual(query, {"id": ["eq.TEST-IDISP"], "status": ["not.in.(closed,cancelled)"], "or": ["(closed_at.is.null,closed_at.eq.)"]})

    def test_terminal_errors_are_conflicts_not_500(self):
        for code in ("official_dispatch_record_locked", "internal_dispatch_closed"):
            self.assertEqual(backend.api_value_error_status(code), 409)
