"""Display filenames must not become Supabase object keys or audit details."""
from contextlib import ExitStack
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from unittest import mock

import backend


class EditorStorageFilenameTests(unittest.TestCase):
    NAMES = (
        "中文合約.pdf", "合作 意向書 (1).pdf", "合約[修訂版]100%.pdf",
        "文件😀.pdf", "résumé.pdf", "a # b.pdf", "a4.pdf",
    )

    def intent(self, name, mime_type="application/pdf", internal_metadata=None):
        inserted = []
        def insert(table, row):
            inserted.append((table, dict(row)))
            return dict(row)
        with ExitStack() as stack:
            patches = {
                "require_production_editor_runtime_ready": None,
                "supabase_official_document_row": {"id": "OD-QA", "company_id": "CO-QA"},
                "_supabase_editor_assert_document_access": {"id": "USER-QA"},
                "supabase_cleanup_stale_official_editor_uploads": {"count": 0},
                "_supabase_editor_latest_revision": {"id": "REV-QA", "revision_no": 1},
                "_supabase_storage_direct_tus_url": "https://qa.storage.supabase.co/storage/v1/upload/resumable/sign",
                "_supabase_storage_public_upload_key": "sb_publishable_fixture",
            }
            for key, value in patches.items():
                stack.enter_context(mock.patch.object(backend, key, return_value=value))
            signer = stack.enter_context(mock.patch.object(backend, "_supabase_create_signed_upload_token", return_value="fixture-capability"))
            stack.enter_context(mock.patch.object(backend, "supabase_insert", side_effect=insert))
            result = backend.supabase_create_official_editor_upload_intent("OD-QA", {
                "file_name": name, "mime_type": mime_type, "asset_kind": "image" if mime_type.startswith("image/") else "source_pdf",
                "size_bytes": 100, "sha256": "A" * 64,
            }, {"user": {"id": "USER-QA"}}, internal_metadata=internal_metadata)
        return result, inserted[0][1], inserted[1][1], signer

    def test_all_display_names_use_opaque_keys_and_preserve_original_name(self):
        for name in self.NAMES:
            with self.subTest(name=name):
                intent, asset, job, signer = self.intent(name)
                self.assertEqual(asset["file_name"], name)
                self.assertEqual(intent["asset"]["fileName"], name)
                self.assertEqual(json.loads(asset["metadata_json"])["storage_key_version"], 2)
                self.assertEqual(intent["path"], job["staging_path"])
                self.assertEqual(intent["metadata"]["objectName"], intent["path"])
                self.assertEqual(intent["path"], f"editor/OD-QA/{asset['id']}.pdf")
                self.assertEqual(job["final_path"], f"editor-final/OD-QA/{asset['id']}/{'A' * 64}.pdf")
                for path in (intent["path"], job["final_path"]):
                    self.assertRegex(path, r"^[A-Za-z0-9_/.-]+$")
                    self.assertNotIn(name, path)
                signer.assert_called_once_with(intent["path"], backend.EDOC_STORAGE_BUCKET)

    def test_duplicate_names_have_distinct_create_only_capabilities(self):
        one, _, _, _ = self.intent("中文合約.pdf")
        two, _, _, _ = self.intent("中文合約.pdf")
        self.assertNotEqual(one["path"], two["path"])
        self.assertNotIn("x-upsert", {key.lower() for key in one["headers"]})

    def test_imported_images_use_mime_extension_and_never_filename(self):
        for mime_type, extension in (("image/png", "png"), ("image/jpeg", "jpg")):
            with self.subTest(mime_type=mime_type):
                intent, asset, job, _ = self.intent(f"測試 圖片.{extension}", mime_type)
                self.assertTrue(intent["path"].endswith("." + extension))
                self.assertTrue(job["final_path"].endswith("." + extension))
                self.assertEqual(asset["mime_type"], mime_type)

    def test_original_metadata_cannot_override_new_key_version(self):
        _, asset, _, _ = self.intent("合約.pdf", internal_metadata={"storage_key_version": 1, "a4_source_revision_no": 1})
        self.assertEqual(json.loads(asset["metadata_json"])["storage_key_version"], 2)

    def test_legacy_committed_storage_job_path_does_not_change(self):
        asset = {"id": "ASSET-QA", "file_name": "legacy.pdf", "mime_type": "application/pdf", "metadata_json": "{}"}
        self.assertEqual(backend._supabase_editor_immutable_storage_path("OD-QA", asset, "A" * 64), f"editor-final/OD-QA/ASSET-QA/{'A' * 64}-legacy.pdf")

    def test_path_components_and_digest_cannot_inject_another_location(self):
        for component in ("../OD", "OD/OTHER", "公文", "", "X" * 161):
            with self.subTest(component=component):
                with self.assertRaisesRegex(ValueError, "editor_storage_identity_invalid"):
                    backend._supabase_editor_staging_storage_path(component, "ASSET-QA", "application/pdf")
        with self.assertRaisesRegex(ValueError, "editor_upload_hash_invalid"):
            backend._supabase_editor_immutable_storage_path("OD-QA", {"id": "ASSET-QA", "mime_type": "application/pdf", "metadata_json": '{"storage_key_version":2}'}, "../other")

    def test_shipping_client_error_codes_are_preserved_but_arbitrary_text_is_not(self):
        source = (Path(__file__).resolve().parents[1] / "app.js").read_text()
        start = source.index("async function editorTusResponseError(")
        end = source.index("function waitForTusRetry(", start)
        codes = set(re.findall(r'code = "(editor_[a-z_]+)"', source[start:end]))
        self.assertGreaterEqual(len(codes), 10)
        for code in codes:
            self.assertEqual(backend.normalized_editor_upload_failure_code(code), code)
        for detail in ("InvalidKey:secret-document.pdf", "editor_tus_error_private_name", "https://private.invalid?token=secret"):
            self.assertEqual(backend.normalized_editor_upload_failure_code(detail), "editor_upload_failed")

    def test_invalid_storage_key_error_is_actionable_without_leaking_provider_text(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node required")
        script = r'''
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const source=fs.readFileSync('app.js','utf8');
const start=source.indexOf('async function editorTusResponseError('), end=source.indexOf('function waitForTusRetry(',start);
const context={Response}; vm.createContext(context);vm.runInContext(source.slice(start,end),context);
(async()=>{for(const body of [JSON.stringify({error:'InvalidKey',message:'secret-person.pdf'}),'Invalid key: secret-person.pdf']) {
const e=await context.editorTusResponseError(new Response(body,{status:400}),'建立上傳');
assert.equal(e.code,'editor_tus_invalid_object_key');assert.equal(e.retryable,false);assert.match(e.message,/不需要修改原檔名/);assert.ok(!e.message.includes('secret-person'));}})().catch(()=>process.exitCode=1);
'''
        result = subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
