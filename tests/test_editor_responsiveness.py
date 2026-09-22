"""Include shipping upload/canvas responsiveness regressions in standard CI discovery."""
from pathlib import Path
import shutil
import subprocess
import unittest


class EditorResponsivenessTests(unittest.TestCase):
    def test_upload_preparation_and_canvas_reuse(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js required for shipping editor responsiveness regressions")
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [node, "--test", "tests/editor_responsiveness.test.js"],
            cwd=root, text=True, capture_output=True, timeout=45,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
