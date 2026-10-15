"""Actual local PostgreSQL dispatch transactions; no hosted credentials/network."""
import concurrent.futures
import copy
import hashlib
import json
import os
import re
import threading
import unittest
from pathlib import Path

import backend
import internal_dispatch_workflow
from tests import test_compose_output_postgres as fixture
from tools.shared_supabase_bootstrap import transform_sql, sha256_text
from tools.internal_dispatch_shared_forward import FORWARD_NAME, render_shared_forward

MIGRATION = "20261015144049_internal_dispatch_workflow_integrity.sql"


class InternalDispatchMigrationContractTest(unittest.TestCase):
    def test_shared_forward_and_cutover_bind_exact_migration_inventory(self):
        source = (fixture.ROOT / "supabase/migrations" / MIGRATION).read_text()
        source_hash = sha256_text(source)
        transformed_hash = sha256_text(transform_sql(source))
        forward = (fixture.ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text()
        self.assertEqual(render_shared_forward(), forward)

        manifest = json.loads((fixture.ROOT / "supabase/verification/migration_manifest.json").read_text())
        names = manifest["migrations"] + ["roles.sql"]
        self.assertIn(MIGRATION, names)
        inventory_hash = hashlib.sha256("\n".join(sorted(names)).encode()).hexdigest()
        checks = (fixture.ROOT / "supabase/verification/shared_project_cutover_checks.sql").read_text()
        ledger_check = checks.split("'migration_ledger_complete',", 1)[1].split(
            "'atomic_submission_step_evidence_contract',", 1
        )[0]
        self.assertIn(f"shared_project_migration_ledger) = {len(names)}", ledger_check)
        self.assertIn("string_agg(file_name, E'\\n' order by file_name)", ledger_check)
        self.assertIn(f"= '{inventory_hash}'", ledger_check)
        self.assertRegex(
            ledger_check,
            rf"file_name='{re.escape(MIGRATION)}'\s+and source_sha256='{source_hash}'"
            rf"\s+and transformed_sha256='{transformed_hash}'",
        )
        self.assertIn("('r','p','v','m')) = 100", checks)
        dispatch_gate = checks.split("do $internal_dispatch_integrity_gate$", 1)[1].split(
            "$internal_dispatch_integrity_gate$;", 1
        )[0]
        self.assertIn("edoc.internal_dispatch_mutations", dispatch_gate)
        self.assertIn("relrowsecurity", dispatch_gate)
        self.assertIn("edoc_backend", dispatch_gate)
        self.assertIn("internal_dispatch_rpc_browser_grant", dispatch_gate)
        for rpc in (
            "edoc_internal_dispatch_scope_v1",
            "edoc_dispatch_log_v1",
            "edoc_list_internal_dispatches_v1",
            "edoc_create_internal_dispatch_v1",
            "edoc_close_internal_dispatch_v1",
            "edoc_reply_internal_dispatch_v1",
            "edoc_assign_inbound_with_dispatch_v1",
        ):
            self.assertIn(rpc, dispatch_gate)


@unittest.skipUnless(fixture.PORT, "isolated PostgreSQL gate not enabled")
class InternalDispatchPostgresTest(unittest.TestCase):
    namespace = "public"
    backend_role = "service_role"

    @classmethod
    def setUpClass(cls):
        fixture.ComposeOutputPostgresTest.setUpClass.__func__(cls)
        sql = (fixture.ROOT / "supabase/migrations" / MIGRATION).read_text()
        if cls.namespace == "public":
            cls.pg.execute(sql)
        else:
            cls.pg.execute(render_shared_forward())
            cls.pg.execute(render_shared_forward())  # Ledger replay is non-mutating.
        # Match the existing exact runtime matrix, not a broad fixture grant.
        grants = (fixture.ROOT / "supabase/migrations/20260827063824_lock_runtime_table_data_api_grants.sql").read_text()
        needed = {"users", "companies", "inbound_documents", "inbound_document_attachments", "official_documents", "internal_dispatches", "internal_dispatch_recipients", "internal_dispatch_replies", "internal_dispatch_logs", "notifications", "file_objects", "audit_logs", "department_registry"}
        for verb, tables in re.findall(r"grant (select|insert|update|delete) on table(.*?)to service_role;", grants, re.S):
            names = [name for name in re.findall(r"public\.(\w+)", tables) if name in needed]
            if names: cls.pg.execute(f"GRANT {verb} ON " + ",".join(cls.namespace + "." + name for name in names) + f" TO {cls.backend_role}")
        # Shared schemas are deny-by-default; the real new ledger policy is
        # used, while old runtime policies are installed by the base fixture.
        cls.pg.execute("INSERT INTO companies(id,name,finance_tenant_id,finance_entity_id,source_system,status) VALUES ('CO-P1','去識別化公司','TENANT-P1','E-P1','finance','active'),('CO-FOREIGN','別公司','TENANT-X','E-X','finance','active')")
        cls.users = {}
        for uid,role,company,tenant in (("GA","總務","CO-P1","TENANT-P1"),("OLD","員工","CO-P1","TENANT-P1"),("NEW","員工","CO-P1","TENANT-P1"),("OTHER","員工","CO-P1","TENANT-P1"),("FOREIGN","總務","CO-FOREIGN","TENANT-X")):
            user = {"id": uid, "name": "去識別化"+uid, "email": uid.lower()+"@example.invalid", "unit": "測試部門", "role": role, "status": "啟用", "account_source": "finance", "company_id": company, "finance_tenant_id": tenant, "external_account_payload_json": "{}"}
            cls.pg.execute("INSERT INTO users(id,name,email,unit,role,status,account_source,company_id,finance_tenant_id,external_account_payload_json) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", tuple(user.values()))
            cls.users[uid] = user

    @classmethod
    def cleanup(cls):
        fixture.ComposeOutputPostgresTest.cleanup.__func__(cls)

    def setUp(self):
        self.pg.execute("TRUNCATE internal_dispatch_mutations,internal_dispatch_replies,internal_dispatch_recipients,internal_dispatch_logs,internal_dispatches,inbound_document_mutations,inbound_documents,notifications,audit_logs CASCADE")
        self.pg.execute("UPDATE users SET status='啟用'")

    def connection(self):
        return self.psycopg.connect(host="127.0.0.1", port=int(fixture.PORT), user=os.getenv("EDOC_TEST_PG_USER", "seniorlifepr"), dbname=self.dbname, autocommit=True)

    def rpc(self, name, args, *, conn=None, role=None):
        connection = conn or self.pg
        with connection.transaction():
            connection.execute(f"SET LOCAL ROLE {role or self.backend_role}")
            values = [self.psycopg.types.json.Jsonb(v) if isinstance(v, (dict, list)) else v for v in args]
            return connection.execute(f"SELECT {self.namespace}.{name}({','.join(['%s']*len(values))})", values).fetchone()[0]

    def plan(self, key="postgres-dispatch-001", actor="GA", recipients=None, **kw):
        recipients = recipients or [("OLD", True)]
        payload = {"idempotency_key": key, "subject": "去識別化派文", "body": "隔離測試", "reply_required": True, "reply_due_days": 3,
                   "recipients": [{"user_id": uid, "action_required": required} for uid,required in recipients], **kw}
        return internal_dispatch_workflow.create_plan(backend, payload, self.users[actor], [(p,self.users[uid]) for p,(uid,_) in zip(payload["recipients"],recipients)])

    def create(self, **kw):
        return self.rpc("edoc_create_internal_dispatch_v1", [kw.get("actor", "GA"), self.plan(**kw)])

    def reply(self, dispatch, actor="OLD", conn=None):
        return self.rpc("edoc_reply_internal_dispatch_v1", [actor, dispatch, {"id":"REPLY-"+actor, "reply_text":"去識別化回覆"}], conn=conn)

    def close(self, dispatch, actor="GA", conn=None):
        return self.rpc("edoc_close_internal_dispatch_v1", [actor,dispatch,False,"去識別化結案"], conn=conn)

    def test_request_replay_concurrency_and_changed_payload_conflict(self):
        barrier = threading.Barrier(2)
        def create(_):
            with self.connection() as conn:
                barrier.wait(timeout=5)
                return self.rpc("edoc_create_internal_dispatch_v1", ["GA",self.plan()], conn=conn)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create,range(2)))
        self.assertEqual(results[0]["id"],results[1]["id"])
        self.assertEqual([False,True],sorted(x["replayed"] for x in results))
        for table in ("internal_dispatches","internal_dispatch_recipients","notifications","internal_dispatch_logs","internal_dispatch_mutations"):
            self.assertEqual(1,self.pg.execute(f"SELECT count(*) FROM {table}").fetchone()[0],table)
        with self.assertRaisesRegex(self.psycopg.Error,"internal_dispatch_idempotency_conflict"):
            self.rpc("edoc_create_internal_dispatch_v1",["GA",self.plan(body="不同內容")])
        self.assertNotEqual(results[0]["id"],self.create(key="postgres-dispatch-002")["id"])

    def test_mid_transaction_invalid_recipient_rolls_back_then_retry(self):
        plan = self.plan(recipients=[("OLD",True),("NEW",True)])
        plan["recipients"][1]["recipient_user_id"]="FOREIGN"
        with self.assertRaisesRegex(self.psycopg.Error,"internal_dispatch_recipient_company_forbidden"):
            self.rpc("edoc_create_internal_dispatch_v1",["GA",plan])
        for table in ("internal_dispatches","internal_dispatch_recipients","notifications","internal_dispatch_logs","internal_dispatch_mutations"):
            self.assertEqual(0,self.pg.execute(f"SELECT count(*) FROM {table}").fetchone()[0],table)
        self.assertFalse(self.create(recipients=[("OLD",True),("NEW",True)])["replayed"])

    def test_pending_close_reply_and_idempotent_closed_history(self):
        case=self.create()["id"]
        with self.assertRaisesRegex(self.psycopg.Error,"internal_dispatch_pending_replies"): self.close(case)
        self.assertEqual(("sent","pending"),self.pg.execute("SELECT status,reply_status FROM internal_dispatches WHERE id=%s",(case,)).fetchone())
        with self.assertRaisesRegex(self.psycopg.Error,"internal_dispatch_close_forbidden"): self.close(case,"OLD")
        self.reply(case); self.assertFalse(self.close(case)["replayed"]); self.assertTrue(self.close(case)["replayed"])
        self.assertEqual(1,self.pg.execute("SELECT count(*) FROM internal_dispatch_logs WHERE action='close_internal_dispatch'").fetchone()[0])
        with self.assertRaisesRegex(self.psycopg.Error,"internal_dispatch_closed"): self.reply(case)
        information=self.create(key="postgres-information-001",recipients=[("OLD",False)])["id"]
        self.assertFalse(self.close(information)["replayed"])

    def test_reply_close_concurrent_never_discards_pending_reply(self):
        case=self.create()["id"]; barrier=threading.Barrier(2)
        def run(action):
            with self.connection() as conn:
                barrier.wait(timeout=5)
                try:
                    self.reply(case,conn=conn) if action=="reply" else self.close(case,conn=conn)
                    return action,"ok"
                except self.psycopg.Error as exc:
                    return action,str(exc).splitlines()[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: results=dict(pool.map(run,["reply","close"]))
        self.assertEqual("ok",results["reply"])
        self.assertIn(results["close"],{"ok","internal_dispatch_pending_replies"})
        self.assertEqual(1,self.pg.execute("SELECT count(*) FROM internal_dispatch_replies").fetchone()[0])
        self.assertEqual("replied",self.pg.execute("SELECT status FROM internal_dispatch_recipients").fetchone()[0])

    def test_scope_before_pagination_351_old_cases_and_foreign_denied(self):
        # Latest 400 belong to another recipient and 400 to another company.
        self.pg.execute("INSERT INTO internal_dispatches(id,title,subject,sender_user_id,created_at,updated_at,status) SELECT 'ROW-'||lpad(n::text,4,'0'),'測試','測試',case when n>751 then 'FOREIGN' else 'GA' end,case when n<=351 then '2020-01-01 00:00:00' else '2030-01-01 00:00:00' end,'2020-01-01','sent' FROM generate_series(1,1151) n")
        self.pg.execute("INSERT INTO internal_dispatch_recipients(id,dispatch_id,recipient_user_id,action_required,status,created_at,updated_at) SELECT 'R-'||lpad(n::text,4,'0'),'ROW-'||lpad(n::text,4,'0'),case when n<=351 then 'OLD' when n<=751 then 'OTHER' else 'FOREIGN' end,true,'pending','2020-01-01','2020-01-01' FROM generate_series(1,1151) n")
        found=[]; after=(None,None)
        while True:
            rows=self.rpc("edoc_list_internal_dispatches_v1",["OLD",False,True,"sent",51,*after])["items"]
            found.extend(row["id"] for row in rows[:50])
            if len(rows)<=50: break
            after=(rows[49]["created_at"],rows[49]["id"])
        self.assertEqual(351,len(found)); self.assertEqual(351,len(set(found))); self.assertIn("ROW-0001",found)
        broad=self.rpc("edoc_list_internal_dispatches_v1",["GA",True,False,"",101,None,None])["items"]
        self.assertTrue(all(row["sender_user_id"]!="FOREIGN" for row in broad))
        for row in broad: self.assertIn("pending_reply_count",row)
        with self.assertRaisesRegex(self.psycopg.Error,"internal_dispatch_company_forbidden"): self.close("ROW-1151")

    def inbound(self):
        self.pg.execute("INSERT INTO inbound_documents(id,company_id,finance_tenant_id,receive_no,sender_name,subject,created_by,assignee_user_id,assignee_name,status,mutation_version,created_at,updated_at) VALUES('INB-P1','CO-P1','TENANT-P1','TEST-P1','去識別化單位','去識別化來文','GA','OLD','去識別化OLD','assigned',1,'2020-01-01','2020-01-01')")

    def reassign(self, actor="NEW", key="postgres-handoff-001", conn=None, version=1):
        return self.rpc("edoc_assign_inbound_with_dispatch_v1",["assign",key,"a"*64,"GA","INB-P1",version,{"assignee_user_id":actor}],conn=conn)

    def test_handoff_pending_only_replay_audit_no_scope_widening(self):
        self.inbound()
        pending=self.create(inbound_document_id="INB-P1")["id"]
        finished=self.create(key="postgres-complete-001",inbound_document_id="INB-P1")["id"]
        self.reply(finished)
        with self.assertRaisesRegex(self.psycopg.Error,"inbound_assignee_scope_forbidden"): self.reassign("FOREIGN","postgres-handoff-cross")
        self.assertEqual("OLD",self.pg.execute("SELECT assignee_user_id FROM inbound_documents").fetchone()[0])
        self.pg.execute("UPDATE users SET status='停用' WHERE id='OLD'")
        result=self.reassign(); self.assertEqual("NEW",result["item"]["assignee_user_id"])
        self.assertTrue(self.reassign()["replayed"])
        rows=self.pg.execute("SELECT recipient_user_id,action_required,status FROM internal_dispatch_recipients WHERE dispatch_id=%s ORDER BY recipient_user_id",(pending,)).fetchall()
        self.assertEqual([("NEW",True,"pending"),("OLD",False,"reassigned")],rows)
        self.assertEqual([("OLD",True,"replied")],self.pg.execute("SELECT recipient_user_id,action_required,status FROM internal_dispatch_recipients WHERE dispatch_id=%s",(finished,)).fetchall())
        self.assertEqual("OLD",self.pg.execute("SELECT replier_user_id FROM internal_dispatch_replies").fetchone()[0])
        self.assertEqual(1,self.pg.execute("SELECT count(*) FROM internal_dispatch_logs WHERE action='reassign_internal_dispatch'").fetchone()[0])
        self.assertEqual(1,self.pg.execute("SELECT count(*) FROM notifications WHERE type='內部派文交接'").fetchone()[0])
        with self.assertRaisesRegex(self.psycopg.Error,"internal_dispatch_company_forbidden"): self.reply(pending,"OLD")
        self.reply(pending,"NEW")
        self.assertEqual("reply_completed",self.pg.execute("SELECT status FROM internal_dispatches WHERE id=%s",(pending,)).fetchone()[0])

    def test_handoff_and_old_reply_race_preserves_exact_one_obligation(self):
        self.inbound(); case=self.create(inbound_document_id="INB-P1")["id"]; barrier=threading.Barrier(2)
        def run(action):
            with self.connection() as conn:
                barrier.wait(timeout=5)
                try:
                    self.reassign(conn=conn) if action=="handoff" else self.reply(case,conn=conn)
                    return action,"ok"
                except self.psycopg.Error as exc: return action,str(exc).splitlines()[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: result=dict(pool.map(run,["handoff","reply"]))
        self.assertEqual("ok",result["handoff"])
        self.assertIn(result["reply"],{"ok","internal_dispatch_reply_forbidden"})
        required=self.pg.execute("SELECT recipient_user_id,status FROM internal_dispatch_recipients WHERE action_required").fetchall()
        self.assertIn(required, [[("OLD","replied")],[("NEW","pending")]])

    def test_browser_roles_cannot_execute_backend_only_rpcs(self):
        for role in ("anon","authenticated"):
            with self.subTest(role=role),self.assertRaises(self.psycopg.Error):
                self.rpc("edoc_create_internal_dispatch_v1",["GA",self.plan()],role=role)
        self.assertEqual(0,self.pg.execute("SELECT count(*) FROM internal_dispatches").fetchone()[0])
        if self.namespace=="edoc": self.assertEqual("unchanged",self.pg.execute("SELECT payload FROM public.hr_untouched").fetchone()[0])

    def test_previously_replied_recipient_can_accept_new_handoff_obligation(self):
        self.inbound(); case=self.create(inbound_document_id="INB-P1",recipients=[("OLD",True),("NEW",True)])["id"]
        self.reply(case,"NEW"); original=self.pg.execute("SELECT recipient_id FROM internal_dispatch_replies").fetchone()[0]
        self.reassign()
        pending=self.pg.execute("SELECT id FROM internal_dispatch_recipients WHERE recipient_user_id='NEW' AND status='pending'").fetchone()[0]
        self.assertNotEqual(original,pending)
        self.rpc("edoc_reply_internal_dispatch_v1",["NEW",case,{"id":"REPLY-NEW-AFTER-HANDOFF","reply_text":"承接後完成"}])
        self.assertEqual(0,self.pg.execute("SELECT count(*) FROM internal_dispatch_recipients WHERE action_required AND status NOT IN ('replied','reassigned')").fetchone()[0])
        self.assertEqual({original,pending},{x[0] for x in self.pg.execute("SELECT recipient_id FROM internal_dispatch_replies")})
        self.assertFalse(self.close(case)["replayed"])

    def test_handoff_back_to_original_recipient_has_one_pending_obligation(self):
        self.inbound(); case=self.create(inbound_document_id="INB-P1")["id"]
        self.reassign(); self.reassign("OLD","postgres-handoff-return",version=2)
        self.assertEqual([("OLD","pending")],self.pg.execute("SELECT recipient_user_id,status FROM internal_dispatch_recipients WHERE action_required").fetchall())
        self.assertEqual(2,self.pg.execute("SELECT count(*) FROM internal_dispatch_recipients WHERE status='reassigned'").fetchone()[0])
        with self.assertRaisesRegex(self.psycopg.Error,"internal_dispatch_reply_forbidden"): self.reply(case,"NEW")
        self.reply(case,"OLD"); self.close(case)

    def test_list_preserves_source_attachment_metadata_and_handoff_hint(self):
        self.inbound(); case=self.create(inbound_document_id="INB-P1")["id"]
        self.pg.execute("INSERT INTO inbound_document_attachments(id,inbound_document_id,file_name,file_mime_type,file_size,file_hash,created_at) VALUES ('ATT-P1','INB-P1','去識別化來源.pdf','application/pdf',42,'test-hash','2020-01-01')")
        self.pg.execute("UPDATE users SET status='停用' WHERE id='OLD'")
        page=self.rpc("edoc_list_internal_dispatches_v1",["GA",True,False,"",51,None,None])
        source=page["items"][0]["inbound_document"]
        self.assertEqual("INB-P1",source["id"]); self.assertTrue(source["handover_required"])
        self.assertEqual("ATT-P1",source["attachments"][0]["id"])
        self.assertEqual("去識別化來源.pdf",source["attachments"][0]["file_name"])
        self.assertEqual({},source["metadata"])


@unittest.skipUnless(fixture.PORT, "isolated PostgreSQL gate not enabled")
class InternalDispatchSharedPostgresTest(InternalDispatchPostgresTest):
    namespace="edoc"
    backend_role="edoc_backend"


if __name__=="__main__": unittest.main()
