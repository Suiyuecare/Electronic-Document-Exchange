"""Execute real workflow UI helpers with synthetic data, never real accounts."""
import json
from pathlib import Path
import subprocess
import unittest

from tests.test_compose_output_contract import function

ROOT = Path(__file__).resolve().parents[1]


class ConfigurableWorkflowFrontendTest(unittest.TestCase):
    def evaluate(self, names, setup, body):
        source = (ROOT / "app.js").read_text()
        script = setup + "\n" + "\n".join(function(source, name) for name in names)
        script += "\n(async()=>{" + body + "})().catch(e=>{console.error(e);process.exit(1)});"
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    DECISION_SETUP = r'''
let scope='actor',evidence=true,calls=[],closed=0;
let officialDecisionState={documentId:'D',action:'add-sign',source:'workflow',operationId:'synthetic-operation',expectedStepId:'STEP',expectedContentRevision:7,scope:'actor',candidates:[{id:'TARGET'}]};
const officialWorkflowItems=[{id:'D',available_actions:['approve','reject','return-previous','add-sign','withdraw']}];
const officialDocumentDetailReady=new Set(['D']);
const controls={};
for(const id of ['officialDecisionSubmitBtn','officialDecisionError','officialApprovalComment','officialWithdrawComment','officialAddSignPerson','officialRejectComment','officialRejectCategory','officialCorrectionDueDate'])controls['#'+id]={value:'',hidden:true,disabled:false,focus(){}};
controls['#officialApprovalComment'].value='已確認內容正確';controls['#officialWithdrawComment'].value='需要重新補充文件';controls['#officialAddSignPerson'].value='TARGET';
const document={querySelector:key=>controls[key]||null,querySelectorAll:()=>[]};
const frontendSessionScope=()=>scope,officialDecisionEvidenceComplete=()=>evidence;
const officialDecisionIntegrity=()=>({preparedSha256:'PREPARED',manifestSha256:'MANIFEST'});
const officialDecisionReviewAcknowledgements=()=>({application:true,source:true,attachments:true,editor:true});
const mutateOfficialDocument=async(...args)=>{calls.push(args);return true};
const closeOfficialDecisionDialog=()=>closed++,updateOfficialDecisionSubmitAvailability=()=>{};
const event={preventDefault(){}};
'''

    def decision(self, body):
        return self.evaluate(["officialDocumentAvailableActions", "submitOfficialDecision"], self.DECISION_SETUP, body)

    def test_add_sign_approves_then_adds_named_person_with_complete_review_evidence(self):
        value = self.decision('await submitOfficialDecision(event);console.log(JSON.stringify(calls[0]));')
        self.assertEqual(value[0], "add-sign")
        payload = value[1]
        self.assertEqual(payload["placement"], "after")
        self.assertEqual(payload["target_user_id"], "TARGET")
        self.assertEqual(payload["expected_step_id"], "STEP")
        self.assertEqual(payload["operation_id"], "synthetic-operation")
        self.assertEqual(payload["prepared_sha256"], "PREPARED")
        self.assertEqual(payload["manifest_sha256"], "MANIFEST")
        self.assertTrue(all(payload["review_acknowledgements"].values()))

    def test_return_previous_keeps_review_evidence_and_does_not_set_target(self):
        value = self.decision('officialDecisionState.action="return-previous";await submitOfficialDecision(event);console.log(JSON.stringify(calls[0]));')
        self.assertEqual(value[0], "return-previous")
        self.assertEqual(value[1]["expected_step_id"], "STEP")
        self.assertIn("review_acknowledgements", value[1])
        self.assertNotIn("target_user_id", value[1])

    def test_all_review_decisions_require_evidence(self):
        for action in ("approve", "reject", "return-previous", "add-sign"):
            with self.subTest(action=action):
                value = self.decision(f'officialDecisionState.action={json.dumps(action)};evidence=false;await submitOfficialDecision(event);console.log(JSON.stringify(calls));')
                self.assertEqual(value, [])

    def test_unlisted_add_sign_person_never_posts(self):
        value = self.decision('controls["#officialAddSignPerson"].value="UNLISTED";await submitOfficialDecision(event);console.log(JSON.stringify(calls));')
        self.assertEqual(value, [])

    def test_withdraw_requires_reason_and_content_revision_not_approval_evidence(self):
        value = self.decision('officialDecisionState.action="withdraw";evidence=false;await submitOfficialDecision(event);console.log(JSON.stringify(calls[0]));')
        self.assertEqual(value[0], "withdraw")
        self.assertEqual(value[1]["expected_content_revision"], 7)
        self.assertNotIn("review_acknowledgements", value[1])
        value = self.decision('officialDecisionState.action="withdraw";controls["#officialWithdrawComment"].value="";await submitOfficialDecision(event);console.log(JSON.stringify(calls));')
        self.assertEqual(value, [])

    def test_actor_switch_busy_or_server_denied_action_never_posts(self):
        for mutation in ('scope="other"', 'officialDecisionState.busy=true', 'officialWorkflowItems[0].available_actions=[]'):
            with self.subTest(mutation=mutation):
                value = self.decision(mutation + ';await submitOfficialDecision(event);console.log(JSON.stringify(calls));')
                self.assertEqual(value, [])

    def test_action_capabilities_fail_closed_when_server_returns_empty_list(self):
        value = self.evaluate(["officialDocumentAvailableActions"], "", '''console.log(JSON.stringify([
          officialDocumentAvailableActions({can_act:true,available_actions:[]}),
          officialDocumentAvailableActions({can_act:true}),
          officialDocumentAvailableActions({available_actions:['withdraw','unknown']})]));''')
        self.assertEqual(value, [[], ["approve", "reject"], ["withdraw"]])

    def test_workflow_settings_permission_matches_backend_not_role_label(self):
        value = self.evaluate(["canManageOfficialWorkflowConfig"], "let permissions=[];const hasBackendPermission=key=>permissions.includes(key);", '''
          const result=[];for(const next of [[],['system_permissions.manage'],['settings.manage'],['settings.system_manage']]){permissions=next;result.push(canManageOfficialWorkflowConfig())}console.log(JSON.stringify(result));''')
        self.assertEqual(value, [False, False, True, True])

    def test_withdrawn_pending_steps_are_not_presented_as_future_work(self):
        setup = "const latestOfficialApprovalSteps=item=>item.approval_steps,escapeHtml=value=>String(value??''),safeHtmlClassToken=value=>value;"
        value = self.evaluate(["officialApprovalStepActor", "renderOfficialStepRows", "renderOfficialSteps"], setup, '''console.log(JSON.stringify(renderOfficialSteps({current_step:'',approval_steps:[{step_order:1,step_key:'manager',step_name:'主管',approver_name:'測試主管',status:'skipped'}]})));''')
        self.assertIn("本輪已取消", value)
        self.assertNotIn("待後續", value)
        self.assertNotIn("· skipped", value)

    CONFIG_SETUP = r'''
let scope='actor',calls=[],rendered=0;
let officialWorkflowConfigLoadRequest=null,officialWorkflowConfigLoadGeneration=0;
let officialWorkflowConfig={schema_version:3,version:8,available_roles:[{key:'applicant_manager',name:'主管'}]};
const original={synthetic:{nodes:[{id:'N',name:'指定審核',assignee:{type:'user',user_id:'FORMAL'}}]}};
const officialWorkflowConfigEditor={categories:structuredClone(original),version:8,dirty:true,saving:false,conflict:false};
const notice={textContent:''};const document={querySelector:()=>notice};
const canManageOfficialWorkflowConfig=()=>true,frontendSessionScope=()=>scope;
const renderEditableOfficialWorkflowConfig=()=>rendered++,renderAllWorkflowReadinessContexts=()=>{},showToast=()=>{};
const officialWorkflowReadinessByRoute=new Map([['old',{}]]),officialWorkflowReadinessRequests=new Map();
let backendRequest=async(path,options)=>{calls.push({path,payload:JSON.parse(options.body)});return {...officialWorkflowConfig,version:9,categories:structuredClone(original)}};
'''

    def test_config_save_uses_compare_and_swap_and_only_updates_after_success(self):
        value = self.evaluate(["saveEditableOfficialWorkflowConfig"], self.CONFIG_SETUP, 'await saveEditableOfficialWorkflowConfig();console.log(JSON.stringify({calls,state:officialWorkflowConfigEditor,cache:officialWorkflowReadinessByRoute.size}));')
        self.assertEqual(value["calls"][0]["payload"]["expected_version"], 8)
        self.assertEqual(value["state"]["version"], 9)
        self.assertFalse(value["state"]["dirty"])
        self.assertEqual(value["cache"], 0)

    def test_config_conflict_preserves_unsaved_changes_and_blocks_overwrite(self):
        value = self.evaluate(["saveEditableOfficialWorkflowConfig"], self.CONFIG_SETUP, '''backendRequest=async()=>{calls.push('PATCH');throw Object.assign(new Error('conflict'),{status:409})};
          await saveEditableOfficialWorkflowConfig();await saveEditableOfficialWorkflowConfig();console.log(JSON.stringify({calls,state:officialWorkflowConfigEditor,message:notice.textContent}));''')
        self.assertEqual(value["calls"], ["PATCH"])
        self.assertEqual(value["state"]["version"], 8)
        self.assertTrue(value["state"]["dirty"])
        self.assertTrue(value["state"]["conflict"])
        self.assertIn("仍保留", value["message"])

    def test_config_does_not_save_incomplete_user_or_unavailable_role(self):
        for assignee in ({"type": "user", "user_id": ""}, {"type": "role", "role_key": "unknown"}):
            value = self.evaluate(["saveEditableOfficialWorkflowConfig"], self.CONFIG_SETUP, f'officialWorkflowConfigEditor.categories.synthetic.nodes[0].assignee={json.dumps(assignee)};await saveEditableOfficialWorkflowConfig();console.log(JSON.stringify(calls));')
            self.assertEqual(value, [])

    def test_readiness_cache_is_isolated_by_category_company_unit_actor_and_config_version(self):
        setup = '''let scope='A',version=1,query={document_category:'contract',company_id:'C',unit:'U',source_type:'uploaded_pdf'},route='A';
const frontendSessionScope=()=>scope,officialWorkflowConfig={version},workflowReadinessSelection=()=>({approvalRouteCode:route}),workflowReadinessContextQuery=()=>query;'''
        value = self.evaluate(["workflowReadinessCacheKey"], setup, '''const keys=[workflowReadinessCacheKey('uploadedSeal')];
query={...query,document_category:'letter'};keys.push(workflowReadinessCacheKey('uploadedSeal'));
query={...query,company_id:'D'};keys.push(workflowReadinessCacheKey('uploadedSeal'));
query={...query,unit:'V'};keys.push(workflowReadinessCacheKey('uploadedSeal'));
scope='B';keys.push(workflowReadinessCacheKey('uploadedSeal'));officialWorkflowConfig.version=2;keys.push(workflowReadinessCacheKey('uploadedSeal'));
query={...query,source_type:'blank_editor'};keys.push(workflowReadinessCacheKey('compose'));console.log(JSON.stringify(keys));''')
        self.assertEqual(len(set(value)), 7)

    def test_readiness_explicitly_distinguishes_composed_documents_from_pdf_editor(self):
        setup = '''const workflowReadinessSelection=()=>({documentCategory:'contract'}),activeUnit=()=> 'OWN';
const composeCompanyForOfficialApplication=()=>({id:'COMPOSE-COMPANY'});
const document={querySelector:selector=>({value:({'#uploadedSealCompany':'SELECTED-COMPANY','#uploadedSealDepartment':'SELECTED-UNIT'})[selector]||''})};'''
        value = self.evaluate(["workflowReadinessContextQuery"], setup, "console.log(JSON.stringify([workflowReadinessContextQuery('compose'),workflowReadinessContextQuery('uploadedSeal')]));")
        self.assertEqual(value[0], {"document_category": "contract", "company_id": "COMPOSE-COMPANY", "unit": "OWN", "source_type": "blank_editor"})
        self.assertEqual(value[1], {"document_category": "contract", "company_id": "SELECTED-COMPANY", "unit": "SELECTED-UNIT", "source_type": "uploaded_pdf"})

    def test_background_config_load_never_overwrites_unsaved_changes(self):
        setup = self.CONFIG_SETUP + '''
const hasAuthenticatedBackendSession=()=>true,renderOfficialWorkflowConfig=()=>{},loadOfficialWorkflowCandidates=async()=>{};
'''
        value = self.evaluate(["loadOfficialWorkflowConfig"], setup, 'await loadOfficialWorkflowConfig();console.log(JSON.stringify({calls,dirty:officialWorkflowConfigEditor.dirty,version:officialWorkflowConfigEditor.version}));')
        self.assertEqual(value, {"calls": [], "dirty": True, "version": 8})

    def test_config_load_ignores_late_response_after_account_switch(self):
        setup = self.CONFIG_SETUP + '''
const hasAuthenticatedBackendSession=()=>true,renderOfficialWorkflowConfig=()=>{},loadOfficialWorkflowCandidates=async()=>{};
'''
        value = self.evaluate(["loadOfficialWorkflowConfig"], setup, '''officialWorkflowConfigEditor.dirty=false;
backendRequest=async()=>{scope='new-actor';return {schema_version:3,version:99,categories:{foreign:{nodes:[]}}}};
await loadOfficialWorkflowConfig();console.log(JSON.stringify({version:officialWorkflowConfig.version,categories:officialWorkflowConfigEditor.categories}));''')
        self.assertEqual(value["version"], 8)
        self.assertIn("synthetic", value["categories"])
        self.assertNotIn("foreign", value["categories"])

    def test_late_review_download_cannot_check_evidence_for_another_modal_or_account(self):
        source = function((ROOT / "app.js").read_text(), "renderOfficialDecisionEvidence")
        guard = source.index("officialDecisionState.operationId !== operationId")
        self.assertLess(guard, source.index("markOfficialDecisionEvidenceReviewed(kind)"))
        self.assertIn("scope !== frontendSessionScope()", source)
        self.assertIn("officialDecisionState.documentId !== item.id", source)

    def test_authenticated_legacy_actions_are_guarded_and_workspace_keeps_real_delegation(self):
        source = (ROOT / "app.js").read_text()
        for name in ("mutateWorkflowTasks", "runWorkflowAdvancedAction", "applyWorkflowTemplate"):
            action = function(source, name)
            self.assertIn("if (hasAuthenticatedBackendSession()) return showToast", action)
        workspace = function(source, "renderOfficialWorkflowWorkspace")
        self.assertIn('child.id === "officialWorkflowConfigPanel"', workspace)
        self.assertIn('"#workflowProxyForm"', workspace)
        self.assertIn("child.hidden = true", workspace)


if __name__ == "__main__":
    unittest.main()
