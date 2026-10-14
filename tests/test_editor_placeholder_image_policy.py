"""Synthetic privacy and no-AV image lifecycle checks; no production services."""
import copy
import io
import json
import math
import unittest
from unittest import mock

from PIL import Image
import backend
from tests import test_editor_seal_catalog_scope as scope_fixture
from tests import test_five_account_editor_workflow as workflow_fixture


def image_bytes(format="PNG"):
    image = Image.new("RGB", (31, 23), (0, 0, 255))
    stream = io.BytesIO(); image.save(stream, format=format)
    return stream.getvalue()


class EditorPlaceholderPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = scope_fixture.EditorSealCatalogScopeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_supabase_applicant_preview_is_source_independent_and_never_downloads_pixels(self):
        item = self.fixture.catalog_file
        with mock.patch.object(backend, "supabase_require_current_company_seal_file", return_value=item), \
             mock.patch.object(backend, "supabase_storage_download", side_effect=AssertionError("private pixels fetched")) as read, \
             mock.patch.object(backend, "supabase_log_seal_usage") as audit:
            result = backend.supabase_editor_seal_preview("SEAL-2", self.fixture.session, file_id=item["id"], file_sha256=item["file_hash"])
            self.assertTrue(result.startswith(b"\x89PNG"))
            read.assert_not_called()
            self.assertIn("private_pixels=false", audit.call_args.kwargs["detail"])
        with Image.open(io.BytesIO(result)) as image:
            self.assertEqual(image.width, image.height)
            self.assertFalse(any(b > 150 and r < 80 and g < 80 and a > 0 for r,g,b,a in image.convert("RGBA").getdata()))
        changed = {**item, "file_hash": "b"*64, "id": "unrelated-file"}
        self.assertEqual(result, backend.generate_editor_seal_placeholder(changed, "large_seal"))

    def test_preview_geometry_and_version_gates_are_retained(self):
        item = {**self.fixture.catalog_file, "dimension_policy_version": backend.seal_policy.OFFICIAL_POLICY,
                "render_width_mm": 20, "render_height_mm": 40,
                "pixel_width": 250, "pixel_height": 500, "source_aspect_ratio": .5}
        result = backend.generate_editor_seal_placeholder(item, "small_seal")
        with Image.open(io.BytesIO(result)) as image:
            self.assertAlmostEqual(image.width / image.height, .5, delta=.01)
        with mock.patch.object(backend, "supabase_require_current_company_seal_file", return_value=item):
            with self.assertRaisesRegex(ValueError, "hash_mismatch"):
                backend.supabase_editor_seal_preview("SEAL-2", self.fixture.session, file_id=item["id"], file_sha256="f"*64)

    def test_native200_and_native120_geometry_only_for_all_attested_sizes(self):
        import seal_scan_exceptions as native200
        import seal_scan_20261013 as native120
        for registry in (native200, native120):
            for digest,company,seal_id,category,size,w,h,mw,mh,page in registry._ROWS:
                row = {"seal_id":seal_id,"file_hash":digest,"pixel_width":w,"pixel_height":h,
                       "source_aspect_ratio":w/h,"render_width_mm":mw,"render_height_mm":mh,
                       "dimension_validated":True,"dimension_policy_version":registry.POLICY}
                with self.subTest(policy=registry.POLICY,size=size):
                    data=backend.generate_editor_seal_placeholder(row,size)
                    with Image.open(io.BytesIO(data)) as image:
                        self.assertEqual(image.size,(math.ceil(mw*72/25.4*2),math.ceil(mh*72/25.4*2)))
                    # No image path, bytes or Storage operation was available
                    # to this call; only the exact attested physical geometry.


class EditorImageNoAvTests(unittest.TestCase):
    def setUp(self):
        self.fixture = workflow_fixture.FiveAccountEditorWorkflowTestCase()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.conn = self.fixture.conn
        self.session = self.fixture._session_for_user_id(self.fixture.applicant_ids[0])

    def upload(self, data, mime="image/png", suffix="png", *, finalize=True):
        draft = backend.create_official_editor_draft(self.conn, {"company_id": "CO-001", "title": "Synthetic image", "document_category": "合作意向書"}, self.session)
        intent = backend.create_official_editor_upload_intent(self.conn, draft["id"], {
            "asset_kind": "image", "file_name": "synthetic."+suffix, "mime_type": mime,
            "size_bytes": len(data), "sha256": backend.sha256_bytes(data),
        }, self.session)
        backend.store_official_editor_local_upload(self.conn, draft["id"], intent["upload_id"], data, self.session, mime)
        if not finalize: return draft["id"], intent["upload_id"]
        return backend.finalize_official_editor_upload(self.conn, draft["id"], intent["upload_id"], {}, self.session)

    def test_png_jpeg_finalize_without_scanner_and_reopen_as_immutable_assets(self):
        with mock.patch.object(backend, "editor_scan_bytes_for_threats", side_effect=AssertionError("AV called")) as scanner:
            for format, mime, suffix in (("PNG", "image/png", "png"), ("JPEG", "image/jpeg", "jpg")):
                data = image_bytes(format)
                with self.subTest(format=format):
                    result = self.upload(data, mime, suffix)
                    asset = result["asset"]
                    self.assertEqual(asset["scanStatus"], "not_scanned")
                    row = dict(self.conn.execute("SELECT * FROM official_document_editor_assets WHERE id=?", (asset["id"],)).fetchone())
                    backing = dict(self.conn.execute("SELECT * FROM file_objects WHERE id=?", (row["file_object_id"],)).fetchone())
                    self.assertEqual((backing["scan_status"], backing["scan_engine"], backing["last_scan_at"]), ("not_scanned", "", ""))
                    self.assertTrue(backend.editor_asset_preflight_is_ready(row))
                    content, _ = backend._editor_local_asset_bytes(self.conn, row["document_id"], result["editor_state"])
                    self.assertEqual(content[row["id"]], data)
                    self.assertEqual(backend.sha256_bytes(data), row["sha256"])
            scanner.assert_not_called()

    def test_bad_decode_wrong_mime_hash_and_foreign_actor_stay_blocked(self):
        with mock.patch.object(backend, "editor_scan_bytes_for_threats", side_effect=AssertionError("AV called")):
            for data, mime, suffix in ((b"not a PNG", "image/png", "png"), (image_bytes(), "image/jpeg", "jpg"), (image_bytes("JPEG")[:80], "image/jpeg", "jpg")):
                with self.subTest(mime=mime), self.assertRaisesRegex(ValueError, "editor_image_invalid"):
                    self.upload(data, mime, suffix)
            document_id, asset_id = self.upload(image_bytes(), finalize=False)
            foreign = self.fixture._session_for_user_id(self.fixture.applicant_ids[1])
            with self.assertRaises(PermissionError):
                backend.finalize_official_editor_upload(self.conn, document_id, asset_id, {}, foreign)
            with self.assertRaisesRegex(ValueError, "hash_mismatch"):
                backend.finalize_official_editor_upload(self.conn, document_id, asset_id, {"sha256": "f"*64}, self.session)
        for kind in ("attachment", "prepared_pdf", "seal", "seal-vault"):
            self.assertFalse(backend.editor_asset_preflight_is_ready({"asset_kind": kind, "upload_status": "finalized", "preflight_status": "passed", "scan_status": "not_scanned"}))
        self.assertFalse(backend.editor_asset_preflight_is_ready({"asset_kind": "image", "upload_status": "finalized", "preflight_status": "pending", "scan_status": "not_scanned"}))

    def test_local_applicant_preview_never_reads_private_raster(self):
        file = backend.require_current_company_seal_file(self.conn, self.fixture.seal_id)
        with mock.patch.object(backend, "read_file_object_bytes", side_effect=AssertionError("private raster read")) as read:
            result = backend.local_editor_seal_preview(self.conn, self.fixture.seal_id, self.session,
                file_id=file["id"], file_sha256=file["file_hash"])
            self.assertTrue(result.startswith(b"\x89PNG"))
            read.assert_not_called()


if __name__ == "__main__": unittest.main()
