"""Run draft metadata RPC against disposable local databases, never production."""
import json
import unittest
from unittest import mock
import backend
from tests import test_compose_output_postgres as fixture
from tools.workspace_drafts_shared_forward import SOURCE, FORWARD_NAME, render_shared_forward


@unittest.skipUnless(fixture.PORT, "isolated PostgreSQL draft gate not enabled")
class WorkspaceDraftPostgresTest(unittest.TestCase):
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
                cls.pg.execute("INSERT INTO edoc_private.shared_project_migration_ledger(file_name) VALUES ('20260924154315_scoped_official_document_listing.sql') ON CONFLICT DO NOTHING")
                cls.pg.execute(render_shared_forward())
                cls.pg.execute(render_shared_forward())
        finally:
            cls.pg.execute("RESET ROLE")
        cls.pg.execute(f"GRANT SELECT ON {cls.namespace}.users,{cls.namespace}.official_document_compose_drafts TO {cls.backend_role}")
        cls.pg.execute("INSERT INTO users(id,name,status,company_id) VALUES ('ACTOR','Synthetic actor','啟用','CO-COMPOSE'),('OTHER','Synthetic other','啟用','CO-COMPOSE')")
        cls.pg.execute("""INSERT INTO official_document_compose_drafts(id,applicant_id,company_id,revision,snapshot_json,snapshot_hash,archived,created_at,updated_at)
          SELECT 'C-'||lpad(n::text,3,'0'),'ACTOR','CO-COMPOSE',1,jsonb_build_object('values',jsonb_build_object('#subject','Synthetic '||n::text)),'hash',false,'2026-10-14','2026-10-14'
          FROM generate_series(1,81) n""")
        cls.pg.execute("""INSERT INTO official_documents(id,company_id,applicant_id,source_type,title,subject,requires_stamp,output_mode,dispatch_date,current_status,current_step,created_at,updated_at)
          VALUES ('D','CO-COMPOSE','ACTOR','uploaded_pdf','Synthetic draft','Draft',true,'physical','2026-10-14','draft','','2026-10-14','2026-10-14'),
          ('OTHER-D','CO-COMPOSE','OTHER','uploaded_pdf','Hidden draft','Hidden',true,'physical','2026-10-14','draft','','2026-10-14','2026-10-14')""")

    def rpc(self, **kwargs):
        request = {"actor_id": "ACTOR", "company_id": "CO-COMPOSE", "page_size": 25, **kwargs}
        with self.pg.transaction():
            self.pg.execute(f"SET LOCAL ROLE {self.backend_role}")
            return self.pg.execute(f"SELECT {self.namespace}.edoc_workspace_drafts(%s::jsonb)", (json.dumps(request),)).fetchone()[0]

    def test_01_total_and_pages_are_complete_without_snapshot_payload(self):
        self.assertEqual({"total": 82, "items": []}, self.rpc(summary=True))
        rows, after = [], {}
        while True:
            page = self.rpc(**after)
            self.assertEqual(82, page["total"])
            rows.extend(page["items"][:25])
            if len(page["items"]) <= 25: break
            row = page["items"][24]
            after = {"after_at": row["updated_at"], "after_key": row["key"]}
        self.assertEqual(82, len({row["key"] for row in rows}))
        self.assertTrue(all("snapshot_json" not in row for row in rows))

    def test_02_linked_cloud_dedup_and_submitted_case_is_excluded(self):
        with self.pg.transaction(force_rollback=True):
            self.pg.execute("UPDATE official_document_compose_drafts SET snapshot_json=snapshot_json||'{\"draftRequestId\":\"D\"}'::jsonb WHERE id in ('C-001','C-002')")
            self.assertEqual(80, self.rpc(summary=True)["total"])
            self.pg.execute("UPDATE official_documents SET current_status='pending_applicant_manager' WHERE id='D'")
            self.assertEqual(79, self.rpc(summary=True)["total"])

    def test_03_anonymous_authenticated_wrong_company_and_inactive_refused(self):
        for role in ("anon", "authenticated"):
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                with self.pg.transaction():
                    self.pg.execute(f"SET LOCAL ROLE {role}")
                    self.pg.execute(f"SELECT {self.namespace}.edoc_workspace_drafts('{{}}')")
        with self.assertRaisesRegex(self.psycopg.Error, "actor_inactive"):
            self.rpc(company_id="FOREIGN")
        with self.pg.transaction(force_rollback=True):
            self.pg.execute("UPDATE users SET status='停用' WHERE id='ACTOR'")
            with self.assertRaisesRegex(self.psycopg.Error, "actor_inactive"):
                self.rpc()
        signature = f"{self.namespace}.edoc_workspace_drafts(jsonb)"
        self.assertFalse(self.pg.execute("SELECT prosecdef FROM pg_proc WHERE oid=%s::regprocedure", (signature,)).fetchone()[0])

    def test_approval_tabs_fetch_once_past_1000_irrelevant_history_rows(self):
        with self.pg.transaction(force_rollback=True):
            # Exercise the deployed candidate RPC, then the independent Python
            # projector, rather than emulating the new SQL in a mocked page.
            tables = ("users", "official_document_approval_steps", "approval_step_actor_snapshots",
                      "official_document_dispatch_records", "official_document_stamp_requests",
                      "official_document_approval_logs", "official_workflow_delegations", "official_document_files")
            self.pg.execute(f"GRANT SELECT ON {','.join(self.namespace + '.' + table for table in tables)} TO {self.backend_role}")
            self.pg.execute("DELETE FROM official_documents")
            self.pg.execute("""INSERT INTO official_documents(id,company_id,applicant_id,source_type,title,current_status,current_step,created_at,updated_at)
              SELECT 'HISTORY-'||lpad(n::text,4,'0'),'CO-COMPOSE','OTHER','uploaded_pdf','Synthetic history','closed','','2026-10-14 12:00:00','2026-10-14'
              FROM generate_series(1,1000) n""")
            self.pg.execute("""INSERT INTO official_documents(id,company_id,applicant_id,source_type,title,current_status,current_step,created_at,updated_at)
              VALUES ('MINE','CO-COMPOSE','ACTOR','uploaded_pdf','Synthetic','closed','','2026-01-01 12:00:00','2026-10-14'),
              ('REJECTED','CO-COMPOSE','OTHER','uploaded_pdf','Synthetic','rejected','','2026-01-01 12:00:00','2026-10-14'),
              ('ACTED-LOG','CO-COMPOSE','OTHER','uploaded_pdf','Synthetic','closed','','2026-01-01 12:00:00','2026-10-14'),
              ('ACTED-STEP','CO-COMPOSE','OTHER','uploaded_pdf','Synthetic','closed','','2026-01-01 12:00:00','2026-10-14'),
              ('PENDING','CO-COMPOSE','OTHER','uploaded_pdf','Synthetic','pending_applicant_manager','applicant_manager','2026-01-01 12:00:00','2026-10-14')""")
            self.pg.execute("""INSERT INTO official_document_approval_logs(id,document_id,actor_id,action,created_at)
              VALUES ('LOG','ACTED-LOG','ACTOR','return_previous','2026-10-14')""")
            self.pg.execute("""INSERT INTO official_document_approval_steps(id,document_id,step_order,step_key,step_name,approver_user_id,decision_actor_user_id,status,created_at,updated_at)
              VALUES ('DECIDED','ACTED-STEP',1,'applicant_manager','Synthetic','OTHER','ACTOR','approved','2026-10-14','2026-10-14'),
              ('PENDING-STEP','PENDING',1,'applicant_manager','Synthetic','ACTOR',NULL,'pending','2026-10-14','2026-10-14'),
              ('ASSIGNED-ONLY','HISTORY-1000',1,'applicant_manager','Synthetic','ACTOR',NULL,'approved','2026-10-14','2026-10-14')""")
            def request(method, path, payload):
                self.assertEqual((method, path), ("POST", "rpc/edoc_list_official_document_candidates"))
                with self.pg.transaction():
                    self.pg.execute(f"SET LOCAL ROLE {self.backend_role}")
                    return self.pg.execute(f"SELECT {self.namespace}.edoc_list_official_document_candidates(%s::jsonb)",
                                           (json.dumps(payload["p_request"]),)).fetchone()[0]
            session = {"user": {"id": "ACTOR", "company_id": "CO-COMPOSE"}, "permissions": ["official_documents.all_records"]}
            for view, expected in (("mine", ["MINE"]), ("rejected", ["REJECTED"]),
                                   ("acted", ["ACTED-STEP", "ACTED-LOG"]), ("pending", ["PENDING"])):
                with self.subTest(view=view), mock.patch.object(backend, "supabase_request", side_effect=request) as rpc:
                    page = backend.supabase_list_official_documents({"scope": ["all"], "view": [view], "page_size": ["25"]}, session)
                    self.assertEqual(expected, [row["id"] for row in page["items"]])
                    self.assertFalse(page["has_more"])
                    self.assertEqual(1, rpc.call_count)


class SharedWorkspaceDraftPostgresTest(WorkspaceDraftPostgresTest):
    namespace = "edoc"
    backend_role = "edoc_backend"

    def test_04_forward_hash_and_unrelated_hr_unchanged(self):
        self.assertEqual(render_shared_forward(), (fixture.ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text())
        self.assertEqual("unchanged", self.pg.execute("SELECT payload FROM public.hr_untouched WHERE id='HR'").fetchone()[0])
        self.assertEqual(1, self.pg.execute("SELECT count(*) FROM edoc_private.shared_project_migration_ledger WHERE file_name=%s", (SOURCE,)).fetchone()[0])
