"""Versioned right-edge policy and historical-manifest preservation."""
import copy
import json
import subprocess
import unittest
from pathlib import Path

from editor_seam import CURRENT_SEAM_POLICY, SEAM_MARGIN_PT, validate_seam_groups, validate_seam_policy_transition
from tests.test_editor_grouped_seam import grouped_fixture


class SeamV2Tests(unittest.TestCase):
    def current(self, count=7, offset=120):
        value = grouped_fixture(count, rotations=(0,), offset=offset)
        for item in value["elements"]:
            item["properties"]["seamPolicyVersion"] = CURRENT_SEAM_POLICY
        return value

    def test_new_groups_right_edge_and_margin_are_server_enforced(self):
        state = self.current()
        self.assertEqual([len(x) for x in validate_seam_groups(state).values()], [5,2])
        validate_seam_policy_transition(state, {"elements": []})
        for mutate, error in (
            (lambda s: s["elements"][0]["properties"].update(seamEdge="left"), "right_edge_required"),
            (lambda s: s["elements"][0]["properties"].update(seamPolicyVersion="unknown"), "policy_invalid"),
            (lambda s: s["elements"][0]["properties"].pop("seamPolicyVersion"), "policy_invalid"),
            (lambda s: s["elements"][0].update(y=1), "margin_required"),
        ):
            broken = copy.deepcopy(state); mutate(broken)
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                validate_seam_groups(broken)
        for top in (0, SEAM_MARGIN_PT - .01):
            with self.assertRaisesRegex(ValueError, "margin_required"):
                validate_seam_groups(self.current(1, top))
        validate_seam_groups(self.current(1, SEAM_MARGIN_PT))

    def test_no_policy_downgrade_or_new_legacy_groups(self):
        old = grouped_fixture(7, "top")
        before = copy.deepcopy(old)
        validate_seam_policy_transition(old, before)
        validate_seam_groups(old)
        self.assertEqual(old, before)
        with self.assertRaisesRegex(ValueError, "current_policy_required"):
            validate_seam_policy_transition(old, {"elements": []})
        current = self.current()
        downgraded = copy.deepcopy(current)
        for item in downgraded["elements"]: item["properties"].pop("seamPolicyVersion")
        with self.assertRaisesRegex(ValueError, "current_policy_required"):
            validate_seam_policy_transition(downgraded, current)

    def test_frontend_common_initial_height_margin_and_server_parity(self):
        script = '''
const seam=require('./editor-seam.js');
const state=JSON.parse(process.argv[1]);
const ids=[...seam.groups(state).keys()];
const top=seam.initialBatchTopMm(state,ids);
for(const id of ids) seam.position(state,id,top,'right');
const starts=state.elements.map(item=>seam.topPt(state.pages.find(p=>p.pageId===item.pageId),item));
const rejected=seam.position(state,ids[0],top,'left');
seam.position(state,ids[0],-100,'right');
seam.position(state,ids[1],10000,'right');
console.log(JSON.stringify({state,starts,rejected,bounds:ids.map(id=>seam.offsetBoundsPt(state,id))}));
'''
        state = self.current()
        state["pages"][1]["rotation"] = 90
        run = subprocess.run(["node", "-e", script, json.dumps(state)], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)
        value = json.loads(run.stdout)
        self.assertFalse(value["rejected"])
        self.assertLess(max(value["starts"])-min(value["starts"]), .001)
        self.assertAlmostEqual(value["bounds"][0]["min"], SEAM_MARGIN_PT)
        validate_seam_groups(value["state"])


if __name__ == "__main__": unittest.main()
