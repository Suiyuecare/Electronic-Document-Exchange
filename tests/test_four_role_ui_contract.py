from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FourRoleUiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "styles.css").read_text(encoding="utf-8")

    def test_authenticated_users_never_receive_demo_approval_rows(self) -> None:
        self.assertIn("explicitFrontendFixturesEnabled", self.js)
        self.assertIn("window.__EDOC_ENABLE_TEST_FIXTURES__ === true", self.js)
        self.assertIn("window.__EDOC_TEST_WORKFLOW_TASKS__", self.js)
        self.assertNotIn("workflowTaskFixtures", self.js)
        self.assertNotIn("WF-008", self.js)
        self.assertNotIn("重大密件核定", self.js)

    def test_frontend_bundle_contains_no_retired_demo_accounts_or_notifications(self) -> None:
        self.assertNotRegex(self.js, r"USR-00[1-7]")
        self.assertNotRegex(self.js, r"NTF-00[1-5]")
        self.assertNotIn("DOC-ADMIN-1140523-001", self.js)
        self.assertIn("const userAccounts = [];", self.js)
        self.assertIn("const notificationItems = [];", self.js)

    def test_approval_filters_match_human_tasks_and_decision_requires_evidence(self) -> None:
        approval_start = self.html.index('<section class="view" id="approvalLog">')
        approval_end = self.html.index('<section class="view" id="contracts">', approval_start)
        approval_html = self.html[approval_start:approval_end]
        self.assertEqual(
            re.findall(r'data-approval-log-filter="([^"]+)">([^<]+)</button>', approval_html),
            [
                ("my_pending", "我的待簽"),
                ("delegated", "代理待簽"),
                ("overdue", "逾期"),
                ("processed", "已處理"),
            ],
        )
        for element_id in (
            "officialDecisionEvidence",
            "officialDecisionEvidenceActions",
            "officialReviewOriginal",
            "officialReviewAttachments",
            "officialReviewEdited",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn("先查看完整案件", self.html)
        self.assertNotIn("開啟流程控管", approval_html)

    def test_editor_starts_as_one_clear_upload_action(self) -> None:
        self.assertIn('id="uploadedPdfEditor"', self.html)
        self.assertIn('data-has-document="false"', self.html)
        self.assertIn("選擇 PDF 並開始編輯", self.html)
        normalized = re.sub(r"\s+", " ", self.css)
        self.assertIn('#uploadedPdfEditor[data-has-document="false"] :is(', normalized)
        self.assertIn('.pdf-editor-toolbar, .pdf-editor-general-options, .pdf-editor-thumbnails, .pdf-editor-properties', normalized)
        self.assertIn('editor.dataset.hasDocument = String(uploadedSealEditorState.pages.length > 0);', self.js)

    def test_settings_are_progressively_disclosed_with_a_governance_summary(self) -> None:
        for label in ("公司與人員", "簽核規則", "印章管理", "正式交換"):
            self.assertIn(label, self.html)
        self.assertIn("function initializeSettingsProgressiveDisclosure()", self.js)
        self.assertIn("settings-governance-group", self.js)
        self.assertIn("settings-governance-summary", self.css)
        self.assertIn("settings-governance-content", self.css)

    def test_modal_sits_above_mobile_navigation_and_has_keyboard_focus_style(self) -> None:
        normalized = re.sub(r"\s+", " ", self.css)
        self.assertIn(".modal-backdrop { z-index: 800;", normalized)
        self.assertIn(":focus-visible", self.css)
        self.assertIn(".official-decision-form > .form-actions { position: sticky;", normalized)
        self.assertIn(".decision-check, .official-missing-items label { min-height: 44px;", normalized)

    def test_internal_launch_consoles_are_not_part_of_daily_home(self) -> None:
        for panel_id in (
            "launchChecklistPanel",
            "launchJourneyAttestationPanel",
            "rolePerspectiveReview",
        ):
            self.assertRegex(self.html, rf'id="{panel_id}" hidden')
        normalized = re.sub(r"\s+", " ", self.css)
        self.assertIn("#dashboard > #scopeZone, #dashboard > .content-grid { display: none !important;", normalized)


if __name__ == "__main__":
    unittest.main()
