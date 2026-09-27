"""Run authorized reopen latency and cancellation contracts with synthetic data."""
from pathlib import Path
import shutil
import subprocess
import unittest


class ReopenPerformanceResilienceTests(unittest.TestCase):
    def test_parallel_reopen_preserves_active_case(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js required for editor reopen regressions")
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [node, "--test", "tests/reopen_perf_resilience.test.js"],
            cwd=root, text=True, capture_output=True, timeout=45,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
