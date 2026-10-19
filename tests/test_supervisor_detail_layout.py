"""Structural guard for SUP-01; browser acceptance measures actual child bounds."""
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SupervisorDetailLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = (ROOT / "styles.css").read_text(encoding="utf-8")

    def rule(self, selector):
        match = re.search(r"(?:^|\n)" + re.escape(selector) + r"\s*\{([^}]+)\}", self.css)
        self.assertIsNotNone(match, selector)
        return match.group(1)

    def test_detail_and_summary_columns_can_shrink_with_long_identifiers(self):
        for selector in ("#approvalLogDetail", ".approval-log-summary", ".approval-log-summary-head"):
            with self.subTest(selector=selector):
                rule = self.rule(selector)
                self.assertIn("grid-template-columns: minmax(0, 1fr)", rule)
                self.assertNotRegex(rule, r"overflow(?:-x)?:\s*(?:hidden|clip)")
        self.assertIn("overflow-wrap: anywhere", self.rule(".approval-log-summary-head"))

    def test_file_text_shrinks_independently_of_the_download_action(self):
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto", self.rule(".official-file-row"))
        text = self.rule(".official-file-row > div")
        self.assertIn("min-width: 0", text)
        self.assertIn("overflow-wrap: anywhere", text)
        self.assertNotRegex(text, r"text-overflow:\s*ellipsis|overflow:\s*(?:hidden|clip)")

    def test_case_list_wraps_long_subjects_inside_the_card(self):
        self.assertIn("grid-template-columns: minmax(0, 1fr)", self.rule("#approvalLogList .approval-case-card"))
        rule = self.rule("#approvalLogList .approval-case-card > *")
        self.assertIn("min-width: 0", rule)
        self.assertIn("overflow-wrap: anywhere", rule)
        self.assertNotRegex(rule, r"text-overflow:\s*ellipsis|overflow:\s*(?:hidden|clip)")

    def test_long_audit_actor_names_remain_readable(self):
        for selector in (".approval-log-step-title strong", ".approval-log-step p", ".approval-log-step small"):
            with self.subTest(selector=selector):
                self.assertIn("overflow-wrap: anywhere", self.rule(selector))
        self.assertIn("overflow-x: auto", self.rule("#approvalLog .approval-log-trail"))


if __name__ == "__main__":
    unittest.main()
