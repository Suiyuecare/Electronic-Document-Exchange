"""A resubmission changes the active generation, never its audit history."""
from __future__ import annotations

import copy
import sqlite3
import unittest
from contextlib import ExitStack
from unittest import mock

import backend


def workflow_steps():
    return [
        {"id": "OLD-REVIEW", "workflow_generation": 1, "step_order": 1,
         "step_key": "approval_review", "approver_user_id": "REVIEWER", "status": "rejected"},
        {"id": "OLD-GA", "workflow_generation": 1, "step_order": 2,
         "step_key": "general_affairs_review", "approver_user_id": "OLD-GA", "status": "skipped"},
        {"id": "NEW-REVIEW", "workflow_generation": 2, "step_order": 1,
         "step_key": "approval_review", "approver_user_id": "REVIEWER", "status": "approved"},
        {"id": "NEW-GA", "workflow_generation": 2, "step_order": 2,
         "step_key": "general_affairs_review", "approver_user_id": "CURRENT-GA", "status": "approved"},
        {"id": "NEW-RECEIPT", "workflow_generation": 2, "step_order": 3,
         "step_key": "applicant_confirm", "approver_user_id": "APPLICANT", "status": "pending"},
    ]


class OfficialStampRetryGenerationTest(unittest.TestCase):
    def retry(self, mode, rows, actor="CURRENT-GA", expected_error=None):
        document = {"id": "DOC", "current_status": "stamping_failed",
                    "current_step": "general_affairs_review"}
        request = {"id": "REQUEST", "status": "failed"}
        prefix = "supabase_" if mode == "supabase" else ""
        original = copy.deepcopy(rows)
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(backend, prefix + "official_document_row", return_value=document))
            stack.enter_context(mock.patch.object(backend, prefix + "official_document_stamp_request", return_value=request))
            stack.enter_context(mock.patch.object(backend, prefix + "official_document_steps", return_value=rows))
            log = stack.enter_context(mock.patch.object(backend, prefix + "insert_official_log"))
            stamp = stack.enter_context(mock.patch.object(backend, prefix + "auto_stamp_official_document", return_value={"ok": True}))
            stack.enter_context(mock.patch.object(backend, prefix + "official_document_detail", return_value={"id": "DOC"}))
            args = ("DOC", {}, {"user": {"id": actor}})
            if mode == "sqlite":
                args = (None, *args)
            method = getattr(backend, prefix + "retry_official_document_stamp")
            if expected_error:
                with self.assertRaisesRegex((ValueError, PermissionError), expected_error):
                    method(*args)
                stamp.assert_not_called()
                log.assert_not_called()
            else:
                self.assertTrue(method(*args)["auto_stamp"]["ok"])
                stamp.assert_called_once()
                self.assertEqual("CURRENT-GA", stamp.call_args.args[-1]["id"])
                log.assert_called_once()
        self.assertEqual(original, rows, "Retried stamping must retain old workflow history")

    def test_retry_accepts_latest_ga_after_old_rejection_and_preserves_history(self):
        for mode in ("sqlite", "supabase"):
            with self.subTest(mode=mode):
                self.retry(mode, workflow_steps())

    def test_retry_denies_the_previous_ga_even_when_the_old_generation_was_approved(self):
        rows = workflow_steps()
        rows[0]["status"] = rows[1]["status"] = "approved"
        for mode in ("sqlite", "supabase"):
            with self.subTest(mode=mode):
                self.retry(mode, rows, actor="OLD-GA", expected_error="official_stamp_retry_forbidden")

    def test_current_generation_requires_every_approval_but_not_applicant_receipt(self):
        for mode in ("sqlite", "supabase"):
            for status in ("pending", "rejected", "skipped"):
                with self.subTest(mode=mode, status=status):
                    rows = workflow_steps()
                    rows[2]["status"] = status
                    self.retry(mode, rows, expected_error="official_document_not_fully_approved_for_stamp_retry")

    def test_new_generation_without_ga_does_not_fall_back_to_old_assignment(self):
        rows = [row for row in workflow_steps() if row["id"] != "NEW-GA"]
        for mode in ("sqlite", "supabase"):
            with self.subTest(mode=mode):
                self.retry(mode, rows, actor="OLD-GA", expected_error="official_stamp_retry_forbidden")
        with self.assertRaisesRegex(ValueError, "official_dispatch_owner_unresolved"):
            backend.official_dispatch_workflow_owner(rows)

    def test_retry_and_dispatch_capabilities_resolve_latest_generation_independent_of_order(self):
        rows = workflow_steps()
        for history in (rows, list(reversed(rows)), iter(rows)):
            self.assertTrue(backend.can_retry_official_stamp({"id": "CURRENT-GA"}, history))
        self.assertFalse(backend.can_retry_official_stamp({"id": "OLD-GA"}, rows))
        self.assertEqual("CURRENT-GA", backend.official_dispatch_workflow_owner(iter(rows))["id"])
        self.assertFalse(backend.can_retry_official_stamp({"id": "CURRENT-GA"}, []))


class OfficialStampRetryLeaseGenerationTest(unittest.TestCase):
    """Execute the durable SQLite lease gate, not a mocked authorization result."""
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        backend.register_sqlite_functions(self.conn)
        self.conn.executescript(backend.SCHEMA)
        self.addCleanup(self.conn.close)
        self.conn.execute("""INSERT INTO companies(id,name,created_at,updated_at)
            VALUES ('CO-TEST','Synthetic company','2026-09-24','2026-09-24')""")
        self.conn.execute("""INSERT INTO company_seals
            (id,company_id,seal_name,seal_category,seal_size_type,created_at,updated_at)
            VALUES ('SEAL-TEST','CO-TEST','Synthetic seal','general_seal','large_seal','2026-09-24','2026-09-24')""")
        self.conn.execute("""INSERT INTO official_documents
            (id,company_id,source_type,title,applicant_id,current_status,current_step,created_at,updated_at)
            VALUES ('DOC','CO-TEST','uploaded_pdf','Synthetic document','APPLICANT',
                    'stamping_failed','general_affairs_review','2026-09-24','2026-09-24')""")
        self.conn.execute("""INSERT INTO official_document_stamp_requests
            (id,document_id,company_id,seal_id,status,created_at,updated_at)
            VALUES ('REQUEST','DOC','CO-TEST','SEAL-TEST','failed','2026-09-24','2026-09-24')""")
        for row in workflow_steps():
            backend.insert_row(self.conn, "official_document_approval_steps", {
                **row, "document_id": "DOC", "step_name": row["step_key"],
                "created_at": "2026-09-24", "updated_at": "2026-09-24",
            })
        self.original = backend.official_document_steps(self.conn, "DOC")

    def claim(self, actor="CURRENT-GA", token="A" * 64):
        return backend.claim_official_document_stamp(self.conn, "DOC", "REQUEST", token, actor)

    def test_latest_ga_can_claim_and_renew_but_cannot_create_a_duplicate_worker(self):
        self.assertTrue(self.claim()["claimed"])
        self.assertTrue(self.claim()["renewed"])
        competing = self.claim(token="B" * 64)
        self.assertFalse(competing["claimed"])
        self.assertEqual("official_stamp_claim_busy", competing["reason"])
        self.assertEqual(self.original, backend.official_document_steps(self.conn, "DOC"))
        self.assertEqual(1, self.conn.execute("SELECT claim_attempt_count FROM official_document_stamp_requests").fetchone()[0])

    def test_old_ga_is_denied_by_the_durable_gate(self):
        with self.assertRaisesRegex(PermissionError, "official_stamp_retry_forbidden"):
            self.claim(actor="OLD-GA")
        self.assertEqual("stamping_failed", backend.official_document_row(self.conn, "DOC")["current_status"])

    def test_current_unapproved_step_blocks_claim_without_mutation(self):
        self.conn.execute("UPDATE official_document_approval_steps SET status='pending' WHERE id='NEW-REVIEW'")
        with self.assertRaisesRegex(ValueError, "official_document_not_fully_approved_for_stamp_retry"):
            self.claim()
        self.assertEqual("failed", self.conn.execute("SELECT status FROM official_document_stamp_requests").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
