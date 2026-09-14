"""Independent pixel checks using synthetic blocks, never real company seals."""
import copy
import hashlib
import io
import unittest

import fitz
from PIL import Image

import backend
from tests import test_editor_seam as seam_fixture


class SealFrontRegressionTest(unittest.TestCase):
    V3 = "pymupdf-1.26.5-editor-v3-kai-text-front"
    V4 = "pymupdf-1.26.5-editor-v4-seal-front"

    def locked(self, *, transparent=False, opacity=1):
        with fitz.open() as pdf:
            page = pdf.new_page(width=200, height=200)
            page.draw_rect(fitz.Rect(50, 20, 130, 100), fill=(0, 0, 1), color=None)
            page.insert_text((55, 48), "TEST", fontsize=16, color=(0, 0, 0))
            original = pdf.tobytes()
        raster = Image.new("RGBA", (320, 320), (220, 0, 0, 255))
        if transparent:
            raster.paste((0, 0, 0, 0), (120, 120, 200, 200))
        stream = io.BytesIO()
        raster.save(stream, format="PNG")
        seal = stream.getvalue()
        return {
            "renderer_version": self.V4,
            "prepared_bytes": original,
            "state": {
                "pages": [{"pageId": "P1", "widthPt": 200, "heightPt": 200, "rotation": 0, "order": 0}],
                "elements": [{"id": "T1", "pageId": "P1", "kind": "text", "x": 55, "y": 140,
                              "width": 70, "height": 35, "rotation": 0, "opacity": 1, "zIndex": 99,
                              "properties": {"text": "TEST", "fontSize": 16, "color": "#000000"}}],
            },
            "positions": [{"page_ref": "P1", "page": 1, "x": 50, "y": 100, "width": 80,
                           "height": 80, "rotation": 0, "opacity": opacity, "z_index": -100,
                           "order_index": 1, "locked_seal_file_id": "S1"}],
            "seal_assets": {"S1": {"data": seal, "mime_type": "image/png", "sha256": hashlib.sha256(seal).hexdigest()}},
        }

    @staticmethod
    def image(data):
        with fitz.open(stream=data, filetype="pdf") as doc:
            pix = doc[0].get_pixmap(alpha=False)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    def test_new_version_seal_covers_entered_text_despite_lower_z_index(self):
        locked = self.locked()
        before = copy.deepcopy(locked)
        output, _, metadata = backend.stamp_prepared_pdf_with_locked_seals(locked)
        self.assertEqual(metadata["front_text_repaint_count"], 0)
        region = self.image(output).crop((53, 23, 127, 97))
        self.assertTrue(all(r > 210 and g < 5 and b < 5 for r, g, b in region.getdata()))
        self.assertEqual(locked, before, "rendering must never rewrite locked state, source, or seal bytes")
        with fitz.open(stream=output, filetype="pdf") as doc:
            self.assertIn("TEST", doc[0].get_text())

    def test_transparent_hole_reveals_original_without_white_rectangle(self):
        locked = self.locked(transparent=True)
        output, _, _ = backend.stamp_prepared_pdf_with_locked_seals(locked)
        actual = self.image(output)
        self.assertEqual(actual.getpixel((90, 60)), self.image(locked["prepared_bytes"]).getpixel((90, 60)))
        self.assertEqual(actual.getpixel((60, 70)), (220, 0, 0))

    def test_opacity_is_preserved_when_seal_is_topmost(self):
        output, _, _ = backend.stamp_prepared_pdf_with_locked_seals(self.locked(opacity=0.5))
        red, green, blue = self.image(output).getpixel((60, 70))
        self.assertTrue(100 <= red <= 120 and green <= 2 and 120 <= blue <= 140, (red, green, blue))

    def test_old_locked_v3_keeps_text_front_behavior(self):
        locked = self.locked()
        locked["renderer_version"] = self.V3
        output, _, metadata = backend.stamp_prepared_pdf_with_locked_seals(locked)
        self.assertEqual(metadata["front_text_repaint_count"], 1)
        pixels = self.image(output).crop((53, 23, 127, 97)).getdata()
        self.assertGreater(sum(max(pixel) < 80 for pixel in pixels), 0)

    def test_multiple_seals_keep_their_internal_z_order(self):
        locked = self.locked()
        second = Image.new("RGBA", (320, 320), (0, 190, 0, 255))
        stream = io.BytesIO()
        second.save(stream, format="PNG")
        locked["seal_assets"]["S2"] = {"data": stream.getvalue(), "mime_type": "image/png"}
        locked["positions"].append({**locked["positions"][0], "locked_seal_file_id": "S2", "z_index": 20, "order_index": 2})
        locked["positions"].reverse()
        output, _, metadata = backend.stamp_prepared_pdf_with_locked_seals(locked)
        self.assertEqual(metadata["seal_count"], 2)
        self.assertEqual(self.image(output).getpixel((60, 70)), (0, 190, 0))

    def test_seam_halves_are_topmost_without_filling_transparent_half(self):
        locked = self.locked()
        state = seam_fixture.fixture()
        positions = [seam_fixture.position(element) for element in state["elements"]]
        with fitz.open() as prepared:
            for index, definition in enumerate(state["pages"]):
                page = prepared.new_page(width=definition["widthPt"], height=definition["heightPt"])
                page.draw_rect(page.rect, fill=(0, 0, 1), color=None)
                x = definition["widthPt"] - 35 if index == 0 else 5
                page.insert_text((x, 145), "TEST", fontsize=10, color=(0, 0, 0))
                state["elements"].append({"id": f"T{index}", "pageId": definition["pageId"], "kind": "text",
                                          "x": x, "y": definition["heightPt"] - 160, "width": 30, "height": 30,
                                          "opacity": 1, "zIndex": 999, "properties": {"text": "TEST", "fontSize": 10}})
            locked["prepared_bytes"] = prepared.tobytes()
        locked.update(state=state, positions=positions, seal_assets={"synthetic-file": locked["seal_assets"]["S1"]})
        before = copy.deepcopy(locked)
        result, _, metadata = backend.stamp_prepared_pdf_with_locked_seals(locked)
        with fitz.open(stream=result, filetype="pdf") as stamped:
            for index, page in enumerate(stamped):
                pix = page.get_pixmap(alpha=False)
                visible_x = pix.width - 10 if index == 0 else 10
                clear_x = pix.width - 65 if index == 0 else 65
                self.assertEqual(pix.pixel(visible_x, 150), (220, 0, 0))
                self.assertEqual(pix.pixel(clear_x, 150), (0, 0, 255))
        self.assertEqual(metadata["seam_group_count"], 1)
        self.assertEqual(metadata["front_text_repaint_count"], 0)
        self.assertEqual(locked, before)


if __name__ == "__main__":
    unittest.main()
