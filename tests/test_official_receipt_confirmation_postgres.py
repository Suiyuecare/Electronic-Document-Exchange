"""Real receipt transaction/race/role gates in ephemeral local PostgreSQL only."""
import json
import unittest
from concurrent.futures import ThreadPoolExecutor

import backend
from tests import test_editor_cross_company_workflow_postgres as fixture
from tools.configurable_workflow_shared_forward import SOURCE as WORKFLOW_SOURCE, render_shared_forward as workflow_forward
from tools.receipt_confirmation_shared_forward import SOURCE, render_shared_forward
from tools.shared_supabase_bootstrap import ROOT


@unittest.skipUnless(fixture.selection.resilience.fixture.PORT, "isolated PostgreSQL receipt gate not enabled")
class OfficialReceiptConfirmationPostgresTest(unittest.TestCase):
    namespace = "public"
    backend_role = "service_role"
    cleanup = classmethod(fixture.EditorCrossCompanyWorkflowPostgresTest.cleanup.__func__)
    create = fixture.EditorCrossCompanyWorkflowPostgresTest.create
    case = fixture.EditorCrossCompanyWorkflowPostgresTest.case
    insert = fixture.EditorCrossCompanyWorkflowPostgresTest.insert
    file = fixture.EditorCrossCompanyWorkflowPostgresTest.file
    workflow = fixture.EditorCrossCompanyWorkflowPostgresTest.workflow
    rpc = fixture.EditorCrossCompanyWorkflowPostgresTest.rpc

    @classmethod
    def setUpClass(cls):
        fixture.EditorCrossCompanyWorkflowPostgresTest.setUpClass.__func__(cls)
        cls.pg.execute("SET ROLE postgres")
        try:
            if cls.namespace == "public":
                cls.pg.execute((ROOT / "supabase/migrations" / WORKFLOW_SOURCE).read_text())
                cls.pg.execute((ROOT / "supabase/migrations" / SOURCE).read_text())
            else:
                cls.pg.execute("INSERT INTO edoc_private.shared_project_migration_ledger(file_name) VALUES (%s) ON CONFLICT DO NOTHING", (fixture.MIGRATION,))
                cls.pg.execute(workflow_forward())
                cls.pg.execute(render_shared_forward())
                cls.pg.execute(render_shared_forward())
        finally:
            cls.pg.execute("RESET ROLE")
        # Reproduce already-existing runtime privileges; migration grants no
        # table permissions and the shared backend does not bypass RLS.
        for table, permissions in (("official_document_approval_steps", "SELECT,UPDATE"),
                                   ("official_document_approval_logs", "SELECT,INSERT"),
                                   ("audit_logs", "SELECT,INSERT"),
                                   ("official_document_dispatch_records", "SELECT,UPDATE")):
            cls.pg.execute(f"GRANT {permissions} ON {cls.namespace}.{table} TO {cls.backend_role}")

    def prepared(self, status="stamped"):
        doc, _ = self.workflow()
        self.pg.execute("UPDATE official_document_approval_steps SET status='approved' WHERE document_id=%s AND step_key<>'applicant_confirm'", (doc,))
        self.pg.execute("UPDATE official_documents SET current_status=%s,current_step='applicant_confirm' WHERE id=%s", (status, doc))
        request = {"document_id": doc, "actor_id": "APPLICANT", "expected_step_id": "step-3-"+doc,
                   "workflow_generation": 1, "comment": "Synthetic receipt", "dispatch": {}, "user_agent": "isolated-test"}
        return request

    def confirm(self, request):
        return self.rpc("edoc_confirm_official_document", [json.dumps(request)], ["::jsonb"])

    def counts(self, doc):
        return self.pg.execute("SELECT (SELECT count(*) FROM official_document_approval_logs WHERE document_id=%s AND action='confirm'),(SELECT count(*) FROM audit_logs WHERE target_id=%s AND action='confirm')", (doc,doc)).fetchone()

    def test_success_replay_binds_step_actor_and_both_audit_witnesses(self):
        request = self.prepared()
        first, second = self.confirm(request), self.confirm(request)
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(first["approval_log_id"], second["approval_log_id"])
        step = self.pg.execute("SELECT to_jsonb(s) FROM official_document_approval_steps s WHERE id=%s", (request["expected_step_id"],)).fetchone()[0]
        log = self.pg.execute("SELECT to_jsonb(l) FROM official_document_approval_logs l WHERE id=%s", (first["approval_log_id"],)).fetchone()[0]
        self.assertEqual("APPLICANT", step["decision_actor_user_id"])
        self.assertEqual(step["id"], log["step_id"])
        self.assertEqual(step["approved_at"], log["created_at"])
        self.assertEqual("Isolated applicant", backend.official_step_decision_display([step], [log])[0]["decision_actor_name"])
        self.assertEqual((1,1), self.counts(request["document_id"]))

    def install_failure(self, doc):
        self.pg.execute(f"CREATE FUNCTION {self.namespace}.fixture_receipt_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action='confirm' AND NEW.target_id='{doc}' THEN RAISE EXCEPTION 'synthetic_receipt_audit_failure'; END IF; RETURN NEW; END $$")
        self.pg.execute(f"CREATE TRIGGER fixture_receipt_failure BEFORE INSERT ON {self.namespace}.audit_logs FOR EACH ROW EXECUTE FUNCTION {self.namespace}.fixture_receipt_failure()")

    def remove_failure(self):
        self.pg.execute(f"DROP TRIGGER IF EXISTS fixture_receipt_failure ON {self.namespace}.audit_logs")
        self.pg.execute(f"DROP FUNCTION IF EXISTS {self.namespace}.fixture_receipt_failure()")

    def test_final_audit_failure_rolls_back_step_document_log_and_is_retryable(self):
        request = self.prepared()
        self.install_failure(request["document_id"])
        try:
            with self.assertRaisesRegex(self.psycopg.Error, "synthetic_receipt_audit_failure"):
                self.confirm(request)
        finally:
            self.remove_failure()
        self.assertEqual(("stamped","applicant_confirm"), self.pg.execute("SELECT current_status,current_step FROM official_documents WHERE id=%s", (request["document_id"],)).fetchone())
        self.assertEqual(("pending",None), self.pg.execute("SELECT status,decision_actor_user_id FROM official_document_approval_steps WHERE id=%s", (request["expected_step_id"],)).fetchone())
        self.assertEqual((0,0), self.counts(request["document_id"]))
        self.assertTrue(self.confirm(request)["confirmed"])

    def test_duplicate_requests_commit_once_under_actual_concurrency(self):
        request = self.prepared()
        def run(_):
            with self.psycopg.connect(self.pg.info.dsn, autocommit=True) as conn, conn.transaction():
                conn.execute(f"SET LOCAL ROLE {self.backend_role}")
                return conn.execute(f"SELECT {self.namespace}.edoc_confirm_official_document(%s::jsonb)", (json.dumps(request),)).fetchone()[0]
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(run, range(6)))
        self.assertEqual(1, sum(not result["idempotent"] for result in results))
        self.assertEqual((1,1), self.counts(request["document_id"]))

    def test_wrong_actor_old_generation_missing_review_and_bad_state_fail_closed(self):
        for alteration in ("actor", "generation", "step", "review", "state", "disabled"):
            request = self.prepared()
            with self.pg.transaction(force_rollback=True):
                if alteration == "actor": request["actor_id"] = "STRANGER"
                if alteration == "generation": request["workflow_generation"] = 0
                if alteration == "step": request["expected_step_id"] = "step-1-"+request["document_id"]
                if alteration == "review": self.pg.execute("UPDATE official_document_approval_steps SET status='pending' WHERE id=%s", ("step-1-"+request["document_id"],))
                if alteration == "state": self.pg.execute("UPDATE official_documents SET current_status='rejected' WHERE id=%s", (request["document_id"],))
                if alteration == "disabled": self.pg.execute("UPDATE users SET status='停用' WHERE id='APPLICANT'")
                with self.subTest(alteration=alteration), self.assertRaises(self.psycopg.Error):
                    self.confirm(request)
                self.assertEqual((0,0), self.counts(request["document_id"]))

    def test_applicant_dispatch_and_receipt_share_one_transaction(self):
        request = self.prepared("returned_to_applicant_for_send")
        doc = request["document_id"]
        self.pg.execute("UPDATE official_documents SET dispatch_method='return_to_applicant_for_manual_send',current_step='applicant_dispatch' WHERE id=%s", (doc,))
        record = self.rpc("edoc_create_official_document_dispatch_record", [doc,"APPLICANT"])["dispatch_record_id"]
        proof = self.file(doc,"dispatch_proof","E"*64)
        self.pg.execute("UPDATE official_document_dispatch_records SET proof_file_id=%s WHERE id=%s", (proof["id"],record))
        request["dispatch"] = {"dispatch_date":"2026-09-24","recipient":"Synthetic recipient","dispatch_note":"Test only, no exchange call"}
        self.install_failure(doc)
        try:
            with self.assertRaisesRegex(self.psycopg.Error, "synthetic_receipt_audit_failure"):
                self.confirm(request)
        finally:
            self.remove_failure()
        self.assertEqual("returned_to_applicant_for_send", self.pg.execute("SELECT current_status FROM official_documents WHERE id=%s", (doc,)).fetchone()[0])
        self.assertEqual("pending", self.pg.execute("SELECT dispatch_status FROM official_document_dispatch_records WHERE id=%s", (record,)).fetchone()[0])
        self.assertEqual(0, self.pg.execute("SELECT count(*) FROM official_document_approval_logs WHERE document_id=%s AND action='complete_dispatch'", (doc,)).fetchone()[0])
        self.assertTrue(self.confirm(request)["confirmed"])
        self.assertTrue(self.confirm(request)["idempotent"])
        self.assertEqual("sent_by_applicant", self.pg.execute("SELECT dispatch_status FROM official_document_dispatch_records WHERE id=%s", (record,)).fetchone()[0])
        self.assertEqual((1,1), self.counts(doc))

    def test_backend_only_invoker_and_shared_schema_boundary(self):
        signature = f"{self.namespace}.edoc_confirm_official_document(jsonb)"
        definition, definer = self.pg.execute("SELECT pg_get_functiondef(oid),prosecdef FROM pg_proc WHERE oid=%s::regprocedure", (signature,)).fetchone()
        self.assertFalse(definer)
        self.assertIn("FOR UPDATE", definition.upper())
        for role in ("anon","authenticated"):
            self.assertFalse(self.pg.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')", (role,signature)).fetchone()[0])
        self.assertTrue(self.pg.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')", (self.backend_role,signature)).fetchone()[0])
        if self.namespace == "edoc":
            self.assertFalse(self.pg.execute("SELECT rolbypassrls FROM pg_roles WHERE rolname='edoc_backend'").fetchone()[0])
            self.assertEqual("unchanged", self.pg.execute("SELECT payload FROM public.hr_untouched WHERE id='HR'").fetchone()[0])

    def test_missing_applicant_dispatch_proof_does_not_create_partial_record(self):
        request = self.prepared("returned_to_applicant_for_send")
        doc = request["document_id"]
        self.pg.execute("UPDATE official_documents SET dispatch_method='return_to_applicant_for_manual_send',current_step='applicant_dispatch' WHERE id=%s", (doc,))
        request["dispatch"] = {"dispatch_date":"2026-09-24","recipient":"Synthetic recipient"}
        with self.assertRaisesRegex(self.psycopg.Error, "official_dispatch_proof_required"):
            self.confirm(request)
        self.assertEqual(0, self.pg.execute("SELECT count(*) FROM official_document_dispatch_records WHERE document_id=%s", (doc,)).fetchone()[0])
        self.assertEqual((0,0), self.counts(doc))
        self.assertEqual("returned_to_applicant_for_send", self.pg.execute("SELECT current_status FROM official_documents WHERE id=%s", (doc,)).fetchone()[0])


@unittest.skipUnless(fixture.selection.resilience.fixture.PORT, "isolated PostgreSQL shared receipt gate not enabled")
class SharedOfficialReceiptConfirmationPostgresTest(OfficialReceiptConfirmationPostgresTest):
    namespace = "edoc"
    backend_role = "edoc_backend"
