"""Exercise shipping config loader promises without network or real identities."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkflowConfigLoadCoalescingTest(unittest.TestCase):
    def run_javascript(self, case):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js required for frontend promise regressions")
        source = (ROOT / "app.js").read_text()
        functions = []
        for name in ("resetOfficialWorkflowConfigEditor", "loadOfficialWorkflowConfig"):
            match = re.search(r"(?:async )?function " + name + r"\([^\n]*\) \{\n[\s\S]*?\n\}", source)
            self.assertIsNotNone(match, name)
            functions.append(match.group())
        harness = r'''
const assert=require('node:assert/strict');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
const tick=()=>new Promise(r=>setImmediate(r));
let scope='actor-A',authenticated=true;
const frontendSessionScope=()=>scope,hasAuthenticatedBackendSession=()=>authenticated;
const officialWorkflowConfigEditor={scope,categories:null,loading:false,saving:false,dirty:false,conflict:false,candidateRequest:0};
let officialWorkflowConfig={schema_version:3,version:1,categories:{original:{nodes:[]}}};
let officialWorkflowConfigLoadRequest=null,officialWorkflowConfigLoadGeneration=0;
const officialWorkflowReadinessByRoute=new Map(),officialWorkflowReadinessRequests=new Map();
const nodes={};const document={querySelector:s=>nodes[s]||(nodes[s]={textContent:''})};
const calls=[],gates=[],toasts=[];let renders=0,candidates=0;
const backendRequest=url=>{calls.push(url);const gate=deferred();gates.push(gate);return gate.promise};
function renderOfficialWorkflowConfig(){renders++}
function renderEditableOfficialWorkflowConfig(){renders++}
function loadOfficialWorkflowCandidates(){candidates++;return Promise.resolve()}
function showToast(message){toasts.push(message)}
const response=version=>({schema_version:3,version,categories:{synthetic:{nodes:[]}}});
'''
        script = harness + "\n" + "\n".join(functions) + "\n(async()=>{\n" + case + "\n})().catch(e=>{console.error(e);process.exitCode=1});"
        result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cross_route_waiters_share_one_request_and_observe_same_version(self):
        self.run_javascript(r'''
const seen=[];
const compose=loadOfficialWorkflowConfig(true,{throwOnError:true}).then(()=>seen.push(['compose',officialWorkflowConfig.version]));
const upload=loadOfficialWorkflowConfig(true,{throwOnError:true}).then(()=>seen.push(['upload',officialWorkflowConfig.version]));
await tick();assert.equal(calls.length,1);assert.equal(seen.length,0);assert.equal(officialWorkflowConfigEditor.loading,true);
gates[0].resolve(response(7));await Promise.all([compose,upload]);
assert.deepEqual(seen,[['compose',7],['upload',7]]);assert.equal(officialWorkflowConfigEditor.loading,false);
assert.equal(officialWorkflowConfigLoadRequest,null);assert.equal(candidates,1);
''')

    def test_strict_failure_rejects_nonstrict_is_consumed_and_retry_fetches(self):
        self.run_javascript(r'''
const errors=[];process.on('unhandledRejection',e=>errors.push(e));
const background=loadOfficialWorkflowConfig(false);
const strict=loadOfficialWorkflowConfig(false,{throwOnError:true});
const rejected=assert.rejects(strict,/offline/);
gates[0].reject(new Error('offline'));await Promise.all([background,rejected]);await tick();
assert.equal(errors.length,0);assert.equal(toasts.length,1);assert.equal(officialWorkflowConfig.version,1);
assert.equal(officialWorkflowConfigLoadRequest,null);assert.equal(officialWorkflowConfigEditor.loading,false);
const retry=loadOfficialWorkflowConfig(true,{throwOnError:true});assert.equal(calls.length,2);
gates[1].resolve(response(8));await retry;assert.equal(officialWorkflowConfig.version,8);
''')

    def test_nonstrict_unobserved_caller_does_not_leak_rejection(self):
        self.run_javascript(r'''
const errors=[];process.on('unhandledRejection',e=>errors.push(e));
void loadOfficialWorkflowConfig();gates[0].reject(new Error('offline'));await tick();await tick();
assert.equal(errors.length,0);assert.equal(toasts.length,0);assert.equal(officialWorkflowConfigEditor.loading,false);
''')

    def test_same_actor_reset_invalidates_old_success_failure_and_finally(self):
        self.run_javascript(r'''
for(const fail of [false,true]){
 const old=loadOfficialWorkflowConfig(false,{throwOnError:true});const oldGate=gates.at(-1);
 resetOfficialWorkflowConfigEditor();const current=loadOfficialWorkflowConfig();const newGate=gates.at(-1);
 const newRequest=officialWorkflowConfigLoadRequest,before=renders;
 if(fail)oldGate.reject(new Error('stale failure'));else oldGate.resolve(response(100));await old;
 assert.equal(officialWorkflowConfigLoadRequest,newRequest);assert.equal(officialWorkflowConfigEditor.loading,true);
 assert.equal(officialWorkflowConfig.version,undefined);assert.equal(renders,before);assert.equal(toasts.length,0);
 newGate.resolve(response(9));await current;assert.equal(officialWorkflowConfig.version,9);
}
''')

    def test_new_session_can_start_without_adopting_old_response(self):
        self.run_javascript(r'''
const old=loadOfficialWorkflowConfig();scope='actor-B';const current=loadOfficialWorkflowConfig();
assert.equal(calls.length,2);const request=officialWorkflowConfigLoadRequest;
gates[0].resolve(response(100));await old;assert.equal(officialWorkflowConfig.version,1);
assert.equal(officialWorkflowConfigLoadRequest,request);assert.equal(officialWorkflowConfigEditor.loading,true);
gates[1].resolve(response(10));await current;assert.equal(officialWorkflowConfig.version,10);
''')

    def test_logout_does_not_publish_old_data_or_error(self):
        self.run_javascript(r'''
const old=loadOfficialWorkflowConfig(false,{throwOnError:true});authenticated=false;resetOfficialWorkflowConfigEditor();
const before=renders;gates[0].reject(new Error('private old error'));await old;
assert.equal(renders,before);assert.equal(toasts.length,0);assert.equal(officialWorkflowConfigEditor.loading,false);
assert.equal(officialWorkflowConfigLoadRequest,null);assert.equal(officialWorkflowConfig.version,undefined);
''')

    def test_dirty_and_saving_protections_apply_before_and_during_load(self):
        self.run_javascript(r'''
officialWorkflowConfigEditor.dirty=true;await loadOfficialWorkflowConfig(true,{throwOnError:true});assert.equal(calls.length,0);
officialWorkflowConfigEditor.dirty=false;officialWorkflowConfigEditor.saving=true;await loadOfficialWorkflowConfig();assert.equal(calls.length,0);
officialWorkflowConfigEditor.saving=false;
for(const guard of ['dirty','saving']){
 const pending=loadOfficialWorkflowConfig();officialWorkflowConfigEditor[guard]=true;
 gates.at(-1).resolve(response(99));await pending;assert.equal(officialWorkflowConfig.version,1);
 assert.equal(officialWorkflowConfigEditor[guard],true);assert.equal(officialWorkflowConfigEditor.loading,false);
 officialWorkflowConfigEditor[guard]=false;
}
''')

    def test_explicit_discard_still_reloads_and_clears_confirmed_unsaved_state(self):
        self.run_javascript(r'''
officialWorkflowConfigEditor.dirty=true;officialWorkflowConfigEditor.categories={unsaved:{nodes:[]}};
const pending=loadOfficialWorkflowConfig(false,{discardChanges:true});assert.equal(calls.length,1);
gates[0].resolve(response(11));await pending;
assert.equal(officialWorkflowConfig.version,11);assert.equal(officialWorkflowConfigEditor.dirty,false);
assert.equal(officialWorkflowConfigEditor.categories,null);
''')


if __name__ == "__main__":
    unittest.main()
