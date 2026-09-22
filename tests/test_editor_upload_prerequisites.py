"""Missing application fields are not misreported as failed PDF uploads."""
import json
from pathlib import Path
import subprocess
import unittest

from tests.test_compose_output_contract import function

ROOT = Path(__file__).resolve().parents[1]


class EditorUploadPrerequisitesTest(unittest.TestCase):
    def run_js(self, body):
        source = (ROOT / "app.js").read_text()
        names = ["uploadedEditorDraftPrerequisiteIssue", "showUploadedEditorDraftPrerequisite",
                 "uploadedPdfUploadBlockingMessage", "openUploadedPdfPicker", "handleUploadedSealPdfChange"]
        setup = r'''
const events=[];let selection={documentCategory:'synthetic',approvalRouteCode:'A'},feature=true;
const uploadedSealEditorRuntime={documentId:'',locked:false,reviewMode:'edited',uploading:false,dirtyGeneration:0,savedGeneration:0};
const uploadedSealApplicationRuntime={editable:true};
const uploadedSealEditorState={pages:[],elements:[]};
const nodes={'#uploadedSealPdfInput':{value:'file',files:[new File(['synthetic'],'synthetic.pdf',{type:'application/pdf'})],click(){events.push(['picker'])}},'#uploadedSealCompany':{value:'CO'},'#uploadedSealDepartment':{value:'DEPT'},'#uploadedSealApplicationFields':{hidden:true}};
const document={querySelector:key=>nodes[key]||null};const window={confirm:()=>true};
const hasAuthenticatedBackendSession=()=>true,approvalSelectionForSelect=()=>selection,uploadedEditorV2FeatureEnabled=()=>feature;
const renderUploadedSealApplicationDisclosure=()=>{},setOfficialFieldValidity=(...args)=>events.push(['field',...args]),focusOfficialWorkflowField=key=>events.push(['focus',key]);
const showToast=text=>events.push(['toast',text]),clearUploadedEditorUploadError=()=>events.push(['clear']),setUploadedPdfA4Status=(...args)=>events.push(['a4',...args]),setUploadedEditorSaveStatus=(...args)=>events.push(['status',...args]);
const refreshUploadedEditorAccess=async()=>events.push(['access']);
const PDF_EDITOR_MAX_FILE_BYTES=50*1024*1024;
const uploadedSealApplicationScopeSnapshot=()=>({}),uploadedSealApplicationScopeIsCurrent=()=>true,renderUploadedSealWorkbench=()=>{};
const confirmUploadedPdfConversion=async()=>{events.push(['pdf-inspection']);return false};
const requestEditorUpload=async()=>events.push(['tus']),reportEditorUploadFailure=async()=>events.push(['failure']),pdfA4UiErrorMessage=e=>e.message;
const showUploadedEditorUploadError=()=>events.push(['upload-error']);
'''
        script = setup + "\n" + "\n".join(function(source, name) for name in names) + "\n(async()=>{" + body + "})().catch(e=>{console.error(e);process.exit(1)});"
        result = subprocess.run(["node", "-e", script], text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_missing_category_focuses_application_without_opening_file_picker(self):
        value = self.run_js('selection={};openUploadedPdfPicker();console.log(JSON.stringify({events,hidden:nodes["#uploadedSealApplicationFields"].hidden}));')
        self.assertFalse(value["hidden"])
        self.assertIn(["focus", "#uploadedSealApprovalCategorySelect"], value["events"])
        self.assertFalse(any(event[0] in {"picker", "pdf-inspection", "tus", "failure", "upload-error"} for event in value["events"]))
        self.assertFalse(any("失敗" in str(event) or "未通過" in str(event) for event in value["events"]))

    def test_direct_change_with_missing_category_never_inspects_or_uploads_pdf(self):
        value = self.run_js('selection={};await handleUploadedSealPdfChange();console.log(JSON.stringify({events,uploading:uploadedSealEditorRuntime.uploading}));')
        self.assertFalse(value["uploading"])
        self.assertIn(["focus", "#uploadedSealApprovalCategorySelect"], value["events"])
        self.assertFalse(any(event[0] in {"pdf-inspection", "tus", "failure", "upload-error"} for event in value["events"]))

    def test_missing_company_or_department_focuses_exact_field(self):
        for selector in ("#uploadedSealCompany", "#uploadedSealDepartment"):
            with self.subTest(selector=selector):
                value = self.run_js(f'nodes[{json.dumps(selector)}].value="";openUploadedPdfPicker();console.log(JSON.stringify(events));')
                self.assertIn(["focus", selector], value)
                self.assertNotIn(["picker"], value)

    def test_no_usable_seals_does_not_block_file_picker_or_pdf_inspection(self):
        value = self.run_js('const uploadedSealOptions=[];openUploadedPdfPicker();await handleUploadedSealPdfChange();console.log(JSON.stringify(events));')
        self.assertIn(["picker"], value)
        self.assertIn(["pdf-inspection"], value)

    def test_readonly_busy_or_switching_states_block_both_entrypoints(self):
        for assignment in ('locked=true', 'uploading=true', 'companyChanging=true', 'directoryLoading=true', 'reviewMode="original"'):
            with self.subTest(assignment=assignment):
                value = self.run_js(f'uploadedSealEditorRuntime.{assignment};openUploadedPdfPicker();await handleUploadedSealPdfChange();console.log(JSON.stringify(events));')
                self.assertFalse(any(event[0] in {"picker", "pdf-inspection", "tus"} for event in value))

    def test_missing_feature_access_reloads_permissions_not_pdf_error(self):
        value = self.run_js('feature=false;openUploadedPdfPicker();await handleUploadedSealPdfChange();console.log(JSON.stringify(events));')
        self.assertIn(["access"], value)
        self.assertFalse(any(event[0] in {"picker", "pdf-inspection", "tus", "upload-error"} for event in value))

    def test_existing_draft_uses_locked_classification_instead_of_hidden_form_value(self):
        value = self.run_js('uploadedSealEditorRuntime.documentId="DRAFT";selection={};nodes["#uploadedSealDepartment"].value="";openUploadedPdfPicker();console.log(JSON.stringify(events));')
        self.assertIn(["picker"], value)


if __name__ == "__main__":
    unittest.main()
