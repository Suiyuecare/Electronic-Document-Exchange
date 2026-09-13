"""Synthetic same-tenant V2 workflow; never contacts production services."""
import unittest

import backend
from tests import test_five_account_editor_workflow as five_accounts


class EditorCrossCompanyLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.fixture = five_accounts.FiveAccountEditorWorkflowTestCase()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.conn = self.fixture.conn
        tenant = "00000000-0000-0000-0000-000000000001"
        self.conn.execute("UPDATE companies SET finance_tenant_id=? WHERE id IN ('CO-001','CO-002')", (tenant,))
        # All people retain their actual Finance home company and relationships.
        # Only the application and synthetic seal belong to the selected CO-001.
        self.conn.execute("UPDATE users SET company_id='CO-002', company_name='Isolated home company', finance_tenant_id=?, account_source='finance', finance_employee_id=id", (tenant,))
        self.conn.execute("UPDATE users SET manager_employee_id='USR-003', approval_manager_employee_id='USR-003', manager_email=NULL, approval_manager_email=NULL WHERE id LIKE 'E2E-APPLICANT-%'")
        self.applicant_id = self.fixture.applicant_ids[0]
        self.applicant = self.fixture._session_for_user_id(self.applicant_id)

    def submitted_case(self):
        f = self.fixture
        draft = backend.create_official_editor_draft(self.conn, {
            "company_id": "CO-001", "applicant_department_id": "DEP-001",
            "title": "Isolated cross-company case", "subject": "Isolated cross-company case",
            "request_reason": "Synthetic lifecycle validation", "document_category": "採購合約",
            "dispatch_method": "no_dispatch_required",
        }, self.applicant)
        doc_id = draft["document_id"]
        data = f._a4_pdf_bytes(301)
        digest = backend.sha256_bytes(data)
        intent = backend.create_official_editor_upload_intent(self.conn, doc_id, {
            "asset_kind": "source_pdf", "file_name": "synthetic.pdf", "mime_type": "application/pdf",
            "size_bytes": len(data), "sha256": digest,
        }, self.applicant)
        backend.store_official_editor_local_upload(self.conn, doc_id, intent["upload_id"], data, self.applicant, "application/pdf")
        result = backend.finalize_official_editor_upload(self.conn, doc_id, intent["upload_id"], {"sha256": digest}, self.applicant)
        revision = result["editor_revision"]
        saved = backend.save_official_editor_state(self.conn, doc_id, {
            "revisionNo": revision["revisionNo"], "baseManifestSha256": revision["manifestSha256"],
            "state": f._add_editor_elements(revision, 301),
        }, self.applicant)
        prepared = backend.preflight_official_editor(self.conn, doc_id, {
            "editorRevisionId": saved["id"], "manifestSha256": saved["manifestSha256"],
        }, self.applicant)
        detail = backend.submit_official_document(self.conn, doc_id, {
            key: prepared[key] for key in ("editorRevisionId", "manifestSha256", "preparedFileId", "preparedSha256")
        }, self.applicant)
        self.assertEqual(detail["company_id"], "CO-001")
        self.assertEqual(detail["applicant_department_id"], "DEP-001")
        self.assertEqual(detail["approval_steps"][0]["approver_user_id"], "USR-003")
        return detail

    def test_selected_company_full_approval_stamp_receipt_and_private_download(self):
        detail = self.submitted_case()
        detail = self.fixture._approve_and_stamp(detail)
        stamped = next(file for file in detail["files"] if file["file_type"] == "stamped_pdf")
        participants = {self.applicant_id, *(step["approver_user_id"] for step in detail["approval_steps"])}
        for participant_id in participants:
            session = self.fixture._session_for_user_id(participant_id)
            self.assertEqual(session["user"]["company_id"], "CO-002")
            self.assertTrue(backend.official_document_detail(self.conn, detail["id"], session)["can_download"])
            _, _, data = backend.official_document_download_file(self.conn, detail["id"], stamped["id"], session, "127.0.0.1", "synthetic-selected-company")
            self.assertEqual(backend.sha256_bytes(data), stamped["file_hash"])
        outsider = self.fixture._session_for_user_id(self.fixture.applicant_ids[1])
        with self.assertRaises(PermissionError):
            backend.official_document_detail(self.conn, detail["id"], outsider)
        with self.assertRaises(PermissionError):
            backend.official_document_download_file(self.conn, detail["id"], stamped["id"], outsider, "127.0.0.1", "synthetic-outsider")
        closed = backend.confirm_official_document(self.conn, detail["id"], {"comment": "Synthetic receipt"}, self.applicant)
        self.assertEqual(closed["current_status"], "closed")
        notifications = self.conn.execute("SELECT target_user_id,target_company_id FROM notifications WHERE source=?", (detail["id"],)).fetchall()
        self.assertGreaterEqual(len(notifications), 5)
        self.assertTrue(all(row["target_user_id"] in participants and row["target_company_id"] == "CO-002" for row in notifications))

    def test_selected_company_rejection_notifies_actual_applicant_home_inbox(self):
        detail = self.submitted_case()
        step = next(step for step in detail["approval_steps"] if step["step_key"] == detail["current_step"])
        session = self.fixture._session_for_user_id(step["approver_user_id"])
        for file in detail["files"]:
            if file["file_type"] in {"original_pdf", "prepared_pdf", "attachment"}:
                backend.official_document_download_file(self.conn, detail["id"], file["id"], session, "127.0.0.1", "synthetic-rejection-review")
        rejected = backend.reject_official_document(self.conn, detail["id"], {
            "expected_step_id": step["id"], "comment": "Synthetic correction requested",
            "prepared_sha256": detail["stamp_request"]["prepared_sha256"],
            "manifest_sha256": detail["stamp_request"]["editor_manifest_sha256"],
            "reason_category": "content", "missing_items": ["Synthetic correction"],
            "review_acknowledgements": {"original_reviewed": True, "edited_version_reviewed": True, "attachments_reviewed": True},
        }, session)
        self.assertEqual(rejected["current_status"], "rejected")
        target = self.conn.execute("SELECT target_user_id,target_company_id FROM notifications WHERE source=? ORDER BY rowid DESC LIMIT 1", (detail["id"],)).fetchone()
        self.assertEqual(tuple(target), (self.applicant_id, "CO-002"))

    def test_notification_exception_never_admits_foreign_tenant_or_legacy_case(self):
        actor = dict(self.applicant["user"])
        v2 = {"company_id": "CO-001", "source_type": "uploaded_pdf", "metadata_json": '{"pdf_editor_v2":true}'}
        self.assertEqual(backend.official_document_notification_target(actor, v2, self.conn)["target_company_id"], "CO-002")
        actor["finance_tenant_id"] = "00000000-0000-0000-0000-000000000009"
        with self.assertRaises(PermissionError):
            backend.official_document_notification_target(actor, v2, self.conn)
        with self.assertRaisesRegex(PermissionError, "notification_target_company_forbidden"):
            backend.official_document_notification_target(self.applicant["user"], {**v2, "metadata_json": "{}"}, self.conn)
