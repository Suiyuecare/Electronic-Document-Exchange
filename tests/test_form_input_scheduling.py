"""Committed-input scheduling executes shipping functions with a fake clock."""
from pathlib import Path
import ast
import subprocess
import unittest

from tests.test_compose_output_contract import function

ROOT = Path(__file__).resolve().parents[1]


class FormInputSchedulingTest(unittest.TestCase):
    COMPOSE_FUNCTIONS = [
        'composeInputScope', 'composeInputIsComposing', 'startComposeComposition',
        'finishComposeComposition', 'flushComposeInputUpdates', 'markDraftDirty',
        'scheduleDraftPreviewRender', 'writeComposeAutosave',
        'scheduleComposeCloudSave', 'saveComposeCloudDraft', 'resetComposeAsyncScope',
    ]
    SETUP = r'''
const assert=require('node:assert/strict');
let now=0,nextTimer=0;const timers=new Map();
function setTimeout(fn,delay){timers.set(++nextTimer,{fn,at:now+delay});return nextTimer;}
function clearTimeout(id){timers.delete(id);}
const window={setTimeout,clearTimeout};
async function tick(ms){const until=now+ms;for(;;){const due=[...timers].filter(([,t])=>t.at<=until).sort((a,b)=>a[1].at-b[1].at)[0];if(!due)break;now=due[1].at;timers.delete(due[0]);due[1].fn();for(let n=0;n<8;n++)await Promise.resolve();}now=until;}
const nodes={'#composeCompanySelect':{value:'Company',dataset:{}},'#subject':{value:'Initial'},'#submitDispatchBtn':{disabled:false}};
const document={querySelector:key=>nodes[key]};
const composeInputRuntime={composing:false,compositionScope:'',pending:false};
let draftPreviewRenderTimer=null,composeCloudTimer=null,composeCloudEpoch=0;
let draftConfirmed=true,draftSigned=true,activeComposeStep='fill';
let modalCloses=0;const hideComposeSubmitDialog=()=>{modalCloses++};
let composeCloudOperation=null,composeCloudDraftId='',composeCloudConflict=false;
let composeRecoveryCandidate=null,composeRecoveryDismissedIdentity='',composeAiOperation=null,composeAiSuggestion=null,composeAiUndo=null,composeAiReview=null;
const composeAutosaveIdentity=()=>session,renderComposeAiActions=()=>{};
let currentComposeDraftId='',composeDraftRequestId='',session='user-one';
const authState={token:'synthetic',user:{id:'U',company_id:'CO'}};
const frontendSessionScope=()=>session,composeRequestScope=()=>composeInputScope();
const composeCloudRevisions=new Map(),composeCloudSavedSnapshots=new Map();
const composeAutosaveStorageKey='fixture';let composeSaveState={};
const composeRawSnapshot=()=>({userId:authState.user.id,companyId:authState.user.company_id,values:{'#subject':nodes['#subject'].value}});
const composeSnapshotHasMeaningfulContent=snapshot=>!!snapshot.values['#subject'];
const formatComposeSaveTime=()=>'',renderComposeSaveStatus=()=>{};
let localWrites=[];const localStorage={setItem:(key,value)=>localWrites.push(JSON.parse(value))};
let previews=[];function renderDraftPreview(){previews.push(nodes['#subject'].value);}
const navigator={onLine:true};let puts=[];
let backendRequest=async(path,options)=>{puts.push(JSON.parse(options.body));return{revision:puts.length};};
'''

    def run_case(self, body, extra_functions=(), extra_setup=''):
        source = (ROOT / 'app.js').read_text()
        functions = '\n'.join(function(source, name) for name in [*self.COMPOSE_FUNCTIONS, *extra_functions])
        result = subprocess.run(
            ['node', '-e', self.SETUP + extra_setup + functions + '\n(async()=>{' + body + '})().catch(e=>{console.error(e);process.exit(1)});'],
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_paused_ime_never_saves_or_previews_partial_text(self):
        self.run_case('''
markDraftDirty();await tick(220); // Cancel the already scheduled cloud save.
const before=localWrites.length;startComposeComposition();
nodes['#subject'].value='組字中的部分';markDraftDirty({isComposing:true});
await tick(5000);assert.equal(localWrites.length,before);assert.equal(puts.length,0);assert.equal(previews.length,1);
assert.equal(draftConfirmed,false);assert.ok(modalCloses>0);
assert.equal(flushComposeInputUpdates(),false);assert.equal(await saveComposeCloudDraft(),null);
''')

    def test_compositionend_and_final_input_coalesce_latest_snapshot_once(self):
        self.run_case('''
startComposeComposition();nodes['#subject'].value='部分';markDraftDirty({isComposing:true});
nodes['#subject'].value='已完成文字';finishComposeComposition();markDraftDirty({isComposing:false});
await tick(219);assert.equal(localWrites.length,0);assert.equal(previews.length,0);
await tick(1);assert.equal(localWrites.length,1);assert.deepEqual(previews,['已完成文字']);
await tick(1800);assert.equal(puts.length,1);assert.equal(puts[0].snapshot.values['#subject'],'已完成文字');
assert.equal(localWrites[0].snapshot.values['#subject'],'已完成文字');
''')

    def test_ordinary_burst_has_one_preview_local_save_and_cloud_mutation(self):
        self.run_case('''
for(let n=0;n<12;n++){nodes['#subject'].value='Latest '+n;markDraftDirty();await tick(10);}
assert.equal(localWrites.length,0);assert.equal(previews.length,0);
await tick(220);assert.equal(localWrites.length,1);assert.deepEqual(previews,['Latest 11']);
await tick(1800);assert.equal(puts.length,1);assert.equal(puts[0].snapshot.values['#subject'],'Latest 11');
''')

    def test_manual_flush_immediately_preserves_latest_committed_text(self):
        self.run_case('''
nodes['#subject'].value='Manual latest';markDraftDirty();
assert.equal(flushComposeInputUpdates(),true);assert.equal(localWrites.length,1);assert.deepEqual(previews,['Manual latest']);
await saveComposeCloudDraft();assert.equal(puts.length,1);assert.equal(puts[0].snapshot.values['#subject'],'Manual latest');
await tick(3000);assert.equal(puts.length,1);assert.equal(previews.length,1);
''')

    def test_scope_change_rejects_pending_old_preview_and_cloud_callbacks(self):
        self.run_case('''
markDraftDirty();const stalePreview=[...timers.values()][0].fn;
resetComposeAsyncScope();session='user-two';nodes['#subject'].value='New account';stalePreview();
assert.equal(localWrites.length,0);assert.equal(previews.length,0);assert.equal(puts.length,0);
markDraftDirty();await tick(220);const staleCloud=[...timers.values()][0].fn;
resetComposeAsyncScope();session='user-three';staleCloud();await tick(3000);assert.equal(puts.length,0);
startComposeComposition();markDraftDirty({isComposing:true});resetComposeAsyncScope();finishComposeComposition();assert.equal(timers.size,0);
''')

    def test_old_cloud_success_during_new_composition_does_not_write_partial_text(self):
        self.run_case('''
let release;backendRequest=(path,options)=>{puts.push(JSON.parse(options.body));return new Promise(resolve=>release=resolve);};
const saving=saveComposeCloudDraft();startComposeComposition();nodes['#subject'].value='未完成組字';markDraftDirty({isComposing:true});
release({revision:1});await saving;assert.equal(localWrites.length,0);assert.equal(puts.length,1);assert.equal(timers.size,0);
nodes['#subject'].value='完成新版';finishComposeComposition();await tick(2020);
assert.equal(puts.length,2);assert.equal(puts[1].snapshot.values['#subject'],'完成新版');
''')

    def test_company_options_are_stable_until_directory_changes(self):
        self.run_case('''
let writes=0,html='';Object.defineProperty(nodes['#composeCompanySelect'],'innerHTML',{get:()=>html,set:v=>{writes++;html=v;}});
renderComposeCompanyOptions();renderComposeCompanyOptions();assert.equal(writes,1);
companies.push({name:'Other'});renderComposeCompanyOptions();assert.equal(writes,2);
assert.equal(nodes['#composeCompanySelect'].value,'Company');
''', ['renderComposeCompanyOptions'], '''
const companies=[{name:'Company'}],financeDirectoryCompanies=()=>companies,financeDirectoryCurrentCompany=()=>companies[0],financeIdentitySelectionLocked=()=>false,escapeDraftHtml=String;
''')

    def test_stepper_keeps_tab_nodes_focus_and_single_handlers_when_state_changes(self):
        self.run_case('''
renderComposeStepper();const original=buttons[0];document.activeElement=original;
activeIndex=1;activeComposeStep='confirm';renderComposeStepper();renderComposeStepper();
assert.equal(tabWrites,1);assert.equal(buttons[0],original);assert.equal(document.activeElement,original);
assert.equal(buttons[0].listeners,1);assert.equal(buttons[1].listeners,1);
assert.equal(buttons[1].attributes['aria-current'],'step');assert.equal(buttons[0].attributes['aria-current'],undefined);
''', ['renderComposeStepper'], '''
let tabWrites=0,buttons=[],activeIndex=0;
const stepper={dataset:{},querySelectorAll:()=>buttons};
Object.defineProperty(stepper,'innerHTML',{set:()=>{tabWrites++;buttons=['fill','confirm'].map(key=>({dataset:{composeStep:key},listeners:0,attributes:{},classList:{toggle(){}},addEventListener(){this.listeners++;},setAttribute(k,v){this.attributes[k]=v;},removeAttribute(k){delete this.attributes[k];}}));}});
nodes['#composeStepper']=stepper;document.querySelectorAll=()=>[];
const renderComposeFieldHints=()=>{},renderComposeContactSummary=()=>{},applyWorkflowReadinessSubmitGuards=()=>{};
const composeStepState=()=>[{key:'fill',label:'Fill',body:'Form',done:false},{key:'confirm',label:'Confirm',body:'Review',done:false}];
const composeStepIndex=()=>activeIndex,composeNextControlState=()=>({disabled:false,text:'Next'}),composePanesForStep=()=>[];
''')

    def test_explicit_manual_save_during_ime_does_not_create_official_document(self):
        self.run_case('''
startComposeComposition();markDraftDirty({isComposing:true});
assert.equal(await saveComposeDraft(),null);assert.equal(localWrites.length,0);assert.equal(puts.length,0);assert.equal(previews.length,0);
''', ['saveComposeDraft'], 'const showToast=()=>{};')

    def test_browser_probe_scripts_parse_before_acceptance_runs(self):
        source = (ROOT / 'tools/form_input_browser_acceptance.py').read_text()
        tree = ast.parse(source)
        scripts = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                   and isinstance(node.value, str) and node.value.startswith(('(()=>{', '(async()=>{'))]
        self.assertGreaterEqual(len(scripts), 5)
        for script in scripts:
            result = subprocess.run(['node', '--check'], input=script, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('No hosted service', source)
        self.assertIn("run(output, cases=['metadata'])", source)

    def test_native_compose_and_application_fields_bind_composition_lifecycle(self):
        source = (ROOT / 'app.js').read_text()
        for statement in [
            'element?.addEventListener("compositionstart", startComposeComposition)',
            'element?.addEventListener("compositionend", finishComposeComposition)',
            'input.addEventListener("compositionstart", startUploadedSealApplicationComposition)',
            'input.addEventListener("compositionend", finishUploadedSealApplicationComposition)',
            'if (!flushComposeInputUpdates()) return showToast("請先完成文字輸入。")',
        ]:
            self.assertIn(statement, source)


if __name__ == '__main__':
    unittest.main()
