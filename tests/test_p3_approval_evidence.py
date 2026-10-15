"""P3-01: truthful evidence feedback without relaxing manual review gates."""
from pathlib import Path
import subprocess
import unittest

from tests.test_workflow_history_frontend import runtime_function

ROOT = Path(__file__).resolve().parents[1]


class ApprovalEvidenceFeedbackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "app.js").read_text()

    SETUP = r'''
const assert = require('node:assert/strict');
let scope = 'ACTOR-A', downloadResults = [], downloadCalls = [], buttons = {};
const fields = {};
const officialDecisionState = {documentId:'CASE-A', operationId:'OPEN-A', action:'approve'};
const officialDocumentDetailReady = new Set(['CASE-A']);
const frontendSessionScope = () => scope;
const officialApplicationFiles = item => item.files || [];
const escapeHtml = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;');
const renderCaseCompanyField = () => '<div><dt>用印單位</dt><dd>隔離測試公司</dd></div>';
const isValidFutureOrToday = () => true;
const downloadOfficialWorkflowFile = async (id, fileId) => {
  downloadCalls.push([id, fileId]);
  const result = downloadResults.length ? downloadResults.shift() : true;
  return typeof result === 'function' ? await result() : result;
};
const evidence = {dataset:{}, details:null, querySelector(){return this.details}, append(node){this.details=node}};
const actions = {
  set innerHTML(html) {
    for (const button of Object.values(buttons)) button.isConnected = false;
    buttons = {};
    for (const match of html.matchAll(/<button\b([^>]*)>([^<]*)<\/button>/g)) {
      const attrs = match[1];
      const attr = name => attrs.match(new RegExp(name+'="([^"]*)"'))?.[1] || '';
      const kind = attr('data-decision-evidence');
      const classes = new Set();
      buttons[kind] = {
        dataset:{decisionEvidence:kind, defaultLabel:attr('data-default-label'), completionLabel:attr('data-completion-label')},
        disabled:/\sdisabled(?:\s|$)/.test(attrs), textContent:match[2], title:'', isConnected:true,
        classList:{add:name=>classes.add(name), contains:name=>classes.has(name)},
        addEventListener(type, handler){this.handler=handler},
      };
    }
  },
  querySelectorAll(){return Object.values(buttons)}
};
fields['#officialDecisionEvidence'] = evidence;
fields['#officialDecisionEvidenceActions'] = actions;
fields['#officialDecisionError'] = {hidden:true, textContent:'', dataset:{}};
fields['#officialDecisionSubmitBtn'] = {disabled:true};
fields['#officialDecisionRequirements'] = {textContent:''};
fields['#officialApprovalComment'] = {value:'隔離測試意見保留'};
const selectors = {source:'#officialReviewOriginal', attachments:'#officialReviewAttachments', editor:'#officialReviewEdited'};
for (const selector of Object.values(selectors)) fields[selector] = {disabled:true, checked:false};
const document = {
  querySelector(selector) {
    const kind = selector.match(/^\[data-decision-evidence="([^"]+)"\]$/)?.[1];
    return kind ? buttons[kind] : fields[selector] || null;
  },
  createElement(){return {hidden:false,remove(){evidence.details=null}}}
};
const file = (id, type) => ({id,file_type:type});
const sourceFile = file('SOURCE','original_pdf');
const render = (files, extra={}) => renderOfficialDecisionEvidence({id:'CASE-A',files,...extra});
const click = async kind => {if(!buttons[kind].disabled) await buttons[kind].handler()};
const assertUnacknowledged = kind => {
  assert.equal(fields[selectors[kind]].checked, false);
  assert.equal(fields['#officialDecisionSubmitBtn'].disabled, true);
};
'''

    def run_case(self, code):
        names = (
            "officialDecisionEvidenceFiles", "officialDecisionEvidenceReady",
            "officialDecisionEvidenceComplete", "officialDecisionPendingRequirements",
            "updateOfficialDecisionSubmitAvailability", "markOfficialDecisionEvidenceReviewed",
            "renderOfficialDecisionEvidence",
        )
        source = self.SETUP + "\n" + "\n".join(runtime_function(self.source, name) for name in names)
        source += "\n(async()=>{" + code + "})().catch(e=>{console.error(e);process.exitCode=1});"
        result = subprocess.run(["node", "-e", source], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_empty_actions_require_explicit_confirmation_without_download(self):
        self.run_case(r'''
render([sourceFile]);
assert.equal(buttons.attachments.textContent,'確認沒有附件');
assert.equal(buttons.editor.textContent,'確認無編輯內容');
for(const kind of ['attachments','editor']) {
  assert.equal(fields[selectors[kind]].disabled,true);
  await click(kind);
  const expected = kind==='attachments' ? '已確認無附件' : '已確認無編輯內容';
  assert.equal(buttons[kind].textContent,expected);
  assert.match(buttons[kind].title,new RegExp(expected));
  assert.doesNotMatch(buttons[kind].textContent+buttons[kind].title,/已下載/);
  assert.equal(fields[selectors[kind]].disabled,false);
  assertUnacknowledged(kind);
}
assert.deepEqual(downloadCalls,[]);
''')

    def test_all_actual_file_downloads_report_success_but_never_auto_acknowledge(self):
        self.run_case(r'''
render([sourceFile,file('A1','attachment'),file('A2','attachment'),file('P','prepared_pdf')]);
for(const kind of ['source','attachments','editor']) {
  await click(kind);
  assert.match(buttons[kind].textContent,/^已下載｜下載/);
  assert.match(buttons[kind].title,/^已下載；請另行勾選/);
  assert.equal(fields[selectors[kind]].disabled,false);
  assertUnacknowledged(kind);
}
assert.deepEqual(downloadCalls.map(call=>call[1]),['SOURCE','A1','A2','P']);
''')

    def test_each_failed_download_remains_retryable_and_preserves_comment(self):
        self.run_case(r'''
for(const kind of ['source','attachments','editor']) {
  render([sourceFile,file('A','attachment'),file('P','prepared_pdf')]);
  fields[selectors[kind]].disabled=true;
  const label=buttons[kind].textContent;
  downloadResults=[false];await click(kind);
  assert.equal(buttons[kind].textContent,label);
  assert.equal(buttons[kind].disabled,false);
  assert.equal(buttons[kind].classList.contains('complete'),false);
  assert.equal(fields[selectors[kind]].disabled,true);
  assert.equal(fields['#officialDecisionError'].hidden,false);
  assert.match(fields['#officialDecisionError'].textContent,/未完整下載/);
  assert.equal(fields['#officialApprovalComment'].value,'隔離測試意見保留');
  assertUnacknowledged(kind);
}
''')

    def test_partial_attachment_failure_is_not_reported_as_complete(self):
        self.run_case(r'''
render([sourceFile,file('A1','attachment'),file('A2','attachment')]);
downloadResults=[true,false];await click('attachments');
assert.equal(buttons.attachments.textContent,'下載全部附件（2）');
assert.equal(buttons.attachments.disabled,false);
assert.equal(fields[selectors.attachments].disabled,true);
assertUnacknowledged('attachments');
assert.deepEqual(downloadCalls.map(call=>call[1]),['A1','A2']);
''')

    def test_successful_retry_clears_only_its_error_and_waits_for_manual_ack(self):
        self.run_case(r'''
render([sourceFile,file('A1','attachment'),file('A2','attachment')]);
downloadResults=[false,true,true,true];await click('attachments');await click('attachments');
assert.equal(buttons.attachments.textContent,'已下載｜下載全部附件（2）');
assert.equal(fields['#officialDecisionError'].hidden,true);
assert.equal(fields['#officialDecisionError'].textContent,'');
assert.equal(fields['#officialDecisionError'].dataset.evidenceFailure,undefined);
assert.equal(fields['#officialApprovalComment'].value,'隔離測試意見保留');
assertUnacknowledged('attachments');
''')

    def test_other_success_cannot_hide_an_outstanding_download_failure(self):
        self.run_case(r'''
render([sourceFile]);downloadResults=[false];await click('source');await click('attachments');
assert.equal(fields['#officialDecisionError'].hidden,false);
assert.equal(fields['#officialDecisionError'].dataset.evidenceFailure,'source');
assert.equal(buttons.attachments.textContent,'已確認無附件');
assert.equal(fields[selectors.source].disabled,true);
''')

    def test_missing_locked_prepared_file_never_becomes_no_edit_confirmation(self):
        self.run_case(r'''
render([sourceFile,file('OLD','prepared_pdf')],{stamp_request:{prepared_file_id:'LOCKED',locked_editor_revision_id:'REV'}});
assert.equal(buttons.editor.disabled,true);
assert.match(buttons.editor.textContent,/鎖定確認版無法讀取/);
assert.equal(buttons.editor.dataset.completionLabel,'');
await click('editor');assert.deepEqual(downloadCalls,[]);
assert.equal(fields[selectors.editor].disabled,true);
assertUnacknowledged('editor');
''')

    def test_exact_locked_prepared_file_is_the_one_downloaded(self):
        self.run_case(r'''
render([sourceFile,file('NEWER','prepared_pdf'),file('LOCKED','prepared_pdf')],{stamp_request:{prepared_file_id:'LOCKED'}});
await click('editor');assert.deepEqual(downloadCalls,[['CASE-A','LOCKED']]);
assert.match(buttons.editor.textContent,/^已下載｜/);assertUnacknowledged('editor');
''')

    def test_missing_source_cannot_be_marked_as_downloaded(self):
        self.run_case(r'''
render([]);assert.equal(buttons.source.disabled,true);await click('source');
assert.equal(buttons.source.textContent,'找不到原稿或送簽版');
assert.deepEqual(downloadCalls,[]);assert.equal(fields[selectors.source].disabled,true);
''')

    def test_late_results_do_not_mark_another_account_case_or_dialog_complete(self):
        self.run_case(r'''
for(const change of [()=>scope='ACTOR-B',()=>officialDecisionState.documentId='CASE-B',()=>officialDecisionState.operationId='OPEN-B']) {
  scope='ACTOR-A';officialDecisionState.documentId='CASE-A';officialDecisionState.operationId='OPEN-A';
  render([sourceFile]);const previous=buttons.source;
  downloadResults=[()=>{change();return true}];await click('source');
  assert.doesNotMatch(previous.textContent,/已下載/);
  assert.equal(fields[selectors.source].disabled,true);
  assertUnacknowledged('source');
}
''')

    def test_render_replaces_old_completion_labels_and_application_status(self):
        self.run_case(r'''
render([sourceFile]);await click('application');await click('attachments');await click('editor');
assert.match(buttons.application.textContent,/^已展開｜/);
assert.equal(evidence.dataset.applicationReviewed,'true');
render([sourceFile,file('A','attachment'),file('P','prepared_pdf')]);
assert.equal(evidence.dataset.applicationReviewed,'false');
assert.equal(buttons.application.textContent,'展開申請資料');
assert.equal(buttons.attachments.textContent,'下載全部附件（1）');
assert.equal(buttons.editor.textContent,'下載編輯 PDF');
assert.equal(buttons.attachments.title,'');assert.equal(buttons.editor.title,'');
''')

    def test_submission_gate_still_requires_all_three_manual_acknowledgements(self):
        self.run_case(r'''
render([sourceFile]);
for(const kind of ['application','source','attachments','editor'])await click(kind);
assert.equal(fields['#officialDecisionSubmitBtn'].disabled,true);
for(const kind of ['source','attachments','editor']) {
  assert.equal(fields[selectors[kind]].checked,false);
  fields[selectors[kind]].checked=true;
  updateOfficialDecisionSubmitAvailability();
  assert.equal(fields['#officialDecisionSubmitBtn'].disabled,kind!=='editor');
}
fields[selectors.attachments].checked=false;updateOfficialDecisionSubmitAvailability();
assert.equal(fields['#officialDecisionSubmitBtn'].disabled,true);
''')


if __name__ == "__main__":
    unittest.main()
