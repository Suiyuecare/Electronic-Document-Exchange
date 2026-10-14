"""Ensure the browser evidence rejects resized/repeated/misbound stamp parts."""
import copy
import unittest

from tools.verify_grouped_seam_browser import check_groups


class GroupedSeamBrowserEvidenceTest(unittest.TestCase):
    def sample(self, edge="right"):
        seal = {"id": "SYNTHETIC-SEAL", "file_id": "SYNTHETIC-FILE", "sha256": "a" * 64, "width_mm": 25}
        size = 25 * 72 / 25.4
        groups = []
        for count, pages in ((5, [1, 2, 3, 4, 5]), (2, [6, 7])):
            slices = []
            for part in range(count):
                horizontal = edge in {"top", "bottom"}
                target = size * (1 - 1 / count) if edge in {"right", "bottom"} else 0
                clip = {"x": 0, "y": 0, "width": size, "height": size}
                image = dict(clip)
                clip["height" if horizontal else "width"] = size / count
                clip["y" if horizontal else "x"] = target
                shift = target - size * part / count
                matrix = [1, 0, 0, 1, 0 if horizontal else shift, shift if horizontal else 0]
                image["transform"] = "matrix(" + " ".join(map(str, matrix)) + ")"
                slices.append({"clip": clip, "image": image})
            groups.append({"count": count, "pages": pages, "parts": list(range(count)), "partCounts": [count] * count,
                           "edges": [edge] * count, "modes": ["grouped"] * count,
                           "dimensions": [{"width": size, "height": size} for _ in range(count)],
                           "slices": slices, "bindings": [{"sealId": seal["id"], "fileId": seal["file_id"], "sha256": seal["sha256"]} for _ in range(count)]})
        return groups, seal

    def test_all_four_edges_validate_true_five_and_two_parts(self):
        for edge in ("left", "right", "top", "bottom"):
            groups, seal = self.sample(edge)
            self.assertTrue(check_groups(groups, seal, (edge, edge)))

    def test_resized_full_stamp_repeated_strip_and_changed_binding_fail(self):
        groups, seal = self.sample()
        for mutate in (
            lambda rows: rows[0]["slices"][0]["image"].update(width=rows[0]["dimensions"][0]["width"] / 5),
            lambda rows: rows[0]["slices"][1].update(image=copy.deepcopy(rows[0]["slices"][0]["image"])),
            lambda rows: rows[1]["bindings"][1].update(fileId="SYNTHETIC-OTHER-FILE"),
            lambda rows: rows[1]["partCounts"].__setitem__(0, 5),
            lambda rows: rows[1]["pages"].__setitem__(0, 5),
            lambda rows: rows[0]["slices"][0]["image"].update(transform="matrix(0.2 0 0 1 0 0)"),
            lambda rows: rows[0]["slices"][0]["image"].update(transform="matrix(1 0 0 1 999 0)"),
            lambda rows: rows[0]["slices"][0]["image"].pop("transform"),
        ):
            changed = copy.deepcopy(groups); mutate(changed)
            self.assertFalse(check_groups(changed, seal, ("right", "right")))


if __name__ == "__main__":
    unittest.main()
