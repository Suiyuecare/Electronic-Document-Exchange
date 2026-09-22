"""Execute production seal loaders with synthetic responses, never live data."""
import json
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SealOptionLoadingErrorsTest(unittest.TestCase):
    SETUP = r"""
const vm=require('node:vm'),assert=require('node:assert/strict');
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};}
function setup(kind){
 const c={Array,Promise,Error,scope:'actor-a:company-a',authenticated:true,requests:[],renders:[],toasts:[],
 officialSealOptions:[{id:'old'}],uploadedSealOptions:[{id:'old'}],uploadedSealOptionsRequestNo:0,
 financeDirectoryRefreshGeneration:0,departmentRegistry:[],resetRouteBackendData(){},renderFinanceDirectorySyncStatus(){},
 uploadedSealEditorRuntime:{sealOptionsLoading:false,documentId:'synthetic-doc',locked:false},uploadedSealEditorState:{},
 nodes:{'#officialCompanySelect':{value:'A'},'#uploadedSealCompany':{value:'A',dataset:{},replaceChildren(){}}}};
 c.document={querySelector:s=>c.nodes[s]||null};c.frontendSessionScope=()=>c.scope;c.hasAuthenticatedBackendSession=()=>c.authenticated;
 c.renderOfficialSealOptions=()=>c.renders.push('official');c.renderUploadedSealOptions=()=>c.renders.push('uploaded');
 c.renderUploadedSealWorkbench=()=>c.renders.push('workbench');c.showToast=text=>c.toasts.push(text);
 c.normalizeUploadedEditorSealGeometry=()=>false;
 c.backendRequest=path=>{const d=deferred();c.requests.push({path,...d});return d.promise};
 vm.createContext(c);vm.runInContext(JSON.parse(process.argv[1]),c);
 c.load=kind==='official'?c.loadOfficialSealOptions:c.loadUploadedSealOptions;
 c.records=()=>kind==='official'?c.officialSealOptions:c.uploadedSealOptions;
 c.selector=kind==='official'?'#officialCompanySelect':'#uploadedSealCompany';
 return c;
}
"""

    def run_js(self, body):
        source = (ROOT / "app.js").read_text()
        functions = []
        for name in ("loadOfficialSealOptions", "loadUploadedSealOptions", "clearFinanceDirectoryCache"):
            match = re.search(r"(?:async )?function " + name + r"\([^\n]*\) \{\n.*?\n\}", source, re.S)
            self.assertIsNotNone(match, name)
            functions.append(match.group())
        script = self.SETUP + "\n(async()=>{\n" + body + r"""
console.log('seal loaders passed');
})().catch(error=>{console.error(error);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", script, json.dumps("\n".join(functions))], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_strict_transport_failures_render_before_rejecting(self):
        self.run_js(r"""
for(const kind of ['official','uploaded'])for(const status of [403,500]){
 const c=setup(kind),error=Object.assign(new Error('synthetic transport failure'),{status});
 const pending=c.load('A',{throwOnError:true});
 c.requests[0].reject(error);
 await assert.rejects(pending,actual=>actual===error);
 assert.equal(c.records().length,0);assert.ok(c.renders.includes(kind));
 if(kind==='uploaded'){assert.equal(c.uploadedSealEditorRuntime.sealOptionsLoading,false);assert.equal(c.renders.at(-1),'workbench');}
}
""")

    def test_default_callers_keep_existing_nonthrowing_behavior(self):
        self.run_js(r"""
for(const kind of ['official','uploaded']){
 const c=setup(kind),pending=c.load('A');c.requests[0].reject(new Error('offline'));await pending;
 assert.equal(c.records().length,0);assert.ok(c.renders.includes(kind));
 assert.equal(c.toasts.length,kind==='uploaded'?1:0);
}
""")

    def test_empty_or_inactive_business_results_are_not_transport_failures(self):
        self.run_js(r"""
for(const kind of ['official','uploaded'])for(const rows of [[],[{id:'inactive',is_active:false}],[{id:'active'},{id:'disabled',is_active:0}]]){
 const c=setup(kind),pending=c.load('A',{throwOnError:true});c.requests[0].resolve(rows);await pending;
 assert.deepEqual(c.records().map(row=>row.id),rows.filter(row=>row.is_active!==false&&row.is_active!==0).map(row=>row.id));
 assert.equal(c.toasts.length,0);
}
""")

    def test_invalid_response_is_retryable_not_an_empty_company(self):
        self.run_js(r"""
for(const kind of ['official','uploaded']){
 const c=setup(kind),pending=c.load('A',{throwOnError:true});c.requests[0].resolve({error:'invalid'});
 await assert.rejects(pending,/seal_list_response_invalid/);assert.equal(c.records().length,0);
 const retry=c.load('A',{throwOnError:true});c.requests[1].resolve([{id:'recovered'}]);await retry;
 assert.equal(c.records()[0].id,'recovered');
}
""")

    def test_old_company_success_or_error_cannot_replace_current_records(self):
        self.run_js(r"""
for(const kind of ['official','uploaded'])for(const fails of [false,true]){
 const c=setup(kind),old=c.load('A',{throwOnError:true});c.nodes[c.selector].value='B';
 const current=c.load('B',{throwOnError:true});c.requests[1].resolve([{id:'B-seal'}]);await current;
 const renders=c.renders.length;
 if(fails)c.requests[0].reject(new Error('old-company'));else c.requests[0].resolve([{id:'A-seal'}]);await old;
 assert.equal(c.records()[0].id,'B-seal');assert.equal(c.renders.length,renders);assert.equal(c.toasts.length,0);
}
""")

    def test_old_session_and_logout_responses_do_not_render_or_leak_errors(self):
        self.run_js(r"""
for(const kind of ['official','uploaded'])for(const logout of [false,true])for(const fails of [false,true]){
 const c=setup(kind),pending=c.load('A',{throwOnError:true}),renders=c.renders.length;
 if(logout)c.authenticated=false;else c.scope='actor-b:company-b';
 if(fails)c.requests[0].reject(new Error('old-session'));else c.requests[0].resolve([{id:'stale'}]);await pending;
 assert.equal(c.records()[0].id,'old');assert.equal(c.renders.length,renders);assert.equal(c.toasts.length,0);
}
""")

    def test_newest_same_company_request_wins_and_anonymous_never_fetches(self):
        self.run_js(r"""
for(const kind of ['official','uploaded']){
 const c=setup(kind),old=c.load('A',{throwOnError:true}),current=c.load('A',{throwOnError:true});
 c.requests[1].resolve([{id:'newest'}]);await current;c.requests[0].resolve([{id:'oldest'}]);await old;
 assert.equal(c.records()[0].id,'newest');
 c.authenticated=false;await c.load('A',{throwOnError:true});assert.equal(c.requests.length,2);assert.equal(c.records().length,0);
}
""")

    def test_cache_reset_invalidates_response_even_for_same_actor_relogin(self):
        self.run_js(r"""
for(const fails of [false,true]){
 const c=setup('official'),pending=c.load('A',{throwOnError:true});
 c.clearFinanceDirectoryCache();
 if(fails)c.requests[0].reject(new Error('old login'));else c.requests[0].resolve([{id:'old-login-seal'}]);await pending;
 assert.equal(c.records()[0].id,'old');assert.equal(c.renders.length,0);assert.equal(c.toasts.length,0);
 const retry=c.load('A',{throwOnError:true});c.requests[1].resolve([{id:'new-login-seal'}]);await retry;
 assert.equal(c.records()[0].id,'new-login-seal');
}
""")


if __name__ == "__main__":
    unittest.main()
