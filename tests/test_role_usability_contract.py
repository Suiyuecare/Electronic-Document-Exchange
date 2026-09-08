"""Executable browser-function contracts for the deidentified role audit fixes."""
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    match = re.search(r"(?:async )?function " + re.escape(name) + r"\([^\n]*\) \{\n.*?\n\}", source, re.S)
    if not match:
        raise AssertionError(name)
    return match.group(0)


class RoleUsabilityContractTest(unittest.TestCase):
    def run_js(self, names, script):
        source = (ROOT / "app.js").read_text()
        functions = "\n".join(function(source, name) for name in names)
        result = subprocess.run(["node", "-e", "const assert=require('node:assert/strict');\n" + functions + "\n" + script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_draft_progress_does_not_claim_submission(self):
        self.run_js(["approvalRecordTimeMeta"], r'''
const draft=approvalRecordTimeMeta({officialDocument:{current_status:'draft',created_at:'created'},doneCount:0,totalSteps:0});
assert.equal(draft.label,'建立時間');assert.equal(draft.value,'created');assert.equal(draft.progress,'草稿・尚未送簽');
assert.equal(approvalRecordTimeMeta({officialDocument:{current_status:'pending',created_at:'not-submitted'}}).value,'尚無送出紀錄');
assert.equal(approvalRecordTimeMeta({officialDocument:{current_status:'pending',approval_steps:[{created_at:'2026-02-02'},{created_at:'2026-02-01'}]}}).value,'2026-02-01');
assert.equal(approvalRecordTimeMeta({officialDocument:{current_status:'pending',submitted_at:'first',correction_resubmitted_at:'second'}}).value,'second');
''')

    def test_internal_dispatch_singleflight_and_recovery(self):
        self.run_js(["runInternalDispatchOnce"], r'''
const internalDispatchMutationsInFlight=new Set();
const button={textContent:'送出',disabled:false,isConnected:true,setAttribute(k,v){this[k]=v},removeAttribute(k){delete this[k]}};
const document={querySelector:()=>button};
(async()=>{
 let resolve,calls=0;const operation=()=>{calls++;return new Promise(r=>resolve=r)};
 const first=runInternalDispatchOnce('create','button',operation);
 assert.equal(button.disabled,true);assert.equal(button['aria-busy'],'true');
 await runInternalDispatchOnce('create','button',operation);assert.equal(calls,1);
 resolve('created');assert.equal(await first,'created');assert.equal(button.disabled,false);assert.equal(button.textContent,'送出');
 await assert.rejects(runInternalDispatchOnce('create','button',async()=>{throw new Error('offline')}));
 assert.equal(button.disabled,false);assert.equal(internalDispatchMutationsInFlight.size,0);
 assert.equal(await runInternalDispatchOnce('create','button',async()=> 'retry'),'retry');
})().catch(e=>{console.error(e);process.exitCode=1});
''')

    def test_tabs_skip_hidden_and_wrap(self):
        self.run_js(["handleWorkspaceTabKeydown"], r'''
let active=-1,prevented=0;
const tabs=Array.from({length:4},(_,i)=>({hidden:i===1,disabled:false,click(){active=i},focus(){},closest(){return {querySelectorAll:()=>tabs}}}));
const key=(i,key)=>handleWorkspaceTabKeydown({currentTarget:tabs[i],key,preventDefault(){prevented++}});
key(0,'ArrowRight');assert.equal(active,2);key(0,'ArrowLeft');assert.equal(active,3);key(3,'Home');assert.equal(active,0);key(0,'End');assert.equal(active,3);assert.equal(prevented,4);
''')

    def test_internal_dispatch_background_scope_and_failure_preservation(self):
        self.run_js(["loadInternalDispatches"], r'''
let authenticated=true,scope='A',internalDispatchLoadGeneration=0,internalDispatchLoadStatus='idle',internalDispatchItems=[],internalDispatchRecipientDirectory=[],selectedInternalDispatchId='',calls=[];
const hasAuthenticatedBackendSession=()=>authenticated,frontendSessionScope=()=>scope,canCreateInternalDispatch=()=>true;
const renderInternalDispatchModule=()=>{},refreshDashboardWorkEntryPoints=()=>{},showToast=()=>{};
let backendRequest=p=>{calls.push(p);return Promise.resolve([{id:'A-1'}])};
(async()=>{
 await loadInternalDispatches(true,{includeDirectory:false});assert.deepEqual(calls,['/internal-dispatches']);assert.equal(internalDispatchItems[0].id,'A-1');
 backendRequest=()=>Promise.reject(new Error('offline'));await loadInternalDispatches();assert.equal(internalDispatchItems[0].id,'A-1');assert.equal(internalDispatchLoadStatus,'error');
 let resolve;backendRequest=()=>new Promise(r=>resolve=r);const old=loadInternalDispatches(true,{includeDirectory:false});scope='B';resolve([{id:'A-OLD'}]);await old;assert.equal(internalDispatchItems[0].id,'A-1');
 authenticated=false;calls=[];backendRequest=p=>{calls.push(p)};await loadInternalDispatches();assert.equal(calls.length,0);
})().catch(e=>{console.error(e);process.exitCode=1});
''')

    def test_compose_validation_order_and_email(self):
        self.run_js(["composeFieldValidations"], r'''
const data={documentCategory:'fixture',approvalRouteCode:'A',dispatchDate:'2026-09-09',recipient:'recipient',subject:'synthetic subject',body:'synthetic body',contactAddress:'address',contactOwner:'owner',contactPhone:'02-66045432 #31',contactEmail:'bad-email',attachmentDetails:''};
const composeValidationData=()=>data,isValidComposeDispatchDate=()=>true,isValidComposeContactPhone=()=>true,Node={DOCUMENT_POSITION_FOLLOWING:4};
const order=['#contactOwner','#contactAddress','#contactEmail','#contactPhone','#dispatchDate','#recipient','#subject','#bodyText','#attachmentDetails','#composeApprovalCategorySelect'];
const nodes=Object.fromEntries(order.map((id,i)=>[id,{validity:{typeMismatch:id==='#contactEmail'},compareDocumentPosition(other){return i<order.indexOf(other.id)?4:2},id}]));
const document={querySelector:s=>nodes[s]||{files:[]}};
const validations=composeFieldValidations();assert.equal(validations[0].selector,'#contactOwner');assert.equal(validations.at(-1).selector,'#composeApprovalCategorySelect');assert.equal(validations.find(x=>x.selector==='#contactEmail').valid,false);
nodes['#contactEmail'].validity.typeMismatch=false;assert.equal(composeFieldValidations().find(x=>x.selector==='#contactEmail').valid,true);
''')

    def test_honest_save_and_mobile_layout_contract(self):
        source=(ROOT/'app.js').read_text();html=(ROOT/'index.html').read_text();css=(ROOT/'styles.css').read_text()
        self.assertIn('renderDailyActionCenter();',function(source,'refreshDashboardWorkEntryPoints'))
        self.assertIn('includeDirectory: false',function(source,'runAuthenticatedStartupSyncs'))
        self.assertIn('fullCaseButton.disabled = !selected',function(source,'renderApprovalLog'))
        self.assertIn('else if (composeSaveState.tone === "saving")',function(source,'saveComposeDraft'))
        self.assertIn('tone: "error"',function(source,'saveComposeDraft'))
        self.assertRegex(html,r'<form[^>]+id="composeForm"[^>]+novalidate')
        self.assertIn('id="composeValidationSummary" role="alert" hidden',html)
        self.assertRegex(css,r'\.compose-form-shell\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)')
        self.assertIn('input.setAttribute("aria-invalid", String(!valid))',function(source,'setComposeFieldValidity'))


if __name__ == '__main__':
    unittest.main()
