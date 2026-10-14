"""Repository policy is explicit; the file does not assert remote enforcement."""
import json
from pathlib import Path
import unittest


class ReleaseProtectionPolicyTest(unittest.TestCase):
    def test_main_allows_owner_approval_and_preserves_checks_and_protections(self):
        root = Path(__file__).resolve().parents[1]
        policy = json.loads((root / "docs/release-protection-policy.json").read_text())
        self.assertIs(policy["enforce_admins"], True)
        self.assertIs(policy["required_status_checks"]["strict"], True)
        self.assertEqual(2, len(policy["required_status_checks"]["checks"]))
        self.assertEqual({"Validate backend and frontend", "Rebuild Supabase from migrations"},
                         {row["context"] for row in policy["required_status_checks"]["checks"]})
        self.assertTrue(all(row["app_id"] == 15368 for row in policy["required_status_checks"]["checks"]))
        review = policy["required_pull_request_reviews"]
        self.assertEqual(0, review["required_approving_review_count"])
        self.assertIs(review["dismiss_stale_reviews"], True)
        self.assertIs(review["require_code_owner_reviews"], False)
        self.assertIsNone(policy["restrictions"])
        self.assertIs(policy["allow_force_pushes"], False)
        self.assertIs(policy["allow_deletions"], False)
        self.assertIs(policy["required_conversation_resolution"], True)


if __name__ == "__main__":
    unittest.main()
