"""Real isolated PostgreSQL terminal decisions, including shared namespaces."""
import copy
import json
import unittest
from concurrent.futures import ThreadPoolExecutor

import backend
from tests import test_configurable_workflow_postgres as fixture
from tools.terminal_decline_shared_forward import SOURCE, render_shared_forward
from tools.shared_supabase_bootstrap import ROOT


@unittest.skipUnless(fixture.fixture.selection.resilience.fixture.PORT, "isolated PostgreSQL terminal gate not enabled")
class TerminalDeclinePostgresTest(fixture.ConfigurableWorkflowPostgresTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pg.execute("SET ROLE postgres")
        try:
            if cls.namespace == "public":
                cls.pg.execute((ROOT / "supabase/migrations" / SOURCE).read_text())
                cls.pg.execute((ROOT / "supabase/migrations" / SOURCE).read_text())
            else:
                cls.pg.execute(render_shared_forward())
                cls.pg.execute(render_shared_forward())
        finally:
            cls.pg.execute("RESET ROLE")

    def terminal_plan(self, *, second=False):
        doc, evidence = self.workflow()
        if second:
            self.decide(doc, evidence)
            evidence = self.review(doc, "step-2-" + doc, "NEXT")
        document = self.pg.execute("SELECT to_jsonb(d) FROM official_documents d WHERE id=%s", (doc,)).fetchone()[0]
        actor = {"id": evidence["decision_actor_user_id"], "name": "Synthetic actor"}
        evidence["decision_type"] = "decline"
        payload = {"operation_id": "DECLINE-" + doc, "expected_step_id": evidence["expected_step_id"], "comment": "Synthetic terminal decision reason"}
        return backend.plan_official_workflow_mutation(document, self.rows(doc), actor, "decline", payload, decision_evidence=evidence)

    def decline(self, request):
        return self.rpc("edoc_decline_official_document", [json.dumps(request)], ["::jsonb"])

    def test_decline_terminal_history_notification_replay_and_no_clone(self):
        request = self.terminal_plan(second=True)
        doc = request["document_id"]
        previous = self.rows(doc)[0]
        self.assertTrue(self.decline(request)["committed"])
        self.assertEqual(("declined", ""), self.pg.execute("SELECT current_status,current_step FROM official_documents WHERE id=%s", (doc,)).fetchone())
        rows = self.rows(doc)
        self.assertEqual(previous, rows[0])
        self.assertEqual(["approved", "rejected", "skipped"], [row["status"] for row in rows])
        self.assertEqual("NEXT", rows[1]["decision_actor_user_id"])
        self.assertEqual("decline", rows[1]["decision_evidence_json"]["decision_type"])
        self.assertEqual(("cancelled",), self.pg.execute("SELECT status FROM official_document_stamp_requests WHERE document_id=%s", (doc,)).fetchone())
        self.assertEqual((1,), self.pg.execute("SELECT count(*) FROM official_document_editor_revisions WHERE document_id=%s", (doc,)).fetchone())
        self.assertEqual(("APPLICANT",), self.pg.execute("SELECT target_user_id FROM notifications WHERE id=%s", ("NOTIF-DECLINE-" + __import__("hashlib").md5(request["operation_id"].encode()).hexdigest(),)).fetchone())
        self.assertTrue(self.decline(request)["idempotent"])
        changed = copy.deepcopy(request); changed["request_sha256"] = "0" * 64
        with self.assertRaisesRegex(self.psycopg.Error, "operation_conflict"):
            self.decline(changed)
        with self.assertRaisesRegex(self.psycopg.Error, "terminal"):
            self.rpc("edoc_cancel_official_document", [doc, "APPLICANT"])

    def test_terminal_rpc_denies_wrong_actor_review_hash_stale_reason_and_stamp(self):
        for alteration in ("actor", "self", "review", "step", "reason", "stamp", "disabled"):
            request = self.terminal_plan()
            if alteration == "actor": request["actor_id"] = "STRANGER"
            if alteration == "self": request["actor_id"] = request["principal_actor_id"] = "APPLICANT"
            if alteration == "review": request["decision_evidence"]["prepared_sha256"] = "0" * 64
            if alteration == "step": request["expected_step_id"] = "stale"
            if alteration == "reason": request["approval_log"]["comment"] = "short"
            if alteration == "stamp": self.pg.execute("UPDATE official_document_stamp_requests SET claim_token='synthetic-claimed' WHERE document_id=%s", (request["document_id"],))
            if alteration == "disabled": self.pg.execute("UPDATE users SET status='停用' WHERE id='REVIEWER'")
            try:
                with self.subTest(alteration=alteration), self.assertRaises(self.psycopg.Error): self.decline(request)
                self.assertEqual(("pending_applicant_manager",), self.pg.execute("SELECT current_status FROM official_documents WHERE id=%s", (request["document_id"],)).fetchone())
                self.assertEqual((0,), self.pg.execute("SELECT count(*) FROM official_document_approval_logs WHERE id=%s", (request["operation_id"],)).fetchone())
            finally:
                self.pg.execute("UPDATE users SET status='啟用' WHERE id='REVIEWER'")

    def test_browser_roles_cannot_execute_terminal_rpc(self):
        denied = ("anon", "authenticated", "service_role") if self.namespace == "edoc" else ("anon", "authenticated")
        for role in denied:
            self.assertFalse(self.pg.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, self.namespace + ".edoc_decline_official_document(jsonb)")).fetchone()[0])
        self.assertTrue(self.pg.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')", (self.backend_role, self.namespace + ".edoc_decline_official_document(jsonb)")).fetchone()[0])

    def test_decline_and_approval_race_have_one_effect(self):
        request = self.terminal_plan()
        evidence = copy.deepcopy(request["decision_evidence"]); evidence["decision_type"] = "approve"
        def run(kind):
            base = fixture.fixture.selection.resilience.fixture
            with self.psycopg.connect(host="127.0.0.1", port=int(base.PORT), user=base.os.getenv("EDOC_TEST_PG_USER", "seniorlifepr"), dbname=self.dbname, autocommit=True) as pg:
                try:
                    with pg.transaction():
                        pg.execute(f"SET LOCAL ROLE {self.backend_role}")
                        if kind == "decline":
                            value = pg.execute(f"SELECT {self.namespace}.edoc_decline_official_document(%s::jsonb)", (json.dumps(request),)).fetchone()[0]
                            return bool(value["committed"])
                        value = pg.execute(f"SELECT {self.namespace}.edoc_claim_official_document_approval_v3(%s,%s,'REVIEWER','REVIEWER','Concurrent review',%s::jsonb)", (request["document_id"], request["expected_step_id"], json.dumps(evidence))).fetchone()[0]
                        return bool(value["claimed"])
                except self.psycopg.Error: return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(run, ("decline", "approve")))
        self.assertEqual(1, sum(results))
        self.assertIn(self.pg.execute("SELECT current_status FROM official_documents WHERE id=%s", (request["document_id"],)).fetchone()[0], ("declined", "pending_department_head"))


class SharedTerminalDeclinePostgresTest(TerminalDeclinePostgresTest):
    namespace = "edoc"
    backend_role = "edoc_backend"
