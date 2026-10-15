"""Readonly display is distinct from workflow authority and temporary preview."""
import subprocess
import unittest
from pathlib import Path
from tests.test_workflow_history_frontend import runtime_function

ROOT = Path(__file__).resolve().parents[1]


class ReadOnlyEditorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'app.js').read_text()

    def js(self, assertion, extra='', names=()):
        labels = self.source.split('const officialStatusLabels = ', 1)[1].split('\nconst officialFileTypeLabels', 1)[0]
        script = "const assert=require('node:assert/strict');const officialStatusLabels = " + labels
        script += '''
const uploadedSealEditorRuntime={documentId:'OD-1',revisionId:'REV-1',locked:false,reviewMode:'edited',preparedFileId:'FILE-1',preparedSha256:'a'.repeat(64),applicationSnapshot:{id:'OD-1',status:'draft'}};
const uploadedSealEditorState={revisionNo:3,pages:[{pageId:'p1'}],elements:[]};
const uploadedSealApplicationRuntime={editable:true};
''' + extra
        script += '\n' + runtime_function(self.source, 'uploadedEditorReadOnlyPresentation')
        script += '\n' + '\n'.join(runtime_function(self.source, name) for name in names)
        script += '\n(async()=>{' + assertion + '})().catch(e=>{console.error(e);process.exitCode=1});'
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_draft_and_correction_keep_existing_editability(self):
        self.js('''for (const status of ['draft','rejected']) { uploadedSealEditorRuntime.applicationSnapshot.status=status; const p=uploadedEditorReadOnlyPresentation(); assert.equal(p.readonly,false);assert.equal(p.caseReadOnly,false); }''')

    def test_pending_approved_closed_have_exact_readonly_status(self):
        self.js('''uploadedSealEditorRuntime.locked=true;for(const [status,label] of [['pending_department_head','待部門主任簽核'],['approved','已核准'],['closed','已結案歸檔'],['declined','不通過（已終止）']]){uploadedSealEditorRuntime.applicationSnapshot.status=status;const p=uploadedEditorReadOnlyPresentation();assert.equal(p.readonly,true);assert.equal(p.status,label+'・唯讀');assert.equal(p.versionLabel,'版本 3');assert.equal(p.downloadable,true);}''')

    def test_other_applicant_draft_is_not_called_submitted(self):
        self.js('''uploadedSealEditorRuntime.locked=true;const p=uploadedEditorReadOnlyPresentation();assert.equal(p.status,'草稿・唯讀');assert.doesNotMatch(p.status,/送簽|送出/);''')

    def test_loading_failure_and_unknown_never_invent_submission(self):
        self.js('''uploadedSealEditorRuntime.locked=true;uploadedSealEditorRuntime.hydrating=true;assert.equal(uploadedEditorReadOnlyPresentation().status,'正在載入文件・暫時唯讀');assert.equal(uploadedEditorReadOnlyPresentation().downloadable,false);uploadedSealEditorRuntime.hydrating=false;uploadedSealEditorRuntime.hydrationError='請重試';assert.equal(uploadedEditorReadOnlyPresentation().status,'文件載入失敗・唯讀');assert.equal(uploadedEditorReadOnlyPresentation().downloadable,false);uploadedSealEditorRuntime.hydrationError='';uploadedSealEditorRuntime.applicationSnapshot={id:'OD-other',status:'approved'};uploadedSealEditorRuntime.revisionId='';const p=uploadedEditorReadOnlyPresentation();assert.equal(p.status,'文件檢閱・唯讀');assert.equal(p.versionLabel,'版本資料未提供');''')

    def test_temporary_preview_is_readonly_but_returns_to_edit(self):
        self.js('''for(const mode of ['original','prepared','changes']){uploadedSealEditorRuntime.reviewMode=mode;const p=uploadedEditorReadOnlyPresentation();assert.equal(p.readonly,true);assert.equal(p.reviewingDraft,true);assert.equal(p.caseReadOnly,false);assert.match(p.status,/草稿預覽/);}uploadedSealEditorRuntime.reviewMode='edited';assert.equal(uploadedEditorReadOnlyPresentation().readonly,false);''')

    def test_denied_runtime_editability_fails_closed_without_confusing_metadata(self):
        self.js('''uploadedSealApplicationRuntime.metadataEditable=false;uploadedSealApplicationRuntime.companyEditable=false;assert.equal(uploadedEditorReadOnlyPresentation().readonly,false);uploadedSealApplicationRuntime.editable=false;assert.equal(uploadedEditorReadOnlyPresentation().caseReadOnly,true);''')

    def test_existing_locked_and_preview_mutation_guards_do_zero_work(self):
        self.js('''for(const mode of ['edited','original','prepared','changes']){uploadedSealEditorRuntime.locked=true;uploadedSealEditorRuntime.reviewMode=mode;commitUploadedEditorMutation(()=>writes++);}uploadedSealEditorRuntime.locked=false;for(const mode of ['original','prepared','changes']){uploadedSealEditorRuntime.reviewMode=mode;commitUploadedEditorMutation(()=>writes++);}assert.equal(writes,0);assert.deepEqual(uploadedSealEditorState.elements,[]);assert.equal(uploadedSealEditorState.revisionNo,3);''', 'let writes=0;const showToast=()=>{};', ['commitUploadedEditorMutation'])

    def test_readonly_download_uses_authorized_endpoint_once(self):
        self.js('''assert.equal(await downloadUploadedEditorReadOnlyPrepared(),false);uploadedSealEditorRuntime.locked=true;const pending=downloadUploadedEditorReadOnlyPrepared();assert.equal(await downloadUploadedEditorReadOnlyPrepared(),false);release(true);assert.equal(await pending,true);assert.deepEqual(downloads,[['OD-1','FILE-1']]);assert.equal(button.disabled,false);''', '''
let release;const downloads=[];const button={dataset:{},disabled:false,setAttribute:()=>{}};
const document={querySelector:()=>button};const uploadedSealApplicationScopeSnapshot=()=>({documentId:'OD-1'}),uploadedSealApplicationScopeIsCurrent=()=>true;
const downloadOfficialWorkflowFile=(...args)=>{downloads.push(args);return new Promise(r=>release=r)};
const renderUploadedEditorReadOnlyPresentation=()=>button.disabled=false;
''', ['downloadUploadedEditorReadOnlyPrepared'])

    def test_draft_preview_footer_preserves_confirm_and_return_actions(self):
        css = (ROOT / 'styles.css').read_text()
        self.assertIn('#uploadedPdfEditor[data-case-read-only="true"] .pdf-editor-footer-actions { display: none; }', css)
        owner = runtime_function(self.source, 'renderUploadedEditorSubmissionActions')
        self.assertIn('back.hidden = uploadedSealEditorRuntime.reviewMode === "edited" || uploadedEditorReadOnlyPresentation().caseReadOnly', owner)
        self.assertIn('current ? "確認內容並送簽"', owner)

    def test_readonly_render_and_disclosure_restore_both_directions(self):
        self.js('''
uploadedSealApplicationRuntime.editable=false;
renderUploadedEditorReadOnlyPresentation();renderUploadedSealApplicationDisclosure();
assert.equal(nodes['#uploadedPdfEditor'].dataset.caseReadOnly,'true');
assert.equal(nodes['#uploadedSealApplicationPanel'].dataset.caseReadOnly,'true');
assert.equal(nodes['#uploadedSealWorkspaceTitle'].textContent,'用印案件檢閱（唯讀）');
assert.equal(nodes['#uploadedSealApplicationToggleBtn'].textContent,'展開申請資訊');
uploadedSealApplicationRuntime.editable=true;uploadedSealEditorRuntime.reviewMode='prepared';
renderUploadedEditorReadOnlyPresentation();renderUploadedSealApplicationDisclosure();
assert.equal(nodes['#uploadedSealApplicationPanel'].dataset.caseReadOnly,'false');
assert.equal(nodes['#uploadedSealWorkspaceTitle'].textContent,'PDF 文件預覽');
assert.equal(nodes['#uploadedSealApplicationToggleBtn'].textContent,'修改申請資料');
uploadedSealEditorRuntime.reviewMode='edited';renderUploadedEditorReadOnlyPresentation();
assert.equal(nodes['#uploadedSealWorkspaceTitle'].textContent,'電子用印編輯');
assert.equal(nodes['#uploadedEditorReadOnlyNotice'].hidden,true);
''', '''
const element=()=>({dataset:{},hidden:false,textContent:'',setAttribute:()=>{},removeAttribute:()=>{}});
const nodes=Object.fromEntries(['#uploadedPdfEditor','#uploadedSealApplicationPanel','#uploadedSealWorkspaceTitle','#uploadedEditorReadOnlyNotice','#uploadedSealApplicationToggleBtn','#uploadedSealApplicationSummary'].map(key=>[key,element()]));
nodes['#uploadedSealApplicationFields']={hidden:true,querySelectorAll:()=>[{value:'filled'}]};
const document={querySelector:key=>nodes[key]||null};
''', ['renderUploadedEditorReadOnlyPresentation','renderUploadedSealApplicationDisclosure'])
        css = (ROOT / 'styles.css').read_text()
        self.assertIn('#uploadedSealApplicationPanel[data-case-read-only="true"] .electronic-seal-route-result { display: none; }', css)


if __name__ == '__main__':
    unittest.main()
