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
            "finance_tenant_id": "tenant-100",
            "logging_account_id": "finance-user-100",
            "finance_employee_id": "finance-user-100",
            "logging_role_key": "staff",
            "job_level": "職員",
            "unit": "業務部",
            "title": "職員",
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

    def expected_binding(self) -> dict:
        return {
            "tenant_id": "tenant-100",
            "user_id": self.user["id"],
            "company_id": self.user["company_id"],
            "entity_id": "E100",
            "finance_user_id": self.user["logging_account_id"],
            "email": self.user["email"],
            "role": self.user["role"],
            "logging_role_key": self.user["logging_role_key"],
            "job_level": self.user["job_level"],
            "unit": self.user["unit"],
            "title": self.user["title"],
            "status": self.user["status"],
            "projection_state": self.user["finance_source_status"],
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
        refreshed_user = {
            **stale_user,
            backend.FINANCE_LOGIN_EXPECTED_BINDING_KEY: self.expected_binding(),
        }

        def rpc(_method, path, payload=None):
            if path == "rpc/edoc_resolve_finance_session_v1":
                return {
                    "session": dict(self.session),
                    "user": stale_user,
                    "permissions": [],
                }
            self.assertEqual(path, "rpc/edoc_revalidate_finance_session_v2")
            self.assertEqual(payload["p_session_id"], self.session["id"])
            self.assertEqual(payload["p_expected_role"], "員工")
            self.assertEqual(payload["p_expected_unit"], self.user["unit"])
            return {
                "session": dict(self.session),
                "user": {
                    **stale_user,
                    "last_synced_from_logging_at": payload["p_verified_at"],
                },
                "permissions": ["official_documents.compose"],
            }

        with (
            patch("backend.supabase_request", side_effect=rpc) as request,
            patch("backend.current_finance_bridge_snapshot", return_value={"schemaVersion": 1}) as bridge,
            patch("backend.sync_supabase_finance_login_snapshot", return_value=refreshed_user) as sync,
            patch("backend.supabase_patch") as update,
        ):
            current = backend.supabase_current_session("b" * 48)

        self.assertIsNotNone(current)
        self.assertEqual(current["user"]["role"], "員工")
        self.assertNotIn(backend.FINANCE_LOGIN_EXPECTED_BINDING_KEY, current["user"])
        bridge.assert_called_once_with(
            self.user["email"],
            portal_authenticated=True,
        )
        sync.assert_called_once()
        self.assertEqual(request.call_count, 2)
        update.assert_not_called()

    def test_revalidation_rpc_rejects_staff_to_ceo_race_without_high_permissions(self) -> None:
        stale_user = {
            **self.user,
            "last_synced_from_logging_at": "2000-01-01 00:00:00",
        }
        refreshed_user = {
            **stale_user,
            backend.FINANCE_LOGIN_EXPECTED_BINDING_KEY: self.expected_binding(),
        }

        def rpc(_method, path, payload=None):
            if path == "rpc/edoc_resolve_finance_session_v1":
                return {
                    "session": dict(self.session),
                    "user": stale_user,
                    "permissions": ["official_documents.compose"],
                }
            self.assertEqual(path, "rpc/edoc_revalidate_finance_session_v2")
            return {
                "session": dict(self.session),
                "user": {
                    **stale_user,
                    "role": "執行長",
                    "logging_role_key": "ceo",
                    "job_level": "執行長",
                    "last_synced_from_logging_at": payload["p_verified_at"],
                },
                "permissions": ["system_permissions.manage"],
            }

        with (
            patch("backend.supabase_request", side_effect=rpc),
            patch("backend.current_finance_bridge_snapshot", return_value={"schemaVersion": 1}),
            patch("backend.sync_supabase_finance_login_snapshot", return_value=refreshed_user),
            patch("backend.supabase_patch", return_value={}) as update,
        ):
            current = backend.supabase_current_session("c" * 48)

        self.assertIsNone(current)
        update.assert_called_once()
        self.assertEqual(update.call_args.args[:2], ("auth_sessions", self.session["id"]))
        self.assertTrue(update.call_args.args[2].get("revoked_at"))

    def test_missing_atomic_revalidation_rpc_fails_503_without_user_patch(self) -> None:
        stale_user = {
            **self.user,
            "last_synced_from_logging_at": "2000-01-01 00:00:00",
        }
        refreshed_user = {
            **stale_user,
            backend.FINANCE_LOGIN_EXPECTED_BINDING_KEY: self.expected_binding(),
        }

        def rpc(_method, path, _payload=None):
            if path == "rpc/edoc_resolve_finance_session_v1":
                return {
                    "session": dict(self.session),
                    "user": stale_user,
                    "permissions": [],
                }
            raise RuntimeError(
                "PGRST202 Could not find the function edoc_revalidate_finance_session_v2"
            )

        with (
            patch("backend.supabase_request", side_effect=rpc),
            patch("backend.current_finance_bridge_snapshot", return_value={"schemaVersion": 1}),
            patch("backend.sync_supabase_finance_login_snapshot", return_value=refreshed_user),
            patch("backend.supabase_patch") as update,
        ):
            with self.assertRaisesRegex(
                backend.FinanceBridgeUnavailable,
                "finance_session_revalidation_unavailable",
            ):
                backend.supabase_current_session("d" * 48)

        update.assert_not_called()

    def test_session_creation_uses_one_atomic_rpc(self) -> None:
        def rpc(method, path, payload):
            self.assertEqual(method, "POST")
            self.assertEqual(path, "rpc/edoc_create_finance_login_session_v2")
            self.assertEqual(payload["p_user_id"], self.user["id"])
            self.assertEqual(payload["p_expected_tenant_id"], "tenant-100")
            self.assertEqual(payload["p_expected_role"], "員工")
            self.assertEqual(payload["p_expected_logging_role_key"], "staff")
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
                expected_binding=self.expected_binding(),
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
                    expected_binding=self.expected_binding(),
                )
        insert.assert_not_called()

    def test_missing_v2_rpc_never_falls_back_to_v1_or_sequential_session_writes(self) -> None:
        with (
            patch(
                "backend.supabase_request",
                side_effect=RuntimeError("PGRST202 Could not find the function edoc_create_finance_login_session_v2"),
            ),
            patch("backend.supabase_insert") as insert,
            patch("backend.supabase_patch") as update,
        ):
            with self.assertRaises(RuntimeError):
                backend.supabase_create_finance_login_session(
                    dict(self.user),
                    "127.0.0.1",
                    "contract-test",
                    expected_binding=self.expected_binding(),
                )
        insert.assert_not_called()
        update.assert_not_called()

    def test_rpc_response_rebound_after_final_read_is_rejected(self) -> None:
        rebound = {
            **self.user,
            "role": "執行長",
            "logging_role_key": "ceo",
            "job_level": "執行長",
        }

        def rpc(_method, _path, payload):
            return {
                "session": {
                    "id": payload["p_session_id"],
                    "user_id": self.user["id"],
                    "expires_at": payload["p_expires_at"],
                },
                "user": rebound,
                "permissions": ["system_permissions.manage"],
            }

        with (
            patch("backend.supabase_request", side_effect=rpc),
            patch("backend.supabase_insert") as insert,
        ):
            with self.assertRaisesRegex(
                backend.FinanceBridgeContractError,
                "finance_bridge_legacy_projection_changed",
            ):
                backend.supabase_create_finance_login_session(
                    dict(self.user),
                    "127.0.0.1",
                    "contract-test",
                    expected_binding=self.expected_binding(),
                )
        insert.assert_not_called()

    def test_finance_identity_aliases_resolve_in_one_data_api_request(self) -> None:
        source = {
            "tenant_id": "tenant-100",
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
            "tenant_id": "tenant-100",
            "finance_user_id": self.user["logging_account_id"],
            "email": self.user["email"],
            "entity_id": "E100",
            "role_label": "一般人員",
            "department_code": "D100",
            "department_name": self.user["unit"],
            "job_title": self.user["title"],
            "projection_state": "pending",
            "source_revision": 12,
            "profile": {
                "role": "員工",
                "logging_role_key": "staff",
                "job_level": "職員",
            },
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
        self.assertIn('font-family: "EDoc MOE EduKai", "標楷體"', self.css)
        self.assertIn("#uploadedSealTextInput", self.css)
        editor_rule = self.css[
            self.css.index("#uploadedSealTextInput") : self.css.index(".draft-preview-heading-actions")
        ]
        self.assertNotIn("EDoc MOE EduKai", editor_rule)

    def test_login_fast_path_migration_is_service_role_only(self) -> None:
        sql = (ROOT / "supabase" / "migrations" / "20260824124500_finance_login_fast_path.sql").read_text(encoding="utf-8")
        normalized = " ".join(sql.lower().split())
        self.assertIn("security definer", normalized)
        self.assertIn("set search_path = pg_catalog, public", normalized)
        self.assertIn("revoke all on function public.edoc_create_finance_login_session_v1", normalized)
        self.assertIn("revoke all on function public.edoc_resolve_finance_session_v1", normalized)
        self.assertIn("from public, anon, authenticated", normalized)
        self.assertIn("to service_role", normalized)

    def test_finance_login_v2_migration_atomically_binds_signed_authority(self) -> None:
        sql = (
            ROOT
            / "supabase"
            / "migrations"
            / "20260826120000_finance_login_authorization_binding_v2.sql"
        ).read_text(encoding="utf-8")
        normalized = " ".join(sql.lower().split())

        self.assertIn("function public.edoc_create_finance_login_session_v2", normalized)
        self.assertGreaterEqual(normalized.count("for update"), 2)
        for field in (
            "p_expected_tenant_id",
            "p_expected_company_id",
            "p_expected_entity_id",
            "p_expected_finance_user_id",
            "p_expected_email",
            "p_expected_role",
            "p_expected_logging_role_key",
            "p_expected_job_level",
            "p_expected_unit",
            "p_expected_title",
            "p_expected_status",
            "p_expected_projection_state",
        ):
            self.assertIn(field, normalized)
        self.assertLess(
            normalized.index("finance_login_authorization_binding_mismatch"),
            normalized.index("insert into public.auth_sessions"),
        )
        self.assertIn(
            "revoke all on function public.edoc_create_finance_login_session_v1",
            normalized,
        )
        self.assertIn("from service_role", normalized)
        self.assertIn(
            "revoke all on function public.edoc_create_finance_login_session_v2",
            normalized,
        )
        self.assertIn("from public, anon, authenticated", normalized)
        self.assertIn("to service_role", normalized)
        self.assertIn("function public.edoc_revalidate_finance_session_v2", normalized)
        revalidate_start = normalized.index(
            "create or replace function public.edoc_revalidate_finance_session_v2"
        )
        revalidate_end = normalized.index("alter function", revalidate_start)
        revalidate = normalized[revalidate_start:revalidate_end]
        self.assertLess(
            revalidate.index("from public.auth_sessions"),
            revalidate.index("from public.companies"),
        )
        self.assertLess(
            revalidate.index("from public.companies"),
            revalidate.index("from public.users"),
        )
        self.assertLess(
            revalidate.index("finance_session_authorization_binding_mismatch"),
            revalidate.index("update public.users"),
        )
        self.assertIn("v_session.token_hash is distinct from p_token_hash", revalidate)
        self.assertIn("v_session.revoked_at is not null", revalidate)
        self.assertIn("v_session.expires_at <=", revalidate)
        self.assertIn(
            "revoke all on function public.edoc_revalidate_finance_session_v2",
            normalized,
        )
        self.assertNotIn("commit;", normalized)
        self.assertIn("notify pgrst, 'reload schema'", normalized)


if __name__ == "__main__":
    unittest.main()
