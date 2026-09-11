"""Run shipping editor correctness regressions in the standard CI suite."""
from pathlib import Path
import shutil
import subprocess
import unittest


class EditorCorrectnessTests(unittest.TestCase):
    def test_browser_editor_output_and_mutations(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js required for shipping editor regressions")
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [node, "--test", "tests/editor_correctness.test.js"],
            cwd=root, text=True, capture_output=True, timeout=45,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
