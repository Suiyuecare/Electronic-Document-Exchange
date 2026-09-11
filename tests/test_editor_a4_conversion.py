"""A4 normalization is opt-in, preserves source bytes and retains safety gates."""
from __future__ import annotations

import io
import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, TextStringObject

import backend


def fixture_pdf(width=612, height=792, *, rotation=0, user_unit=1, crop=False):
    document = fitz.open()
    page = document.new_page(width=width, height=height)
    inset = 60 if crop else 15
    page.draw_rect(fitz.Rect(inset, inset, width - inset, height - inset), color=(1, 0, 0), width=2)
    page.insert_text((inset + 10, inset + 25), "A4 conversion isolated fixture", fontsize=12)
    page.insert_text((inset + 10, height - inset - 20), "BOTTOM - preserve every edge", fontsize=12)
    if crop:
        page.set_cropbox(fitz.Rect(40, 40, width - 40, height - 40))
    page.set_rotation(rotation)
    source = document.tobytes(no_new_id=True)
    document.close()
    if user_unit != 1:
        reader = PdfReader(io.BytesIO(source))
        writer = PdfWriter()
        writer.append(reader)
        writer.pages[0][NameObject("/UserUnit")] = NumberObject(user_unit)
        stream = io.BytesIO()
        writer.write(stream)
        source = stream.getvalue()
    return source


class EditorA4GeometryTests(unittest.TestCase):
    def test_all_sizes_rotations_cropbox_and_userunit_fit_without_distortion(self):
        for width, height in ((612, 792), (612, 1008), (841.89, 1190.55), (419.53, 595.28), (900, 480)):
            for rotation in (0, 90, 180, 270):
                for crop, unit in ((False, 1), (True, 1), (True, 2)):
                    with self.subTest(size=(width, height), rotation=rotation, crop=crop, unit=unit):
                        source = fixture_pdf(width, height, rotation=rotation, crop=crop, user_unit=unit)
                        digest = backend.sha256_bytes(source)
                        converted, details = backend.convert_editor_pdf_to_a4(source)
                        self.assertEqual(digest, backend.sha256_bytes(source))
                        checked = backend.inspect_editor_pdf(converted)
                        self.assertEqual(checked["pageCount"], 1)
                        self.assertFalse(checked["requiresA4Conversion"])
                        with fitz.open(stream=source, filetype="pdf") as before, fitz.open(stream=converted, filetype="pdf") as after:
                            self.assertIn("BOTTOM", after[0].get_text())
                            self.assertIn("isolated fixture", after[0].get_text())
                            source_draw = before[0].get_drawings()[0]["rect"] * before[0].rotation_matrix
                            target_draw = after[0].get_drawings()[0]["rect"]
                            self.assertAlmostEqual(source_draw.width / source_draw.height, target_draw.width / target_draw.height, delta=0.0001)
                            self.assertEqual(before[0].rect.width > before[0].rect.height, after[0].rect.width > after[0].rect.height)
                        self.assertGreaterEqual(details["transformations"][0]["offsetXPt"], -0.001)
                        self.assertGreaterEqual(details["transformations"][0]["offsetYPt"], -0.001)

    def test_inspection_is_strict_unless_explicitly_opted_in(self):
        source = fixture_pdf()
        with self.assertRaisesRegex(ValueError, "pdf_page_not_a4:page=1"):
            backend.inspect_editor_pdf(source)
        inspection = backend.inspect_editor_pdf(source, allow_non_a4=True)
        self.assertEqual(inspection["nonA4Pages"][0]["widthMm"], 215.9)
        self.assertEqual(inspection["nonA4Pages"][0]["pageNumber"], 1)

    def test_mixed_pages_and_blank_pages_remain_same_count(self):
        writer = PdfWriter()
        writer.add_blank_page(width=backend.EDOC_A4_WIDTH_PT, height=backend.EDOC_A4_HEIGHT_PT)
        writer.append(PdfReader(io.BytesIO(fixture_pdf())))
        writer.add_blank_page(width=1008, height=612)
        stream = io.BytesIO()
        writer.write(stream)
        converted, _ = backend.convert_editor_pdf_to_a4(stream.getvalue())
        self.assertEqual(backend.inspect_editor_pdf(converted)["pageCount"], 3)

    def test_conversion_does_not_bypass_security_rejections(self):
        source = fixture_pdf()
        variants = []
        for kind in ("encrypted", "signature", "xfa", "javascript", "embedded", "launch"):
            writer = PdfWriter()
            writer.append(PdfReader(io.BytesIO(source)))
            if kind == "encrypted":
                writer.encrypt("test-only-password")
            elif kind == "signature":
                writer._root_object[NameObject("/ByteRange")] = TextStringObject("signature-marker")
            elif kind == "xfa":
                writer._root_object[NameObject("/AcroForm")] = DictionaryObject({NameObject("/XFA"): TextStringObject("isolated")})
            elif kind == "javascript":
                writer.add_js("app.alert('isolated')")
            elif kind == "embedded":
                writer.add_attachment("isolated.txt", b"test")
            elif kind == "launch":
                writer._root_object[NameObject("/OpenAction")] = DictionaryObject({NameObject("/S"): NameObject("/Launch")})
            stream = io.BytesIO()
            writer.write(stream)
            variants.append((kind, stream.getvalue()))
        for kind, data in variants:
            with self.subTest(kind=kind), self.assertRaises(ValueError) as error:
                backend.convert_editor_pdf_to_a4(data)
            self.assertNotIn("pdf_page_not_a4", str(error.exception))

    def test_escaped_javascript_and_nested_signature_are_rejected(self):
        class EscapedJavaScriptName(NameObject):
            def write_to_stream(self, stream, encryption_key=None):
                stream.write(b"/J#61vaScript")

        for kind in ("escaped-js", "nested-signature"):
            writer = PdfWriter()
            writer.append(PdfReader(io.BytesIO(fixture_pdf())))
            if kind == "escaped-js":
                action = DictionaryObject({NameObject("/S"): EscapedJavaScriptName("/JavaScript")})
                writer.pages[0][NameObject("/Annots")] = ArrayObject([DictionaryObject({NameObject("/Subtype"): NameObject("/Link"), NameObject("/A"): action})])
            else:
                writer._root_object[NameObject("/AcroForm")] = DictionaryObject({NameObject("/Fields"): ArrayObject([DictionaryObject({NameObject("/Kids"): ArrayObject([DictionaryObject({NameObject("/FT"): NameObject("/Sig")})])})])})
            stream = io.BytesIO()
            writer.write(stream)
            data = stream.getvalue()
            if kind == "escaped-js":
                self.assertNotIn(b"/JavaScript", data)
            with self.assertRaisesRegex(ValueError, "javascript_not_supported" if kind == "escaped-js" else "digital_signature_not_supported"):
                backend.convert_editor_pdf_to_a4(data)


class EditorA4LocalFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(backend, "STORAGE_DIR", Path(self.tmp.name) / "storage"),
            mock.patch.object(backend, "USE_SUPABASE", False),
            mock.patch.object(backend, "DEPLOYMENT_ENV", "test"),
            mock.patch.object(backend, "EDOC_PDF_EDITOR_V2_COMPANY_MODE", "manual_allowlist"),
            mock.patch.object(backend, "EDOC_PDF_EDITOR_V2_COMPANY_IDS", "CO-001"),
        ]
        for patch in self.patches:
            patch.start()
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        backend.register_sqlite_functions(self.conn)
        self.conn.executescript(backend.SCHEMA)
        backend.seed(self.conn)
        backend.seed_auth(self.conn)
        backend.ensure_allowed_edoc_users(self.conn)
        backend.seed_persistent_registries(self.conn)
        backend.seed_company_seal_module(self.conn)
        self.conn.execute("UPDATE users SET company_id = 'CO-001'")
        user = self.conn.execute("SELECT * FROM users WHERE id = 'USR-008'").fetchone()
        self.session = {"user": backend.public_user(user), "permissions": backend.role_permission_codes(self.conn, user["role"])}
        self.draft = backend.create_official_editor_draft(self.conn, {"company_id": "CO-001", "title": "isolated A4 conversion", "reason": "Test only", "document_category": "合作意向書"}, self.session)

    def tearDown(self):
        self.conn.close()
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def stage(self, data=None, allow=True):
        data = data or fixture_pdf()
        intent = backend.create_official_editor_upload_intent(self.conn, self.draft["id"], {"file_name": "isolated-letter.pdf", "asset_kind": "source_pdf", "mime_type": "application/pdf", "size_bytes": len(data), "sha256": backend.sha256_bytes(data)}, self.session)
        backend.store_official_editor_local_upload(self.conn, self.draft["id"], intent["upload_id"], data, self.session, "application/pdf")
        return backend.finalize_official_editor_upload(self.conn, self.draft["id"], intent["upload_id"], {"allowA4Conversion": allow, "sha256": backend.sha256_bytes(data)}, self.session)

    def convert(self):
        staged = self.stage()
        return backend.convert_official_editor_upload_a4(self.conn, self.draft["id"], staged["asset"]["id"], {
            "confirm": True, "sourceSha256": staged["asset"]["sha256"], "baseRevisionNo": staged["editor_revision"]["revisionNo"],
        }, self.session)

    def test_save_restores_authoritative_a4_lineage_instead_of_trusting_client_links(self):
        converted = self.convert()
        current = backend.get_official_editor_state(self.conn, self.draft["id"], self.session)
        state = copy.deepcopy(current["state"])
        original, derived = state["sourceFiles"]
        original.pop("a4Conversion")
        derived["a4Conversion"] = {"converted": True, "sourceAssetId": "FORGED-ORIGINAL", "sourceSha256": "F" * 64}
        saved = backend.save_official_editor_state(self.conn, self.draft["id"], {
            "revisionNo": current["revisionNo"], "baseManifestSha256": current["manifestSha256"], "state": state,
        }, self.session)
        self.assertTrue(saved["state"]["sourceFiles"][0]["a4Conversion"]["required"])
        self.assertEqual(saved["state"]["sourceFiles"][1]["a4Conversion"], converted["asset"]["a4Conversion"])
        self.assertTrue(backend.preflight_official_editor(self.conn, self.draft["id"], {}, self.session)["preparedFileId"])

    def test_save_and_locked_source_bundle_reject_detached_original_and_changed_source_hash(self):
        self.convert()
        current = backend.get_official_editor_state(self.conn, self.draft["id"], self.session)
        for manipulation, code in (("remove", "editor_a4_original_missing"), ("hash", "editor_asset_hash_mismatch")):
            with self.subTest(manipulation=manipulation):
                state = copy.deepcopy(current["state"])
                if manipulation == "remove":
                    state["sourceFiles"].pop(0)
                    state["sourceFiles"][0].pop("a4Conversion")
                else:
                    state["sourceFiles"][0]["sha256"] = "F" * 64
                with self.assertRaisesRegex(ValueError, code):
                    backend.save_official_editor_state(self.conn, self.draft["id"], {
                        "revisionNo": current["revisionNo"], "baseManifestSha256": current["manifestSha256"], "state": state,
                    }, self.session)
                with self.assertRaisesRegex(ValueError, code):
                    backend._editor_source_bundle_sha256(self.conn, self.draft["id"], state)
        self.assertEqual(backend.get_official_editor_state(self.conn, self.draft["id"], self.session)["revisionNo"], current["revisionNo"])

    def test_supabase_save_and_bundle_enforce_the_same_immutable_lineage(self):
        converted = self.convert()
        latest = backend._editor_latest_revision_row(self.conn, self.draft["id"])
        assets = [dict(row) for row in self.conn.execute("SELECT * FROM official_document_editor_assets").fetchall()]
        def filtered(table, filters, **kwargs):
            self.assertEqual(table, "official_document_editor_assets")
            return [asset for asset in assets if all(asset.get(key) == value for key, value in filters.items())]
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(backend, "supabase_filter_rows", side_effect=filtered))
            stack.enter_context(mock.patch.object(backend, "supabase_official_document_row", return_value={"id": self.draft["id"], "company_id": "CO-001"}))
            stack.enter_context(mock.patch.object(backend, "_supabase_editor_assert_document_access", return_value=self.session["user"]))
            stack.enter_context(mock.patch.object(backend, "_supabase_editor_latest_revision", return_value=latest))
            stack.enter_context(mock.patch.object(backend, "validate_supabase_editor_seal_placements"))
            insert = stack.enter_context(mock.patch.object(backend, "_supabase_insert_editor_revision", return_value=latest))
            stack.enter_context(mock.patch.object(backend, "supabase_insert_official_log"))
            state = copy.deepcopy(converted["editor_state"])
            state["sourceFiles"][1].pop("a4Conversion")
            backend.supabase_save_official_editor_state(self.draft["id"], {
                "revisionNo": latest["revision_no"], "baseManifestSha256": latest["manifest_sha256"], "state": state,
            }, self.session)
            self.assertEqual(insert.call_args.args[1]["sourceFiles"][1]["a4Conversion"], converted["asset"]["a4Conversion"])
            valid_hash = backend._supabase_editor_source_bundle_sha256(self.draft["id"], converted["editor_state"])
            self.assertEqual(valid_hash, backend._editor_source_bundle_sha256(self.conn, self.draft["id"], converted["editor_state"]))
            state["sourceFiles"].pop(0)
            with self.assertRaisesRegex(ValueError, "editor_a4_original_missing"):
                backend.supabase_save_official_editor_state(self.draft["id"], {
                    "revisionNo": latest["revision_no"], "baseManifestSha256": latest["manifest_sha256"], "state": state,
                }, self.session)
            with self.assertRaisesRegex(ValueError, "editor_a4_original_missing"):
                backend._supabase_editor_source_bundle_sha256(self.draft["id"], state)

    def test_original_bytes_remain_verified_even_when_only_derivative_pages_are_visible(self):
        self.convert()
        state = backend.get_official_editor_state(self.conn, self.draft["id"], self.session)["state"]
        original_id = state["sourceFiles"][0]["assetId"]
        self.assertTrue(all(page["sourceAssetId"] != original_id for page in state["pages"]))
        original = self.conn.execute("SELECT * FROM official_document_editor_assets WHERE id = ?", (original_id,)).fetchone()
        read_bytes = backend.read_file_object_bytes
        def corrupted(conn, file_id):
            metadata, data = read_bytes(conn, file_id)
            return metadata, data + b"tampered" if file_id == original["file_object_id"] else data
        with mock.patch.object(backend, "read_file_object_bytes", side_effect=corrupted), self.assertRaisesRegex(ValueError, "editor_asset_hash_mismatch"):
            backend._editor_local_asset_bytes(self.conn, self.draft["id"], state)

    def test_opt_in_stages_immutable_original_and_conversion_adds_separate_a4_asset(self):
        source = fixture_pdf()
        staged = self.stage(source)
        self.assertTrue(staged["a4Conversion"]["required"])
        self.assertEqual(staged["editor_state"]["pages"], [])
        original_id = staged["asset"]["id"]
        with self.assertRaisesRegex(ValueError, "editor_source_pdf_required"):
            backend.preflight_official_editor(self.conn, self.draft["id"], {}, self.session)
        payload = {"confirm": True, "sourceSha256": staged["asset"]["sha256"], "baseRevisionNo": staged["editor_revision"]["revisionNo"]}
        converted = backend.convert_official_editor_upload_a4(self.conn, self.draft["id"], original_id, payload, self.session)
        self.assertNotEqual(converted["asset"]["id"], original_id)
        self.assertEqual(len(converted["editor_state"]["sourceFiles"]), 2)
        self.assertEqual(len(converted["editor_state"]["pages"]), 1)
        self.assertEqual(converted["a4Conversion"]["sourceAssetId"], original_id)
        self.assertTrue(converted["a4Conversion"]["converted"])
        original = self.conn.execute("SELECT * FROM official_document_editor_assets WHERE id = ?", (original_id,)).fetchone()
        self.assertEqual(backend.read_file_object_bytes(self.conn, original["file_object_id"])[1], source)
        self.assertEqual(original["sha256"], backend.sha256_bytes(source))
        repeated = backend.convert_official_editor_upload_a4(self.conn, self.draft["id"], original_id, payload, self.session)
        self.assertEqual(repeated["asset"]["id"], converted["asset"]["id"])
        self.assertEqual(repeated["editor_revision"]["revisionNo"], converted["editor_revision"]["revisionNo"])
        preview = backend.preflight_official_editor(self.conn, self.draft["id"], {}, self.session)
        self.assertTrue(preview["preparedFileId"])

    def test_legacy_finalize_still_rejects_non_a4(self):
        with self.assertRaisesRegex(ValueError, "pdf_page_not_a4"):
            self.stage(allow=False)

    def test_confirmation_hash_and_revision_required_and_cross_owner_denied(self):
        staged = self.stage()
        asset_id = staged["asset"]["id"]
        base = {"confirm": True, "sourceSha256": staged["asset"]["sha256"], "baseRevisionNo": staged["editor_revision"]["revisionNo"]}
        for override, code in (({"confirm": False}, "confirmation_required"), ({"sourceSha256": "F" * 64}, "hash_mismatch"), ({"baseRevisionNo": 0}, "revision_conflict")):
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, code):
                backend.convert_official_editor_upload_a4(self.conn, self.draft["id"], asset_id, {**base, **override}, self.session)
        other = {**self.session, "user": {**self.session["user"], "id": "OTHER-TEST-ACCOUNT", "company_id": "CO-OTHER"}}
        with self.assertRaises(PermissionError):
            backend.convert_official_editor_upload_a4(self.conn, self.draft["id"], asset_id, base, other)

    def test_malware_remains_quarantined_even_with_conversion_opt_in(self):
        with mock.patch.object(backend, "editor_scan_bytes_for_threats", return_value=("未通過", "test-only")), self.assertRaisesRegex(ValueError, "quarantined"):
            self.stage()
        self.assertEqual(backend.get_official_editor_state(self.conn, self.draft["id"], self.session)["state"]["sourceFiles"], [])


class EditorA4SupabaseContractTests(unittest.TestCase):
    def test_supabase_original_staging_uses_atomic_rpc_without_non_a4_editor_pages(self):
        source = fixture_pdf()
        digest = backend.sha256_bytes(source)
        asset = {"id": "ASSET-A4-TEST", "document_id": "DOC-A4-TEST", "asset_kind": "source_pdf",
                 "file_name": "isolated-letter.pdf", "mime_type": "application/pdf", "size_bytes": len(source),
                 "expected_sha256": digest, "storage_bucket": "private-test", "storage_path": "editor/test-stage.pdf",
                 "upload_status": "pending", "metadata_json": json.dumps({"base_revision_no": 1})}
        latest = {"id": "REV-A4-1", "revision_no": 1, "editor_state_json": json.dumps({
            "schemaVersion": 2, "revisionNo": 1, "sourceFiles": [], "pages": [], "elements": []})}
        captured = {}
        final_path = f"editor-final/DOC-A4-TEST/ASSET-A4-TEST/{digest}-isolated-letter.pdf"

        def filter_rows(table, filters, **kwargs):
            self.assertEqual(table, "official_document_editor_assets")
            return [asset]

        def rpc(method, endpoint, payload, **kwargs):
            self.assertEqual((method, endpoint), ("POST", "rpc/edoc_finalize_editor_asset_v2"))
            request = payload["p_request"]
            captured.update(request)
            asset.update(request["asset_patch"])
            return {"committed": True, "document_id": "DOC-A4-TEST", "asset_id": asset["id"],
                    "operation_id": request["operation_id"], "revision_id": request["revision"]["id"],
                    "file_object_id": request["file_object"]["id"], "official_file_id": request["official_file"]["id"]}

        with ExitStack() as stack:
            values = {"require_production_editor_runtime_ready": None,
                      "supabase_official_document_row": {"id": "DOC-A4-TEST", "company_id": "CO-TEST"},
                      "_supabase_editor_assert_document_access": {"id": "USER-TEST", "name": "Isolated"},
                      "_supabase_editor_latest_revision": latest,
                      "supabase_storage_download": source,
                      "editor_scan_bytes_for_threats": ("已通過", "test-clean"),
                      "_supabase_promote_editor_asset_to_immutable_storage": (final_path, "JOB-TEST", "LEASE-TEST"),
                      "supabase_official_raw_document_files": [],
                      "_supabase_assert_finalized_editor_asset_immutable": {},
                      "supabase_storage_delete": None}
            for name, value in values.items():
                stack.enter_context(mock.patch.object(backend, name, return_value=value))
            stack.enter_context(mock.patch.object(backend, "supabase_filter_rows", side_effect=filter_rows))
            stack.enter_context(mock.patch.object(backend, "supabase_request", side_effect=rpc))
            result = backend.supabase_finalize_official_editor_upload("DOC-A4-TEST", asset["id"], {"allowA4Conversion": True, "sha256": digest}, {"user": {"id": "USER-TEST"}})
        self.assertTrue(result["a4Conversion"]["required"])
        self.assertEqual(result["editor_state"]["pages"], [])
        self.assertEqual(captured["official_file"]["file_hash"], digest)
        self.assertEqual(captured["file_object"]["size_bytes"], len(source))
        self.assertEqual(captured["asset_patch"]["page_count"], 1)
        self.assertEqual(captured["expected_base_revision_no"], 1)

    def test_supabase_conversion_never_mints_capability_and_reuses_scan_finalize(self):
        source = fixture_pdf()
        digest = backend.sha256_bytes(source)
        asset = {"id": "SOURCE-A4", "document_id": "DOC-A4", "asset_kind": "source_pdf",
                 "file_name": "isolated-letter.pdf", "sha256": digest, "upload_status": "finalized",
                 "scan_status": "passed", "preflight_status": "passed", "metadata_json": json.dumps({"a4_conversion": {"required": True}})}
        latest = {"id": "REV-A4", "revision_no": 2, "editor_state_json": json.dumps({"sourceFiles": [{"assetId": "SOURCE-A4"}]})}
        with ExitStack() as stack:
            values = {"require_production_editor_runtime_ready": None,
                      "supabase_official_document_row": {"id": "DOC-A4", "company_id": "CO-TEST"},
                      "_supabase_editor_assert_document_access": {"id": "USER-TEST"},
                      "_supabase_editor_latest_revision": latest,
                      "_supabase_assert_finalized_editor_asset_immutable": {"storage_key": "private-original", "bucket": "private-test"},
                      "supabase_storage_download": source}
            for name, value in values.items():
                stack.enter_context(mock.patch.object(backend, name, return_value=value))
            stack.enter_context(mock.patch.object(backend, "supabase_filter_rows", side_effect=[[asset], []]))
            intent = stack.enter_context(mock.patch.object(backend, "supabase_create_official_editor_upload_intent", return_value={"path": "private-derivative-stage", "bucket": "private-test", "upload_id": "DERIVED-A4"}))
            upload = stack.enter_context(mock.patch.object(backend, "supabase_storage_upload"))
            finalize = stack.enter_context(mock.patch.object(backend, "supabase_finalize_official_editor_upload", return_value={"success": True}))
            result = backend.supabase_convert_official_editor_upload_a4("DOC-A4", "SOURCE-A4", {"confirm": True, "sourceSha256": digest, "baseRevisionNo": 2}, {"user": {"id": "USER-TEST"}})
        self.assertTrue(result["success"])
        self.assertFalse(intent.call_args.kwargs["issue_upload_capability"])
        metadata = intent.call_args.kwargs["internal_metadata"]
        self.assertEqual(metadata["a4_conversion"]["sourceSha256"], digest)
        self.assertEqual(metadata["a4_source_revision_no"], 2)
        derived = upload.call_args.args[1]
        self.assertFalse(backend.inspect_editor_pdf(derived)["requiresA4Conversion"])
        self.assertEqual(finalize.call_args.args[2], {"sha256": backend.sha256_bytes(derived)})

    def test_supabase_conversion_is_gated_before_reads_or_writes(self):
        with mock.patch.object(backend, "require_production_editor_runtime_ready", side_effect=ValueError("editor_runtime_maintenance")), mock.patch.object(backend, "supabase_official_document_row") as read:
            with self.assertRaisesRegex(ValueError, "editor_runtime_maintenance"):
                backend.supabase_convert_official_editor_upload_a4("DOC-TEST", "ASSET-TEST", {}, None)
        read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
