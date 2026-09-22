"""Versioned seal paint order; synthetic content only, no external services."""
import ast
import inspect
import io
import json
import unittest
from unittest import mock

import fitz
from PIL import Image

import backend
from tests import test_compose_resilience_frontend as frontend_fixture
from tests import test_compose_multiseal as compose_fixture
from tests import test_five_account_editor_workflow as editor_fixture


class SealFrontFrontendTest(unittest.TestCase):
    run_js = frontend_fixture.ComposeResilienceFrontendTest.run_js
    PREFLIGHT_SETUP = '''
      const PDF_EDITOR_SCHEMA_VERSION=2;
      let scope="D";
      let uploadedSealEditorState={schemaVersion:2,revisionNo:3,manifestSha256:"old-manifest",pages:[{pageId:"P"}],elements:[]};
      const uploadedSealEditorRuntime={documentId:"D",revisionId:"R3",dirtyGeneration:0,currentPageId:"P",selectedIds:new Set()};
      const finishUploadedEditorTextEdit=()=>true,ensureUploadedEditorPagesA4=()=>{},saveUploadedEditorState=async()=>{};
      const uploadedSealApplicationScopeSnapshot=()=>scope,uploadedSealApplicationScopeIsCurrent=value=>scope===value;
      const cloneUploadedEditorValue=structuredClone,emptyUploadedSealEditorState=()=>({schemaVersion:2,pages:[],elements:[]});
      const rememberUploadedEditorSavedSealBindings=()=>{},syncLegacyUploadedEditorCollections=()=>{};
      const editorPreparedAuthorizedUrl=()=>"/synthetic-preview";
      global.document={querySelector:()=>null};
      const response={status:"prepared",rendererVersion:"v4",preparedFileId:"F4",preparedSha256:"prepared-hash",manifestSha256:"new-manifest",revision:{id:"R4",revisionNo:4,state:{schemaVersion:2,revisionNo:4,manifestSha256:"new-manifest",pages:[{pageId:"P"}],elements:[]}}};
    '''

    def test_preflight_upgrade_updates_public_revision_and_submission_manifest_together(self):
        result = self.run_js(
            ["preflightUploadedEditor", "applyEditorRevisionFromResponse", "applyUploadedEditorCanonicalSaveResponse"],
            self.PREFLIGHT_SETUP + 'const backendRequest=async()=>response;',
            'await preflightUploadedEditor();console.log(JSON.stringify({revision:uploadedSealEditorRuntime.revisionId,renderer:uploadedSealEditorRuntime.rendererVersion,manifest:uploadedSealEditorState.manifestSha256,number:uploadedSealEditorState.revisionNo}));',
        )
        self.assertEqual(result, {"revision": "R4", "renderer": "v4", "manifest": "new-manifest", "number": 4})

    def test_preflight_upgrade_cannot_overwrite_new_edits_or_a_new_document(self):
        for change in ('scope="OTHER";', 'uploadedSealEditorRuntime.dirtyGeneration+=1;'):
            with self.subTest(change=change):
                result = self.run_js(
                    ["preflightUploadedEditor", "applyEditorRevisionFromResponse", "applyUploadedEditorCanonicalSaveResponse"],
                    self.PREFLIGHT_SETUP + f'const backendRequest=async()=>{{{change}return response;}};',
                    'let error="";try{await preflightUploadedEditor()}catch(e){error=e.message}console.log(JSON.stringify({error,revision:uploadedSealEditorRuntime.revisionId,manifest:uploadedSealEditorState.manifestSha256,prepared:uploadedSealEditorRuntime.preparedFileId||""}));',
                )
                if change == 'scope="OTHER";':
                    self.assertEqual(result["error"], "", "Old-case completion must be ignored, not shown as an error in the new draft")
                else:
                    self.assertIn("重新預覽", result["error"])
                self.assertEqual(result["revision"], "R3")
                self.assertEqual(result["manifest"], "old-manifest")
                self.assertEqual(result["prepared"], "")

    def layers(self, locked, renderer):
        return self.run_js(
            ["editorElementLayerTier", "compareEditorElementsForLayer"],
            f"const PDF_EDITOR_RENDERER_VERSION={json.dumps(backend.EDOC_EDITOR_RENDERER_VERSION)};"
            f"const uploadedSealEditorRuntime={{locked:{json.dumps(locked)},rendererVersion:{json.dumps(renderer)}}};",
            'console.log(JSON.stringify([{id:"seal-a",kind:"seal",zIndex:1},{id:"text",kind:"text",zIndex:999},'
            '{id:"seal-b",kind:"seal",zIndex:2},{id:"image",kind:"image",zIndex:9999}]'
            '.sort(compareEditorElementsForLayer).map(e=>e.id)));',
        )

    def test_editable_old_and_new_drafts_put_both_seals_last(self):
        for version in ("", backend.EDOC_EDITOR_RENDERER_VERSION, backend.EDOC_EDITOR_LEGACY_TEXT_FRONT_RENDERER_VERSION):
            with self.subTest(version=version):
                self.assertEqual(self.layers(False, version), ["image", "text", "seal-a", "seal-b"])

    def test_locked_v4_keeps_seals_above_later_text(self):
        self.assertEqual(self.layers(True, backend.EDOC_EDITOR_RENDERER_VERSION), ["image", "text", "seal-a", "seal-b"])

    def test_locked_historical_or_unknown_version_preserves_previous_order(self):
        for version in ("", "old-renderer", backend.EDOC_EDITOR_LEGACY_TEXT_FRONT_RENDERER_VERSION):
            self.assertEqual(self.layers(True, version), ["seal-a", "seal-b", "image", "text"])

    def test_response_version_is_carried_without_changing_manifest_or_state(self):
        result = self.run_js(
            ["applyEditorRevisionFromResponse"],
            'const uploadedSealEditorState={revisionNo:1};const uploadedSealEditorRuntime={};'
            'const rememberUploadedEditorSavedSealBindings=()=>{};',
            'applyEditorRevisionFromResponse({revision:{id:"R",revisionNo:2,rendererVersion:"historical",manifestSha256:"locked-hash"}});'
            'console.log(JSON.stringify({runtime:uploadedSealEditorRuntime,state:uploadedSealEditorState}));',
        )
        self.assertEqual(result["runtime"], {"revisionId": "R", "rendererVersion": "historical", "baseManifestSha256": "locked-hash"})
        self.assertEqual(result["state"], {"revisionNo": 2})


class SealFrontLegacyPolicyTest(unittest.TestCase):
    @staticmethod
    def source():
        document = fitz.open()
        page = document.new_page(width=200, height=200)
        page.draw_rect(fitz.Rect(0, 0, 200, 200), color=(0, 0, 0), fill=(0, 0, 0))
        data = document.tobytes()
        document.close()
        return data

    @staticmethod
    def png(color):
        image = Image.new("RGBA", (64, 64), color)
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        return stream.getvalue()

    @staticmethod
    def pixel(data):
        with fitz.open(stream=data, filetype="pdf") as document:
            return document[0].get_pixmap().pixel(60, 140)

    def test_new_policy_seals_cover_source_but_unmarked_legacy_keeps_underlay(self):
        original = self.source()
        asset = {"data": self.png((255, 0, 0, 255)), "mime_type": "image/png"}
        stamp = [{"page": 1, "x": 40, "y": 40, "width": 80, "height": 80}]
        modern, _, info = backend.stamp_uploaded_pdf_bytes(original, stamp, "TEST", seal_asset=asset, source_text_on_top=True, seal_on_top=True)
        legacy, _, old_info = backend.stamp_uploaded_pdf_bytes(original, stamp, "TEST", seal_asset=asset, source_text_on_top=True)
        self.assertEqual(self.pixel(modern), (255, 0, 0))
        self.assertEqual(self.pixel(legacy), (0, 0, 0))
        self.assertEqual(info["layer_policy"], backend.SEAL_FRONT_LAYER_POLICY)
        self.assertEqual(old_info["layer_policy"], "source_and_added_text_over_company_seal")

    def test_multiple_seals_apply_text_once_before_every_seal_and_keep_saved_order(self):
        positions = [{"id": "first"}, {"id": "second"}]
        assets = [({"id": "red"}, b"red"), ({"id": "blue"}, b"blue")]
        calls = []
        def render(original, stamps, stamp_no, text, asset, **options):
            calls.append((stamps[0]["id"], text, options))
            return original, "fixture", {}
        with mock.patch.object(backend, "stamp_uploaded_pdf_bytes", side_effect=render):
            backend.stamp_legacy_pdf_with_locked_seals(b"immutable", positions, "TEST", [{"text": "synthetic"}], assets, source_text_on_top=True, seal_on_top=True)
        self.assertEqual([call[0] for call in calls], ["first", "second"])
        self.assertEqual([call[1] for call in calls], [[{"text": "synthetic"}], []])
        self.assertTrue(all(call[2]["seal_on_top"] for call in calls))

    def test_only_top_level_server_metadata_enables_policy(self):
        for metadata in ({}, {"extra": {"seal_layer_policy": backend.SEAL_FRONT_LAYER_POLICY}}, {"seal_layer_policy": "unknown"}):
            self.assertFalse(backend.official_document_seal_on_top({"metadata_json": json.dumps(metadata)}))
        self.assertTrue(backend.official_document_seal_on_top({"metadata_json": json.dumps({"seal_layer_policy": backend.SEAL_FRONT_LAYER_POLICY})}))

    def test_official_pdf_paints_stamps_after_footer(self):
        tree = ast.parse(inspect.getsource(backend.draw_official_page))
        last = tree.body[0].body[-1]
        self.assertIsInstance(last, ast.Expr)
        self.assertEqual(last.value.func.id, "draw_official_page_stamps")
        self.assertIn("v6", backend.OFFICIAL_PDF_RENDERER_VERSION)

    def test_new_legacy_snapshot_keeps_interleaved_placement_order(self):
        calls = []
        def render(original, stamps, *args, **kwargs):
            calls.append(stamps[0]["id"])
            self.assertTrue(kwargs["seal_on_top"])
            return original, "fixture", {}
        positions = [{"id": identity, "locked_seal_file_id": file_id} for identity, file_id in (("a", "red"), ("b", "blue"), ("c", "red"))]
        with mock.patch.object(backend, "stamp_uploaded_pdf_bytes", side_effect=render):
            backend.stamp_seal_application_positions(b"immutable", positions, "TEST", {"red": {}, "blue": {}}, seal_on_top=True)
        self.assertEqual(calls, ["a", "b", "c"])


class SealFrontRequestPolicyTest(unittest.TestCase):
    def setUp(self):
        self.fixture = compose_fixture.ComposeMultiSealBackendTest()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_new_request_records_policy_and_old_draft_adopts_only_when_edited(self):
        detail = self.fixture.create(submit=False)
        self.assertTrue(backend.official_document_seal_on_top(detail))
        metadata = json.loads(detail["metadata_json"])
        del metadata["seal_layer_policy"]
        self.fixture.conn.execute("UPDATE official_documents SET metadata_json=? WHERE id=?", (json.dumps(metadata), detail["id"]))
        old = backend.official_document_detail(self.fixture.conn, detail["id"])
        self.assertFalse(backend.official_document_seal_on_top(old))
        edited = backend.update_official_document_correction(self.fixture.conn, detail["id"], {
            "subject": "新修訂合成公文", "expected_content_revision": detail["content_revision"],
        }, self.fixture.session)
        self.assertTrue(backend.official_document_seal_on_top(edited))

    def usage_request(self, policy):
        request = backend.create_seal_usage_request(self.fixture.conn, "DOC-SYNTHETIC-LAYER", {
            "seal_id": self.fixture.large, "usage_type": "official_document", "status": "draft", "metadata": {"seal_layer_policy": "untrusted-client-value"},
            "document": {"document_id": "DOC-SYNTHETIC-LAYER", "doc_no": "TEST-LAYER", "subject": "合成圖層測試", "body": "僅供本機回歸測試"},
            "stamp_positions": [{"page": 1, "x": 420, "y": 130, "w": 85, "h": 85, "seal_id": self.fixture.large}],
        })
        self.assertEqual(request["metadata"]["seal_layer_policy"], backend.SEAL_FRONT_LAYER_POLICY)
        if not policy:
            metadata = request["metadata"]
            del metadata["seal_layer_policy"]
            self.fixture.conn.execute("UPDATE seal_usage_requests SET metadata_json=? WHERE id=?", (json.dumps(metadata), request["id"]))
        approved = backend.approve_seal_usage_request(self.fixture.conn, request["id"], {"actor": "synthetic-approver"})
        return backend.seal_usage_request_row(self.fixture.conn, approved["id"])

    def test_sqlite_usage_stamping_respects_new_or_historical_approved_request_policy(self):
        for policy in (True, False):
            with self.subTest(policy=policy):
                request = self.usage_request(policy)
                with mock.patch.object(backend, "stamp_uploaded_pdf_bytes", wraps=backend.stamp_uploaded_pdf_bytes) as render:
                    backend.stamp_seal_usage_request(self.fixture.conn, request["id"], {"actor": "synthetic-stamper"})
                self.assertEqual(render.call_args.kwargs["seal_on_top"], policy)

    def test_supabase_usage_stamping_respects_approved_metadata_not_new_package_date(self):
        for policy in (True, False):
            with self.subTest(policy=policy):
                request = self.usage_request(policy)
                seal = backend.company_seal_row(self.fixture.conn, request["seal_id"])
                file_row, positions = backend.locked_company_seal_usage_file(self.fixture.conn, request, seal)
                object_row, data = backend.read_file_object_bytes(self.fixture.conn, file_row["file_object_id"])
                document = dict(self.fixture.conn.execute("SELECT * FROM documents WHERE id=?", (request["document_id"],)).fetchone())
                with (
                    mock.patch.object(backend, "supabase_seal_usage_request_row", return_value=request),
                    mock.patch.object(backend, "supabase_company_seal_row", return_value=seal),
                    mock.patch.object(backend, "supabase_locked_company_seal_usage_file", return_value=(file_row, positions)),
                    mock.patch.object(backend, "supabase_get", side_effect=lambda table, identity: object_row if table == "file_objects" else document),
                    mock.patch.object(backend, "supabase_storage_download", return_value=data),
                    mock.patch.object(backend, "supabase_log_seal_usage"),
                    mock.patch.object(backend, "stamp_uploaded_pdf_bytes", side_effect=RuntimeError("synthetic-render-boundary")) as render,
                ):
                    with self.assertRaisesRegex(RuntimeError, "synthetic-render-boundary"):
                        backend.supabase_stamp_seal_usage_request(request["id"], {})
                self.assertEqual(render.call_args.kwargs["seal_on_top"], policy)


class SealFrontPreflightVersionTest(unittest.TestCase):
    def setUp(self):
        self.fixture = editor_fixture.FiveAccountEditorWorkflowTestCase()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.conn = self.fixture.conn
        self.session = self.fixture._session_for_user_id(self.fixture.applicant_ids[0])

    def old_preflight(self):
        with mock.patch.object(backend, "EDOC_EDITOR_RENDERER_VERSION", backend.EDOC_EDITOR_LEGACY_TEXT_FRONT_RENDERER_VERSION):
            draft = backend.create_official_editor_draft(self.conn, {"company_id": "CO-001", "title": "合成跨版本測試", "request_reason": "合成測試", "document_category": "合作意向書", "dispatch_method": "no_dispatch_required"}, self.session)
            source = self.fixture._a4_pdf_bytes(1)
            digest = backend.sha256_bytes(source)
            intent = backend.create_official_editor_upload_intent(self.conn, draft["id"], {"file_name": "synthetic.pdf", "mime_type": "application/pdf", "size_bytes": len(source), "sha256": digest}, self.session)
            backend.store_official_editor_local_upload(self.conn, draft["id"], intent["upload_id"], source, self.session, "application/pdf")
            uploaded = backend.finalize_official_editor_upload(self.conn, draft["id"], intent["upload_id"], {"sha256": digest}, self.session)
            revision = uploaded["editor_revision"]
            backend.save_official_editor_state(self.conn, draft["id"], {"revisionNo": revision["revisionNo"], "baseManifestSha256": revision["manifestSha256"], "state": self.fixture._add_editor_elements(revision, 1)}, self.session)
            prepared = backend.preflight_official_editor(self.conn, draft["id"], {}, self.session)
        return draft["id"], prepared

    def test_old_preflight_cannot_submit_then_repreview_creates_new_immutable_revision(self):
        doc_id, old_prepared = self.old_preflight()
        original_row = backend._editor_latest_revision_row(self.conn, doc_id)
        original_file = dict(self.conn.execute("SELECT * FROM official_document_files WHERE id=?", (old_prepared["preparedFileId"],)).fetchone())
        original_bytes = backend.read_file_object_bytes(self.conn, original_file["file_object_id"])[1]
        with self.assertRaisesRegex(ValueError, "editor_preflight_not_completed"):
            backend.submit_official_document(self.conn, doc_id, old_prepared, self.session)
        self.assertEqual(backend.official_document_row(self.conn, doc_id)["current_status"], "draft")
        new_prepared = backend.preflight_official_editor(self.conn, doc_id, {}, self.session)
        self.assertNotEqual(new_prepared["editorRevisionId"], original_row["id"])
        self.assertEqual(new_prepared["revision"]["rendererVersion"], backend.EDOC_EDITOR_RENDERER_VERSION)
        self.assertEqual(new_prepared["rendererVersion"], backend.EDOC_EDITOR_RENDERER_VERSION)
        self.assertEqual(dict(self.conn.execute("SELECT * FROM official_document_editor_revisions WHERE id=?", (original_row["id"],)).fetchone()), original_row)
        self.assertEqual(backend.read_file_object_bytes(self.conn, original_file["file_object_id"])[1], original_bytes)
        submitted = backend.submit_official_document(self.conn, doc_id, new_prepared, self.session)
        reopened = backend.get_official_editor_state(self.conn, doc_id, self.session)
        self.assertEqual(reopened["rendererVersion"], backend.EDOC_EDITOR_RENDERER_VERSION)
        self.assertEqual(submitted["stamp_request"]["renderer_version"], reopened["rendererVersion"])
        self.assertEqual(submitted["stamp_request"]["editor_manifest_sha256"], reopened["manifestSha256"])

    def test_supabase_rejects_old_prepared_version_before_any_write(self):
        doc_id, prepared = self.old_preflight()
        document = backend.official_document_row(self.conn, doc_id)
        def rows(table, filters, **kwargs):
            return [dict(row) for row in self.conn.execute(f"SELECT * FROM {table} WHERE " + " AND ".join(f"{name}=?" for name in filters), tuple(filters.values()))]
        def download(path, bucket):
            row = self.conn.execute("SELECT id FROM file_objects WHERE storage_key=?", (path,)).fetchone()
            return backend.read_file_object_bytes(self.conn, row["id"])[1]
        with (
            mock.patch.object(backend, "_supabase_editor_latest_revision", return_value=backend._editor_latest_revision_row(self.conn, doc_id)),
            mock.patch.object(backend, "supabase_filter_rows", side_effect=rows),
            mock.patch.object(backend, "supabase_storage_download", side_effect=download),
            mock.patch.object(backend, "supabase_patch", side_effect=AssertionError("must not write")),
            mock.patch.object(backend, "supabase_insert", side_effect=AssertionError("must not write")),
        ):
            with self.assertRaisesRegex(ValueError, "editor_preflight_not_completed"):
                backend.supabase_lock_official_editor_submission(document, prepared, self.session["user"])

    def test_prepared_and_revision_must_both_match_current_renderer(self):
        current = backend.EDOC_EDITOR_RENDERER_VERSION
        for revision_version, prepared_version in ((current, ""), (current, "v3"), ("v3", current), ("", current)):
            with self.subTest(revision=revision_version, prepared=prepared_version):
                with self.assertRaisesRegex(ValueError, "editor_preflight_not_completed"):
                    backend.require_current_editor_preflight({"renderer_version": revision_version}, {"metadata_json": json.dumps({"renderer_version": prepared_version})})
        backend.require_current_editor_preflight({"renderer_version": current}, {"metadata_json": json.dumps({"renderer_version": current})})


if __name__ == "__main__":
    unittest.main()
