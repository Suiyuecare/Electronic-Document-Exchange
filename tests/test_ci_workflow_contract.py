from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CiWorkflowContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    def test_stale_runs_are_cancelled_before_they_can_repeat_failure_email(self) -> None:
        self.assertIn("concurrency:", self.workflow)
        self.assertIn("github.event.pull_request.number || github.ref", self.workflow)
        self.assertIn("cancel-in-progress: true", self.workflow)

    def test_protected_smoke_endpoints_are_expected_to_reject_anonymous_calls(self) -> None:
        self.assertIn("assert_unauthorized /api/cron/run-due", self.workflow)
        self.assertIn("assert_unauthorized /api/dashboard", self.workflow)
        self.assertIn("assert_unauthorized /api/documents", self.workflow)
        self.assertNotIn("curl --fail http://127.0.0.1:5174/api/cron/run-due", self.workflow)


if __name__ == "__main__":
    unittest.main()
