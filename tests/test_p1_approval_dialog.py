"""AP-01/AP-02: retain authoritative membership and explain unchanged review gates."""
import subprocess
import unittest
from pathlib import Path

from tests.test_workflow_history_frontend import runtime_function

ROOT = Path(__file__).resolve().parents[1]


class ApprovalDialogRepairTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "app.js").read_text()

    def js(self, names, setup, case):
        functions = "\n".join(runtime_function(self.source, name) for name in names)
        code = "const assert=require('node:assert/strict');\n" + setup + "\n" + functions
        code += "\n(async()=>{" + case + "})().catch(e=>{console.error(e);process.exitCode=1});"
        result = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    SETUP = r'''
const fields={};const document={querySelector:s=>fields[s]||null};
const officialDecisionState={documentId:'CASE',action:'approve',candidates:[]};
const officialDocumentDetailReady=new Set(['CASE']);
const isValidFutureOrToday=v=>v==='2026-10-16';
fields['#officialDecisionEvidence']={dataset:{applicationReviewed:'false'}};
for(const s of ['#officialReviewOriginal','#officialReviewAttachments','#officialReviewEdited'])fields[s]={checked:false,disabled:true};
for(const s of ['#officialApprovalComment','#officialWithdrawComment','#officialRejectCategory','#officialRejectComment','#officialCorrectionDueDate','#officialAddSignPerson'])fields[s]={value:''};
fields['#officialDecisionSubmitBtn']={disabled:true};
fields['#officialDecisionRequirements']={textContent:'',hidden:false};
'''

    def test_pending_requirements_explain_download_manual_ack_and_comment(self):
        self.js(["officialDecisionEvidenceReady", "officialDecisionPendingRequirements"], self.SETUP, r'''
let pending=officialDecisionPendingRequirements();
assert.match(pending.join(' '),/展開申請資料/);assert.match(pending.join(' '),/下載原稿/);assert.match(pending.join(' '),/至少 2 個字/);
fields['#officialDecisionEvidence'].dataset.applicationReviewed='true';
for(const s of ['#officialReviewOriginal','#officialReviewAttachments','#officialReviewEdited'])fields[s].disabled=false;
pending=officialDecisionPendingRequirements();assert.match(pending.join(' '),/勾選原稿/);
for(const s of ['#officialReviewOriginal','#officialReviewAttachments','#officialReviewEdited'])fields[s].checked=true;
fields['#officialApprovalComment'].value='已核對';assert.deepEqual(officialDecisionPendingRequirements(),[]);
''')

    def test_disabled_gate_stays_closed_until_all_existing_requirements(self):
        self.js(["officialDecisionEvidenceReady", "officialDecisionEvidenceComplete", "officialDecisionPendingRequirements", "updateOfficialDecisionSubmitAvailability"], self.SETUP, r'''
updateOfficialDecisionSubmitAvailability();assert.equal(fields['#officialDecisionSubmitBtn'].disabled,true);
assert.match(fields['#officialDecisionRequirements'].textContent,/尚待完成/);
fields['#officialDecisionEvidence'].dataset.applicationReviewed='true';
fields['#officialApprovalComment'].value='已核對';
for(const s of ['#officialReviewOriginal','#officialReviewAttachments','#officialReviewEdited']){fields[s].disabled=false;fields[s].checked=true;}
updateOfficialDecisionSubmitAvailability();assert.equal(fields['#officialDecisionSubmitBtn'].disabled,false);
officialDecisionState.busy=true;updateOfficialDecisionSubmitAvailability();assert.equal(fields['#officialDecisionSubmitBtn'].disabled,true);
assert.match(fields['#officialDecisionRequirements'].textContent,/送出中/);
''')

    def test_action_specific_reason_date_and_candidate_requirements(self):
        self.js(["officialDecisionEvidenceReady", "officialDecisionPendingRequirements"], self.SETUP, r'''
fields['#officialDecisionEvidence'].dataset.applicationReviewed='true';
for(const s of ['#officialReviewOriginal','#officialReviewAttachments','#officialReviewEdited']){fields[s].disabled=false;fields[s].checked=true;}
officialDecisionState.action='decline';fields['#officialApprovalComment'].value='理由';assert.match(officialDecisionPendingRequirements().join(' '),/至少 6 個字/);
officialDecisionState.action='withdraw';assert.equal(officialDecisionPendingRequirements().length,1);assert.match(officialDecisionPendingRequirements()[0],/抽單原因/);
fields['#officialWithdrawComment'].value='隔離測試撤回原因';assert.deepEqual(officialDecisionPendingRequirements(),[]);
officialDecisionState.action='reject';fields['#officialRejectComment'].value='隔離測試補正原因';fields['#officialRejectCategory'].value='other';fields['#officialCorrectionDueDate'].value='2026-10-01';assert.match(officialDecisionPendingRequirements().join(' '),/補正期限/);
officialDecisionState.action='add-sign';fields['#officialApprovalComment'].value='已核對';fields['#officialAddSignPerson'].value='FORGED';assert.match(officialDecisionPendingRequirements().join(' '),/加簽人員/);
officialDecisionState.candidates=[{id:'VALID'}];fields['#officialAddSignPerson'].value='VALID';assert.deepEqual(officialDecisionPendingRequirements(),[]);
''')

    def test_no_file_confirmation_never_claims_download_or_checks_ack(self):
        self.js(["markOfficialDecisionEvidenceReviewed"], self.SETUP + r'''
function updateOfficialDecisionSubmitAvailability(){}
const button={dataset:{defaultLabel:'本案沒有附件',completionLabel:'已確認無附件'},classList:{add(){}},textContent:''};
fields['[data-decision-evidence="attachments"]']=button;
''', r'''
markOfficialDecisionEvidenceReviewed('attachments');assert.equal(button.textContent,'已確認無附件');assert.doesNotMatch(button.textContent,/已下載/);
assert.equal(fields['#officialReviewAttachments'].checked,false);assert.equal(fields['#officialReviewAttachments'].disabled,false);
''')

    def test_detail_hydration_retains_server_membership_and_does_not_infer_assignment(self):
        self.js(["officialDocumentAvailableActions", "ensureOfficialDocumentDetail"], r'''
const frontendSessionScope=()=> 'session-A';const officialDocumentDetailReady=new Set();const officialDocumentDetailRequests=new Map();
let officialWorkflowItems=[{id:'CASE',approval_views:{acted:true}}];
let response={id:'CASE',approval_views:{acted:true},approval_steps:[]};const backendRequest=async()=>response;
''', r'''
await ensureOfficialDocumentDetail('CASE');assert.equal(officialWorkflowItems[0].approval_views.acted,true);
officialDocumentDetailReady.clear();response={id:'CASE',approval_views:{acted:false},approval_steps:[{approver_user_id:'session-A'}]};
await ensureOfficialDocumentDetail('CASE');assert.equal(officialWorkflowItems[0].approval_views.acted,false);
''')

    def test_modal_has_persistent_accessible_requirement_summary(self):
        html = (ROOT / "index.html").read_text()
        self.assertTrue('id="officialDecisionRequirements"' in html)
        self.assertTrue('aria-describedby="officialDecisionRequirements officialDecisionError"' in html)

    def test_each_manual_checkbox_recomputes_gate_without_retyping_comment(self):
        start = self.source.index('["#officialApprovalComment", "#officialRejectCategory"')
        binding = self.source[start:self.source.index('});', start)]
        for selector in ('#officialReviewOriginal', '#officialReviewAttachments', '#officialReviewEdited'):
            self.assertIn(selector, binding)
        self.assertIn('addEventListener("change", updateOfficialDecisionSubmitAvailability)', binding)


if __name__ == "__main__":
    unittest.main()
