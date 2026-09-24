"""Receipt atomicity, retry, and actual-actor linkage; synthetic local data only."""
import copy
import json
import sqlite3
import unittest
from unittest import mock

import backend
from tools.receipt_confirmation_shared_forward import SOURCE, FORWARD_NAME, render_shared_forward
from tools.shared_supabase_bootstrap import ROOT


class OfficialReceiptConfirmationTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        backend.register_sqlite_functions(self.conn)
        self.conn.executescript(backend.SCHEMA)
        self.session = {"user": {"id": "APPLICANT", "name": "合成收件人"}}
        self.conn.execute("INSERT INTO companies(id,name,created_at,updated_at) VALUES ('CO','Synthetic company','x','x')")
        self.conn.execute("INSERT INTO official_documents(id,company_id,source_type,title,applicant_id,current_status,current_step,created_at,updated_at) VALUES ('DOC','CO','uploaded_pdf','Synthetic','APPLICANT','stamped','applicant_confirm','2026-09-24 10:00:00','2026-09-24 10:00:00')")
        self.conn.execute("INSERT INTO official_document_approval_steps(id,document_id,step_order,step_key,step_name,approver_user_id,status,created_at,updated_at) VALUES ('RECEIPT','DOC',1,'applicant_confirm','Receipt','APPLICANT','pending','2026-09-24 10:00:00','2026-09-24 10:00:00')")
        self.detail = mock.patch.object(backend, "official_document_detail", side_effect=lambda conn, doc, session: backend.official_document_row(conn, doc))
        self.detail.start()
        self.addCleanup(self.detail.stop)
        self.addCleanup(self.conn.close)

    def confirm(self):
        return backend.confirm_official_document(self.conn, "DOC", {}, self.session)

    def test_audit_failure_rolls_back_entire_confirmation_then_retry_is_safe(self):
        with mock.patch.object(backend, "log_audit", side_effect=RuntimeError("synthetic audit outage")):
            with self.assertRaisesRegex(RuntimeError, "synthetic"):
                self.confirm()
        self.assertEqual("stamped", backend.official_document_row(self.conn, "DOC")["current_status"])
        self.assertEqual("pending", backend.official_document_steps(self.conn, "DOC")[0]["status"])
        self.assertEqual(0, self.conn.execute("SELECT count(*) FROM official_document_approval_logs").fetchone()[0])
        self.assertEqual("closed", self.confirm()["current_status"])
        self.assertEqual("closed", self.confirm()["current_status"])
        self.assertEqual(1, self.conn.execute("SELECT count(*) FROM official_document_approval_logs WHERE action='confirm'").fetchone()[0])
        self.assertEqual(1, self.conn.execute("SELECT count(*) FROM audit_logs WHERE action='confirm'").fetchone()[0])

    def test_cross_second_receipt_records_explicit_actual_actor_and_step(self):
        times = iter(["2026-09-24 10:00:00", "2026-09-24 10:00:02", "2026-09-24 10:00:03"])
        with mock.patch.object(backend, "now", side_effect=lambda: next(times, "2026-09-24 10:00:04")):
            self.confirm()
        step = backend.official_document_steps(self.conn, "DOC")[0]
        log = dict(self.conn.execute("SELECT * FROM official_document_approval_logs").fetchone())
        self.assertNotEqual(step["approved_at"], log["created_at"])
        self.assertEqual("RECEIPT", log["step_id"])
        self.assertEqual("APPLICANT", step["decision_actor_user_id"])
        self.assertEqual(log["id"], json.loads(step["decision_evidence_json"])["confirmation_log_id"])
        self.assertEqual("合成收件人", backend.official_step_decision_display([step], [log])[0]["decision_actor_name"])

    def test_assignment_never_allows_other_actor_or_incomplete_workflow_to_confirm(self):
        with self.assertRaisesRegex(PermissionError, "only_applicant"):
            backend.confirm_official_document(self.conn, "DOC", {}, {"user": {"id": "OTHER"}})
        self.conn.execute("INSERT INTO official_document_approval_steps(id,document_id,step_order,step_key,step_name,approver_user_id,status,created_at,updated_at) VALUES ('EARLIER','DOC',0,'admin_director','Review','OTHER','pending','x','x')")
        with self.assertRaisesRegex(ValueError, "not_ready"):
            self.confirm()
        self.assertEqual("stamped", backend.official_document_row(self.conn, "DOC")["current_status"])

    def test_unique_legacy_witness_resolves_clock_drift_but_ambiguity_does_not(self):
        step = backend.official_document_steps(self.conn, "DOC")[0]
        step.update(status="approved", approved_at="2026-09-24 10:00:00")
        log = {"id": "OLD-LOG", "document_id": "DOC", "action": "confirm", "step_id": None,
               "actor_id": "APPLICANT", "actor_name": "真正收件人", "created_at": "2026-09-24 10:00:02"}
        self.assertEqual("真正收件人", backend.official_step_decision_display([step], [log])[0]["decision_actor_name"])
        for steps, logs in (([step, {**step, "id": "OLDER", "workflow_generation": 2}], [log]),
                            ([step], [log, {**log, "id": "OTHER-LOG"}]),
                            ([step], [{**log, "actor_id": "OTHER"}])):
            self.assertEqual("", backend.official_step_decision_display(steps, logs)[0]["decision_actor_name"])

    def test_rpc_wrapper_has_one_mutation_and_validates_response_identity(self):
        step = backend.official_document_steps(self.conn, "DOC")[0]
        document = backend.official_document_row(self.conn, "DOC")
        response = {"confirmed": True, "document_id": "DOC", "step_id": "RECEIPT", "actor_id": "APPLICANT", "idempotent": False}
        with mock.patch.object(backend, "supabase_official_document_row", return_value=document), mock.patch.object(backend, "supabase_official_document_steps", return_value=[step]), mock.patch.object(backend, "supabase_request", return_value=response) as rpc, mock.patch.object(backend, "supabase_official_document_detail", return_value={"current_status": "closed"}), mock.patch.object(backend, "supabase_patch", side_effect=AssertionError("non-atomic patch")), mock.patch.object(backend, "supabase_insert_official_log", side_effect=AssertionError("non-atomic log")):
            self.assertEqual("closed", backend.supabase_confirm_official_document("DOC", {}, self.session)["current_status"])
            self.assertEqual(1, rpc.call_count)
            self.assertEqual("rpc/edoc_confirm_official_document", rpc.call_args.args[1])
            self.assertEqual("RECEIPT", rpc.call_args.args[2]["p_request"]["expected_step_id"])
            for invalid in ([], {**response, "actor_id": "OTHER"}, {**response, "step_id": "OLD"}, {**response, "confirmed": False}):
                rpc.return_value = copy.deepcopy(invalid)
                with self.assertRaises(RuntimeError):
                    backend.supabase_confirm_official_document("DOC", {}, self.session)

    def test_shared_forward_and_runtime_readiness_are_pinned(self):
        self.assertEqual((ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text(), render_shared_forward())
        self.assertIn("edoc_confirm_official_document", backend.EDOC_READINESS_REQUIRED_RPC_NAMES)
        source = (ROOT / "supabase/migrations" / SOURCE).read_text()
        self.assertIn("security invoker", source)
        self.assertNotIn("security definer", source.lower())


if __name__ == "__main__":
    unittest.main()
