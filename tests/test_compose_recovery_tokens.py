"""Exercise actual restore code with old-client and cross-device snapshots."""
import json
import unittest

import compose_resilience

from tests import test_compose_resilience_frontend as fixture


class ComposeRecoveryTokenTest(unittest.TestCase):
    run_js = fixture.ComposeResilienceFrontendTest.run_js
    FUNCTIONS = ["restoreComposeAutosave", "canonicalEditorJson", "composePersistedSnapshotKey"]
    SETUP = '''
      const composeAutosaveIdentity=()=>"U:CO",refreshComposeCloudDrafts=()=>Promise.resolve(),renderApprovalCategorySelect=()=>{},syncComposeCopyRecipientsDefault=()=>{},syncComposeElectronicExchangeMode=()=>{},renderComposeApprovalRoute=()=>{},renderDraftPreview=()=>{},renderComposeSaveStatus=()=>{},formatComposeSaveTime=()=>"12:00";
      let composeAutosaveRestoredForIdentity="",currentComposeDraftId="",composeDraftRequestId="",composeCloudDraftId="",composeOfficialContentRevision=null,draftConfirmed=false,draftSigned=false,activeComposeStep="fill",composeSaveState={};
      const composeAutosaveSelectors=["#subject"],node={value:"",tagName:"TEXTAREA",dataset:{}},dispatchDocs=[],composeSealPlacements={large:{x:70,y:80},small:{x:80,y:80}},clampComposePlacement=(value,fallback)=>fallback;
      global.document={querySelector:key=>key==="#subject"?node:null};
      const id="OD-00000000-0000-4000-8000-000000000001";
      const saved={snapshot:{schemaVersion:2,userId:"U",companyId:"CO",cloudDraftId:id,values:{"#subject":"上次草稿"}},updatedAt:"2026-09-12"};
      const readComposeAutosave=()=>saved,composeCloudRevisions=new Map();
      const composeCloudRows=[{id,revision:7,snapshot:{values:{"#subject":"上次草稿"},cloudDraftId:id,companyId:"CO",userId:"U",schemaVersion:2}}];
    '''

    def test_old_client_exact_snapshot_matches_despite_server_key_sort_order(self):
        result = self.run_js(self.FUNCTIONS, self.SETUP, '''const restored=restoreComposeAutosave();console.log(JSON.stringify({restored,revision:composeCloudRevisions.get(id),text:node.value}));''')
        self.assertEqual(result, {"restored": True, "revision": 7, "text": "上次草稿"})

    def test_different_cloud_content_never_upgrades_unknown_old_client_token(self):
        result = self.run_js(self.FUNCTIONS, self.SETUP, '''composeCloudRows[0].snapshot.values["#subject"]="別人已修改的新版本";restoreComposeAutosave();console.log(JSON.stringify({revision:composeCloudRevisions.get(id),text:node.value}));''')
        self.assertEqual(result, {"revision": 0, "text": "上次草稿"})

    def test_known_local_revision_is_preserved_even_if_cloud_has_a_newer_row(self):
        result = self.run_js(self.FUNCTIONS, self.SETUP, '''saved.cloudRevision=2;restoreComposeAutosave();console.log(JSON.stringify({revision:composeCloudRevisions.get(id),text:node.value}));''')
        self.assertEqual(result, {"revision": 2, "text": "上次草稿"})

    def test_other_account_saved_snapshot_cannot_be_loaded(self):
        result = self.run_js(self.FUNCTIONS, self.SETUP, '''saved.snapshot.userId="OTHER";const restored=restoreComposeAutosave();console.log(JSON.stringify({restored,versions:composeCloudRevisions.size,text:node.value}));''')
        self.assertEqual(result, {"restored": False, "versions": 0, "text": ""})

    def test_client_only_hints_do_not_prevent_exact_persisted_content_recovery(self):
        result = self.run_js(self.FUNCTIONS, self.SETUP, '''saved.snapshot.approval={documentCategory:"derived"};saved.snapshot.role="client-role";delete composeCloudRows[0].snapshot.cloudDraftId;restoreComposeAutosave();console.log(JSON.stringify({revision:composeCloudRevisions.get(id)}));''')
        self.assertEqual(result, {"revision": 7})

    def test_stamp_position_changes_are_not_treated_as_identical_content(self):
        result = self.run_js(self.FUNCTIONS, self.SETUP, '''saved.snapshot.sealPlacements={large:{x:70,y:80}};composeCloudRows[0].snapshot.sealPlacements={large:{x:75,y:80}};restoreComposeAutosave();console.log(JSON.stringify({revision:composeCloudRevisions.get(id)}));''')
        self.assertEqual(result, {"revision": 0})

    def test_comparison_projection_matches_actual_server_sanitized_snapshot(self):
        snapshot = {"schemaVersion": 2, "userId": "U", "companyId": "CO", "values": {"#subject": "合成測試", "#bodyText": "說明"},
                    "draftRequestId": "OD-REQUEST", "currentComposeDraftId": "LOCAL", "officialContentRevision": 2,
                    "officialDocumentId": "OD-OFFICIAL", "sealPlacements": {"large": {"x": 70, "y": 80}},
                    "cloudDraftId": "OD-00000000-0000-4000-8000-000000000001", "role": "client-role", "approval": {"derived": True}}
        _, encoded, _ = compose_resilience.draft_payload(snapshot["cloudDraftId"], {"expected_revision": 2, "snapshot": snapshot}, {"id": "U", "company_id": "CO"})
        result = self.run_js(["composePersistedSnapshotKey", "canonicalEditorJson"], "", "console.log(JSON.stringify(JSON.parse(composePersistedSnapshotKey(" + json.dumps(snapshot, ensure_ascii=False) + "))));")
        self.assertEqual(result, json.loads(encoded))


if __name__ == "__main__":
    unittest.main()
