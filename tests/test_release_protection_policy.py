"""Repository policy is explicit; the file does not assert remote enforcement."""
import json
from pathlib import Path
import unittest


class ReleaseProtectionPolicyTest(unittest.TestCase):
    def test_main_requires_checks_independent_review_and_no_bypass_flags(self):
        root = Path(__file__).resolve().parents[1]
        policy = json.loads((root / "docs/release-protection-policy.json").read_text())
        self.assertIs(policy["enforce_admins"], True)
        self.assertIs(policy["required_status_checks"]["strict"], True)
        self.assertEqual({"Validate backend and frontend", "Rebuild Supabase from migrations"},
                         {row["context"] for row in policy["required_status_checks"]["checks"]})
        self.assertTrue(all(row["app_id"] == 15368 for row in policy["required_status_checks"]["checks"]))
        review = policy["required_pull_request_reviews"]
        self.assertEqual(1, review["required_approving_review_count"])
        self.assertIs(review["dismiss_stale_reviews"], True)
        self.assertIs(policy["allow_force_pushes"], False)
        self.assertIs(policy["allow_deletions"], False)
        self.assertIs(policy["required_conversation_resolution"], True)


if __name__ == "__main__":
    unittest.main()
