"""Applicant pre-confirmation checks; executable JS, synthetic data only."""
import json
from pathlib import Path
import subprocess
import unittest
from tests.test_compose_output_contract import function

ROOT = Path(__file__).resolve().parents[1]


class ComposePreflightSealsTest(unittest.TestCase):
    def evaluate(self, names, setup, body):
        source = (ROOT / "app.js").read_text()
        code = "\n".join(function(source, name) for name in names)
        result = subprocess.run(["node", "-e", code + "\n" + setup + "\n(async()=>{" + body + "})().catch(e=>{console.error(e);process.exit(1)});"], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_electronic_empty_inactive_wrong_company_and_loading(self):
        result = self.evaluate([
            "composeSealSubmissionReadiness", "composeSealTypeLabel",
            "composeSealOptionsForSelectedCompany", "companySealSelectable", "officialSealHasCurrentFile"
        ], r'''
let mode='physical',loading=false,composeSealOptionsError=false;
let composeSealOptionsCompanyId='A',composeSealCatalogState={scope:'scope',token:'token',status:'ready'};
const authState={token:'token'},frontendSessionScope=()=> 'scope';
const nodes={'#composeCompanySelect':{value:'A'},'#largeSealType':{value:'無'},'#smallSealType':{value:'無'},'#continuousSealType':{value:'無'}};
const document={querySelector:s=>nodes[s]};
const composeOutputMode=()=>mode,composeSealOptionsAreLoadingForSelectedCompany=()=>loading;
const composeCompanyForOfficialApplication=name=>({id:name});
const ready={id:'synthetic',company_id:'A',owner_kind:'company',seal_category:'general_seal',seal_size_type:'large_seal',is_active:true,selectable:true,current_file:{id:'file',usable:true,is_current:true}};
let composeSealOptions=[];
''', r'''
const out={empty:composeSealSubmissionReadiness()};
mode='electronic';out.electronic=composeSealSubmissionReadiness();mode='physical';
composeSealOptions=[ready];out.unselected=composeSealSubmissionReadiness();
nodes['#largeSealType'].value='一般章';out.ready=composeSealSubmissionReadiness();
composeSealOptions=[{...ready,is_active:false}];out.inactive=composeSealSubmissionReadiness();
composeSealOptions=[ready];nodes['#composeCompanySelect'].value='B';out.foreign=composeSealSubmissionReadiness();
nodes['#composeCompanySelect'].value='A';loading=true;out.loading=composeSealSubmissionReadiness();loading=false;
composeSealOptionsError=true;out.error=composeSealSubmissionReadiness();composeSealCatalogState.status='forbidden';out.denied=composeSealSubmissionReadiness();
console.log(JSON.stringify(out));
''')
        self.assertTrue(result["electronic"]["valid"])
        self.assertTrue(result["ready"]["valid"])
        for key in ("empty", "unselected", "inactive", "foreign", "loading", "error", "denied"):
            self.assertFalse(result[key]["valid"], key)
            self.assertIn("草稿", result[key]["message"])

    def test_contact_fields_are_always_visible_without_toggle(self):
        result = self.evaluate(["renderComposeContactSummary"], r'''
const labels=[{hidden:true},{hidden:false},{hidden:true}],fields={hidden:true,querySelectorAll:()=>labels},summary={};
const document={querySelector:s=>({'#composeContactFields':fields,'#composeContactSummaryText':summary}[s])};
''', "renderComposeContactSummary();console.log(JSON.stringify({hidden:fields.hidden,labels:labels.map(l=>l.hidden),summary:summary.textContent}));")
        self.assertFalse(result["hidden"])
        self.assertEqual(result["labels"], [False, False, False])
        self.assertNotIn('id="composeContactToggleBtn"', (ROOT / "index.html").read_text())

    def test_submission_rejection_and_transport_loss_are_distinct(self):
        result = self.evaluate(["createOfficialApplicationFromCompose"], r'''
const composeRequestScope=()=> 'fixture',composeCompanyForOfficialApplication=()=>({id:'A'});
let composeOfficialContentRevision=null;
const ensureComposeDraftRequestId=()=> 'OD-FIXTURE',activeUnit=()=> 'synthetic-unit',officialComposeMetadata=()=>({});
const document={querySelector:s=>s==='#dispatchNo'?{value:''}:{files:[]}};
const data={outputMode:'electronic',companyName:'A',approvalFlowNodes:[],sealPlacements:{},attachments:[]};
let status=400,code='';const paths=[];
const backendRequest=async(path,options)=>{paths.push(path);if(path.endsWith('/submit')){const error=new Error('synthetic failure');error.status=status;error.code=code;throw error;}return {id:'OD-FIXTURE',dispatch_no:'TEST-1',content_revision:1}};
''', r'''
const out=[];for(const code of [400,403,409,422,500,0]){status=code;try{await createOfficialApplicationFromCompose({},data)}catch(e){out.push({status:code,outcome:e.composeSubmissionOutcome})}}
status=500;code='official_submission_validation_failed';try{await createOfficialApplicationFromCompose({},data)}catch(e){out.push({status,outcome:e.composeSubmissionOutcome})}
console.log(JSON.stringify(out));
''')
        self.assertEqual([row["outcome"] for row in result], ["not_submitted"] * 4 + ["unknown"] * 2 + ["not_submitted"])

    def test_missing_stamp_does_not_block_explicit_draft_save(self):
        result = self.evaluate(["createOfficialApplicationFromCompose"], r'''
const composeRequestScope=()=> 'fixture',composeCompanyForOfficialApplication=()=>({id:'A'});
let composeOfficialContentRevision=null;
const ensureComposeDraftRequestId=()=> 'OD-FIXTURE',activeUnit=()=> 'synthetic-unit',officialComposeMetadata=()=>({});
const document={querySelector:s=>s==='#dispatchNo'?{value:''}:{files:[]}};
const data={outputMode:'physical',companyName:'A',approvalFlowNodes:[],sealPlacements:{},attachments:[],largeSealType:'無',smallSealType:'無',continuousSealType:'無'};
const paths=[];const backendRequest=async(path,options)=>{paths.push(path);return {id:'OD-FIXTURE',dispatch_no:'TEST-1',content_revision:1}};
''', r'''
await createOfficialApplicationFromCompose({},data,{submit:false});
let error='';try{await createOfficialApplicationFromCompose({},data)}catch(e){error=e.message}
console.log(JSON.stringify({paths,error}));
''')
        self.assertEqual(result["paths"], ["/official-documents"])
        self.assertIn("請選擇", result["error"])


if __name__ == "__main__":
    unittest.main()
