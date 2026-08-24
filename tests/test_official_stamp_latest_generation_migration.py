from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20260824061729_fix_official_stamp_latest_workflow_generation.sql"


class OfficialStampLatestGenerationMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_all_approval_checks_are_scoped_to_latest_generation(self) -> None:
        self.assertIn("select max(step.workflow_generation)", self.sql)
        self.assertEqual(
            self.sql.count("workflow_generation = v_workflow_generation"),
            3,
        )
        self.assertIn("if v_workflow_generation is null then", self.sql)

    def test_stamp_claim_rpc_remains_service_role_only(self) -> None:
        signature = "public.edoc_claim_official_document_stamp(text, text, text, text, integer)"
        self.assertIn(f"revoke all on function {signature} from public, anon, authenticated", self.sql)
        self.assertIn(f"grant execute on function {signature} to service_role", self.sql)
        self.assertIn("security definer", self.sql)
        self.assertIn("set search_path to ''", self.sql)


if __name__ == "__main__":
    unittest.main()
