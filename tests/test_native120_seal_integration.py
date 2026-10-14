"""Exact six-source calibration/native rendering; isolated, no live mutations."""
import copy
import hashlib
import io
import json
import math
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

import fitz
from PIL import Image

import backend
import seal_policy
import seal_scan_exceptions as facade
import seal_scan_20261013 as scan
from tests import test_editor_grouped_seam as seam_fixture


def row_for(values):
    digest, company, seal_id, category, size, w, h, mw, mh, page = values
    return {"seal_id": seal_id, "file_hash": digest, "pixel_width": w, "pixel_height": h,
            "source_aspect_ratio": w / h, "render_width_mm": mw, "render_height_mm": mh,
            "dimension_policy_version": scan.POLICY, "dimension_validated": True}


def seal_for(values):
    return {"id": values[2], "company_id": values[1], "seal_category": values[3],
            "seal_size_type": values[4], "is_active": True}


class Native120RegistryTests(unittest.TestCase):
    def test_exact_six_source_and_three_units_without_taipei_alternative(self):
        self.assertEqual(len(scan._ROWS), 6)
        self.assertEqual(len({r[0] for r in scan._ROWS}), 6)
        self.assertEqual({r[1] for r in scan._ROWS}, {"CO-007", "FINCO-AE264D87483E", "FINCO-D7FAD93DE9AE"})
        self.assertEqual(len(facade._ROWS), 22)
        self.assertNotEqual(scan.SOURCE_SHA256, facade.SOURCE_SHA256)
        self.assertFalse(facade.is_native_policy("native-scan-120dpi-invented"))
        for r in scan._ROWS:
            entries = facade.approved_metadata(seal_for(r))
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["source_pdf_sha256"], scan.SOURCE_SHA256)
            self.assertEqual(entries[0]["calibration_dpi"], 120)
            expected_category = "establishment_seal" if r[1] == "CO-007" else "official_seal"
            self.assertEqual(r[3], expected_category)
            self.assertEqual(r[7:9], (round(r[5] * 25.4 / 120, 3), round(r[6] * 25.4 / 120, 3)))
        self.assertEqual(facade.approved_metadata({**seal_for(scan._ROWS[4]), "company_id": "CO-008"}), [])

    def test_all_six_current_metadata_and_exact_locked_conversion(self):
        for r in scan._ROWS:
            row = row_for(r)
            self.assertTrue(backend.company_seal_file_dimension_is_valid(row, r[4]))
            self.assertTrue(seal_policy.category_policy_valid(r[3], r[4], row))
            profile = backend.company_seal_file_dimension_profile(r[4], row, current=True)
            self.assertEqual((profile["width_mm"], profile["height_mm"]), r[7:9])
            self.assertEqual(profile["calibration_dpi"], 120)
            api = backend.company_seal_api_dimension_metadata(r[4], row, r[3])
            self.assertEqual(api["dimension_policy_version"], scan.POLICY)
            self.assertEqual(api["calibration_dpi"], 120)
            self.assertTrue(api["size_locked"])
            actual = backend.canonical_company_seal_dimensions_pt(r[4], render_width_mm=r[7], render_height_mm=r[8], allow_unspecified=True, dimension_policy_version=scan.POLICY)
            self.assertEqual(actual, (profile["width_pt"], profile["height_pt"]))
            with self.assertRaisesRegex(ValueError, "seal_size_locked"):
                backend.canonical_company_seal_dimensions_pt(r[4], actual[0] + 2, actual[1], render_width_mm=r[7], render_height_mm=r[8], dimension_policy_version=scan.POLICY)

    def test_forged_hash_slot_size_geometry_types_and_old_policy_cannot_attest(self):
        r = scan._ROWS[0]
        row = row_for(r)
        mutations = (("file_hash", "0" * 64), ("seal_id", "CSEAL-CO-008-EST-L"),
                     ("pixel_width", r[5] + 1), ("pixel_width", str(r[5])), ("pixel_height", True),
                     ("pixel_width", r[5] + .1), ("source_aspect_ratio", 1),
                     ("render_width_mm", r[7] + .001), ("render_height_mm", float("nan")),
                     ("render_width_mm", True), ("render_height_mm", "26.247"),
                     ("dimension_validated", "false"), ("dimension_validated", 2),
                     ("dimension_policy_version", facade.POLICY))
        for key, value in mutations:
            with self.subTest(key=key, value=repr(value)):
                self.assertIsNone(facade.file_entry({**row, key: value}, r[4]))
        self.assertFalse(seal_policy.category_policy_valid("official_seal", r[4], row))
        self.assertIsNone(facade.file_entry(row, "small_seal"))
        self.assertTrue(facade.file_entry({**row, "dimension_validated": 1}, r[4]))
        self.assertIsNone(facade.upload_match({**seal_for(r), "company_id": "CO-008"}, r[0], r[5], r[6], r[7], r[8]))
        with self.assertRaisesRegex(ValueError, "geometry_mismatch"):
            facade.upload_match(seal_for(r), r[0], r[5], r[6], r[7] + .001, r[8])

    def test_sqlite_function_uses_exact_new_slot_hash_category_and_company(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        backend.register_sqlite_functions(conn)
        sql = "select edoc_approved_original_scan_matches(" + ",".join("?" for _ in range(12)) + ")"
        for r in scan._ROWS:
            args = (r[2], r[1], r[3], r[4], r[0], r[5], r[6], r[5] / r[6], r[7], r[8], scan.POLICY, True)
            self.assertEqual(conn.execute(sql, args).fetchone()[0], 1)
            for offset, value in ((1, "CO-008"), (2, "general_seal"), (4, "f" * 64), (10, facade.POLICY)):
                bad = list(args); bad[offset] = value
                self.assertEqual(conn.execute(sql, bad).fetchone()[0], 0)

    def test_unknown_native120_image_keeps_ordinary250_resolution_guard(self):
        image = Image.new("RGBA", (125, 124), (180, 0, 0, 255))
        stream = io.BytesIO(); image.save(stream, "PNG")
        with self.assertRaisesRegex(ValueError, "resolution_too_low"):
            backend.validate_seal_file_upload("synthetic.png", "image/png", stream.getvalue(), "large_seal", 26.458, 26.247, "official_seal")
        self.assertEqual(backend.EDOC_SEAL_CALIBRATION_DPI, 250)

    def test_supabase_usable_current_still_requires_owner_hash_av_and_backing(self):
        r = scan._ROWS[0]
        row = {**row_for(r), "id": "SFILE-SYNTHETIC", "file_object_id": "OBJ-SYNTHETIC", "is_current": True,
               "file_mime_type": "image/png", "file_size": 123, "file_storage_key": "private/synthetic.png"}
        obj = {"id": row["file_object_id"], "sha256": r[0], "size_bytes": 123, "mime_type": "image/png",
               "storage_key": row["file_storage_key"], "scan_status": "clean"}
        def get(table, identity):
            return obj if table == "file_objects" else seal_for(r)
        with mock.patch.object(backend, "supabase_get", side_effect=get), mock.patch.object(backend, "supabase_seal_backing_exists", return_value=True) as backing:
            self.assertTrue(backend.supabase_seal_file_with_backing_status(row)["usable"])
            obj["scan_status"] = "quarantined"
            self.assertFalse(backend.supabase_seal_file_with_backing_status(row)["usable"])
            obj["scan_status"] = "clean"; obj["sha256"] = "0" * 64
            self.assertFalse(backend.supabase_seal_file_with_backing_status(row)["usable"])
            obj["sha256"] = r[0]; backing.return_value = False
            self.assertFalse(backend.supabase_seal_file_with_backing_status(row)["usable"])
        with mock.patch.object(backend, "supabase_get", side_effect=lambda table, identity: obj if table == "file_objects" else {**seal_for(r), "company_id": "CO-008"}), mock.patch.object(backend, "supabase_seal_backing_exists", return_value=True):
            self.assertFalse(backend.supabase_seal_file_with_backing_status(row)["usable"])

    def test_private_raw_dct_prepared_pngs_match_final_manifest_and_decode(self):
        folder = Path(__file__).resolve().parents[2] / "artifacts/seal-registration-20261013-aiwuxian/pending-calibration"
        if not folder.exists():
            self.skipTest("private user-provided originals are not available in this environment")
        manifest = json.loads((folder / "registration-manifest.json").read_text())
        self.assertEqual(manifest["source_pdf_sha256"], scan.SOURCE_SHA256)
        self.assertEqual(len(manifest["entries"]), 6)
        for r in scan._ROWS:
            candidate = next(item for item in manifest["entries"] if item["existing_seal_slot_id"] == r[2])
            data = (folder / candidate["png_file"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), r[0])
            result = backend.validate_seal_file_upload(candidate["png_file"], "image/png", data, r[4], r[7], r[8], r[3], seal_for(r))
            self.assertEqual(result["dimension_policy_version"], scan.POLICY)
            self.assertEqual((result["pixel_width"], result["pixel_height"]), r[5:7])


class Native120OutputTests(unittest.TestCase):
    def test_native_pixels_and_physical_affine_rotation_opacity_for_all_six(self):
        for r in scan._ROWS:
            image = Image.new("RGBA", r[5:7], (180, 0, 0, 255))
            image.paste((0, 0, 180, 255), (0, 0, r[5], 8))
            stream = io.BytesIO(); image.save(stream, "PNG"); original = stream.getvalue()
            original_hash = hashlib.sha256(original).hexdigest()
            width, height = r[7] * 72 / 25.4, r[8] * 72 / 25.4
            for page_rotation in (0, 90, 180, 270):
                for seal_rotation in (0, 90, 180, 270, 35):
                    for opacity in (1, .5):
                        page_def = {"pageId": "native", "order": 1, "widthPt": 595.2756, "heightPt": 841.8898, "rotation": page_rotation}
                        element = {"id": "stamp", "kind": "seal", "pageId": "native", "x": 200, "y": 300,
                                   "width": width, "height": height, "rotation": seal_rotation, "opacity": opacity, "zIndex": 1,
                                   "properties": {"sealFileId": "SYNTHETIC", "sealFileSha256": original_hash}}
                        doc = fitz.open(); doc.new_page(width=page_def["widthPt"], height=page_def["heightPt"]).set_rotation(page_rotation)
                        prepared = doc.tobytes(); doc.close()
                        position = seam_fixture.locked_position(element)
                        position["locked_dimension_policy_version"] = scan.POLICY
                        locked = {"state": {"pages": [page_def], "elements": [element]}, "prepared_bytes": prepared,
                                  "positions": [position], "seal_assets": {"SYNTHETIC": {"data": original, "mime_type": "image/png"}}, "renderer_version": "synthetic"}
                        result, _, _ = backend.stamp_prepared_pdf_with_locked_seals(locked)
                        with fitz.open(stream=result, filetype="pdf") as output:
                            info = output[0].get_image_info()[0]
                            self.assertEqual((info["width"], info["height"]), r[5:7])
                            a, b, c, d, _, _ = info["transform"]
                            self.assertAlmostEqual(math.hypot(a, b), width, delta=.001)
                            self.assertAlmostEqual(math.hypot(c, d), height, delta=.001)
                            raster = output[0].get_images(full=True)[0]
                            embedded = Image.open(io.BytesIO(output.extract_image(raster[0])["image"]))
                            self.assertEqual(embedded.convert("RGB").tobytes(), image.convert("RGB").tobytes())
                            if opacity < 1:
                                alpha = Image.open(io.BytesIO(output.extract_image(raster[1])["image"]))
                                self.assertEqual(alpha.size, r[5:7])
                                self.assertTrue(126 <= alpha.getpixel((10, 20)) <= 129)
            self.assertEqual(hashlib.sha256(original).hexdigest(), original_hash)

    def test_grouped_five_plus_two_keeps_native_canvas_at_each_edge(self):
        for r in scan._ROWS[::2]:
            width, height = r[7] * 72 / 25.4, r[8] * 72 / 25.4
            stream = io.BytesIO(); Image.new("RGBA", r[5:7], (180, 0, 0, 255)).save(stream, "PNG")
            for edge in ("left", "right", "top", "bottom"):
                for rotation in (0, 90, 180, 270):
                    state = seam_fixture.grouped_fixture(7, edge, rotations=(rotation,), size=width, height_size=height)
                    self.assertEqual([len(group) for group in backend.validate_seam_groups(state).values()], [5, 2])
                    doc = fitz.open()
                    for definition in state["pages"]:
                        doc.new_page(width=definition["widthPt"], height=definition["heightPt"]).set_rotation(rotation)
                    prepared = doc.tobytes(); doc.close()
                    locked = {"state": state, "prepared_bytes": prepared, "positions": [seam_fixture.locked_position(item) for item in state["elements"]],
                              "seal_assets": {"synthetic-file": {"data": stream.getvalue(), "mime_type": "image/png"}}, "renderer_version": "synthetic"}
                    result, _, meta = backend.stamp_prepared_pdf_with_locked_seals(locked)
                    self.assertEqual((meta["seam_group_count"], meta["seal_count"]), (2, 7))
                    with fitz.open(stream=result, filetype="pdf") as output:
                        for page in output:
                            info = page.get_image_info()[0]
                            self.assertEqual((info["width"], info["height"]), r[5:7])
                            box = fitz.Rect(info["bbox"])
                            self.assertAlmostEqual(box.width, width, delta=.001)
                            self.assertAlmostEqual(box.height, height, delta=.001)


if __name__ == "__main__":
    unittest.main()
