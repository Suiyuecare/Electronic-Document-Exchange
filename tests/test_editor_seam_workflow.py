"""Synthetic seam seals through the real isolated approval and download path."""
from __future__ import annotations

import copy
import io
import json
import os
import unittest
from pathlib import Path

import fitz
from PIL import Image
from reportlab.pdfgen import canvas

import backend
from editor_seam import validate_seam_groups, validate_seam_positions
from tests import test_five_account_editor_workflow as workflow_fixture


class EditorSeamPositionPrecisionTest(unittest.TestCase):
    def test_v2_page_references_keep_four_decimal_geometry_and_legacy_keeps_two(self):
        geometry = {"x": 510.2362, "y": 576.8504, "width": 85.0394, "height": 85.0394}
        for reference_key in ("page_ref", "pageRef", "pageId"):
            with self.subTest(reference_key=reference_key):
                position = backend.official_stamp_positions_payload({"stamp_positions": [{**geometry, reference_key: "PAGE-SEAM-FIXTURE"}]}, "SEAL-FIXTURE")[0]
                self.assertEqual(position["page_ref"], "PAGE-SEAM-FIXTURE")
                for key, value in geometry.items():
                    self.assertEqual(position[key], value)
        legacy = backend.official_stamp_positions_payload({"stamp_positions": [geometry]}, "SEAL-FIXTURE")[0]
        for key, value in geometry.items():
            self.assertEqual(legacy[key], round(value, 2))


class EditorSeamWorkflowTest(unittest.TestCase):
    def setUp(self):
        # Composition deliberately avoids inheriting/discovering the five-account
        # suite again. Its fixtures stay entirely in memory and temporary storage.
        self.fixture = workflow_fixture.FiveAccountEditorWorkflowTestCase()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.conn = self.fixture.conn

    @staticmethod
    def three_page_pdf():
        stream = io.BytesIO()
        document = canvas.Canvas(stream, pagesize=(backend.EDOC_A4_WIDTH_PT, backend.EDOC_A4_HEIGHT_PT))
        for index in range(3):
            document.drawString(70, 780, f"Synthetic seam approval fixture - page {index + 1}")
            document.drawString(70, 750, "No employee data; no external document exchange.")
            document.showPage()
        document.save()
        return stream.getvalue()

    def assert_half_seals_rendered(self, pdf_bytes, state):
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            self.assertEqual(len(document), 3)
            for page_index, page in enumerate(document):
                raster = page.get_pixmap(alpha=False)
                image = Image.frombytes("RGB", (raster.width, raster.height), raster.samples)
                red = [(x, y) for y in range(image.height) for x in range(image.width)
                       if (lambda color: color[0] > 80 and color[1] < 80 and color[2] < 80)(image.getpixel((x, y)))]
                elements = [item for item in state["elements"] if item["pageId"] == state["pages"][page_index]["pageId"]]
                self.assertEqual(len(elements), (1, 2, 1)[page_index])
                expected_regions = []
                for element in elements:
                    size = element["width"]
                    top = state["pages"][page_index]["heightPt"] - element["y"] - element["height"]
                    part = element["properties"]["seamPartIndex"]
                    left = state["pages"][page_index]["widthPt"] - size / 2 if part == 0 else 0
                    region = (left - 1, top - 1, left + size / 2 + 1, top + size + 1)
                    expected_regions.append(region)
                    pixels = [(x, y) for x, y in red if region[0] <= x <= region[2] and region[1] <= y <= region[3]]
                    self.assertGreater(len(pixels), 100, f"Missing half seal on page {page_index + 1}: {element['id']}")
                # No unsplit/full stamp may leak into the other half of its box.
                self.assertTrue(all(any(a <= x <= c and b <= y <= d for a, b, c, d in expected_regions) for x, y in red))

    def test_two_independent_seam_pairs_complete_approval_and_download(self):
        applicant = self.fixture._session_for_user_id(self.fixture.applicant_ids[0])
        source = self.three_page_pdf()
        source_hash = backend.sha256_bytes(source)
        draft = backend.create_official_editor_draft(self.conn, {
            "company_id": "CO-001", "title": "隔離騎縫章完整流程驗收",
            "request_reason": "三頁、兩組不同高度騎縫章", "document_category": "服務委託合約",
            "dispatch_method": "no_dispatch_required",
        }, applicant)
        document_id = draft["document_id"]
        intent = backend.create_official_editor_upload_intent(self.conn, document_id, {
            "asset_kind": "source_pdf", "file_name": "synthetic-three-page-seam.pdf",
            "mime_type": "application/pdf", "size_bytes": len(source), "sha256": source_hash,
        }, applicant)
        backend.store_official_editor_local_upload(self.conn, document_id, intent["upload_id"], source, applicant, "application/pdf")
        finalized = backend.finalize_official_editor_upload(self.conn, document_id, intent["upload_id"], {"sha256": source_hash}, applicant)
        revision = finalized["editor_revision"]
        state = copy.deepcopy(revision["state"])
        self.assertEqual(len(state["pages"]), 3)
        seal = backend.company_seal_row(self.conn, self.fixture.seal_id)
        seal_file = backend.require_current_company_seal_file(self.conn, self.fixture.seal_id)
        profile = backend.company_seal_file_dimension_profile(seal["seal_size_type"], seal_file, current=True)
        _, original_seal_bytes = backend.read_file_object_bytes(self.conn, seal_file["file_object_id"])
        size = profile["width_pt"]
        state["elements"] = []
        for group, top in enumerate((180, 420)):
            for part in range(2):
                page = state["pages"][group + part]
                state["elements"].append({
                    "id": f"SEAM-{group}-{part}", "kind": "seal", "pageId": page["pageId"],
                    "x": round(page["widthPt"] - size, 4) if part == 0 else 0,
                    "y": round(page["heightPt"] - top - profile["height_pt"], 4),
                    "width": size, "height": profile["height_pt"], "rotation": 0, "opacity": 1,
                    "zIndex": len(state["elements"]) + 1,
                    "properties": {
                        "sealId": self.fixture.seal_id, "sealFileId": seal_file["id"], "sealFileSha256": seal_file["file_hash"],
                        "renderWidthMm": profile["width_mm"], "renderHeightMm": profile["height_mm"],
                        "dimensionPolicyVersion": profile["dimension_policy_version"],
                        "seamGroupId": f"SEAM-GROUP-{group}", "seamMode": "pair", "seamPartCount": 2, "seamPartIndex": part,
                    },
                })
        self.assertEqual(len(validate_seam_groups(state)), 2)
        saved = backend.save_official_editor_state(self.conn, document_id, {
            "revisionNo": revision["revisionNo"], "baseManifestSha256": revision["manifestSha256"], "state": state,
        }, applicant)
        preflight = backend.preflight_official_editor(self.conn, document_id, {
            "editorRevisionId": saved["id"], "manifestSha256": saved["manifestSha256"],
        }, applicant)
        detail = backend.submit_official_document(self.conn, document_id, {
            "editorRevisionId": preflight["editorRevisionId"], "manifestSha256": preflight["manifestSha256"],
            "preparedFileId": preflight["preparedFileId"], "preparedSha256": preflight["preparedSha256"],
            "comment": "隔離騎縫章流程送簽",
        }, applicant)
        self.assertEqual(detail["metadata"]["official_seal"]["approval_route_code"], "C")
        locked = copy.deepcopy(detail["stamp_request"])
        locked_state = json.loads(self.conn.execute("SELECT editor_state_json FROM official_document_editor_revisions WHERE id=?", (locked["locked_editor_revision_id"],)).fetchone()[0])
        self.assertEqual(len(locked["stamp_positions"]), 4)
        for element, position in zip(locked_state["elements"], locked["stamp_positions"]):
            for key in ("x", "y", "width", "height", "rotation", "opacity"):
                self.assertAlmostEqual(float(element[key]), float(position[key]), delta=0.001, msg=f"Locked {element['id']} {key}")
        validate_seam_positions(locked_state, locked["stamp_positions"])
        self.assertTrue(all(position["locked_seal_sha256"] == seal_file["file_hash"] for position in locked["stamp_positions"]))
        prepared_file = next(item for item in detail["files"] if item["id"] == preflight["preparedFileId"])
        _, _, prepared_before = backend.official_document_download_file(self.conn, document_id, prepared_file["id"], applicant)
        with self.assertRaisesRegex(ValueError, "editor_locked_after_submit"):
            backend.save_official_editor_state(self.conn, document_id, {
                "revisionNo": preflight["revisionNo"], "baseManifestSha256": preflight["manifestSha256"], "state": state,
            }, applicant)

        # The shared helper actually downloads every review source and approves
        # each stored step using that exact assigned test account, including CEO.
        detail = self.fixture._approve_and_stamp(detail)
        stamped_file = next(item for item in detail["files"] if item["file_type"] == "stamped_pdf")
        _, _, stamped = backend.official_document_download_file(self.conn, document_id, stamped_file["id"], applicant)
        self.assertEqual(backend.sha256_bytes(stamped), stamped_file["file_hash"])
        self.assert_half_seals_rendered(stamped, locked_state)
        for key in ("locked_editor_revision_id", "locked_source_sha256", "prepared_file_id", "prepared_sha256", "editor_manifest_sha256"):
            self.assertEqual(detail["stamp_request"][key], locked[key])
        current_locked_state = json.loads(self.conn.execute("SELECT editor_state_json FROM official_document_editor_revisions WHERE id=?", (locked["locked_editor_revision_id"],)).fetchone()[0])
        self.assertEqual(current_locked_state, locked_state)
        original_file = next(item for item in detail["files"] if item["file_type"] == "original_pdf")
        _, _, source_after = backend.official_document_download_file(self.conn, document_id, original_file["id"], applicant)
        _, _, prepared_after = backend.official_document_download_file(self.conn, document_id, prepared_file["id"], applicant)
        _, seal_after = backend.read_file_object_bytes(self.conn, seal_file["file_object_id"])
        self.assertEqual(source_after, source)
        self.assertEqual(prepared_after, prepared_before)
        self.assertEqual(seal_after, original_seal_bytes)
        detail = backend.confirm_official_document(self.conn, document_id, {"comment": "隔離申請人收到騎縫章檔案"}, applicant)
        self.assertEqual(detail["current_status"], "closed")
        participants = {step["approver_user_id"] for step in detail["approval_steps"] if step.get("approver_user_id")}
        for user_id in participants:
            _, _, downloaded = backend.official_document_download_file(self.conn, document_id, stamped_file["id"], self.fixture._session_for_user_id(user_id))
            self.assertEqual(downloaded, stamped)
        evidence = os.environ.get("EDOC_SEAM_TEST_EVIDENCE_DIR")
        if evidence:
            destination = Path(evidence)
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "synthetic-seam-approved.pdf").write_bytes(stamped)


if __name__ == "__main__":
    unittest.main()
