"""Include deferred browser upload regressions in the standard unittest run."""
from pathlib import Path
import shutil
import subprocess
import unittest


class EditorUploadScopeNodeTests(unittest.TestCase):
    def test_shipping_upload_functions_keep_async_results_in_their_scope(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js required for browser-function regressions")
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [node, "--test", "tests/editor_upload_scope.test.js"],
            cwd=root, text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
