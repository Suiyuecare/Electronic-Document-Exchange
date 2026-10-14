"""A committed newer tab is not success for a stale final-submit intention."""
import copy
import json
import unittest
from contextlib import ExitStack
from unittest import mock

import backend
from tests import test_backend_security_atomic as atomic_fixture


class EditorSubmissionIntentTest(unittest.TestCase):
    def case(self):
        document,user,stamp,position,step,snapshot=atomic_fixture.BackendSecurityAndAtomicityTestCase._submission_fixture("draft")
        document.update(content_revision=1,metadata_json=json.dumps({"pdf_editor_v2":True,"official_seal":{"document_category":"合作意向書","submission_generation":1}}))
        payload={"expected_content_revision":1,"editorRevisionId":stamp["locked_editor_revision_id"],"manifestSha256":stamp["editor_manifest_sha256"],"preparedFileId":stamp["prepared_file_id"],"preparedSha256":stamp["prepared_sha256"]}
        intent=backend._official_submission_intent(document,payload,1)
        operation=backend._supabase_official_submission_operation_ids(document,user["id"],workflow_generation=1,submission_intent=intent)[0]
        evidence={"operation_id":operation,"first_step_id":step["id"],"workflow_generation":1,"stamp_request_id":stamp["id"],"submission_intent":intent}
        return document,user,stamp,position,step,snapshot,payload,intent,operation,evidence

    def probe(self,document,user,stamp,step,operation,evidence,intent):
        with mock.patch.object(backend,"supabase_official_document_row",return_value=document),mock.patch.object(backend,"supabase_filter_rows",return_value=[{"actor_id":user["id"],"decision_evidence_json":evidence}]),mock.patch.object(backend,"supabase_current_official_document_steps",return_value=[step]),mock.patch.object(backend,"supabase_get",return_value=stamp):
            return backend._supabase_official_submission_commit_state(document["id"],user["id"],operation,intent)

    def test_operation_ids_bind_company_content_application_and_exact_pdf_version(self):
        document,user,stamp,position,step,snapshot,payload,intent,operation,evidence=self.case()
        variants=[]
        for key,value in (("company_id","OTHER-COMPANY"),("title","Another final title"),("content_revision",2)):
            changed={**document,key:value};request={**payload,"expected_content_revision":changed["content_revision"]}
            variants.append(backend._official_submission_intent(changed,request,1))
        for key,value in (("editorRevisionId","OTHER-REV"),("manifestSha256","9"*64),("preparedFileId","OTHER-FILE"),("preparedSha256","8"*64)):
            variants.append(backend._official_submission_intent(document,{**payload,key:value},1))
        for variant in variants:
            self.assertNotEqual(operation,backend._supabase_official_submission_operation_ids(document,user["id"],workflow_generation=1,submission_intent=variant)[0])
        pending={**document,"current_status":"pending_applicant_manager","correction_requested_at":None,"metadata_json":json.dumps({"official_seal":{"submission_generation":1},"submission_intent":intent})}
        self.assertEqual(operation,backend._supabase_official_submission_operation_ids(pending,user["id"])[0])

    def test_newer_committed_snapshot_is_conflict_for_old_tab_not_success(self):
        document,user,stamp,position,step,snapshot,payload,intent,operation,evidence=self.case()
        newer={**document,"company_id":"OTHER-COMPANY","content_revision":2,"current_status":"pending_applicant_manager"}
        new_payload={**payload,"expected_content_revision":2,"preparedFileId":"NEWER-FILE","preparedSha256":"7"*64}
        new_intent=backend._official_submission_intent(newer,new_payload,1)
        newer_evidence={**evidence,"submission_intent":new_intent}
        self.assertEqual("conflict",self.probe(newer,user,stamp,step,operation,newer_evidence,intent))

    def test_matching_intent_requires_matching_locked_stamp_and_strict_json_types(self):
        document,user,stamp,position,step,snapshot,payload,intent,operation,evidence=self.case()
        document["current_status"]="pending_applicant_manager"
        self.assertEqual("committed",self.probe(document,user,stamp,step,operation,evidence,intent))
        for key,value in (("prepared_sha256","0"*64),("locked_editor_revision_id","OTHER"),("company_id","OTHER"),("requested_by","ANOTHER")):
            self.assertEqual("conflict",self.probe(document,user,{**stamp,key:value},step,operation,evidence,intent))
        malformed=copy.deepcopy(evidence);malformed["submission_intent"]["content_revision"]=True
        self.assertEqual("conflict",self.probe(document,user,stamp,step,operation,malformed,intent))

    def test_status_or_untyped_historical_log_alone_is_never_exact_success(self):
        document,user,stamp,position,step,snapshot,payload,intent,operation,evidence=self.case()
        document["current_status"]="pending_applicant_manager"
        old={key:value for key,value in evidence.items() if key!="submission_intent"}
        self.assertEqual("unknown",self.probe(document,user,stamp,step,operation,old,intent))
        self.assertEqual("unknown",self.probe(document,user,stamp,step,operation,evidence,None))

    def test_pending_early_replay_refuses_wrong_version_before_probe_or_mutation(self):
        document,user,stamp,position,step,snapshot,payload,intent,operation,evidence=self.case()
        document.update(current_status="pending_applicant_manager",metadata_json=json.dumps({"pdf_editor_v2":True,"official_seal":{"document_category":"合作意向書","submission_generation":1},"submission_intent":intent}))
        with mock.patch.object(backend,"supabase_official_session_user",return_value=user),mock.patch.object(backend,"supabase_official_document_row",return_value=document),mock.patch.object(backend,"_supabase_official_submission_commit_state") as probe,mock.patch.object(backend,"supabase_request") as rpc:
            with self.assertRaisesRegex(ValueError,"compose_content_revision_conflict"):
                backend.supabase_submit_official_document(document["id"],{**payload,"expected_content_revision":0},{"user":user})
            with self.assertRaisesRegex(ValueError,"official_submission_operation_conflict"):
                backend.supabase_submit_official_document(document["id"],{**payload,"preparedSha256":"0"*64},{"user":user})
            probe.assert_not_called();rpc.assert_not_called()

    def test_lost_rpc_response_reconciles_only_exact_actual_committed_witness(self):
        for newer_tab in (False,True):
            with self.subTest(newer_tab=newer_tab):
                document,user,stamp,position,step,snapshot,payload,intent,operation,evidence=self.case()
                current=[copy.deepcopy(document)];committed_log=[];locked=[stamp]
                def lost_response(method,endpoint,body,**kwargs):
                    self.assertEqual(endpoint,"rpc/edoc_commit_official_document_submission")
                    request=body["p_request"]
                    observed=copy.deepcopy(request["submit_log"])
                    current[0].update(current_status=request["first_status"],current_step=request["first_step_key"],metadata_json=request["document_patch"]["metadata_json"])
                    if newer_tab:
                        current[0]["content_revision"]=2
                        observed["decision_evidence_json"]["submission_intent"]["content_revision"]=2
                        locked[0]={**stamp,"prepared_sha256":"7"*64}
                    committed_log.append(observed)
                    raise RuntimeError("synthetic_lost_response")
                with ExitStack() as stack:
                    patches={"supabase_official_session_user":user,"supabase_official_document_row":lambda identity:current[0],"official_seal_context_from_document":{"approval_route_code":"A","document_category":"合作意向書"},"supabase_official_workflow_config":backend.normalize_official_workflow_config(),"is_production":False,"require_official_document_application_company":None,"supabase_assert_official_document_uploads_av_clean":None,"supabase_user_by_id":lambda identity:user if identity==user["id"] else {"id":identity,"company_id":"CO-1","name":"Synthetic reviewer","status":"啟用"},"supabase_plan_official_workflow_submission":{"workflow_generation":1,"supersede_generation":0,"steps":[step],"actor_snapshots":[snapshot]},"supabase_official_document_detail":lambda identity,session:copy.deepcopy(current[0]),"supabase_create_and_deliver_notification":None,"supabase_current_official_document_steps":[step],"supabase_filter_rows":lambda *args,**kwargs:committed_log,"supabase_get":lambda *args,**kwargs:locked[0]}
                    for name,value in patches.items(): stack.enter_context(mock.patch.object(backend,name,side_effect=value) if callable(value) else mock.patch.object(backend,name,return_value=value))
                    stack.enter_context(mock.patch.object(backend,"supabase_lock_official_editor_submission",return_value={"revision_id":stamp["locked_editor_revision_id"],"manifest_sha256":stamp["editor_manifest_sha256"],"source_sha256":"A"*64,"prepared_file_id":stamp["prepared_file_id"],"prepared_sha256":stamp["prepared_sha256"],"seal_positions":1,"request_row":stamp,"position_rows":[position]}))
                    stack.enter_context(mock.patch.object(backend,"supabase_request",side_effect=lost_response))
                    if newer_tab:
                        with self.assertRaisesRegex(ValueError,"official_submission_operation_conflict"):
                            backend.supabase_submit_official_document(document["id"],payload,{"user":user})
                    else:
                        result=backend.supabase_submit_official_document(document["id"],payload,{"user":user})
                        self.assertEqual(result["current_status"],"pending_applicant_manager")

