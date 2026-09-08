from __future__ import annotations

import io
import json
import base64
from contextlib import ExitStack
import unittest
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

from pypdf import PdfReader

import backend
from tests import test_official_document_workflow as workflow_fixture
from tests import test_backend_security_atomic as atomic_fixture


class ComposeOutputBackendTest(unittest.TestCase):
    def setUp(self):
        self.fixture = workflow_fixture.OfficialDocumentWorkflowTestCase()
        self.fixture.setUp()
        self.conn = self.fixture.conn
        self.session = self.fixture.login_session("sales-assistant@suiyuecare.com")

    def tearDown(self):
        self.fixture.tearDown()

    def payload(self, **overrides):
        return {
            "id": "OD-COMPOSE-OUTPUT-TEST", "source_type": "blank_editor", "company_id": "CO-001",
            "document_type": "outgoing_official_document", "output_mode": "electronic",
            "title": "去識別化公文輸出測試", "subject": "檢送測試資料一份，請查照。",
            "description": "本文件不含真實個資，僅供隔離測試使用。", "recipient": "測試機關",
            "document_category": "主管機關 申請或回覆文件（與 費用、法令無關）",
            "submit": False, "dispatch_method": "email_by_general_affairs", **overrides,
        }

    def create(self, **overrides):
        return backend.create_official_document(self.conn, self.payload(**overrides), self.session)

    def test_default_date_and_edit_keep_the_allocated_number_and_regenerate_pdf(self):
        draft = self.create()
        self.assertEqual(draft["dispatch_date"], datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d"))
        original_number = draft["dispatch_no"]
        edited = backend.update_official_document_correction(self.conn, draft["id"], {
            "dispatch_date": "2026-12-11", "metadata": {"dispatch_no": "不可改號"},
        }, self.session)
        self.assertEqual(edited["dispatch_date"], "2026-12-11")
        self.assertEqual(edited["dispatch_no"], original_number)
        source = backend.official_latest_source_file(self.conn, edited)
        _, data = backend.read_file_object_bytes(self.conn, source["file_object_id"])
        text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)
        self.assertIn("115年12月11日", text)
        self.assertIn(original_number, text)
        self.assertNotIn("不可改號", text)
        self.assertEqual(len([f for f in edited["files"] if f["file_type"] == "generated_pdf"]), 2)

    def test_electronic_full_approval_never_reads_seals_and_releases_downloadable_file(self):
        with mock.patch.object(backend, "validate_official_document_seal", side_effect=AssertionError("electronic must not read seal")), mock.patch.object(
            backend, "auto_stamp_official_document", side_effect=AssertionError("electronic must not stamp")
        ):
            detail = self.create(submit=True)
            self.assertFalse(detail["requires_stamp"])
            self.assertEqual(detail["current_status"], "pending_applicant_manager")
            self.assertEqual([s["step_key"] for s in detail["approval_steps"]], [
                "applicant_manager", "department_head", "admin_director", "general_affairs_review", "applicant_confirm",
            ])
            approved = self.fixture.approve_until_after_stamp(detail)
        self.assertEqual(approved["current_status"], "pending_general_affairs_dispatch")
        self.assertTrue(approved["stamped_file_id"])
        self.assertFalse([f for f in approved["files"] if f["file_type"] == "stamped_pdf"])
        final_file = next(f for f in approved["files"] if f["id"] == approved["stamped_file_id"])
        self.assertEqual(final_file["file_type"], "generated_pdf")
        package = approved["application_package"]
        self.assertEqual(package["output_mode"], "electronic")
        self.assertEqual(package["final_file"]["id"], final_file["id"])
        self.assertTrue(package["summary"]["has_final_pdf"])
        self.assertFalse(package["summary"]["has_stamped_pdf"])
        notification = backend.official_dispatch_route_notification_payload(self.conn, approved, approved["dispatch_record"])
        self.assertIn("電子公文已核准", notification["body"])
        self.assertNotIn("已用印", notification["body"])
        for step in approved["approval_steps"]:
            actor = self.fixture.session_for_user_id(step["approver_user_id"])
            backend.official_document_download_file(self.conn, approved["id"], final_file["id"], actor)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM official_document_dispatch_records WHERE document_id=?", (approved["id"],)).fetchone()[0], 1)
        ga_step = next(step for step in approved["approval_steps"] if step["step_key"] == "general_affairs_review")
        ga = self.fixture.session_for_user_id(ga_step["approver_user_id"])
        proof = backend.build_official_pdf({"subject": "隔離寄發證明", "body": "此為測試，不連線寄送。"})
        backend.upload_official_dispatch_proof_file(self.conn, approved["id"], {
            "file_name": "synthetic-proof.pdf", "file_mime_type": "application/pdf",
            "content_base64": base64.b64encode(proof).decode("ascii"),
        }, ga)
        dispatched = backend.complete_official_dispatch(self.conn, approved["id"], {
            "dispatch_date": "2026-09-08", "recipient": "測試機關", "dispatch_note": "隔離測試已人工寄送，不呼叫外部provider",
        }, ga)
        self.assertEqual(dispatched["current_status"], "dispatched")
        completed = backend.confirm_official_document(self.conn, approved["id"], {"comment": "確認測試收件"}, self.session)
        self.assertEqual(completed["current_status"], "closed")

    def test_uploaded_pdf_and_untrusted_metadata_cannot_bypass_seal_requirements(self):
        with self.assertRaisesRegex(PermissionError, "electronic_output_forbidden"):
            backend.official_output_fields(self.payload(source_type="uploaded_pdf", metadata={"source": "compose_form"}))
        with self.assertRaisesRegex(PermissionError, "stamp_required"):
            self.create(output_mode="physical", requires_stamp=False)
        with self.assertRaisesRegex(PermissionError, "stamp_required"):
            self.create(output_mode="physical", requires_stamp=False, metadata={"output_mode": "electronic"})
        with self.assertRaisesRegex(ValueError, "category_required"):
            self.create(document_category="")

    def test_physical_draft_still_requires_seal_and_date_validation_is_strict(self):
        draft = self.create(output_mode="physical")
        self.assertTrue(draft["requires_stamp"])
        with self.assertRaisesRegex(ValueError, "seal_required"):
            backend.submit_official_document(self.conn, draft["id"], {}, self.session)
        for date in ("", "2026-02-30", "2026-1-1", "yesterday"):
            with self.subTest(date=date), self.assertRaisesRegex(ValueError, "official_dispatch_date"):
                backend.official_compose_dispatch_date({"dispatch_date": date})

    def test_mode_switch_clears_positions_but_is_locked_after_submission(self):
        draft = self.create(output_mode="physical")
        electronic = backend.update_official_document_correction(self.conn, draft["id"], {"output_mode": "electronic"}, self.session)
        self.assertEqual(electronic["output_mode"], "electronic")
        self.assertFalse(electronic["requires_stamp"])
        submitted = backend.submit_official_document(self.conn, draft["id"], {}, self.session)
        with self.assertRaisesRegex(ValueError, "correction_locked"):
            backend.update_official_document_correction(self.conn, submitted["id"], {"output_mode": "physical"}, self.session)
        with self.assertRaisesRegex(ValueError, "output_mode_locked"):
            backend.official_output_fields({"output_mode": "physical"}, {**submitted, "current_status": "rejected"})

    def test_rejected_electronic_letter_restarts_approval_and_locks_corrected_source(self):
        detail = self.create(submit=True)
        first = next(step for step in detail["approval_steps"] if step["step_key"] == detail["current_step"])
        approver = self.fixture.session_for_user_id(first["approver_user_id"])
        for file in detail["files"]:
            if file["file_type"] == "generated_pdf":
                backend.official_document_download_file(self.conn, detail["id"], file["id"], approver)
        rejected = backend.reject_official_document(self.conn, detail["id"], {
            "expected_step_id": first["id"], "comment": "請修改發文日期", "reason_category": "內容補正",
            "missing_items": ["日期"], "review_acknowledgements": {
                "original_reviewed": True, "edited_version_reviewed": True, "attachments_reviewed": True,
            },
        }, approver)
        original_hash = backend.parse_json_field(backend.official_document_row(self.conn, detail["id"])["metadata_json"])["electronic_output"]["source_sha256"]
        backend.update_official_document_correction(self.conn, detail["id"], {"dispatch_date": "2026-12-11"}, self.session)
        resubmitted = backend.resubmit_official_document(self.conn, detail["id"], {}, self.session)
        self.assertEqual(resubmitted["current_step"], "applicant_manager")
        self.assertEqual(resubmitted["dispatch_no"], detail["dispatch_no"])
        new_lock = backend.parse_json_field(backend.official_document_row(self.conn, detail["id"])["metadata_json"])["electronic_output"]
        self.assertNotEqual(new_lock["source_sha256"], original_hash)
        approved = self.fixture.approve_until_after_stamp(resubmitted)
        self.assertEqual(approved["stamped_file_id"], new_lock["source_file_id"])
        self.assertEqual(approved["current_status"], "pending_general_affairs_dispatch")

    def test_source_lock_tampering_prevents_final_release(self):
        detail = self.create(submit=True)
        document = backend.official_document_row(self.conn, detail["id"])
        metadata = backend.parse_json_field(document["metadata_json"])
        metadata["electronic_output"]["source_sha256"] = "0" * 64
        self.conn.execute("UPDATE official_documents SET metadata_json=? WHERE id=?", (json.dumps(metadata), detail["id"]))
        with self.assertRaisesRegex(ValueError, "electronic_source_invalid"):
            self.fixture.approve_until_after_stamp(detail)
        self.assertIsNone(backend.official_document_row(self.conn, detail["id"])["stamped_file_id"])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM official_document_dispatch_records WHERE document_id=?", (detail["id"],)).fetchone()[0], 0)

    def test_retry_keeps_document_number_and_does_not_duplicate_files(self):
        first = self.create()
        second = self.create(subject="重試不得覆寫", dispatch_date="2026-12-11")
        self.assertEqual(second["dispatch_no"], first["dispatch_no"])
        self.assertEqual(second["subject"], first["subject"])
        self.assertTrue(second["create_replayed"])
        self.assertNotIn("create_replayed", backend.official_document_row(self.conn, first["id"]))
        self.assertEqual(len(second["files"]), 1)
        other = self.conn.execute("SELECT id FROM users WHERE id <> ? AND company_id = 'CO-001' LIMIT 1", (self.session["user"]["id"],)).fetchone()
        self.assertIsNotNone(other)
        other_session = self.fixture.session_for_user_id(other["id"])
        other_session["permissions"].append("official_documents.compose")
        with self.assertRaisesRegex(PermissionError, "create_id_conflict"):
            backend.create_official_document(self.conn, self.payload(), other_session)

    def test_contact_block_is_wider_but_stays_inside_a4(self):
        info = backend.official_pdf_info({
            "contact_email": "document.operator@example.test", "subject": "測試", "body": "去識別化測試",
        }, "歲悅正式函")
        layout = backend.paginate_official_pdf(info)
        lines = layout["header"]["contact_lines"]
        self.assertIn("電子信箱：document.operator@example.test", lines)
        self.assertLess(302.85 + 250, backend.A4_WIDTH_PT - 40)

    def test_missing_number_fails_before_pdf_in_both_create_backends(self):
        original_row = backend.official_document_row
        def missing_number(*args):
            return {**original_row(*args), "dispatch_no": None}
        with mock.patch.object(backend, "official_document_row", side_effect=missing_number), mock.patch.object(backend, "ensure_official_generated_pdf") as generate:
            with self.assertRaisesRegex(ValueError, "numbering_unavailable"):
                self.create()
            generate.assert_not_called()
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(backend, "supabase_get", return_value=None))
            stack.enter_context(mock.patch.object(backend, "supabase_official_company_row", return_value={"id": "CO-001", "name": "測試公司"}))
            stack.enter_context(mock.patch.object(backend, "supabase_insert", side_effect=lambda _table, row: row))
            generate = stack.enter_context(mock.patch.object(backend, "supabase_ensure_official_generated_pdf"))
            with self.assertRaisesRegex(ValueError, "numbering_unavailable"):
                backend.supabase_create_official_document(self.payload(id="OD-MISSING-PG-NUMBER"), self.session)
            generate.assert_not_called()

    def test_legacy_numbers_are_readable_but_not_accepted_as_new_allocations(self):
        legacy = {"source_type": "blank_editor", "metadata_json": {"extra": {"dispatch_no": "舊測試字第1140101001號"}}}
        self.assertEqual(backend.require_official_compose_number(legacy, allow_legacy=True), "舊測試字第1140101001號")
        for record, allow_legacy in ((legacy, False), ({"source_type": "blank_editor", "id": "OD-LEGACY-NO-NUMBER"}, True)):
            with self.assertRaisesRegex(ValueError, "numbering_unavailable"):
                backend.require_official_compose_number(record, allow_legacy=allow_legacy)
        self.assertNotIn("dispatch_no", legacy)
        self.assertEqual(backend.api_value_error_status("official_document_numbering_unavailable"), 503)

    def test_supabase_electronic_submit_payload_locks_generated_source_without_stamp(self):
        fixture = atomic_fixture.BackendSecurityAndAtomicityTestCase()
        for status in ("draft", "rejected"):
            with self.subTest(status=status):
                document, user, _, _, step, snapshot = fixture._submission_fixture(status)
                document.update(source_type="blank_editor", document_type="outgoing_official_document", output_mode="electronic", requires_stamp=False)
                source = {"id": f"FILE-SOURCE-{status}", "file_hash": "a" * 64, "file_type": "generated_pdf"}
                captured = {}
                def rpc(method, endpoint, body):
                    self.assertEqual((method, endpoint), ("POST", "rpc/edoc_commit_official_document_submission"))
                    request = body["p_request"]
                    captured.update(request)
                    return {"committed": True, "document_id": document["id"], "operation_id": request["operation_id"],
                            "first_step_id": request["first_step_id"], "current_status": request["first_status"],
                            "current_step": request["first_step_key"], "workflow_generation": request["workflow_generation"]}
                with ExitStack() as stack:
                    mocks = {
                        "supabase_official_session_user": user, "supabase_official_document_row": document,
                        "official_seal_context_from_document": {"approval_route_code": "A"}, "is_production": False,
                        "supabase_lock_official_editor_submission": None, "supabase_ensure_official_generated_pdf": source,
                        "supabase_user_by_id": user, "supabase_official_document_detail": document,
                        "supabase_plan_official_workflow_submission": {"workflow_generation": step["workflow_generation"],
                            "supersede_generation": 1 if status == "rejected" else 0, "steps": [step], "actor_snapshots": [snapshot]},
                    }
                    for name, value in mocks.items():
                        stack.enter_context(mock.patch.object(backend, name, return_value=value))
                    for name in ("require_official_creation_company", "supabase_assert_official_document_uploads_av_clean", "supabase_create_and_deliver_notification"):
                        stack.enter_context(mock.patch.object(backend, name))
                    for name in ("supabase_official_document_stamp_request", "supabase_plan_official_stamp_seal_versions", "supabase_insert", "supabase_patch"):
                        stack.enter_context(mock.patch.object(backend, name, side_effect=AssertionError(f"no independent mutation or seal read: {name}")))
                    stack.enter_context(mock.patch.object(backend, "supabase_request", side_effect=rpc))
                    backend.supabase_submit_official_document(document["id"], {}, {"user": user})
                evidence = captured["submit_log"]["decision_evidence_json"]
                self.assertEqual(evidence["output_mode"], "electronic")
                self.assertEqual((evidence["source_file_id"], evidence["source_sha256"]), (source["id"], source["file_hash"]))
                self.assertEqual(evidence["stamp_request_id"], "")
                self.assertNotIn("id", captured["stamp_request"])
                self.assertEqual(captured["stamp_positions"], [])
                self.assertEqual(captured["resubmit"]["enabled"], status == "rejected")
                if status == "rejected":
                    self.assertEqual(captured["resubmit"]["log"]["decision_evidence_json"]["source_file_id"], source["id"])


if __name__ == "__main__":
    unittest.main()
