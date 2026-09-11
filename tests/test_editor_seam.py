"""Synthetic-only seam geometry and final PDF rendering regressions."""
import copy
import hashlib
import io
import json
import subprocess
import unittest
from pathlib import Path

import fitz
from PIL import Image

import backend
from editor_seam import validate_seam_groups, validate_seam_positions, split_seal_raster, seam_element_for_position


def fixture(rotations=(0, 0), tops=(120,)):
    pages = [dict(pageId=f"p{i}", order=i + 1, widthPt=595.2756, heightPt=841.8898, rotation=r) for i, r in enumerate(rotations)]
    elements = []
    for group, top in enumerate(tops):
        for part in range(2):
            page = pages[group + part]
            width, height, r, size = page["widthPt"], page["heightPt"], page["rotation"], 84
            edge = ((height if r % 180 else width) - size) if part == 0 else 0
            if r == 90: x, y = top, edge
            elif r == 180: x, y = width - edge - size, top
            elif r == 270: x, y = width - top - size, height - edge - size
            else: x, y = edge, height - top - size
            elements.append(dict(id=f"s{group}-{part}", pageId=page["pageId"], kind="seal", x=x, y=y, width=size, height=size, rotation=0, opacity=1, zIndex=len(elements) + 1,
                properties=dict(sealId="synthetic-seal", sealFileId="synthetic-file", sealFileSha256="a" * 64, seamGroupId=f"group-{group}", seamMode="pair", seamPartCount=2, seamPartIndex=part)))
    return dict(pages=pages, elements=elements)


def position(element):
    props = element["properties"]
    return {**{key: element[key] for key in ("x", "y", "width", "height", "rotation", "opacity")}, "page_ref": element["pageId"], "order_index": element["zIndex"], "z_index": element["zIndex"], "locked_seal_file_id": props["sealFileId"], "locked_seal_sha256": props["sealFileSha256"]}


class SeamTests(unittest.TestCase):
    def test_complete_groups_and_independent_positions(self):
        state = fixture((0, 90, 270), (120, 240))
        self.assertEqual(len(validate_seam_groups(state)), 2)
        for element in state["elements"]:
            self.assertEqual(seam_element_for_position(state, position(element)), element)

    def test_incomplete_forged_or_mismatched_groups_rejected(self):
        for mutation in (
            lambda s: s["elements"].pop(),
            lambda s: s["elements"][1]["properties"].update(sealFileSha256="b" * 64),
            lambda s: s["elements"][1].update(width=90),
            lambda s: s["elements"][1].update(opacity=.4),
            lambda s: s["elements"][1].update(y=200),
            lambda s: s["elements"][1].update(x=25),
            lambda s: s["elements"][1].update(rotation=90),
            lambda s: s["elements"][1]["properties"].update(seamPartIndex=True),
            lambda s: s["elements"][1]["properties"].update(seamGroupId="../unsafe"),
            lambda s: s["pages"].reverse(),
        ):
            state = fixture()
            mutation(state)
            with self.assertRaises(ValueError): validate_seam_groups(state)

    def test_locked_position_tamper_rejected(self):
        state = fixture()
        for key, value in (("x", 2), ("page_ref", "other"), ("locked_seal_sha256", "b" * 64), ("order_index", 0)):
            item = position(state["elements"][0]); item[key] = value
            with self.assertRaisesRegex(ValueError, "editor_seam_position_mismatch"):
                seam_element_for_position(state, item)

    def test_halves_reconstruct_original_without_scaling(self):
        image = Image.new("RGBA", (101, 100), (0, 0, 0, 0))
        for x in range(101):
            for y in range(100): image.putpixel((x, y), (x, y, 130, 255))
        buffer = io.BytesIO(); image.save(buffer, "PNG"); data = buffer.getvalue()
        left = Image.open(io.BytesIO(split_seal_raster(data, 0)))
        right = Image.open(io.BytesIO(split_seal_raster(data, 1)))
        combined = Image.new("RGBA", image.size)
        combined.paste(left.crop((51, 0, 101, 100)), (0, 0))
        combined.paste(right.crop((0, 0, 51, 100)), (50, 0))
        self.assertEqual(combined.tobytes(), image.tobytes())
        self.assertEqual(left.size, image.size)
        self.assertEqual(left.getpixel((0, 0))[3], 0)

    def test_locked_half_coverage_is_exact(self):
        state = fixture()
        positions = [position(item) for item in state["elements"]]
        validate_seam_positions(state, positions)
        for forged in (positions[:1], [positions[0], positions[0]], positions + [positions[0]], []):
            with self.assertRaisesRegex(ValueError, "editor_seam_position_mismatch"):
                validate_seam_positions(state, forged)
        regular = copy.deepcopy(state["elements"][0])
        regular["properties"] = {key: value for key, value in regular["properties"].items() if not key.startswith("seam")}
        regular.update(id="ordinary", zIndex=3)
        state["elements"].append(regular)
        with self.assertRaisesRegex(ValueError, "editor_seam_position_mismatch"):
            validate_seam_positions(state, [positions[0], position(regular)])

    def test_render_edges_and_upright_halves_for_all_page_rotations(self):
        image = Image.new("RGBA", (252, 252), "red")
        image.paste(Image.new("RGBA", (126, 252), "green"), (126, 0))
        image.paste(Image.new("RGBA", (252, 30), "blue"), (0, 0))
        source = io.BytesIO(); image.save(source, "PNG"); original = source.getvalue()
        original_hash = hashlib.sha256(original).hexdigest()
        for rotations in ((0, 0), (90, 180), (180, 270), (270, 90)):
            with self.subTest(rotations=rotations):
                state = fixture(rotations)
                doc = fitz.open()
                for p in state["pages"]:
                    page = doc.new_page(width=p["widthPt"], height=p["heightPt"]); page.set_rotation(p["rotation"])
                prepared = doc.tobytes(); doc.close()
                locked = dict(state=state, prepared_bytes=prepared, positions=[position(e) for e in state["elements"]], seal_assets={"synthetic-file": dict(data=original, mime_type="image/png")}, renderer_version="synthetic")
                result, _, metadata = backend.stamp_prepared_pdf_with_locked_seals(locked)
                output = fitz.open(stream=result, filetype="pdf")
                for index, page in enumerate(output):
                    pix = page.get_pixmap(alpha=False)
                    x = pix.width - 10 if index == 0 else 10
                    self.assertEqual(pix.pixel(x, 125)[:3], (0, 0, 255))
                    self.assertEqual(pix.pixel(x, 150)[:3], (255, 0, 0) if index == 0 else (0, 128, 0))
                    self.assertEqual(pix.pixel(x, 230)[:3], (255, 255, 255))
                self.assertEqual(metadata["seal_count"], 2)
                output.close()
        self.assertEqual(hashlib.sha256(original).hexdigest(), original_hash)

    def test_frontend_group_model(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(["node", "--test", "tests/editor_seam.test.js"], cwd=root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__": unittest.main()
