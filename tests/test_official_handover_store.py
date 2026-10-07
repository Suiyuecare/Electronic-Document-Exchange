"""Real SQLite atomicity and synthetic-file regression. Never production."""
import copy
import json
import sqlite3
import unittest
from unittest import mock

import backend
import official_handover as policy
import official_handover_store as store
from tests import test_official_handover_policy as policy_fixture


class HandoverStoreTest(unittest.TestCase):
    def setUp(self):
        self.fixture = policy_fixture.HandoverPolicyTest()
        self.fixture.setUp()
        f = self.fixture
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(backend.SCHEMA)
        self.addCleanup(self.conn.close)
        backend.insert_row(self.conn, "companies", {**f.company, "name": "Synthetic company",
                                                   "created_at": "2026-10-07 00:00:00", "updated_at": "2026-10-07 00:00:00"})
        for actor in (f.proposer, f.confirmer, f.former, f.successor,
                      f.user("MANAGER-TEST", "主管"), f.user("APPLICANT-TEST", "員工")):
            values = {**actor, "email": actor["id"].lower() + "@example.invalid", "created_at": "2026-10-07 00:00:00"}
            self.conn.execute("INSERT INTO users(id,name,role,status,company_id,finance_tenant_id,account_source,email,created_at) VALUES (:id,:name,:role,:status,:company_id,:finance_tenant_id,:account_source,:email,:created_at)", values)
        document = {**f.document, "metadata_json": "{}", "created_at": "2026-10-07 00:00:00"}
        document["source_type"] = getattr(self, "source_type", document["source_type"])
        document.pop("dispatch_no")  # Exercise the real server-owned numbering guard.
        backend.insert_row(self.conn, "official_documents", document)
        for step in f.steps:
            backend.insert_row(self.conn, "official_document_approval_steps", {
                **step, "decision_evidence_json": json.dumps(
                    {} if step["step_key"] == "applicant_confirm" else step["decision_evidence_json"])})
        self.document_id = f.document["id"]
        self.proposer_session = {"user": copy.deepcopy(f.proposer)}
        self.confirmer_session = {"user": copy.deepcopy(f.confirmer)}
        self.conn.commit()

    def payload(self, *, kind="pending_approver", operation="HANDOVER-SQLITE-0001", former="FORMER-TEST", successor="SUCCESSOR-TEST"):
        doc = backend.official_document_row(self.conn, self.document_id)
        steps = [dict(row) for row in self.conn.execute("SELECT * FROM official_document_approval_steps WHERE document_id=?", (self.document_id,))]
        binding = store._binding(self.conn, doc, backend)
        return {"operation_id": operation, "kind": kind, "former_user_id": former,
                "successor_user_id": successor, "reason": "Synthetic offboarding handover",
                "expected_fingerprint": policy.handover_fingerprint(doc, steps, binding=binding)}

    def propose(self, payload=None):
        return store.propose(self.conn, self.document_id, payload or self.payload(), self.proposer_session, backend=backend)

    def confirm(self, identity="HANDOVER-SQLITE-0001"):
        return store.confirm(self.conn, identity, self.confirmer_session, backend=backend)

    def counts(self):
        return tuple(self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in
                     ("official_document_approval_steps", "official_document_approval_logs", "approval_step_actor_snapshots", "notifications", "audit_logs"))

    def test_atomic_confirm_replay_preserves_actual_history_and_emits_only_system_notices(self):
        payload = self.payload()
        before = dict(self.conn.execute("SELECT * FROM official_document_approval_steps WHERE id='S1'").fetchone())
        self.assertFalse(self.propose(payload)["idempotent"])
        self.assertTrue(self.propose(payload)["idempotent"])
        self.assertFalse(self.confirm()["idempotent"])
        counts = self.counts()
        self.assertTrue(self.confirm()["idempotent"])
        self.assertEqual(counts, self.counts())
        self.assertEqual(before, dict(self.conn.execute("SELECT * FROM official_document_approval_steps WHERE id='S1'").fetchone()))
        rows = backend.current_official_document_steps(self.conn, self.document_id)
        self.assertEqual("SUCCESSOR-TEST", rows[1]["approver_user_id"])
        self.assertEqual("ACTUAL-DELEGATE-TEST", rows[0]["decision_actor_user_id"])
        self.assertEqual("APPLICANT-TEST", backend.official_document_row(self.conn, self.document_id)["applicant_id"])
        self.assertEqual({"系統通知"}, {row[0] for row in self.conn.execute("SELECT channel FROM notifications")})
        self.assertEqual(3, self.conn.execute("SELECT count(*) FROM approval_step_actor_snapshots").fetchone()[0])
        self.assertTrue(self.propose(payload)["idempotent"])

    def test_operation_id_cannot_be_reused_for_changed_target_or_reason(self):
        payload = self.payload()
        self.propose(payload)
        for field, value in (("reason", "Different justification"), ("successor_user_id", "APPLICANT-TEST"),
                              ("expected_fingerprint", "forged")):
            with self.subTest(field=field), self.assertRaises(policy.HandoverConflict):
                self.propose({**payload, field: value})

    def test_only_one_pending_proposal_for_assignment(self):
        self.propose()
        with self.assertRaisesRegex(policy.HandoverConflict, "pending_request_exists"):
            self.propose(self.payload(operation="HANDOVER-SQLITE-0002"))
        self.assertEqual(1, self.conn.execute("SELECT count(*) FROM official_document_handovers").fetchone()[0])

    def test_role_claim_in_session_does_not_override_live_finance_record(self):
        self.proposer_session["user"]["role"] = "總務"
        self.conn.execute("UPDATE users SET role='員工' WHERE id='PROPOSER-TEST'")
        with self.assertRaises(PermissionError): self.propose()
        self.assertEqual(0, self.conn.execute("SELECT count(*) FROM official_document_handovers").fetchone()[0])

    def test_successor_disable_after_proposal_denies_without_partial_mutation(self):
        self.propose()
        before = self.counts()
        self.conn.execute("UPDATE users SET status='停用' WHERE id='SUCCESSOR-TEST'")
        with self.assertRaises(PermissionError): self.confirm()
        self.assertEqual(before, self.counts())
        self.assertEqual("pending", self.conn.execute("SELECT status FROM official_document_handovers").fetchone()[0])

    def test_workflow_advances_before_confirmation_and_handover_is_rejected(self):
        self.propose()
        self.conn.execute("UPDATE official_documents SET current_step='applicant_confirm',current_status='approved' WHERE id=?", (self.document_id,))
        before = self.counts()
        with self.assertRaises(policy.HandoverConflict): self.confirm()
        self.assertEqual(before, self.counts())

    def test_notification_failure_rolls_back_steps_snapshot_binding_and_audit(self):
        self.propose()
        before = self.counts()
        with mock.patch.object(backend, "create_notification", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaises(RuntimeError): self.confirm()
        self.assertEqual(before, self.counts())
        self.assertEqual("pending", self.conn.execute("SELECT status FROM official_document_handovers").fetchone()[0])
        self.assertEqual("pending", self.conn.execute("SELECT status FROM official_document_approval_steps WHERE id='S2'").fetchone()[0])

    def test_stale_inactive_session_cannot_confirm_even_when_claims_active(self):
        self.propose()
        self.conn.execute("UPDATE users SET status='停用' WHERE id='CONFIRMER-TEST'")
        with self.assertRaises(PermissionError): self.confirm()

    def test_reject_stale_proposal_preserves_steps_and_can_be_retried(self):
        self.propose()
        before = [dict(row) for row in self.conn.execute("SELECT * FROM official_document_approval_steps ORDER BY id")]
        self.conn.execute("UPDATE users SET status='停用' WHERE id IN ('PROPOSER-TEST','SUCCESSOR-TEST')")
        receipt = store.reject(self.conn, "HANDOVER-SQLITE-0001", "Synthetic rejection", self.confirmer_session, backend=backend)
        self.assertEqual("rejected", receipt["status"])
        counts = self.counts()
        self.assertTrue(store.reject(self.conn, "HANDOVER-SQLITE-0001", "Synthetic rejection", self.confirmer_session, backend=backend)["idempotent"])
        self.assertEqual(counts, self.counts())
        self.assertEqual(before, [dict(row) for row in self.conn.execute("SELECT * FROM official_document_approval_steps ORDER BY id")])
        with self.assertRaises(policy.HandoverConflict):
            store.reject(self.conn, "HANDOVER-SQLITE-0001", "Changed rejection", self.confirmer_session, backend=backend)
        with self.assertRaises(policy.HandoverConflict): self.confirm()

    def test_reject_requires_live_director_and_justification(self):
        self.propose()
        for session, reason, error in (
            (self.proposer_session, "Synthetic rejection", PermissionError),
            (self.confirmer_session, "", ValueError),
        ):
            with self.subTest(reason=reason), self.assertRaises(error):
                store.reject(self.conn, "HANDOVER-SQLITE-0001", reason, session, backend=backend)
        self.assertEqual("pending", self.conn.execute("SELECT status FROM official_document_handovers").fetchone()[0])

    def test_followup_binding_is_independent_and_duplicate_overwrite_denied(self):
        self.conn.execute("UPDATE users SET status='停用' WHERE id='APPLICANT-TEST'")
        self.conn.execute("UPDATE official_documents SET current_status='rejected' WHERE id=?", (self.document_id,))
        payload = self.payload(kind="followup_owner", former="APPLICANT-TEST")
        self.propose(payload)
        old = backend.official_document_row(self.conn, self.document_id)
        self.confirm()
        self.assertEqual(old, backend.official_document_row(self.conn, self.document_id))
        binding = dict(self.conn.execute("SELECT * FROM official_document_followup_owners").fetchone())
        self.assertEqual("APPLICANT-TEST", binding["original_applicant_id"])
        self.assertEqual("SUCCESSOR-TEST", binding["process_owner_user_id"])
        another = self.payload(kind="followup_owner", former="APPLICANT-TEST", operation="HANDOVER-SQLITE-0002")
        with self.assertRaises(PermissionError): self.propose(another)

    def test_repeat_succession_requires_inactive_current_owner_and_preserves_chain(self):
        import official_handover_followup
        self.conn.execute("UPDATE users SET status='停用' WHERE id='APPLICANT-TEST'")
        first = self.payload(kind="followup_owner", former="APPLICANT-TEST")
        self.propose(first); self.confirm()
        original = backend.official_document_row(self.conn, self.document_id)
        second = self.payload(kind="followup_owner", former="SUCCESSOR-TEST", successor="MANAGER-TEST", operation="HANDOVER-SQLITE-0002")
        with self.assertRaises(PermissionError): self.propose(second)
        self.conn.execute("UPDATE users SET status='停用' WHERE id='SUCCESSOR-TEST'")
        second = self.payload(kind="followup_owner", former="SUCCESSOR-TEST", successor="MANAGER-TEST", operation="HANDOVER-SQLITE-0002")
        self.propose(second)
        self.assertIsNone(official_handover_followup.load(backend, original, conn=self.conn))
        self.confirm(second["operation_id"])
        binding = official_handover_followup.load(backend, original, conn=self.conn, actor_id="MANAGER-TEST")
        self.assertEqual(second["operation_id"], binding["handover_id"])
        history = [json.loads(row[0]) for row in self.conn.execute("SELECT request_json FROM official_document_handovers ORDER BY id")]
        self.assertEqual(first["operation_id"], history[1]["previous_handover_id"])
        self.assertEqual({"approved"}, {row["status"] for row in history})
        self.assertEqual(original, backend.official_document_row(self.conn, self.document_id))
        counts = self.counts()
        self.assertTrue(self.confirm(second["operation_id"])["idempotent"])
        self.assertEqual(counts, self.counts())
        self.conn.execute("UPDATE official_document_handovers SET request_json=json_set(request_json,'$.previous_handover_id','MISSING-PARENT') WHERE id=?", (second["operation_id"],))
        self.assertIsNone(official_handover_followup.load(backend, original, conn=self.conn))


class HandoverExistingFileWorkflowTest(unittest.TestCase):
    def test_reassigned_reviewer_still_must_review_exact_locked_pdf_before_approval(self):
        from tests.test_configurable_official_workflow import ConfigurableOfficialWorkflowTest
        fixture = ConfigurableOfficialWorkflowTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        conn = fixture.conn
        detail = fixture._approve(fixture.fixture._submitted()[0])
        company_id = detail["company_id"]
        tenant = "HANDOVER-TENANT-TEST"
        conn.execute("UPDATE companies SET finance_tenant_id=?,source_system='finance',status='active' WHERE id=?", (tenant, company_id))
        conn.execute("UPDATE users SET account_source='finance',finance_tenant_id=? WHERE company_id=?", (tenant, company_id))
        current = next(row for row in detail["approval_steps"] if row["step_key"] == detail["current_step"] and row["status"] == "pending")
        former = dict(conn.execute("SELECT * FROM users WHERE id=?", (current["approver_user_id"],)).fetchone())
        identities = [("GA-HANDOVER-TEST", "總務"), ("AD-HANDOVER-TEST", "行政部主任"), ("NEW-HANDOVER-TEST", former["role"])]
        for identity, role in identities:
            conn.execute("INSERT INTO users(id,name,email,role,status,account_source,company_id,finance_tenant_id,created_at) VALUES (?,?,?,?,'啟用','finance',?,?,?)",
                         (identity, identity, identity.lower()+"@example.invalid", role, company_id, tenant, backend.now()))
        conn.execute("UPDATE users SET status='停用' WHERE id=?", (former["id"],))
        document = backend.official_document_row(conn, detail["id"])
        steps = backend.current_official_document_steps(conn, detail["id"])
        stamp = backend.official_document_stamp_request(conn, detail["id"])
        payload = {"operation_id": "HANDOVER-FILE-REGRESSION", "kind": "pending_approver",
                   "former_user_id": former["id"], "successor_user_id": "NEW-HANDOVER-TEST",
                   "reason": "Synthetic reviewer offboarding", "expected_fingerprint": policy.handover_fingerprint(document, steps, stamp)}
        store.propose(conn, detail["id"], payload, {"user": {"id": "GA-HANDOVER-TEST"}}, backend=backend)
        store.confirm(conn, payload["operation_id"], {"user": {"id": "AD-HANDOVER-TEST"}}, backend=backend)
        renewed = backend.official_document_detail(conn, detail["id"], fixture.session)
        self.assertEqual("NEW-HANDOVER-TEST", next(row for row in renewed["approval_steps"] if row["status"] == "pending")["approver_user_id"])
        with self.assertRaises((ValueError, PermissionError)):
            backend.approve_official_document(conn, detail["id"], {"expected_step_id": current["id"],
                "review_acknowledgements": {"original_reviewed": True, "edited_version_reviewed": True, "attachments_reviewed": True}},
                {"user": {"id": "NEW-HANDOVER-TEST", "name": "NEW-HANDOVER-TEST"}})
        step, session, review = fixture._review(renewed)
        self.assertNotEqual(current["id"], step["id"])
        approved = backend.approve_official_document(conn, detail["id"], review, session)
        self.assertNotEqual(renewed["current_step"], approved["current_step"])


if __name__ == "__main__": unittest.main()
