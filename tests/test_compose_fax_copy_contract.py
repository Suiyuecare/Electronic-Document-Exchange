from __future__ import annotations

import io
import inspect
import json
import re
import subprocess
import unittest
from pathlib import Path

import backend
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]


def javascript_function(source: str, name: str, next_name: str) -> str:
    start = source.index(f"function {name}(")
    boundary = re.search(rf"\n(?:async\s+)?function\s+{re.escape(next_name)}\(", source[start:])
    if boundary is None:
        raise AssertionError(f"JavaScript function boundary not found: {name} -> {next_name}")
    end = start + boundary.start()
    return source[start:end]


class ComposeFaxCopyContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "app.js").read_text(encoding="utf-8")

    def test_sender_fax_defaults_to_na_everywhere_the_compose_form_is_initialized(self) -> None:
        fax_input = re.search(r'<input\s+id="contactFax"(?P<attrs>[^>]*)>', self.html)
        self.assertIsNotNone(fax_input)
        self.assertRegex(fax_input.group("attrs"), r'\bvalue="N/A"')

        payload = javascript_function(self.js, "composePayload", "syncComposeElectronicExchangeMode")
        defaults = javascript_function(self.js, "composeContactDefaults", "applyComposeContactDefaults")
        correction = javascript_function(self.js, "beginComposeOfficialCorrection", "beginOfficialCorrection")
        self.assertRegex(self.js, r'const\s+composeDefaultContactFax\s*=\s*"N/A"')
        self.assertRegex(payload, r'contactFax:\s*[^\n]+\|\|\s*composeDefaultContactFax')
        self.assertIn("contactFax: composeDefaultContactFax", defaults)
        self.assertRegex(correction, r'"#contactFax":\s*metadata\.contact_fax\s*\|\|\s*composeDefaultContactFax')
        for body in (payload, defaults, correction):
            self.assertNotIn("(02)2254-4029", body)

    def test_copy_recipients_is_an_editable_company_default_and_part_of_autosave(self) -> None:
        copy_input = re.search(r'<(?:input|textarea)\b(?P<before>[^>]*)\bid="copyRecipients"(?P<after>[^>]*)>', self.html)
        self.assertIsNotNone(copy_input)
        attributes = copy_input.group("before") + copy_input.group("after")
        self.assertNotRegex(attributes, r'\b(?:readonly|disabled)\b')

        payload = javascript_function(self.js, "composePayload", "syncComposeElectronicExchangeMode")
        defaults = javascript_function(self.js, "composeContactDefaults", "applyComposeContactDefaults")
        apply_defaults = javascript_function(self.js, "applyComposeContactDefaults", "setAiDraftStatus")
        self.assertIn('document.querySelector("#copyRecipients")', payload)
        self.assertIn("composeCopyRecipientsValue(companyName", payload)
        self.assertIn("selectedCompanyName", defaults)
        self.assertIn("syncComposeCopyRecipientsDefault(force);", apply_defaults)

        autosave_start = self.js.index("const composeAutosaveSelectors = [")
        autosave_end = self.js.index("\n];", autosave_start) + 3
        self.assertIn('"#copyRecipients"', self.js[autosave_start:autosave_end])

        dirty_binding = self.js[self.js.rindex('["#composeCompanySelect"'):]
        self.assertIn('"#copyRecipients"', dirty_binding.split(".forEach", 1)[0])

    def test_original_defaults_from_recipient_without_overwriting_a_manual_edit(self) -> None:
        script = javascript_function(self.js, "syncComposeOriginalRecipientsDefault", "composeCopyRecipientsValue")
        result = subprocess.run(["node", "-e", script + r'''
const recipient={value:"虛構收文甲單位"};
const original={value:"",dataset:{}};
const document={querySelector:selector=>selector==="#recipient"?recipient:original};
syncComposeOriginalRecipientsDefault();
const initial={value:original.value,autoDefault:original.dataset.autoDefault};
recipient.value="虛構收文乙單位";syncComposeOriginalRecipientsDefault();
const changed=original.value;
original.value="人工指定正本單位";original.dataset.autoDefault="false";
recipient.value="虛構收文丙單位";syncComposeOriginalRecipientsDefault();
console.log(JSON.stringify({initial,changed,manual:original.value}));
'''], capture_output=True, text=True, check=True, timeout=20)
        self.assertEqual(json.loads(result.stdout), {
            "initial": {"value": "虛構收文甲單位", "autoDefault": "true"},
            "changed": "虛構收文乙單位",
            "manual": "人工指定正本單位",
        })

    def test_both_distribution_fields_are_saved_and_restored(self) -> None:
        payload = javascript_function(self.js, "composePayload", "syncComposeElectronicExchangeMode")
        snapshot = javascript_function(self.js, "dispatchDocSnapshot", "dispatchDocContentHash")
        application = javascript_function(self.js, "createOfficialApplicationFromCompose", "createDispatchFromForm")
        correction = javascript_function(self.js, "beginComposeOfficialCorrection", "beginOfficialCorrection")
        pdf_payload = javascript_function(self.js, "backendPdfPayload", "currentSignatureProof")
        self.assertIn('document.querySelector("#originalRecipients")', payload)
        self.assertIn('document.querySelector("#copyRecipients")', payload)
        self.assertIn('"#originalRecipients"', self.js[self.js.index("const composeAutosaveSelectors = ["):self.js.index("\n];", self.js.index("const composeAutosaveSelectors = ["))])
        self.assertIn("originalRecipients: doc.originalRecipients", snapshot)
        self.assertIn("original_recipients: data.originalRecipients", application)
        self.assertIn("copy_recipients: data.copyRecipients", application)
        self.assertIn('"#originalRecipients": metadata.original_recipients', correction)
        self.assertIn("originalRecipients: doc.originalRecipients", pdf_payload)

    def test_copy_default_respects_manual_list_and_replaces_only_a_retained_company(self) -> None:
        names = [
            ("composePartyItems", "syncComposeOriginalRecipientsDefault"),
            ("composeCopyRecipientsValue", "syncComposeCopyRecipientsDefault"),
            ("syncComposeCopyRecipientsDefault", "syncComposeAttachmentDescription"),
        ]
        script = "\n".join(javascript_function(self.js, name, next_name) for name, next_name in names)
        result = subprocess.run(["node", "-e", script + r'''
const company={value:"虛構發文甲單位"};
const copies={value:"",dataset:{}};
const document={querySelector:selector=>selector==="#composeCompanySelect"?company:copies};
const authState={user:{company_name:"虛構備援單位"}};
const initial=syncComposeCopyRecipientsDefault();
copies.value="人工自訂副本";copies.dataset.autoDefault="false";
const manualOnly=syncComposeCopyRecipientsDefault();
company.value="虛構發文乙單位";const manualAfterSwitch=syncComposeCopyRecipientsDefault();
company.value="虛構發文甲單位";copies.value="";copies.dataset={};
syncComposeCopyRecipientsDefault();
copies.value+="、人工增補單位";copies.dataset.autoDefault="false";
company.value="虛構發文乙單位";const replacedRetainedCompany=syncComposeCopyRecipientsDefault();
console.log(JSON.stringify({initial,manualOnly,manualAfterSwitch,replacedRetainedCompany,defaultCompany:copies.dataset.defaultCompany}));
'''], capture_output=True, text=True, check=True, timeout=20)
        self.assertEqual(json.loads(result.stdout), {
            "initial": "虛構發文甲單位",
            "manualOnly": "人工自訂副本",
            "manualAfterSwitch": "人工自訂副本",
            "replacedRetainedCompany": "虛構發文乙單位、人工增補單位",
            "defaultCompany": "虛構發文乙單位",
        })

    def test_restoring_another_company_preserves_manual_copy_recipient(self) -> None:
        names = [
            ("composePartyItems", "syncComposeOriginalRecipientsDefault"),
            ("syncComposeOriginalRecipientsDefault", "composeCopyRecipientsValue"),
            ("composeCopyRecipientsValue", "syncComposeCopyRecipientsDefault"),
            ("syncComposeCopyRecipientsDefault", "syncComposeAttachmentDescription"),
            ("restoreComposeAutosave", "clearComposeAutosave"),
        ]
        script = "\n".join(javascript_function(self.js, name, next_name) for name, next_name in names)
        result = subprocess.run(["node", "-e", script + r'''
const controls={
  "#composeCompanySelect":{tagName:"SELECT",value:"虛構甲公司",options:[{value:"虛構甲公司"},{value:"虛構乙公司"}],dataset:{}},
  "#copyRecipients":{tagName:"TEXTAREA",value:"虛構甲公司",dataset:{defaultCompany:"虛構甲公司",autoDefault:"false"}},
  "#originalRecipients":{tagName:"TEXTAREA",value:"",dataset:{}},
  "#recipient":{tagName:"INPUT",value:"虛構收文單位",dataset:{}}
};
const document={querySelector:selector=>controls[selector]||null};
const authState={user:{company_name:"虛構甲公司"}};
const composeAutosaveSelectors=Object.keys(controls);
const composeAutosaveIdentity=()=>"u:c";
let composeAutosaveRestoredForIdentity="";
const refreshComposeCloudDrafts=()=>{};
const renderApprovalCategorySelect=()=>{};
const composeSealPlacements={large:{page:1,x:0,y:0},small:{page:1,x:0,y:0}};
const clampComposePlacement=(value,fallback)=>fallback;
const dispatchDocs=[];
let currentComposeDraftId="",composeDraftRequestId="",composeCloudDraftId="",composeOfficialContentRevision=null;
const composeCloudRows=[],composeCloudRevisions=new Map();
const syncComposeElectronicExchangeMode=()=>{};
let draftConfirmed=false,draftSigned=false,activeComposeStep="",composeSaveState={};
const formatComposeSaveTime=()=>"now";
const renderComposeApprovalRoute=()=>{},renderDraftPreview=()=>{},renderComposeSaveStatus=()=>{};
const restored=restoreComposeAutosave({updatedAt:"now",snapshot:{
  userId:"u",companyId:"c",copyRecipientsAutoDefault:false,originalRecipientsAutoDefault:true,
  values:{"#composeCompanySelect":"虛構乙公司","#copyRecipients":"虛構甲公司","#recipient":"虛構收文單位","#originalRecipients":"虛構收文單位"}
}});
console.log(JSON.stringify({restored,sender:controls["#composeCompanySelect"].value,
  copies:controls["#copyRecipients"].value,defaultCompany:controls["#copyRecipients"].dataset.defaultCompany}));
'''], capture_output=True, text=True, check=True, timeout=20)
        self.assertEqual(json.loads(result.stdout), {
            "restored": True,
            "sender": "虛構乙公司",
            "copies": "虛構甲公司",
            "defaultCompany": "虛構乙公司",
        })

    def test_preview_and_submit_payload_render_and_persist_fax_and_copy_recipients(self) -> None:
        preview = javascript_function(self.js, "renderOfficialDraftPageHtml", "renderOfficialDraftPagesHtml")
        self.assertRegex(preview, r'>傳真：\$\{escapeDraftHtml\(data\.contactFax(?:\s*\|\|\s*composeDefaultContactFax)?\)\}<')
        self.assertRegex(preview, r'>副本：</span><strong>\$\{escapeDraftHtml\(data\.copyRecipients')

        application = javascript_function(self.js, "createOfficialApplicationFromCompose", "createDispatchFromForm")
        self.assertIn("contact_fax: data.contactFax", application)
        self.assertIn("copy_recipients: data.copyRecipients", application)

        legacy_payload = javascript_function(self.js, "backendDocumentPayload", "backendWorkflowPayload")
        self.assertIn("fax: doc.contactFax", legacy_payload)
        self.assertIn("copy_recipients: doc.copyRecipients", legacy_payload)

        snapshot = javascript_function(self.js, "dispatchDocSnapshot", "dispatchDocContentHash")
        self.assertIn("copyRecipients: doc.copyRecipients", snapshot)

        pdf_payload = javascript_function(self.js, "backendPdfPayload", "currentSignatureProof")
        self.assertIn("copyRecipients: doc.copyRecipients", pdf_payload)
        self.assertRegex(pdf_payload, r'contactFax:\s*[^\n]+\|\|\s*composeDefaultContactFax')

    def test_edit_and_resubmit_paths_restore_and_keep_copy_recipients(self) -> None:
        correction = javascript_function(self.js, "beginComposeOfficialCorrection", "beginOfficialCorrection")
        self.assertRegex(correction, r'"#copyRecipients":\s*metadata\.copy_recipients')
        self.assertRegex(correction, r'copyRecipients:\s*metadata\.copy_recipients_manual\s*===\s*true')
        self.assertRegex(correction, r'copyRecipientsManual:\s*metadata\.copy_recipients_manual\s*===\s*true')
        self.assertIn('correctedCopies.dataset.autoDefault = metadata.copy_recipients_manual === true ? "false" : "true"', correction)

        create_dispatch = javascript_function(self.js, "createDispatchFromForm", "saveComposeDraft")
        self.assertIn("copyRecipients: data.copyRecipients", create_dispatch)
        self.assertIn("copyRecipientsManual: data.copyRecipientsManual", create_dispatch)
        self.assertIn("contactFax: data.contactFax", create_dispatch)


class OfficialPdfFaxCopyContractTest(unittest.TestCase):
    def test_sqlite_and_supabase_generated_pdf_payloads_keep_the_same_fields(self) -> None:
        self.assertEqual(backend.EDOC_DEFAULT_CONTACT_FAX, "N/A")
        self.assertIn("copy_recipients", backend.OFFICIAL_CORRECTION_METADATA_TEXT_FIELDS)
        self.assertIn("copy_recipients", backend.OFFICIAL_CORRECTION_RENDER_METADATA_FIELDS)
        for builder in (
            backend.official_pdf_document_payload,
            backend.supabase_official_pdf_document_payload,
        ):
            source = inspect.getsource(builder)
            self.assertIn('"contact_fax"', source)
            self.assertIn('"copy_recipients"', source)
            self.assertIn("EDOC_DEFAULT_CONTACT_FAX", source)

    def test_missing_fax_is_normalized_to_na_and_pdf_contains_fax_and_custom_copies(self) -> None:
        document = {
            "company_name": "歲悅股份有限公司",
            "doc_type": "函",
            "doc_no": "測試字第1150825001號",
            "agency_name": "測試受文機關",
            "subject": "傳真與副本欄位測試",
            "body": "本測試資料已去識別化。",
            "copy_recipients": ["歲悅股份有限公司", "增補副本單位"],
        }
        info = backend.official_pdf_info(document, "歲悅正式函")
        self.assertEqual(info["contact_fax"], "N/A")
        self.assertEqual(info["copy_recipients"], "歲悅股份有限公司、增補副本單位")

        package = backend.build_official_pdf_package(document)
        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(package["data"])).pages)
        self.assertIn("傳真：N/A", text)
        self.assertIn("副本：", text)
        self.assertIn("歲悅股份有限公司、增補副本單位", text)

    def test_custom_original_and_copy_units_are_rendered_in_generated_pdf(self) -> None:
        document = {
            "company_name": "虛構發文單位",
            "doc_type": "函",
            "doc_no": "測試字第1150000001號",
            "agency_name": "虛構收文單位",
            "subject": "去識別化正副本驗收",
            "body": "本測試不包含真實個資。",
            "original_recipients": "人工指定正本單位",
            "copy_recipients": "虛構發文單位、人工增補副本單位",
        }
        info = backend.official_pdf_info(document, "歲悅正式函")
        self.assertEqual(info["original_recipients"], "人工指定正本單位")
        self.assertEqual(info["copy_recipients"], "虛構發文單位、人工增補副本單位")
        package = backend.build_official_pdf_package(document)
        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(package["data"])).pages)
        self.assertIn("正本：", text)
        self.assertIn("人工指定正本單位", text)
        self.assertIn("副本：", text)
        self.assertIn("人工增補副本單位", text)


if __name__ == "__main__":
    unittest.main()
