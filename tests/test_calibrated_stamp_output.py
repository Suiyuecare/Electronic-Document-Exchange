"""Physical geometry and final immutable continuous stamp; synthetic only."""
import base64
import io
import unittest

import fitz
from PIL import Image

import backend
from tests import test_official_document_workflow as fixture


def png(width, height, color):
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), color).save(buffer, "PNG")
    return buffer.getvalue()


class CalibratedOverlayOutputTest(unittest.TestCase):
    def test_one_mm_width_is_not_enlarged_to_legacy_placeholder_minimum(self):
        width, height = 1 * 72 / 25.4, 10 * 72 / 25.4
        asset = {"data": png(40, 400, (100, 0, 200, 255)), "mime_type": "image/png", "_locked_render_size_pt": [width, height]}
        output = backend.write_asset_stamp_overlay_pdf([(595, 842)], [{"page": 1, "x": 594, "y": 830, "w": width, "h": height}], [], asset)
        with fitz.open(stream=output, filetype="pdf") as document:
            rectangles = document[0].get_image_rects(document[0].get_images()[0][0])
            self.assertEqual(len(rectangles), 1)
            self.assertAlmostEqual(rectangles[0].width, width, places=3)
            self.assertAlmostEqual(rectangles[0].height, height, places=3)
            self.assertLessEqual(rectangles[0].x1, 595.01)

    def test_size_tamper_and_oversized_page_are_rejected_not_rescaled(self):
        asset = {"data": png(40, 400, (100, 0, 200, 255)), "mime_type": "image/png", "_locked_render_size_pt": [3.0, 30.0]}
        with self.assertRaisesRegex(ValueError, "seal_size_locked"):
            backend.write_asset_stamp_overlay_pdf([(595, 842)], [{"page": 1, "w": 12, "h": 30}], [], asset)
        with self.assertRaisesRegex(ValueError, "outside_page"):
            backend.clamp_pdf_rect(0, 0, 201, 30, preserve_size=True, page_width=200, page_height=200)


class ContinuousFinalWorkflowTest(unittest.TestCase):
    owner_kind = "company"
    category = "continuous_seal"
    size_type = "single_seal"
    width_mm, height_mm = 50, 12

    def setUp(self):
        self.fixture = fixture.OfficialDocumentWorkflowTestCase()
        self.fixture.setUp()
        self.conn = self.fixture.conn
        backend.patch_company_seal_policy(self.conn, "CO-001", {"owner_kind": self.owner_kind})
        self.seal = backend.create_company_seal(self.conn, "CO-001", {
            "seal_name": "合成校準章", "seal_category": self.category, "seal_size_type": self.size_type})["id"]
        self.original = self.upload((100, 0, 200, 255))

    def tearDown(self):
        self.fixture.tearDown()

    def upload(self, color):
        return backend.upload_company_seal_file(self.conn, self.seal, {
            "file_name": "synthetic-continuous.png", "file_mime_type": "image/png",
            "content_base64": base64.b64encode(png(self.width_mm * 20, self.height_mm * 20, color)).decode(),
            "render_width_mm": self.width_mm, "render_height_mm": self.height_mm,
        })

    def test_continuous_letter_approval_keeps_original_file_and_both_dimensions(self):
        seal = backend.company_seal_row(self.conn, self.seal)
        profile = backend.company_seal_file_dimension_profile(self.size_type, seal["current_file"], current=True)
        detail = backend.create_official_document(self.conn, {
            "source_type": "blank_editor", "company_id": "CO-001", "seal_id": self.seal,
            "document_type": "outgoing_official_document", "output_mode": "physical",
            "title": "合成連續章測試", "subject": "合成連續章公文，請查照。", "description": "去識別化驗收，不寄送。",
            "recipient": "測試收文單位", "document_category": "主管機關 申請或回覆文件（與 費用、法令無關）",
            "stamp_positions": [{"seal_id": self.seal, "page": 1, "x": 300, "y": 100, "width": profile["width_pt"], "height": profile["height_pt"]}],
            "metadata": {"continuous_seal_type": "連續章", "seal_placements": {"single": {"page": 1, "x": 70, "y": 80}}},
            "submit": True,
        }, self.fixture.login_session("sales-assistant@suiyuecare.com"))
        position = backend.official_document_stamp_request(self.conn, detail["id"])["stamp_positions"][0]
        old_file = position["locked_seal_file_id"]
        self.upload((255, 150, 0, 255))
        self.assertNotEqual(old_file, backend.company_seal_row(self.conn, self.seal)["current_file"]["id"])
        approved = self.fixture.approve_until_after_stamp(detail)
        final = next(row for row in approved["files"] if row["file_type"] == "stamped_pdf")
        file_id = self.conn.execute("SELECT file_object_id FROM official_document_files WHERE id=?", (final["id"],)).fetchone()[0]
        _, output = backend.read_file_object_bytes(self.conn, file_id)
        with fitz.open(stream=output, filetype="pdf") as document:
            rects = [rect for page in document for image in page.get_images() for rect in page.get_image_rects(image[0])]
            self.assertTrue(any(abs(rect.width-profile["width_pt"])<.02 and abs(rect.height-profile["height_pt"])<.02 for rect in rects))
            image_data = [document.extract_image(image[0])["image"] for page in document for image in page.get_images()]
            colors = [color for data in image_data for color in Image.open(io.BytesIO(data)).convert("RGB").getdata()]
            self.assertTrue(any(r == 100 and g == 0 and b == 200 for r, g, b in colors))
            self.assertFalse(any(r == 255 and g == 150 and b == 0 for r, g, b in colors))


class OfficialRectangleFinalWorkflowTest(ContinuousFinalWorkflowTest):
    owner_kind = "institution"
    category = "official_seal"
    size_type = "large_seal"
    width_mm, height_mm = 20, 40


if __name__ == "__main__":
    unittest.main()
