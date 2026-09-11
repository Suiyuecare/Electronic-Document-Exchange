from __future__ import annotations
import base64
import copy
import unittest
import uuid
from unittest import mock
import backend
from tests import test_compose_output_backend as fixture


class ComposeResilienceTest(unittest.TestCase):
    setUp = fixture.ComposeOutputBackendTest.setUp
    tearDown = fixture.ComposeOutputBackendTest.tearDown
    payload = fixture.ComposeOutputBackendTest.payload
    create = fixture.ComposeOutputBackendTest.create
    def snapshot(self, **values):
        return {"schemaVersion": 2, "userId": self.session["user"]["id"], "companyId": self.session["user"]["company_id"],
                "values": {"#documentPurpose": "未完成的隔離測試用途", **values}}

    def test_incomplete_cloud_draft_does_not_allocate_number_or_create_official_case(self):
        document_count = self.conn.execute("SELECT count(*) FROM official_documents").fetchone()[0]
        key = "OD-" + str(uuid.uuid4())
        result = backend.save_compose_draft(self.conn, key, {"snapshot": self.snapshot(), "expected_revision": 0}, self.session)
        self.assertEqual(result["revision"], 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM official_documents").fetchone()[0], document_count)
        self.assertEqual(backend.list_compose_drafts(self.conn, self.session)[0]["id"], key)

    def test_cloud_draft_replay_and_stale_device_are_not_silent_overwrites(self):
        key = "OD-" + str(uuid.uuid4())
        first = {"snapshot": self.snapshot(), "expected_revision": 0}
        backend.save_compose_draft(self.conn, key, first, self.session)
        replay = backend.save_compose_draft(self.conn, key, first, self.session)
        self.assertEqual(replay["revision"], 1)
        backend.save_compose_draft(self.conn, key, {"snapshot": self.snapshot(**{"#subject": "裝置 A"}), "expected_revision": 1}, self.session)
        with self.assertRaisesRegex(ValueError, "compose_draft_revision_conflict"):
            backend.save_compose_draft(self.conn, key, {"snapshot": self.snapshot(**{"#subject": "装置 B"}), "expected_revision": 1}, self.session)
        self.assertEqual(backend.list_compose_drafts(self.conn, self.session)[0]["snapshot"]["values"]["#subject"], "裝置 A")

    def test_cloud_draft_rejects_cross_user_company_and_unknown_fields(self):
        key = "OD-" + str(uuid.uuid4())
        snapshot = self.snapshot()
        snapshot["companyId"] = "CO-002"
        with self.assertRaisesRegex(PermissionError, "scope_forbidden"):
            backend.save_compose_draft(self.conn, key, {"snapshot": snapshot, "expected_revision": 0}, self.session)
        with self.assertRaisesRegex(ValueError, "snapshot_invalid"):
            backend.save_compose_draft(self.conn, key, {"snapshot": self.snapshot(**{"#privateFileUrl": "private"}), "expected_revision": 0}, self.session)

    def test_archived_cloud_draft_disappears_from_recovery_list(self):
        key = "OD-" + str(uuid.uuid4())
        payload = {"snapshot": self.snapshot(), "expected_revision": 0}
        backend.save_compose_draft(self.conn, key, payload, self.session)
        backend.save_compose_draft(self.conn, key, {**payload, "expected_revision": 1, "archived": True}, self.session)
        self.assertFalse(backend.list_compose_drafts(self.conn, self.session))

    def test_compose_content_revision_stale_patch_and_submit_rejected(self):
        draft = self.create(metadata={"source": "compose_form"})
        self.assertEqual(draft["content_revision"], 0)
        with self.assertRaisesRegex(ValueError, "revision_required"):
            backend.update_official_document_correction(self.conn, draft["id"], {"subject": "無版本"}, self.session)
        updated = backend.update_official_document_correction(self.conn, draft["id"], {"subject": "裝置一已修改", "expected_content_revision": 0}, self.session)
        self.assertEqual(updated["content_revision"], 1)
        self.assertEqual(updated["dispatch_no"], draft["dispatch_no"])
        for operation in (backend.update_official_document_correction, backend.submit_official_document):
            with self.assertRaisesRegex(ValueError, "revision_conflict"):
                operation(self.conn, draft["id"], {"subject": "裝置二舊文字", "expected_content_revision": 0}, self.session)
        self.assertEqual(backend.official_document_row(self.conn, draft["id"])["subject"], "裝置一已修改")
        self.assertEqual(backend.api_value_error_status("compose_content_revision_conflict"), 409)

    def test_attachment_response_loss_replays_same_file_and_refuses_different_bytes(self):
        draft = self.create()
        pdf = backend.build_official_pdf({"subject": "隔離附件", "body": "測試用"})
        payload = {"file_name": "fixture.pdf", "file_mime_type": "application/pdf", "content_base64": base64.b64encode(pdf).decode(), "upload_id": "fixture-upload-0000001"}
        with mock.patch.object(backend, "scan_official_upload_bytes", return_value=("clean", "fixture")):
            first = backend.upload_official_document_attachment(self.conn, draft["id"], payload, self.session)
            second = backend.upload_official_document_attachment(self.conn, draft["id"], payload, self.session)
            self.assertEqual(first["file"]["id"], second["file"]["id"])
            self.assertTrue(second["upload_replayed"])
            self.assertEqual(self.conn.execute("SELECT count(*) FROM official_document_files WHERE document_id=? AND file_type='attachment'", (draft["id"],)).fetchone()[0], 1)
            with self.assertRaisesRegex(ValueError, "upload_id_conflict"):
                backend.upload_official_document_attachment(self.conn, draft["id"], {**payload, "file_name": "changed.pdf"}, self.session)

    def test_submission_rechecks_content_revision_after_workflow_resolution(self):
        draft = self.create(metadata={"source": "compose_form"})
        original = backend.official_workflow_steps_for_document
        def competing_edit(conn, document):
            steps = original(conn, document)
            conn.execute("UPDATE official_documents SET content_revision=content_revision+1,subject=? WHERE id=?", ("競爭更新", document["id"]))
            return steps
        with mock.patch.object(backend, "official_workflow_steps_for_document", side_effect=competing_edit), mock.patch.object(
            backend, "assert_official_document_uploads_av_clean",
        ) as scan:
            with self.assertRaisesRegex(ValueError, "compose_content_revision_conflict"):
                backend.submit_official_document(self.conn, draft["id"], {"expected_content_revision": 0}, self.session)
        scan.assert_not_called()
        self.assertEqual(backend.official_document_row(self.conn, draft["id"])["current_status"], "draft")


if __name__ == "__main__":
    unittest.main()
