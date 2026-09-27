"""Synthetic shipping projection lifecycle; never contacts a live account."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AccountProjectionSessionTest(unittest.TestCase):
    def test_shipping_session_lifecycle(self):
        result = subprocess.run(
            ['node', '--test', 'tests/account_projection_session.test.js'],
            cwd=ROOT, capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
