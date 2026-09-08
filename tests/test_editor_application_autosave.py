"""Application metadata saves separately from immutable PDF editor revisions."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

from tests.test_electronic_seal_editor_ui_contract import javascript_function

ROOT = Path(__file__).resolve().parents[1]


class EditorApplicationAutosaveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'app.js').read_text()

    def run_javascript(self, case):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js required for browser function regression')
        names = [
            'uploadedSealApplicationPatch', 'uploadedSealApplicationKey',
            'uploadedSealApplicationHasUnsavedChanges', 'scheduleUploadedSealApplicationSave',
            'syncUploadedSealApplicationDraft', 'flushUploadedSealDraftBeforeSwitch',
            'invalidateUploadedEditorSubmissionPreview', 'uploadedEditorSubmissionFingerprint',
            'uploadedEditorSubmissionPreviewIsCurrent',
            'uploadedSealApplicationScopeSnapshot', 'uploadedSealApplicationScopeIsCurrent',
            'resetUploadedSealApplicationSaving', 'ensureUploadedEditorDraft',
        ]
        def runtime_function(name):
            # These top-level helpers include a default argument calling another
            # helper, which the legacy one-level argument regex cannot parse.
            match = re.search(r'(?:async )?function ' + re.escape(name) + r'\(', self.source)
            self.assertIsNotNone(match, name)
            following = re.search(r'\n(?:async )?function \w+\(', self.source[match.end():])
            self.assertIsNotNone(following, name)
            return self.source[match.start():match.end() + following.start()]
        functions = '\n'.join(runtime_function(name) for name in names)
        harness = r'''
const assert = require('node:assert/strict');
const timers = new Map();let nextTimer=0;let calls=[];let savePdfCalls=0;let statusRenders=0;
let sessionScope='user-one:company-one';
const frontendSessionScope=()=>sessionScope;
const window={clearTimeout:(id)=>timers.delete(id),setTimeout:(fn)=>{timers.set(++nextTimer,fn);return nextTimer;}};
const navigator={onLine:true};
const draft={title:'Original',description:'Reason',request_reason:'Reason',handler_name:'Test person',dispatch_unit:'Test unit'};
const document={querySelector:()=>({value:draft.title})};
const uploadedSealEditorRuntime={documentId:'OD-TEST',locked:false,saving:false,dirtyGeneration:0,savedGeneration:0,conflict:null};
const uploadedSealEditorState={revisionNo:1,manifestSha256:'manifest-one'};
const uploadedSealApplicationRuntime={documentId:'OD-TEST',savedKey:'',timer:0,promise:null,error:'',editable:true,retryCount:0,epoch:0};
const officialWorkflowItems=[{id:'OD-TEST'}];
const editorDraftPayload=()=>({...draft});
function renderUploadedSealApplicationSaveStatus(){statusRenders++;}
function renderUploadedEditorSubmissionActions(){}
function renderElectronicSealWorkQueue(){}
async function saveUploadedEditorState(){savePdfCalls++;}
const uploadedEditorV2FeatureEnabled=()=>true;
const approvalSelectionForSelect=()=>({documentCategory:'test',approvalRouteCode:'A'});
function rememberUploadedEditorSavedSealBindings(){}
function setUploadedEditorSaveStatus(){}
let backendRequest=async(path,options)=>{calls.push({path,body:JSON.parse(options.body)});return {id:'OD-TEST',...JSON.parse(options.body)}};
'''
        script = harness + functions + "\nuploadedSealApplicationRuntime.savedKey=uploadedSealApplicationKey();\n(async()=>{\n" + case + "\n})().catch(error=>{console.error(error);process.exitCode=1});"
        result = subprocess.run([node, '-e', script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_saves_only_application_patch_and_updates_saved_key(self):
        self.run_javascript('''
draft.title='Edited';await syncUploadedSealApplicationDraft();
assert.equal(calls.length,1);assert.equal(calls[0].path,'/official-documents/OD-TEST');
assert.deepEqual(Object.keys(calls[0].body),['title','subject','description','request_reason','handler_name','dispatch_unit']);
assert.equal(calls[0].body.title,'Edited');assert.equal(uploadedSealApplicationHasUnsavedChanges(),false);
assert.equal(savePdfCalls,0);
''')

    def test_edit_during_inflight_save_is_flushed_as_a_second_patch(self):
        self.run_javascript('''
let release;backendRequest=async(path,options)=>{calls.push(JSON.parse(options.body));if(calls.length===1)await new Promise(resolve=>release=resolve);return {id:'OD-TEST'}};
draft.title='First change';const saving=syncUploadedSealApplicationDraft();
draft.title='Latest change';release();await saving;
assert.equal(calls.length,2);assert.equal(calls[0].title,'First change');assert.equal(calls[1].title,'Latest change');
assert.equal(draft.title,'Latest change');assert.equal(uploadedSealApplicationHasUnsavedChanges(),false);
''')

    def test_failed_save_does_not_claim_saved_and_explicit_retry_succeeds(self):
        self.run_javascript('''
draft.title='Unsaved';const original=backendRequest;
backendRequest=async()=>{throw Object.assign(new Error('Temporary error'),{status:503})};
await assert.rejects(syncUploadedSealApplicationDraft(),/Temporary error/);
assert.equal(uploadedSealApplicationHasUnsavedChanges(),true);assert.equal(uploadedSealApplicationRuntime.error,'Temporary error');
assert.equal(timers.size,1);assert.equal(uploadedSealApplicationRuntime.promise,null);
backendRequest=original;await syncUploadedSealApplicationDraft();
assert.equal(uploadedSealApplicationHasUnsavedChanges(),false);assert.equal(uploadedSealApplicationRuntime.error,'');
''')

    def test_denied_save_never_retries_and_blocks_case_switch(self):
        self.run_javascript('''
draft.title='Denied';backendRequest=async()=>{throw Object.assign(new Error('No permission'),{status:403})};
await assert.rejects(flushUploadedSealDraftBeforeSwitch(),/No permission/);
assert.equal(uploadedSealEditorRuntime.documentId,'OD-TEST');assert.equal(timers.size,0);
assert.equal(uploadedSealApplicationHasUnsavedChanges(),true);
''')

    def test_offline_or_pdf_conflict_blocks_switch_without_losing_state(self):
        self.run_javascript('''
draft.title='Offline';navigator.onLine=false;
await assert.rejects(flushUploadedSealDraftBeforeSwitch(),/離線/);assert.equal(calls.length,0);
navigator.onLine=true;uploadedSealEditorRuntime.dirtyGeneration=2;uploadedSealEditorRuntime.conflict={};
await assert.rejects(flushUploadedSealDraftBeforeSwitch(),/尚未保存完成/);assert.equal(savePdfCalls,1);
assert.equal(uploadedSealEditorRuntime.documentId,'OD-TEST');
''')

    def test_upload_in_progress_blocks_case_switch(self):
        self.run_javascript('''
uploadedSealEditorRuntime.uploading=true;
await assert.rejects(flushUploadedSealDraftBeforeSwitch(),/正在上傳/);assert.equal(calls.length,0);
''')

    def test_readonly_application_cannot_autosave(self):
        self.run_javascript('''
draft.title='Read only';uploadedSealEditorRuntime.locked=true;
await syncUploadedSealApplicationDraft();scheduleUploadedSealApplicationSave();
assert.equal(calls.length,0);assert.equal(timers.size,0);
''')

    def test_old_success_cannot_contaminate_reopened_same_document_or_new_user(self):
        for switch_user in [False, True]:
            with self.subTest(switch_user=switch_user):
                self.run_javascript('''
let release;backendRequest=()=>new Promise(resolve=>release=resolve);
draft.title='Old request';const oldSave=syncUploadedSealApplicationDraft();
resetUploadedSealApplicationSaving();
''' + ("sessionScope='user-two:company-two';" if switch_user else '') + '''
Object.assign(uploadedSealApplicationRuntime,{documentId:'OD-TEST',savedKey:'NEW-SNAPSHOT',error:'NEW-ERROR'});
officialWorkflowItems[0]={id:'OD-TEST',title:'NEW-SCOPE'};
const newOperation=Promise.resolve();uploadedSealApplicationRuntime.promise=newOperation;
const renders=statusRenders;
release({id:'OD-TEST',title:'OLD-RESPONSE'});await oldSave;
assert.equal(uploadedSealApplicationRuntime.savedKey,'NEW-SNAPSHOT');
assert.equal(officialWorkflowItems[0].title,'NEW-SCOPE');
assert.equal(uploadedSealApplicationRuntime.error,'NEW-ERROR');
assert.equal(uploadedSealApplicationRuntime.promise,newOperation);
assert.equal(statusRenders,renders);assert.equal(timers.size,0);
''')

    def test_old_rejection_does_not_retry_or_replace_new_scope_error(self):
        self.run_javascript('''
let reject;backendRequest=()=>new Promise((resolve,no)=>reject=no);
draft.title='Old request';const oldSave=syncUploadedSealApplicationDraft();
resetUploadedSealApplicationSaving();sessionScope='user-two:company-one';
Object.assign(uploadedSealApplicationRuntime,{documentId:'OD-TEST',savedKey:'NEW-SNAPSHOT',error:'NEW-ERROR'});
const newOperation=Promise.resolve();uploadedSealApplicationRuntime.promise=newOperation;
const renders=statusRenders;reject(Object.assign(new Error('OLD-ERROR'),{status:503}));await oldSave;
assert.equal(uploadedSealApplicationRuntime.error,'NEW-ERROR');assert.equal(timers.size,0);
assert.equal(uploadedSealApplicationRuntime.promise,newOperation);assert.equal(statusRenders,renders);
''')

    def test_account_scope_change_alone_rejects_stale_success(self):
        self.run_javascript('''
let release;backendRequest=()=>new Promise(resolve=>release=resolve);
draft.title='Old request';const oldSave=syncUploadedSealApplicationDraft();
sessionScope='user-two:company-one';
const newOperation=Promise.resolve();uploadedSealApplicationRuntime.promise=newOperation;
uploadedSealApplicationRuntime.savedKey='NEW-SNAPSHOT';officialWorkflowItems[0].title='NEW-SCOPE';
const renders=statusRenders;release({id:'OD-TEST',title:'OLD-SCOPE'});await oldSave;
assert.equal(uploadedSealApplicationRuntime.savedKey,'NEW-SNAPSHOT');
assert.equal(officialWorkflowItems[0].title,'NEW-SCOPE');
assert.equal(uploadedSealApplicationRuntime.promise,newOperation);assert.equal(statusRenders,renders);
''')

    def test_old_rejected_promise_waiter_does_not_raise_in_new_scope(self):
        self.run_javascript('''
let reject;uploadedSealApplicationRuntime.promise=new Promise((resolve,no)=>reject=no);
draft.title='Old request';const oldWaiter=syncUploadedSealApplicationDraft();
resetUploadedSealApplicationSaving();uploadedSealApplicationRuntime.documentId='OD-TEST';
uploadedSealApplicationRuntime.error='NEW-ERROR';
reject(new Error('OLD-ERROR'));await oldWaiter;
assert.equal(calls.length,0);assert.equal(uploadedSealApplicationRuntime.error,'NEW-ERROR');
''')

    def test_old_promise_waiter_cannot_recursively_save_reopened_scope(self):
        self.run_javascript('''
let release;uploadedSealApplicationRuntime.promise=new Promise(resolve=>release=resolve);
draft.title='Old request';const oldWaiter=syncUploadedSealApplicationDraft();
resetUploadedSealApplicationSaving();
Object.assign(uploadedSealApplicationRuntime,{documentId:'OD-TEST',savedKey:'NEW-SNAPSHOT'});
release();await oldWaiter;assert.equal(calls.length,0);assert.equal(uploadedSealApplicationRuntime.savedKey,'NEW-SNAPSHOT');
''')

    def test_stale_debounce_and_retry_callbacks_do_not_save_new_scope(self):
        self.run_javascript('''
draft.title='Old request';scheduleUploadedSealApplicationSave();const debounce=[...timers.values()][0];
resetUploadedSealApplicationSaving();uploadedSealApplicationRuntime.documentId='OD-TEST';debounce();
assert.equal(calls.length,0);
backendRequest=async()=>{calls.push('retry-failure');throw Object.assign(new Error('Temporary error'),{status:503})};
await assert.rejects(syncUploadedSealApplicationDraft());const retry=[...timers.values()][0];
resetUploadedSealApplicationSaving();uploadedSealApplicationRuntime.documentId='OD-TEST';retry();
assert.equal(calls.length,1);assert.equal(timers.size,0);
''')

    def test_draft_creation_old_response_cannot_replace_new_document_or_promise(self):
        self.run_javascript('''
uploadedSealEditorRuntime.documentId='';resetUploadedSealApplicationSaving();
let release;backendRequest=()=>new Promise(resolve=>release=resolve);
const creation=ensureUploadedEditorDraft();resetUploadedSealApplicationSaving();sessionScope='user-two:company-one';
uploadedSealEditorRuntime.documentId='NEW-DOC';
const newOperation=Promise.resolve();uploadedSealEditorRuntime.draftCreatePromise=newOperation;
uploadedSealApplicationRuntime.savedKey='NEW-SNAPSHOT';
release({document_id:'OLD-DOC',revision_id:'OLD-REV'});
await assert.rejects(creation,/已忽略/);
assert.equal(uploadedSealEditorRuntime.documentId,'NEW-DOC');
assert.equal(uploadedSealApplicationRuntime.savedKey,'NEW-SNAPSHOT');
assert.equal(uploadedSealEditorRuntime.draftCreatePromise,newOperation);
''')

    def test_confirmation_binds_revision_hash_file_and_application_snapshot(self):
        self.run_javascript('''
Object.assign(uploadedSealEditorRuntime,{reviewMode:'prepared',preparedPdfDocument:{},revisionId:'REV-1',preparedFileId:'FILE-1',preparedSha256:'hash-one'});
uploadedSealApplicationRuntime.submissionPreview=uploadedEditorSubmissionFingerprint();
assert.equal(uploadedEditorSubmissionPreviewIsCurrent(),true);
for(const [object,key,replacement] of [
 [uploadedSealEditorRuntime,'documentId','OD-OTHER'],[uploadedSealEditorRuntime,'revisionId','REV-2'],
 [uploadedSealEditorRuntime,'preparedFileId','FILE-2'],[uploadedSealEditorRuntime,'preparedSha256','hash-two'],
 [uploadedSealEditorState,'revisionNo',2],[uploadedSealEditorState,'manifestSha256','manifest-two'],
 [draft,'title','Other title']]){
 const old=object[key];object[key]=replacement;assert.equal(uploadedEditorSubmissionPreviewIsCurrent(),false,key);object[key]=old;
}
assert.equal(uploadedEditorSubmissionPreviewIsCurrent(),true);
uploadedSealEditorRuntime.preparedPdfDocument=null;assert.equal(uploadedEditorSubmissionPreviewIsCurrent(),false);
''')

    def test_application_edit_explicitly_invalidates_second_confirmation(self):
        self.run_javascript('''
uploadedSealApplicationRuntime.submissionPreview='previous-confirmation';draft.title='New';
scheduleUploadedSealApplicationSave();assert.equal(uploadedSealApplicationRuntime.submissionPreview,null);
''')

    def test_first_submit_action_previews_and_returns_before_mutation(self):
        source = javascript_function(self.source, 'submitUploadedSealApplication')
        self.assertIn('if (!uploadedEditorSubmissionPreviewIsCurrent())', source)
        self.assertLess(source.index('await showUploadedEditorReview("prepared")'), source.index('/submit`'))
        first_stage = source[source.index('await showUploadedEditorReview("prepared")'):source.index('// This is a second')]
        self.assertIn('return;', first_stage)
        self.assertNotIn('window.confirm(', source)
        self.assertIn('uploadedSealApplicationRuntime.submissionBusy = true', source)
        self.assertIn('renderUploadedSealWorkbench()', source)

    def test_restore_fetches_authorized_application_and_preserves_backend_locks(self):
        source = javascript_function(self.source, 'loadUploadedEditorState')
        self.assertLess(source.index('await flushUploadedSealDraftBeforeSwitch'), source.index('const application = await backendRequest'))
        self.assertLess(source.index('const application = await backendRequest'), source.index('clearUploadedEditorSensitivePreviews'))
        self.assertIn('restoreUploadedSealApplication(application)', source)
        self.assertIn('!officialDocumentIsApplicant(application)', source)
        self.assertIn('!["draft", "rejected"].includes(application.current_status)', source)
        restore = javascript_function(self.source, 'restoreUploadedSealApplication')
        for name in ['Company', 'Department', 'Applicant', 'Title', 'Reason', 'ApprovalCategorySelect']:
            self.assertIn('#uploadedSeal' + name, restore)

    def test_dedicated_save_status_and_beforeunload_guard_are_wired(self):
        self.assertIn('uploadedSealApplicationSaveStatus', self.source)
        self.assertIn('input.addEventListener("input", scheduleUploadedSealApplicationSave)', self.source)
        self.assertIn('window.addEventListener("beforeunload"', self.source)
        self.assertIn('event.returnValue = ""', self.source)


if __name__ == '__main__':
    unittest.main()
