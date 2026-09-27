"""Keep bounded fetch and cancellation regressions in the standard test suite."""
from pathlib import Path
import shutil
import subprocess
import unittest


class TransportResilienceNodeTests(unittest.TestCase):
    def test_shipping_transport_deadlines_and_cancellation(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js required for transport regressions")
        result = subprocess.run(
            [node, "--test", "tests/transport_resilience.test.js"],
            cwd=Path(__file__).resolve().parents[1],
            text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
