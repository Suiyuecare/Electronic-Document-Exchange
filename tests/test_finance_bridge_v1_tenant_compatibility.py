from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import backend
import finance_bridge


TENANT_ID = "tenant-existing-001"
FINANCE_USER_ID = "finance-user-existing-001"
EMAIL = "existing-member@example.invalid"
ENTITY_ID = "E100"
COMPANY_ID = "FINCO-EXISTING-001"
ACTOR_TENANT_ID = "tenant-other-002"
ACTOR_FINANCE_USER_ID = "finance-manager-existing-002"
ACTOR_EMAIL = "existing-manager@example.invalid"
ACTOR_ENTITY_ID = "E200"
ACTOR_COMPANY_ID = "FINCO-EXISTING-002"


def production_v1_snapshot() -> dict:
    """Mirror the live pinned v1 identity response, which has no tenantId."""
    return {
        "ok": True,
        "source": "finance",
        "schemaVersion": 1,
        "snapshotAt": "2026-08-25T17:00:00Z",
        "identity": {
            "financeUserId": FINANCE_USER_ID,
            "name": "去識別化既有人員",
            "email": EMAIL,
            "role": "staff",
            "roleLabel": "一般人員",
            "entityId": ENTITY_ID,
            "departmentCode": "D100",
            "orgStatus": "active",
            "sourceUpdatedAt": "2026-08-25T16:59:00Z",
            "active": True,
            "authUserBound": True,
            "googleLoginVerified": True,
        },
        "company": {
            "entityId": ENTITY_ID,
            "name": "去識別化既有公司",
            "taxId": "",
            "address": "",
        },
        "actors": {
            "applicantManager": None,
            "departmentHead": None,
            "ceo": None,
            "adminDirector": None,
            "generalAffairs": None,
        },
        "workflowReady": False,
        "issues": [],
    }


def projected_user(*, row_id: str = "FIN-EXISTING-001", tenant_id: str = TENANT_ID) -> dict:
    return {
        "id": row_id,
        "email": EMAIL,
        "account_source": "finance",
        "logging_account_id": FINANCE_USER_ID,
        "finance_employee_id": FINANCE_USER_ID,
        "company_id": COMPANY_ID,
        "finance_tenant_id": tenant_id,
        "status": "啟用",
        "role": "員工",
        "logging_role_key": "staff",
        "job_level": "職員",
        "unit": "D100",
        "title": "一般人員",
        "finance_source_status": "active",
    }


def projected_company(*, tenant_id: str = TENANT_ID) -> dict:
    return {
        "id": COMPANY_ID,
        "finance_entity_id": ENTITY_ID,
        "finance_tenant_id": tenant_id,
        "source_system": "finance",
        "status": "active",
    }


def production_v1_actor(*, tenant_id: str = "") -> dict:
    actor = {
        "financeUserId": ACTOR_FINANCE_USER_ID,
        "name": "去識別化既有主管",
        "email": ACTOR_EMAIL,
        "role": "section_chief",
        "roleLabel": "課長",
        "entityId": ACTOR_ENTITY_ID,
        "departmentCode": "D200",
        "orgStatus": "active",
        "sourceUpdatedAt": "2026-08-25T16:59:00Z",
        "active": True,
        "authUserBound": True,
        "googleLoginVerified": True,
    }
    if tenant_id:
        actor["tenantId"] = tenant_id
    return actor


def projected_actor_user(*, tenant_id: str = ACTOR_TENANT_ID) -> dict:
    return {
        "id": "FIN-EXISTING-002",
        "email": ACTOR_EMAIL,
        "account_source": "finance",
        "logging_account_id": ACTOR_FINANCE_USER_ID,
        "finance_employee_id": ACTOR_FINANCE_USER_ID,
        "company_id": ACTOR_COMPANY_ID,
        "finance_tenant_id": tenant_id,
        "status": "啟用",
        "role": "主管",
    }


def projected_actor_company(*, tenant_id: str = ACTOR_TENANT_ID) -> dict:
    return {
        "id": ACTOR_COMPANY_ID,
        "finance_entity_id": ACTOR_ENTITY_ID,
        "finance_tenant_id": tenant_id,
        "source_system": "finance",
        "status": "active",
    }


class FinanceBridgeV1TenantCompatibilityTest(unittest.TestCase):
    def recover(self, snapshot: dict, *, users=None, companies=None) -> dict:
        with (
            patch("backend.supabase_request", return_value=list(users if users is not None else [projected_user()])),
            patch(
                "backend.supabase_filter_rows",
                return_value=list(companies if companies is not None else [projected_company()]),
            ),
            patch("backend.supabase_insert") as insert,
        ):
            hydrated = backend.supabase_recover_legacy_finance_snapshot_tenant_scope(snapshot)
        insert.assert_not_called()
        return hydrated

    def test_live_v1_shape_is_accepted_only_after_exact_existing_projection_recovery(self) -> None:
        snapshot = production_v1_snapshot()

        # The pinned transport validator accepts the current live v1 shape.
        finance_bridge.validate_finance_bridge_snapshot(snapshot, EMAIL)
        with self.assertRaisesRegex(
            backend.FinanceBridgeContractError,
            "finance_bridge_identity_invalid",
        ):
            backend.normalize_finance_bridge_snapshot(snapshot)

        hydrated = self.recover(snapshot)
        normalized = backend.normalize_finance_bridge_snapshot(hydrated)

        self.assertEqual(hydrated["identity"]["tenantId"], TENANT_ID)
        self.assertEqual(hydrated["company"]["tenantId"], TENANT_ID)
        self.assertEqual(normalized["applicant"]["tenant_id"], TENANT_ID)
        self.assertNotIn("tenantId", snapshot["identity"], "authenticated upstream snapshot must stay immutable")
        self.assertNotIn("tenantId", snapshot["company"])

    def test_v1_never_guesses_a_global_or_company_tenant_without_exact_user_match(self) -> None:
        with (
            patch("backend.supabase_request", return_value=[]),
            patch("backend.supabase_filter_rows", return_value=[projected_company()]),
            patch("backend.supabase_insert") as insert,
        ):
            with self.assertRaisesRegex(
                backend.FinanceBridgeContractError,
                "finance_bridge_legacy_tenant_projection_invalid",
            ):
                backend.supabase_recover_legacy_finance_snapshot_tenant_scope(
                    production_v1_snapshot()
                )
        insert.assert_not_called()

    def test_v1_rejects_ambiguous_identity_projection(self) -> None:
        users = [projected_user(row_id="FIN-1"), projected_user(row_id="FIN-2")]
        with self.assertRaisesRegex(
            backend.FinanceBridgeContractError,
            "finance_bridge_legacy_tenant_projection_invalid",
        ):
            self.recover(production_v1_snapshot(), users=users)

    def test_v1_rejects_user_company_tenant_or_binding_mismatch(self) -> None:
        mismatch_cases = (
            ([projected_user(tenant_id="tenant-one")], [projected_company(tenant_id="tenant-two")]),
            ([{**projected_user(), "company_id": "FINCO-OTHER"}], [projected_company()]),
        )
        for users, companies in mismatch_cases:
            with self.subTest(users=users, companies=companies):
                with self.assertRaisesRegex(
                    backend.FinanceBridgeContractError,
                    "finance_bridge_legacy_tenant_projection_invalid",
                ):
                    self.recover(production_v1_snapshot(), users=users, companies=companies)

    def test_v1_rejects_missing_actor_tenant_recovered_into_another_tenant(self) -> None:
        snapshot = production_v1_snapshot()
        snapshot["actors"]["applicantManager"] = production_v1_actor()
        with (
            patch(
                "backend.supabase_request",
                side_effect=[[projected_user()], [projected_actor_user()]],
            ),
            patch(
                "backend.supabase_filter_rows",
                side_effect=[[projected_company()], [projected_actor_company()]],
            ),
            patch("backend.supabase_insert") as insert,
        ):
            with self.assertRaisesRegex(
                backend.FinanceBridgeContractError,
                "finance_bridge_legacy_tenant_projection_invalid",
            ):
                backend.supabase_recover_legacy_finance_snapshot_tenant_scope(snapshot)
        insert.assert_not_called()

    def test_explicit_actor_tenant_mismatch_fails_both_security_layers(self) -> None:
        snapshot = production_v1_snapshot()
        snapshot["identity"]["tenantId"] = TENANT_ID
        snapshot["company"]["tenantId"] = TENANT_ID
        snapshot["actors"]["applicantManager"] = production_v1_actor(
            tenant_id=ACTOR_TENANT_ID
        )

        with self.assertRaisesRegex(
            backend.FinanceBridgeContractError,
            "finance_bridge_legacy_tenant_projection_invalid",
        ):
            backend.supabase_recover_legacy_finance_snapshot_tenant_scope(snapshot)
        with self.assertRaisesRegex(
            backend.FinanceBridgeContractError,
            "finance_bridge_actor_tenant_mismatch",
        ):
            backend.normalize_finance_bridge_snapshot(snapshot)

    def test_v2_missing_tenant_remains_strict_and_never_uses_v1_recovery(self) -> None:
        snapshot = production_v1_snapshot()
        snapshot["schemaVersion"] = 2
        with (
            patch("backend.supabase_request") as request,
            patch("backend.supabase_filter_rows") as filter_rows,
        ):
            unchanged = backend.supabase_recover_legacy_finance_snapshot_tenant_scope(snapshot)

        self.assertIs(unchanged, snapshot)
        request.assert_not_called()
        filter_rows.assert_not_called()
        with self.assertRaisesRegex(
            backend.FinanceBridgeContractError,
            "finance_bridge_identity_invalid",
        ):
            backend.normalize_finance_bridge_snapshot(unchanged)

    def test_v1_login_uses_existing_projection_without_any_jit_insert(self) -> None:
        snapshot = production_v1_snapshot()
        user = projected_user()
        company = projected_company()

        def get_row(table: str, row_id: str) -> dict | None:
            if table == "users" and row_id == user["id"]:
                return dict(user)
            if table == "companies" and row_id == company["id"]:
                return dict(company)
            return None

        with (
            patch("backend.supabase_request", side_effect=[[user], [user]]),
            patch("backend.supabase_filter_rows", return_value=[company]),
            patch("backend.supabase_get", side_effect=get_row),
            patch("backend.launch_company_in_scope", return_value=True),
            patch("backend.is_production", return_value=False),
            patch("backend.supabase_insert") as insert,
            patch("backend.supabase_upsert_finance_company_snapshot") as company_upsert,
            patch("backend._supabase_upsert_finance_snapshot_user") as user_upsert,
            patch("backend.supabase_upsert_finance_module_link") as link_upsert,
        ):
            logged_in = backend.sync_supabase_finance_login_snapshot(
                snapshot,
                portal_authenticated=True,
            )

        self.assertEqual(logged_in["id"], user["id"])
        insert.assert_not_called()
        company_upsert.assert_not_called()
        user_upsert.assert_not_called()
        link_upsert.assert_not_called()

    def test_v1_login_rejects_stored_high_role_not_authorized_by_signed_snapshot(self) -> None:
        stale_high_role = {
            **projected_user(),
            "role": "執行長",
            "logging_role_key": "ceo",
            "job_level": "執行長",
        }
        with (
            patch(
                "backend.supabase_request",
                side_effect=[[stale_high_role], [stale_high_role]],
            ),
            patch("backend.supabase_filter_rows", return_value=[projected_company()]),
            patch("backend.supabase_insert") as insert,
            patch("backend._supabase_upsert_finance_snapshot_user") as user_upsert,
        ):
            with self.assertRaisesRegex(
                backend.FinanceBridgeContractError,
                "finance_bridge_legacy_projection_changed",
            ):
                backend.sync_supabase_finance_login_snapshot(
                    production_v1_snapshot(),
                    portal_authenticated=True,
                )
        insert.assert_not_called()
        user_upsert.assert_not_called()

    def test_v1_login_ignores_optional_actor_missing_tenant_projection(self) -> None:
        snapshot = production_v1_snapshot()
        snapshot["actors"]["applicantManager"] = production_v1_actor()
        user = projected_user()
        company = projected_company()

        def get_row(table: str, row_id: str) -> dict | None:
            if table == "users" and row_id == user["id"]:
                return dict(user)
            if table == "companies" and row_id == company["id"]:
                return dict(company)
            return None

        with (
            patch("backend.supabase_request", side_effect=[[user], [user]]) as request,
            patch("backend.supabase_filter_rows", return_value=[company]) as filter_rows,
            patch("backend.supabase_get", side_effect=get_row),
            patch("backend.launch_company_in_scope", return_value=True),
            patch("backend.is_production", return_value=False),
            patch("backend.supabase_insert") as insert,
        ):
            logged_in = backend.sync_supabase_finance_login_snapshot(
                snapshot,
                portal_authenticated=True,
            )

        self.assertEqual(logged_in["id"], user["id"])
        self.assertEqual(request.call_count, 2, "optional actor must not trigger a login projection lookup")
        filter_rows.assert_called_once()
        insert.assert_not_called()

    def test_v1_login_accepts_existing_same_tenant_manager_without_syncing_it(self) -> None:
        snapshot = production_v1_snapshot()
        snapshot["actors"]["applicantManager"] = production_v1_actor()
        user = projected_user()
        company = projected_company()

        def get_row(table: str, row_id: str) -> dict | None:
            if table == "users" and row_id == user["id"]:
                return dict(user)
            if table == "companies" and row_id == company["id"]:
                return dict(company)
            return None

        with (
            patch(
                "backend.supabase_request",
                side_effect=[[user], [user]],
            ) as request,
            patch("backend.supabase_filter_rows", return_value=[company]) as filter_rows,
            patch("backend.supabase_get", side_effect=get_row),
            patch("backend.launch_company_in_scope", return_value=True),
            patch("backend.is_production", return_value=False),
            patch("backend.supabase_insert") as insert,
            patch("backend.supabase_upsert_finance_company_snapshot") as company_upsert,
            patch("backend._supabase_upsert_finance_snapshot_user") as user_upsert,
            patch("backend.supabase_upsert_finance_module_link") as link_upsert,
        ):
            logged_in = backend.sync_supabase_finance_login_snapshot(
                snapshot,
                portal_authenticated=True,
            )

        self.assertEqual(logged_in["id"], user["id"])
        self.assertEqual(request.call_count, 2)
        filter_rows.assert_called_once()
        insert.assert_not_called()
        company_upsert.assert_not_called()
        user_upsert.assert_not_called()
        link_upsert.assert_not_called()

    def test_v1_login_fails_closed_if_projection_disappears_or_is_rebound(self) -> None:
        race_candidates = (
            [],
            [{**projected_user(), "company_id": "FINCO-RACE-OTHER"}],
        )
        for candidate_rows in race_candidates:
            with self.subTest(candidate_rows=candidate_rows):
                with (
                    patch(
                        "backend.supabase_request",
                        side_effect=[[projected_user()], candidate_rows],
                    ),
                    patch("backend.supabase_filter_rows", return_value=[projected_company()]),
                    patch("backend.launch_company_in_scope", return_value=True),
                    patch("backend.is_production", return_value=False),
                    patch("backend.supabase_insert") as insert,
                    patch("backend.supabase_upsert_finance_company_snapshot") as company_upsert,
                    patch("backend._supabase_upsert_finance_snapshot_user") as user_upsert,
                ):
                    with self.assertRaisesRegex(
                        backend.FinanceBridgeContractError,
                        "finance_bridge_legacy_projection_changed",
                    ):
                        backend.sync_supabase_finance_login_snapshot(
                            production_v1_snapshot(),
                            portal_authenticated=True,
                        )
                insert.assert_not_called()
                company_upsert.assert_not_called()
                user_upsert.assert_not_called()


class FinanceSessionTransientFailureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_environment = backend.DEPLOYMENT_ENV
        self.previous_ttl = backend.EDOC_FINANCE_SESSION_REVALIDATE_SECONDS
        backend.DEPLOYMENT_ENV = "production"
        backend.EDOC_FINANCE_SESSION_REVALIDATE_SECONDS = 60
        self.user = {
            "id": "FIN-EXISTING-001",
            "name": "去識別化既有人員",
            "email": EMAIL,
            "status": "啟用",
            "role": "員工",
            "account_source": "finance",
            "logging_account_id": FINANCE_USER_ID,
            "finance_employee_id": FINANCE_USER_ID,
            "company_id": COMPANY_ID,
            "last_synced_from_logging_at": "2000-01-01 00:00:00",
        }
        self.session = {
            "id": "SESSION-EXISTING-001",
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

    def test_transient_revalidation_failure_raises_503_signal_without_revoking_session(self) -> None:
        with (
            patch("backend.supabase_request", return_value=dict(self.bundle)),
            patch(
                "backend.current_finance_bridge_snapshot",
                side_effect=backend.FinanceBridgeUnavailable("finance_bridge_unavailable"),
            ),
            patch("backend.supabase_patch") as update,
        ):
            with self.assertRaisesRegex(
                backend.FinanceBridgeUnavailable,
                "finance_session_revalidation_unavailable",
            ):
                backend.supabase_current_session("a" * 48)

        update.assert_not_called()

    def test_definitive_finance_denial_still_revokes_session(self) -> None:
        with (
            patch("backend.supabase_request", return_value=dict(self.bundle)),
            patch(
                "backend.current_finance_bridge_snapshot",
                side_effect=backend.FinanceBridgeDenied("finance_identity_denied"),
            ),
            patch("backend.supabase_patch", return_value={}) as update,
        ):
            current = backend.supabase_current_session("b" * 48)

        self.assertIsNone(current)
        self.assertEqual(update.call_args.args[:2], ("auth_sessions", self.session["id"]))
        self.assertTrue(update.call_args.args[2].get("revoked_at"))

    def test_handoff_exchange_preserves_http_only_cookie_on_retryable_503(self) -> None:
        handler = object.__new__(backend.Handler)
        handler.headers = {
            "X-EDOC-Handoff-Exchange": "1",
            "Sec-Fetch-Site": "same-origin",
        }
        token = "c" * 48
        handler.cookie_value = Mock(return_value=token)
        handler.send_json = Mock()
        handler.log_handoff_failure = Mock()

        with (
            patch.object(backend, "USE_SUPABASE", True),
            patch(
                "backend.supabase_current_session",
                side_effect=backend.FinanceBridgeUnavailable(
                    "finance_session_revalidation_unavailable"
                ),
            ),
        ):
            handler.handle_handoff_session_exchange()

        payload, status, headers = handler.send_json.call_args.args
        self.assertEqual(status, 503)
        self.assertTrue(payload["retryable"])
        self.assertFalse(
            any(name.lower() == "set-cookie" for name, _value in headers),
            "transient 503 must retain the short-lived HttpOnly handoff cookie",
        )
        handler.log_handoff_failure.assert_called_once_with(
            "handoff_session_unavailable",
            503,
        )

    def test_handoff_exchange_clears_cookie_for_permanent_session_errors(self) -> None:
        cases = (
            (backend.FinanceBridgeContractError("finance_bridge_contract_invalid"), 503),
            (backend.FinanceBridgeDenied("finance_identity_denied"), 401),
            (RuntimeError("permanent_integrity_failure"), 503),
        )
        for error, expected_status in cases:
            with self.subTest(error=type(error).__name__):
                handler = object.__new__(backend.Handler)
                handler.headers = {
                    "X-EDOC-Handoff-Exchange": "1",
                    "Sec-Fetch-Site": "same-origin",
                }
                handler.cookie_value = Mock(return_value="d" * 48)
                handler.send_json = Mock()
                handler.log_handoff_failure = Mock()

                with (
                    patch.object(backend, "USE_SUPABASE", True),
                    patch("backend.supabase_current_session", side_effect=error),
                ):
                    handler.handle_handoff_session_exchange()

                payload, status, headers = handler.send_json.call_args.args
                self.assertEqual(status, expected_status)
                self.assertFalse(payload["retryable"])
                self.assertTrue(
                    any(name.lower() == "set-cookie" for name, _value in headers),
                    "permanent failures must clear the handoff cookie",
                )
                handler.log_handoff_failure.assert_called_once_with(
                    "handoff_session_invalid",
                    expected_status,
                )

    def test_handoff_exchange_only_retries_explicit_sqlite_lock_errors(self) -> None:
        self.assertTrue(
            backend.Handler.handoff_session_error_retryable(
                backend.FinanceBridgeUnavailable("finance_bridge_unavailable")
            )
        )
        self.assertTrue(
            backend.Handler.handoff_session_error_retryable(
                backend.sqlite3.OperationalError("database is locked")
            )
        )
        self.assertFalse(
            backend.Handler.handoff_session_error_retryable(
                backend.sqlite3.OperationalError("malformed database schema")
            )
        )


if __name__ == "__main__":
    unittest.main()
