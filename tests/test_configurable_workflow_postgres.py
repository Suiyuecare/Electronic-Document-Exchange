"""Real PostgreSQL transaction/security checks, isolated local databases only."""
import copy
import hashlib
import json
import re
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import backend

from tests import test_editor_cross_company_workflow_postgres as fixture
from tools.configurable_workflow_shared_forward import SOURCE, FORWARD_NAME, render_shared_forward
from tools.shared_supabase_bootstrap import ROOT, transform_sql


@unittest.skipUnless(fixture.selection.resilience.fixture.PORT, "isolated PostgreSQL workflow gate not enabled")
class ConfigurableWorkflowPostgresTest(fixture.EditorCrossCompanyWorkflowPostgresTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pg.execute("SET ROLE postgres")
        try:
            if cls.namespace == "public":
                cls.pg.execute((ROOT / "supabase/migrations" / SOURCE).read_text())
            else:
                cls.pg.execute("INSERT INTO edoc_private.shared_project_migration_ledger(file_name) VALUES (%s) ON CONFLICT DO NOTHING", (fixture.MIGRATION,))
                cls.pg.execute(render_shared_forward())
                cls.pg.execute(render_shared_forward())
        finally:
            cls.pg.execute("RESET ROLE")
        for actor, role in (("EXTRA", "員工"), ("CONFIGADMIN", "執行長")):
            cls.pg.execute("INSERT INTO users(id,name,status,company_id,finance_tenant_id,email,role,account_source) VALUES (%s,%s,'啟用','CO-COMPOSE',%s,%s,%s,'finance')", (actor, actor, cls.tenant, actor.lower()+"@example.invalid", role))
        cls.pg.execute("UPDATE users SET account_source='finance' WHERE id IN ('REVIEWER','NEXT','APPLICANT')")

    def rows(self, doc, generation=None):
        return [row[0] for row in self.pg.execute("SELECT to_jsonb(s) FROM official_document_approval_steps s WHERE document_id=%s AND (%s::integer IS NULL OR workflow_generation=%s) ORDER BY step_order", (doc, generation, generation))]

    def plan(self, action="add_sign", *, target="EXTRA"):
        doc, evidence = self.workflow()
        if action == "return_previous":
            self.decide(doc, evidence)
            evidence = self.review(doc, "step-2-"+doc, "NEXT")
        current = self.pg.execute("SELECT to_jsonb(d) FROM official_documents d WHERE id=%s", (doc,)).fetchone()[0]
        old = self.rows(doc, 1)
        active = next(s for s in old if s["id"] == evidence["expected_step_id"])
        actor = "APPLICANT" if action == "withdraw" else evidence["decision_actor_user_id"]
        operation = "WFA-"+uuid.uuid4().hex
        timestamp = "2026-09-22 16:00:00"
        fresh = []
        previous = next((s for s in reversed(old) if s["step_order"] < active["step_order"] and s["status"] == "approved"), None)
        if action != "withdraw":
            for row in old:
                item = copy.deepcopy(row)
                item.update(id="new-"+row["id"], workflow_generation=2, updated_at=timestamp, created_at=timestamp)
                item["decision_evidence_json"] = {**(item.get("decision_evidence_json") or {}), "copied_from_step_id": row["id"]}
                if action == "return_previous" and row["step_order"] >= previous["step_order"]:
                    item.update(status="pending", approved_at=None, decision_actor_user_id=None, review_started_at=None,
                                decision_evidence_json={"copied_from_step_id":row["id"]})
                if action == "add_sign" and row["id"] == active["id"]:
                    item.update(status="approved", approved_at=timestamp, decision_actor_user_id=actor,
                                decision_evidence_json={**evidence, "copied_from_step_id":row["id"]})
                if action == "add_sign" and row["step_order"] > active["step_order"]:
                    item.update(step_order=row["step_order"]+1, status="pending", review_started_at=None,
                                approved_at=None, decision_actor_user_id=None, decision_evidence_json={"copied_from_step_id":row["id"]})
                fresh.append(item)
            if action == "add_sign":
                fresh.append({"id":"added-"+doc, "document_id":doc, "workflow_generation":2,
                    "step_order":active["step_order"]+1, "step_key":"approval_add_fixture", "step_name":"加簽",
                    "approver_user_id":target,"approver_name":target,"approver_role":"員工","status":"pending",
                    "comment":"", "approved_at":None,"review_started_at":timestamp,"decision_actor_user_id":None,
                    "decision_evidence_json":{"added_by_operation_id":operation},"created_at":timestamp,"updated_at":timestamp})
            fresh.sort(key=lambda s:s["step_order"])
        first = next((s for s in fresh if s["status"] == "pending"), None)
        metadata = current.get("metadata_json") or "{}"
        if isinstance(metadata, str): metadata = json.loads(metadata)
        result = {"action":action,"workflow_generation":2 if fresh else 1,"current_step_id":first["id"] if first else "", "approval_restart_required":action=="withdraw"}
        patch = {"current_status":"draft" if not first else ("pending_approval" if first["step_key"].startswith("approval_") else "pending_"+first["step_key"]),
                 "current_step":first["step_key"] if first else "", "content_revision":current["content_revision"]+(action=="withdraw"),"metadata_json":metadata}
        request = {"operation_id":operation,"request_sha256":hashlib.sha256(operation.encode()).hexdigest(),"action":action,
            "document_id":doc,"company_id":current["company_id"],"actor_id":actor,"principal_actor_id":actor,
            "expected_step_id":active["id"],"expected_status":current["current_status"],"expected_current_step":current["current_step"],
            "expected_content_revision":current["content_revision"],"expected_updated_at":current["updated_at"],
            "expected_generation":1,"workflow_generation":2 if fresh else 1,"steps":fresh,"actor_snapshots":[],
            "document_patch":patch,"timestamp":timestamp,"action_result":result,"decision_evidence":evidence,
            "approval_log":{"id":operation,"document_id":doc,"step_id":active["id"],"actor_id":actor,"actor_name":actor,
                "principal_actor_id":actor,"action":action,"comment":"Synthetic reason","decision_evidence_json":{},
                "ip_address":"","user_agent":"isolated-test","created_at":timestamp}}
        return request

    def review(self, doc, step_id, actor):
        # Build authoritative access proof for the new visit, not a stale UI ack.
        source = self.pg.execute("SELECT to_jsonb(f) FROM official_document_files f WHERE document_id=%s AND file_type='original_pdf'",(doc,)).fetchone()[0]
        prepared = self.pg.execute("SELECT to_jsonb(f) FROM official_document_files f WHERE document_id=%s AND file_type='prepared_pdf'",(doc,)).fetchone()[0]
        step = self.pg.execute("SELECT review_started_at FROM official_document_approval_steps WHERE id=%s",(step_id,)).fetchone()[0]
        stamp = self.pg.execute("SELECT to_jsonb(r) FROM official_document_stamp_requests r WHERE document_id=%s",(doc,)).fetchone()[0]
        access=[]
        files=[]
        for row in (source,prepared):
            log="ACCESS-"+uuid.uuid4().hex
            self.insert("official_document_approval_logs",id=log,document_id=doc,actor_id=actor,file_id=row["id"],action="download_file",created_at="2026-09-23 10:00:00")
            access.append({"file_id":row["id"],"access_log_id":log,"action":"download_file","accessed_at":"2026-09-23 10:00:00"})
            files.append({"id":row["id"],"type":row["file_type"],"sha256":row["file_hash"],"size":row["file_size"],"version":row["version"]})
        return {"schema_version":2,"decision_type":"approve","expected_step_id":step_id,"principal_actor_id":actor,"decision_actor_user_id":actor,
            "review_acknowledgements":{"original_reviewed":True,"edited_version_reviewed":True,"attachments_reviewed":True},
            "source_file":files[0],"prepared_file":files[1],"legacy_renderer":False,"source_bundle_sha256":"C"*64,
            "prepared_sha256":"B"*64,"manifest_sha256":"D"*64,"editor_revision_id":stamp["locked_editor_revision_id"],
            "editor_schema_version":2,"renderer_version":"fixture-renderer","attachments":[],"attachments_manifest_sha256":hashlib.sha256(b"").hexdigest(),
            "review_access":{"server_verified":True,"step_started_at":step,"required_file_ids":[f["id"] for f in files],"access_logs":access}}

    def mutate(self, request):
        return self.rpc("edoc_mutate_official_workflow",[json.dumps(request)],["::jsonb"])

    def test_add_sign_atomic_approve_then_next_and_replay(self):
        request=self.plan()
        result=self.mutate(request)
        self.assertTrue(result["committed"])
        rows=self.rows(request["document_id"],2)
        self.assertEqual(["approved","pending","pending","pending"],[s["status"] for s in rows])
        self.assertEqual("REVIEWER",rows[0]["decision_actor_user_id"])
        self.assertEqual("EXTRA",rows[1]["approver_user_id"])
        self.assertTrue(self.mutate(request)["idempotent"])
        self.assertEqual(1,self.pg.execute("SELECT count(*) FROM official_document_approval_logs WHERE id=%s",(request["operation_id"],)).fetchone()[0])
        evidence=self.review(request["document_id"],rows[1]["id"],"EXTRA")
        self.assertTrue(self.decide(request["document_id"],evidence)["claimed"])
        self.assertEqual("pending_department_head",self.pg.execute("SELECT current_status FROM official_documents WHERE id=%s",(request["document_id"],)).fetchone()[0])

    def test_return_previous_uses_new_ids_preserves_old_decisions(self):
        request=self.plan("return_previous")
        old=self.rows(request["document_id"],1)
        self.assertTrue(self.mutate(request)["committed"])
        fresh=self.rows(request["document_id"],2)
        self.assertEqual("approved",self.rows(request["document_id"],1)[0]["status"])
        self.assertEqual("pending",fresh[0]["status"])
        self.assertNotEqual(old[0]["id"],fresh[0]["id"])
        self.assertEqual("REVIEWER",fresh[0]["approver_user_id"])
        stale=copy.deepcopy(request);stale["operation_id"]+="stale";stale["approval_log"]["id"]=stale["operation_id"]
        with self.assertRaisesRegex(self.psycopg.Error,"step_conflict"):self.mutate(stale)

    def test_cross_actor_self_disabled_and_duplicate_targets_denied(self):
        for target in ("OUTSIDER","APPLICANT","REVIEWER","NEXT"):
            with self.subTest(target=target):
                request=self.plan(target=target)
                with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):self.mutate(request)
                self.assertEqual(3,len(self.rows(request["document_id"])))
        request=self.plan()
        request["actor_id"]="STRANGER";request["approval_log"]["actor_id"]="STRANGER"
        with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):self.mutate(request)

    def test_forged_plan_and_missing_evidence_roll_back(self):
        for alteration in ("drop","reassign","status","no_review","metadata","history_name"):
            request=self.plan()
            if alteration=="drop":request["steps"].pop()
            if alteration=="reassign":request["steps"][-2]["approver_user_id"]="STRANGER"
            if alteration=="status":request["document_patch"]["current_status"]="approved"
            if alteration=="no_review":request["decision_evidence"]={}
            if alteration=="metadata":request["document_patch"]["metadata_json"]={"pdf_editor_v2":False}
            if alteration=="history_name":request["steps"][0]["approver_name"]="FORGED"
            with self.subTest(alteration=alteration), self.assertRaises(self.psycopg.Error):self.mutate(request)
            self.assertEqual(3,len(self.rows(request["document_id"])))

    def withdraw_plan(self):
        state={"schemaVersion":2,"revisionNo":1,"sourceFiles":[],"pages":[],"elements":[]}
        state["manifestSha256"]=backend.canonical_editor_manifest(state)
        original_insert=self.insert
        def insert_valid_source(table,**values):
            if table=="official_document_editor_revisions":
                values.update(editor_state_json=json.dumps(state),manifest_sha256=state["manifestSha256"],renderer_version="fixture-renderer",schema_version=2)
            if table=="official_document_stamp_requests":
                values.update(editor_manifest_sha256=state["manifestSha256"],status="pending")
            return original_insert(table,**values)
        with mock.patch.object(self,"insert",side_effect=insert_valid_source):
            request=self.plan("withdraw")
        doc=request["document_id"]
        revision_id="revision-"+doc
        source=self.pg.execute("SELECT to_jsonb(r) FROM official_document_editor_revisions r WHERE id=%s",(revision_id,)).fetchone()[0]
        document=self.pg.execute("SELECT to_jsonb(d) FROM official_documents d WHERE id=%s",(doc,)).fetchone()[0]
        clone=backend.plan_official_withdraw_editor_clone(document,source,source,{"id":"APPLICANT"},request["operation_id"])
        request.update(editor_clone=clone,clone_source_revision_id=revision_id)
        return request

    def test_withdraw_clones_editor_atomically_and_preserves_locked_original(self):
        request=self.withdraw_plan()
        doc=request["document_id"]
        old=self.pg.execute("SELECT editor_state_json,manifest_sha256 FROM official_document_editor_revisions WHERE id=%s",(request["clone_source_revision_id"],)).fetchone()
        result=self.mutate(request)
        self.assertTrue(result["committed"])
        self.assertFalse(result["action_result"]["cloning"])
        self.assertEqual(("draft",1),self.pg.execute("SELECT current_status,content_revision FROM official_documents WHERE id=%s",(doc,)).fetchone())
        self.assertEqual(old,self.pg.execute("SELECT editor_state_json,manifest_sha256 FROM official_document_editor_revisions WHERE id=%s",(request["clone_source_revision_id"],)).fetchone())
        self.assertEqual(("completed",request["editor_clone"]["id"]),self.pg.execute("SELECT status,target_revision_id FROM official_document_rejection_jobs WHERE document_id=%s",(doc,)).fetchone())
        self.assertTrue(self.mutate(request)["idempotent"])
        self.assertEqual(2,self.pg.execute("SELECT count(*) FROM official_document_editor_revisions WHERE document_id=%s",(doc,)).fetchone()[0])
        self.assertEqual(("APPLICANT",),self.pg.execute("SELECT target_user_id FROM notifications WHERE id=%s",("NOTIF-WFA-"+hashlib.md5(request["operation_id"].encode()).hexdigest(),)).fetchone())

    def test_withdraw_forged_clone_or_late_stamp_rolls_back(self):
        for alteration in ("content","actor","revision","stamp_claim"):
            request=self.withdraw_plan()
            if alteration=="content":request["editor_clone"]["editor_state_json"]["elements"]=[{"forged":True}]
            if alteration=="actor":request["actor_id"]="STRANGER"
            if alteration=="revision":request["editor_clone"]["revision_no"]=99
            if alteration=="stamp_claim":self.pg.execute("UPDATE official_document_stamp_requests SET claim_token='claimed' WHERE document_id=%s",(request["document_id"],))
            with self.subTest(alteration=alteration),self.assertRaises(self.psycopg.Error):self.mutate(request)
            self.assertEqual(1,self.pg.execute("SELECT count(*) FROM official_document_editor_revisions WHERE document_id=%s",(request["document_id"],)).fetchone()[0])

    def test_approval_and_withdraw_race_have_exactly_one_winner(self):
        request=self.withdraw_plan()
        doc=request["document_id"]
        evidence=self.review(doc,request["expected_step_id"],"REVIEWER")
        # Approval must review the locked original manifest, not the new draft.
        evidence["manifest_sha256"]=self.pg.execute("SELECT editor_manifest_sha256 FROM official_document_stamp_requests WHERE document_id=%s",(doc,)).fetchone()[0]
        def run(kind):
            with self.psycopg.connect(host="127.0.0.1",port=int(fixture.selection.resilience.fixture.PORT),
                user=fixture.selection.resilience.fixture.os.getenv("EDOC_TEST_PG_USER","seniorlifepr"),dbname=self.dbname,autocommit=True) as pg:
                try:
                    with pg.transaction():
                        pg.execute(f"SET LOCAL ROLE {self.backend_role}")
                        if kind=="withdraw":
                            value=pg.execute(f"SELECT {self.namespace}.edoc_mutate_official_workflow(%s::jsonb)",(json.dumps(request),)).fetchone()[0]
                            return bool(value["committed"])
                        value=pg.execute(f"SELECT {self.namespace}.edoc_claim_official_document_approval_v3(%s,%s,'REVIEWER','REVIEWER','Concurrent review',%s::jsonb)",(doc,request["expected_step_id"],json.dumps(evidence))).fetchone()[0]
                        return bool(value["claimed"])
                except self.psycopg.Error as exc:
                    if exc.sqlstate not in ("PT409","55000"):raise
                    return False
        with ThreadPoolExecutor(max_workers=2) as pool: winners=list(pool.map(run,["withdraw","approve"]))
        self.assertEqual(1,sum(winners))

    def test_completed_review_evidence_is_immutable_and_provenance_survives(self):
        request=self.plan()
        self.mutate(request)
        added_id="added-"+request["document_id"]
        evidence=self.review(request["document_id"],added_id,"EXTRA")
        self.assertTrue(self.decide(request["document_id"],evidence)["claimed"])
        retained=self.pg.execute("SELECT decision_evidence_json FROM official_document_approval_steps WHERE id=%s",(added_id,)).fetchone()[0]
        self.assertEqual(request["operation_id"],retained["added_by_operation_id"])
        with self.assertRaisesRegex(self.psycopg.Error,"evidence_immutable"):
            self.pg.execute("UPDATE official_document_approval_steps SET decision_evidence_json='{}' WHERE id=%s",(added_id,))

    def test_null_assignment_rejected_without_corrupting_config(self):
        current=self.pg.execute("SELECT version FROM settings WHERE key='official_workflow_config'").fetchone()
        request={"operation_id":uuid.uuid4().hex,"actor_id":"CONFIGADMIN","expected_version":current[0] if current else 0,
            "config_sha256":"A"*64,"config":{"schema_version":3,"categories":{"採購合約":{"nodes":[{"id":"manager","name":"主管"}]}}}}
        with self.assertRaisesRegex(self.psycopg.Error,"node_invalid"):
            self.rpc("edoc_save_official_workflow_config",[json.dumps(request)],["::jsonb"])

    def electronic_review(self,doc,step_id,actor):
        file_id="FILE-"+doc
        access_id="ACCESS-"+uuid.uuid4().hex
        self.insert("official_document_approval_logs",id=access_id,document_id=doc,actor_id=actor,
                    file_id=file_id,action="download_file",created_at="2026-09-23 10:00:00")
        started=self.pg.execute("SELECT review_started_at FROM official_document_approval_steps WHERE id=%s",(step_id,)).fetchone()[0]
        return {"schema_version":2,"decision_type":"approve","expected_step_id":step_id,"principal_actor_id":actor,"decision_actor_user_id":actor,
            "review_acknowledgements":{"original_reviewed":True,"edited_version_reviewed":True,"attachments_reviewed":True},
            "source_file":{"id":file_id,"type":"generated_pdf","sha256":"A"*64,"version":1,"size":123},
            "legacy_renderer":True,"prepared_file":None,"attachments":[],"attachments_manifest_sha256":hashlib.sha256(b"").hexdigest(),
            "review_access":{"server_verified":True,"step_started_at":started,"required_file_ids":[file_id],
                "access_logs":[{"file_id":file_id,"access_log_id":access_id,"action":"download_file","accessed_at":"2026-09-23 10:00:00"}]}}

    def electronic_action(self,doc,action,target=None):
        document=self.pg.execute("SELECT to_jsonb(d) FROM official_documents d WHERE id=%s",(doc,)).fetchone()[0]
        generation=self.pg.execute("SELECT max(workflow_generation) FROM official_document_approval_steps WHERE document_id=%s",(doc,)).fetchone()[0]
        rows=self.rows(doc,generation)
        current=next(s for s in rows if s["status"]=="pending" and s["step_key"]==document["current_step"])
        actor=self.pg.execute("SELECT to_jsonb(u) FROM users u WHERE id=%s",(current["approver_user_id"],)).fetchone()[0]
        target_row=self.pg.execute("SELECT to_jsonb(u) FROM users u WHERE id=%s",(target,)).fetchone()[0] if target else None
        evidence=self.electronic_review(doc,current["id"],actor["id"])
        payload={"operation_id":"ELECTRONIC-"+uuid.uuid4().hex,"expected_step_id":current["id"],"comment":"Synthetic review lineage","placement":"after","target_user_id":target}
        plan=backend.plan_official_workflow_mutation(document,rows,actor,action,payload,decision_evidence=evidence,target=target_row)
        return self.mutate(plan)

    def test_real_python_plan_electronic_add_after_general_affairs_and_return_lineage(self):
        base=fixture.selection.resilience.fixture.ComposeOutputPostgresTest
        for return_again in (False,True):
            doc="electronic-"+uuid.uuid4().hex
            payload=base.submission(self,doc)
            base.call_submit(self,payload)
            added=self.electronic_action(doc,"add_sign","EXTRA")
            self.assertTrue(added["committed"])
            if return_again:
                self.assertTrue(self.electronic_action(doc,"return_previous")["committed"])
                generation=self.pg.execute("SELECT max(workflow_generation) FROM official_document_approval_steps WHERE document_id=%s",(doc,)).fetchone()[0]
                ga=next(s for s in self.rows(doc,generation) if s["step_key"]=="general_affairs_review")
                self.assertTrue(self.decide(doc,self.electronic_review(doc,ga["id"],"REVIEWER"))["claimed"])
            current=self.pg.execute("SELECT s.id,s.approver_user_id FROM official_document_approval_steps s JOIN official_documents d ON d.id=s.document_id WHERE s.document_id=%s AND s.step_key=d.current_step AND s.status='pending' ORDER BY workflow_generation DESC LIMIT 1",(doc,)).fetchone()
            result=self.decide(doc,self.electronic_review(doc,current[0],current[1]))
            self.assertTrue(result["claimed"])
            self.assertEqual(("pending_general_affairs_dispatch","FILE-"+doc),self.pg.execute("SELECT current_status,stamped_file_id FROM official_documents WHERE id=%s",(doc,)).fetchone())
            self.assertEqual(1,self.pg.execute("SELECT count(*) FROM official_document_dispatch_records WHERE document_id=%s",(doc,)).fetchone()[0])
            self.assertEqual(0,self.pg.execute("SELECT count(*) FROM official_document_stamp_requests WHERE document_id=%s",(doc,)).fetchone()[0])

    def test_mutation_rpc_and_helpers_are_private(self):
        for name in ("edoc_mutate_official_workflow","edoc_save_official_workflow_config"):
            signature=f"{self.namespace}.{name}(jsonb)"
            for role in ("anon","authenticated"):
                self.assertFalse(self.pg.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')",(role,signature)).fetchone()[0])
            self.assertTrue(self.pg.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')",(self.backend_role,signature)).fetchone()[0])
        for role in ("anon","authenticated",self.backend_role):
            self.assertFalse(self.pg.execute("SELECT has_function_privilege(%s,'edoc_private.official_workflow_step_status(text)','EXECUTE')",(role,)).fetchone()[0])

    def test_settings_version_cas_admin_only_and_idempotence(self):
        row=self.pg.execute("SELECT version FROM settings WHERE key='official_workflow_config'").fetchone()
        request={"operation_id":uuid.uuid4().hex,"actor_id":"CONFIGADMIN","expected_version":row[0] if row else 0,
            "config_sha256":"A"*64,"config":{"schema_version":3,"categories":{"採購合約":{"nodes":[{"id":"manager","name":"主管","assignee":{"type":"role","role_key":"applicant_manager"}}]}}}}
        result=self.rpc("edoc_save_official_workflow_config",[json.dumps(request)],["::jsonb"])
        self.assertEqual(request["expected_version"]+1,result["version"])
        self.assertTrue(self.rpc("edoc_save_official_workflow_config",[json.dumps(request)],["::jsonb"])["idempotent"])
        stale=copy.deepcopy(request);stale["operation_id"]=uuid.uuid4().hex
        with self.assertRaisesRegex(self.psycopg.Error,"config_conflict"):self.rpc("edoc_save_official_workflow_config",[json.dumps(stale)],["::jsonb"])
        stale["actor_id"]="REVIEWER"
        with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):self.rpc("edoc_save_official_workflow_config",[json.dumps(stale)],["::jsonb"])

    def test_normalized_config_custom_first_node_submits_and_completes(self):
        config = backend.normalize_official_workflow_config({"categories": {"採購合約": {"nodes": [
            {"id": "named_reviewer", "name": "指定審核", "assignee": {"type": "user", "user_id": "EXTRA"}}
        ]}}})
        current = self.pg.execute("SELECT version FROM settings WHERE key='official_workflow_config'").fetchone()
        request = {"operation_id": uuid.uuid4().hex, "actor_id": "CONFIGADMIN", "expected_version": current[0] if current else 0,
                   "config": config, "config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()}
        saved = self.rpc("edoc_save_official_workflow_config", [json.dumps(request)], ["::jsonb"])
        configured = backend.configured_official_workflow_steps(saved["config"], "採購合約")
        self.assertEqual(["approval_named_reviewer", "general_affairs_review", "applicant_confirm"], [s["key"] for s in configured])
        base = fixture.selection.resilience.fixture.ComposeOutputPostgresTest
        doc = "configured-" + uuid.uuid4().hex
        payload = base.submission(self, doc)
        original = self.pg.execute("SELECT to_jsonb(d) FROM official_documents d WHERE id=%s", (doc,)).fetchone()[0]
        locked = backend.locked_official_config_metadata(original, saved["config"], "採購合約", configured)
        payload["document_patch"] = {"metadata_json": json.dumps(locked)}
        payload["steps"] = [{"id": f"custom-{i}-{doc}", "document_id": doc, "step_order": i + 1,
            "step_key": step["key"], "step_name": step["name"], "workflow_generation": 1, "status": "pending",
            "approver_user_id": ["EXTRA", "REVIEWER", "APPLICANT"][i]} for i, step in enumerate(configured)]
        payload.update(first_step_id=payload["steps"][0]["id"], first_step_key=configured[0]["key"], first_status="pending_approval")
        self.assertTrue(base.call_submit(self, payload)["committed"])
        for row in payload["steps"][:-1]:
            self.assertTrue(self.decide(doc, self.electronic_review(doc, row["id"], row["approver_user_id"]))["claimed"])
        self.assertEqual("pending_general_affairs_dispatch", self.pg.execute("SELECT current_status FROM official_documents WHERE id=%s", (doc,)).fetchone()[0])
        stored = json.loads(self.pg.execute("SELECT metadata_json FROM official_documents WHERE id=%s", (doc,)).fetchone()[0])
        self.assertEqual(saved["version"], stored["official_seal"]["workflow_config_snapshot"]["version"])

    def test_actual_submit_withdraw_resubmit_uses_new_operation_and_generation(self):
        base = fixture.selection.resilience.fixture.ComposeOutputPostgresTest
        doc = "withdraw-resubmit-" + uuid.uuid4().hex
        payload = base.submission(self, doc)
        before = self.pg.execute("SELECT to_jsonb(d) FROM official_documents d WHERE id=%s", (doc,)).fetchone()[0]
        operation, audit, _, _ = backend._supabase_official_submission_operation_ids(before, "APPLICANT", workflow_generation=1)
        payload.update(operation_id=operation, expected_content_revision=0,
                       document_patch={"metadata_json": json.dumps({"official_seal": {"submission_generation": 1}})})
        payload["submit_log"]["id"] = operation
        payload["submit_log"]["decision_evidence_json"]["operation_id"] = operation
        payload["submit_audit"]["id"] = audit
        self.assertTrue(base.call_submit(self, payload)["committed"])
        self.assertTrue(base.call_submit(self, payload)["idempotent"])
        document = self.pg.execute("SELECT to_jsonb(d) FROM official_documents d WHERE id=%s", (doc,)).fetchone()[0]
        self.assertEqual(operation, backend._supabase_official_submission_operation_ids(document, "APPLICANT")[0])
        applicant = self.pg.execute("SELECT to_jsonb(u) FROM users u WHERE id='APPLICANT'").fetchone()[0]
        withdrawal = backend.plan_official_workflow_mutation(document, self.rows(doc), applicant, "withdraw", {
            "operation_id": uuid.uuid4().hex, "expected_step_id": payload["first_step_id"],
            "expected_content_revision": document["content_revision"], "comment": "Withdraw before resubmission"})
        self.assertTrue(self.mutate(withdrawal)["committed"])
        draft = self.pg.execute("SELECT to_jsonb(d) FROM official_documents d WHERE id=%s", (doc,)).fetchone()[0]
        fresh = copy.deepcopy(payload)
        operation2, audit2, _, _ = backend._supabase_official_submission_operation_ids(draft, "APPLICANT", workflow_generation=2)
        self.assertNotEqual(operation, operation2)
        fresh.update(operation_id=operation2, workflow_generation=2, expected_status="draft",
                     expected_updated_at=draft["updated_at"], expected_content_revision=draft["content_revision"],
                     document_patch={"metadata_json": json.dumps({"official_seal": {"submission_generation": 2}})})
        for step in fresh["steps"]:
            step["id"] += "-resubmit"
            step["workflow_generation"] = 2
        fresh["first_step_id"] = fresh["steps"][0]["id"]
        fresh["submit_log"]["id"] = operation2
        fresh["submit_log"]["decision_evidence_json"].update(operation_id=operation2, workflow_generation=2)
        fresh["submit_audit"]["id"] = audit2
        self.assertTrue(base.call_submit(self, fresh)["committed"])
        self.assertTrue(base.call_submit(self, fresh)["idempotent"])
        self.assertTrue(all(row["status"] == "skipped" for row in self.rows(doc, 1)))
        self.assertTrue(all(row["status"] == "pending" for row in self.rows(doc, 2)))
        active = self.pg.execute("SELECT to_jsonb(d) FROM official_documents d WHERE id=%s", (doc,)).fetchone()[0]
        self.assertEqual(operation2, backend._supabase_official_submission_operation_ids(active, "APPLICANT")[0])
        self.assertEqual(2, self.pg.execute("SELECT count(*) FROM official_document_approval_logs WHERE document_id=%s AND action='submit'", (doc,)).fetchone()[0])
        self.assertTrue(self.decide(doc, self.electronic_review(doc, fresh["first_step_id"], "REVIEWER"))["claimed"])
        self.assertEqual("pending_general_affairs_dispatch", self.pg.execute("SELECT current_status FROM official_documents WHERE id=%s", (doc,)).fetchone()[0])

    def test_composed_cross_company_add_sign_is_not_an_implicit_scope_expansion(self):
        base = fixture.selection.resilience.fixture.ComposeOutputPostgresTest
        doc = "compose-scope-" + uuid.uuid4().hex
        payload = base.submission(self, doc)
        base.call_submit(self, payload)
        with self.pg.transaction(force_rollback=True):
            self.pg.execute("UPDATE users SET company_id='CO-SECOND' WHERE id='EXTRA'")
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                with self.pg.transaction():
                    self.electronic_action(doc, "add_sign", "EXTRA")
            self.assertEqual(2, len(self.rows(doc)))
            self.assertEqual("pending_general_affairs_review", self.pg.execute("SELECT current_status FROM official_documents WHERE id=%s", (doc,)).fetchone()[0])

    def workflow_release_gate(self):
        name = "fresh_bootstrap_smoke.sql" if self.namespace == "public" else "shared_project_cutover_checks.sql"
        sql = (ROOT / "supabase/verification" / name).read_text()
        return re.search(r"do \$configurable_workflow_gate\$.*?\$configurable_workflow_gate\$;", sql, re.S).group(0)

    def test_release_gate_passes_and_rejects_rpc_acl_drift(self):
        self.pg.execute(self.workflow_release_gate())
        for mutation, code in (
            (f"GRANT EXECUTE ON FUNCTION {self.namespace}.edoc_mutate_official_workflow(jsonb) TO anon", "browser_rpc_grant"),
            (f"ALTER FUNCTION {self.namespace}.edoc_save_official_workflow_config(jsonb) SET search_path=public", "rpc_security_mismatch"),
            (f"ALTER TABLE {self.namespace}.official_document_approval_steps DISABLE TRIGGER preserve_official_decision_evidence", "evidence_trigger_missing"),
        ):
            with self.subTest(code=code), self.pg.transaction(force_rollback=True):
                self.pg.execute(mutation)
                with self.assertRaisesRegex(self.psycopg.Error, code):
                    with self.pg.transaction(): self.pg.execute(self.workflow_release_gate())


@unittest.skipUnless(fixture.selection.resilience.fixture.PORT, "isolated PostgreSQL workflow gate not enabled")
class SharedConfigurableWorkflowPostgresTest(ConfigurableWorkflowPostgresTest):
    namespace="edoc"
    backend_role="edoc_backend"


class ConfigurableWorkflowForwardContractTest(unittest.TestCase):
    def test_shared_forward_is_exact(self):
        self.assertEqual(render_shared_forward(),(ROOT/"supabase/shared-project-migrations"/FORWARD_NAME).read_text())

    def test_forward_only_changes_own_namespace(self):
        sql=transform_sql((ROOT/"supabase/migrations"/SOURCE).read_text())
        self.assertNotIn("public.official_documents",sql)
        self.assertIn("to edoc_backend",sql)
        self.assertNotIn("to authenticated",sql.lower())
