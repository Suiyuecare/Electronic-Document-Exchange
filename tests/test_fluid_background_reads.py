"""Run deterministic shipping read/initialization contracts without production."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FluidBackgroundReadsTest(unittest.TestCase):
    def test_shipping_background_read_and_batch_contracts(self):
        result = subprocess.run(["node", "--test", "tests/fluid_background_reads.test.js"], cwd=ROOT, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
