"""Delayed PDF autosave responses must not mutate a reopened draft/session."""
from pathlib import Path
import shutil
import subprocess
import unittest

from tests.test_electronic_seal_editor_ui_contract import javascript_function

ROOT = Path(__file__).resolve().parents[1]


class EditorSaveScopeTest(unittest.TestCase):
    def run_case(self, case):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js required for asynchronous editor regression')
        source = (ROOT / 'app.js').read_text()
        functions = '\n'.join(javascript_function(source, name) for name in (
            'saveUploadedEditorState', 'uploadedSealApplicationScopeSnapshot',
            'uploadedSealApplicationScopeIsCurrent',
        ))
        harness = r'''
const assert=require('node:assert/strict');
let session='user-a:company-a',calls=[],statuses=[],conflicts=0,timers=new Map(),timerNo=0;
const frontendSessionScope=()=>session;
const uploadedSealApplicationRuntime={epoch:0};
const uploadedSealEditorRuntime={documentId:'DOC-A',locked:false,conflict:null,saving:false,savePromise:null,saveQueued:false,saveTimer:0,dirtyGeneration:1,savedGeneration:0,baseManifestSha256:'base-a'};
let uploadedSealEditorState={schemaVersion:2,revisionNo:1,manifestSha256:'base-a',elements:[{id:'text-a',kind:'text',properties:{text:'SYNTHETIC A'}}]};
const cloneUploadedEditorValue=value=>JSON.parse(JSON.stringify(value));
const window={clearTimeout:id=>timers.delete(id),setTimeout(fn){timers.set(++timerNo,fn);return timerNo;}};
const navigator={onLine:true};
const document={querySelector:()=>({toggleAttribute(){}})};
const normalizeUploadedEditorSealGeometry=()=>false;
const syncLegacyUploadedEditorCollections=()=>{};
const renderUploadedEditorSvgLayer=()=>{};
const renderUploadedEditorProperties=()=>{};
const renderUploadedSealWorkbench=()=>{};
const setUploadedEditorSaveStatus=(...value)=>statuses.push(value);
let calculateUploadedEditorManifest=async()=> 'hash-a';
let backendRequest=async(path,options)=>{calls.push({path,body:JSON.parse(options.body)});return {revisionNo:2,manifestSha256:'saved-a',state:{...uploadedSealEditorState,revisionNo:2}}};
const applyEditorRevisionFromResponse=result=>{uploadedSealEditorState.revisionNo=result.revisionNo;};
const applyUploadedEditorCanonicalSaveResponse=result=>{uploadedSealEditorState=cloneUploadedEditorValue(result.state);return true;};
const handleUploadedEditorConflict=()=>{conflicts++;uploadedSealEditorRuntime.conflict={};};
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject};};
async function tick(){await Promise.resolve();await Promise.resolve();}
function replaceScope({sameDocument=false,newUser=false}={}){
 uploadedSealApplicationRuntime.epoch++;
 if(newUser)session='user-b:company-b';
 Object.assign(uploadedSealEditorRuntime,{documentId:sameDocument?'DOC-A':'DOC-B',saving:true,savePromise:Promise.resolve('new-operation'),saveQueued:false,dirtyGeneration:3,savedGeneration:2,baseManifestSha256:'base-b',saveTimer:900,conflict:null});
 uploadedSealEditorState={schemaVersion:2,revisionNo:8,manifestSha256:'base-b',elements:[{id:'text-b',properties:{text:'SYNTHETIC B'}}]};
}
'''
        result = subprocess.run([node, '-e', harness + functions + '\n(async()=>{\n' + case + '\n})().catch(error=>{console.error(error);process.exitCode=1;});'], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_current_save_updates_revision_and_clears_busy(self):
        self.run_case('''
await saveUploadedEditorState();
assert.equal(calls.length,1);assert.equal(calls[0].path,'/official-documents/DOC-A/editor-state');
assert.equal(uploadedSealEditorState.revisionNo,2);assert.equal(uploadedSealEditorRuntime.savedGeneration,1);
assert.equal(uploadedSealEditorRuntime.saving,false);assert.equal(uploadedSealEditorRuntime.savePromise,null);
''')

    def test_late_success_cannot_replace_new_or_reopened_draft(self):
        for same_document, new_user in [(False, False), (True, False), (True, True)]:
            with self.subTest(same_document=same_document, new_user=new_user):
                self.run_case('''
const gate=deferred();backendRequest=()=>gate.promise;
const old=saveUploadedEditorState();await tick();
replaceScope({sameDocument:%s,newUser:%s});
const current=JSON.stringify(uploadedSealEditorState),newOperation=uploadedSealEditorRuntime.savePromise,renderCount=statuses.length;
gate.resolve({revisionNo:99,manifestSha256:'stale',state:{revisionNo:99,elements:[]}});await old;
assert.equal(JSON.stringify(uploadedSealEditorState),current,'old response must not overwrite current PDF');
assert.equal(uploadedSealEditorRuntime.baseManifestSha256,'base-b');
assert.equal(uploadedSealEditorRuntime.savePromise,newOperation);assert.equal(uploadedSealEditorRuntime.saving,true);
assert.equal(statuses.length,renderCount);assert.equal(timers.size,0);
''' % (str(same_document).lower(), str(new_user).lower()))

    def test_scope_switch_while_hashing_sends_no_request(self):
        self.run_case('''
const gate=deferred();calculateUploadedEditorManifest=()=>gate.promise;
const old=saveUploadedEditorState();replaceScope();gate.resolve('old-hash');await old;
assert.equal(calls.length,0,'old PDF must never be sent to the new document URL');
assert.equal(uploadedSealEditorRuntime.baseManifestSha256,'base-b');
assert.equal(uploadedSealEditorRuntime.saving,true);
''')

    def test_late_failure_cannot_retry_or_set_new_scope_conflict(self):
        for status in [409, 403, 503]:
            with self.subTest(status=status):
                self.run_case('''
const gate=deferred();backendRequest=()=>gate.promise;
const old=saveUploadedEditorState();await tick();replaceScope({newUser:true});
const newOperation=uploadedSealEditorRuntime.savePromise,renderCount=statuses.length;
gate.reject(Object.assign(new Error('synthetic stale error'),{status:%d}));await old;
assert.equal(conflicts,0);assert.equal(timers.size,0);assert.equal(statuses.length,renderCount);
assert.equal(uploadedSealEditorRuntime.savePromise,newOperation);assert.equal(uploadedSealEditorRuntime.saving,true);
''' % status)

    def test_waiting_immediate_save_does_not_flush_another_draft(self):
        self.run_case('''
const gate=deferred();uploadedSealEditorRuntime.saving=true;uploadedSealEditorRuntime.savePromise=gate.promise;
const old=saveUploadedEditorState({immediate:true});replaceScope();
uploadedSealEditorRuntime.saving=false;uploadedSealEditorRuntime.savePromise=null;
gate.resolve({revisionNo:2});await old;
assert.equal(calls.length,0);assert.equal(uploadedSealEditorState.revisionNo,8);
''')

    def test_scope_switch_between_rejection_microtasks_does_not_leak_old_error(self):
        self.run_case('''
const gate=deferred();backendRequest=()=>gate.promise;
const first=saveUploadedEditorState();await tick();
const waiting=saveUploadedEditorState({immediate:true});
let rejected=0;
const results=Promise.all([first.catch(()=>{rejected++}),waiting.catch(()=>{rejected++})]);
gate.reject(Object.assign(new Error('synthetic old failure'),{status:503}));
await Promise.resolve();
replaceScope({newUser:true});
await results;
assert.equal(rejected,0,'old error must not reach new-scope callers');
assert.equal(uploadedSealEditorRuntime.baseManifestSha256,'base-b');
assert.equal(uploadedSealEditorRuntime.saving,true);
''')

    def test_queued_retry_is_bound_to_the_failed_scope(self):
        self.run_case('''
backendRequest=async()=>{throw Object.assign(new Error('synthetic retry'),{status:503})};
await assert.rejects(saveUploadedEditorState(),/synthetic retry/);assert.equal(timers.size,1);
const retry=[...timers.values()][0];replaceScope();uploadedSealEditorRuntime.saving=false;calls=[];
backendRequest=async()=>{calls.push('unexpected');return {state:{}}};
await retry();await tick();assert.equal(calls.length,0);
''')

    def test_immediate_save_flushes_newer_edits_in_the_same_scope(self):
        self.run_case('''
const gate=deferred();
backendRequest=async(path,options)=>{
 const body=JSON.parse(options.body);calls.push({path,body});
 if(calls.length===1)return gate.promise;
 return {revisionNo:3,manifestSha256:'saved-latest',state:{...body.state,revisionNo:3}};
};
const saving=saveUploadedEditorState({immediate:true});await tick();
uploadedSealEditorState.elements[0].properties.text='LATEST EDIT';
uploadedSealEditorRuntime.dirtyGeneration=2;
gate.resolve({revisionNo:2,manifestSha256:'saved-first',state:{revisionNo:2,elements:[]}});
await saving;
assert.equal(calls.length,2);assert.equal(calls[1].path,'/official-documents/DOC-A/editor-state');
assert.equal(calls[1].body.revisionNo,2);assert.equal(calls[1].body.baseManifestSha256,'saved-first');
assert.equal(calls[1].body.state.elements[0].properties.text,'LATEST EDIT');
assert.equal(uploadedSealEditorState.revisionNo,3);assert.equal(uploadedSealEditorRuntime.savedGeneration,2);
assert.equal(uploadedSealEditorRuntime.saving,false);assert.equal(timers.size,0);
''')


if __name__ == '__main__':
    unittest.main()
