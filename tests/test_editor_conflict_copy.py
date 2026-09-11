"""Conflict recovery keeps both versions, without production accounts or data."""
import copy
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import backend
from tests.test_five_account_editor_workflow import FiveAccountEditorWorkflowTestCase as Fixture

ROOT = Path(__file__).resolve().parents[1]


class EditorConflictCopyTest(Fixture):
    # Reuse the isolated DB setup, not the unrelated full approval scenario.
    test_five_randomized_accounts_complete_editor_approval_stamp_and_download = None
    test_finance_seniority_shortening_is_server_derived = None

    def source(self, content=None, *, convert_a4=False):
        session = self._session_for_user_id(self.applicant_ids[0])
        draft = backend.create_official_editor_draft(self.conn, {"company_id": "CO-001", "title": "Before conflict", "document_category": "合作意向書"}, session)
        content = content if content is not None else self._a4_pdf_bytes(1)
        intent = backend.create_official_editor_upload_intent(self.conn, draft["id"], {"file_name": "fixture.pdf", "mime_type": "application/pdf", "size_bytes": len(content), "sha256": backend.sha256_bytes(content)}, session)
        backend.store_official_editor_local_upload(self.conn, draft["id"], intent["upload_id"], content, session, "application/pdf")
        finalized = backend.finalize_official_editor_upload(self.conn, draft["id"], intent["upload_id"], {"allowA4Conversion": convert_a4}, session)
        if convert_a4:
            finalized = backend.convert_official_editor_upload_a4(self.conn, draft["id"], intent["upload_id"], {
                "confirm": True, "sourceSha256": finalized["asset"]["sha256"],
                "baseRevisionNo": finalized["editor_revision"]["revisionNo"],
            }, session)
        state = self._add_editor_elements(finalized["editor_revision"], 1)
        payload = {"requestId": "fixture-request-123456", "state": state, "application": {"title": "Preserved local title", "description": "Local reason", "request_reason": "Local reason", "document_category": "合作意向書", "company_id": "CO-001"}}
        return session, draft["id"], payload

    def test_copy_preserves_content_and_assets_but_not_source_revision(self):
        session, source_id, payload = self.source()
        with patch.object(backend.time, "time", return_value=1_800_000_000):
            before = backend.get_official_editor_state(self.conn, source_id, session)
        result = backend.copy_official_editor_conflict(self.conn, source_id, payload, session)
        self.assertNotEqual(result["id"], source_id)
        with patch.object(backend.time, "time", return_value=1_800_000_001):
            after = backend.get_official_editor_state(self.conn, source_id, session)
        # Read responses refresh short-lived capabilities. Crossing a second
        # must not be mistaken for mutation of the immutable source revision.
        self.assertNotEqual(after["assets"][0]["url"], before["assets"][0]["url"])
        for response in (before, after):
            for asset in response["assets"]:
                self.assertTrue(asset.pop("url").startswith(f"/api/official-documents/{source_id}/editor-assets/"))
                self.assertTrue(asset.pop("expiresAt"))
        self.assertEqual(after, before)
        reopened = backend.get_official_editor_state(self.conn, result["id"], session)
        self.assertEqual(reopened["state"], result["state"])
        self.assertEqual(len(reopened["state"]["elements"]), 2)
        self.assertNotEqual(reopened["state"]["pages"][0]["pageId"], payload["state"]["pages"][0]["pageId"])
        self.assertNotEqual(reopened["state"]["sourceFiles"][0]["assetId"], payload["state"]["sourceFiles"][0]["assetId"])
        document = backend.official_document_row(self.conn, result["id"])
        self.assertEqual(document["title"], "Preserved local title")
        self.assertEqual(document["current_status"], "draft")
        data, assets = backend._editor_local_asset_bytes(self.conn, result["id"], reopened["state"])
        self.assertEqual(len(data), 1)
        self.assertTrue(all(asset["document_id"] == result["id"] for asset in assets))
        backend.assert_official_document_uploads_av_clean(self.conn, document)
        prepared = backend.preflight_official_editor(self.conn, result["id"], {}, session)
        self.assertEqual(prepared["status"], "prepared")

    def test_same_request_is_idempotent_and_changed_payload_rejected(self):
        session, source_id, payload = self.source()
        first = backend.copy_official_editor_conflict(self.conn, source_id, payload, session)
        count = self.conn.execute("SELECT count(*) FROM official_documents").fetchone()[0]
        second = backend.copy_official_editor_conflict(self.conn, source_id, payload, session)
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM official_documents").fetchone()[0], count)
        payload["application"]["title"] = "Different"
        with self.assertRaisesRegex(ValueError, "editor_conflict_copy_request_conflict"):
            backend.copy_official_editor_conflict(self.conn, source_id, payload, session)

    def test_other_applicant_company_and_submitted_source_are_denied(self):
        session, source_id, payload = self.source()
        with self.assertRaises(PermissionError):
            backend.copy_official_editor_conflict(self.conn, source_id, payload, self._session_for_user_id(self.applicant_ids[1]))
        other_company = copy.deepcopy(session)
        other_company["user"]["company_id"] = "CO-OTHER"
        with self.assertRaises(PermissionError):
            backend.copy_official_editor_conflict(self.conn, source_id, payload, other_company)
        self.conn.execute("UPDATE official_documents SET current_status='pending_approval' WHERE id=?", (source_id,))
        with self.assertRaisesRegex(ValueError, "editor_locked_after_submit"):
            backend.copy_official_editor_conflict(self.conn, source_id, payload, session)

    def test_foreign_source_asset_and_hash_tampering_rejected_without_copy(self):
        session, source_id, payload = self.source()
        count = self.conn.execute("SELECT count(*) FROM official_documents").fetchone()[0]
        payload["state"]["sourceFiles"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "editor_asset_hash_mismatch"):
            backend.copy_official_editor_conflict(self.conn, source_id, payload, session)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM official_documents").fetchone()[0], count)

    def test_failed_atomic_copy_rolls_back_new_rows_and_files(self):
        session, source_id, payload = self.source()
        original = backend.insert_row
        count = self.conn.execute("SELECT count(*) FROM official_documents").fetchone()[0]
        def fail(conn, table, row):
            if table == "official_document_editor_assets":
                raise RuntimeError("simulated db failure")
            return original(conn, table, row)
        with patch.object(backend, "insert_row", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "simulated db failure"):
                backend.copy_official_editor_conflict(self.conn, source_id, payload, session)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM official_documents").fetchone()[0], count)
        self.assertEqual(list(backend.STORAGE_DIR.glob("editor-final/ODCOPY-*/**/*.pdf")), [])

    def test_seam_pairs_remain_grouped_on_remapped_pages(self):
        session, source_id, payload = self.source()
        state = payload["state"]
        page = state["pages"][0]
        state["pages"].append({**page, "pageId": "second-copy-page", "order": 1})
        seal = state["elements"][1]
        seal.update({"x": round(page["widthPt"] - seal["width"], 4), "y": 100, "rotation": 0})
        seal["properties"].update({"seamGroupId": "fixture-seam", "seamMode": "pair", "seamPartIndex": 0, "seamPartCount": 2})
        partner = copy.deepcopy(seal)
        partner.update({"id": "seam-second-half", "pageId": "second-copy-page", "x": 0})
        partner["properties"]["seamPartIndex"] = 1
        state["elements"].append(partner)
        result = backend.copy_official_editor_conflict(self.conn, source_id, payload, session)
        groups = backend.validate_seam_groups(result["state"])
        self.assertEqual(len(groups["fixture-seam"]), 2)
        self.assertEqual({item["properties"]["seamPartIndex"] for item in groups["fixture-seam"]}, {0, 1})
        backend.preflight_official_editor(self.conn, result["id"], {}, session)

    def test_a4_conversion_clone_remaps_authoritative_lineage_and_retains_original(self):
        from tests.test_editor_a4_conversion import fixture_pdf

        session, source_id, payload = self.source(fixture_pdf(), convert_a4=True)
        old_sources = payload["state"]["sourceFiles"]
        self.assertEqual(len(old_sources), 2)
        old_ids = {item["assetId"] for item in old_sources}
        result = backend.copy_official_editor_conflict(self.conn, source_id, payload, session)
        reopened = backend.get_official_editor_state(self.conn, result["id"], session)
        sources = reopened["state"]["sourceFiles"]
        self.assertEqual(len(sources), 2)
        self.assertTrue(old_ids.isdisjoint({item["assetId"] for item in sources}))
        original = next(item for item in sources if item["a4Conversion"].get("required"))
        derivative = next(item for item in sources if not item["a4Conversion"].get("required"))
        self.assertEqual(original["a4Conversion"]["sourceAssetId"], original["assetId"])
        self.assertEqual(derivative["a4Conversion"]["sourceAssetId"], original["assetId"])
        self.assertEqual(derivative["a4Conversion"]["sourceSha256"], original["sha256"])
        for source in sources:
            asset = dict(self.conn.execute("SELECT * FROM official_document_editor_assets WHERE id=?", (source["assetId"],)).fetchone())
            self.assertEqual(source["a4Conversion"], backend._editor_asset_a4_conversion(asset))
        self.assertTrue(all(page["sourceAssetId"] == derivative["assetId"] for page in reopened["state"]["pages"]))
        backend._editor_local_asset_bytes(self.conn, result["id"], reopened["state"])
        prepared = backend.preflight_official_editor(self.conn, result["id"], {}, session)
        self.assertEqual(prepared["status"], "prepared")


class EditorConflictCopyJavascriptTest(unittest.TestCase):
    def run_case(self, case):
        source = (ROOT / "app.js").read_text()
        functions = []
        for name in ("copyUploadedEditorConflictVersion", "reloadUploadedEditorServerState", "renderUploadedEditorConflictBusy"):
            match = re.search(r"(?:async )?function " + name + r"\(", source)
            end = re.search(r"\n(?:async )?function \w+\(", source[match.end():])
            functions.append(source[match.start():match.end() + end.start()])
        harness = r'''
const assert=require('node:assert/strict');let calls=[],messages=[],installs=0,scope='one',draft={title:'local'};
const crypto=require('node:crypto');const cloneUploadedEditorValue=v=>JSON.parse(JSON.stringify(v));
const document={querySelector:()=>({disabled:false,textContent:''})};const window={confirm:()=>true};
const uploadedSealEditorRuntime={documentId:'old',conflict:{requestId:'request-fixture-111'},dirtyGeneration:2};
let uploadedSealEditorState={schemaVersion:2,revisionNo:1,pages:[],sourceFiles:[],elements:[]};
const uploadedSealApplicationScopeSnapshot=()=>({scope,documentId:uploadedSealEditorRuntime.documentId});
const uploadedSealApplicationScopeIsCurrent=s=>s.scope===scope&&s.documentId===uploadedSealEditorRuntime.documentId;
const editorDraftPayload=()=>({...draft});const uploadedSealApplicationKey=()=>JSON.stringify(draft);
const showToast=m=>messages.push(m);const setUploadedEditorSaveStatus=()=>{};
let backendRequest=async(path,options)=>{calls.push({path,...options});return {document_id:'new',state:{schemaVersion:2}}};
async function installUploadedEditorRecovery(r,id,s){installs++;uploadedSealEditorRuntime.documentId=id;uploadedSealEditorRuntime.conflict=null;}
'''
        script = harness + "\n".join(functions) + "\n(async()=>{" + case + "})().catch(e=>{console.error(e);process.exitCode=1});"
        result = subprocess.run([shutil.which("node"), "-e", script], text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_copy_posts_current_state_once_and_opens_copy(self):
        self.run_case("await Promise.all([copyUploadedEditorConflictVersion(),copyUploadedEditorConflictVersion()]);assert.equal(calls.length,1);assert.equal(installs,1);assert.equal(uploadedSealEditorRuntime.documentId,'new');assert.equal(JSON.parse(calls[0].body).application.title,'local');")

    def test_failure_preserves_local_content_and_retry_key(self):
        self.run_case("backendRequest=async(p,o)=>{calls.push(JSON.parse(o.body));throw Error('offline')};await copyUploadedEditorConflictVersion();await copyUploadedEditorConflictVersion();assert.equal(uploadedSealEditorRuntime.documentId,'old');assert.equal(installs,0);assert.equal(calls[0].requestId,calls[1].requestId);assert.equal(draft.title,'local');")

    def test_edit_during_copy_is_not_discarded(self):
        self.run_case("let done;backendRequest=()=>new Promise(r=>done=r);let pending=copyUploadedEditorConflictVersion();await Promise.resolve();draft.title='new typing';done({document_id:'new'});await pending;assert.equal(installs,0);assert.equal(draft.title,'new typing');assert.equal(uploadedSealEditorRuntime.documentId,'old');")

    def test_account_switch_ignores_old_copy_response(self):
        self.run_case("let done;backendRequest=()=>new Promise(r=>done=r);let pending=copyUploadedEditorConflictVersion();await Promise.resolve();scope='two';done({document_id:'new'});await pending;assert.equal(installs,0);")

    def test_latest_cancel_does_not_fetch_or_lose_content(self):
        self.run_case("window.confirm=()=>false;await reloadUploadedEditorServerState();assert.equal(calls.length,0);assert.equal(draft.title,'local');")

    def test_latest_does_not_replace_edits_during_fetch(self):
        self.run_case("backendRequest=async()=>{uploadedSealEditorRuntime.dirtyGeneration++;return {state:{schemaVersion:2}}};await reloadUploadedEditorServerState();assert.equal(installs,0);")


del Fixture  # Do not rediscover the imported five-account suite in this module.
