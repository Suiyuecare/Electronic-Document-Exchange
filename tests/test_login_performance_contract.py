from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import backend


ROOT = Path(__file__).resolve().parents[1]


class FinanceSessionFastPathTest(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_environment = backend.DEPLOYMENT_ENV
        self.previous_ttl = backend.EDOC_FINANCE_SESSION_REVALIDATE_SECONDS
        backend.DEPLOYMENT_ENV = "production"
        backend.EDOC_FINANCE_SESSION_REVALIDATE_SECONDS = 60
        self.user = {
            "id": "FIN-TEST-100",
            "name": "去識別化測試人員",
            "email": "member-100@example.invalid",
            "status": "啟用",
            "role": "員工",
            "account_source": "finance",
            "logging_account_id": "finance-user-100",
            "finance_employee_id": "finance-user-100",
            "finance_source_revision": 12,
            "finance_source_event_id": "evt-finance-user-100-r12",
            "finance_source_status": "active",
            "company_id": "FINCO-100",
            # Finance and eDoc have separate Auth namespaces; this is allowed
            # to remain empty after a verified Portal handoff.
            "auth_user_id": None,
            "last_synced_from_logging_at": backend.now(),
        }
        self.session = {
            "id": "SESSION-100",
            "user_id": self.user["id"],
            "expires_at": "2099-01-01 00:00:00",
        }
        self.bundle = {
            "session": dict(self.session),
            "user": dict(self.user),
            "permissions": ["official_documents.compose"],
        }

    def tearDown(self) -> None:
        backend.DEPLOYMENT_ENV = self.previous_environment
        backend.EDOC_FINANCE_SESSION_REVALIDATE_SECONDS = self.previous_ttl

    def test_recent_live_finance_verification_skips_duplicate_bridge_call(self) -> None:
        with (
            patch("backend.supabase_request", return_value=dict(self.bundle)) as request,
            patch("backend.current_finance_bridge_snapshot") as bridge,
        ):
            current = backend.supabase_current_session("a" * 48)

        self.assertIsNotNone(current)
        self.assertIsNone(current["user"]["auth_user_id"])
        request.assert_called_once()
        self.assertEqual(request.call_args.args[1], "rpc/edoc_resolve_finance_session_v1")
        bridge.assert_not_called()

    def test_expired_short_cache_performs_one_live_revalidation(self) -> None:
        stale_user = {
            **self.user,
            "last_synced_from_logging_at": (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"),
        }
        refreshed_user = {**stale_user, "last_synced_from_logging_at": backend.now()}
        with (
            patch("backend.supabase_request", return_value={
                "session": dict(self.session),
                "user": stale_user,
                "permissions": [],
            }),
            patch("backend.current_finance_bridge_snapshot", return_value={"schemaVersion": 1}) as bridge,
            patch("backend.sync_supabase_finance_login_snapshot", return_value=refreshed_user) as sync,
            patch("backend.supabase_patch", return_value=refreshed_user) as update,
        ):
            current = backend.supabase_current_session("b" * 48)

        self.assertIsNotNone(current)
        bridge.assert_called_once_with(self.user["email"])
        sync.assert_called_once()
        update.assert_called_once()

    def test_session_creation_uses_one_atomic_rpc(self) -> None:
        def rpc(method, path, payload):
            self.assertEqual(method, "POST")
            self.assertEqual(path, "rpc/edoc_create_finance_login_session_v1")
            self.assertEqual(payload["p_user_id"], self.user["id"])
            return {
                "session": {
                    "id": payload["p_session_id"],
                    "user_id": self.user["id"],
                    "expires_at": payload["p_expires_at"],
                },
                "user": dict(self.user),
                "permissions": ["official_documents.compose"],
            }

        with (
            patch("backend.supabase_request", side_effect=rpc) as request,
            patch("backend.supabase_insert") as insert,
            patch("backend.supabase_patch") as update,
            patch("backend.supabase_role_permissions") as permissions,
        ):
            session = backend.supabase_create_finance_login_session(
                dict(self.user),
                "127.0.0.1",
                "contract-test",
            )

        self.assertEqual(session["user"]["id"], self.user["id"])
        self.assertIn("official_documents.compose", session["permissions"])
        request.assert_called_once()
        insert.assert_not_called()
        update.assert_not_called()
        permissions.assert_not_called()

    def test_installed_rpc_failure_remains_fail_closed(self) -> None:
        with (
            patch("backend.supabase_request", side_effect=RuntimeError("Supabase 400: finance_login_identity_ineligible")),
            patch("backend.supabase_insert") as insert,
        ):
            with self.assertRaises(RuntimeError):
                backend.supabase_create_finance_login_session(
                    dict(self.user),
                    "127.0.0.1",
                    "contract-test",
                )
        insert.assert_not_called()

    def test_finance_identity_aliases_resolve_in_one_data_api_request(self) -> None:
        source = {
            "finance_user_id": "finance-user-100",
            "email": "member-100@example.invalid",
        }
        with patch("backend.supabase_request", return_value=[dict(self.user)]) as request:
            candidate = backend._supabase_finance_snapshot_user_candidate(source)

        self.assertEqual(candidate["id"], self.user["id"])
        request.assert_called_once()
        method, path = request.call_args.args[:2]
        self.assertEqual(method, "GET")
        self.assertIn("users?", path)
        self.assertIn("or=", path)

    def test_role_permissions_use_one_embedded_data_api_request(self) -> None:
        with patch("backend.supabase_request", return_value=[{
            "id": "ROLE-STAFF",
            "role_permissions": [
                {"permission_id": "PERM-1", "permissions": {"code": "official_documents.compose"}},
                {"permission_id": "PERM-2", "permissions": {"code": "official_documents.view"}},
            ],
        }]) as request:
            permissions = backend.supabase_role_permissions("員工")

        self.assertIn("official_documents.compose", permissions)
        self.assertIn("official_documents.view", permissions)
        request.assert_called_once()
        method, path = request.call_args.args[:2]
        self.assertEqual(method, "GET")
        self.assertIn("role_permissions", path)
        self.assertIn("permissions%28code%29", path)

    def test_revalidation_window_is_short_and_fail_closed_when_missing(self) -> None:
        self.assertFalse(backend.finance_session_revalidation_due(self.user))
        self.assertTrue(backend.finance_session_revalidation_due({}))

    def test_signed_portal_first_visit_promotes_active_pending_employee(self) -> None:
        pending = {
            **self.user,
            "status": "待啟用",
            "finance_source_status": "pending",
        }
        applicant = {
            "finance_user_id": self.user["logging_account_id"],
            "email": self.user["email"],
            "entity_id": "E100",
            "projection_state": "pending",
            "source_revision": 12,
            "profile": {"logging_role_key": "staff"},
        }
        company = {
            "id": self.user["company_id"],
            "finance_entity_id": "E100",
            "name": "去識別化測試公司",
            "status": "active",
        }
        enabled = {**pending, "status": "啟用", "finance_source_status": "active"}
        snapshot = {"company": {"entityId": "E100", "name": "去識別化測試公司"}}
        with (
            patch("backend.normalize_finance_bridge_snapshot", return_value={
                "applicant": applicant,
                "actors": {},
                "metadata": {},
            }),
            patch("backend._supabase_finance_snapshot_user_candidate", return_value=pending),
            patch("backend.supabase_upsert_finance_company_snapshot", return_value=(company, "resolved")),
            patch("backend._supabase_upsert_finance_snapshot_user", return_value=(pending, "stale")),
            patch("backend.supabase_patch", return_value=enabled) as update,
            patch("backend.supabase_upsert_finance_module_link") as link,
            patch("backend.supabase_enforce_finance_company_state", return_value=(enabled, False)),
        ):
            user = backend.sync_supabase_finance_login_snapshot(
                snapshot,
                portal_authenticated=True,
            )

        self.assertEqual(user["status"], "啟用")
        self.assertEqual(applicant["projection_state"], "active")
        update.assert_called_once()
        link.assert_called_once()

    def test_readiness_accepts_revisioned_finance_identity_without_edoc_auth_uuid(self) -> None:
        self.assertTrue(backend.user_has_formal_login_identity(self.user))

        for override in (
            {"finance_source_status": "pending"},
            {"finance_source_revision": 0},
            {"finance_source_event_id": ""},
            {"logging_account_id": "", "finance_employee_id": ""},
            {"company_id": ""},
        ):
            with self.subTest(override=override):
                self.assertFalse(backend.user_has_formal_login_identity({**self.user, **override}))


class EntryExperienceContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "styles.css").read_text(encoding="utf-8")

    def test_entry_screen_has_named_determinate_progress(self) -> None:
        for marker in (
            'id="moduleEntryProgress"',
            'id="moduleEntryProgressBar"',
            'id="moduleEntryProgressPercent"',
            "正在確認公司帳號",
        ):
            self.assertIn(marker, self.html)
        self.assertIn("function setModuleEntryProgress", self.js)
        self.assertIn("finishModuleEntryProgress", self.js)

    def test_startup_sync_loads_only_dashboard_sources(self) -> None:
        start = self.js.index("function runAuthenticatedStartupSyncs")
        end = self.js.index("\nconst routeBackendDataLoaded", start)
        body = self.js[start:end]
        self.assertIn("loadOfficialWorkflow", body)
        self.assertIn("syncNotificationsFromBackend", body)
        self.assertIn("syncDashboardFromBackend", body)
        for heavy in (
            "syncDatabaseFromBackend",
            "syncJobsFromBackend",
            "loadCompanySealModule",
            "syncGoLiveAuditFromBackend",
        ):
            self.assertNotIn(heavy, body)

    def test_heavy_workspace_render_is_deferred_until_after_authentication(self) -> None:
        self.assertIn("function initializeDeferredWorkspace()", self.js)
        self.assertIn("scheduleDeferredWorkspaceInitialization();", self.js)
        bootstrap = self.js[self.js.rindex("updateHeaderStatus();") :]
        self.assertIn("tryResumePlatformSession()", bootstrap)
        self.assertNotIn("renderDatabase();", bootstrap)
        self.assertNotIn("renderWorkflowTasks();", bootstrap)

    def test_kai_type_is_reserved_for_document_output_not_product_forms(self) -> None:
        self.assertNotIn(".official-document-entry :is(", self.css)
        self.assertIn(".official-draft-preview", self.css)
        self.assertIn('font-family: "EDoc LXGW WenKai TC", "標楷體"', self.css)
        self.assertIn("#uploadedSealTextInput", self.css)

    def test_login_fast_path_migration_is_service_role_only(self) -> None:
        sql = (ROOT / "supabase" / "migrations" / "20260824124500_finance_login_fast_path.sql").read_text(encoding="utf-8")
        normalized = " ".join(sql.lower().split())
        self.assertIn("security definer", normalized)
        self.assertIn("set search_path = pg_catalog, public", normalized)
        self.assertIn("revoke all on function public.edoc_create_finance_login_session_v1", normalized)
        self.assertIn("revoke all on function public.edoc_resolve_finance_session_v1", normalized)
        self.assertIn("from public, anon, authenticated", normalized)
        self.assertIn("to service_role", normalized)


if __name__ == "__main__":
    unittest.main()
