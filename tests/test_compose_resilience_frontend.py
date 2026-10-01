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
      const flushComposeInputUpdates=()=>true,composeInputIsComposing=()=>false;
      let composeCloudTimer=null,composeCloudOperation=null,composeCloudDraftId="OD-00000000-0000-4000-8000-000000000001",composeCloudConflict=false,composeSaveState={},authState={token:"fixture"},scope="A",nextSnapshot={values:{"#subject":"草稿"}};
      const composeCloudRevisions=new Map(),composeCloudSavedSnapshots=new Map();
      const refreshComposeCloudDraftCount=async()=>{},refreshComposeCloudDrafts=async()=>{},renderComposeDraftCount=()=>{};
      let activeRouteTarget="compose";
      const composeRequestScope=()=>scope,composeRawSnapshot=()=>nextSnapshot,composeSnapshotHasMeaningfulContent=()=>true,renderComposeSaveStatus=()=>{};
      const writeComposeAutosaveRaw=()=>true;
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
          let composeOfficialContentRevision=2,composeCloudDraftId="";const composeRequestScope=()=>"same",calls=[];
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
          const composeLocalUnsyncedDraft=()=>null,preserveCurrentComposeBeforeDraftSwitch=async()=>true,setView=()=>{};
          const pendingComposeArchiveForDraft=()=>null;
          const composeCloudDraftsError=false,composeCloudDraftsLoading=false;
          let composeAutosaveRestoredForIdentity="A",composeCloudDraftId="A";
          const composeAutosaveStorageKey="fixture",composeCloudRevisions=new Map(),composeCloudSavedSnapshots=new Map();
          const writeComposeAutosaveRaw=()=>true;
          global.document={querySelector:k=>k==="#attachments"?oldFiles:k==="#composeAttachmentUploadStatus"?status:{value:"B"}};
          global.window={confirm:()=>true};global.localStorage={setItem:()=>{}};
        '''
        value = self.run_js(["loadComposeCloudDraft"], setup, '''await loadComposeCloudDraft("B");console.log(JSON.stringify({fileValue:oldFiles.value,cleared:status.cleared,id:composeCloudDraftId,revision:composeCloudRevisions.get("B")}));''')
        self.assertEqual(value, {"fileValue": "", "cleared": True, "id": "B", "revision": 4})

    def test_draft_badge_counts_local_only_without_double_counting_cloud_edits(self):
        setup = '''
          let composeCloudDraftCount=3,composeCloudProbeId="",composeCloudProbeExists=null;
          const composeCloudRows=[];let local={snapshot:{cloudDraftId:"OD-A"},cloudRevision:4,needsCloudSync:true};
          const pendingComposeArchives=()=>[];
          const item={label:"",setAttribute(_,value){this.label=value}},badge={hidden:true,textContent:"",closest:()=>item};
          const document={querySelector:()=>badge},composeLocalUnsyncedDraft=()=>local;
        '''
        value = self.run_js(["composeDraftCountState", "renderComposeDraftCount"], setup, '''
          renderComposeDraftCount();const existing={count:badge.textContent,label:item.label};
          local={snapshot:{},cloudRevision:null,needsCloudSync:true};renderComposeDraftCount();
          const localOnly={count:badge.textContent,label:item.label};
          local={snapshot:{cloudDraftId:"OD-B"},cloudRevision:null,needsCloudSync:true};renderComposeDraftCount();
          const pending={hidden:badge.hidden,label:item.label};
          composeCloudProbeId="OD-B";composeCloudProbeExists=false;renderComposeDraftCount();
          const probedMissing={count:badge.textContent,label:item.label};
          composeCloudProbeExists=true;renderComposeDraftCount();
          const probedPresent={count:badge.textContent,label:item.label};
          composeCloudDraftCount=0;local=null;renderComposeDraftCount();
          console.log(JSON.stringify({existing,localOnly,pending,probedMissing,probedPresent,empty:{hidden:badge.hidden,label:item.label}}));
        ''')
        self.assertEqual(value, {
            "existing": {"count": "3", "label": "草稿編輯，3 份未完成草稿"},
            "localOnly": {"count": "4", "label": "草稿編輯，4 份未完成草稿"},
            "pending": {"hidden": True, "label": "草稿編輯，數量更新中"},
            "probedMissing": {"count": "4", "label": "草稿編輯，4 份未完成草稿"},
            "probedPresent": {"count": "3", "label": "草稿編輯，3 份未完成草稿"},
            "empty": {"hidden": True, "label": "草稿編輯，0 份未完成草稿"},
        })

    def test_draft_switch_stops_if_current_changes_cannot_be_saved(self):
        setup = '''
          let composeCloudOperation=null,composeCloudDraftId="OD-A",notice="";
          const document={querySelector:()=>({files:[]})};
          const composeInputIsComposing=()=>false,flushComposeInputUpdates=()=>true;
          const composeRawSnapshot=()=>({values:{"#subject":"尚未保存"}}),composeSnapshotHasMeaningfulContent=()=>true;
          const composeCloudSavedSnapshots=new Map(),saveComposeCloudDraft=async()=>null,showToast=value=>{notice=value};
        '''
        value = self.run_js(["preserveCurrentComposeBeforeDraftSwitch"], setup, '''
          const allowed=await preserveCurrentComposeBeforeDraftSwitch();console.log(JSON.stringify({allowed,notice}));
        ''')
        self.assertEqual(value["allowed"], False)
        self.assertIn("已取消切換", value["notice"])

    DRAFT_FETCH_SETUP = '''
      let scope="account-A",activeRouteTarget="drafts";
      const authState={token:"fixture"},composeCloudIdentityScope=()=>scope,composeLocalUnsyncedDraft=()=>null;
      let composeCloudRows=[{id:"OD-old",revision:1,snapshot:{values:{"#subject":"已載入"}}}],composeCloudDraftCount=1;
      let composeCloudDraftHasMore=false,composeCloudDraftsLoading=false,composeCloudDraftsError=false;
      let composeCloudProbeId="",composeCloudProbeExists=null,composeCloudListGeneration=0,composeCloudCountGeneration=0;
      let composeCloudListRequest=null,composeCloudCountRequest=null;
      let renders=0;const renderComposeDraftList=()=>{renders++},renderComposeDraftCount=()=>{};
      let resolveList,rejectList,resolveCount,rejectCount;
      const backendRequest=(path)=>new Promise((yes,no)=>{
        if(path.startsWith("/compose-drafts/count")){resolveCount=yes;rejectCount=no}
        else {resolveList=yes;rejectList=no}
      });
    '''

    def test_draft_refresh_waits_for_list_and_exact_count(self):
        value = self.run_js(["refreshComposeCloudDraftCount", "refreshComposeCloudDrafts"], self.DRAFT_FETCH_SETUP, '''
          let settled=false;const pending=refreshComposeCloudDrafts().then(result=>{settled=true;return result});
          resolveList([{id:"OD-new",revision:2,snapshot:{values:{"#subject":"新版"}}}]);
          await new Promise(setImmediate);
          const beforeCount={settled,loading:composeCloudDraftsLoading,rows:composeCloudRows[0].id};
          resolveCount({count:5});const success=await pending;
          console.log(JSON.stringify({beforeCount,success,loading:composeCloudDraftsLoading,count:composeCloudDraftCount,rows:composeCloudRows[0].id,error:composeCloudDraftsError}));
        ''')
        self.assertEqual(value, {"beforeCount": {"settled": False, "loading": True, "rows": "OD-old"},
                                 "success": True, "loading": False, "count": 5, "rows": "OD-new", "error": False})

    def test_failed_draft_refresh_preserves_cached_rows_and_reports_failure(self):
        value = self.run_js(["refreshComposeCloudDraftCount", "refreshComposeCloudDrafts"], self.DRAFT_FETCH_SETUP, '''
          const first=refreshComposeCloudDrafts();rejectList(new Error("offline"));resolveCount({count:1});
          const listFailure=await first;
          const cachedAfterListFailure=composeCloudRows[0].id;
          const second=refreshComposeCloudDrafts();resolveList([{id:"OD-new",revision:2,snapshot:{values:{"#subject":"新版"}}}]);rejectCount(new Error("offline"));
          const countFailure=await second;
          console.log(JSON.stringify({listFailure,cachedAfterListFailure,countFailure,updatedRow:composeCloudRows[0].id,count:composeCloudDraftCount,error:composeCloudDraftsError}));
        ''')
        self.assertEqual(value, {"listFailure": False, "cachedAfterListFailure": "OD-old", "countFailure": False,
                                 "updatedRow": "OD-new", "count": None, "error": True})

    def test_concurrent_draft_refreshes_share_one_list_and_count_read(self):
        setup = self.DRAFT_FETCH_SETUP.replace('const backendRequest=(path)=>new Promise((yes,no)=>{',
                                               'let calls=0;const backendRequest=(path)=>new Promise((yes,no)=>{calls++;')
        value = self.run_js(["refreshComposeCloudDraftCount", "refreshComposeCloudDrafts"], setup, '''
          const first=refreshComposeCloudDrafts(),second=refreshComposeCloudDrafts();
          resolveList([{id:"OD-new",revision:2,snapshot:{values:{"#subject":"新版"}}}]);resolveCount({count:1});
          const results=await Promise.all([first,second]);
          console.log(JSON.stringify({results,calls,rows:composeCloudRows.length,error:composeCloudDraftsError}));
        ''')
        self.assertEqual(value, {"results": [True, True], "calls": 2, "rows": 1, "error": False})

    def test_draft_cards_remain_clickable_and_keep_focus_across_refresh_status(self):
        setup = '''
          let composeCloudRows=[{id:"OD-1",revision:2,updatedAt:"2026-10-01T00:00:00Z",snapshot:{values:{"#subject":"去識別草稿"}}}];
          let composeCloudDraftsLoading=false,composeCloudDraftsError=false,composeCloudDraftHasMore=false,composeCloudDraftCount=1;
          let pending=false,writes=0;
          const host={dataset:{},_html:"",set innerHTML(value){writes++;this._html=value},get innerHTML(){return this._html}};
          const status={},localCard={},refresh={setAttribute(name,value){this[name]=value}},more={};
          const nodes={"#composeDraftList":host,"#composeDraftListStatus":status,"#composeLocalDraftCard":localCard,
            "#composeDraftLoadMoreBtn":more,"#composeDraftRefreshBtn":refresh};
          global.document={querySelector:key=>nodes[key]};
          const composeDraftCountState=()=>({local:null,total:1,uncertain:false});
          const formatComposeDraftUpdatedAt=()=>"2026/10/1",escapeHtml=value=>String(value);
          const pendingComposeArchiveForDraft=()=>pending?{draftId:"OD-1"}:null;
          const pendingComposeArchives=()=>pending?[{draftId:"OD-1",officialDocumentId:"OD-official"}]:[];
          const composeSubmittedLocalRecovery=()=>null;
        '''
        value = self.run_js(["renderComposeDraftList"], setup, '''
          renderComposeDraftList();const initial=host.innerHTML;
          composeCloudDraftsLoading=true;renderComposeDraftList();const during={writes,html:host.innerHTML,status:status.textContent};
          composeCloudDraftsLoading=false;composeCloudDraftsError=true;renderComposeDraftList();
          const failed={writes,html:host.innerHTML,status:status.textContent};
          pending=true;renderComposeDraftList();const archived=host.innerHTML;
          console.log(JSON.stringify({initialClickable:initial.includes("data-compose-draft-id")&&!initial.includes("disabled"),
            duringSame:during.html===initial,duringWrites:during.writes,duringStatus:during.status,
            failedSame:failed.html===initial,failedWrites:failed.writes,failedStatus:failed.status,
            archivedRetry:archived.includes("data-compose-archive-retry")&&!archived.includes("data-compose-draft-id")}));
        ''')
        self.assertTrue(value["initialClickable"])
        self.assertTrue(value["duringSame"])
        self.assertEqual(value["duringWrites"], 1)
        self.assertIn("仍可編輯", value["duringStatus"])
        self.assertTrue(value["failedSame"])
        self.assertEqual(value["failedWrites"], 1)
        self.assertIn("更新失敗", value["failedStatus"])
        self.assertTrue(value["archivedRetry"])

    def test_pending_archive_without_cloud_row_still_has_cleanup_card_not_local_editor(self):
        setup = '''
          let composeCloudRows=[],composeCloudDraftsLoading=false,composeCloudDraftsError=true,composeCloudDraftHasMore=false,composeCloudDraftCount=3;
          const marker={draftId:"OD-submitted",officialDocumentId:"OD-official"};
          const pendingComposeArchives=()=>[marker],pendingComposeArchiveForDraft=()=>null;
          const composeSubmittedLocalRecovery=()=>null;
          const composeLocalUnsyncedDraft=()=>({snapshot:{cloudDraftId:"OD-submitted",draftRequestId:"OD-official",values:{"#subject":"已送簽"}},cloudRevision:0});
          const composeCloudProbeId="",composeCloudProbeExists=null;
          const host={dataset:{},innerHTML:""},status={},localCard={},more={},refresh={setAttribute(){}};
          const nodes={"#composeDraftList":host,"#composeDraftListStatus":status,"#composeLocalDraftCard":localCard,
            "#composeDraftLoadMoreBtn":more,"#composeDraftRefreshBtn":refresh};
          global.document={querySelector:key=>nodes[key]};const escapeHtml=value=>String(value),formatComposeDraftUpdatedAt=()=>"";
        '''
        value = self.run_js(["composePendingArchiveMatchesSnapshot", "composeDraftCountState", "renderComposeDraftList"], setup, '''
          renderComposeDraftList();
          console.log(JSON.stringify({localHidden:localCard.hidden,retry:host.innerHTML.includes("data-compose-archive-retry"),editable:host.innerHTML.includes("data-compose-draft-id"),count:composeDraftCountState().total}));
        ''')
        self.assertEqual(value, {"localHidden": True, "retry": True, "editable": False, "count": None})

    def test_submitted_other_tab_text_has_explicit_new_draft_recovery_not_badge_count(self):
        setup = '''
          let recovery={updatedAt:"2026-10-02T00:00:00Z",snapshot:{values:{"#subject":"已送簽後的新文字"}}};
          const composeSubmittedLocalRecovery=()=>recovery,composeCloudRows=[],pendingComposeArchives=()=>[];
          const pendingComposeArchiveForDraft=()=>null,composeCloudDraftsLoading=false,composeCloudDraftsError=false;
          const composeCloudDraftHasMore=false,composeCloudDraftCount=0;
          let writes=0;const host={dataset:{},_html:"",set innerHTML(value){writes++;this._html=value},get innerHTML(){return this._html}};
          const status={},localCard={},more={},refresh={setAttribute(){}};
          const nodes={"#composeDraftList":host,"#composeDraftListStatus":status,"#composeLocalDraftCard":localCard,
            "#composeDraftLoadMoreBtn":more,"#composeDraftRefreshBtn":refresh};
          global.document={querySelector:key=>nodes[key]};
          const composeDraftCountState=()=>({local:null,total:0,uncertain:false,pendingCleanup:0});
          const escapeHtml=value=>String(value),formatComposeDraftUpdatedAt=()=>"";
        '''
        value = self.run_js(["renderComposeDraftList"], setup, '''
          renderComposeDraftList();const before={visible:host.innerHTML.includes("data-compose-recover-submitted"),
            wording:host.innerHTML.includes("已送簽文件仍有本機內容")&&host.innerHTML.includes("若需保留變更，可另存為新草稿")&&host.innerHTML.includes("原公文不會變更"),
            editable:host.innerHTML.includes("data-compose-draft-id"),status:status.textContent,writes};
          recovery=null;renderComposeDraftList();
          console.log(JSON.stringify({before,cleared:!host.innerHTML.includes("data-compose-recover-submitted"),writes}));
        ''')
        self.assertEqual(value["before"], {"visible": True, "wording": True, "editable": False,
                                           "status": "目前沒有未完成草稿。", "writes": 1})
        self.assertTrue(value["cleared"])
        self.assertEqual(value["writes"], 2)
        source = (ROOT / "app.js").read_text()
        self.assertIn('event.target.closest("[data-compose-recover-submitted]")', source)
        self.assertIn('void resumeSubmittedComposeLocalAsNewDraft();', source)

    def test_unloaded_pending_archive_never_overstates_unfinished_badge(self):
        setup = '''
          const composeCloudRows=[],composeCloudDraftCount=3,composeCloudProbeId="",composeCloudProbeExists=null;
          const composeLocalUnsyncedDraft=()=>null,pendingComposeArchives=()=>[{draftId:"OD-submitted",officialDocumentId:"OD-official"}];
          const item={setAttribute(name,value){this[name]=value}},badge={closest:()=>item};
          global.document={querySelector:()=>badge};
        '''
        value = self.run_js(["composeDraftCountState", "renderComposeDraftCount"], setup, '''
          renderComposeDraftCount();console.log(JSON.stringify({count:composeDraftCountState().total,hidden:badge.hidden,label:item["aria-label"]}));
        ''')
        self.assertEqual(value, {"count": None, "hidden": True,
                                 "label": "草稿編輯，已送簽草稿待清理，未完成數量暫時無法確認"})

    DRAFT_ROUTE_SETUP = '''
      let scope="A",authenticated=true,activeRouteTarget="drafts",workspaceRefreshRequest=null;
      const authState={token:"fixture"},frontendSessionScope=()=>scope,hasAuthenticatedBackendSession=()=>authenticated;
      const routeBackendDataLoaded=new Set(),routeBackendDataRequests=new Map(),routeBackendDataErrors=new Map(),routeBackendDataSyncedAt=new Map();
      let routeBackendDataScope="A",headerBackendSyncState={status:"idle",syncedAt:""};
      const renderWorkspaceLoadStatus=()=>{},updateHeaderStatus=()=>{},resetRouteBackendData=()=>{};
      let finish;const refreshComposeCloudDrafts=()=>new Promise(yes=>{finish=yes});
    '''

    def test_drafts_route_reports_synced_only_after_both_reads_and_failure_is_false(self):
        value = self.run_js(["loadRouteBackendData"], self.DRAFT_ROUTE_SETUP, '''
          const first=loadRouteBackendData("drafts",true,{force:true});
          const pendingStatus=headerBackendSyncState.status;
          finish(false);const failure=await first;
          const failedStatus=headerBackendSyncState.status;
          const second=loadRouteBackendData("drafts",true,{force:true});
          finish(true);const success=await second;
          console.log(JSON.stringify({pendingStatus,failure,failedStatus,success,finalStatus:headerBackendSyncState.status,loaded:routeBackendDataLoaded.has("drafts")}));
        ''')
        self.assertEqual(value, {"pendingStatus": "syncing", "failure": False, "failedStatus": "error",
                                 "success": True, "finalStatus": "synced", "loaded": True})

    def test_stale_scope_route_load_is_not_reported_as_success(self):
        value = self.run_js(["loadRouteBackendData"], self.DRAFT_ROUTE_SETUP, '''
          const pending=loadRouteBackendData("drafts",true,{force:true});scope="B";finish(true);
          const result=await pending;console.log(JSON.stringify({result,synced:headerBackendSyncState.status==="synced"}));
        ''')
        self.assertEqual(value, {"result": False, "synced": False})

    def test_workspace_refresh_does_not_toast_success_for_false_route_read(self):
        setup = '''
          let activeRouteTarget="drafts",workspaceRefreshRequest=null,headerBackendSyncState={status:"idle",syncedAt:""};
          const authState={token:"fixture"},hasAuthenticatedBackendSession=()=>true,frontendSessionScope=()=>"A";
          let finish;const loadRouteBackendData=()=>new Promise(yes=>{finish=yes});
          const syncNotificationsFromBackend=async()=>true,routeBackendDataErrors=new Map(),routeBackendDataLoaded=new Set();
          const renderWorkspaceLoadStatus=()=>{},updateHeaderStatus=()=>{};let toast="";const showToast=value=>{toast=value};
          const button={setAttribute(){},removeAttribute(){}};
          global.document={querySelector:()=>button};
        '''
        value = self.run_js(["refreshCurrentWorkspace"], setup, '''
          const pending=refreshCurrentWorkspace();const before=headerBackendSyncState.status;
          finish(false);const result=await pending;
          console.log(JSON.stringify({before,result,status:headerBackendSyncState.status,toast,button:button.textContent}));
        ''')
        self.assertEqual(value["before"], "syncing")
        self.assertFalse(value["result"])
        self.assertEqual(value["status"], "error")
        self.assertIn("失敗", value["toast"])
        self.assertEqual(value["button"], "重新整理")

    SAME_DRAFT_SETUP = '''
      const id="OD-00000000-0000-4000-8000-000000000001";
      const authState={user:{id:"U",company_id:"CO"}},row={id,revision:4,updatedAt:"2026-10-01T00:00:00Z",snapshot:{userId:"U",companyId:"CO",values:{"#subject":"雲端新版"}}};
      const composeCloudRows=[row],composeCloudRevisions=new Map([[id,2]]);
      let current={values:{"#subject":"舊版"}},restored=0,route="",notice="";
      const composeCloudSavedSnapshots=new Map([[id,JSON.stringify(current)]]),composeRawSnapshot=()=>current;
      let composeCloudDraftId=id,composeCloudOperation=null,composeCloudConflict=false,composeAutosaveRestoredForIdentity="";
      const composeLocalUnsyncedDraft=()=>null,pendingComposeArchiveForDraft=()=>null;
      const composeInputIsComposing=()=>false,flushComposeInputUpdates=()=>true,composeSnapshotHasMeaningfulContent=()=>true;
      const resetComposeAsyncScope=()=>{},restoreComposeAutosave=saved=>{restored++;current=saved.snapshot};
      const setView=value=>{route=value},showToast=value=>{notice=value};
      const composeAutosaveStorageKey="fixture";global.localStorage={setItem:()=>{}};
      const writeComposeAutosaveRaw=()=>true;
      const files={value:"",files:[]};global.document={querySelector:key=>key==="#attachments"?files:key==="#composeAttachmentUploadStatus"?{replaceChildren:()=>{}}:null};
    '''

    def test_same_draft_newer_revision_restores_only_when_current_editor_is_clean(self):
        value = self.run_js(["loadComposeCloudDraft"], self.SAME_DRAFT_SETUP, '''
          await loadComposeCloudDraft(id);
          console.log(JSON.stringify({restored,revision:composeCloudRevisions.get(id),route,subject:current.values["#subject"]}));
        ''')
        self.assertEqual(value, {"restored": 1, "revision": 4, "route": "compose", "subject": "雲端新版"})

    def test_same_draft_newer_revision_never_overwrites_unsaved_edits_or_file(self):
        value = self.run_js(["loadComposeCloudDraft"], self.SAME_DRAFT_SETUP, '''
          current={values:{"#subject":"本機未存修改"}};await loadComposeCloudDraft(id);
          const dirty={restored,route,notice,subject:current.values["#subject"]};
          current={values:{"#subject":"舊版"}};files.files=[{name:"unuploaded.pdf"}];await loadComposeCloudDraft(id);
          console.log(JSON.stringify({dirty,fileBlocked:restored===0&&files.files.length===1,notice}));
        ''')
        self.assertEqual(value["dirty"]["restored"], 0)
        self.assertEqual(value["dirty"]["subject"], "本機未存修改")
        self.assertIn("尚未保存", value["dirty"]["notice"])
        self.assertTrue(value["fileBlocked"])


if __name__ == "__main__": unittest.main()
