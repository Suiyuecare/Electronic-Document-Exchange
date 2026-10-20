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

    def test_actions_use_node24_compatible_runtimes(self) -> None:
        # Reviewed official major versions, pinned to immutable commit SHAs.
        self.assertIn("actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09", self.workflow)
        self.assertIn("actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1", self.workflow)
        self.assertIn("actions/setup-node@a0853c24544627f65ddf259abe73b1d18a591444", self.workflow)
        self.assertIn("actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f", self.workflow)
        self.assertIn("package-manager-cache: false", self.workflow)
        for retired_action in (
            "actions/checkout@v4",
            "actions/setup-python@v5",
            "actions/setup-node@v4",
            "actions/upload-artifact@v4",
        ):
            self.assertNotIn(retired_action, self.workflow)

    def test_validation_is_read_only_and_new_database_gates_actually_execute(self) -> None:
        self.assertIn("permissions:\n  contents: read", self.workflow)
        self.assertNotIn("contents: write", self.workflow)
        self.assertIn("tests.test_workflow_readiness_postgres", self.workflow)
        self.assertIn("tests.test_official_handover_postgres", self.workflow)
        self.assertIn("node tests/handover_feature_gate.js", self.workflow)

    def test_private_draft_archive_runs_with_real_postgres_not_discovery_only(self) -> None:
        database_command = self.workflow.split(
            "EDOC_COMPOSE_TEST_PG_PORT=54322", 1
        )[1].split("# Opt-in acceptance", 1)[0]
        self.assertIn("python -m unittest -v", database_command)
        self.assertIn("tests.test_private_draft_archive_postgres", database_command)


if __name__ == "__main__":
    unittest.main()
