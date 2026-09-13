"""Own Finance defaults with explicit, scoped company and unit selection."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

from tests.test_finance_directory_ui_contract import javascript_function

ROOT = Path(__file__).resolve().parents[1]


class EditorApplicantIdentityFrontendTest(unittest.TestCase):
    def run_js(self, case):
        source = (ROOT / "app.js").read_text()
        names = ["uploadedSealApplicantDepartment", "renderUploadedSealDepartmentOptions", "renderUploadedSealCompanyOptions",
                 "uploadedSealDepartments", "uploadedSealApplicantSelectionBusy", "handleUploadedSealCompanyChange",
                 "uploadedSealApplicationPatch", "loadUploadedSealOptions",
                 "preferredFinanceDepartment", "editorDraftPayload", "uploadedSealCompanies",
                 "friendlyBackendErrorMessage"]
        def top_level_function(name):
            start = re.search(r'^(?:async )?function ' + re.escape(name) + r'\(', source, re.M)
            # Match the next top-level function, so apostrophes in comments
            # are not confused with JavaScript string delimiters.
            following = re.search(r'^function |^async function ', source[start.end():], re.M)
            return source[start.start():start.end() + following.start()]
        functions = "\n".join(top_level_function(name) for name in names)
        harness = r'''
const assert = require('node:assert/strict');
let authenticated = true;
const hasAuthenticatedBackendSession = () => authenticated;
let authState = {user:{id:'TEST-CEO',role:'執行長',company_id:'TEST-CO',unit:'測試公司層級'}};
let financeDirectoryState = {currentApplicantDepartment:{id:'A1000',code:'A1000',name:'測試公司層級',companyId:'TEST-CO',status:'active',unitType:'division'}};
let departments = [{id:'OTHER',code:'D100',name:'非本人部門',companyId:'TEST-CO',status:'active'}];
financeDirectoryState.editorApplicantCompanies = [{id:'TEST-CO',name:'測試公司',status:'active'},{id:'OTHER-CO',name:'可選公司',status:'active'}];
financeDirectoryState.editorApplicantDepartments = [financeDirectoryState.currentApplicantDepartment,...departments,{id:'D200',code:'D200',name:'另一公司部門',companyId:'OTHER-CO',status:'active'}];
const financeDepartmentsForCompany = () => departments;
const financeDepartmentMatchesCompany = (d,c) => d.companyId === c.id;
const financeDirectoryCurrentCompany = () => ({id:'TEST-CO',name:'測試公司'});
const financeDirectoryCompanies = () => [{id:'TEST-CO'},{id:'OTHER-CO'}];
const parseJsonMaybe = s => s ? JSON.parse(s) : null;
const escapeDraftHtml = s => String(s);
const activeUnit = () => authState.user.unit;
const PDF_A4_INVALID_MESSAGE = 'A4';
let uploadedSealMode = 'official_document';
const PDF_EDITOR_SCHEMA_VERSION = 2, PDF_EDITOR_RENDERER_VERSION = 'test';
const approvalSelectionForSelect = () => ({documentCategory:'合作意向書',approvalRouteCode:'A'});
const uploadedSealEditorRuntime = {documentId:'',locked:false,companyChanging:false};
const uploadedSealApplicationRuntime = {submissionBusy:false};
const uploadedSealEditorState = {sourceFiles:[],pages:[],elements:[]};
let calls=[],toasts=[],confirmResult=true,clears=0,flushFailure=null;
const window={confirm:()=>confirmResult};
const officialWorkflowReadinessByRoute={clear(){}};
const uploadedSealApplicationScopeSnapshot=()=>({scope:'one',epoch:0,documentId:uploadedSealEditorRuntime.documentId});
const uploadedSealApplicationScopeIsCurrent=s=>s.documentId===uploadedSealEditorRuntime.documentId;
const frontendSessionScope=()=> 'one';
const flushUploadedSealDraftBeforeSwitch=async()=>{calls.push({operation:'flush',company:company.value});if(flushFailure)throw flushFailure;};
const clearUploadedEditorSensitivePreviews=()=>{clears++;uploadedSealEditorRuntime.documentId='';uploadedSealEditorState.pages=[];uploadedSealEditorState.elements=[];};
const renderUploadedSealWorkbench=()=>{};
const finishUploadedEditorTextEdit=()=>true; // No transient text edit in this identity fixture.
const renderUploadedSealOptions=()=>{};
const invalidateUploadedEditorSubmissionPreview=()=>{};
const refreshWorkflowReadinessForContext=async()=>{};
const showToast=s=>toasts.push(s);
let uploadedSealOptions=[],uploadedSealOptionsRequestNo=0;
let backendRequest=async(path)=>{calls.push({path});return [];};
const normalizeUploadedEditorSealGeometry=()=>false;
function makeSelect(){return {value:'',dataset:{},options:[],disabled:false,
  set innerHTML(html){
    this.options = [...html.matchAll(/<option value="([^"]*)"([^>]*)>(.*?)<\/option>/g)].map(m => ({value:m[1],textContent:m[3],dataset:{financeUnitCode:(m[2].match(/data-finance-unit-code="([^"]*)"/)||[])[1]||''}}));
    this.value = this.options[0]?.value || '';
  }, get selectedOptions(){return this.options.filter(x => x.value === this.value);},
  set selectedIndex(index){this.value=this.options[index]?.value||'';},
  append(option){this.options.push(option);}
};}
const select=makeSelect(),company=makeSelect();
company.value='TEST-CO';
const fields = {'#uploadedSealDepartment':select,'#uploadedSealCompany':company,
 '#uploadedSealApplicant':{value:'測試申請人'},'#uploadedSealTitle':{value:'測試'},'#uploadedSealReason':{value:'測試原因'}};
const document = {querySelector: selector => fields[selector] || null,createElement:()=>({dataset:{}})};
'''
        result = subprocess.run([shutil.which("node") or "node", "-e", harness + functions + "\n(async()=>{" + case + "})().catch(error=>{console.error(error);process.exitCode=1});"], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_authenticated_roles_keep_their_own_division(self):
        self.run_js('''
for(const role of ['執行長','行政部主任','總務','主任','員工']){
 authState.user.role=role;select.value='';select.dataset={};
 renderUploadedSealDepartmentOptions();
 assert.equal(select.value,'測試公司層級');assert.equal(select.disabled,false);
 assert.equal(select.options.length,3);
 const payload=editorDraftPayload();
 assert.equal(payload.applicant_department_name,'測試公司層級');
 assert.equal(payload.applicant_department_id,'A1000');
 assert.equal(payload.dispatch_unit,'測試公司層級');
 assert.deepEqual(uploadedSealCompanies().map(x=>x.id),['TEST-CO','OTHER-CO']);
}
''')

    def test_unavailable_authoritative_unit_never_selects_first_department(self):
        self.run_js('''
financeDirectoryState.currentApplicantDepartment=null;
renderUploadedSealDepartmentOptions();
assert.equal(select.value,'');assert.equal(select.disabled,false);
assert.equal(select.dataset.financeDirectoryEmpty,'false');
''')

    def test_other_company_unit_and_inactive_unit_are_not_adopted(self):
        self.run_js('''
financeDirectoryState.currentApplicantDepartment.companyId='OTHER-CO';
assert.equal(uploadedSealApplicantDepartment(departments,'TEST-CO'),null);
financeDirectoryState.currentApplicantDepartment.companyId='TEST-CO';
financeDirectoryState.currentApplicantDepartment.status='inactive';
assert.equal(uploadedSealApplicantDepartment(departments,'TEST-CO'),null);
''')

    def test_finance_rename_updates_new_form_without_touching_other_fields(self):
        self.run_js('''
renderUploadedSealDepartmentOptions();
financeDirectoryState.currentApplicantDepartment.name='測試新單位名稱';
renderUploadedSealDepartmentOptions();
assert.equal(select.value,'測試新單位名稱');
assert.equal(editorDraftPayload().applicant_department_id,'A1000');
assert.equal(fields['#uploadedSealReason'].value,'測試原因');
''')

    def test_submitted_document_preserves_historical_unit_read_only(self):
        self.run_js('''
uploadedSealEditorRuntime.documentId='OD-HISTORICAL';
uploadedSealEditorRuntime.locked=true;select.dataset.financeCompanyId='TEST-CO';
select.value='歷史單位名稱';renderUploadedSealDepartmentOptions();
assert.equal(select.value,'歷史單位名稱');assert.equal(select.disabled,true);
assert.equal(editorDraftPayload().applicant_department_id,'');
''')

    def test_submitted_department_label_is_not_rewritten_by_directory_rename(self):
        self.run_js('''
renderUploadedSealDepartmentOptions();uploadedSealEditorRuntime.documentId='OD-SUBMITTED';uploadedSealEditorRuntime.locked=true;
financeDirectoryState.currentApplicantDepartment.name='組織調整後名稱';
renderUploadedSealDepartmentOptions();assert.equal(select.value,'測試公司層級');assert.equal(select.disabled,true);
''')

    def test_explicit_department_choice_survives_refresh_and_saves_code(self):
        self.run_js('''
renderUploadedSealDepartmentOptions();select.value='非本人部門';
renderUploadedSealDepartmentOptions();
assert.equal(select.value,'非本人部門');assert.equal(select.disabled,false);
const patch=uploadedSealApplicationPatch();
assert.equal(patch.applicant_department_id,'D100');
assert.equal(patch.applicant_department_name,'非本人部門');
assert.equal(patch.dispatch_unit,'非本人部門');
''')

    def test_company_choices_default_own_then_preserve_explicit_choice(self):
        self.run_js('''
company.value='';renderUploadedSealCompanyOptions();
assert.equal(company.value,'TEST-CO');assert.equal(company.disabled,false);
company.value='OTHER-CO';renderUploadedSealCompanyOptions();
assert.equal(company.value,'OTHER-CO');assert.equal(select.value,'');
assert.deepEqual(select.options.map(x=>x.value),['','另一公司部門']);
select.value='另一公司部門';renderUploadedSealCompanyOptions();
assert.equal(select.value,'另一公司部門');
''')

    def test_removed_selected_unit_never_silently_defaults_to_another(self):
        self.run_js('''
renderUploadedSealDepartmentOptions();select.value='非本人部門';
financeDirectoryState.editorApplicantDepartments=financeDirectoryState.editorApplicantDepartments.filter(x=>x.code!=='D100');
renderUploadedSealDepartmentOptions();assert.equal(select.value,'');
assert.equal(editorDraftPayload().applicant_department_name,'');
''')

    def test_missing_own_company_does_not_default_to_other_company(self):
        self.run_js('''
financeDirectoryState.editorApplicantCompanies=financeDirectoryState.editorApplicantCompanies.filter(c=>c.id==='OTHER-CO');
company.value='';renderUploadedSealCompanyOptions();assert.equal(company.value,'');assert.equal(select.value,'');
''')

    def test_delayed_seal_response_cannot_cross_company_selection(self):
        self.run_js('''
let release;backendRequest=async(path)=>path.includes('TEST-CO')?await new Promise(resolve=>release=resolve):[{id:'NEW-COMPANY-SEAL'}];
const old=loadUploadedSealOptions('TEST-CO');company.value='OTHER-CO';
await loadUploadedSealOptions('OTHER-CO');release([{id:'OLD-COMPANY-SEAL'}]);await old;
assert.deepEqual(uploadedSealOptions.map(s=>s.id),['NEW-COMPANY-SEAL']);
''')

    def test_draft_department_stays_editable_but_submit_and_upload_lock_it(self):
        self.run_js('''
uploadedSealEditorRuntime.documentId='OD-DRAFT';renderUploadedSealCompanyOptions();
assert.equal(company.disabled,false);assert.equal(select.disabled,false);
uploadedSealEditorRuntime.uploading=true;renderUploadedSealCompanyOptions();
assert.equal(company.disabled,true);assert.equal(select.disabled,true);
uploadedSealEditorRuntime.uploading=false;uploadedSealEditorRuntime.locked=true;renderUploadedSealCompanyOptions();
assert.equal(company.disabled,true);assert.equal(select.disabled,true);
''')

    def test_company_change_creates_blank_scope_after_preserving_old_draft(self):
        self.run_js('''
renderUploadedSealCompanyOptions();uploadedSealEditorRuntime.documentId='OLD';
uploadedSealEditorState.pages=[{pageId:'old-page'}];
company.value='OTHER-CO';await handleUploadedSealCompanyChange({currentTarget:company});
assert.equal(calls[0].company,'TEST-CO');assert.equal(clears,1);
assert.equal(uploadedSealEditorRuntime.documentId,'');assert.equal(company.value,'OTHER-CO');
assert.equal(select.value,'');assert.equal(fields['#uploadedSealReason'].value,'測試原因');
assert.equal(uploadedSealEditorState.pages.length,0);assert.equal(uploadedSealEditorRuntime.companyChanging,false);
''')

    def test_cancel_or_failed_flush_preserves_original_company_and_pdf(self):
        self.run_js('''
renderUploadedSealCompanyOptions();uploadedSealEditorRuntime.documentId='OLD';
uploadedSealEditorState.pages=[{pageId:'old-page'}];
confirmResult=false;company.value='OTHER-CO';await handleUploadedSealCompanyChange({currentTarget:company});
assert.equal(company.value,'TEST-CO');assert.equal(clears,0);assert.equal(calls.length,0);
confirmResult=true;flushFailure=new Error('版本衝突');company.value='OTHER-CO';
await handleUploadedSealCompanyChange({currentTarget:company});
assert.equal(company.value,'TEST-CO');assert.equal(clears,0);assert.equal(uploadedSealEditorState.pages[0].pageId,'old-page');
assert.match(toasts[0],/版本衝突/);assert.equal(uploadedSealEditorRuntime.companyChanging,false);
''')

    def test_department_errors_explain_identity_instead_of_generic_denial(self):
        self.run_js('''
for(const code of ['finance_unit_required','finance_unit_projection_unavailable','finance_unit_payload_mismatch']){
 const message=friendlyBackendErrorMessage(code,403);
 assert.match(message,/單位|部門/);assert.doesNotMatch(message,/目前帳號沒有權限/);
}
''')

    def test_logout_clears_current_applicant_department(self):
        source = (ROOT / "app.js").read_text()
        self.assertIn('currentApplicantDepartment: undefined', javascript_function(source, 'clearFinanceDirectoryCache'))


if __name__ == '__main__':
    unittest.main()
