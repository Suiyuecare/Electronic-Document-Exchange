"""Applicant identity must not fall back to a different Finance department."""
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
        names = ["uploadedSealApplicantDepartment", "renderUploadedSealDepartmentOptions",
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
let departments = [{id:'OTHER',code:'D100',name:'非本人部門',status:'啟用'}];
const financeDepartmentsForCompany = () => departments;
const financeDirectoryCurrentCompany = () => ({id:'TEST-CO',name:'測試公司'});
const financeDirectoryCompanies = () => [{id:'TEST-CO'},{id:'OTHER-CO'}];
const parseJsonMaybe = s => s ? JSON.parse(s) : null;
const escapeDraftHtml = s => String(s);
const activeUnit = () => authState.user.unit;
const PDF_A4_INVALID_MESSAGE = 'A4';
let uploadedSealMode = 'official_document';
const PDF_EDITOR_SCHEMA_VERSION = 2, PDF_EDITOR_RENDERER_VERSION = 'test';
const approvalSelectionForSelect = () => ({documentCategory:'合作意向書',approvalRouteCode:'A'});
const uploadedSealEditorRuntime = {documentId:'',locked:false};
const select = {value:'',dataset:{},options:[],disabled:false,
  set innerHTML(html){
    this.options = [...html.matchAll(/<option value="([^"]*)"([^>]*)>(.*?)<\/option>/g)].map(m => ({value:m[1],textContent:m[3],dataset:{financeUnitCode:(m[2].match(/data-finance-unit-code="([^"]*)"/)||[])[1]||''}}));
    this.value = this.options[0]?.value || '';
  }, get selectedOptions(){return this.options.filter(x => x.value === this.value);}
};
const company = {value:'TEST-CO'};
const fields = {'#uploadedSealDepartment':select,'#uploadedSealCompany':company,
 '#uploadedSealApplicant':{value:'測試申請人'},'#uploadedSealTitle':{value:'測試'},'#uploadedSealReason':{value:'測試原因'}};
const document = {querySelector: selector => fields[selector] || null};
'''
        result = subprocess.run([shutil.which("node") or "node", "-e", harness + functions + "\n" + case], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_authenticated_roles_keep_their_own_division(self):
        self.run_js('''
for(const role of ['執行長','行政部主任','總務','主任','員工']){
 authState.user.role=role;select.value='非本人部門';
 renderUploadedSealDepartmentOptions();
 assert.equal(select.value,'測試公司層級');assert.equal(select.disabled,true);
 assert.equal(select.options.length,1);
 const payload=editorDraftPayload();
 assert.equal(payload.applicant_department_name,'測試公司層級');
 assert.equal(payload.applicant_department_id,'A1000');
 assert.equal(payload.dispatch_unit,'測試公司層級');
 assert.deepEqual(uploadedSealCompanies().map(x=>x.id),['TEST-CO']);
}
''')

    def test_unavailable_authoritative_unit_never_selects_first_department(self):
        self.run_js('''
financeDirectoryState.currentApplicantDepartment=null;
renderUploadedSealDepartmentOptions();
assert.equal(select.value,'');assert.equal(select.disabled,true);
assert.equal(select.dataset.financeDirectoryEmpty,'true');
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

    def test_existing_document_preserves_historical_unit_read_only(self):
        self.run_js('''
uploadedSealEditorRuntime.documentId='OD-HISTORICAL';
select.value='歷史單位名稱';renderUploadedSealDepartmentOptions();
assert.equal(select.value,'歷史單位名稱');assert.equal(select.disabled,true);
assert.equal(editorDraftPayload().applicant_department_id,'');
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
