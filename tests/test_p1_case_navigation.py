"""Synthetic navigation guards; paired with real localhost browser acceptance."""
import subprocess
import unittest
from pathlib import Path
from tests.test_workflow_history_frontend import runtime_function

ROOT = Path(__file__).resolve().parents[1]


class CaseNavigationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'app.js').read_text()

    def js(self, names, setup, assertions):
        script = "const assert=require('node:assert/strict');\n" + setup
        script += '\n' + '\n'.join(runtime_function(self.source, name) for name in names)
        script += '\n(async()=>{' + assertions + '})().catch(e=>{console.error(e);process.exitCode=1});'
        result = subprocess.run(['node', '-e', script], text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_route_whitelist_excludes_sensitive_search_and_unknown_modes(self):
        self.js(['parseWorkspaceCaseRoute', 'writeWorkspaceCaseRoute'], '''
const titles={dashboard:'home',approvalLog:'approvals',electronicSeal:'seal'};
let approvalLogFilter='mine';const location={hash:'#dashboard'};
const history={pushState:(_,__,h)=>location.hash=h,replaceState:(_,__,h)=>location.hash=h};
''', '''
const parsed=parseWorkspaceCaseRoute('#electronicSeal?case=OD-A_1&tab=mine&mode=original&search=private-person');
assert.deepEqual(parsed,{route:'electronicSeal',caseId:'OD-A_1',tab:'mine',mode:'original'});
writeWorkspaceCaseRoute(parsed.route,{caseId:parsed.caseId,tab:parsed.tab,mode:parsed.mode});
assert.equal(location.hash,'#electronicSeal?case=OD-A_1&tab=mine&mode=original');
assert.equal(parseWorkspaceCaseRoute('#approvalLog?case=../private&tab=other').caseId,'');
assert.equal(parseWorkspaceCaseRoute('#electronicSeal?case=OD-A&mode=javascript').mode,'edited');
assert.equal(parseWorkspaceCaseRoute('#unknown').route,'dashboard');
''')

    def test_notification_tab_uses_authorized_membership_not_status(self):
        self.js(['officialCasePreferredTab', 'approvalRecordMatchesView'], '''
const officialDocumentIsApplicant=x=>x.applicant_id==='me',hasAuthenticatedBackendSession=()=>true;
''', '''
assert.equal(officialCasePreferredTab({current_status:'submitted',applicant_id:'me',approval_views:{mine:true,acted:false,pending:false}}),'mine');
assert.equal(officialCasePreferredTab({current_status:'closed',approval_views:{mine:true,acted:false,pending:false}}),'mine');
assert.equal(officialCasePreferredTab({current_status:'submitted',approval_views:{mine:false,acted:false,pending:true}}),'pending');
assert.equal(officialCasePreferredTab({current_status:'closed',approval_views:{mine:false,acted:true,pending:false}}),'acted');
assert.equal(officialCasePreferredTab({approval_views:{mine:true,pending:true}},'mine'),'mine');
''')

    def test_pinned_detail_uses_latest_decision_even_after_leaving_pending_list(self):
        self.js(['officialCaseNavigationRecord'], '''
const old={id:'OD-A',current_step:'supervisor',can_act:true};
const latest={id:'OD-A',current_step:'director',can_act:false};
let officialWorkflowItems=[latest];
const approvalLogRecords=items=>items.map(item=>({task:{id:item.id},officialDocument:item}));
''', '''
const navigation={id:'OD-A',detail:old};
const selected=officialCaseNavigationRecord([],navigation);
assert.equal(selected.officialDocument,latest);
assert.equal(selected.officialDocument.can_act,false);
officialWorkflowItems=[];
assert.equal(officialCaseNavigationRecord([],navigation).officialDocument,latest);
assert.equal(officialCaseNavigationRecord([],{id:'OD-A',detail:null}),null);
''')

    NAV_SETUP = '''
let actor='A',authState={token:'token-A'},activeRouteTarget='dashboard',selectedWorkflowTaskId='',selectedOfficialDocumentId='',approvalLogFilter='pending',approvalLogSearchTerm='private query',approvalTaskFilter='overdue';
let officialWorkflowItems=[],officialDocumentDetailReady=new Set(),renders=0,loads=0,routeWrites=[];
const officialCaseNavigation={generation:0,controller:null,scope:'',token:'',id:'',detail:null,loading:false,error:''};
const frontendSessionScope=()=>actor,isRouteAllowed=()=>true;
const document={querySelector:()=>null};
const setView=t=>activeRouteTarget=t,writeWorkspaceCaseRoute=(...args)=>routeWrites.push(args);
const renderApprovalLog=()=>renders++,openApprovalLogMobileDetail=()=>{},loadApprovalProgressFromBackend=()=>{loads++;return Promise.resolve()};
const officialCasePreferredTab=()=> 'mine';
let resolveRead,rejectRead;let backendRequest=()=>new Promise((resolve,reject)=>{resolveRead=resolve;rejectRead=reject});
'''

    def test_late_case_response_cannot_restore_previous_route(self):
        self.js(['clearOfficialCaseNavigation', 'openOfficialCaseFromNavigation'], self.NAV_SETUP, '''
const operation=openOfficialCaseFromNavigation('OD-A');activeRouteTarget='dashboard';
resolveRead({id:'OD-A'});assert.equal(await operation,false);assert.deepEqual(officialWorkflowItems,[]);assert.equal(loads,0);
''')

    def test_late_case_response_is_actor_and_token_isolated(self):
        for switch in ["actor='B'", "authState.token='token-B'"]:
            with self.subTest(switch=switch):
                self.js(['clearOfficialCaseNavigation', 'openOfficialCaseFromNavigation'], self.NAV_SETUP, '''
const operation=openOfficialCaseFromNavigation('OD-A');''' + switch + ''';
resolveRead({id:'OD-A'});assert.equal(await operation,false);assert.deepEqual(officialWorkflowItems,[]);assert.equal(loads,0);
''')

    def test_forbidden_case_never_reuses_old_detail_and_has_recovery(self):
        self.js(['clearOfficialCaseNavigation', 'openOfficialCaseFromNavigation'], self.NAV_SETUP, '''
officialCaseNavigation.detail={id:'OD-OLD'};
const operation=openOfficialCaseFromNavigation('OD-A');rejectRead(Object.assign(new Error('forbidden'),{status:403}));
assert.equal(await operation,false);assert.equal(officialCaseNavigation.detail,null);assert.equal(officialCaseNavigation.loading,false);
assert.match(officialCaseNavigation.error,/沒有查看.*權限.*返回清單/);assert.deepEqual(officialWorkflowItems,[]);
''')

    def test_exact_case_load_does_not_keep_unrelated_search(self):
        self.js(['clearOfficialCaseNavigation', 'openOfficialCaseFromNavigation'], self.NAV_SETUP, '''
const operation=openOfficialCaseFromNavigation('OD-A');resolveRead({id:'OD-A'});assert.equal(await operation,true);
assert.equal(selectedWorkflowTaskId,'OD-A');assert.equal(approvalLogFilter,'mine');
assert.equal(approvalLogSearchTerm,'');assert.equal(approvalTaskFilter,'');assert.equal(officialDocumentDetailReady.has('OD-A'),true);
''')

    def test_cancel_new_application_does_not_save_reset_or_navigate(self):
        self.js(['startNewUploadedSealApplication'], '''
const hasBackendPermission=()=>true,frontendSessionScope=()=> 'A';
let uploadedSealBlankInputScope='A',calls=[];
const uploadedSealApplicationRuntime={openPromise:null,submissionBusy:false};
const uploadedSealEditorRuntime={documentId:'',locked:false,dirtyGeneration:0,savedGeneration:0};
const uploadedSealApplicationScopeSnapshot=()=>({}),uploadedSealApplicationScopeIsCurrent=()=>true;
const uploadedSealApplicationHasUnsavedChanges=()=>false,requestWorkspaceConfirmation=async()=>false;
const document={querySelector:()=>({value:'unsaved'})},showToast=x=>calls.push(x);
const flushUploadedSealDraftBeforeSwitch=async()=>calls.push('write'),clearUploadedEditorSensitivePreviews=()=>calls.push('reset'),setView=()=>calls.push('navigate');
''', '''
assert.equal(await startNewUploadedSealApplication(),false);assert.deepEqual(calls,[]);
''')

    def test_new_application_is_blocked_during_unknown_submission(self):
        self.js(['startNewUploadedSealApplication'], '''
const hasBackendPermission=()=>true;let calls=[];
const uploadedSealApplicationRuntime={submissionBusy:true},uploadedSealEditorRuntime={};
const showToast=x=>calls.push(x);
''', '''
assert.equal(await startNewUploadedSealApplication(),false);assert.equal(calls.length,1);assert.match(calls[0],/正在處理/);
''')


if __name__ == '__main__':
    unittest.main()
