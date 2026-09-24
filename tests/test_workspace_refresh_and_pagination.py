"""Run shipping frontend reads against controlled data, never live accounts."""
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkspaceRefreshAndPaginationTest(unittest.TestCase):
    def run_js(self, names, script):
        source = (ROOT / "app.js").read_text()
        functions = []
        for name in names:
            match = re.search(r"(?:async )?function " + name + r"\([^\n]*\) \{\n.*?\n\}", source, re.S)
            self.assertIsNotNone(match, name)
            functions.append(match.group())
        result = subprocess.run(["node", "-e", "const vm=require('node:vm'),assert=require('node:assert/strict');\n" + script, json.dumps("\n".join(functions))], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_refresh_reads_active_route_waits_coalesces_and_preserves_inputs(self):
        self.run_js(["refreshCurrentWorkspace"], r"""
const defer=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {resolve,reject,promise}};
const nodes={};for(const id of ['headerRefreshBtn','mobileDrawerRefreshBtn'])nodes['#'+id]={disabled:false,textContent:'重新整理',setAttribute(k,v){this[k]=v},removeAttribute(k){delete this[k]}};
const c={console,Promise,scope:'actor-a',activeRouteTarget:'approvalLog',workspaceRefreshRequest:null,officialWorkflowScope:'all',officialWorkflowPage:{query:null},calls:[],pending:[],toasts:[],routeBackendDataErrors:new Map(),routeBackendDataLoaded:new Set(['approvalLog']),
 document:{querySelector:s=>nodes[s]||null},frontendSessionScope:()=>c.scope,hasAuthenticatedBackendSession:()=>true,showToast:s=>c.toasts.push(s),renderWorkspaceLoadStatus(){},updateHeaderStatus(){}};
for(const name of ['loadRouteBackendData','syncNotificationsFromBackend','loadApprovalProgressFromBackend','loadOfficialWorkflow','syncDashboardFromBackend','loadInternalDispatches','loadArchiveRecordsFromBackend'])c[name]=(...args)=>{const d=defer();c.calls.push({name,args});c.pending.push(d);return d.promise};
vm.createContext(c);vm.runInContext(JSON.parse(process.argv[1]),c);
(async()=>{
 const first=c.refreshCurrentWorkspace(),second=c.refreshCurrentWorkspace();
 assert.deepEqual(c.calls.map(x=>x.name),['loadRouteBackendData','syncNotificationsFromBackend','loadApprovalProgressFromBackend']);
 assert.equal(c.calls[0].args[2].force,true);assert.equal(c.calls[2].args[0].throwOnError,true);
 assert.equal(nodes['#headerRefreshBtn'].disabled,true);assert.equal(nodes['#mobileDrawerRefreshBtn']['aria-busy'],'true');assert.equal(c.toasts.length,0);
 c.pending[0].resolve(true);c.pending[1].resolve();await Promise.resolve();assert.equal(c.toasts.length,0);
 c.pending[2].resolve();assert.equal(await first,true);assert.equal(await second,true);assert.equal(c.toasts.length,1);assert.equal(nodes['#headerRefreshBtn'].disabled,false);
 const failed=c.refreshCurrentWorkspace();c.pending[3].resolve(true);c.pending[4].reject(Error('offline'));c.pending[5].resolve();assert.equal(await failed,false);
 assert.equal(c.routeBackendDataErrors.has('approvalLog'),true);assert.equal(c.routeBackendDataLoaded.has('approvalLog'),false);assert.match(c.toasts.at(-1),/失敗/);
 const stale=c.refreshCurrentWorkspace(),count=c.toasts.length;c.scope='actor-b';c.pending.slice(6).forEach(x=>x.resolve());assert.equal(await stale,false);assert.equal(c.toasts.length,count);
})().catch(e=>{console.error(e);process.exit(1)});
""")

    def test_pagination_server_search_dedup_errors_and_stale_response_guard(self):
        self.run_js(["loadOfficialWorkflow", "officialWorkflowEndpoint", "loadApprovalProgressFromBackend"], r"""
const defer=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {resolve,reject,promise}};
const c={console,URLSearchParams,Map,Array,JSON,Promise,scope:'A',officialWorkflowScope:'all',officialWorkflowSearchTerm:'',officialWorkflowStatusFilter:'',approvalLogSearchTerm:'old document',approvalLogFilter:'my_pending',
 officialWorkflowItems:[],selectedOfficialDocumentId:'',officialWorkflowPage:{generation:0,scope:'',query:null,cursor:'',hasMore:false,loading:false,error:false},officialDocumentDetailReady:new Set(),officialDocumentDetailRequests:new Map(),calls:[],pending:[],toasts:[],
 frontendSessionScope:()=>c.scope,renderOfficialWorkflowPagination(){},renderOfficialWorkflow(){},renderApprovalLog(){},renderElectronicSealWorkQueue(){},refreshDashboardWorkEntryPoints(){},showToast:s=>c.toasts.push(s),backendRequest:path=>{const d=defer();c.calls.push(path);c.pending.push(d);return d.promise}};
vm.createContext(c);vm.runInContext(JSON.parse(process.argv[1]),c);
(async()=>{
 const first=c.loadApprovalProgressFromBackend();assert.match(c.calls[0],/page_size=50/);assert.match(c.calls[0],/search=old\+document/);assert.match(c.calls[0],/view=my_pending/);
 c.pending[0].resolve({items:[{id:'older-than-1000'}],has_more:true,next_cursor:'opaque:a+b'});await first;
 assert.equal(c.officialWorkflowItems[0].id,'older-than-1000');assert.equal(c.officialWorkflowPage.hasMore,true);
 const more=c.loadOfficialWorkflow('all',{...c.officialWorkflowPage.query,append:true});assert.match(c.calls[1],/cursor=opaque%3Aa%2Bb/);
 c.pending[1].resolve({items:[{id:'older-than-1000'},{id:'last'}],has_more:false,next_cursor:''});await more;assert.equal(c.officialWorkflowItems.length,2);
 const fail=c.loadOfficialWorkflow('all',{throwOnError:true});c.pending[2].reject(Error('offline'));await assert.rejects(fail,/offline/);assert.equal(c.officialWorkflowItems.length,2);assert.equal(c.officialWorkflowPage.error,true);
 const old=c.loadOfficialWorkflow('all',{search:'old'}),latest=c.loadOfficialWorkflow('all',{search:'latest'});c.pending[4].resolve({items:[{id:'latest'}],has_more:false,next_cursor:''});await latest;
 c.pending[3].resolve({items:[{id:'stale'}],has_more:false,next_cursor:''});await old;assert.equal(c.officialWorkflowItems[0].id,'latest');
 const logout=c.loadOfficialWorkflow();c.scope='B';c.pending[5].resolve({items:[{id:'private'}],has_more:false,next_cursor:''});await logout;assert.equal(c.officialWorkflowItems[0].id,'latest');
})().catch(e=>{console.error(e);process.exit(1)});
""")

    def test_company_seal_failure_preserves_cached_metadata_and_retries(self):
        self.run_js(["loadCompanySealCompanyData"], r"""
const defer=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {resolve,reject,promise}};
const c={console,Promise,Array,Error,scope:'actor-A',selectedCompanySealCompanyId:'company-A',selectedCompanySealId:'seal-A',companySealModuleLoaded:true,companySealLibrary:[{id:'seal-A'}],companySealRequests:[{id:'request-A'}],companySealLogs:[{id:'log-A'}],companySealFiles:[{id:'file-A'}],companySealLoadState:{generation:0,status:'loaded'},routeBackendDataLoaded:new Set(['seals']),routeBackendDataErrors:new Map(),pending:[],calls:[],renders:0,
frontendSessionScope:()=>c.scope,renderCompanySealModule(){c.renders++},renderCompanySealLoadStatus(){},renderWorkspaceLoadStatus(){},addSealAudit(){},currentCompanySealCompany:()=>({name:'Synthetic'}),showToast(){},backendRequest:path=>{const d=defer();c.calls.push(path);c.pending.push(d);return d.promise}};
vm.createContext(c);vm.runInContext(JSON.parse(process.argv[1]),c);
(async()=>{
 const first=c.loadCompanySealCompanyData(true,{throwOnError:true});c.pending[0].reject(Error('offline'));c.pending[1].resolve([]);c.pending[2].resolve([]);await assert.rejects(first,/offline/);
 assert.equal(c.companySealLibrary[0].id,'seal-A');assert.equal(c.companySealFiles[0].id,'file-A');assert.equal(c.companySealLoadState.status,'error');assert.equal(c.routeBackendDataLoaded.has('seals'),false);
 const retry=c.loadCompanySealCompanyData(true,{throwOnError:true});c.pending[3].resolve([]);c.pending[4].resolve([]);c.pending[5].resolve([]);await retry;assert.equal(c.companySealLoadState.status,'loaded');assert.equal(c.companySealLibrary.length,0);assert.equal(c.routeBackendDataErrors.has('seals'),false);
 const old=c.loadCompanySealCompanyData(true,{throwOnError:true}),renderCount=c.renders;c.selectedCompanySealCompanyId='company-B';c.pending.slice(6).forEach(x=>x.resolve([{id:'private-A'}]));await old;assert.equal(c.renders,renderCount);assert.equal(c.companySealLibrary.length,0);
})().catch(e=>{console.error(e);process.exit(1)});
""")

    def test_dashboard_reads_attention_and_own_cases_independently(self):
        self.run_js(["loadHomeOfficialCases", "loadDashboardOfficialWorkflow"], r"""
const defer=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {resolve,reject,promise}};
const c={console,Promise,Array,Error,scope:'A',homeOfficialCases:{scope:'',items:[],request:null},dashboardOfficialRequest:null,routeBackendDataErrors:new Map(),calls:[],pending:[],renders:0,
frontendSessionScope:()=>c.scope,renderHomeMyCases(){c.renders++},renderWorkspaceLoadStatus(){},backendRequest:path=>{const d=defer();c.calls.push(path);c.pending.push(d);return d.promise},loadOfficialWorkflow:(scope,options)=>{const d=defer();c.calls.push({scope,...options});c.pending.push(d);return d.promise}};
vm.createContext(c);vm.runInContext(JSON.parse(process.argv[1]),c);
(async()=>{
 const first=c.loadDashboardOfficialWorkflow(),second=c.loadDashboardOfficialWorkflow();assert.equal(c.calls.length,2);assert.equal(c.calls[0].view,'attention');assert.equal(c.calls[0].source,'dashboard');assert.equal(c.calls[1],'/official-documents/my-requests?page_size=5');
 c.pending[0].resolve();c.pending[1].resolve({items:[{id:'own-older-than-1000'}]});assert.equal(await first,true);assert.equal(await second,true);assert.equal(c.homeOfficialCases.items[0].id,'own-older-than-1000');
 const fail=c.loadDashboardOfficialWorkflow({throwOnError:true});c.pending[2].resolve();c.pending[3].reject(Error('offline'));await assert.rejects(fail,/offline/);assert.equal(c.homeOfficialCases.items[0].id,'own-older-than-1000');assert.equal(c.homeOfficialCases.error,true);
 const old=c.loadHomeOfficialCases();c.scope='B';const next=c.loadHomeOfficialCases();c.pending[5].resolve({items:[{id:'new-owner'}]});await next;c.pending[4].resolve({items:[{id:'private-old'}]});await old;assert.equal(c.homeOfficialCases.items[0].id,'new-owner');
})().catch(e=>{console.error(e);process.exit(1)});
""")

    def test_details_cannot_inject_wrong_tab_and_correction_deadline_works(self):
        self.run_js(["filteredApprovalLogRecords", "approvalRecordDueTimestamp"], r"""
const own={task:{id:'old',title:'S',role:'R',status:'draft'},doc:{companyName:'SyntheticCo'},officialDocument:{current_status:'draft'},category:'my_pending'};
const other={task:{id:'detail-injected',title:'S',role:'R',status:'closed'},doc:{companyName:'SyntheticCo'},officialDocument:{current_status:'closed'},category:'processed'};
const c={console,Date,Number,approvalLogSearchTerm:'SyntheticCo',approvalLogFilter:'my_pending',approvalLogRecords:()=>[own,other],approvalProgressCategory:r=>r.category,approvalRecordIsOverdue:()=>false};
vm.createContext(c);vm.runInContext(JSON.parse(process.argv[1]),c);
assert.deepEqual(c.filteredApprovalLogRecords().map(x=>x.task.id),['old']);
assert.equal(c.approvalRecordDueTimestamp({officialDocument:{correction_due_at:'2026-09-20 12:00:00',correction_due_date:'2026-09-30'}}),Date.parse('2026-09-20T12:00:00'));
""")

    def test_production_company_options_survive_metadata_failure_and_child_is_invalidated(self):
        self.run_js(["financeLinkedSealCompanies", "loadCompanySealModule"], r"""
const c={console,Promise,Error,scope:'A',companySealModuleLoaded:false,companySealCompanies:[{id:'chosen',finance_entity_id:'E1'}],companySealLoadState:{generation:4,status:'error'},companySealModuleRequestNo:0,financeDirectoryState:{status:'synced'},companySealReferences:{},routeBackendDataLoaded:new Set(),routeBackendDataErrors:new Map(),selectedCompanySealCompanyId:'chosen',
frontendSessionScope:()=>c.scope,isProductionEdocHost:()=>true,availableCompanySealCompanies:()=>c.companySealCompanies,companySealCompaniesForCurrentUser:x=>x||c.companySealCompanies,
refreshFinanceDirectory:async()=>{},backendRequest:async()=>{throw Error('offline')},renderCompanySealModule(){},renderWorkspaceLoadStatus(){},showToast(){}};
vm.createContext(c);vm.runInContext(JSON.parse(process.argv[1]),c);
(async()=>{assert.equal(c.financeLinkedSealCompanies()[0].id,'chosen');const oldGeneration=c.companySealLoadState.generation;await c.loadCompanySealModule(true);assert.equal(c.companySealLoadState.generation,oldGeneration+1);assert.equal(c.selectedCompanySealCompanyId,'chosen');assert.equal(c.companySealLoadState.status,'error')})().catch(e=>{console.error(e);process.exit(1)});
""")

    def test_authorized_stamp_retry_remains_actionable_without_pending_approval(self):
        self.run_js(["officialDocumentNeedsUserAttention", "approvalProgressCategory", "approvalRecordIsOverdue", "approvalRecordDueTimestamp"], r"""
const c={console,Date,authState:{user:{id:'synthetic-reviewer'}},officialDocumentIsApplicant:()=>false,officialDocumentPendingStepMatchesRole:()=>false};
vm.createContext(c);vm.runInContext(JSON.parse(process.argv[1]),c);
for(const status of ['stamping_failed','general_affairs_approved']) {
 const item={current_status:status,can_act:false,can_manage_dispatch:false,can_retry_stamp:true,applicant_id:'synthetic-other'};
 assert.equal(c.officialDocumentNeedsUserAttention(item),true);
 assert.equal(c.approvalProgressCategory({officialDocument:item}),'my_pending');
 assert.equal(c.approvalProgressCategory({officialDocument:{...item,due_at:'2000-01-01T00:00:00Z'}}),'overdue');
 const denied={...item,can_retry_stamp:false,can_manage_dispatch:true};
 assert.equal(c.officialDocumentNeedsUserAttention(denied),false);
 assert.equal(c.approvalProgressCategory({officialDocument:denied}),'processed');
 assert.equal(c.officialDocumentNeedsUserAttention({...item,can_retry_stamp:'true'}),false);
}
""")


if __name__ == "__main__":
    unittest.main()
