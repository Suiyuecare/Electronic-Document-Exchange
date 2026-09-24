"""Latest-generation dispatch owners against the complete current RPC chain."""
import unittest

from tests import test_official_receipt_confirmation_postgres as fixture
from tools.dispatch_generation_shared_forward import SOURCE, FORWARD_NAME, render_shared_forward
from tools.shared_supabase_bootstrap import ROOT


@unittest.skipUnless(fixture.fixture.selection.resilience.fixture.PORT, "isolated PostgreSQL dispatch generation gate not enabled")
class OfficialDispatchGenerationPostgresTest(unittest.TestCase):
    namespace = "public"
    backend_role = "service_role"
    cleanup = classmethod(fixture.OfficialReceiptConfirmationPostgresTest.cleanup.__func__)
    create = fixture.OfficialReceiptConfirmationPostgresTest.create
    case = fixture.OfficialReceiptConfirmationPostgresTest.case
    insert = fixture.OfficialReceiptConfirmationPostgresTest.insert
    file = fixture.OfficialReceiptConfirmationPostgresTest.file
    workflow = fixture.OfficialReceiptConfirmationPostgresTest.workflow
    rpc = fixture.OfficialReceiptConfirmationPostgresTest.rpc

    @classmethod
    def setUpClass(cls):
        fixture.OfficialReceiptConfirmationPostgresTest.setUpClass.__func__(cls)
        cls.signatures = [f"{cls.namespace}.edoc_create_official_document_dispatch_record(text,text)",
                          f"{cls.namespace}.edoc_complete_official_document_stamp(text,text,text,text)"]
        cls.before = {s: cls.pg.execute("SELECT pg_get_functiondef(oid),prosecdef,proconfig,proacl FROM pg_proc WHERE oid=%s::regprocedure", (s,)).fetchone() for s in cls.signatures}
        cls.pg.execute("SET ROLE postgres")
        try:
            if cls.namespace == "public":
                sql = (ROOT / "supabase/migrations" / SOURCE).read_text()
                cls.pg.execute(sql)
                cls.pg.execute(sql)
            else:
                cls.pg.execute(render_shared_forward())
                cls.pg.execute(render_shared_forward())
        finally:
            cls.pg.execute("RESET ROLE")

    def stamped_case(self, *, completing=False, missing_current_ga=False):
        doc, _ = self.workflow()
        self.pg.execute("UPDATE official_document_approval_steps SET workflow_generation=2,status='approved' WHERE document_id=%s AND step_key<>'applicant_confirm'", (doc,))
        self.pg.execute("UPDATE official_document_approval_steps SET workflow_generation=2 WHERE document_id=%s AND step_key='applicant_confirm'", (doc,))
        if not missing_current_ga:
            self.pg.execute("UPDATE official_document_approval_steps SET step_key='general_affairs_review' WHERE id=%s", ("step-1-"+doc,))
        self.insert("official_document_approval_steps", id="old-ga-"+doc, document_id=doc,
                    workflow_generation=1, step_order=99, step_key="general_affairs_review",
                    step_name="Old synthetic GA", approver_user_id="NEXT", status="approved")
        self.pg.execute("UPDATE official_documents SET dispatch_method='physical_mail_by_general_affairs',current_status=%s,current_step=%s WHERE id=%s",
                        ("stamping" if completing else "stamped", "auto_stamp" if completing else "general_affairs_dispatch", doc))
        if completing:
            self.pg.execute("UPDATE official_document_stamp_requests SET status='stamping',claim_token=%s,claim_owner_id='REVIEWER',claim_expires_at=now()+interval '5 minutes' WHERE document_id=%s", ("A"*64,doc))
            stamped = self.file(doc,"stamped_pdf","F"*64)
            self.pg.execute("UPDATE official_document_files SET stamp_request_id=%s WHERE id=%s", ("request-"+doc,stamped["id"]))
        return doc

    def test_current_ga_receives_dispatch_even_when_old_approved_ga_has_higher_order(self):
        doc = self.stamped_case()
        result = self.rpc("edoc_create_official_document_dispatch_record", [doc,"REVIEWER"])
        owner = self.pg.execute("SELECT dispatch_owner_user_id FROM official_document_dispatch_records WHERE id=%s", (result["dispatch_record_id"],)).fetchone()[0]
        self.assertEqual("REVIEWER", owner)
        self.assertEqual("approved", self.pg.execute("SELECT status FROM official_document_approval_steps WHERE id=%s", ("old-ga-"+doc,)).fetchone()[0])

    def test_stamp_completion_assigns_current_ga_and_preserves_audit_history(self):
        doc = self.stamped_case(completing=True)
        result = self.rpc("edoc_complete_official_document_stamp", [doc,"request-"+doc,"A"*64,"stamped_pdf-"+doc])
        self.assertTrue(result["completed"])
        self.assertEqual("REVIEWER", self.pg.execute("SELECT dispatch_owner_user_id FROM official_document_dispatch_records WHERE id=%s", (result["dispatch_record_id"],)).fetchone()[0])
        self.assertEqual("approved", self.pg.execute("SELECT status FROM official_document_approval_steps WHERE id=%s", ("old-ga-"+doc,)).fetchone()[0])

    def test_missing_current_ga_never_falls_back_to_old_ga(self):
        for completing in (False,True):
            doc = self.stamped_case(completing=completing,missing_current_ga=True)
            name,args = ("edoc_complete_official_document_stamp",[doc,"request-"+doc,"A"*64,"stamped_pdf-"+doc]) if completing else ("edoc_create_official_document_dispatch_record",[doc,"REVIEWER"])
            with self.subTest(completing=completing), self.assertRaisesRegex(self.psycopg.Error,"official_dispatch_owner_unresolved"):
                self.rpc(name,args)
            self.assertEqual(0,self.pg.execute("SELECT count(*) FROM official_document_dispatch_records WHERE document_id=%s",(doc,)).fetchone()[0])

    def test_current_deployed_guards_security_and_grants_are_preserved_exactly(self):
        old_clause = "and step.step_key = 'general_affairs_review'\n       and step.status = 'approved'"
        new_clause = ("and step.step_key = 'general_affairs_review'\n       and step.workflow_generation = (\n"
                      "         select max(current_generation.workflow_generation)\n"
                      f"         from {self.namespace}.official_document_approval_steps current_generation\n"
                      "         where current_generation.document_id = v_document.id\n       )\n"
                      "       and step.status = 'approved'")
        for signature,before in self.before.items():
            after = self.pg.execute("SELECT pg_get_functiondef(oid),prosecdef,proconfig,proacl FROM pg_proc WHERE oid=%s::regprocedure", (signature,)).fetchone()
            self.assertEqual(before[0].replace(old_clause,new_clause),after[0])
            self.assertEqual(before[1:],after[1:])
            self.assertTrue(after[1], "Existing definer model must not accidentally change")
            for role in ("anon","authenticated"):
                self.assertFalse(self.pg.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')", (role,signature)).fetchone()[0])


class SharedOfficialDispatchGenerationPostgresTest(OfficialDispatchGenerationPostgresTest):
    namespace = "edoc"
    backend_role = "edoc_backend"

    def test_shared_forward_exact_and_hr_untouched(self):
        self.assertEqual(render_shared_forward(), (ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text())
        self.assertEqual("unchanged", self.pg.execute("SELECT payload FROM public.hr_untouched WHERE id='HR'").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
