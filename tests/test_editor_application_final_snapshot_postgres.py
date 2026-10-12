"""True public/shared PostgreSQL CAS races in disposable loopback databases."""
from __future__ import annotations

import concurrent.futures
import copy
import json
import re
import unittest
import uuid
from unittest import mock

import backend
import editor_application
from tests import test_compose_output_postgres as fixture
from tools.shared_supabase_bootstrap import transform_sql
from tools.editor_metadata_seal_shared_forward import FORWARDS, render_shared_forward

SOURCE = "20261012115431_editor_application_final_snapshot.sql"
SEAL_SOURCE = "20261012114854_explicit_seal_owner_policy_and_continuous_geometry.sql"


@unittest.skipUnless(fixture.PORT, "isolated PostgreSQL gate not enabled")
class EditorApplicationFinalSnapshotPostgresTest(unittest.TestCase):
    namespace = "public"
    backend_role = "service_role"
    cleanup = classmethod(fixture.ComposeOutputPostgresTest.cleanup.__func__)
    create = fixture.ComposeOutputPostgresTest.create

    @classmethod
    def setUpClass(cls):
        fixture.ComposeOutputPostgresTest.setUpClass.__func__(cls)
        cls.pg.execute("SET ROLE postgres")
        try:
            for name in ("20260911133144_compose_resilience_drafts_revision.sql",):
                source = (fixture.ROOT / "supabase/migrations" / name).read_text()
                cls.pg.execute(source if cls.namespace == "public" else transform_sql(source))
            # The old isolated projection already creates tables but carries no
            # real policies/constraints for this newly shipped seal policy table.
            cls.pg.execute(f"DROP TABLE {cls.namespace}.company_seal_policies")
            cls.pg.execute(f"ALTER TABLE {cls.namespace}.seal_reference_options ADD CONSTRAINT fixture_reference_option_kind_code UNIQUE(option_type,code)")
            for source_name in (SEAL_SOURCE, SOURCE):
                source = (fixture.ROOT / "supabase/migrations" / source_name).read_text()
                cls.pg.execute(source if cls.namespace == "public" else transform_sql(source))
            cls.pg.execute(f"GRANT SELECT ON {cls.namespace}.users,{cls.namespace}.finance_organization_units,{cls.namespace}.department_registry,{cls.namespace}.company_seals,{cls.namespace}.company_seal_files,{cls.namespace}.approval_step_actor_snapshots TO {cls.backend_role}")
        finally:
            cls.pg.execute("RESET ROLE")
        cls.tenant = "SYNTHETIC-APPLICATION-TENANT"
        cls.pg.execute("UPDATE companies SET finance_tenant_id=%s,finance_entity_id='E1',source_system='finance',status='active' WHERE id='CO-COMPOSE'", (cls.tenant,))
        cls.pg.execute("INSERT INTO companies(id,name,finance_tenant_id,finance_entity_id,source_system,status) VALUES ('CO-SECOND','Synthetic second company',%s,'E2','finance','active')", (cls.tenant,))
        cls.pg.execute("INSERT INTO users(id,name,status,company_id,email,finance_tenant_id) VALUES ('APPLICANT','Synthetic applicant','啟用','CO-COMPOSE','applicant@example.invalid',%s)", (cls.tenant,))
        for number, company in ((1, "CO-COMPOSE"), (2, "CO-SECOND")):
            cls.pg.execute("INSERT INTO finance_organization_units(id,finance_tenant_id,finance_unit_id,code,name,unit_type,status,entity_scope_mode,entity_codes) VALUES (%s,%s,%s,%s,%s,'department','active','explicit',%s::jsonb)", (f"UNIT-{number}", cls.tenant, f"SYNTHETIC-UNIT-{number}", f"D{number}", f"Synthetic unit {number}", json.dumps([f"E{number}"])))

    def row(self, table, identity):
        cursor = self.pg.execute(f"SELECT * FROM {self.namespace}.{table} WHERE id=%s", (identity,))
        values = cursor.fetchone()
        return dict(zip((column.name for column in cursor.description), values)) if values else None

    def insert(self, table, values):
        from psycopg import sql
        names = list(values)
        self.pg.execute(sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(sql.Identifier(self.namespace),sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,names)),sql.SQL(',').join(sql.Placeholder() for _ in names)), [json.dumps(value) if isinstance(value,(dict,list)) else value for value in values.values()])

    def seed(self, *, with_seals=False):
        suffix = uuid.uuid4().hex
        identity = "ODAPP-" + suffix
        context = backend.require_official_seal_classification({"document_category":"服務委託合約"})
        metadata = {"pdf_editor_v2":True,"official_seal":context,"future_rule_inputs":{"company_id":"CO-COMPOSE","department":"Synthetic unit 1"}}
        self.create(identity,source_type="uploaded_pdf",document_type="electronic_seal_pdf_editor_v2",output_mode="physical",requires_stamp=True,
          metadata_json=json.dumps(metadata),applicant_department_id="D1",applicant_department_name="Synthetic unit 1",dispatch_unit="Synthetic unit 1",title="Synthetic title",subject="Synthetic title",description="Synthetic reason",request_reason="Synthetic reason",content_revision=0)
        state = {"schemaVersion":2,"revisionNo":1,"sourceFiles":[{"assetId":"PDF-"+suffix,"fileName":"synthetic.pdf","kind":"source_pdf","sha256":"A"*64}],
          "pages":[{"pageId":f"P-{i}-{suffix}","sourceAssetId":"PDF-"+suffix,"sourcePageIndex":i,"widthPt":backend.EDOC_A4_WIDTH_PT,"heightPt":backend.EDOC_A4_HEIGHT_PT,"cropBox":[0,0,backend.EDOC_A4_WIDTH_PT,backend.EDOC_A4_HEIGHT_PT],"rotation":0,"order":i} for i in range(2)],
          "elements":[{"id":"TEXT-"+suffix,"kind":"text","pageId":"P-0-"+suffix,"x":40,"y":40,"width":100,"height":20,"rotation":0,"opacity":1,"zIndex":1,"properties":{"text":"Synthetic text"}}],"manifestSha256":""}
        if with_seals:
            seal_id, file_id = "SEAL-"+suffix, "SEALFILE-"+suffix
            self.insert("company_seals",{"id":seal_id,"company_id":"CO-COMPOSE","seal_category":"general_seal","seal_size_type":"large_seal","is_active":True})
            obj_id="SEALOBJ-"+suffix
            seal_path=f"seal-vault/seals/{seal_id}/SEAL-VAULT/synthetic.png"
            self.insert("file_objects",{"id":obj_id,"document_id":"SEAL-VAULT","file_name":"synthetic.png","storage_key":seal_path,"mime_type":"image/png","sha256":"B"*64,"size_bytes":128,"scan_status":"passed"})
            self.insert("company_seal_files",{"id":file_id,"seal_id":seal_id,"file_object_id":obj_id,"file_hash":"B"*64,"file_size":128,"file_mime_type":"image/png","file_storage_key":seal_path,"dimension_policy_version":"institution-seal-v2-calibrated","pixel_width":400,"pixel_height":400,"source_aspect_ratio":1,"render_width_mm":30,"render_height_mm":30,"dimension_validated":True})
            size = round(30*72/25.4,4)
            for part in range(2):
                state["elements"].append({"id":f"SEAM-{part}-"+suffix,"kind":"seal","pageId":state["pages"][part]["pageId"],"x":round(backend.EDOC_A4_WIDTH_PT-size,4) if part==0 else 0,"y":round(backend.EDOC_A4_HEIGHT_PT-180-size,4),"width":size,"height":size,"rotation":0,"opacity":1,"zIndex":10+part,
                  "properties":{"sealId":seal_id,"sealFileId":file_id,"sealFileSha256":"B"*64,"seamGroupId":"SEAMGROUP-"+suffix,"seamMode":"pair","seamPartCount":2,"seamPartIndex":part}})
        state = backend.validate_editor_state(state)
        revision = {"id":"REV-"+suffix,"document_id":identity,"revision_no":1,"parent_revision_id":None,"schema_version":2,"editor_state_json":json.dumps(state),"manifest_sha256":state["manifestSha256"],"renderer_version":backend.EDOC_EDITOR_RENDERER_VERSION,"created_by":"APPLICANT","created_at":"2026-10-12 12:00:00"}
        self.insert("official_document_editor_revisions",revision)
        return identity,revision

    def application_request(self, identity, latest, *, company="CO-COMPOSE", title="Final title"):
        document = self.row("official_documents",identity)
        department = {"id":"D1" if company=="CO-COMPOSE" else "D2","name":"Synthetic unit 1" if company=="CO-COMPOSE" else "Synthetic unit 2"}
        category = "採購合約"
        context = backend.require_official_seal_classification({"document_category":category})
        metadata = backend._official_correction_metadata(document,context,"",{})
        metadata["future_rule_inputs"].update(company_id=company,department=department["name"])
        state = json.loads(latest["editor_state_json"])
        state,removed = editor_application.remove_foreign_seals(state,company,lambda identity:self.row("company_seals",identity))
        revision = backend._supabase_editor_revision_payload(identity,state,{"id":"APPLICANT"},latest=latest) if removed else None
        patch = {"company_id":company,"title":title,"subject":title,"description":"Final reason","request_reason":"Final reason",
          "applicant_department_id":department["id"],"applicant_department_name":department["name"],"dispatch_unit":department["name"],"workflow_template_key":context["workflow_template_key"],"metadata_json":json.dumps(metadata)}
        return {"document_id":identity,"actor_id":"APPLICANT","company_id":company,"expected_content_revision":document["content_revision"],"expected_editor_revision_id":latest["id"],"expected_editor_manifest_sha256":latest["manifest_sha256"],"patch":patch,"revision":revision,"updated_fields":["title","document_category","company_id"],"removed_seal_element_ids":removed,"log_id":"LOG-"+uuid.uuid4().hex,"actor_name":"Synthetic applicant","timestamp":"2026-10-12 12:01:00"}

    def rpc(self,name,request,conn=None,role=None):
        connection=conn or self.pg
        with connection.transaction():
            connection.execute(f"SET LOCAL ROLE {role or self.backend_role}")
            return connection.execute(f"SELECT {self.namespace}.{name}(%s::jsonb)",(json.dumps(request),)).fetchone()[0]

    def save_request(self,identity,latest):
        state=json.loads(latest["editor_state_json"])
        state["elements"][0]["properties"]["text"]="Final PDF edit"
        return {"document_id":identity,"actor_id":"APPLICANT","expected_content_revision":self.row("official_documents",identity)["content_revision"],"expected_editor_revision_id":latest["id"],"expected_editor_manifest_sha256":latest["manifest_sha256"],"revision":backend._supabase_editor_revision_payload(identity,state,{"id":"APPLICANT"},latest=latest)}

    def prepared_request(self,identity,latest):
        document=self.row("official_documents",identity)
        suffix=uuid.uuid4().hex
        obj,file_id,asset_id="OBJ-"+suffix,"FILE-"+suffix,"ASSET-"+suffix
        path="editor-final/"+identity+"/"+asset_id+"/"+"C"*64+".pdf"
        self.insert("file_objects",{"id":obj,"document_id":identity,"file_name":"synthetic-prepared.pdf","storage_key":path,"bucket":"edoc-private","mime_type":"application/pdf","sha256":"C"*64,"size_bytes":128})
        self.insert("official_document_files",{"id":file_id,"document_id":identity,"file_object_id":obj,"file_type":"prepared_pdf","file_hash":"C"*64,"file_size":128,"version":1})
        metadata={"application_content_revision":document["content_revision"],"application_company_id":document["company_id"],"application_snapshot":editor_application.application_snapshot(document),"manifest_sha256":latest["manifest_sha256"],"renderer_version":backend.EDOC_EDITOR_RENDERER_VERSION}
        asset={"id":asset_id,"document_id":identity,"editor_revision_id":latest["id"],"asset_kind":"prepared_pdf","file_object_id":obj,"official_file_id":file_id,"file_name":"synthetic-prepared.pdf","mime_type":"application/pdf","size_bytes":128,"sha256":"C"*64,"expected_sha256":"C"*64,"storage_bucket":"edoc-private","storage_path":path,"upload_status":"finalized","scan_status":"passed","preflight_status":"passed","page_count":2,"metadata_json":json.dumps(metadata),"created_by":"APPLICANT","created_at":"2026-10-12 12:00:00","finalized_at":"2026-10-12 12:00:00"}
        return {"document_id":identity,"actor_id":"APPLICANT","expected_content_revision":document["content_revision"],"expected_editor_revision_id":latest["id"],"expected_editor_manifest_sha256":latest["manifest_sha256"],"asset":asset}

    def submit_request(self,identity,latest,prepared):
        document=self.row("official_documents",identity)
        state=json.loads(latest["editor_state_json"])
        request_id="STAMP-"+identity
        positions=[]
        for index,element in enumerate([item for item in state["elements"] if item["kind"]=="seal"],1):
            props=element["properties"]
            positions.append({"id":f"POS-{index}-"+identity,"request_id":request_id,"seal_id":props["sealId"],"page":index,"page_ref":element["pageId"],"x":element["x"],"y":element["y"],"width":element["width"],"height":element["height"],"rotation":0,"opacity":1,"z_index":element["zIndex"],"locked_seal_file_id":props["sealFileId"],"locked_seal_sha256":props["sealFileSha256"],"locked_render_width_pt":element["width"],"locked_render_height_pt":element["height"],"locked_dimension_policy_version":"institution-seal-v2-calibrated","order_index":index})
        first=positions[0]
        stamp={"id":request_id,"document_id":identity,"company_id":document["company_id"],"requested_by":"APPLICANT","status":"pending","seal_id":first["seal_id"],"stamp_page":1,"stamp_x":first["x"],"stamp_y":first["y"],"stamp_width":first["width"],"stamp_height":first["height"],"locked_editor_revision_id":latest["id"],"locked_source_sha256":"A"*64,"prepared_file_id":prepared["asset"]["official_file_id"],"prepared_sha256":"C"*64,"editor_manifest_sha256":latest["manifest_sha256"],"editor_schema_version":2,"renderer_version":backend.EDOC_EDITOR_RENDERER_VERSION,"editor_locked_at":"2026-10-12 12:03:00"}
        operation,step="SUBMIT-"+identity,"STEP-"+identity
        return {"operation_id":operation,"document_id":identity,"company_id":document["company_id"],"applicant_id":"APPLICANT","expected_status":"draft","expected_updated_at":document["updated_at"],"expected_content_revision":document["content_revision"],"submitted_at":"2026-10-12 12:03:00","first_step_id":step,"first_step_key":"general_affairs_review","first_status":"pending_general_affairs_review","workflow_generation":1,"stamp_request":stamp,"stamp_positions":positions,"actor_snapshots":[],"steps":[{"id":step,"document_id":identity,"step_order":1,"step_key":"general_affairs_review","step_name":"Synthetic general affairs","approver_user_id":"REVIEWER","workflow_generation":1,"status":"pending"}],"submit_log":{"id":operation,"document_id":identity,"actor_id":"APPLICANT","action":"submit","created_at":"2026-10-12 12:03:00","decision_evidence_json":{"operation_id":operation,"workflow_generation":1,"stamp_request_id":request_id}},"submit_audit":{"id":"AUDIT-"+identity,"target_id":identity,"created_at":"2026-10-12 12:03:00"}}

    def test_01_company_switch_preserves_source_state_removes_full_seam_and_actor_identity(self):
        identity,latest=self.seed(with_seals=True)
        request=self.application_request(identity,latest,company="CO-SECOND")
        result=self.rpc("edoc_update_editor_application",request)
        self.assertEqual(result["content_revision"],1)
        self.assertEqual(len(result["removed_seal_element_ids"]),2)
        document=self.row("official_documents",identity)
        self.assertEqual((document["company_id"],document["applicant_id"],document["applicant_department_id"]),("CO-SECOND","APPLICANT","D2"))
        saved=self.row("official_document_editor_revisions",result["editor_revision_id"])
        before,after=json.loads(latest["editor_state_json"]),json.loads(saved["editor_state_json"])
        self.assertEqual(before["sourceFiles"],after["sourceFiles"])
        self.assertEqual(before["pages"],after["pages"])
        self.assertEqual([item["kind"] for item in after["elements"]],["text"])
        self.assertEqual(self.row("users","APPLICANT")["company_id"],"CO-COMPOSE")

    def test_02_past_submit_legacy_snapshot_rejected_and_foreign_tenant_block_company_changes(self):
        for source in ("submit","official_documents","official_document_application"):
            identity,latest=self.seed()
            if source=="submit": self.insert("official_document_approval_logs",{"id":"OLD-"+identity,"document_id":identity,"actor_id":"APPLICANT","action":"submit"})
            else: self.insert("approval_step_actor_snapshots",{"id":"OLD-"+identity,"source_id":identity,"source_type":source})
            with self.assertRaisesRegex(self.psycopg.Error,"official_document_company_forbidden"):
                self.rpc("edoc_update_editor_application",self.application_request(identity,latest,company="CO-SECOND"))
            self.assertEqual(self.row("official_documents",identity)["content_revision"],0)
        identity,latest=self.seed()
        self.pg.execute("UPDATE official_documents SET current_status='rejected' WHERE id=%s",(identity,))
        result=self.rpc("edoc_update_editor_application",self.application_request(identity,latest))
        self.assertEqual(result["content_revision"],1)
        with self.assertRaisesRegex(self.psycopg.Error,"official_document_company_forbidden"):
            self.rpc("edoc_update_editor_application",self.application_request(identity,latest,company="CO-SECOND"))
        with self.pg.transaction(force_rollback=True):
            self.pg.execute("UPDATE companies SET finance_tenant_id='FOREIGN' WHERE id='CO-SECOND'")
            with self.assertRaisesRegex(self.psycopg.Error,"official_editor_company_forbidden"):
                self.rpc("edoc_update_editor_application",self.application_request(identity,latest,company="CO-SECOND"))

    def test_03_metadata_vs_pdf_save_two_connections_one_snapshot_wins(self):
        identity,latest=self.seed()
        requests=[("edoc_update_editor_application",self.application_request(identity,latest)),("edoc_save_editor_revision",self.save_request(identity,latest))]
        def execute(item):
            with self.psycopg.connect(host="127.0.0.1",port=int(fixture.PORT),user="postgres",dbname=self.dbname,autocommit=True) as connection:
                try: return ("ok",self.rpc(*item,conn=connection))
                except self.psycopg.Error as error: return ("conflict",str(error).splitlines()[0])
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(execute,requests))
        self.assertEqual(["conflict","ok"],sorted(result[0] for result in results))
        self.assertRegex(next(result[1] for result in results if result[0]=="conflict"),"(compose_content_revision_conflict|editor_revision_conflict)")

    def test_04_preflight_inflight_application_change_has_zero_completed_witness(self):
        identity,latest=self.seed()
        old=self.prepared_request(identity,latest)
        self.rpc("edoc_update_editor_application",self.application_request(identity,latest))
        with self.assertRaisesRegex(self.psycopg.Error,"compose_content_revision_conflict"):
            self.rpc("edoc_commit_editor_preflight",old)
        self.assertEqual(self.pg.execute("SELECT count(*) FROM official_document_editor_assets WHERE id=%s",(old["asset"]["id"],)).fetchone()[0],0)
        fresh=self.prepared_request(identity,latest)
        result=self.rpc("edoc_commit_editor_preflight",fresh)
        self.assertEqual(json.loads(result["metadata_json"])["application_content_revision"],1)

    def test_05_stale_tokens_unknown_fields_forbidden_actor_and_browser_are_zero_write(self):
        identity,latest=self.seed()
        original=self.application_request(identity,latest)
        for change,code in (({"expected_content_revision":5},"compose_content_revision_conflict"),({"expected_editor_manifest_sha256":"0"*64},"editor_revision_conflict"),({"actor_id":"ANOTHER"},"official_editor_write_forbidden")):
            with self.assertRaisesRegex(self.psycopg.Error,code): self.rpc("edoc_update_editor_application",{**original,**change})
        forbidden=copy.deepcopy(original); forbidden["patch"]["current_status"]="approved"
        with self.assertRaisesRegex(self.psycopg.Error,"editor_application_fields_invalid"): self.rpc("edoc_update_editor_application",forbidden)
        for name in ("edoc_update_editor_application","edoc_save_editor_revision","edoc_commit_editor_preflight"):
            for role in ("anon","authenticated"):
                with self.assertRaises(self.psycopg.errors.InsufficientPrivilege): self.rpc(name,original,role=role)
        self.assertEqual(self.row("official_documents",identity)["content_revision"],0)

    def test_06_shipping_gate_rejects_browser_grants_definer_and_unsafe_searchpath(self):
        name="fresh_bootstrap_smoke.sql" if self.namespace=="public" else "shared_project_cutover_checks.sql"
        gate=re.search(r'do \$editor_application_seal_policy_gate\$.*?\$editor_application_seal_policy_gate\$;', (fixture.ROOT/"supabase/verification"/name).read_text(),re.S).group(0)
        self.pg.execute(gate)
        signature=f"{self.namespace}.edoc_update_editor_application(jsonb)"
        for mutation,code in ((f"GRANT EXECUTE ON FUNCTION {signature} TO anon","browser_rpc_grant"),(f"ALTER FUNCTION {signature} SECURITY DEFINER","security_mismatch"),(f"ALTER FUNCTION {signature} RESET search_path","security_mismatch")):
            with self.assertRaisesRegex(self.psycopg.Error,code):
                with self.pg.transaction(): self.pg.execute(mutation);self.pg.execute(gate)
        self.pg.execute(gate)
        if self.namespace=="edoc": self.assertEqual([("HR","unchanged")],self.pg.execute("SELECT * FROM public.hr_untouched").fetchall())

    def test_07_changed_application_old_prepared_bytes_cannot_submit_final_workflow(self):
        identity,latest=self.seed(with_seals=True)
        prepared=self.prepared_request(identity,latest)
        self.rpc("edoc_commit_editor_preflight",prepared)
        self.rpc("edoc_update_editor_application",self.application_request(identity,latest))
        # Even if a caller knows the newest content token, it must produce and
        # inspect the fresh prepared witness belonging to those exact fields.
        submit=self.submit_request(identity,latest,prepared)
        with self.assertRaisesRegex(self.psycopg.Error,"editor_preflight_not_completed"):
            self.rpc("edoc_commit_official_document_submission",submit)
        self.assertEqual(self.pg.execute("SELECT count(*) FROM official_document_approval_steps WHERE document_id=%s",(identity,)).fetchone()[0],0)
        fresh=self.prepared_request(identity,latest)
        self.rpc("edoc_commit_editor_preflight",fresh)
        result=self.rpc("edoc_commit_official_document_submission",self.submit_request(identity,latest,fresh))
        self.assertTrue(result["committed"])
        self.assertEqual(self.row("official_documents",identity)["title"],"Final title")

    def test_08_pdf_save_and_submit_race_cannot_lock_old_editor_snapshot(self):
        self._race_submit("edoc_save_editor_revision")

    def test_09_metadata_save_and_submit_race_cannot_mix_application_and_workflow_versions(self):
        self._race_submit("edoc_update_editor_application")

    def _race_submit(self,mutation):
        identity,latest=self.seed(with_seals=True)
        prepared=self.prepared_request(identity,latest)
        self.rpc("edoc_commit_editor_preflight",prepared)
        edit=self.save_request(identity,latest) if mutation=="edoc_save_editor_revision" else self.application_request(identity,latest)
        requests=[(mutation,edit),("edoc_commit_official_document_submission",self.submit_request(identity,latest,prepared))]
        def execute(item):
            with self.psycopg.connect(host="127.0.0.1",port=int(fixture.PORT),user="postgres",dbname=self.dbname,autocommit=True) as connection:
                try: return (item[0],"ok",self.rpc(*item,conn=connection))
                except self.psycopg.Error as error: return (item[0],"conflict",str(error).splitlines()[0])
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(execute,requests))
        self.assertEqual(["conflict","ok"],sorted(result[1] for result in results))
        failed=next(result for result in results if result[1]=="conflict")
        self.assertRegex(failed[2],"(compose_content_revision_conflict|editor_revision_conflict|editor_locked_after_submit)")
        document=self.row("official_documents",identity)
        count=self.pg.execute("SELECT count(*) FROM official_document_approval_steps WHERE document_id=%s",(identity,)).fetchone()[0]
        if document["current_status"]=="draft": self.assertEqual(count,0)
        else:
            self.assertEqual(count,1)
            self.assertEqual(self.row("official_document_stamp_requests","STAMP-"+identity)["locked_editor_revision_id"],latest["id"])

    def test_10_actual_committed_newer_tab_does_not_reconcile_stale_submit_as_success(self):
        identity,latest=self.seed(with_seals=True)
        old_prepared=self.prepared_request(identity,latest)
        self.rpc("edoc_commit_editor_preflight",old_prepared)
        old_doc=self.row("official_documents",identity)
        old_payload={"expected_content_revision":0,"editorRevisionId":latest["id"],"manifestSha256":latest["manifest_sha256"],"preparedFileId":old_prepared["asset"]["official_file_id"],"preparedSha256":"C"*64}
        old_intent=backend._official_submission_intent(old_doc,old_payload,1)
        old_operation=backend._supabase_official_submission_operation_ids(old_doc,"APPLICANT",workflow_generation=1,submission_intent=old_intent)[0]
        self.rpc("edoc_update_editor_application",self.application_request(identity,latest,title="Newer tab final title"))
        prepared=self.prepared_request(identity,latest)
        self.rpc("edoc_commit_editor_preflight",prepared)
        document=self.row("official_documents",identity)
        payload={**old_payload,"expected_content_revision":1,"preparedFileId":prepared["asset"]["official_file_id"]}
        intent=backend._official_submission_intent(document,payload,1)
        operation,audit,_,_=backend._supabase_official_submission_operation_ids(document,"APPLICANT",workflow_generation=1,submission_intent=intent)
        request=self.submit_request(identity,latest,prepared)
        request["operation_id"]=operation
        request["submit_log"]["id"]=operation
        request["submit_log"]["decision_evidence_json"].update(operation_id=operation,submission_intent=intent)
        request["submit_log"]["decision_evidence_json"].update(first_step_id=request["first_step_id"],first_step_key=request["first_step_key"])
        request["submit_audit"]["id"]=audit
        metadata=json.loads(document["metadata_json"])
        metadata["official_seal"]["submission_generation"]=1
        metadata["submission_intent"]=intent
        request["document_patch"]={"metadata_json":json.dumps(metadata)}
        # Execute and deliberately discard the actual committed response.
        self.rpc("edoc_commit_official_document_submission",request)
        def filtered(table,filters,**kwargs):
            cursor=self.pg.execute(f"SELECT * FROM {self.namespace}.{table} WHERE "+" AND ".join(f"{key}=%s" for key in filters),tuple(filters.values()))
            return [dict(zip((column.name for column in cursor.description),row)) for row in cursor.fetchall()]
        with mock.patch.object(backend,"supabase_official_document_row",side_effect=lambda doc:self.row("official_documents",doc)),mock.patch.object(backend,"supabase_filter_rows",side_effect=filtered),mock.patch.object(backend,"supabase_current_official_document_steps",side_effect=lambda doc:filtered("official_document_approval_steps",{"document_id":doc,"workflow_generation":1})),mock.patch.object(backend,"supabase_get",side_effect=self.row):
            self.assertEqual("committed",backend._supabase_official_submission_commit_state(identity,"APPLICANT",operation,intent))
            self.assertEqual("conflict",backend._supabase_official_submission_commit_state(identity,"APPLICANT",old_operation,old_intent))
        self.assertTrue(self.rpc("edoc_commit_official_document_submission",request)["idempotent"])
        for change in ("intent","prepared"):
            altered=copy.deepcopy(request)
            if change=="intent": altered["submit_log"]["decision_evidence_json"]["submission_intent"]["content_revision"]=0
            else: altered["stamp_request"]["prepared_sha256"]="0"*64
            with self.assertRaisesRegex(self.psycopg.Error,"official_submission_operation_conflict"):
                self.rpc("edoc_commit_official_document_submission",altered)
        self.assertEqual(self.row("official_documents",identity)["title"],"Newer tab final title")


class SharedEditorApplicationFinalSnapshotPostgresTest(EditorApplicationFinalSnapshotPostgresTest):
    namespace="edoc"
    backend_role="edoc_backend"

