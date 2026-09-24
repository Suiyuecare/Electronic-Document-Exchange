"""Execute listing and stamp-lease RPCs in disposable local PostgreSQL databases."""
import json
import unittest

from tests import test_compose_output_postgres as fixture
from tools.official_listing_shared_forward import SOURCE, FORWARD_NAME, render_shared_forward
from tools.shared_supabase_bootstrap import transform_sql


@unittest.skipUnless(fixture.PORT, "isolated PostgreSQL list gate not enabled")
class OfficialListingPostgresTest(unittest.TestCase):
    namespace = "public"
    backend_role = "service_role"
    cleanup = classmethod(fixture.ComposeOutputPostgresTest.cleanup.__func__)

    @classmethod
    def setUpClass(cls):
        fixture.ComposeOutputPostgresTest.setUpClass.__func__(cls)
        cls.pg.execute("SET ROLE postgres")
        try:
            if cls.namespace == "public":
                cls.pg.execute((fixture.ROOT / "supabase/migrations" / SOURCE).read_text())
            else:
                cls.pg.execute("INSERT INTO edoc_private.shared_project_migration_ledger(file_name) VALUES ('20260922074613_configurable_official_workflows.sql') ON CONFLICT DO NOTHING")
                cls.pg.execute(render_shared_forward())
                cls.pg.execute(render_shared_forward())
            stamp_sql = (fixture.ROOT / "supabase/migrations/20260824061729_fix_official_stamp_latest_workflow_generation.sql").read_text()
            cls.pg.execute(stamp_sql if cls.namespace == "public" else transform_sql(stamp_sql))
        finally:
            cls.pg.execute("RESET ROLE")
        cls.pg.execute("INSERT INTO companies(id,name) VALUES ('CO-OTHER','Other synthetic company')")
        cls.pg.execute("""INSERT INTO users(id,name,status,company_id,account_source,title,logging_role_key,role,job_level,auth_user_id,finance_employee_id)
            VALUES ('ACTOR','Synthetic actor','啟用','CO-COMPOSE','finance','Synthetic title','employee','員工','employee','00000000-0000-0000-0000-000000000001','EMP-A'),
            ('OTHER','Other synthetic actor','啟用','CO-OTHER','finance','Synthetic title','employee','員工','employee','00000000-0000-0000-0000-000000000002','EMP-O')""")
        cls.pg.execute("""INSERT INTO official_documents(id,company_id,applicant_id,source_type,title,requires_stamp,output_mode,dispatch_date,current_status,current_step,created_at,updated_at)
            SELECT 'NEW-'||lpad(n::text,4,'0'),case when n%2=0 then 'CO-COMPOSE' else 'CO-OTHER' end,
              'OTHER','uploaded_pdf','Synthetic newer document',true,'physical','2026-09-24','draft','','2026-09-24 12:00:00','2026-09-24 12:00:00'
            FROM generate_series(1,1000) n""")
        cls.pg.execute("""INSERT INTO official_documents(id,company_id,applicant_id,source_type,title,requires_stamp,output_mode,dispatch_date,current_status,current_step,created_at,updated_at)
            VALUES ('TARGET','CO-COMPOSE','OTHER','uploaded_pdf','Synthetic old pending case',true,'physical','2026-09-24','draft','','2026-01-01 12:00:00','2026-01-01 12:00:00')""")
        cls.pg.execute("""INSERT INTO official_document_approval_steps(id,document_id,workflow_generation,step_order,step_key,step_name,approver_user_id,status,created_at,updated_at)
            SELECT 'HISTORY-'||n::text,'TARGET',n,1,'applicant_manager','Synthetic review',case when n=1 then 'ACTOR' else 'OTHER' end,'rejected','2026-01-01','2026-01-01'
            FROM generate_series(1,1100) n""")
        cls.pg.execute("""INSERT INTO official_document_approval_steps(id,document_id,workflow_generation,step_order,step_key,step_name,approver_user_id,status,created_at,updated_at)
            VALUES ('CURRENT-TARGET','TARGET',1101,1,'applicant_manager','Synthetic review','ACTOR','pending','2026-01-01','2026-01-01')""")
        cls.pg.execute("UPDATE official_documents SET current_status='pending_applicant_manager',current_step='applicant_manager' WHERE id='TARGET'")
        # The existing table grants/RLS remain authoritative; this RPC grants
        # no table or schema privileges and is invoked as the real backend role.
        cls.pg.execute(f"GRANT SELECT ON {cls.namespace}.users,{cls.namespace}.official_document_approval_steps,{cls.namespace}.approval_step_actor_snapshots,{cls.namespace}.official_document_dispatch_records,{cls.namespace}.official_document_stamp_requests,{cls.namespace}.official_document_approval_logs,{cls.namespace}.official_workflow_delegations,{cls.namespace}.official_document_files TO {cls.backend_role}")

    def rpc(self, request=None, role=None):
        body = {"actor_id": "ACTOR", "actor_company_id": "CO-COMPOSE", "scope": "all", "company_wide": False, "limit": 100, **(request or {})}
        with self.pg.transaction():
            self.pg.execute(f"SET LOCAL ROLE {role or self.backend_role}")
            return self.pg.execute(f"SELECT {self.namespace}.edoc_list_official_document_candidates(%s::jsonb)", (json.dumps(body),)).fetchone()[0]["items"]

    def test_01_old_pending_case_after_1000_new_cases_and_1101_steps_is_not_truncated(self):
        items = self.rpc()
        self.assertEqual(["TARGET"], [item["document"]["id"] for item in items])
        self.assertEqual(1101, len(items[0]["steps"]))
        self.assertEqual(1101, items[0]["steps"][-1]["workflow_generation"])
        self.assertEqual("pending", items[0]["steps"][-1]["status"])
        self.assertNotIn("password_hash", items[0]["delegation_users"][0])
        self.assertNotIn("email", items[0]["delegation_users"][0])
        self.assertEqual([], self.rpc({"scope": "mine"}))

    def test_02_same_company_reader_keyset_reads_all_501_without_duplicates_or_foreign_rows(self):
        ids, after = [], {}
        reads = 0
        while True:
            items = self.rpc({"company_wide": True, **after})
            reads += 1
            self.assertLessEqual(len(items), 100)
            self.assertTrue(all(item["document"]["company_id"] == "CO-COMPOSE" for item in items))
            ids.extend(item["document"]["id"] for item in items)
            if len(items) < 100:
                break
            tail = items[-1]["document"]
            after = {"after_created_at": tail["created_at"], "after_id": tail["id"]}
        self.assertEqual(501, len(ids))
        self.assertEqual(501, len(set(ids)))
        self.assertEqual("TARGET", ids[-1])
        self.assertEqual(6, reads)
        # A request-supplied company cannot broaden the database actor boundary.
        self.assertTrue(all(i["document"]["company_id"] == "CO-COMPOSE" for i in self.rpc({"company_wide": True, "actor_company_id": "CO-OTHER"})))

    def test_03_browser_roles_denied_and_rpc_remains_invoker(self):
        for role in ("anon", "authenticated"):
            with self.subTest(role=role), self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                self.rpc(role=role)
        signature = f"{self.namespace}.edoc_list_official_document_candidates(jsonb)"
        self.assertFalse(self.pg.execute("SELECT prosecdef FROM pg_proc WHERE oid=%s::regprocedure", (signature,)).fetchone()[0])
        with self.assertRaisesRegex(self.psycopg.Error, "official_list_actor_inactive"):
            self.rpc({"actor_id": "UNKNOWN"})

    def test_04_generation_aware_stamp_rpc_authorizes_current_ga_and_keeps_rejection_history(self):
        self.pg.execute("""INSERT INTO official_documents(id,company_id,applicant_id,source_type,title,requires_stamp,output_mode,dispatch_date,current_status,current_step,created_at,updated_at)
            VALUES ('STAMP-GEN','CO-COMPOSE','ACTOR','uploaded_pdf','Synthetic retry',true,'physical','2026-09-24','draft','','2026-09-24','2026-09-24')""")
        self.pg.execute("""INSERT INTO official_document_approval_steps(id,document_id,workflow_generation,step_order,step_key,step_name,approver_user_id,status)
            VALUES ('OLD-GA','STAMP-GEN',1,1,'general_affairs_review','Synthetic GA','OTHER','rejected'),
                   ('NEW-GA','STAMP-GEN',2,1,'general_affairs_review','Synthetic GA','ACTOR','approved'),
                   ('RECEIPT','STAMP-GEN',2,2,'applicant_confirm','Synthetic receipt','ACTOR','pending')""")
        self.pg.execute("INSERT INTO official_document_stamp_requests(id,document_id,company_id,status,created_at,updated_at) VALUES ('STAMP-REQUEST','STAMP-GEN','CO-COMPOSE','failed','2026-09-24','2026-09-24')")
        self.pg.execute("UPDATE official_documents SET current_status='stamping_failed',current_step='general_affairs_review' WHERE id='STAMP-GEN'")
        sql = f"SELECT {self.namespace}.edoc_claim_official_document_stamp('STAMP-GEN','STAMP-REQUEST',%s,%s,300)"
        with self.assertRaisesRegex(self.psycopg.Error, "official_stamp_retry_forbidden"):
            self.pg.execute(sql, ("A" * 64, "OTHER"))
        self.assertTrue(self.pg.execute(sql, ("A" * 64, "ACTOR")).fetchone()[0]["claimed"])
        self.assertEqual("rejected", self.pg.execute("SELECT status FROM official_document_approval_steps WHERE id='OLD-GA'").fetchone()[0])


class SharedOfficialListingPostgresTest(OfficialListingPostgresTest):
    namespace = "edoc"
    backend_role = "edoc_backend"

    def test_05_shared_forward_exact_replay_and_unrelated_hr_preserved(self):
        self.assertEqual(render_shared_forward(), (fixture.ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text())
        self.assertEqual("unchanged", self.pg.execute("SELECT payload FROM public.hr_untouched WHERE id='HR'").fetchone()[0])
        self.assertEqual(1, self.pg.execute("SELECT count(*) FROM edoc_private.shared_project_migration_ledger WHERE file_name=%s", (SOURCE,)).fetchone()[0])
        with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
            self.rpc(role="service_role")


if __name__ == "__main__":
    unittest.main()
