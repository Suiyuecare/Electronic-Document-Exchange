"""Post-submit private-draft cleanup is scoped, revision-safe and nonblocking."""
import json
import subprocess
import unittest
from pathlib import Path

from tests.test_compose_output_contract import function


ROOT = Path(__file__).resolve().parents[1]
DRAFT_ID = "OD-00000000-0000-4000-8000-000000000001"
OFFICIAL_ID = "OD-00000000-0000-4000-8000-000000000002"


class ComposeArchiveFrontendTest(unittest.TestCase):
    def run_js(self, functions, setup, body):
        source = (ROOT / "app.js").read_text()
        code = "\n".join(function(source, name) for name in functions)
        result = subprocess.run(
            ["node", "-e", code + "\n" + setup + "\n(async()=>{" + body + "})().catch(e=>{console.error(e);process.exit(1)});"],
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_archive_waits_for_ordinary_save_and_uses_acknowledged_revision(self):
        setup = f'''
          const id="{DRAFT_ID}",officialId="{OFFICIAL_ID}",snapshot={{values:{{"#subject":"去識別函稿"}}}};
          let composeCloudTimer=null,composeCloudDraftId=id,composeCloudConflict=false,resolveSave;
          let composeCloudOperation=new Promise(yes=>{{resolveSave=yes}});
          const composeCloudSavedSnapshots=new Map([[id,JSON.stringify(snapshot)]]),composeCloudRevisions=new Map([[id,4]]);
          const authState={{token:"token"}},composeRequestScope=()=>"account-A",composeRawSnapshot=()=>snapshot;
          const flushComposeInputUpdates=()=>true,events=[];
          const rememberPendingComposeArchive=(draft,official,revision)=>{{events.push(["marker",draft,official,revision]);return {{draftId:draft}}}};
          const retryPendingComposeArchive=async()=>{{events.push(["archive"]);return true}};
        '''
        value = self.run_js(["saveComposeCloudDraft"], setup, '''
          const pending=saveComposeCloudDraft({archived:true,officialDocumentId:officialId});
          const before=[...events];resolveSave({revision:4});const result=await pending;
          console.log(JSON.stringify({before,events,result}));
        ''')
        self.assertEqual(value["before"], [])
        self.assertEqual(value["events"], [["marker", DRAFT_ID, OFFICIAL_ID, 4], ["archive"]])
        self.assertTrue(value["result"]["archived"])

    def test_known_conflict_keeps_cleanup_marker_without_archiving_newer_draft(self):
        setup = f'''
          const id="{DRAFT_ID}",officialId="{OFFICIAL_ID}";
          let composeCloudTimer=null,composeCloudDraftId=id,composeCloudConflict=true,composeCloudOperation=null;
          const composeCloudSavedSnapshots=new Map(),composeCloudRevisions=new Map([[id,2]]);
          const authState={{token:"token"}},composeRequestScope=()=>"account-A",composeRawSnapshot=()=>({{values:{{"#subject":"local"}}}});
          const flushComposeInputUpdates=()=>true,events=[];
          const rememberPendingComposeArchive=(draft,official,revision)=>{{events.push(["marker",revision]);return {{draftId:draft}}}};
          const retryPendingComposeArchive=async()=>{{events.push(["archive"]);return true}};
        '''
        value = self.run_js(["saveComposeCloudDraft"], setup, '''
          const result=await saveComposeCloudDraft({archived:true,officialDocumentId:officialId});
          console.log(JSON.stringify({result,events}));
        ''')
        self.assertIsNone(value["result"])
        self.assertEqual(value["events"], [["marker", 2]])

    def test_storage_failure_still_attempts_server_archive_with_cas(self):
        setup = f'''
          const id="{DRAFT_ID}",officialId="{OFFICIAL_ID}",snapshot={{values:{{"#subject":"safe"}}}};
          let composeCloudTimer=null,composeCloudDraftId=id,composeCloudConflict=false,composeCloudOperation=null;
          const composeCloudSavedSnapshots=new Map([[id,JSON.stringify(snapshot)]]),composeCloudRevisions=new Map([[id,8]]);
          const authState={{token:"token"}},composeRequestScope=()=>"account-A",composeRawSnapshot=()=>snapshot;
          const flushComposeInputUpdates=()=>true,rememberPendingComposeArchive=()=>null,
            pendingComposeArchiveForDraft=()=>null,forgetPendingComposeArchive=()=>true;
          let request=null;const backendRequest=async(path,options)=>{{request={{path,body:JSON.parse(options.body)}};return {{archived:true}}}};
        '''
        value = self.run_js(["saveComposeCloudDraft"], setup, '''
          const result=await saveComposeCloudDraft({archived:true,officialDocumentId:officialId});
          console.log(JSON.stringify({result,request}));
        ''')
        self.assertTrue(value["result"]["archived"])
        self.assertEqual(value["request"]["body"], {"official_document_id": OFFICIAL_ID, "expected_revision": 8})

    def test_marker_storage_is_account_and_company_scoped(self):
        setup = f'''
          const store=new Map();global.localStorage={{getItem:key=>store.get(key)||null,setItem:(key,value)=>store.set(key,value)}};
          let authState={{user:{{id:"U-A",company_id:"CO-A"}}}},composePendingArchiveCache={{key:"",rows:[]}};
          const frontendScopedSessionKey=name=>`edoc:${{authState.user.id}}:${{authState.user.company_id}}:${{name}}`;
        '''
        functions = ["composePendingArchiveStorageKey", "submittedComposeArchiveRecords", "pendingComposeArchives", "persistPendingComposeArchives",
                     "pendingComposeArchiveForDraft", "rememberPendingComposeArchive"]
        value = self.run_js(functions, setup, f'''
          rememberPendingComposeArchive("{DRAFT_ID}","{OFFICIAL_ID}",7);
          const a=pendingComposeArchiveForDraft("{DRAFT_ID}");
          authState={{user:{{id:"U-B",company_id:"CO-A"}}}};
          const otherUser=pendingComposeArchives();
          authState={{user:{{id:"U-A",company_id:"CO-B"}}}};
          const otherCompany=pendingComposeArchives();
          authState={{user:{{id:"U-A",company_id:"CO-A"}}}};
          const restored=pendingComposeArchiveForDraft("{DRAFT_ID}");
          console.log(JSON.stringify({{a,otherUser,otherCompany,restored,keys:[...store.keys()]}}));
        ''')
        self.assertEqual(value["a"]["expectedRevision"], 7)
        self.assertEqual(value["otherUser"], [])
        self.assertEqual(value["otherCompany"], [])
        self.assertEqual(value["restored"]["draftId"], DRAFT_ID)
        self.assertEqual(len(value["keys"]), 1)

    def test_retry_conflict_preserves_marker_and_submitted_draft(self):
        setup = f'''
          const id="{DRAFT_ID}",officialId="{OFFICIAL_ID}";
          const marker={{draftId:id,officialDocumentId:officialId,expectedRevision:3}};
          const authState={{token:"token"}},composePendingArchiveStorageKey=()=>"A",pendingComposeArchiveForDraft=()=>marker;
          const composePendingArchiveRequests=new Map();let composeCloudRows=[{{id,revision:4}}];
          const backendRequest=async()=>{{throw {{status:409}}}},showToast=()=>{{}};
        '''
        value = self.run_js(["retryPendingComposeArchive"], setup, '''
          const result=await retryPendingComposeArchive(id,{silent:true});
          console.log(JSON.stringify({result,rows:composeCloudRows.length,marker:pendingComposeArchiveForDraft(id)}));
        ''')
        self.assertFalse(value["result"])
        self.assertEqual(value["rows"], 1)
        self.assertEqual(value["marker"]["expectedRevision"], 3)

    def test_formal_send_success_survives_private_archive_failure(self):
        setup = f'''
          let draftConfirmed=true,draftSigned=false,currentComposeDraftId="",composeDraftRequestId="{OFFICIAL_ID}";
          let selectedOfficialDocumentId="",selectedDispatchId="";
          const composeCloudDraftId="{DRAFT_ID}",composeSealPlacements={{large:{{}},small:{{}}}};
          const dispatchDocs=[],officialWorkflowItems=[];
          const approvalSelectionForSelect=()=>({{documentCategory:"一般文件",approvalRouteCode:"A"}});
          const composePayload=()=>({{attachments:[],approvalFlowNodes:[],companyName:"測試公司",dispatchDate:"2026-10-02",subject:"去識別函稿",body:"內容"}});
          const isValidComposeDispatchDate=()=>true,ensureComposeDraftRequestId=()=>{{}},composeRequestScope=()=>"U:CO",writeComposeAutosave=()=>{{}};
          const createOfficialApplicationFromCompose=async()=>({{id:"{OFFICIAL_ID}"}});
          const saveComposeCloudDraft=async()=>null,pendingComposeArchiveForDraft=()=>({{draftId:"{DRAFT_ID}"}});
          const rememberSubmittedComposeTombstone=()=>true,submittedComposeArchiveRecords=()=>[{{officialDocumentId:"{OFFICIAL_ID}"}}];
          const composeAutosaveLastWrittenRaw="saved-by-this-tab";
          let reset=null;const resetComposeAfterConfirmedSubmission=value=>{{reset=value}};
          const addDispatchAudit=()=>{{}},renderDispatchBoard=()=>{{}},renderDispatchDetail=()=>{{}},renderWorkflowTasks=()=>{{}},
            renderUnifiedFlows=()=>{{}},renderApprovalLog=()=>{{}},renderDashboardApprovalProgress=()=>{{}};
          global.document={{querySelector:()=>({{value:"2026-10-02"}})}};
        '''
        value = self.run_js(["performCreateDispatchFromForm"], setup, '''
          const doc=await performCreateDispatchFromForm("待清稿");
          console.log(JSON.stringify({id:doc?.officialDocumentId,pending:doc?.composeCleanupPending,reset,formalCount:officialWorkflowItems.length}));
        ''')
        self.assertEqual(value, {"id": OFFICIAL_ID, "pending": True,
                                 "reset": {"cleanupPending": True, "markerAvailable": True,
                                           "recoveryGuardUnavailable": False,
                                           "expectedAutosaveRaw": "saved-by-this-tab"}, "formalCount": 1})

    def test_confirmed_submission_marker_prevents_stale_local_autorestore(self):
        setup = f'''
          const autosaveKey="fixture";
          const snapshot={{schemaVersion:2,userId:"U",companyId:"CO",cloudDraftId:"{DRAFT_ID}",
            draftRequestId:"{OFFICIAL_ID}",values:{{"#subject":"已送簽內容"}}}};
          let stored=JSON.stringify({{snapshot}}),cleared=false;
          global.localStorage={{getItem:()=>stored}};
          const composeAutosaveStorageKey=autosaveKey,composeAutosaveIdentity=()=>"U:CO",readComposeAutosaveRaw=()=>stored;
          const composeSnapshotHasMeaningfulContent=()=>true;
          const submittedComposeMarkerForSnapshot=()=>({{draftId:"{DRAFT_ID}",officialDocumentId:"{OFFICIAL_ID}"}});
          const clearComposeAutosave=()=>{{cleared=true;stored=""}};
        '''
        value = self.run_js(["readComposeAutosave"], setup, '''
          const result=readComposeAutosave();console.log(JSON.stringify({result,cleared,preserved:!!stored}));
        ''')
        self.assertEqual(value, {"result": None, "cleared": False, "preserved": True})

    def test_scoped_autosave_keys_isolate_accounts_and_migrate_matching_legacy_only(self):
        setup = '''
          const legacyKey="suiyuecare-edoc-compose-autosave",composeAutosaveStorageKey=legacyKey;
          const store=new Map(),localStorage={getItem:key=>store.get(key)||null,
            setItem:(key,value)=>store.set(key,value),removeItem:key=>store.delete(key)};
          let authState={user:{id:"U-A",company_id:"CO-A"}},composeAutosaveLastWrittenRaw=null;
        '''
        functions = ["composeAutosaveIdentity", "composeScopedAutosaveStorageKey", "readComposeAutosaveRaw", "writeComposeAutosaveRaw"]
        value = self.run_js(functions, setup, '''
          const legacy=JSON.stringify({snapshot:{userId:"U-A",companyId:"CO-A",values:{"#subject":"舊稿"}}});
          localStorage.setItem(legacyKey,legacy);
          authState={user:{id:"U-B",company_id:"CO-A"}};
          const foreignRead=readComposeAutosaveRaw(),foreignLegacy=localStorage.getItem(legacyKey)===legacy;
          writeComposeAutosaveRaw("B-content");const bKey=composeScopedAutosaveStorageKey();
          authState={user:{id:"U-A",company_id:"CO-A"}};
          const aRead=readComposeAutosaveRaw(),aKey=composeScopedAutosaveStorageKey();
          writeComposeAutosaveRaw("A-content");
          authState={user:{id:"U-B",company_id:"CO-A"}};
          console.log(JSON.stringify({foreignRead,foreignLegacy,aRead,distinct:aKey!==bKey,
            a:localStorage.getItem(aKey),b:localStorage.getItem(bKey),legacyRemoved:!localStorage.getItem(legacyKey)}));
        ''')
        self.assertEqual(value, {"foreignRead": "", "foreignLegacy": True,
                                 "aRead": '{"snapshot":{"userId":"U-A","companyId":"CO-A","values":{"#subject":"舊稿"}}}',
                                 "distinct": True, "a": "A-content", "b": "B-content", "legacyRemoved": True})

    def test_conditional_clear_preserves_newer_other_tab_content(self):
        setup = '''
          const key="scoped",store=new Map([[key,"submitted-tab-raw"]]);
          const localStorage={getItem:value=>store.get(value)||null,removeItem:value=>store.delete(value)};
          const composeScopedAutosaveStorageKey=()=>key;
          let composeAutosaveLastWrittenRaw="submitted-tab-raw";const renderComposeDraftCount=()=>{};
        '''
        value = self.run_js(["clearComposeAutosave"], setup, '''
          store.set(key,"newer-other-tab-raw");const blocked=clearComposeAutosave("submitted-tab-raw");
          const afterBlocked=store.get(key);const cleared=clearComposeAutosave("newer-other-tab-raw");
          console.log(JSON.stringify({blocked,afterBlocked,cleared,remaining:store.has(key)}));
        ''')
        self.assertEqual(value, {"blocked": False, "afterBlocked": "newer-other-tab-raw",
                                 "cleared": True, "remaining": False})

    def test_submitted_local_recovery_forks_without_formal_or_cloud_ids(self):
        setup = f'''
          const saved={{updatedAt:"2026-10-02T00:00:00Z",snapshot:{{userId:"U",companyId:"CO",
            cloudDraftId:"{DRAFT_ID}",draftRequestId:"{OFFICIAL_ID}",officialDocumentId:"{OFFICIAL_ID}",
            currentComposeDraftId:"OUT-1",officialContentRevision:5,
            values:{{"#subject":"其他分頁未同步修改","#dispatchNo":"舊字號"}}}}}};
          const composeSubmittedLocalRecovery=()=>saved,composeInputIsComposing=()=>false;
          let current={{values:{{}}}},written=false,route="";
          const composeRawSnapshot=()=>current,composeSnapshotHasMeaningfulContent=item=>!!item.values?.["#subject"];
          const resetComposeAsyncScope=()=>{{}},restoreComposeAutosave=fork=>{{current=fork.snapshot;return true}};
          const writeComposeAutosave=()=>{{written=true}},setView=value=>{{route=value}},showToast=()=>{{}};
          let composeAutosaveRestoredForIdentity="U:CO";
          const input={{value:"old-file"}};
          global.document={{querySelector:key=>key==="#attachments"?input:key==="#composeAttachmentUploadStatus"?{{replaceChildren(){{}}}}:null}};
        '''
        value = self.run_js(["resumeSubmittedComposeLocalAsNewDraft"], setup, '''
          const success=await resumeSubmittedComposeLocalAsNewDraft();
          console.log(JSON.stringify({success,written,route,file:input.value,subject:current.values["#subject"],
            number:current.values["#dispatchNo"],cloud:current.cloudDraftId,request:current.draftRequestId,
            official:current.officialDocumentId,legacy:current.currentComposeDraftId,revision:current.officialContentRevision}));
        ''')
        self.assertEqual(value, {"success": True, "written": True, "route": "compose", "file": "",
                                 "subject": "其他分頁未同步修改", "number": "", "cloud": "", "request": "",
                                 "official": "", "legacy": "", "revision": None})

    def test_cross_tab_submission_marker_invalidates_cached_records(self):
        source = (ROOT / "app.js").read_text()
        start = source.index('window.addEventListener("storage", (event) => {')
        end = source.index("\n});", start) + len("\n});")
        snippet = source[start:end]
        setup = '''
          let handler=null,composePendingArchiveCache={key:"marker",rows:[{draftId:"stale"}]};
          const window={addEventListener:(_,callback)=>{handler=callback}};
          const composeScopedAutosaveStorageKey=()=>"scoped",composePendingArchiveStorageKey=()=>"marker";
          const composeAutosaveStorageKey="legacy";let renders=0,activeRouteTarget="drafts";
          const renderComposeDraftCount=()=>{renders++},renderComposeDraftList=()=>{renders++};
        '''
        result = subprocess.run(["node", "-e", setup + snippet + '''
          handler({key:"marker"});const afterMarker={key:composePendingArchiveCache.key,renders};
          handler({key:"other"});console.log(JSON.stringify({afterMarker,finalRenders:renders}));
        '''], text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"afterMarker": {"key": "", "renders": 2}, "finalRenders": 2})


if __name__ == "__main__":
    unittest.main()
