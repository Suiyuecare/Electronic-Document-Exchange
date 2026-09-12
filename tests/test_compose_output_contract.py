from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source: str, name: str) -> str:
    match = re.search(rf"(?:async )?function {re.escape(name)}\(", source)
    if not match:
        raise AssertionError(name)
    boundary = re.search(r"\n(?:async )?function \w+\(", source[match.start():])
    if not boundary:
        raise AssertionError(f"Missing boundary for {name}")
    return source[match.start():match.start() + boundary.start()]


class ComposeOutputContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (ROOT / "app.js").read_text()

    def evaluate(self, names, body):
        code = "\n".join(function(self.js, name) for name in names)
        if "createOfficialApplicationFromCompose" in names:
            code += '\nconst composeRequestScope = () => "fixture-session"; let composeOfficialContentRevision = null;'
        result = subprocess.run(["node", "-e", code + "\n" + body], check=True, text=True, capture_output=True, timeout=20)
        return json.loads(result.stdout)

    def test_date_defaults_to_taipei_calendar_day_not_machine_timezone(self):
        result = self.evaluate(["composeTodayDate", "isValidComposeDispatchDate"], '''
          console.log(JSON.stringify({today:composeTodayDate(new Date("2026-09-08T16:30:00Z")),
            leap:isValidComposeDispatchDate("2028-02-29"), invalid:isValidComposeDispatchDate("2026-02-29"),
            empty:isValidComposeDispatchDate(""), malformed:isValidComposeDispatchDate("2026-9-08")}));
        ''')
        self.assertEqual(result, {"today": "2026-09-09", "leap": True, "invalid": False, "empty": False, "malformed": False})

    def test_official_body_renders_real_sections_and_hanging_numbered_items(self):
        result = self.evaluate(["escapeDraftHtml", "officialDraftBodyItem", "renderOfficialDraftBody"], '''
          const text="說明：一、依測試資料辦理。\\n(一)第一層次\\n１、第二層次\\n(１)第三層次\\n辦法：一、依所列時程辦理。\\n擬辦：一、請核示。\\n核復事項：一、依申請內容核復。";
          console.log(JSON.stringify({html:renderOfficialDraftBody(text),continued:renderOfficialDraftBody("接續上一頁文字",true)}));
        ''')
        html = result["html"]
        for label in ("說明：", "辦法：", "擬辦：", "核復事項："):
            self.assertEqual(html.count(label), 1)
        for level in range(4):
            self.assertIn(f"--item-level:{level}", html)
        self.assertIn("--section-label-width:5em", html)
        self.assertIn("<span>續：</span>", result["continued"])

    def test_official_body_escapes_content_and_preserves_plain_paragraphs(self):
        result = self.evaluate(["escapeDraftHtml", "officialDraftBodyItem", "renderOfficialDraftBody"], '''
          console.log(JSON.stringify({html:renderOfficialDraftBody("一、<script>alert(1)</script>\\n保留原文與社老字第11512220178號。"),empty:renderOfficialDraftBody("")}));
        ''')
        self.assertNotIn("<script>", result["html"])
        self.assertIn("&lt;script&gt;", result["html"])
        self.assertIn("保留原文與社老字第11512220178號。", result["html"])
        self.assertEqual(result["empty"], "")

    PAGINATION_FUNCTIONS = [
        "escapeDraftHtml", "officialDraftBodyItem", "officialDraftBodyContinuationContext",
        "renderOfficialDraftBody", "draftSubjectSource", "draftBodySource",
        "preferredDraftBreak", "draftFitLength", "splitDraftContentIntoPages",
        "chunkTextByLength", "fallbackDraftContentPages", "renderOfficialDraftPageHtml",
    ]

    def test_actual_split_and_render_keep_long_item_indentation_and_original_body(self):
        # Replace only the browser measurement boundary; execute the actual
        # splitter, continuation context and HTML renderer together.
        result = self.evaluate(self.PAGINATION_FUNCTIONS, '''
          const ensureDraftMeasurePreview=()=>true;
          const draftPageMainFits=(data,content)=>content.body.length<=48;
          const source="說明：(一)"+"甲乙丙丁".repeat(40);
          const data={subject:"測試主旨",body:source};
          const pages=splitDraftContentIntoPages(data,"");
          const isValidComposeDispatchDate=()=>true,renderDraftSealLayer=()=>"";
          console.log(JSON.stringify({
            original:data.body, reconstructed:pages.map(p=>p.body).join(""),
            dataKeys:Object.keys(data),
            fullPage:renderOfficialDraftPageHtml({...data,dispatchDate:"2026-09-12"},pages[1],2,pages.length,""),
            rows:pages.map(p=>({context:p.bodyContext,html:renderOfficialDraftBody(p.body,p.bodyContinued,p.bodyContext)}))
          }));
        ''')
        self.assertEqual(result["original"], result["reconstructed"])
        self.assertEqual(result["dataKeys"], ["subject", "body"])
        self.assertGreater(len(result["rows"]), 2)
        self.assertIn('class="draft-body-paragraph draft-body-continuation" style="margin-left:3em"', result["fullPage"])
        self.assertIn("--item-level:1;--item-marker-width:2em", result["rows"][0]["html"])
        for row in result["rows"][1:]:
            self.assertEqual(row["context"]["paragraphIndentEm"], 3)
            self.assertIn('class="draft-body-paragraph draft-body-continuation" style="margin-left:3em"', row["html"])
            self.assertNotIn("draft-item-marker", row["html"])

    def test_actual_split_preserves_wide_section_and_resets_at_new_paragraph_and_section(self):
        result = self.evaluate(self.PAGINATION_FUNCTIONS, '''
          const ensureDraftMeasurePreview=()=>true;
          const draftPageMainFits=(data,content)=>content.body.length<=48;
          const source="核復事項：(１)"+"甲乙丙丁".repeat(30)+"\\n二、新段落。\\n辦法：一、新節。";
          const pages=splitDraftContentIntoPages({subject:"測試",body:source},"");
          console.log(JSON.stringify({source,reconstructed:pages.map(p=>p.body).join(""),rows:pages.map(p=>({context:p.bodyContext,html:renderOfficialDraftBody(p.body,p.bodyContinued,p.bodyContext)}))}));
        ''')
        self.assertEqual(result["source"], result["reconstructed"])
        continued = [row for row in result["rows"] if row["context"]["paragraphIndentEm"] == 5]
        self.assertTrue(continued)
        for row in continued:
            self.assertIn("--section-label-width:5em", row["html"])
            self.assertIn("margin-left:5em", row["html"])
        html = "".join(row["html"] for row in result["rows"])
        self.assertIn('<span class="draft-item-marker">二、</span><span>新段落。</span>', html)
        self.assertIn('--section-label-width:3em"><span>辦法：</span>', html)

    def test_continuation_context_resets_after_newline_and_does_not_invent_a_marker(self):
        result = self.evaluate(self.PAGINATION_FUNCTIONS, '''
          const source="核復事項：(一)甲乙1、這仍是同一段<內容>。\\r\\n二、新段落。";
          const middle=source.indexOf("1、");
          const next=source.indexOf("二、");
          const context=officialDraftBodyContinuationContext(source,middle);
          console.log(JSON.stringify({context,next:officialDraftBodyContinuationContext(source,next),html:renderOfficialDraftBody(source.slice(middle,next),true,context)}));
        ''')
        self.assertEqual(result["context"], {"sectionColumns": 5, "paragraphIndentEm": 3})
        self.assertEqual(result["next"], {"sectionColumns": 5, "paragraphIndentEm": None})
        self.assertIn("margin-left:3em", result["html"])
        self.assertNotIn("draft-item-marker", result["html"])
        self.assertIn("&lt;內容&gt;", result["html"])

    def test_fallback_pagination_also_keeps_continuation_metadata(self):
        result = self.evaluate(self.PAGINATION_FUNCTIONS, '''
          const ensureDraftMeasurePreview=()=>null;
          const source="核復事項：(１)"+"甲乙丙丁".repeat(200);
          const pages=splitDraftContentIntoPages({subject:"測試",body:source},"").filter(p=>p.body);
          console.log(JSON.stringify({source,reconstructed:pages.map(p=>p.body).join(""),rows:pages.map(p=>({context:p.bodyContext,html:renderOfficialDraftBody(p.body,p.bodyContinued,p.bodyContext)}))}));
        ''')
        self.assertEqual(result["source"], result["reconstructed"])
        for row in result["rows"][1:]:
            self.assertEqual(row["context"], {"sectionColumns": 5, "paragraphIndentEm": 5})
            self.assertIn("margin-left:5em", row["html"])

    def test_electronic_mode_hides_disables_and_restores_physical_seal_controls(self):
        result = self.evaluate(["composeOutputMode", "syncComposeElectronicExchangeMode"], '''
          const fields = {hidden:false}, mode={value:"electronic"}, large={value:"一般章"}, small={value:"公司設立章"}, hint={dataset:{}};
          const nodes={"#composeOutputMode":mode,"#largeSealType":large,"#smallSealType":small,"#composeSealFields":fields,"#composeSealModeHint":hint};
          global.document={querySelector:s=>nodes[s]};
          const composeSealTypes=["無","一般章","公司設立章"];
          syncComposeElectronicExchangeMode();
          const electronic={hidden:fields.hidden,disabled:large.disabled&&small.disabled,hint:hint.textContent};
          mode.value="physical"; syncComposeElectronicExchangeMode();
          console.log(JSON.stringify({electronic, physical:{hidden:fields.hidden,disabled:large.disabled||small.disabled,large:large.value,small:small.value}}));
        ''')
        self.assertTrue(result["electronic"]["hidden"])
        self.assertTrue(result["electronic"]["disabled"])
        self.assertIn("仍須完成簽核", result["electronic"]["hint"])
        self.assertEqual(result["physical"], {"hidden": False, "disabled": False, "large": "一般章", "small": "公司設立章"})

    def test_electronic_mode_removes_only_seal_requirement_not_approval_category(self):
        result = self.evaluate(["composeReadinessChecks"], '''
          const activeComposeStep="fill", draftConfirmed=false;
          const composeInputState=()=>({outputMode:"electronic",largeSealType:"無",smallSealType:"無",subject:"",body:"",attachments:[]});
          console.log(JSON.stringify(composeReadinessChecks().filter(item=>["seal","approvalCategory"].includes(item.key))));
        ''')
        by_key = {item["key"]: item for item in result}
        self.assertTrue(by_key["seal"]["done"])
        self.assertTrue(by_key["approvalCategory"]["required"])
        self.assertFalse(by_key["approvalCategory"]["done"])
        guard = function(self.js, "applyWorkflowReadinessSubmitGuards")
        self.assertIn("!draftConfirmed || !composeReady", guard)

    def test_electronic_pdf_preview_has_no_stamp_layer(self):
        result = self.evaluate(["renderDraftSealLayer"], '''
          console.log(JSON.stringify({layer:renderDraftSealLayer({outputMode:"electronic",largeSealType:"一般章"},1)}));
        ''')
        self.assertEqual(result["layer"], "")

    def test_document_number_is_server_owned_and_force_never_regenerates(self):
        result = self.evaluate(["assignNextDispatchNo", "ensureComposeDraftRequestId"], '''
          let composeDraftRequestId="";
          const input={value:"歲悅字第1150908001號"};
          global.document={querySelector:()=>input};
          const first=ensureComposeDraftRequestId(), retry=ensureComposeDraftRequestId();
          const number=assignNextDispatchNo(true);
          input.value="";
          console.log(JSON.stringify({first,retry,number,empty:assignNextDispatchNo(true),readonly:input.readOnly,placeholder:input.placeholder}));
        ''')
        self.assertEqual(result["first"], result["retry"])
        self.assertRegex(result["first"], r"^OD-[0-9a-f-]{36}$")
        self.assertEqual(result["number"], "歲悅字第1150908001號")
        self.assertEqual(result["empty"], "")
        self.assertTrue(result["readonly"])
        self.assertEqual(result["placeholder"], "儲存時自動配號")
        self.assertNotIn('querySelector("#generateDispatchNoBtn")', self.js)
        self.assertNotIn('querySelector("#formatGenerateNoBtn")', self.js)

    def test_electronic_application_payload_still_uses_authorized_workflow_and_backend_number(self):
        result = self.evaluate(["createOfficialApplicationFromCompose"], '''
          const calls=[], numberInput={value:""};
          const composeCompanyForOfficialApplication=()=>({id:"TEST-CO"});
          const ensureComposeDraftRequestId=()=>"OD-00000000-0000-4000-8000-000000000001";
          const activeUnit=()=>"測試部門";
          const composeSealPlacements={large:{},small:{}};
          const officialComposeMetadata=()=>({});
          global.document={querySelector:s=>s==="#dispatchNo"?numberInput:{files:[]}};
          const backendRequest=async(path,options)=>{calls.push({path,payload:JSON.parse(options.body)});return {id:"OD-TEST",dispatch_no:"歲悅字第1150908001號"};};
          const data={outputMode:"electronic",dispatchDate:"2026-09-09",companyName:"測試公司",subject:"測試主旨",body:"測試說明",documentCategory:"合作意向書",approvalFlowNodes:["主管","主任","總務"],approvalRouteCode:"A",sealPlacements:composeSealPlacements,attachmentDetails:"清冊",no:"CLIENT-NUMBER"};
          (async()=>{const doc={id:"LOCAL-TEST"};await createOfficialApplicationFromCompose(doc,data,{submit:false});console.log(JSON.stringify({calls,doc,number:numberInput.value}));})();
        ''')
        self.assertEqual(len(result["calls"]), 1)
        payload = result["calls"][0]["payload"]
        self.assertFalse(payload["requires_stamp"])
        self.assertEqual(payload["output_mode"], "electronic")
        self.assertEqual(payload["dispatch_date"], "2026-09-09")
        self.assertEqual(payload["approval_route_code"], "A")
        self.assertEqual(payload["stamp_positions"], [])
        self.assertNotIn("dispatch_no", payload["metadata"])
        self.assertEqual(result["number"], "歲悅字第1150908001號")

    def test_confirmation_waits_for_persisted_number_before_showing_final_preview(self):
        result = self.evaluate(["advanceComposeStep"], '''
          const composeStepKeys=()=>["fill","confirm"], composeStepIndex=()=>0;
          const validateComposeStep=()=>true;
          let draftPreviewExpanded=false;
          const events=[];
          const saveComposeDraft=async()=>{events.push("saved");return {officialDocumentId:"OD-TEST",no:"server-number"};};
          const setComposeStep=(step)=>events.push(step);
          (async()=>{await advanceComposeStep();console.log(JSON.stringify({events,draftPreviewExpanded}));})();
        ''')
        self.assertEqual(result["events"], ["saved", "confirm"])

    def test_ambiguous_create_retry_patches_current_edits_without_allocating_again(self):
        result = self.evaluate(["createOfficialApplicationFromCompose"], '''
          const calls=[], numberInput={value:""};
          const composeCompanyForOfficialApplication=()=>({id:"TEST-CO"});
          const ensureComposeDraftRequestId=()=>"OD-00000000-0000-4000-8000-000000000001";
          const activeUnit=()=>"測試部門", officialComposeMetadata=()=>({});
          const placements={large:{},small:{}};
          global.document={querySelector:s=>s==="#dispatchNo"?numberInput:{files:[]}};
          const backendRequest=async(path,options)=>{
            calls.push({path,method:options.method,payload:JSON.parse(options.body)});
            return {id:"OD-TEST",current_status:"draft",dispatch_no:"歲悅字第1150908001號",create_replayed:calls.length===1};
          };
          const data={outputMode:"electronic",dispatchDate:"2026-09-16",companyName:"測試公司",subject:"重試前修改的主旨",body:"說明",documentCategory:"合作意向書",approvalFlowNodes:[],sealPlacements:placements};
          (async()=>{const doc={id:"LOCAL-TEST"};await createOfficialApplicationFromCompose(doc,data,{submit:false});console.log(JSON.stringify({calls,doc,number:numberInput.value}));})();
        ''')
        self.assertEqual([call["method"] for call in result["calls"]], ["POST", "PATCH"])
        self.assertEqual(result["calls"][1]["path"], "/official-documents/OD-TEST")
        self.assertEqual(result["calls"][1]["payload"]["subject"], "重試前修改的主旨")
        self.assertEqual(result["calls"][1]["payload"]["dispatch_date"], "2026-09-16")
        self.assertEqual(result["number"], "歲悅字第1150908001號")

    def test_date_output_and_retry_id_survive_autosave_reopen_and_pdf_payload(self):
        snapshot = function(self.js, "composeRawSnapshot")
        self.assertIn("draftRequestId: composeDraftRequestId", snapshot)
        restore = function(self.js, "restoreComposeAutosave")
        self.assertIn("snapshot.draftRequestId", restore)
        correction = function(self.js, "beginComposeOfficialCorrection")
        for text in ("item.dispatch_no", "item.dispatch_date", "item.output_mode"):
            self.assertIn(text, correction)
        payload = function(self.js, "backendPdfPayload")
        self.assertIn("dispatch_date: doc.dispatchDate", payload)
        self.assertIn('output_mode: doc.outputMode || "physical"', payload)
        preview = function(self.js, "renderOfficialDraftPageHtml")
        self.assertIn("data.dispatchDate", preview)
        self.assertNotIn("const today = new Date()", preview)

    def test_new_workflow_failures_have_actionable_messages(self):
        messages = function(self.js, "friendlyBackendErrorMessage")
        for code in ("official_document_numbering_unavailable", "official_document_number_immutable",
                     "official_document_output_mode_locked", "official_dispatch_date_invalid",
                     "official_document_electronic_source_invalid"):
            self.assertIn(code + ":", messages)
        self.assertNotIn("所有發文都必須依文件類型完成用印", messages)

    def test_approved_electronic_download_uses_locked_file_not_newer_draft(self):
        result = self.evaluate(["officialIsElectronicCompose", "officialApplicationFiles", "latestOfficialStampedFile", "renderOfficialFinalStampedDownload"], '''
          const escapeDraftHtml=String;
          const item={id:"DOC",output_mode:"electronic",source_type:"blank_editor",document_type:"outgoing_official_document",requires_stamp:false,
            stamped_file_id:"LOCKED",files:[{id:"LOCKED",file_type:"generated_pdf",version:1,file_name:"approved.pdf"},{id:"NEW-DRAFT",file_type:"generated_pdf",version:2}]};
          console.log(JSON.stringify({chosen:latestOfficialStampedFile(item)?.id,html:renderOfficialFinalStampedDownload(item),
            missing:latestOfficialStampedFile({...item,stamped_file_id:"MISSING"}),unlocked:latestOfficialStampedFile({...item,stamped_file_id:""}),
            uploaded:latestOfficialStampedFile({...item,source_type:"uploaded_pdf"})}));
        ''')
        self.assertEqual(result["chosen"], "LOCKED")
        self.assertIsNone(result["missing"])
        self.assertIsNone(result["unlocked"])
        self.assertIsNone(result["uploaded"])
        self.assertIn('data-official-download="LOCKED"', result["html"])
        self.assertIn("下載已核准電子公文", result["html"])
        self.assertNotIn("最終用印檔", result["html"])

    def test_electronic_dispatch_does_not_report_missing_stamped_pdf(self):
        result = self.evaluate(["officialIsElectronicCompose", "officialApplicationFiles", "latestOfficialStampedFile", "officialApplicationSummary", "officialDispatchReadinessTask"], '''
          const officialDispatchRecord=()=>({proof_file_id:"PROOF"}),officialStatusLabel=s=>s;
          const officialDispatchMethodLabels={email_by_general_affairs:"Email"};
          const officialDispatchMethodNeedsExternalNumber=()=>false, officialDispatchMethodNeedsProof=()=>true;
          const item={id:"DOC",output_mode:"electronic",source_type:"blank_editor",document_type:"outgoing_official_document",requires_stamp:false,
            dispatch_method:"email_by_general_affairs",current_status:"pending_general_affairs_dispatch",stamped_file_id:"LOCKED",files:[{id:"LOCKED",file_type:"generated_pdf"}]};
          console.log(JSON.stringify({summary:officialApplicationSummary(item),task:officialDispatchReadinessTask(item)}));
        ''')
        self.assertFalse(result["summary"]["hasStampedPdf"])
        self.assertTrue(result["summary"]["hasFinalPdf"])
        self.assertEqual(result["task"]["severity"], "wait")
        self.assertNotIn("缺已用印", result["task"]["evidence"])
        self.assertIn("已核准電子公文", result["task"]["body"])


if __name__ == "__main__":
    unittest.main()
