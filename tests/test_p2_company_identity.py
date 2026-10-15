"""P2-02: authorized case identity is never replaced with a different company."""
import subprocess
import unittest
from pathlib import Path

from tests.test_workflow_history_frontend import runtime_function

ROOT = Path(__file__).resolve().parents[1]


class CaseCompanyIdentityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "app.js").read_text()

    def js(self, case, extra="", names=()):
        setup = r'''
const assert=require('node:assert/strict');
let scope='ACTOR-A:CO-A';const frontendSessionScope=()=>scope;
let financeDirectoryState={contentScope:scope,status:'synced'};
let companySealCompanies=[{id:'CO-A',name:'隔離甲公司'}, {id:'CO-B',name:'隔離乙公司'}, {id:'INST-C',name:'隔離長照股份有限公司附設新北市私立專案驗收居家長照機構'}];
const authState={user:{company_id:'CO-A',company_name:'錯誤帳號預設'}};
const companyRegistry=[{id:'UNRELATED',name:'錯誤第一家公司'}];
const parseJsonMaybe=value=>{try{return typeof value==='string'?JSON.parse(value):value}catch{return null}};
const escapeHtml=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const escapeDraftHtml=escapeHtml;
'''
        functions = "\n".join(runtime_function(self.source, name) for name in ("caseCompanyIdentity", "caseCompanyFieldLabel", "renderCaseCompanyField", *names))
        script = setup + extra + "\n" + functions + "\n" + case
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_exact_company_id_for_two_companies_and_long_institution(self):
        self.js(r'''
assert.equal(caseCompanyIdentity({company_id:'CO-A'}).name,'隔離甲公司');
assert.equal(caseCompanyIdentity({company_id:'CO-B'}).name,'隔離乙公司');
assert.equal(caseCompanyIdentity({company_id:'INST-C'}).name,companySealCompanies[2].name);
assert.equal(caseCompanyIdentity({company_id:'隔離乙公司'}).state,'missing');
assert.equal(caseCompanyIdentity({company_id:'CO-'}).state,'missing');
''')

    def test_missing_never_uses_auth_selected_company_first_registry_or_department(self):
        self.js(r'''
for(const item of [{},{company_id:'UNKNOWN'},{applicant_department_name:'只有部門'},{company_id:'CO-A-NOT'}]) {
 const identity=caseCompanyIdentity(item); assert.equal(identity.state,'missing');
 assert.equal(identity.label,'單位資料未提供');assert.equal(identity.name,'');
 assert.doesNotMatch(renderCaseCompanyField(item),/歲悅長照股份有限公司|錯誤|只有部門/);
}
''')

    def test_snapshot_preserves_historical_name_and_never_changes_case(self):
        self.js(r'''
const item={company_id:'CO-A',company_name:'原核准法人名稱',metadata:{company_name:'另一個欄位'}};
const before=JSON.stringify(item);assert.equal(caseCompanyIdentity(item).name,'原核准法人名稱');
assert.equal(caseCompanyIdentity(item).source,'snapshot');assert.equal(JSON.stringify(item),before);
assert.equal(caseCompanyIdentity({companyId:'LEGACY',companyName:'歷史機構名稱'}).name,'歷史機構名稱');
''')

    def test_only_case_bound_metadata_names_are_used(self):
        self.js(r'''
assert.equal(caseCompanyIdentity({company_id:'CO-A',metadata:{company_name:'案卷原單位'}}).name,'案卷原單位');
assert.equal(caseCompanyIdentity({company_id:'CO-A',metadata_json:JSON.stringify({extra:{company_id:'CO-A',company_name:'案卷同 ID'}})}).name,'案卷同 ID');
assert.equal(caseCompanyIdentity({company_id:'CO-B',metadata:{company_id:'CO-A',company_name:'異案名稱'}}).name,'隔離乙公司');
assert.equal(caseCompanyIdentity({company_id:'CO-B',metadata:{extra:{company_id:'CO-A',company_name:'異案名稱'}}}).name,'隔離乙公司');
assert.equal(caseCompanyIdentity({company_id:'CO-A',metadata_json:'invalid'}).name,'隔離甲公司');
''')

    def test_loading_error_and_missing_are_honest_and_session_scoped(self):
        self.js(r'''
financeDirectoryState.status='syncing';assert.equal(caseCompanyIdentity({company_id:'NEW'}).state,'loading');
assert.equal(caseCompanyIdentity({company_id:'CO-A'}).name,'隔離甲公司');
financeDirectoryState.status='error';assert.equal(caseCompanyIdentity({company_id:'NEW'}).state,'unavailable');
assert.equal(caseCompanyIdentity({company_id:'CO-B'}).name,'隔離乙公司');
scope='ACTOR-B:CO-B';assert.equal(caseCompanyIdentity({company_id:'CO-A'}).name,'');
financeDirectoryState.status='syncing';assert.equal(caseCompanyIdentity({company_id:'CO-A'}).state,'loading');
financeDirectoryState={status:'synced',contentScope:scope};companySealCompanies=[{id:'CO-B',name:'新帳號乙公司'}];
assert.equal(caseCompanyIdentity({company_id:'CO-A'}).name,'');assert.equal(caseCompanyIdentity({company_id:'CO-B'}).name,'新帳號乙公司');
''')

    def test_labels_separate_case_company_from_applicant_department_and_escape_names(self):
        self.js(r'''
assert.equal(caseCompanyFieldLabel({source_type:'uploaded_pdf'}),'用印單位');
assert.equal(caseCompanyFieldLabel({source_type:'blank_editor'}),'發文單位');
assert.equal(caseCompanyFieldLabel({}),'公司／機構');
const html=renderCaseCompanyField({company_id:'A',company_name:'隔離 <img src=x> "單位"',source_type:'uploaded_pdf'});
assert.match(html,/<dt>用印單位<\/dt>/);assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<img/);
assert.doesNotMatch(html,/data-case-company-directory/);
assert.match(renderCaseCompanyField({company_id:'CO-A'}),/data-case-company-directory="CO-A"/);
''')

    def test_directory_refresh_updates_display_only_and_retains_snapshot_fields(self):
        self.js(r'''
refreshCaseCompanyDisplays();assert.equal(nodes[0].textContent,'隔離甲公司');assert.equal(nodes[1].textContent,'單位資料未提供');
scope='NEW-ACTOR';refreshCaseCompanyDisplays();assert.equal(nodes[0].textContent,'單位資料未提供');
''', extra=r'''
const nodes=[{dataset:{caseCompanyDirectory:'CO-A'},textContent:'載入中'},{dataset:{caseCompanyDirectory:'MISSING'},textContent:'載入中'}];
const document={querySelectorAll:selector=>{assert.equal(selector,'[data-case-company-directory]');return nodes}};
''', names=("refreshCaseCompanyDisplays",))

    def test_all_touched_readonly_surfaces_use_the_same_resolver(self):
        for name in ("renderApprovalLog", "renderOfficialDecisionEvidence", "renderOfficialWorkflowDetail"):
            function = runtime_function(self.source, name)
            self.assertIn("renderCaseCompanyField(", function, name)
            self.assertNotIn('doc?.companyName || "歲悅長照股份有限公司"', function)
        for name in ("applyPersistentDocuments", "applyPersistentContracts"):
            self.assertNotIn('row.company_name || "歲悅長照股份有限公司"', runtime_function(self.source, name))


if __name__ == "__main__":
    unittest.main()
