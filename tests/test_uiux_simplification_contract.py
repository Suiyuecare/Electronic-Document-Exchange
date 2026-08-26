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

    def test_legacy_contract_route_is_retired_from_daily_navigation(self) -> None:
        start = self.js.index("const secondaryRoutesByIdentity = {")
        end = self.js.index("\n};", start) + 3
        secondary = self.js[start:end]
        self.assertIn('"contracts"', secondary)
        self.assertNotIn('"contractSeal"', secondary)
        self.assertIn('"format"', secondary)
        self.assertIn('"exchange"', secondary)

    def test_executive_does_not_open_legacy_raw_operations_consoles(self) -> None:
        start = self.js.index("const secondaryRoutesByIdentity = {")
        end = self.js.index("\n};", start) + 3
        secondary = self.js[start:end]
        executive = re.search(r"executive:\s*\[(.*?)\]", secondary, re.DOTALL)
        self.assertIsNotNone(executive)
        executive_routes = executive.group(1)
        self.assertNotIn('"jobs"', executive_routes)
        self.assertNotIn('"database"', executive_routes)
        for route in ('"workflow"', '"accounts"', '"security"', '"ops"'):
            self.assertIn(route, executive_routes)

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
        for label in ("今日待辦", "簽核案件", "固定簽核規則", "印章版本控管"):
            self.assertIn(label, self.html)
        for teaching_copy in ("兩步完成", "四步完成", "第一次使用", "三步開始今天的工作"):
            self.assertNotIn(teaching_copy, self.html + self.js)
        for label in ("General Affairs Desk", "General Affairs Home", "Contract Seal Application"):
            self.assertNotIn(label, self.js)

    def test_mobile_primary_controls_have_44px_touch_targets(self) -> None:
        normalized = re.sub(r"\s+", " ", self.css)
        self.assertIn(".mobile-primary-item { display: flex; min-width: 0; min-height: 54px;", normalized)
        self.assertIn(".mobile-menu-button { grid-area: menu; display: flex; width: 40px; min-width: 40px; height: 40px; min-height: 40px;", normalized)
        self.assertIn(".sidebar .nav-item { display: grid; grid-template-columns: 38px minmax(0, 1fr); gap: 12px; min-width: 0; min-height: 54px;", normalized)
        self.assertIn(".flow-step-chip, .segment, .page-arrow, .text-button, .unified-flow-row-button, .contract-link, .pdf-editor-v2 button { min-height: 44px;", normalized)
        self.assertIn(".page-arrow { min-width: 44px;", normalized)
        self.assertIn(".contract-link { display: inline-flex; align-items: center;", normalized)
        self.assertIn(".view button.primary-button, .view button.secondary-button, .view button.icon-button { min-height: 44px;", normalized)

    def test_active_major_navigation_uses_finance_brand_orange(self) -> None:
        self.assertIn("--accent: #ea880c;", self.css)
        self.assertIn("--accent-readable: #b45309;", self.css)
        normalized = re.sub(r"\s+", " ", self.css)
        self.assertIn(".nav-item:hover, .nav-item.active { background: var(--accent-readable);", normalized)

    def test_shell_uses_finance_tokens_logo_and_desktop_frame(self) -> None:
        for token in (
            "--ink: #2f2a26;",
            "--muted: #6e6259;",
            "--line: #f1cfa8;",
            "--soft: #fff4e4;",
            "--accent: #ea880c;",
            "--accent-strong: #b45309;",
            "--cream: #fff9f2;",
        ):
            self.assertIn(token, self.css)
        normalized = re.sub(r"\s+", " ", self.css)
        self.assertIn(".app { width: 100%; max-width: none; min-height: 100dvh; height: 100dvh;", normalized)
        self.assertIn(".sidebar { flex: 0 0 300px; width: 300px;", normalized)
        self.assertIn(".topbar { display: flex; min-height: 82px; height: 82px; max-height: 82px;", normalized)
        self.assertGreaterEqual(self.html.count('src="assets/suiyue-logo-transparent.png"'), 3)
        logo = ROOT / "assets" / "suiyue-logo-transparent.png"
        self.assertTrue(logo.is_file())
        self.assertEqual(logo.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_mobile_shell_has_four_primary_actions_and_six_item_drawer(self) -> None:
        nav_start = self.html.index('<nav class="mobile-primary-nav"')
        nav_end = self.html.index("</nav>", nav_start)
        mobile_navigation = self.html[nav_start:nav_end]
        self.assertEqual(
            re.findall(r'class="mobile-primary-item(?: active)?" data-target="([^"]+)"[^>]+aria-label="([^"]+)"', mobile_navigation),
            [
                ("dashboard", "首頁"),
                ("compose", "撰寫公文"),
                ("electronicSeal", "電子用印"),
                ("approvalLog", "簽核紀錄"),
            ],
        )
        for element_id in (
            "primarySidebar",
            "mobileMenuButton",
            "mobileDrawerCloseBtn",
            "mobileDrawerBackdrop",
            "mobileDrawerRefreshBtn",
            "mobileDrawerPortalBtn",
            "mobileDrawerLogoutBtn",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        normalized = re.sub(r"\s+", " ", self.css)
        self.assertIn("--mobile-nav-height: 68px;", self.css)
        self.assertIn(".topbar { position: sticky; top: 0; z-index: 90; display: grid;", normalized)
        self.assertIn("min-height: 56px; height: 56px; max-height: 56px;", normalized)
        self.assertIn(".sidebar { position: fixed; top: 0; bottom: 0; left: 0; z-index: 510;", normalized)
        for function_name in (
            "setMobileNavigationOpen",
            "openMobileNavigation",
            "closeMobileNavigation",
            "syncMobileNavigationMode",
        ):
            self.assertIn(f"function {function_name}", self.js)

    def test_login_surface_is_finance_handoff_only(self) -> None:
        login_start = self.html.index('id="loginScreen"')
        login_end = self.html.index('id="appShell"', login_start)
        login_surface = self.html[login_start:login_end]
        self.assertIn("本系統沒有獨立登入頁", login_surface)
        self.assertIn('id="loginReturnPortalBtn"', login_surface)
        self.assertNotIn('type="password"', login_surface)
        self.assertNotIn("使用 Google 帳號快速登入", login_surface)
        self.assertIn("returnToLoggingPortalModulePicker", self.js)

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

    def test_legacy_pages_are_integrated_into_the_six_major_pages_at_runtime(self) -> None:
        start = self.js.index("const mergedNavigationParents = Object.freeze({")
        end = self.js.index("\n});", start) + 4
        parents = self.js[start:end]
        for route, parent in (
            ("notifications", "dashboard"),
            ("search", "inbound"),
            ("dispatch", "inbound"),
            ("tracking", "inbound"),
            ("archive", "inbound"),
            ("contractSeal", "electronicSeal"),
            ("seals", "settings"),
            ("format", "compose"),
            ("workflow", "settings"),
            ("exchange", "settings"),
            ("reports", "approvalLog"),
            ("accounts", "settings"),
            ("ops", "settings"),
        ):
            self.assertIn(f'{route}: "{parent}"', parents)

        groups_start = self.js.index("const integratedMajorPageGroups")
        groups_end = self.js.index("\n});", groups_start) + 4
        groups = self.js[groups_start:groups_end]
        for route in (
            "notifications",
            "search",
            "dispatch",
            "tracking",
            "archive",
            "seals",
            "format",
            "workflow",
            "exchange",
            "reports",
            "accounts",
            "ops",
        ):
            self.assertIn(f'"{route}"', groups)

        retired_start = self.js.index("const retiredMergedRoutes")
        retired_end = self.js.index(";", retired_start) + 1
        retired = self.js[retired_start:retired_end]
        self.assertIn('"contractSeal"', retired)
        self.assertNotIn('"contracts"', retired)
        self.assertNotIn('"format"', retired)

        electronic_seal_match = re.search(
            r"electronicSeal:\s*\[(.*?)\]\s*,\s*approvalLog:",
            groups,
            re.DOTALL,
        )
        self.assertIsNotNone(electronic_seal_match)
        electronic_seal_group = electronic_seal_match.group(1)
        self.assertNotIn('"contracts"', electronic_seal_group)
        self.assertNotIn("合約案件", electronic_seal_group)
        self.assertNotIn('"seals"', electronic_seal_group)

        settings_match = re.search(r"settings:\s*\[(.*?)\]\s*\n\}\);", groups, re.DOTALL)
        self.assertIsNotNone(settings_match)
        settings_group = settings_match.group(1)
        self.assertIn('["seals", "印章檔案", false]', settings_group)

        primary_start = self.js.index("function primaryRoutesForRole(")
        primary_end = self.js.index("\nfunction secondaryRoutesForRole(", primary_start)
        primary_routes = self.js[primary_start:primary_end]
        self.assertIn('role === "行政部主任"', primary_routes)
        self.assertIn("navByIdentity.administrativeDirector", primary_routes)

        primary_identity_start = self.js.index("const navByIdentity = {")
        primary_identity_end = self.js.index("\n};", primary_identity_start)
        primary_identity = self.js[primary_identity_start:primary_identity_end]
        company_ops_primary = next(line for line in primary_identity.splitlines() if line.strip().startswith("companyOps:"))
        self.assertIn('"settings"', company_ops_primary)

        secondary_start = self.js.index("const secondaryRoutesByIdentity = {")
        secondary_end = self.js.index("\n};", secondary_start)
        secondary_routes = self.js[secondary_start:secondary_end]
        company_ops_line = next(line for line in secondary_routes.splitlines() if line.strip().startswith("companyOps:"))
        administrative_director_line = next(line for line in secondary_routes.splitlines() if line.strip().startswith("administrativeDirector:"))
        self.assertIn('"seals"', company_ops_line)
        self.assertIn('"seals"', administrative_director_line)

        role_navigation_start = self.js.index("function canViewSystemSettingsBase()")
        role_navigation_end = self.js.index("\nfunction internalDispatchRecipientForCurrentUser", role_navigation_start)
        role_navigation = self.js[role_navigation_start:role_navigation_end]
        self.assertIn("hasAuthenticatedBackendSession()", role_navigation)
        self.assertIn("authState?.permissions", role_navigation)
        self.assertIn('permissionCodes.includes("settings.system_manage")', role_navigation)
        self.assertIn('permissionCodes.includes("settings.manage")', role_navigation)
        self.assertIn('.integrated-page-section[data-integrated-base="settings"]', role_navigation)
        self.assertIn("const canViewSettingsBase = canViewSystemSettingsBase();", role_navigation)
        self.assertIn('document.querySelectorAll("[data-settings-base-controls]")', role_navigation)
        self.assertIn("control.disabled = !canViewSettingsBase;", role_navigation)
        self.assertIn("data-settings-base-controls", self.html)

        self.assertIn("function companySealCompaniesForCurrentUser(", self.js)
        self.assertIn("function preferredCompanySealCompanyId(", self.js)
        self.assertIn('authState?.user?.company_id', self.js)

        self.assertIn("function initializeIntegratedMajorPages()", self.js)
        self.assertIn("function openIntegratedPageSection(", self.js)
        self.assertIn("initializeIntegratedMajorPages();", self.js)
        self.assertLess(
            self.js.index("initializeIntegratedMajorPages();"),
            self.js.index("void tryResumePlatformSession()"),
        )

        initialize_start = self.js.index("function initializeIntegratedMajorPages()")
        initialize_end = self.js.index("\nfunction ", initialize_start + len("function initializeIntegratedMajorPages()"))
        initialize_body = self.js[initialize_start:initialize_end]
        self.assertIn("dataset.integratedRoute", initialize_body)
        self.assertRegex(
            initialize_body,
            r'classList\.remove\("view",\s*"active"\)',
        )
        self.assertIn(".append(", initialize_body)

        view_start = self.js.index("function setView(target)")
        view_end = self.js.index("\nwindow.addEventListener(\"hashchange\"", view_start)
        set_view = self.js[view_start:view_end]
        self.assertIn("const activeMajorRoute = majorRouteForRoute(target);", set_view)
        self.assertRegex(
            set_view,
            r'classList\.toggle\("active",\s*view\.id\s*===\s*activeMajorRoute\)',
        )
        self.assertIn("openIntegratedPageSection(target", set_view)
        self.assertNotIn('target === "contractSeal" ? "electronicSeal" : target', set_view)
        self.assertIn("simpleRouteTitle(activeMajorRoute)", set_view)

    def test_tutorial_and_feature_catalog_are_removed_not_merely_hidden(self) -> None:
        for element_id in ("roleOnboarding", "roleOnboardingShowBtn", "roleOnboardingDismissBtn", "features", "featureGrid"):
            self.assertNotIn(f'id="{element_id}"', self.html)
        for implementation in (
            "roleOnboardingProfiles",
            "roleOnboardingStorageKey",
            "renderRoleOnboarding",
            "dismissRoleOnboarding",
            "showRoleOnboarding",
            "featureGroups",
            "renderFeatureGrid",
        ):
            self.assertNotIn(implementation, self.js)
        self.assertNotIn('features: "settings"', self.js)

    def test_notification_bell_opens_home_task_center(self) -> None:
        start = self.js.index('document.querySelector("#headerNotificationBtn")')
        end = self.js.index("\n});", start) + 4
        handler = self.js[start:end]
        self.assertIn('setView("dashboard");', handler)
        self.assertIn('document.querySelector("#dailyActionCenter")', handler)
        self.assertNotIn('setView(isRouteAllowed("notifications")', handler)

    def test_entry_loading_uses_shared_finance_brand_asset(self) -> None:
        asset = ROOT / "assets" / "suiyue-logo-transparent.png"
        vercel = (ROOT / "vercel.json").read_text(encoding="utf-8")
        self.assertIn('assets/suiyue-logo-transparent.png', self.html)
        self.assertIn('"src": "assets/suiyue-logo-transparent.png"', vercel)
        self.assertTrue(asset.is_file())
        self.assertEqual(asset.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

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
