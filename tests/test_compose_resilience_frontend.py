"""Execute real UI functions with deferred transport; no string-only assertions."""
import json
import subprocess
import unittest
from pathlib import Path
from tests.test_compose_output_contract import function

ROOT = Path(__file__).resolve().parents[1]


class ComposeResilienceFrontendTest(unittest.TestCase):
    def run_js(self, functions, setup, body):
        js = (ROOT / "app.js").read_text()
        code = "\n".join(function(js, name) for name in functions)
        result = subprocess.run(["node", "-e", code + "\n" + setup + "\n(async()=>{" + body + "})().catch(e=>{console.error(e);process.exit(1)});"], text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    AI = ["composeAiContext", "generateAiDraft", "renderComposeAiActions", "applyComposeAiSuggestion", "undoComposeAiSuggestion", "discardComposeAiSuggestion"]
    AI_SETUP = '''
      let composeAiOperation=null, composeAiSuggestion=null, composeAiUndo=null, composeAiReview=null, scope="user-A", dirty=0;
      const nodes={"#subject":{value:"原主旨"},"#bodyText":{value:"原說明"},"#documentPurpose":{value:"六字以上的公文用途"},"#generateFromPurposeBtn":{textContent:"AI產生公文主旨與說明"},"#documentPurposeHint":{},"#composeAiSuggestion":{},"#composeAiSuggestionSubject":{},"#composeAiSuggestionBody":{},"#composeAiUndoBtn":{}};
      global.document={querySelector:key=>nodes[key]};global.window={confirm:()=>true};
      const composeRequestScope=()=>scope, hasMinimumText=()=>true, setAiDraftStatus=()=>{}, composePayload=()=>({}), activeRole=()=>"員工", addDispatchAudit=()=>{},showToast=()=>{},markDraftDirty=()=>{dirty++};
      let resolve,reject;const backendRequest=()=>new Promise((yes,no)=>{resolve=yes;reject=no});
    '''

    def test_ai_does_not_overwrite_edits_while_waiting(self):
        value = self.run_js(self.AI, self.AI_SETUP, '''const pending=generateAiDraft();nodes["#subject"].value="人工新版";resolve({subject:"AI主旨",body:"AI說明"});await pending;console.log(JSON.stringify({subject:nodes["#subject"].value,suggestion:composeAiSuggestion.subject,visible:!nodes["#composeAiSuggestion"].hidden}));''')
        self.assertEqual(value, {"subject": "人工新版", "suggestion": "AI主旨", "visible": True})

    def test_ai_explicit_apply_and_undo_keep_last_manual_text(self):
        value = self.run_js(self.AI, self.AI_SETUP, '''const p=generateAiDraft();nodes["#subject"].value="人工新版";resolve({subject:"AI主旨",body:"AI說明"});await p;applyComposeAiSuggestion();const applied=nodes["#subject"].value;undoComposeAiSuggestion();console.log(JSON.stringify({applied,restored:nodes["#subject"].value,body:nodes["#bodyText"].value}));''')
        self.assertEqual(value, {"applied": "AI主旨", "restored": "人工新版", "body": "原說明"})

    def test_ai_unchanged_inputs_are_applied_and_undoable(self):
        value = self.run_js(self.AI, self.AI_SETUP, '''const p=generateAiDraft();resolve({subject:"AI主旨",body:"AI說明"});await p;console.log(JSON.stringify({subject:nodes["#subject"].value,undo:composeAiUndo.subject,busy:nodes["#generateFromPurposeBtn"].disabled}));''')
        self.assertEqual(value, {"subject": "AI主旨", "undo": "原主旨", "busy": False})

    def test_ai_late_account_response_is_ignored(self):
        value = self.run_js(self.AI, self.AI_SETUP, '''const p=generateAiDraft();scope="user-B";composeAiOperation={};resolve({subject:"前帳號文字",body:"前帳號文字"});await p;console.log(JSON.stringify({subject:nodes["#subject"].value,suggestion:composeAiSuggestion,dirty}));''')
        self.assertEqual(value, {"subject": "原主旨", "suggestion": None, "dirty": 0})

    def test_company_change_ignores_old_response_but_releases_busy_button(self):
        value = self.run_js(self.AI, self.AI_SETUP, '''const p=generateAiDraft();scope="company-B";resolve({subject:"前公司文字",body:"前公司文字"});await p;console.log(JSON.stringify({subject:nodes["#subject"].value,suggestion:composeAiSuggestion,busy:nodes["#generateFromPurposeBtn"].disabled,operation:composeAiOperation}));''')
        self.assertEqual(value, {"subject": "原主旨", "suggestion": None, "busy": False, "operation": None})

    def test_undo_refusal_preserves_post_ai_manual_changes(self):
        value = self.run_js(self.AI, self.AI_SETUP, '''const p=generateAiDraft();resolve({subject:"AI主旨",body:"AI說明"});await p;nodes["#subject"].value="最後人工修改";window.confirm=()=>false;undoComposeAiSuggestion();console.log(JSON.stringify({subject:nodes["#subject"].value,undo:!!composeAiUndo}));''')
        self.assertEqual(value, {"subject": "最後人工修改", "undo": True})

    def test_ai_passes_document_date_issuer_and_attachment_description(self):
        setup = self.AI_SETUP.replace('composePayload=()=>({})', 'composePayload=()=>({dispatchDate:"2026-09-12",companyName:"測試公司",attachmentDetails:"計畫1份",attachments:["計畫.pdf"]})').replace('const backendRequest=()=>new Promise', 'let requestPayload;const backendRequest=(path,options)=>{requestPayload=JSON.parse(options.body);return new Promise').replace('{resolve=yes;reject=no});', '{resolve=yes;reject=no})};')
        value = self.run_js(self.AI, setup, '''const p=generateAiDraft();resolve({subject:"正式主旨",body:"正式說明"});await p;console.log(JSON.stringify(requestPayload));''')
        self.assertEqual(value["documentDate"], "2026-09-12")
        self.assertEqual(value["issuerName"], "測試公司")
        self.assertEqual(value["attachmentDetails"], "計畫1份")
        self.assertEqual(value["attachments"], ["計畫.pdf"])

    def test_ai_warnings_do_not_auto_apply_and_are_rendered_as_text(self):
        setup = self.AI_SETUP + '''
          nodes["#composeAiReview"]={hidden:true};
          nodes["#composeAiReviewWarnings"]={replaceChildren:(...items)=>{nodes["#composeAiReviewWarnings"].items=items}};
          document.createElement=()=>({textContent:""});
        '''
        value = self.run_js(self.AI, setup, '''const p=generateAiDraft();resolve({subject:"待核對主旨",body:"待核對說明",warnings:["引用日期晚於發文日期", "<img src=x onerror=alert(1)>"]});await p;console.log(JSON.stringify({subject:nodes["#subject"].value,visible:!nodes["#composeAiReview"].hidden,warnings:nodes["#composeAiReviewWarnings"].items.map(x=>x.textContent),suggestion:composeAiSuggestion.subject}));''')
        self.assertEqual(value["subject"], "原主旨")
        self.assertTrue(value["visible"])
        self.assertEqual(value["warnings"], ["引用日期晚於發文日期", "<img src=x onerror=alert(1)>"])
        self.assertEqual(value["suggestion"], "待核對主旨")

    def test_ai_changed_context_does_not_auto_apply(self):
        setup = self.AI_SETUP.replace('composePayload=()=>({})', 'composePayload=()=>({dispatchDate:documentDate})') + 'let documentDate="2026-09-12";'
        value = self.run_js(self.AI, setup, '''const p=generateAiDraft();documentDate="2026-12-12";resolve({subject:"舊日期主旨",body:"舊日期說明"});await p;console.log(JSON.stringify({subject:nodes["#subject"].value,suggestion:composeAiSuggestion.subject}));''')
        self.assertEqual(value, {"subject": "原主旨", "suggestion": "舊日期主旨"})

    def test_pending_fallback_is_explicitly_labeled_not_ai(self):
        value = self.run_js(self.AI, self.AI_SETUP, '''nodes["#composeAiSuggestionReason"]={};const p=generateAiDraft();resolve({subject:"本機主旨",body:"本機說明",usedOpenAI:false,notice:"本機規則（非 AI 生成）",warnings:["請核對日期"]});await p;console.log(JSON.stringify({hint:nodes["#documentPurposeHint"].textContent,subject:nodes["#subject"].value,reason:nodes["#composeAiSuggestionReason"].textContent}));''')
        self.assertEqual(value["hint"], "本機規則（非 AI 生成）")
        self.assertEqual(value["subject"], "原主旨")
        self.assertIn("非 AI 生成", value["reason"])

    def test_ai_warning_draft_can_be_explicitly_applied_then_undone(self):
        value = self.run_js(self.AI, self.AI_SETUP, '''const p=generateAiDraft();resolve({subject:"AI主旨",body:"AI說明",warnings:["請核對日期"]});await p;applyComposeAiSuggestion();const applied=nodes["#subject"].value,warningCount=composeAiReview.warnings.length;undoComposeAiSuggestion();console.log(JSON.stringify({applied,warningCount,restored:nodes["#subject"].value,review:composeAiReview}));''')
        self.assertEqual(value, {"applied": "AI主旨", "warningCount": 1, "restored": "原主旨", "review": None})

    def test_discard_clears_suggestion_and_related_warnings(self):
        value = self.run_js(self.AI, self.AI_SETUP, '''const p=generateAiDraft();resolve({subject:"AI主旨",body:"AI說明",warnings:["請核對日期"]});await p;discardComposeAiSuggestion();console.log(JSON.stringify({subject:nodes["#subject"].value,suggestion:composeAiSuggestion,review:composeAiReview}));''')
        self.assertEqual(value, {"subject": "原主旨", "suggestion": None, "review": None})

    CLOUD_SETUP = '''
      let composeCloudTimer=null,composeCloudOperation=null,composeCloudDraftId="OD-00000000-0000-4000-8000-000000000001",composeCloudConflict=false,composeSaveState={},authState={token:"fixture"},scope="A",nextSnapshot={values:{"#subject":"草稿"}};
      const composeCloudRevisions=new Map(),composeCloudSavedSnapshots=new Map();
      const composeRequestScope=()=>scope,composeRawSnapshot=()=>nextSnapshot,composeSnapshotHasMeaningfulContent=()=>true,renderComposeSaveStatus=()=>{};
      let scheduled=0;const scheduleComposeCloudSave=()=>scheduled++;
      global.navigator={onLine:true};let resolve,reject,calls=0;
      const backendRequest=()=>{calls++;return new Promise((yes,no)=>{resolve=yes;reject=no})};
    '''

    def test_cloud_autosave_late_response_does_not_update_other_account(self):
        value = self.run_js(["saveComposeCloudDraft"], self.CLOUD_SETUP, '''const p=saveComposeCloudDraft();scope="B";composeCloudOperation=null;composeSaveState={title:"新帳號"};resolve({revision:7});await p;console.log(JSON.stringify({title:composeSaveState.title,versions:composeCloudRevisions.size,scheduled}));''')
        self.assertEqual(value, {"title": "新帳號", "versions": 0, "scheduled": 0})

    def test_cloud_conflict_retains_input_and_does_not_reschedule(self):
        value = self.run_js(["saveComposeCloudDraft"], self.CLOUD_SETUP, '''const p=saveComposeCloudDraft();reject({status:409});await p;console.log(JSON.stringify({conflict:composeCloudConflict,text:nextSnapshot.values["#subject"],scheduled,versions:composeCloudRevisions.size}));''')
        self.assertEqual(value, {"conflict": True, "text": "草稿", "scheduled": 0, "versions": 0})

    def test_cloud_edits_during_save_schedule_next_version(self):
        value = self.run_js(["saveComposeCloudDraft"], self.CLOUD_SETUP, '''const p=saveComposeCloudDraft();nextSnapshot={values:{"#subject":"更新"}};resolve({revision:3});await p;console.log(JSON.stringify({revision:composeCloudRevisions.get(composeCloudDraftId),scheduled}));''')
        self.assertEqual(value, {"revision": 3, "scheduled": 1})

    def test_cloud_single_flight_and_exact_saved_snapshot_not_reuploaded(self):
        value = self.run_js(["saveComposeCloudDraft"], self.CLOUD_SETUP, '''const a=saveComposeCloudDraft(),b=saveComposeCloudDraft();resolve({revision:1});await Promise.all([a,b]);await saveComposeCloudDraft();console.log(JSON.stringify({calls,revision:composeCloudRevisions.get(composeCloudDraftId)}));''')
        self.assertEqual(value, {"calls": 1, "revision": 1})

    def test_attachment_partial_failure_retry_only_failed_file_same_upload_id(self):
        setup = '''const officialAttachmentUploadCache=new Map();let scope="A",fail=true;const calls=[];const frontendSessionScope=()=>scope,requireInlineJsonUploadSize=()=>{},fileToBase64=async()=>"fixture",escapeHtml=x=>x;global.document={querySelector:()=>({})};const backendRequest=async(path,options)=>{const payload=JSON.parse(options.body);calls.push(payload);if(payload.file_name==="b.txt"&&fail)throw new Error("network");return {file:{id:payload.file_name}}};const files=[new File(["one"],"a.txt",{type:"text/plain"}),new File(["two"],"b.txt",{type:"text/plain"})];'''
        value = self.run_js(["uploadOfficialDocumentAttachments"], setup, '''try{await uploadOfficialDocumentAttachments("D",files)}catch(_){}fail=false;await uploadOfficialDocumentAttachments("D",files);console.log(JSON.stringify({names:calls.map(c=>c.file_name),sameId:calls[1].upload_id===calls[2].upload_id}));''')
        self.assertEqual(value, {"names": ["a.txt", "b.txt", "b.txt"], "sameId": True})

    def test_late_official_save_cannot_rebind_newly_loaded_cloud_draft(self):
        setup = '''
          let scope="draft-A",currentComposeDraftId="A",composeSaveState={title:"A"};
          const dispatchDocs=[{id:"A",status:"草稿",officialDocumentId:"OD-A"}];
          const composeRequestScope=()=>scope, approvalSelectionForSelect=()=>({documentCategory:"合作意向書",approvalRouteCode:"A"}),
            composePayload=()=>({attachments:[],approvalFlowNodes:[],subject:"A"}),isValidComposeDispatchDate=()=>true,
            ensureComposeDraftRequestId=()=>{},writeComposeAutosave=()=>{};
          const composeSealPlacements={large:{},small:{}};
          global.document={querySelector:()=>({value:"2026-09-11"})};
          let reject; const createOfficialApplicationFromCompose=()=>new Promise((_,no)=>{reject=no});
        '''
        value = self.run_js(["performCreateDispatchFromForm"], setup, '''const pending=performCreateDispatchFromForm();scope="draft-B";currentComposeDraftId="B";composeSaveState={title:"B已載入"};reject(new Error("stale response"));await pending;console.log(JSON.stringify({id:currentComposeDraftId,title:composeSaveState.title}));''')
        self.assertEqual(value, {"id": "B", "title": "B已載入"})

    def test_recovered_snapshot_token_is_not_upgraded_by_newer_dashboard_cache(self):
        setup = '''
          let composeOfficialContentRevision=2;const composeRequestScope=()=>"same",calls=[];
          const composeCompanyForOfficialApplication=()=>({id:"CO"}),activeUnit=()=>"fixture",officialComposeMetadata=()=>({});
          global.document={querySelector:()=>({files:[]})};
          const backendRequest=async(path,options)=>{calls.push(JSON.parse(options.body));return{id:"OD-A",dispatch_no:"TEST",content_revision:3}};
          const data={outputMode:"electronic",approvalFlowNodes:[],sealPlacements:{large:{},small:{}}};
        '''
        value = self.run_js(["createOfficialApplicationFromCompose"], setup, '''await createOfficialApplicationFromCompose({id:"A",officialDocumentId:"OD-A",contentRevision:9},data,{submit:false});console.log(JSON.stringify({expected:calls[0].expected_content_revision}));''')
        self.assertEqual(value, {"expected": 2})

    def test_load_cloud_draft_drops_previous_documents_local_file_selection(self):
        setup = '''
          const oldFiles={value:"old-draft.pdf"},status={replaceChildren:()=>{status.cleared=true}};
          const authState={user:{id:"U",company_id:"CO"}};
          const composeCloudRows=[{id:"B",revision:4,snapshot:{userId:"U",companyId:"CO",values:{"#subject":"B"}}}];
          const composeRawSnapshot=()=>({}),composeSnapshotHasMeaningfulContent=()=>true,resetComposeAsyncScope=()=>{},restoreComposeAutosave=()=>{},showToast=()=>{};
          let composeAutosaveRestoredForIdentity="A",composeCloudDraftId="A";
          const composeAutosaveStorageKey="fixture",composeCloudRevisions=new Map(),composeCloudSavedSnapshots=new Map();
          global.document={querySelector:k=>k==="#attachments"?oldFiles:k==="#composeAttachmentUploadStatus"?status:{value:"B"}};
          global.window={confirm:()=>true};global.localStorage={setItem:()=>{}};
        '''
        value = self.run_js(["loadComposeCloudDraft"], setup, '''await loadComposeCloudDraft();console.log(JSON.stringify({fileValue:oldFiles.value,cleared:status.cleared,id:composeCloudDraftId,revision:composeCloudRevisions.get("B")}));''')
        self.assertEqual(value, {"fileValue": "", "cleared": True, "id": "B", "revision": 4})


if __name__ == "__main__": unittest.main()
