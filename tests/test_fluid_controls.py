"""CI runs the shipping navigation, notice and dialog contracts too."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FluidControlsTest(unittest.TestCase):
    def test_shipping_controls(self):
        result = subprocess.run(
            ["node", "--test", "tests/fluid_controls.test.js", "tests/workflow_stable_rendering.test.js"], cwd=ROOT,
            capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
