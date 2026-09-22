"""Synthetic UI regressions for real signers, immutable versions and async isolation."""
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def runtime_function(source, name):
    # app.js still has legacy declarations. The browser executes the LAST one.
    matches = list(re.finditer(r"(?:async )?function " + re.escape(name) + r"\([^\n]*\) \{\n.*?\n\}", source, re.S))
    if not matches:
        raise AssertionError(name)
    return matches[-1].group(0)


class WorkflowHistoryFrontendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "app.js").read_text()

    def run_js(self, names, setup, case):
        functions = "\n".join(runtime_function(self.source, name) for name in names)
        script = "const assert=require('node:assert/strict');\n" + setup + "\n" + functions
        script += "\n(async()=>{" + case + "})().catch(error=>{console.error(error);process.exitCode=1});"
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    RENDER_SETUP = r'''
const escapeHtml=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const escapeDraftHtml=escapeHtml,safeHtmlClassToken=x=>x,parseJsonMaybe=x=>typeof x==='string'?JSON.parse(x):x;
const latestOfficialApprovalSteps=item=>item.approval_steps||[],officialApplicationFiles=item=>item.files||[];
'''

    def test_completed_steps_display_actual_actor_and_keep_assignee_as_reference(self):
        self.run_js(["officialApprovalStepActor", "renderOfficialStepRows", "renderOfficialSteps"], self.RENDER_SETUP, r'''
const item={current_step:'manager',approval_steps:[{step_key:'manager',step_name:'主管',step_order:1,status:'approved',approver_user_id:'ASSIGNEE',approver_name:'原指派主管',decision_actor_id:'DELEGATE',decision_actor_name:'實際代理人',comment:'代理核准',approved_at:'2026-09-22T10:20:30Z'}]};
const html=renderOfficialSteps(item);assert.match(html,/已由：實際代理人/);assert.match(html,/原指派：原指派主管/);assert.doesNotMatch(html,/已由：原指派主管|approved current/);assert.match(html,/2026-09-22T10:20:30Z/);
item.approval_steps[0].status='pending';const pending=renderOfficialSteps(item);assert.match(pending,/待處理：原指派主管/);assert.doesNotMatch(pending,/實際代理人/);
''')

    def test_unknown_completed_actor_never_falls_back_to_assignee_or_exposes_full_id(self):
        self.run_js(["officialApprovalStepActor"], self.RENDER_SETUP, r'''
for(const status of ['approved','rejected']){
 const actor=officialApprovalStepActor({status,approver_name:'並未簽核的主管',approver_user_id:'original',decision_actor_id:'long-sensitive-user-id-123456'});
 assert.match(actor.label,/已由：簽核人待確認.*123456/);assert.doesNotMatch(actor.label,/並未簽核|long-sensitive-user-id/);
}
assert.equal(officialApprovalStepActor({status:'approved',approver_name:'指派'}).label,'已由：簽核人待確認');
''')

    def test_history_is_collapsed_grouped_and_retains_dates_reasons_and_actual_signers(self):
        self.run_js(["officialApprovalStepActor", "renderOfficialStepRows", "renderOfficialApprovalHistory", "renderOfficialLogs"], self.RENDER_SETUP, r'''
const item={current_step:'extra',approval_step_history:[
 {id:'s1',workflow_generation:1,step_order:1,step_name:'主管',status:'approved',approver_name:'指派',decision_actor_name:'代理',decision_actor_id:'actual',comment:'首輪核准',approved_at:'2026-09-20T09:15:20Z'},
 {id:'s3',workflow_generation:3,step_order:2,step_name:'指定加簽',status:'pending',approver_name:'加簽人'},
 {id:'s2',workflow_generation:2,step_order:1,step_name:'主管',status:'approved',decision_actor_name:'代理',comment:'再確認',approved_at:'2026-09-21T09:15:20Z'}
],logs:[{step_id:'s1',action:'return_previous',actor_name:'合成主管',comment:'補充原始文件 <安全>',created_at:'2026-09-20T10:15:20Z'},{step_id:'s2',action:'add_sign',actor_name:'合成主管',comment:'請專責確認',created_at:'2026-09-21T10:15:20Z'}]};
const html=renderOfficialApprovalHistory(item);assert.match(html,/<details class="official-approval-history"><summary>/);assert.doesNotMatch(html,/<details[^>]* open/);assert.match(html,/完整簽核歷程（3 輪）/);assert.ok(html.indexOf('第 3 輪')<html.indexOf('第 2 輪'));assert.ok(html.indexOf('第 2 輪')<html.indexOf('第 1 輪'));assert.match(html,/已由：代理/);assert.match(html,/退回上一關/);assert.match(html,/通過並加簽/);assert.match(html,/2026-09-20T10:15:20Z/);assert.match(html,/補充原始文件 &lt;安全>/);assert.doesNotMatch(html,/<安全>/);
''')

    def test_missing_locked_final_file_never_substitutes_an_older_file(self):
        self.run_js(["officialIsElectronicCompose", "latestOfficialStampedFile", "renderOfficialFinalStampedDownload"], self.RENDER_SETUP, r'''
const item={id:'CASE',stamped_file_id:'locked-missing',files:[{id:'old',file_type:'stamped_pdf',version:9,file_name:'old.pdf'}]};
assert.equal(latestOfficialStampedFile(item),null);const html=renderOfficialFinalStampedDownload(item);assert.match(html,/核定版本暫時無法取得/);assert.match(html,/不會以其他版本替代/);assert.doesNotMatch(html,/data-official-download=/);
item.files.push({id:'locked-missing',file_type:'stamped_pdf',version:2,file_name:'approved.pdf'});assert.equal(latestOfficialStampedFile(item).file_name,'approved.pdf');
delete item.stamped_file_id;item.current_status='stamping_failed';assert.equal(latestOfficialStampedFile(item),null);assert.doesNotMatch(renderOfficialFinalStampedDownload(item),/data-official-download=/);
item.stamped_file_id='locked-missing';item.files[1].document_id='OTHER-CASE';assert.equal(latestOfficialStampedFile(item),null);
''')

    SCOPE_SETUP = r'''
let session='actor-A',renders=0,toasts=[],audits=[],calls=[],opened=[],savedStatus=[],gate=null;
const defer=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}};
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve()};
const frontendSessionScope=()=>session,window={clearTimeout(){}};
let uploadedSealMode='normal';
const uploadedSealApplicationRuntime={epoch:1,submissionBusy:false,submissionOperation:null,submissionPreview:'valid',timer:0};
const uploadedSealEditorRuntime={documentId:'CASE-A',locked:false,revisionId:'REV',preparedFileId:'FILE',preparedSha256:'HASH',reviewMode:'prepared',preparedPdfDocument:{},dirtyGeneration:1,reviewGeneration:0};
const uploadedSealEditorState={pages:[{pageId:'page1'}],elements:[{kind:'seal'}],manifestSha256:'MANIFEST',revisionNo:1};
const fields={};const document={querySelector:s=>fields[s]||null};
const approvalSelectionForSelect=()=>({documentCategory:'contract',approvalRouteCode:'A'});
const renderUploadedSealWorkbench=()=>renders++,showToast=message=>toasts.push(message),addSealAudit=(...args)=>audits.push(args);
const setUploadedEditorSaveStatus=(...args)=>savedStatus.push(args),renderWorkflowReadinessContext=()=>{};
let loadOfficialWorkflowReadiness=async()=>({ready:true});const workflowReadinessAllowsSubmit=()=>true;
const uploadedEditorSubmissionPreviewIsCurrent=()=>uploadedSealApplicationRuntime.submissionPreview==='valid';
const uploadedEditorSubmissionFingerprint=()=>JSON.stringify({id:uploadedSealEditorRuntime.documentId,revision:uploadedSealEditorRuntime.revisionId});
const invalidateUploadedEditorSubmissionPreview=()=>uploadedSealApplicationRuntime.submissionPreview=null;
let syncUploadedSealApplicationDraft=async()=>{},preflightUploadedEditor=async()=>{},showUploadedEditorReview=async()=>{};
let backendRequest=async(path,options)=>{calls.push(path);return {id:'CASE-A'}};
let showSubmittedOfficialDocument=async(id)=>opened.push(id);
const switchDraft=()=>{uploadedSealEditorRuntime.documentId='CASE-B';uploadedSealEditorRuntime.locked=false;uploadedSealEditorRuntime.reviewMode='edited';uploadedSealApplicationRuntime.epoch++;uploadedSealApplicationRuntime.submissionOperation={newer:true};uploadedSealApplicationRuntime.submissionBusy=true;uploadedSealApplicationRuntime.submissionPreview='new-preview'};
'''

    def submission(self, case, setup=None):
        self.run_js(["uploadedSealApplicationScopeSnapshot", "uploadedSealApplicationScopeIsCurrent", "resetUploadedSealApplicationSaving", "submitUploadedSealApplication"], setup or self.SCOPE_SETUP, case)

    def test_current_submit_completes_locks_and_cleans_loading(self):
        self.submission(r'''
await submitUploadedSealApplication();assert.deepEqual(calls,['/official-documents/CASE-A/submit']);assert.equal(uploadedSealEditorRuntime.locked,true);assert.deepEqual(opened,['CASE-A']);assert.equal(uploadedSealApplicationRuntime.submissionBusy,false);assert.equal(uploadedSealApplicationRuntime.submissionOperation,null);assert.equal(audits.length,1);assert.match(toasts[0],/已鎖定並送出簽核/);
''')

    def test_current_submit_failure_is_reported_without_lock_and_cleans_loading(self):
        self.submission(r'''
backendRequest=async()=>{throw new Error('synthetic temporary failure')};await submitUploadedSealApplication();assert.equal(uploadedSealEditorRuntime.locked,false);assert.equal(uploadedSealApplicationRuntime.submissionBusy,false);assert.equal(uploadedSealApplicationRuntime.submissionOperation,null);assert.match(toasts[0],/送簽失敗/);assert.deepEqual(opened,[]);
''')

    def test_late_submit_success_or_failure_never_locks_navigates_or_clears_new_loading(self):
        for outcome in ("resolve({id:'CASE-A'})", "reject(new Error('old failure'))"):
            with self.subTest(outcome=outcome):
                self.submission(r'''
gate=defer();backendRequest=async(path)=>{calls.push(path);return gate.promise};const task=submitUploadedSealApplication();await flush();assert.equal(calls.length,1);switchDraft();const operation=uploadedSealApplicationRuntime.submissionOperation,renderCount=renders;
''' + f"gate.{outcome};" + r'''
await task;assert.equal(uploadedSealEditorRuntime.documentId,'CASE-B');assert.equal(uploadedSealEditorRuntime.locked,false);assert.equal(uploadedSealApplicationRuntime.submissionBusy,true);assert.equal(uploadedSealApplicationRuntime.submissionOperation,operation);assert.equal(uploadedSealApplicationRuntime.submissionPreview,'new-preview');assert.deepEqual(opened,[]);assert.deepEqual(toasts,[]);assert.deepEqual(audits,[]);assert.equal(renders,renderCount);
''')

    def test_cancel_and_logout_invalidate_late_submit_without_resurrecting_busy_state(self):
        for change in ("resetUploadedSealApplicationSaving()", "session='logged-out';resetUploadedSealApplicationSaving()"):
            with self.subTest(change=change):
                self.submission(r'''
gate=defer();backendRequest=()=>gate.promise;const task=submitUploadedSealApplication();await flush();
''' + change + r''';gate.resolve({id:'CASE-A'});await task;assert.equal(uploadedSealEditorRuntime.locked,false);assert.equal(uploadedSealApplicationRuntime.submissionBusy,false);assert.equal(uploadedSealApplicationRuntime.submissionOperation,null);assert.deepEqual(opened,[]);assert.deepEqual(toasts,[]);
''')

    def test_stale_preparation_at_each_await_stops_all_next_steps(self):
        for paused in ("readiness", "save", "preflight", "review"):
            with self.subTest(paused=paused):
                self.submission(r'''
uploadedSealApplicationRuntime.submissionPreview=null;uploadedSealEditorRuntime.reviewMode='edited';gate=defer();const stages=[];
const pause=async(name)=>{stages.push(name);if(name===PAUSE)await gate.promise;};
loadOfficialWorkflowReadiness=async()=>{await pause('readiness');return {ready:true}};
syncUploadedSealApplicationDraft=()=>pause('save');preflightUploadedEditor=()=>pause('preflight');showUploadedEditorReview=()=>pause('review');
const task=submitUploadedSealApplication();await flush();assert.equal(stages.at(-1),PAUSE);switchDraft();const before=[...stages],renderCount=renders;gate.resolve();await task;assert.deepEqual(stages,before);assert.deepEqual(calls,[]);assert.deepEqual(toasts,[]);assert.equal(renders,renderCount);assert.equal(uploadedSealApplicationRuntime.submissionBusy,true);assert.equal(uploadedSealApplicationRuntime.submissionPreview,'new-preview');
'''.replace("PAUSE", repr(paused)))

    PREFLIGHT_SETUP = r'''
let session='actor',calls=[],saveGate=null;const frontendSessionScope=()=>session;
const uploadedSealApplicationRuntime={epoch:1};const uploadedSealEditorRuntime={documentId:'A',dirtyGeneration:1,revisionId:'R',preparedPdfDocument:null};const uploadedSealEditorState={pages:[{}],manifestSha256:'M'};
const document={querySelector:()=>null},finishUploadedEditorTextEdit=()=>true,ensureUploadedEditorPagesA4=()=>{};
const defer=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
let saveUploadedEditorState=async()=>{},backendRequest=async(path)=>{calls.push(path);return {status:'prepared',preparedFileId:'P',preparedSha256:'H'}};
const editorPreparedAuthorizedUrl=()=>'',applyEditorRevisionFromResponse=()=>{},applyUploadedEditorCanonicalSaveResponse=()=>{};
'''

    def test_preflight_scope_is_captured_before_save_not_after(self):
        self.run_js(["uploadedSealApplicationScopeSnapshot", "uploadedSealApplicationScopeIsCurrent", "preflightUploadedEditor"], self.PREFLIGHT_SETUP, r'''
saveGate=defer();saveUploadedEditorState=()=>saveGate.promise;const task=preflightUploadedEditor();uploadedSealEditorRuntime.documentId='B';saveGate.resolve();assert.equal(await task,null);assert.deepEqual(calls,[]);
''')

    def test_preflight_late_response_does_not_replace_new_prepared_version(self):
        self.run_js(["uploadedSealApplicationScopeSnapshot", "uploadedSealApplicationScopeIsCurrent", "preflightUploadedEditor"], self.PREFLIGHT_SETUP, r'''
const gate=defer();backendRequest=()=>gate.promise;const task=preflightUploadedEditor();await Promise.resolve();uploadedSealApplicationRuntime.epoch++;uploadedSealEditorRuntime.preparedFileId='B-file';gate.resolve({status:'prepared',preparedFileId:'A-file',preparedSha256:'A-hash'});assert.equal(await task,null);assert.equal(uploadedSealEditorRuntime.preparedFileId,'B-file');
''')

    def test_late_review_render_success_or_failure_does_not_revert_new_draft_mode(self):
        setup = r'''
let session='actor',renders=0,toasts=[];const frontendSessionScope=()=>session;
const uploadedSealApplicationRuntime={epoch:1},uploadedSealEditorRuntime={documentId:'A',reviewGeneration:0,reviewMode:'edited'};
const document={querySelector:()=>null},finishUploadedEditorTextEdit=()=>true,invalidateUploadedEditorSubmissionPreview=()=>{},renderUploadedSealWorkbench=()=>renders++,showToast=message=>toasts.push(message);
let resolve,reject;const gate=new Promise((yes,no)=>{resolve=yes;reject=no});const renderUploadedPdfPage=()=>gate;
'''
        for finish in ("resolve()", "reject(new Error('old preview failed'))"):
            with self.subTest(finish=finish):
                self.run_js(["uploadedSealApplicationScopeSnapshot", "uploadedSealApplicationScopeIsCurrent", "showUploadedEditorReview"], setup, r'''
const task=showUploadedEditorReview('prepared');uploadedSealEditorRuntime.documentId='B';uploadedSealEditorRuntime.reviewMode='original';
''' + finish + r''';await task;assert.equal(uploadedSealEditorRuntime.reviewMode,'original');assert.equal(renders,0);assert.deepEqual(toasts,[]);
''')

    LIST_SETUP = r'''
let session='actor',valid=true,renders=0,toasts=[],calls=[];const frontendSessionScope=()=>session;
let officialWorkflowItems=[{id:'B'}],selectedOfficialDocumentId='B',editingOfficialDocumentId='',officialWorkflowScope='mine',officialWorkflowStatusFilter='';
const officialDocumentDetailReady=new Set(),officialDocumentDetailRequests=new Map();
const defer=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}};
const gate=defer();let backendRequest=async(path)=>{calls.push(path);return gate.promise};
const officialWorkflowEndpoint=()=>'/official-documents',renderOfficialWorkflow=()=>renders++,renderApprovalLog=()=>renders++,renderElectronicSealWorkQueue=()=>renders++,refreshDashboardWorkEntryPoints=()=>renders++,showToast=message=>toasts.push(message),resetOfficialWorkflowListFilters=()=>{};
'''

    def test_submit_followup_list_does_not_overwrite_navigate_or_show_stale_error(self):
        for outcome in ("resolve([{id:'A'}])", "reject(new Error('old list failure'))"):
            with self.subTest(outcome=outcome):
                self.run_js(["showSubmittedOfficialDocument", "loadOfficialWorkflow", "loadOfficialDocumentDetail", "ensureOfficialDocumentDetail"], self.LIST_SETUP, r'''
const task=showSubmittedOfficialDocument('A',{isCurrent:()=>valid});valid=false;selectedOfficialDocumentId='B';
''' + f"gate.{outcome};" + r'''
await task;assert.deepEqual(officialWorkflowItems,[{id:'B'}]);assert.equal(selectedOfficialDocumentId,'B');assert.equal(calls.length,1);assert.equal(renders,0);assert.deepEqual(toasts,[]);
''')

    def test_detail_completion_after_logout_cannot_reinsert_private_document_or_delete_new_request(self):
        self.run_js(["ensureOfficialDocumentDetail", "loadOfficialDocumentDetail"], self.LIST_SETUP, r'''
const task=loadOfficialDocumentDetail('A');session='logged-out';const newerPromise=Promise.resolve({id:'A'});officialDocumentDetailRequests.set('A',newerPromise);gate.resolve({id:'A',title:'old private data'});await task;assert.deepEqual(officialWorkflowItems,[{id:'B'}]);assert.equal(officialDocumentDetailReady.has('A'),false);assert.equal(officialDocumentDetailRequests.get('A'),newerPromise);assert.equal(renders,0);assert.deepEqual(toasts,[]);
''')

    RECEIPT_SETUP = r'''
let actor='owner',session='owner-session',allow=true,dialogs=0,toasts=[],posts=[],renders=0;
const frontendSessionScope=()=>session,officialDocumentIsApplicant=item=>item.applicant_id===actor;
let selectedOfficialDocumentId='A',officialWorkflowItems=[{id:'A',applicant_id:'owner',can_confirm:true,current_step:'applicant_confirm',current_status:'stamped'}];
const officialDocumentDetailReady=new Set(['A']),officialReceiptRequests=new Map();
let ensureOfficialDocumentDetail=async(id)=>officialWorkflowItems.find(item=>item.id===id);
const confirmOperation=()=>{dialogs++;return allow},showToast=message=>toasts.push(message);
const renderOfficialWorkflow=()=>renders++,renderApprovalLog=()=>renders++,renderElectronicSealWorkQueue=()=>renders++,refreshDashboardWorkEntryPoints=()=>renders++;
const defer=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}};
let backendRequest=async(path,options)=>{posts.push({path,body:JSON.parse(options.body)});return {...officialWorkflowItems[0],can_confirm:false,current_status:'closed',current_step:''}};
'''

    def receipt(self, case):
        self.run_js(["officialDocumentCanConfirm", "confirmOfficialDocument"], self.RECEIPT_SETUP, case)

    def test_all_receipt_click_handlers_pass_captured_document_ids_not_dom_events(self):
        self.assertIn('addEventListener("click", () => void confirmOfficialDocument(item.id))', self.source)
        self.assertIn('await confirmOfficialDocument(button.dataset.approvalLogConfirm)', self.source)
        self.assertIn('await confirmOfficialDocument(button.dataset.electronicSealConfirm)', self.source)
        self.assertNotIn('addEventListener("click", confirmOfficialDocument)', self.source)
        self.assertIn('officialDetailReady && officialDocumentCanConfirm(officialDocument)', self.source)

    def test_only_applicant_with_server_capability_and_receipt_state_can_confirm(self):
        for mutation in ("actor='reviewer'", "officialWorkflowItems[0].can_confirm=false", "officialWorkflowItems[0].current_status='pending'", "officialWorkflowItems[0].current_step='manager'"):
            with self.subTest(mutation=mutation):
                self.receipt(mutation + ";assert.equal(await confirmOfficialDocument('A'),false);assert.deepEqual(posts,[]);assert.equal(dialogs,0);")

    def test_receipt_cancel_never_posts_and_leaves_case_open(self):
        self.receipt("allow=false;assert.equal(await confirmOfficialDocument('A'),false);assert.deepEqual(posts,[]);assert.equal(officialWorkflowItems[0].current_status,'stamped');assert.equal(officialReceiptRequests.size,0);")

    def test_receipt_double_click_posts_once_and_uses_confirm_never_approve(self):
        self.receipt(r'''
const gate=defer(),original=backendRequest;backendRequest=async(...args)=>{const value=await original(...args);await gate.promise;return value};
const first=confirmOfficialDocument('A'),second=confirmOfficialDocument('A');await Promise.resolve();assert.equal(await second,false);assert.equal(posts.length,1);gate.resolve();assert.equal(await first,true);assert.equal(posts[0].path,'/official-documents/A/confirm');assert.equal(dialogs,1);assert.equal(officialWorkflowItems[0].current_status,'closed');assert.equal(officialReceiptRequests.size,0);assert.equal(await confirmOfficialDocument('A'),false);assert.equal(posts.length,1);
''')

    def test_receipt_response_after_logout_does_not_update_case_or_toast(self):
        self.receipt(r'''
const gate=defer();backendRequest=()=>gate.promise;const task=confirmOfficialDocument('A');await Promise.resolve();session='logged-out';gate.resolve({id:'A',current_status:'closed'});assert.equal(await task,false);assert.equal(officialWorkflowItems[0].current_status,'stamped');assert.deepEqual(toasts,[]);assert.equal(renders,0);assert.equal(officialReceiptRequests.size,0);
''')

    def test_failed_receipt_keeps_case_open_and_releases_double_click_guard_for_retry(self):
        self.receipt(r'''
const original=backendRequest;backendRequest=async()=>{throw new Error('temporary')};assert.equal(await confirmOfficialDocument('A'),false);assert.equal(officialWorkflowItems[0].current_status,'stamped');assert.equal(officialReceiptRequests.size,0);backendRequest=original;assert.equal(await confirmOfficialDocument('A'),true);
''')

    CONFLICT_SETUP = r'''
let session='actor',posts=0,reloads=0,renders=0,closed=0,toasts=[];
const frontendSessionScope=()=>session;
let selectedOfficialDocumentId='A',selectedWorkflowTaskId='A';
const item={id:'A',can_act:true,available_actions:['approve'],current_step:'manager',approval_steps:[{id:'OLD',step_key:'manager',status:'pending'}]};
let officialWorkflowItems=[item];const officialDocumentDetailReady=new Set(['A']),officialDocumentDetailRequests=new Map([['A',Promise.resolve(item)]]);
let officialDecisionState={documentId:'A',operationId:'OLD-OP',reviewAcknowledgements:{application:true}};
const closeOfficialDecisionDialog=()=>{closed++;officialDecisionState={documentId:''}};
const renderOfficialWorkflow=()=>renders++,renderApprovalLog=()=>renders++,renderElectronicSealWorkQueue=()=>renders++,refreshDashboardWorkEntryPoints=()=>renders++,showToast=message=>toasts.push(message);
const backendRequest=async()=>{posts++;throw Object.assign(new Error('conflict'),{status:409})};
let ensureOfficialDocumentDetail=async(id)=>{reloads++;assert.equal(officialDocumentDetailReady.has(id),false);assert.equal(officialDocumentDetailRequests.has(id),false);assert.deepEqual(item.available_actions,[]);assert.equal(item.can_act,false);const fresh={id,can_act:false,available_actions:[],current_step:'next'};officialWorkflowItems=[fresh];officialDocumentDetailReady.add(id);return fresh};
const defer=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
'''

    def test_conflict_invalidates_old_evidence_refreshes_once_and_never_replays_mutation(self):
        self.run_js(["officialDocumentAvailableActions", "mutateOfficialDocument"], self.CONFLICT_SETUP, r'''
assert.equal(await mutateOfficialDocument('approve',{expected_step_id:'OLD'},item,'approvalLog'),false);assert.equal(posts,1);assert.equal(reloads,1);assert.equal(closed,1);assert.equal(officialDecisionState.operationId,undefined);assert.equal(officialWorkflowItems[0].current_step,'next');assert.match(toasts[0],/重新檢閱/);assert.match(toasts[0],/未重送/);
''')

    def test_conflict_reload_failure_keeps_decisions_disabled_without_blind_retry(self):
        self.run_js(["officialDocumentAvailableActions", "mutateOfficialDocument"], self.CONFLICT_SETUP, r'''
ensureOfficialDocumentDetail=async()=>{reloads++;throw new Error('unavailable')};await mutateOfficialDocument('approve',{},item);assert.equal(posts,1);assert.equal(reloads,1);assert.equal(officialDocumentDetailReady.has('A'),false);assert.deepEqual(item.available_actions,[]);assert.match(toasts[0],/目前不開放簽核/);
''')

    def test_conflict_reload_after_account_switch_never_renders_or_toasts(self):
        self.run_js(["officialDocumentAvailableActions", "mutateOfficialDocument"], self.CONFLICT_SETUP, r'''
const gate=defer();ensureOfficialDocumentDetail=async()=>{reloads++;return gate.promise};const task=mutateOfficialDocument('approve',{},item);await Promise.resolve();session='new-actor';gate.resolve({id:'A'});assert.equal(await task,false);assert.equal(posts,1);assert.deepEqual(toasts,[]);assert.equal(renders,0);
''')


if __name__ == '__main__':
    unittest.main()
