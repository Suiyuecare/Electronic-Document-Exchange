"""Synthetic binding validation; no staff identity or production changes."""
import copy
import unittest
from unittest import mock
import backend
import official_handover_followup as followup
from tests import test_official_handover_store as fixture_module


class FollowupAuthorizationTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.HandoverStoreTest()
        if "linked_uploaded_pdf" in self._testMethodName:
            self.fixture.source_type = "uploaded_pdf"
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.conn = self.fixture.conn
        self.conn.execute("UPDATE users SET status='停用' WHERE id='APPLICANT-TEST'")
        self.document = backend.official_document_row(self.conn, self.fixture.document_id)
        self.fixture.propose(self.fixture.payload(kind="followup_owner", former="APPLICANT-TEST"))
        self.fixture.confirm()

    def test_only_exact_confirmed_owner_receives_separate_responsibility(self):
        binding = followup.load(backend, self.document, conn=self.conn, actor_id="SUCCESSOR-TEST")
        self.assertEqual("APPLICANT-TEST", binding["original_applicant_id"])
        self.assertIsNone(followup.load(backend, self.document, conn=self.conn, actor_id="CONFIRMER-TEST"))
        self.assertEqual(self.document, backend.official_document_row(self.conn, self.document["id"]))

    def test_stale_account_or_company_truth_revokes_binding_immediately(self):
        for sql, params in (
            ("UPDATE users SET status='停用' WHERE id=?", ("SUCCESSOR-TEST",)),
            ("UPDATE users SET status='啟用' WHERE id=?", ("APPLICANT-TEST",)),
            ("UPDATE users SET finance_tenant_id='OUTSIDE' WHERE id=?", ("SUCCESSOR-TEST",)),
            ("UPDATE companies SET status='inactive' WHERE id=?", (self.document["company_id"],)),
        ):
            with self.subTest(sql=sql):
                self.conn.execute("SAVEPOINT validation")
                self.conn.execute(sql, params)
                self.assertIsNone(followup.load(backend, self.document, conn=self.conn))
                self.conn.execute("ROLLBACK TO validation")
                self.conn.execute("RELEASE validation")

    def test_pending_rejected_or_mismatched_request_is_not_authority(self):
        for change in ("status='pending'", "status='rejected'", "successor_user_id='CONFIRMER-TEST'", "kind='pending_approver'"):
            with self.subTest(change=change):
                self.conn.execute("SAVEPOINT validation")
                self.conn.execute("UPDATE official_document_handovers SET " + change)
                self.assertIsNone(followup.load(backend, self.document, conn=self.conn))
                self.conn.execute("ROLLBACK TO validation")
                self.conn.execute("RELEASE validation")

    def test_hosted_reader_uses_identical_raw_server_records(self):
        def get(table, identity):
            row = self.conn.execute(f"SELECT * FROM {table} WHERE id=?", (identity,)).fetchone()
            return dict(row) if row else None
        binding = dict(self.conn.execute("SELECT * FROM official_document_followup_owners").fetchone())
        with mock.patch.object(backend, "supabase_get", side_effect=get), mock.patch.object(backend, "supabase_filter_rows", return_value=[binding]):
            hosted = followup.load(backend, self.document, actor_id="SUCCESSOR-TEST")
        self.assertEqual(followup.load(backend, self.document, conn=self.conn), hosted)

    def test_bound_owner_reads_original_but_cannot_edit_or_resubmit_it(self):
        user = dict(self.conn.execute("SELECT * FROM users WHERE id='SUCCESSOR-TEST'").fetchone())
        session = {"user": user, "permissions": []}
        self.conn.execute("UPDATE official_documents SET current_status='rejected' WHERE id=?", (self.document["id"],))
        detail = backend.official_document_detail(self.conn, self.document["id"], session)
        self.assertTrue(detail["can_download"])
        self.assertFalse(detail["can_correct"])
        self.assertFalse(detail["can_resubmit"])
        with self.assertRaises(PermissionError):
            backend.resubmit_official_document(self.conn, self.document["id"], {}, session)
        with self.assertRaises(PermissionError):
            backend.official_document_download_file(self.conn, self.document["id"], "ANY", self.fixture.confirmer_session)
        with mock.patch.object(backend, "assert_official_document_uploads_av_clean"), self.assertRaisesRegex(ValueError, "file_not_found"):
            backend.official_document_download_file(self.conn, self.document["id"], "ANY", session)

    def test_receipt_keeps_original_principal_and_records_actual_owner_and_handover(self):
        self.conn.execute("UPDATE official_document_approval_steps SET status='approved' WHERE document_id=? AND step_key<>'applicant_confirm'", (self.document["id"],))
        self.conn.execute("UPDATE official_documents SET current_status='stamped',current_step='applicant_confirm' WHERE id=?", (self.document["id"],))
        user = dict(self.conn.execute("SELECT * FROM users WHERE id='SUCCESSOR-TEST'").fetchone())
        session = {"user": user, "permissions": []}
        detail = backend.official_document_detail(self.conn, self.document["id"], session)
        self.assertTrue(detail["can_confirm"])
        backend.confirm_official_document(self.conn, self.document["id"], {}, session)
        backend.confirm_official_document(self.conn, self.document["id"], {}, session)
        row = dict(self.conn.execute("SELECT * FROM official_document_approval_steps WHERE id='S3'").fetchone())
        evidence = backend.parse_json_any(row["decision_evidence_json"], {})
        self.assertEqual("APPLICANT-TEST", row["approver_user_id"])
        self.assertEqual("SUCCESSOR-TEST", row["decision_actor_user_id"])
        self.assertEqual("APPLICANT-TEST", evidence["principal_actor_id"])
        self.assertEqual("HANDOVER-SQLITE-0001", evidence["followup_handover_id"])
        self.assertEqual(1, self.conn.execute("SELECT count(*) FROM official_document_approval_logs WHERE action='confirm'").fetchone()[0])
        self.assertEqual("APPLICANT-TEST", backend.official_document_row(self.conn, self.document["id"])["applicant_id"])

    def linked_service(self):
        self.conn.execute("UPDATE users SET unit='Synthetic unit' WHERE id='SUCCESSOR-TEST'")
        self.conn.execute("UPDATE official_documents SET current_status='rejected' WHERE id=?", (self.document["id"],))
        user = dict(self.conn.execute("SELECT * FROM users WHERE id='SUCCESSOR-TEST'").fetchone())
        return followup.LinkedApplication(backend, {"user": user, "permissions": ["official_documents.compose"]}, self.conn)

    def test_linked_new_case_is_idempotent_fresh_number_fileless_full_approval_required(self):
        service = self.linked_service()
        seed, before, _ = service.context(self.document["id"])
        payload = {"operation_id": "LINKED-CASE-TEST-0001", "expected_fingerprint": seed["expected_fingerprint"],
                   "id": self.document["id"], "dispatch_no": "FORGED", "applicant_id": "CONFIRMER-TEST", "submit": True}
        first = service.create(self.document["id"], payload)
        self.assertFalse(first["idempotent"])
        self.assertTrue(service.create(self.document["id"], payload)["idempotent"])
        new = backend.official_document_row(self.conn, first["document_id"])
        self.assertNotEqual(before["id"], new["id"])
        self.assertNotEqual(before["dispatch_no"], new["dispatch_no"])
        self.assertEqual("draft", new["current_status"])
        self.assertEqual("SUCCESSOR-TEST", new["applicant_id"])
        self.assertEqual([], backend.official_document_files(self.conn, new["id"]))
        self.assertEqual([], backend.official_document_steps(self.conn, new["id"]))
        self.assertIsNone(backend.official_document_stamp_request(self.conn, new["id"]))
        self.assertEqual(before, backend.official_document_row(self.conn, before["id"]))
        with self.assertRaisesRegex(ValueError, "operation_conflict"):
            service.create(before["id"], {**payload, "expected_fingerprint": "forged"})

    def test_linked_uploaded_pdf_starts_with_empty_editor_not_old_files_or_seals(self):
        service = self.linked_service()
        seed, _, _ = service.context(self.document["id"])
        result = service.create(self.document["id"], {"operation_id": "LINKED-PDF-TEST-0001", "expected_fingerprint": seed["expected_fingerprint"]})
        revision = backend._editor_latest_revision_row(self.conn, result["document_id"])
        state = backend.parse_json_any(revision["editor_state_json"], {})
        self.assertEqual([], state["sourceFiles"])
        self.assertEqual([], state["pages"])
        self.assertEqual([], state["elements"])
        self.assertEqual(1, state["revisionNo"])

    def test_linked_creation_stale_context_and_live_disabled_owner_fail_closed(self):
        service = self.linked_service()
        seed, _, _ = service.context(self.document["id"])
        payload = {"operation_id": "LINKED-STALE-TEST-0001", "expected_fingerprint": seed["expected_fingerprint"]}
        self.conn.execute("UPDATE official_documents SET content_revision=content_revision+1 WHERE id=?", (self.document["id"],))
        with self.assertRaisesRegex(ValueError, "version_conflict"):
            service.create(self.document["id"], payload)
        self.conn.execute("UPDATE users SET status='停用' WHERE id='SUCCESSOR-TEST'")
        with self.assertRaises(PermissionError): service.create(self.document["id"], payload)
        self.assertEqual(1, self.conn.execute("SELECT count(*) FROM official_documents").fetchone()[0])

    def test_followup_owner_case_appears_in_todo_not_mine_and_revokes_when_disabled(self):
        service = self.linked_service()
        session = service.session
        todo = backend.list_official_documents(self.conn, {"scope": ["todo"]}, session)
        self.assertEqual([self.document["id"]], [item["id"] for item in todo])
        self.assertTrue(todo[0]["can_create_linked_application"])
        self.assertEqual([], backend.list_official_documents(self.conn, {"scope": ["mine"]}, session))
        self.conn.execute("UPDATE users SET status='停用' WHERE id='SUCCESSOR-TEST'")
        self.assertEqual([], backend.list_official_documents(self.conn, {"scope": ["todo"]}, session))

    def test_notice_routing_targets_only_confirmed_live_owner(self):
        self.assertEqual("SUCCESSOR-TEST", backend.official_followup_notification_actor(self.document, conn=self.conn)["id"])
        self.conn.execute("UPDATE users SET status='停用' WHERE id='SUCCESSOR-TEST'")
        with self.assertRaisesRegex(ValueError, "handover_required"):
            backend.official_followup_notification_actor(self.document, conn=self.conn)

    def test_local_followup_dispatch_update_uses_same_database_and_revokes_live(self):
        self.conn.create_function("edoc_sha256", 1, lambda value: backend.sha256_bytes(str(value).encode()), deterministic=True)
        method = next(key for key, config in backend.OFFICIAL_DISPATCH_METHODS.items()
                      if config["owner_type"] == "applicant")
        self.conn.execute("UPDATE official_documents SET dispatch_method=? WHERE id=?",
                          (method, self.document["id"]))
        document = backend.official_document_row(self.conn, self.document["id"])
        backend.upsert_official_dispatch_record(self.conn, document, method)
        user = dict(self.conn.execute("SELECT * FROM users WHERE id='SUCCESSOR-TEST'").fetchone())
        session = {"user": user, "permissions": []}
        with mock.patch.object(backend, "supabase_filter_rows", side_effect=AssertionError("local_dispatch_must_not_read_remote")):
            result = backend.update_official_dispatch_record(
                self.conn, self.document["id"], {"dispatch_note": "合成接任人寄送資訊"}, session)
            self.assertEqual("合成接任人寄送資訊", result["dispatch_note"])
            self.assertEqual("APPLICANT-TEST", result["dispatch_owner_user_id"])
            self.conn.execute("UPDATE users SET status='停用' WHERE id='SUCCESSOR-TEST'")
            with self.assertRaises(PermissionError):
                backend.update_official_dispatch_record(
                    self.conn, self.document["id"], {"dispatch_note": "不得保存"}, session)
        self.assertEqual("合成接任人寄送資訊", backend.official_dispatch_record(self.conn, self.document["id"])["dispatch_note"])


if __name__ == "__main__": unittest.main()
