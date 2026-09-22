"""General-document company/style/size/seam parity using isolated synthetic data.

No real employee, stamp, Supabase project, or exchange provider is contacted.
The Supabase tests execute its validators and final verifier over a local table
and storage adapter; they do not claim a live Postgres integration test.
"""
from __future__ import annotations

import base64
import copy
import io
import unittest
from contextlib import ExitStack
from unittest import mock

import fitz
from PIL import Image
from reportlab.pdfgen import canvas

import backend
from editor_seam import validate_seam_groups, validate_seam_positions
from tests import test_five_account_editor_workflow as workflow_fixture


class GeneralDocumentSealWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.fixture = workflow_fixture.FiveAccountEditorWorkflowTestCase()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.conn = self.fixture.conn
        self.session = self.fixture._session_for_user_id(self.fixture.applicant_ids[0])
        self.large = self.fixture.seal_id
        self.small = self._seal_id("establishment_seal", "small_seal")
        self.bank = self._seal_id("bank_seal", "large_seal")
        self._upload(self.small, (0, 0, 190, 255))
        self._upload(self.bank, (180, 0, 180, 255))

    def _seal_id(self, category, size, company="CO-001"):
        row = self.conn.execute(
            "SELECT id FROM company_seals WHERE company_id=? AND seal_category=? AND seal_size_type=?",
            (company, category, size),
        ).fetchone()
        self.assertIsNotNone(row)
        return row[0]

    def _upload(self, seal_id, color):
        # Synthetic pixels only. Never edit or use a user's actual seal in tests.
        output = io.BytesIO()
        Image.new("RGBA", (400, 400), color).save(output, format="PNG")
        return backend.upload_company_seal_file(self.conn, seal_id, {
            "file_name": "synthetic-general-document-seal.png",
            "file_mime_type": "image/png",
            "content_base64": base64.b64encode(output.getvalue()).decode("ascii"),
            "actor": "isolated-regression",
        })

    def _draft(self):
        source = io.BytesIO()
        document = canvas.Canvas(source, pagesize=(backend.EDOC_A4_WIDTH_PT, backend.EDOC_A4_HEIGHT_PT))
        for index in range(3):
            document.drawString(60, 790, f"Synthetic general document page {index + 1}")
            document.showPage()
        document.save()
        source_bytes = source.getvalue()
        draft = backend.create_official_editor_draft(self.conn, {
            "company_id": "CO-001", "title": "一般文件多款印章隔離驗收",
            "request_reason": "大小章與兩組不同位置騎縫章", "document_category": "服務委託合約",
            "dispatch_method": "no_dispatch_required",
        }, self.session)
        document_id = draft["document_id"]
        intent = backend.create_official_editor_upload_intent(self.conn, document_id, {
            "asset_kind": "source_pdf", "file_name": "synthetic-general-document.pdf",
            "mime_type": "application/pdf", "size_bytes": len(source_bytes),
            "sha256": backend.sha256_bytes(source_bytes),
        }, self.session)
        backend.store_official_editor_local_upload(self.conn, document_id, intent["upload_id"], source_bytes, self.session, "application/pdf")
        result = backend.finalize_official_editor_upload(self.conn, document_id, intent["upload_id"], {
            "sha256": backend.sha256_bytes(source_bytes),
        }, self.session)
        return document_id, result["editor_revision"], source_bytes

    def _element(self, identity, seal_id, page, x, y, **properties):
        seal = backend.company_seal_row(self.conn, seal_id)
        current = backend.require_current_company_seal_file(self.conn, seal_id)
        profile = backend.company_seal_file_dimension_profile(seal["seal_size_type"], current)
        return {
            "id": identity, "kind": "seal", "pageId": page["pageId"],
            "x": x, "y": y, "width": profile["width_pt"], "height": profile["height_pt"],
            "rotation": 0, "opacity": 1, "zIndex": 10,
            "properties": {"sealId": seal_id, "sealFileId": current["id"],
                           "sealFileSha256": current["file_hash"], **properties},
        }

    def _combined_state(self, revision):
        state = copy.deepcopy(revision["state"])
        state["elements"] = [
            self._element("LARGE-GENERAL", self.large, state["pages"][0], 71.125, 121.25),
            self._element("SMALL-ESTABLISHMENT", self.small, state["pages"][2], 210.5, 151.75),
        ]
        for group, top in enumerate((190, 430)):
            for part in range(2):
                page = state["pages"][group + part]
                element = self._element(f"BANK-SEAM-{group}-{part}", self.bank, page, 0, 0,
                    seamGroupId=f"GENERAL-SEAM-{group}", seamMode="pair", seamPartCount=2, seamPartIndex=part)
                element["x"] = round(page["widthPt"] - element["width"], 4) if part == 0 else 0
                element["y"] = round(page["heightPt"] - top - element["height"], 4)
                element["zIndex"] = 20 + group * 2 + part
                state["elements"].append(element)
        return state

    def _save(self, document_id, revision, state):
        return backend.save_official_editor_state(self.conn, document_id, {
            "revisionNo": revision["revisionNo"], "baseManifestSha256": revision["manifestSha256"], "state": state,
        }, self.session)

    def _submitted(self):
        document_id, revision, source = self._draft()
        saved = self._save(document_id, revision, self._combined_state(revision))
        preflight = backend.preflight_official_editor(self.conn, document_id, {
            "editorRevisionId": saved["id"], "manifestSha256": saved["manifestSha256"],
        }, self.session)
        detail = backend.submit_official_document(self.conn, document_id, {
            key: preflight[key] for key in ("editorRevisionId", "manifestSha256", "preparedFileId", "preparedSha256")
        }, self.session)
        return detail, preflight, saved, source

    def _supabase_adapter(self):
        def rows(table, filters, **kwargs):
            where = " AND ".join(f"{key}=?" for key in filters)
            result = [dict(row) for row in self.conn.execute(f"SELECT * FROM {table} WHERE {where}", tuple(filters.values()))]
            if kwargs.get("order") == "version.desc":
                result.sort(key=lambda row: row["version"], reverse=True)
            return result[:kwargs["limit"]] if kwargs.get("limit") else result

        def get(table, identity):
            result = rows(table, {"id": identity})
            return result[0] if result else None

        def download(key, bucket):
            row = self.conn.execute("SELECT id FROM file_objects WHERE storage_key=?", (key,)).fetchone()
            self.assertIsNotNone(row)
            return backend.read_file_object_bytes(self.conn, row[0])[1]

        stack = ExitStack()
        stack.enter_context(mock.patch.object(backend, "supabase_filter_rows", side_effect=rows))
        stack.enter_context(mock.patch.object(backend, "supabase_get", side_effect=get))
        stack.enter_context(mock.patch.object(backend, "supabase_storage_download", side_effect=download))
        return stack

    def _assert_rendered_placements(self, output, state):
        with fitz.open(stream=output, filetype="pdf") as document:
            self.assertEqual(len(document), 3)
            for element in state["elements"]:
                page_index = next(i for i, page in enumerate(state["pages"]) if page["pageId"] == element["pageId"])
                page = document[page_index]
                image = page.get_pixmap(alpha=False)
                raster = Image.frombytes("RGB", (image.width, image.height), image.samples)
                props = element["properties"]
                x = element["x"] + element["width"] / 2
                if "seamPartIndex" in props:
                    x = element["x"] + element["width"] * (0.75 if props["seamPartIndex"] == 0 else 0.25)
                y = state["pages"][page_index]["heightPt"] - element["y"] - element["height"] / 2
                r, g, b = raster.getpixel((round(x), round(y)))
                if props["sealId"] == self.large:
                    self.assertTrue(r > 100 and g < 60 and b < 60)
                elif props["sealId"] == self.small:
                    self.assertTrue(b > 100 and r < 60 and g < 60)
                else:
                    self.assertTrue(r > 100 and b > 100 and g < 60)

    def test_general_document_large_small_and_independent_seams_complete_actual_approval(self):
        detail, preflight, saved, source = self._submitted()
        self.assertEqual(detail["source_type"], "uploaded_pdf")
        locked = copy.deepcopy(detail["stamp_request"])
        positions = locked["stamp_positions"]
        self.assertEqual([position["seal_id"] for position in positions], [self.large, self.small, self.bank, self.bank, self.bank, self.bank])
        self.assertEqual(len({position["locked_seal_file_id"] for position in positions}), 3)
        self.assertEqual(len(validate_seam_groups(saved["state"])), 2)
        validate_seam_positions(saved["state"], positions)
        for element, position in zip(saved["state"]["elements"], positions):
            for key in ("x", "y", "width", "height"):
                self.assertAlmostEqual(element[key], position[key], delta=0.001)
        self.assertAlmostEqual(positions[0]["width"] * 25.4 / 72, 30, delta=0.01)
        self.assertAlmostEqual(positions[1]["width"] * 25.4 / 72, 18, delta=0.01)

        # Changed current images must not silently replace any selected version.
        self._upload(self.small, (0, 190, 0, 255))
        self._upload(self.bank, (190, 190, 0, 255))
        approved = self.fixture._approve_and_stamp(detail)
        final = next(file for file in approved["files"] if file["file_type"] == "stamped_pdf")
        _, _, output = backend.official_document_download_file(self.conn, detail["id"], final["id"], self.session)
        self._assert_rendered_placements(output, saved["state"])
        self.assertEqual(approved["stamp_request"]["stamp_positions"], positions)
        state_after = backend.get_official_editor_state(self.conn, detail["id"], self.session)
        self.assertEqual(state_after["state"], saved["state"])
        original = next(file for file in approved["files"] if file["file_type"] == "original_pdf")
        self.assertEqual(backend.official_document_download_file(self.conn, detail["id"], original["id"], self.session)[2], source)
        with self.assertRaisesRegex(ValueError, "editor_locked_after_submit"):
            self._save(detail["id"], saved, self._combined_state(saved))

    def test_supabase_validators_and_locked_renderer_match_combined_local_workflow(self):
        document_id, revision, _ = self._draft()
        state = self._combined_state(revision)
        local_state, remote_state = copy.deepcopy(state), copy.deepcopy(state)
        backend.validate_editor_seal_placements(self.conn, "CO-001", local_state)
        with self._supabase_adapter():
            backend.validate_supabase_editor_seal_placements("CO-001", remote_state)
        self.assertEqual(remote_state, local_state)

        detail, _, saved, _ = self._submitted()
        local = backend.verify_locked_editor_for_stamp(self.conn, detail, detail["stamp_request"])
        with self._supabase_adapter():
            remote = backend.supabase_verify_locked_editor_for_stamp(detail, detail["stamp_request"])
        for key in ("state", "positions", "seal_assets", "prepared_bytes", "renderer_version"):
            self.assertEqual(remote[key], local[key], key)
        output, _, metadata = backend.stamp_prepared_pdf_with_locked_seals(remote)
        self.assertEqual(metadata["distinct_seal_versions"], 3)
        self.assertEqual(metadata["seam_group_count"], 2)
        self._assert_rendered_placements(output, saved["state"])

    def test_saved_styles_stay_bound_but_new_placements_cannot_select_retired_versions(self):
        document_id, revision, _ = self._draft()
        saved = self._save(document_id, revision, self._combined_state(revision))
        old_file = saved["state"]["elements"][1]["properties"]["sealFileId"]
        self._upload(self.small, (0, 190, 0, 255))
        moved = copy.deepcopy(saved["state"])
        moved["elements"][1]["x"] += 12.5
        reopened = self._save(document_id, saved, moved)
        self.assertEqual(reopened["state"]["elements"][1]["properties"]["sealFileId"], old_file)
        with self._supabase_adapter():
            backend.validate_supabase_editor_seal_placements("CO-001", copy.deepcopy(moved), previous_state=saved["state"])
        added = copy.deepcopy(moved)
        duplicate = copy.deepcopy(added["elements"][1])
        duplicate["id"] = "NEW-PLACEMENT-OLD-VERSION"
        added["elements"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "editor_seal_file_must_be_current"):
            self._save(document_id, reopened, added)
        with self._supabase_adapter(), self.assertRaisesRegex(ValueError, "editor_seal_file_must_be_current"):
            backend.validate_supabase_editor_seal_placements("CO-001", added, previous_state=reopened["state"])

    def test_cross_company_inactive_and_resized_placements_fail_in_both_backends(self):
        document_id, revision, _ = self._draft()
        state = self._combined_state(revision)
        cases = [("company", "company_mismatch"), ("inactive", "inactive_seal"), ("resized", "seal_.*(size|dimension)")]
        for case, expected in cases:
            with self.subTest(case=case):
                attempted = copy.deepcopy(state)
                if case == "company":
                    self.conn.execute("UPDATE company_seals SET company_id='CO-002' WHERE id=?", (self.small,))
                elif case == "inactive":
                    self.conn.execute("UPDATE company_seals SET is_active=0 WHERE id=?", (self.small,))
                else:
                    attempted["elements"][1]["width"] += 30
                try:
                    with self.assertRaisesRegex(ValueError, expected):
                        self._save(document_id, revision, attempted)
                    with self._supabase_adapter(), self.assertRaisesRegex(ValueError, expected):
                        backend.validate_supabase_editor_seal_placements("CO-001", copy.deepcopy(attempted))
                    self.assertEqual(backend.get_official_editor_state(self.conn, document_id, self.session)["id"], revision["id"])
                finally:
                    self.conn.execute("UPDATE company_seals SET company_id='CO-001', is_active=1 WHERE id=?", (self.small,))

    def test_secondary_seal_hash_tamper_stops_local_and_supabase_final_render(self):
        detail, _, _, _ = self._submitted()
        request = detail["stamp_request"]
        file_id = request["stamp_positions"][1]["locked_seal_file_id"]
        object_id = self.conn.execute("SELECT file_object_id FROM company_seal_files WHERE id=?", (file_id,)).fetchone()[0]
        original_read = backend.read_file_object_bytes

        def tampered(conn, identity):
            metadata, data = original_read(conn, identity)
            return metadata, b"synthetic-tampered-secondary-seal" if identity == object_id else data

        with mock.patch.object(backend, "read_file_object_bytes", side_effect=tampered):
            with self.assertRaisesRegex(ValueError, "editor_seal_hash_mismatch"):
                backend.verify_locked_editor_for_stamp(self.conn, detail, request)
            with self._supabase_adapter(), self.assertRaisesRegex(ValueError, "editor_seal_hash_mismatch"):
                backend.supabase_verify_locked_editor_for_stamp(detail, request)


if __name__ == "__main__":
    unittest.main()
