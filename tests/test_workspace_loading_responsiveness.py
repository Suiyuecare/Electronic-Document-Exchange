"""Execute production route loading with controlled slow reads, never live data."""
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
    return match.group()


class WorkspaceLoadingResponsivenessTest(unittest.TestCase):
    def test_parallel_reads_coalesce_and_stale_responses_are_isolated(self):
        source = (ROOT / "app.js").read_text()
        functions = "\n".join(function(source, name) for name in (
            "renderWorkspaceLoadStatus", "resetRouteBackendData", "loadRouteBackendData"))
        script = r"""
const vm=require('node:vm'),assert=require('node:assert/strict');
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};}
const tick=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
function setup(){
 const nodes={};for(const name of ['workspaceLoadStatus','workspaceLoadLabel','workspaceLoadRetryBtn'])nodes['#'+name]={hidden:true,textContent:'',dataset:{}};
 nodes['#uploadedSealCompany']={value:'company-a'};nodes['#officialCompanySelect']={value:'compose-company'};nodes['#composeCompanySelect']={value:'compose-company-name'};
 const c={console:{warn(){}},Map,Set,Promise,Error,scope:'user-a:company-a',authenticated:true,activeRouteTarget:'electronicSeal',headerBackendSyncState:{status:'idle',syncedAt:''},calls:[],pending:[],renders:0,
   routeBackendDataLoaded:new Set(),routeBackendDataRequests:new Map(),routeBackendDataErrors:new Map(),routeBackendDataScope:'',
   uploadedSealEditorRuntime:{directoryLoading:true},financeDirectoryState:{status:'synced'},inboundDocumentLoadState:{scope:'user-a:company-a'},
   document:{querySelector:s=>nodes[s]||null},nodes,frontendSessionScope:()=>c.scope,hasAuthenticatedBackendSession:()=>c.authenticated,updateHeaderStatus(){},
   renderUploadedSealCompanyOptions(){},renderUploadedSealWorkbench(){c.renders++},setUploadedEditorSaveStatus(){}};
 for(const name of ['loadFinanceCompanyDirectory','loadOfficialWorkflowConfig','loadOfficialWorkflowCandidates','renderEditableOfficialWorkflowConfig','loadUploadedSealOptions','loadOfficialSealOptions','refreshWorkflowReadinessForContext','loadWorkflowDelegations','loadInboundDocuments','loadInternalDispatches','loadInboundAssigneeCandidates','loadCompanySealModule','syncJobsFromBackend','syncDatabaseFromBackend','loadUiUsageSummary','syncGoLiveAuditFromBackend'])
   c[name]=(...args)=>{const d=deferred();c.calls.push({name,args});c.pending.push({name,...d});return d.promise};
 c.loadComposeSealOptions=(...args)=>{c.calls.push({name:'loadComposeSealOptions',args});return Promise.resolve([])};
 vm.createContext(c);vm.runInContext(JSON.parse(process.argv[1]),c);return c;
}
const resolveAll=c=>c.pending.forEach(d=>d.resolve());
(async()=>{
 let c=setup(),settled=false;
 const a=c.loadRouteBackendData('electronicSeal'),b=c.loadRouteBackendData('electronicSeal').then(()=>settled=true);
 assert.deepEqual(c.calls.map(x=>x.name),['loadFinanceCompanyDirectory','loadOfficialWorkflowConfig']);
 assert.equal(c.nodes['#workspaceLoadStatus'].hidden,false);assert.equal(c.nodes['#workspaceLoadStatus'].dataset.state,'loading');
 assert.equal(c.routeBackendDataLoaded.has('electronicSeal'),false);
 c.pending[0].resolve();await tick();assert.equal(settled,false);assert.equal(c.calls.length,2);
 c.pending[1].resolve();await tick();
 assert.deepEqual(c.calls.slice(2).map(x=>x.name),['loadUploadedSealOptions','refreshWorkflowReadinessForContext']);
 assert.equal(c.calls.some(x=>x.name==='loadOfficialSealOptions'),false);
 assert.equal(c.calls[2].args[0],'company-a');assert.equal(settled,false);
 resolveAll(c);await Promise.all([a,b]);
 assert.equal(c.routeBackendDataLoaded.has('electronicSeal'),true);assert.equal(c.nodes['#workspaceLoadStatus'].hidden,true);
 await c.loadRouteBackendData('electronicSeal');assert.equal(c.calls.length,4);

 c=setup();const old=c.loadRouteBackendData('electronicSeal');c.scope='user-b:company-b';
 const newer=c.loadRouteBackendData('electronicSeal');assert.equal(c.calls.length,4);
 c.pending[0].resolve();c.pending[1].resolve();await old;
 assert.equal(c.calls.length,4);assert.equal(c.renders,0);assert.equal(c.routeBackendDataRequests.size,1);
 assert.equal(c.routeBackendDataLoaded.size,0);
 resolveAll(c);await tick();resolveAll(c);await newer;assert.equal(c.routeBackendDataLoaded.size,1);

 c=setup();const logout=c.loadRouteBackendData('electronicSeal');c.resetRouteBackendData();resolveAll(c);await logout;
 assert.equal(c.calls.length,2);assert.equal(c.routeBackendDataLoaded.size,0);assert.equal(c.renders,0);

 c=setup();const fail=c.loadRouteBackendData('electronicSeal');c.pending[0].reject(new Error('offline'));c.pending[1].resolve();await fail;
 assert.equal(c.routeBackendDataLoaded.size,0);assert.equal(c.nodes['#workspaceLoadRetryBtn'].hidden,false);
 assert.equal(c.nodes['#workspaceLoadStatus'].dataset.state,'error');assert.equal(c.nodes['#uploadedSealCompany'].value,'company-a');
 const retry=c.loadRouteBackendData('electronicSeal');assert.equal(c.nodes['#workspaceLoadRetryBtn'].hidden,true);
 resolveAll(c);await tick();resolveAll(c);await retry;assert.equal(c.routeBackendDataLoaded.size,1);

 c=setup();c.financeDirectoryState.status='error';const unavailable=c.loadRouteBackendData('electronicSeal');resolveAll(c);await unavailable;
 assert.equal(c.calls.length,2);assert.equal(c.routeBackendDataLoaded.size,0);assert.equal(c.routeBackendDataErrors.has('electronicSeal'),true);

 c=setup();const readinessFailure=c.loadRouteBackendData('electronicSeal');resolveAll(c);await tick();
 c.pending[2].resolve();c.pending[3].resolve({error:'offline',submitAllowed:false});await readinessFailure;
 assert.equal(c.routeBackendDataLoaded.size,0);assert.equal(c.nodes['#workspaceLoadRetryBtn'].hidden,false);
 const readinessRetry=c.loadRouteBackendData('electronicSeal');resolveAll(c);await tick();
 assert.equal(c.calls.at(-1).args[1].force,true);resolveAll(c);await readinessRetry;
 assert.equal(c.routeBackendDataLoaded.has('electronicSeal'),true);

 c=setup();const businessBlocked=c.loadRouteBackendData('electronicSeal');resolveAll(c);await tick();
 c.pending[2].resolve();c.pending[3].resolve({submitAllowed:false,blockers:['missing_manager']});await businessBlocked;
 assert.equal(c.routeBackendDataLoaded.has('electronicSeal'),true);assert.equal(c.routeBackendDataErrors.size,0);

 c=setup();c.activeRouteTarget='compose';const compose=c.loadRouteBackendData('compose');resolveAll(c);await tick();
 assert.deepEqual(c.calls.slice(2).map(x=>x.name),['loadComposeSealOptions','loadOfficialSealOptions','refreshWorkflowReadinessForContext']);
 resolveAll(c);await compose;assert.equal(c.calls[2].args[0],'compose-company-name');assert.equal(c.calls[3].args[0],'compose-company');

 c=setup();c.activeRouteTarget='settings';const settings=c.loadRouteBackendData('settings');
 assert.deepEqual(c.calls.map(x=>x.name),['loadFinanceCompanyDirectory','loadOfficialWorkflowConfig']);
 assert.equal(c.calls[1].args[1].deferCandidates,true);
 resolveAll(c);await settings;
 assert.equal(c.calls.some(x=>x.name==='loadOfficialWorkflowCandidates'),true);
 assert.equal(c.routeBackendDataLoaded.has('settings'),true);
 assert.equal(c.calls.some(x=>x.name==='syncGoLiveAuditFromBackend'),false);

 c=setup();const ops=c.loadRouteBackendData('ops');
 assert.deepEqual(c.calls.map(x=>x.name),['syncGoLiveAuditFromBackend']);
 resolveAll(c);await ops;assert.equal(c.routeBackendDataLoaded.has('ops'),true);

 c=setup();const background=c.loadRouteBackendData('electronicSeal');c.activeRouteTarget='dashboard';await c.loadRouteBackendData('dashboard');
 assert.equal(c.nodes['#workspaceLoadStatus'].hidden,true);resolveAll(c);await tick();resolveAll(c);await background;
 assert.equal(c.nodes['#workspaceLoadStatus'].hidden,true);

 c=setup();c.authenticated=false;await c.loadRouteBackendData('electronicSeal');assert.equal(c.calls.length,0);
 console.log('9 route responsiveness, coalescing, retry and scope scenarios passed');
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", script, json.dumps(functions)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("9 route responsiveness", result.stdout)

    def test_failed_directory_retry_is_not_throttled_but_healthy_reads_are(self):
        functions = function((ROOT / "app.js").read_text(), "refreshFinanceDirectory")
        script = r"""
const vm=require('node:vm'),assert=require('node:assert/strict');
const c={console:{warn(){}},Date,Promise,Error,Array,FINANCE_DIRECTORY_REFRESH_INTERVAL_MS:30000,
 hasAuthenticatedBackendSession:()=>true,financeDirectoryRefreshPromise:null,financeDirectoryRefreshGeneration:0,
 financeDirectoryState:{status:'synced',lastAttemptAt:Date.now()},authState:{user:{id:'synthetic'}},calls:0,
 renderFinanceDirectorySyncStatus(){},applyFinanceDirectoryPayload(){c.financeDirectoryState.status='synced'},showToast(){},
 backendRequest:async()=>{c.calls++;return {companies:[],departments:[]}}};
vm.createContext(c);vm.runInContext(JSON.parse(process.argv[1]),c);
(async()=>{
 assert.equal((await c.refreshFinanceDirectory()).throttled,true);assert.equal(c.calls,0);
 c.financeDirectoryState.status='error';await c.refreshFinanceDirectory();assert.equal(c.calls,1);
 assert.equal((await c.refreshFinanceDirectory()).throttled,true);assert.equal(c.calls,1);
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", script, json.dumps(functions)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_status_is_nonblocking_accessible_and_reduced_motion_aware(self):
        html = (ROOT / "index.html").read_text()
        css = (ROOT / "styles.css").read_text()
        self.assertIn('id="workspaceLoadStatus" role="status" aria-live="polite" hidden', html)
        self.assertIn('id="workspaceLoadRetryBtn" type="button" hidden', html)
        self.assertIn('.workspace-load-status[hidden] { display: none; }', css)
        self.assertIn('@media (prefers-reduced-motion: reduce)', css)
        self.assertIn('animation: none; width: 100%; opacity: .6;', css)


if __name__ == "__main__":
    unittest.main()
