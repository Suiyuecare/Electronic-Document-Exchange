"""Shipping frontend safety/measurement contract, no external services."""
from pathlib import Path
import shutil
import subprocess
import unittest


class CompleteUxContractTest(unittest.TestCase):
    def test_shipping_frontend_contracts(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node runtime required")
        result = subprocess.run([node, "--test", "tests/ux_complete_contract.test.js"], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
