from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UiUxSimplificationContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "styles.css").read_text(encoding="utf-8")

    def test_daily_navigation_has_no_duplicate_contract_or_workflow_entry(self) -> None:
        start = self.js.index("const navByIdentity = {")
        end = self.js.index("\n};", start) + 3
        navigation = self.js[start:end]
        self.assertNotIn('"contractSeal"', navigation)
        self.assertNotIn('"workflow"', navigation)
        for route in ("dashboard", "compose", "electronicSeal", "approvalLog", "inbound", "settings"):
            self.assertIn(f'"{route}"', navigation)
        self.assertNotIn('"search"', navigation)

    def test_legacy_contract_route_remains_available_without_being_primary(self) -> None:
        start = self.js.index("const secondaryRoutesByIdentity = {")
        end = self.js.index("\n};", start) + 3
        secondary = self.js[start:end]
        self.assertIn('"contractSeal"', secondary)
        self.assertNotIn('"exchange"', secondary)

    def test_internal_launch_dashboard_does_not_promote_disabled_exchange(self) -> None:
        start = self.js.index("function dashboardRoleData()")
        end = self.js.index("\nfunction dashboardApprovalTasks", start)
        dashboard = self.js[start:end]
        self.assertIn("const internalOnly = formalExchangeUiBlocked();", dashboard)
        for label in ("待寄發", "退回補正", "申請人待收件", "今日優先"):
            self.assertIn(label, dashboard)
        self.assertIn("backendMetrics && formalExchangeUiBlocked()", dashboard)

    def test_supervisor_quick_actions_only_show_authorized_routes(self) -> None:
        start = self.js.index("function renderSupervisorCommandDashboard()")
        end = self.js.index("\nfunction isOpenOperationalStatus", start)
        body = self.js[start:end]
        self.assertIn(".filter(([, target]) => isRouteAllowed(target))", body)
        self.assertIn("operationalExceptions", body)

    def test_dashboard_starts_with_daily_work_instead_of_launch_consoles(self) -> None:
        body_start = self.js.index("function renderRoleDashboard()")
        body_end = self.js.index("\nfunction dashboardApprovalTasks", body_start)
        body = self.js[body_start:body_end]
        self.assertIn("renderDailyActionCenter();", body)
        self.assertNotIn("renderGoLiveGate();", body)
        self.assertNotIn("renderLaunchChecklist();", body)
        self.assertNotIn("renderRolePerspectiveReview();", body)
        for panel_id in (
            "goLiveGatePanel",
            "launchChecklistPanel",
            "launchJourneyAttestationPanel",
            "rolePerspectiveReview",
        ):
            self.assertRegex(self.css, rf"#dashboard\s*>\s*#{panel_id}")

    def test_mobile_workspace_scroll_and_workflow_width_are_bounded(self) -> None:
        normalized = re.sub(r"\s+", " ", self.css)
        self.assertIn(".workspace { display: flex; flex: 1; flex-direction: column; min-height: 0;", normalized)
        self.assertIn("overflow: hidden; background: #f7f3ec;", normalized)
        self.assertIn(".view.active { display: block; flex: 1; min-height: 0; overflow: auto;", normalized)
        self.assertIn(".workflow-workbench { grid-template-columns: minmax(0, 1fr); max-width: 100%;", normalized)
        self.assertIn(".workflow-workbench > *, .notification-layout > *", normalized)
        self.assertIn(".ops-production-checklist > * { min-width: 0; max-width: 100%;", normalized)

    def test_secondary_management_pages_do_not_expand_mobile_viewport(self) -> None:
        normalized = re.sub(r"\s+", " ", self.css)
        self.assertIn(".notification-layout, .tracking-layout, .report-layout, .report-workbench, .account-layout, .ops-layout, .go-live-ops-panel, .go-live-ops-grid, .ops-production-checklist { grid-template-columns: minmax(0, 1fr); max-width: 100%;", normalized)
        self.assertIn(".notification-layout > *, .tracking-layout > *, .report-layout > *, .report-workbench > *, .account-layout > *, .ops-layout > *, .go-live-ops-panel > *", normalized)
        self.assertIn(".report-layout > .panel, .report-workbench > .panel, .go-live-ops-panel { overflow: hidden;", normalized)
        self.assertIn(".go-live-category *, .ops-production-check * { min-width: 0; overflow-wrap: anywhere;", normalized)

    def test_mobile_header_keeps_only_essential_actions(self) -> None:
        self.assertRegex(self.css, r"#headerRefreshBtn\s*\{\s*display:\s*none;")
        self.assertRegex(self.css, r"\.top-info\s*\{\s*display:\s*none;")
        self.assertIn('id="returnPortalBtn"', self.html)
        self.assertIn('id="logoutBtn"', self.html)

    def test_core_page_guidance_uses_plain_chinese(self) -> None:
        for label in ("今日待辦", "簽核案件", "兩步完成", "四步完成", "固定簽核規則", "印章版本控管"):
            self.assertIn(label, self.html)
        for label in ("General Affairs Desk", "General Affairs Home", "Contract Seal Application"):
            self.assertNotIn(label, self.js)

    def test_mobile_primary_controls_have_44px_touch_targets(self) -> None:
        normalized = re.sub(r"\s+", " ", self.css)
        self.assertIn(".nav-list { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));", normalized)
        self.assertIn(".nav-item { display: inline-flex; justify-content: center; min-width: 0; min-height: 44px;", normalized)
        self.assertIn(".module-switch-button, .topbar-notification-button { min-height: 44px;", normalized)
        self.assertIn(".flow-step-chip, .segment, .page-arrow, .text-button, .unified-flow-row-button, .contract-link, .pdf-editor-v2 button { min-height: 44px;", normalized)
        self.assertIn(".page-arrow { min-width: 44px;", normalized)
        self.assertIn(".contract-link { display: inline-flex; align-items: center;", normalized)
        self.assertIn(".view button.primary-button, .view button.secondary-button, .view button.icon-button { min-height: 44px;", normalized)

    def test_active_major_navigation_uses_readable_brand_orange(self) -> None:
        self.assertIn("--accent-readable: #b74f08;", self.css)
        normalized = re.sub(r"\s+", " ", self.css)
        self.assertIn(".nav-item:hover, .nav-item.active { background: var(--accent-readable); color: #fff;", normalized)

    def test_navigation_uses_exactly_six_major_functions_without_second_row(self) -> None:
        nav_start = self.html.index('<nav class="nav-list"')
        nav_end = self.html.index("</nav>", nav_start)
        navigation = self.html[nav_start:nav_end]
        routes_and_labels = re.findall(r'class="nav-item(?: active)?" data-target="([^"]+)" data-icon="[^"]+">([^<]+)</button>', navigation)
        self.assertEqual(routes_and_labels, [
            ("dashboard", "首頁"),
            ("compose", "撰寫公文"),
            ("electronicSeal", "電子用印"),
            ("approvalLog", "簽核紀錄"),
            ("inbound", "收發管理"),
            ("settings", "系統設定"),
        ])
        self.assertEqual(navigation.count('class="nav-item'), 6)
        self.assertNotIn('id="workspaceSubnav"', self.html)
        self.assertNotIn('id="navMoreBtn"', self.html)
        self.assertNotIn('id="navMoreDialog"', self.html)
        self.assertNotIn("workspaceNavigationGroups", self.js)
        self.assertNotIn("renderWorkspaceSubnavigation", self.js)
        self.assertNotIn("workspace-subnav-button", self.css)

    def test_legacy_pages_are_folded_into_one_of_the_six_major_functions(self) -> None:
        start = self.js.index("const mergedNavigationParents = Object.freeze({")
        end = self.js.index("\n});", start) + 4
        parents = self.js[start:end]
        for route, parent in (
            ("notifications", "dashboard"),
            ("search", "inbound"),
            ("tracking", "inbound"),
            ("contracts", "electronicSeal"),
            ("contractSeal", "electronicSeal"),
            ("seals", "electronicSeal"),
            ("workflow", "settings"),
            ("reports", "approvalLog"),
            ("accounts", "settings"),
            ("ops", "settings"),
        ):
            self.assertIn(f'{route}: "{parent}"', parents)
        self.assertIn("const activeMajorRoute = majorRouteForRoute(target);", self.js)
        self.assertIn("simpleRouteTitle(activeMajorRoute)", self.js)

    def test_notification_bell_opens_home_task_center(self) -> None:
        start = self.js.index('document.querySelector("#headerNotificationBtn")')
        end = self.js.index("\n});", start) + 4
        handler = self.js[start:end]
        self.assertIn('setView("dashboard");', handler)
        self.assertIn('document.querySelector("#dailyActionCenter")', handler)
        self.assertNotIn('setView(isRouteAllowed("notifications")', handler)

    def test_entry_loading_brand_asset_is_packaged_for_vercel(self) -> None:
        vercel = (ROOT / "vercel.json").read_text(encoding="utf-8")
        self.assertIn('assets/suiyue-milk-favicon.png', self.html)
        self.assertIn('"src": "assets/suiyue-milk-favicon.png"', vercel)

    def test_employee_startup_does_not_request_admin_notification_health(self) -> None:
        start = self.js.index("async function syncNotificationsFromBackend")
        end = self.js.index("\nasync function checkBackendHealth", start)
        body = self.js[start:end]
        self.assertIn('hasBackendPermission("settings.system_manage")', body)
        self.assertIn('hasBackendPermission("settings.manage")', body)
        self.assertIn("await refreshNotificationGatewayStatus(true);", body)

    def test_submit_result_clears_hidden_filters_and_opens_created_document(self) -> None:
        start = self.js.index("function resetOfficialWorkflowListFilters()")
        end = self.js.index("\nasync function loadApprovalProgressFromBackend", start)
        body = self.js[start:end]
        self.assertIn('officialWorkflowStatusFilter = "";', body)
        self.assertIn('officialWorkflowSearchTerm = "";', body)
        self.assertIn('await loadOfficialWorkflow("mine");', body)
        self.assertIn("await loadOfficialDocumentDetail(documentId);", body)
        self.assertGreaterEqual(self.js.count("await showSubmittedOfficialDocument("), 3)


if __name__ == "__main__":
    unittest.main()
