from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import backend
from tools import live_five_account_sso_acceptance as acceptance


class LaunchAccountTruthfulnessTest(unittest.TestCase):
    def package(self, roles):
        report = {"launchSmokeReport": {"accessReadiness": {
            "counts": {"activeUserCount": len(roles), "demoAccountsDisabled": True,
                       "demoAccountsExplicitlyDisabled": True},
            "roleChecks": [{"role": role, "activeCount": 1, "formalAccountCount": 1,
                            "hasActiveUser": True, "hasFormalAccount": True} for role in roles],
        }}}
        with mock.patch.object(backend, "current_go_live_audit_report", return_value=report):
            return backend.current_account_readiness_package()

    def test_ceo_is_required_for_supported_cd_routes(self):
        package = self.package(["員工", "主管", "主任", "行政部主任", "總務"])
        self.assertEqual(package["missingFormalRoleCount"], 1)
        self.assertEqual(package["decision"], "BLOCKED")
        self.assertTrue(next(row for row in package["roleTasks"] if row["role"] == "執行長")["required"])
        self.assertIn("執行長", backend.INTERNAL_LAUNCH_REQUIRED_ROLES)

    def test_ready_roster_is_not_claimed_as_human_login_acceptance(self):
        package = self.package(["員工", "主管", "主任", "執行長", "行政部主任", "總務"])
        self.assertEqual(package["missingFormalRoleCount"], 0)
        login = next(row for row in package["policyTasks"] if row["key"] == "formal_role_login_smoke")
        self.assertIn("待真人驗收", login["status"])
        self.assertTrue(package["rosterImportTemplate"]["deprecated"])
        self.assertEqual(package["rosterImportTemplate"]["rows"], [])
        self.assertIsNone(package["rosterImportTemplate"]["importApi"])
        self.assertTrue(all("POST /api/users" not in row["api"] for row in package["roleTasks"]))

    def test_legacy_template_endpoint_exports_sync_checklist_not_manual_roster(self):
        package = self.package(["員工"])
        with mock.patch.object(backend, "current_account_readiness_package", return_value=package):
            artifact = backend.production_formal_account_roster_template_artifact()
        self.assertEqual(artifact["xArtifact"], "finance-account-sync-checklist")
        self.assertNotIn("formal-account-import", artifact["file_name"])

    def test_pending_users_are_not_counted_as_disabled_in_ui(self):
        source = (Path(__file__).resolve().parents[1] / "app.js").read_text()
        section = source.split("function renderAccountSummary()", 1)[1].split("function renderAccountRows()", 1)[0]
        self.assertIn('account.status === "待啟用"', section)
        self.assertIn('account.status === "停用"', section)
        self.assertNotIn("userAccounts.length - enabled", section)
        self.assertNotIn(' : "正式角色可登入"', source)

    def test_live_probe_revokes_session_even_when_validation_fails(self):
        def fail_after_login(*args):
            args[-1].append("ephemeral-test-token")
            raise acceptance.AcceptanceError("directory_invalid")
        with mock.patch.object(acceptance, "_acceptance_for_account", side_effect=fail_after_login), \
             mock.patch.object(acceptance, "request_json", side_effect=[(200, {"ok": True}), (401, {})]) as request:
            with self.assertRaisesRegex(acceptance.AcceptanceError, "directory_invalid"):
                acceptance.acceptance_for_account("unused", "unused", "unused", 1)
        self.assertEqual(request.call_count, 2)
        self.assertTrue(request.call_args_list[0].args[0].endswith("/auth/logout"))

    def test_live_probe_fails_if_logout_did_not_revoke_session(self):
        def succeeds(*args):
            args[-1].append("ephemeral-test-token")
            return {"handoff303": 1}
        with mock.patch.object(acceptance, "_acceptance_for_account", side_effect=succeeds), \
             mock.patch.object(acceptance, "request_json", side_effect=[(200, {"ok": True}), (200, {})]):
            with self.assertRaisesRegex(acceptance.AcceptanceError, "acceptance_session_not_revoked"):
                acceptance.acceptance_for_account("unused", "unused", "unused", 1)
