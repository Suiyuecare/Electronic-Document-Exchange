from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path

import backend


ROOT = Path(__file__).resolve().parents[1]


class UiUxP1P2ContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "styles.css").read_text(encoding="utf-8")

    def test_approval_progress_uses_three_plain_language_fields(self) -> None:
        for label in ("目前在誰手上", "已等待多久", "下一步"):
            self.assertIn(label, self.js)
        self.assertIn("function latestOfficialApprovalSteps", self.js)
        self.assertIn("function officialHumanProgress", self.js)
        self.assertIn("review_started_at", self.js)
        self.assertIn("workflow_generation", self.js)

    def test_notification_defaults_to_personal_unread_and_overdue(self) -> None:
        self.assertIn('let notificationFilter = "my_unread_overdue";', self.js)
        self.assertIn('data-notification-filter="my_unread_overdue"', self.html)
        self.assertIn("notificationRelatedToCurrentUser(item) && needsAttention", self.js)
        self.assertIn("目前沒有需要你處理的通知", self.js)

    def test_notification_rules_are_in_settings_not_task_center(self) -> None:
        notifications_start = self.html.index('<section class="view" id="notifications">')
        notifications_end = self.html.index('<section class="view" id="jobs">', notifications_start)
        task_center = self.html[notifications_start:notifications_end]
        settings_start = self.html.index('<section class="view" id="settings">')
        settings_end = self.html.index('</main>', settings_start)
        settings = self.html[settings_start:settings_end]
        self.assertNotIn('id="notificationScheduleForm"', task_center)
        self.assertNotIn('id="notificationGatewayForm"', task_center)
        self.assertIn('id="notificationScheduleForm"', settings)
        self.assertIn('id="notificationGatewayForm"', settings)

    def test_seal_vault_is_split_into_three_tabs(self) -> None:
        for tab in ("upload", "versions", "usage"):
            self.assertIn(f'data-seal-vault-tab="{tab}"', self.html)
            self.assertIn(f'data-seal-vault-panel="{tab}"', self.html)
        self.assertIn('let companySealVaultTab = "versions";', self.js)
        self.assertIn("function renderSimpleSealVersionHistory", self.js)
        self.assertIn("function renderSimpleSealUsage", self.js)
        self.assertIn(".seal-vault-tab-panel[hidden]", self.css)

    def test_role_onboarding_tutorial_is_removed(self) -> None:
        for element_id in ("roleOnboarding", "roleOnboardingShowBtn", "roleOnboardingDismissBtn", "roleOnboardingSteps"):
            self.assertNotIn(f'id="{element_id}"', self.html)
        for implementation in (
            "roleOnboardingProfiles",
            "roleOnboardingStorageKey",
            "renderRoleOnboarding",
            "dismissRoleOnboarding",
            "showRoleOnboarding",
        ):
            self.assertNotIn(implementation, self.js)
        self.assertNotIn("三步開始方式", self.js)

    def test_ux_telemetry_is_privacy_scoped_but_not_user_facing(self) -> None:
        for field_id in ("uxTaskCompletion", "uxReturnRate", "uxGuidanceRate", "uxMobileRatio"):
            self.assertNotIn(f'id="{field_id}"', self.html)
        self.assertNotIn("需要功能導引", self.html)
        render_start = self.js.index("function renderUxHealthMetrics()")
        render_end = self.js.index("\nfunction ", render_start + len("function renderUxHealthMetrics()"))
        render_body = self.js[render_start:render_end]
        guard = 'if (!document.querySelector("#uxHealthPanel")) return;'
        self.assertIn(guard, render_body)
        self.assertLess(render_body.index(guard), render_body.index("#uxTaskCompletion"))
        self.assertIn('backendRequest("/ui-usage"', self.js)
        self.assertIn('backendRequest("/ui-usage/summary")', self.js)

    def test_mobile_layout_stacks_new_panels(self) -> None:
        self.assertIn(".notification-settings-grid,", self.css)
        self.assertIn("grid-template-columns: minmax(0, 1fr);", self.css)

    def test_unified_login_copy_uses_wcag_aa_contrast_color(self) -> None:
        entry_start = self.css.index(".module-entry-card .eyebrow")
        entry_end = self.css.index(".module-entry-progress-track", entry_start)
        entry_styles = self.css[entry_start:entry_end]
        self.assertGreaterEqual(entry_styles.count("color: #80674f;"), 2)
        self.assertNotIn("color: #8b7358;", entry_styles)


class UiUsageBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = {
            "user": {"id": "USR-1", "company_id": "CO-1", "role": "總務"},
            "permissions": [],
        }

    def test_normalized_event_contains_no_content_or_identity(self) -> None:
        event = backend.normalize_ui_usage_payload(
            {
                "eventType": "search_result",
                "sessionId": "uis_1234567890123456",
                "deviceClass": "mobile",
                "route": "search",
                "resultEmpty": True,
                "resultCount": 0,
                "query": "不應保存的公文文字",
                "attachment": "secret.pdf",
            },
            self.session,
        )
        self.assertEqual(event["eventType"], "search_result")
        self.assertTrue(event["privacySafe"])
        self.assertNotIn("query", event)
        self.assertNotIn("attachment", event)
        self.assertNotIn("userId", event)

    def test_summary_deduplicates_sessions_and_counts_mobile_guidance(self) -> None:
        base = {
            "schemaVersion": 1,
            "sessionId": "uis_1234567890123456",
            "deviceClass": "mobile",
            "route": "dashboard",
            "resultEmpty": False,
            "resultCount": 0,
            "companyId": "CO-1",
            "privacySafe": True,
        }
        rows = [
            {"created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "metadata_json": json.dumps({**base, "eventType": "session_started"})},
            {"created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "metadata_json": json.dumps({**base, "eventType": "session_started"})},
            {"created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "metadata_json": json.dumps({**base, "eventType": "guidance_used"})},
        ]
        summary = backend.ui_usage_summary_from_rows(rows, self.session)
        self.assertEqual(summary["sessions"], 1)
        self.assertEqual(summary["mobileSessions"], 1)
        self.assertEqual(summary["guidanceSessions"], 1)
        self.assertEqual(summary["mobileRatio"], 100)
        self.assertEqual(summary["guidanceRate"], 100)

    def test_invalid_event_and_identifier_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            backend.normalize_ui_usage_payload(
                {"eventType": "pdf_content", "sessionId": "uis_1234567890123456", "deviceClass": "desktop", "route": "dashboard"},
                self.session,
            )
        with self.assertRaises(ValueError):
            backend.normalize_ui_usage_payload(
                {"eventType": "route_view", "sessionId": "short", "deviceClass": "desktop", "route": "dashboard"},
                self.session,
            )

    def test_usage_events_require_company_scope(self) -> None:
        session = {"user": {"id": "USR-1", "company_id": "", "role": "總務"}, "permissions": []}
        with self.assertRaises(PermissionError):
            backend.normalize_ui_usage_payload(
                {"eventType": "route_view", "sessionId": "uis_1234567890123456", "deviceClass": "desktop", "route": "dashboard"},
                session,
            )
        with self.assertRaises(PermissionError):
            backend.ui_usage_summary_from_rows([], session)


if __name__ == "__main__":
    unittest.main()
