from __future__ import annotations

import json
import io
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import backend
import finance_bridge


TEST_SECRET = "finance-member-sync-unit-test-secret-32-bytes"


def member_event(*, revision: int = 7, active: bool = True, auth_ready: bool = True, role: str = "staff") -> dict:
    return {
        "source": "finance",
        "schemaVersion": 1,
        "eventId": f"fin-member-u-100-r{revision}",
        "eventType": "member.changed",
        "sourceRevision": revision,
        "occurredAt": "2026-08-22T10:00:00+08:00",
        "identity": {
            "tenantId": "tenant-1",
            "financeUserId": "u-100",
            "memberRevision": revision,
            "name": "去識別化測試人員",
            "email": "member-100@example.invalid",
            "role": role,
            "roleLabel": "一般人員",
            "entityId": "E100",
            "departmentCode": "D100",
            "departmentName": "業務部",
            "unitName": "業務部",
            "jobTitle": "業務專員",
            "extension": "123",
            "contactEmail": "contact-100@example.invalid",
            "orgStatus": "active" if active else "inactive",
            "sourceUpdatedAt": "2026-08-22T09:59:00+08:00",
            "active": active,
            "sourceActive": active,
            "authUserBound": auth_ready,
            "googleLoginVerified": auth_ready,
            "authUserId": "00000000-0000-0000-0000-000000000100" if auth_ready else None,
        },
        "company": {
            "tenantId": "tenant-1",
            "entityId": "E100",
            "name": "去識別化測試公司",
            "taxId": "00000000",
            "address": "去識別化測試地址",
            "active": True,
            "sourceUpdatedAt": "2026-08-22T09:58:00+08:00",
        },
        "actors": {},
        "workflowReady": auth_ready,
        "issues": [] if auth_ready else ["identity_google_login_not_verified"],
    }


def signed_request(payload: dict, *, timestamp: int | None = None, nonce: str = "abcdefghijklmnopqrstuvwx") -> tuple[bytes, dict]:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    wire_timestamp = str(timestamp if timestamp is not None else int(time.time()))
    return raw, {
        "x-finance-timestamp": wire_timestamp,
        "x-finance-nonce": nonce,
        "x-finance-signature": finance_bridge.finance_member_sync_signature(
            TEST_SECRET, wire_timestamp, nonce, raw
        ),
    }


class FinanceMemberSyncContractTestCase(unittest.TestCase):
    def test_valid_hmac_event_preserves_exact_hash_and_profile_fields(self) -> None:
        payload = member_event()
        raw, headers = signed_request(payload, timestamp=1_787_300_000)

        verified = finance_bridge.verify_finance_member_sync_request(
            raw, headers, TEST_SECRET, now_timestamp=1_787_300_030
        )
        snapshot = finance_bridge.finance_member_event_snapshot(verified["payload"])
        normalized = backend.normalize_finance_bridge_snapshot(snapshot)

        self.assertEqual(verified["payload"]["eventId"], payload["eventId"])
        self.assertEqual(len(verified["payloadSha256"]), 64)
        self.assertEqual(normalized["applicant"]["department_name"], "業務部")
        self.assertEqual(normalized["applicant"]["job_title"], "業務專員")
        self.assertEqual(normalized["applicant"]["profile"]["role"], "員工")
        self.assertEqual(normalized["applicant"]["source_revision"], 7)

    def test_tamper_expiry_and_millisecond_timestamp_are_rejected(self) -> None:
        payload = member_event()
        raw, headers = signed_request(payload, timestamp=1_787_300_000)
        with self.assertRaises(finance_bridge.FinanceMemberSyncAuthError):
            finance_bridge.verify_finance_member_sync_request(
                raw + b" ", headers, TEST_SECRET, now_timestamp=1_787_300_010
            )
        with self.assertRaisesRegex(finance_bridge.FinanceMemberSyncAuthError, "expired"):
            finance_bridge.verify_finance_member_sync_request(
                raw, headers, TEST_SECRET, now_timestamp=1_787_300_061
            )

        millisecond_headers = dict(headers)
        millisecond_headers["x-finance-timestamp"] = "1787300000000"
        millisecond_headers["x-finance-signature"] = finance_bridge.finance_member_sync_signature(
            TEST_SECRET, millisecond_headers["x-finance-timestamp"], millisecond_headers["x-finance-nonce"], raw
        )
        with self.assertRaises(finance_bridge.FinanceMemberSyncAuthError):
            finance_bridge.verify_finance_member_sync_request(
                raw, millisecond_headers, TEST_SECRET, now_timestamp=1_787_300_000
            )

    def test_revision_mismatch_and_unknown_fields_are_rejected(self) -> None:
        payload = member_event(revision=8)
        payload["identity"]["memberRevision"] = 7
        raw, headers = signed_request(payload, timestamp=1_787_300_000)
        with self.assertRaisesRegex(finance_bridge.FinanceMemberSyncContractError, "revision_mismatch"):
            finance_bridge.verify_finance_member_sync_request(
                raw, headers, TEST_SECRET, now_timestamp=1_787_300_000
            )

    def test_source_active_is_redundant_employment_state_not_login_readiness(self) -> None:
        pending = member_event(active=True, auth_ready=False)
        raw, headers = signed_request(pending, timestamp=1_787_300_000)
        verified = finance_bridge.verify_finance_member_sync_request(
            raw, headers, TEST_SECRET, now_timestamp=1_787_300_000
        )
        self.assertTrue(verified["payload"]["identity"]["active"])
        self.assertFalse(verified["payload"]["identity"]["authUserBound"])

        mismatched = member_event(active=True, auth_ready=False)
        mismatched["identity"]["sourceActive"] = False
        raw, headers = signed_request(mismatched, timestamp=1_787_300_000)
        with self.assertRaisesRegex(
            finance_bridge.FinanceMemberSyncContractError,
            "active_mismatch",
        ):
            finance_bridge.verify_finance_member_sync_request(
                raw, headers, TEST_SECRET, now_timestamp=1_787_300_000
            )

    def test_cross_tenant_member_event_is_rejected(self) -> None:
        payload = member_event()
        payload["company"]["tenantId"] = "tenant-2"
        raw, headers = signed_request(payload, timestamp=1_787_300_000)
        with self.assertRaisesRegex(finance_bridge.FinanceMemberSyncContractError, "tenant_mismatch"):
            finance_bridge.verify_finance_member_sync_request(
                raw, headers, TEST_SECRET, now_timestamp=1_787_300_000
            )

    def test_member_with_missing_canonical_company_is_accepted_only_with_issue(self) -> None:
        payload = member_event(auth_ready=False)
        payload["company"] = {
            "tenantId": payload["company"]["tenantId"],
            "entityId": payload["company"]["entityId"],
        }
        payload["issues"].append("company_missing")
        raw, headers = signed_request(payload, timestamp=1_787_300_000)
        verified = finance_bridge.verify_finance_member_sync_request(
            raw, headers, TEST_SECRET, now_timestamp=1_787_300_000
        )
        self.assertEqual(verified["payload"]["company"]["entityId"], "E100")

        payload["issues"].remove("company_missing")
        raw, headers = signed_request(payload, timestamp=1_787_300_000)
        with self.assertRaises(finance_bridge.FinanceMemberSyncContractError):
            finance_bridge.verify_finance_member_sync_request(
                raw, headers, TEST_SECRET, now_timestamp=1_787_300_000
            )

    def test_company_changed_contract_is_authenticated(self) -> None:
        payload = {
            "source": "finance",
            "schemaVersion": 1,
            "eventId": "fin-company-E100-r12",
            "eventType": "company.changed",
            "sourceRevision": 12,
            "occurredAt": "2026-08-22T10:00:00+08:00",
            "company": {
                "tenantId": "tenant-1",
                "entityId": "E100",
                "name": "去識別化測試公司",
                "taxId": "00000000",
                "address": "新地址",
                "active": True,
                "sourceUpdatedAt": "2026-08-22T09:59:00+08:00",
            },
        }
        raw, headers = signed_request(payload, timestamp=1_787_300_000)
        verified = finance_bridge.verify_finance_member_sync_request(
            raw, headers, TEST_SECRET, now_timestamp=1_787_300_000
        )
        self.assertEqual(verified["payload"]["eventType"], "company.changed")

        response = backend.finance_member_sync_success_response(
            payload,
            {"status": "applied", "companyId": "FINCO-E100"},
        )
        self.assertEqual(response["status"], "applied")
        self.assertTrue(response["applied"])
        self.assertFalse(response["stale"])
        self.assertFalse(response["replayed"])

        payload = member_event()
        payload["identity"]["administrator"] = True
        raw, headers = signed_request(payload, timestamp=1_787_300_000)
        with self.assertRaises(finance_bridge.FinanceMemberSyncContractError):
            finance_bridge.verify_finance_member_sync_request(
                raw, headers, TEST_SECRET, now_timestamp=1_787_300_000
            )

    def test_success_response_enum_and_compatibility_boolean_match(self) -> None:
        payload = member_event(revision=9)
        for disposition in ("applied", "stale"):
            response = backend.finance_member_sync_success_response(
                payload,
                {"status": disposition, "userId": "FIN-U100"},
            )
            self.assertEqual(response["status"], disposition)
            self.assertEqual(
                [key for key in ("applied", "stale", "replayed") if response[key]],
                [disposition],
            )

        replayed = backend.finance_member_sync_success_response(
            payload,
            {"originalStatus": "applied"},
            status="replayed",
        )
        self.assertEqual(replayed["status"], "replayed")
        self.assertTrue(replayed["replayed"])
        self.assertFalse(replayed["applied"])


class FinanceProjectionTestCase(unittest.TestCase):
    def normalized_source(self, *, auth_ready: bool = False) -> dict:
        payload = member_event(auth_ready=auth_ready)
        return backend.normalize_finance_bridge_snapshot(
            finance_bridge.finance_member_event_snapshot(payload)
        )["applicant"]

    def test_pending_member_uses_revision_cas_without_text_based_privilege(self) -> None:
        source = self.normalized_source(auth_ready=False)
        source["job_title"] = "執行長"
        existing = {
            "id": "FIN-U100",
            "account_source": "finance",
            "logging_account_id": "u-100",
            "finance_employee_id": "u-100",
            "email": "member-100@example.invalid",
            "auth_user_id": None,
            "finance_source_revision": 6,
        }
        company = {"id": "FINCO-E100", "name": "去識別化測試公司", "address": "去識別化測試地址"}

        def cas_response(method: str, path: str, body: dict, prefer: str = "return=representation") -> list[dict]:
            self.assertEqual(method, "PATCH")
            self.assertIn("finance_source_revision=eq.6", path)
            self.assertEqual(body["status"], "待啟用")
            self.assertEqual(body["finance_source_status"], "pending")
            self.assertEqual(body["role"], "員工")
            self.assertEqual(body["title"], "執行長")
            return [{**existing, **body}]

        with patch.object(backend, "supabase_request", side_effect=cas_response):
            user, disposition = backend._supabase_upsert_finance_snapshot_user(
                source,
                company,
                {"source": "finance_bridge"},
                existing=existing,
                source_revision=7,
                event_id="fin-member-u-100-r7",
            )

        self.assertEqual(disposition, "applied")
        self.assertEqual(user["role"], "員工")
        profile = json.loads(user["external_account_payload_json"])["financeProfile"]
        self.assertEqual(profile["extension"], "123")

    def test_stale_member_does_not_write(self) -> None:
        source = self.normalized_source(auth_ready=True)
        existing = {
            "id": "FIN-U100", "email": source["email"], "auth_user_id": source["auth_user_id"],
            "finance_source_revision": 9,
        }
        with patch.object(backend, "supabase_request") as request:
            user, disposition = backend._supabase_upsert_finance_snapshot_user(
                source,
                {"id": "FINCO-E100", "name": "公司", "address": ""},
                {},
                existing=existing,
                source_revision=7,
                event_id="fin-member-u-100-r7",
            )
        self.assertEqual(user, existing)
        self.assertEqual(disposition, "stale")
        request.assert_not_called()

    def test_active_ready_supported_member_is_enabled(self) -> None:
        source = self.normalized_source(auth_ready=True)
        existing = {
            "id": "FIN-U100", "email": source["email"], "auth_user_id": source["auth_user_id"],
            "finance_source_revision": 6,
        }

        def cas_response(method: str, path: str, body: dict, prefer: str = "return=representation") -> list[dict]:
            self.assertEqual(body["status"], "啟用")
            self.assertEqual(body["finance_source_status"], "active")
            self.assertEqual(body["role"], "員工")
            return [{**existing, **body}]

        with patch.object(backend, "supabase_request", side_effect=cas_response):
            user, disposition = backend._supabase_upsert_finance_snapshot_user(
                source,
                {"id": "FINCO-E100", "name": "公司", "address": ""},
                {},
                existing=existing,
                source_revision=7,
                event_id="fin-member-u-100-r7",
            )
        self.assertEqual(disposition, "applied")
        self.assertEqual(user["status"], "啟用")

    def test_finance_auth_uuid_is_not_written_to_edoc_auth_foreign_key(self) -> None:
        source = self.normalized_source(auth_ready=True)
        finance_auth_user_id = source["auth_user_id"]
        existing = {
            "id": "FIN-U100",
            "email": source["email"],
            "auth_user_id": None,
            "finance_source_revision": 6,
        }

        def cas_response(method: str, path: str, body: dict, prefer: str = "return=representation") -> list[dict]:
            self.assertEqual(method, "PATCH")
            self.assertNotIn("auth_user_id", body)
            return [{**existing, **body}]

        with patch.object(backend, "supabase_request", side_effect=cas_response):
            user, disposition = backend._supabase_upsert_finance_snapshot_user(
                source,
                {"id": "FINCO-E100", "name": "公司", "address": ""},
                {},
                existing=existing,
                auth_user_id=finance_auth_user_id,
                source_revision=7,
                event_id="fin-member-u-100-r7",
            )

        self.assertEqual(disposition, "applied")
        self.assertIsNone(user["auth_user_id"])

    def test_candidate_never_selects_by_cross_project_auth_uuid(self) -> None:
        source = self.normalized_source(auth_ready=True)
        requests_seen: list[tuple[str, str]] = []

        def capture_request(method: str, path: str, *_args: object, **_kwargs: object) -> list[dict]:
            requests_seen.append((method, path))
            return []

        with patch.object(backend, "supabase_request", side_effect=capture_request):
            candidate = backend._supabase_finance_snapshot_user_candidate(
                source,
                source["auth_user_id"],
            )

        self.assertIsNone(candidate)
        self.assertEqual(len(requests_seen), 1)
        self.assertEqual(requests_seen[0][0], "GET")
        self.assertNotIn("auth_user_id", requests_seen[0][1])

    def test_actor_own_revision_prevents_older_applicant_event_overwrite(self) -> None:
        actor = {
            "tenantId": "tenant-1",
            "financeUserId": "manager-1",
            "memberRevision": 4,
            "name": "去識別化主管",
            "email": "manager-1@example.invalid",
            "role": "section_chief",
            "roleLabel": "課長",
            "entityId": "E100",
            "departmentCode": "D100",
            "departmentName": "業務部",
            "jobTitle": "業務課長",
            "extension": "456",
            "contactEmail": "manager-contact@example.invalid",
            "orgStatus": "active",
            "sourceUpdatedAt": "2026-08-22T09:59:00+08:00",
            "active": True,
            "authUserBound": True,
            "googleLoginVerified": True,
        }
        payload = member_event(revision=5)
        payload["actors"] = {"applicantManager": actor}
        raw, headers = signed_request(payload, timestamp=1_787_300_000)
        verified = finance_bridge.verify_finance_member_sync_request(
            raw, headers, TEST_SECRET, now_timestamp=1_787_300_000
        )
        normalized_actor = backend.normalize_finance_bridge_snapshot(
            finance_bridge.finance_member_event_snapshot(verified["payload"])
        )["actors"]["applicantManager"]
        self.assertEqual(normalized_actor["source_revision"], 4)

        existing = {
            "id": "FIN-MANAGER-1", "email": normalized_actor["email"],
            "auth_user_id": None, "finance_source_revision": 7,
        }
        with patch.object(backend, "supabase_request") as request:
            user, disposition = backend._supabase_upsert_finance_snapshot_user(
                normalized_actor,
                {"id": "FINCO-E100", "name": "公司", "address": ""},
                {},
                existing=existing,
                source_revision=normalized_actor["source_revision"],
                event_id=payload["eventId"],
            )
        self.assertEqual(user, existing)
        self.assertEqual(disposition, "stale")
        request.assert_not_called()

    def test_inactive_system_account_is_disabled_and_sessions_revoked(self) -> None:
        # system_account is always disabled even if a malformed/upstream event
        # reports the account as employment-active and Google-ready.
        payload = member_event(revision=11, active=True, auth_ready=True, role="system_account")
        existing = {
            "id": "FIN-SYSTEM", "account_source": "finance", "logging_account_id": "u-100",
            "finance_employee_id": "u-100", "email": "member-100@example.invalid",
            "finance_source_revision": 10, "role": "員工", "title": "系統帳號",
        }
        company = {"id": "FINCO-E100", "name": "去識別化測試公司", "address": ""}

        def cas_response(method: str, path: str, body: dict, prefer: str = "return=representation") -> list[dict]:
            self.assertEqual(body["status"], "停用")
            self.assertEqual(body["finance_source_revision"], 11)
            return [{**existing, **body}]

        with (
            patch.object(backend, "_supabase_finance_snapshot_user_candidate", side_effect=[existing, existing]),
            patch.object(backend, "supabase_upsert_finance_company_snapshot", return_value=(company, "applied")),
            patch.object(backend, "supabase_request", side_effect=cas_response),
            patch.object(backend, "supabase_upsert_finance_module_link", return_value={}) as link,
            patch.object(backend, "supabase_update_many", return_value=[]) as revoke,
            patch.object(backend, "supabase_get", return_value=company),
        ):
            result = backend.supabase_apply_finance_member_sync_event(payload)

        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["userId"], "FIN-SYSTEM")
        self.assertEqual(link.call_args.kwargs["sync_status"], "inactive")
        self.assertEqual(revoke.call_args.args[0], "auth_sessions")
        self.assertEqual(revoke.call_args.args[1]["revoked_at"], "__is_null__")

    def test_unmapped_company_member_is_mirrored_inactive_without_fake_company(self) -> None:
        payload = member_event(revision=12, active=True, auth_ready=False, role="admin_director")
        payload["company"] = {
            "tenantId": payload["company"]["tenantId"],
            "entityId": payload["company"]["entityId"],
        }
        payload["issues"].append("company_missing")
        snapshot = finance_bridge.finance_member_event_snapshot(payload)
        user = {"id": "FIN-U100", "finance_source_revision": 12, "company_id": None}

        with (
            patch.object(backend, "_supabase_finance_snapshot_user_candidate", return_value=None),
            patch.object(
                backend,
                "_supabase_upsert_finance_snapshot_user",
                return_value=(user, "applied"),
            ) as user_upsert,
            patch.object(backend, "supabase_upsert_finance_module_link", return_value={}) as link,
            patch.object(backend, "supabase_update_many", return_value=[]) as revoke,
            patch.object(backend, "supabase_upsert_finance_company_snapshot") as company_upsert,
        ):
            result = backend.supabase_apply_finance_member_sync_event(payload)

        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["projectionState"], "inactive")
        self.assertEqual(result["companyId"], "")
        self.assertIsNone(user_upsert.call_args.args[1]["id"])
        self.assertEqual(user_upsert.call_args.args[0]["projection_state"], "inactive")
        link.assert_called_once()
        self.assertEqual(link.call_args.kwargs["sync_status"], "inactive")
        revoke.assert_called_once()
        company_upsert.assert_not_called()

    def test_unsupported_inactive_member_resolves_company_without_overwrite(self) -> None:
        payload = member_event(revision=15, active=False, auth_ready=False, role="unknown_role")
        snapshot = finance_bridge.finance_member_event_snapshot(payload)
        existing = {
            "id": "FIN-OLD-ROLE",
            "email": payload["identity"]["email"],
            "finance_source_revision": 14,
        }
        company = {
            "id": "FINCO-E100",
            "name": "較新的公司名稱",
            "address": "較新的公司地址",
            "status": "active",
            "finance_source_revision": 30,
        }
        with (
            patch.object(backend, "_supabase_finance_snapshot_user_candidate", return_value=existing),
            patch.object(
                backend,
                "supabase_upsert_finance_company_snapshot",
                return_value=(company, "resolved"),
            ) as company_upsert,
            patch.object(
                backend,
                "supabase_request",
                return_value=[{**existing, "status": "停用", "finance_source_revision": 15}],
            ),
            patch.object(backend, "supabase_upsert_finance_module_link", return_value={}),
            patch.object(backend, "supabase_update_many", return_value=[]),
        ):
            _user, resolved_company, disposition = backend._supabase_deactivate_unsupported_finance_member(
                snapshot,
                event_id=payload["eventId"],
                source_revision=15,
            )

        self.assertEqual(disposition, "applied")
        self.assertEqual(resolved_company, company)
        self.assertFalse(company_upsert.call_args.kwargs["update_existing"])

    def test_org_status_system_account_forces_supported_role_inactive(self) -> None:
        payload = member_event(revision=12, active=True, auth_ready=True, role="staff")
        payload["identity"]["orgStatus"] = "system_account"
        existing = {
            "id": "FIN-SYSTEM-STAFF", "account_source": "finance", "logging_account_id": "u-100",
            "finance_employee_id": "u-100", "email": "member-100@example.invalid",
            "auth_user_id": payload["identity"]["authUserId"], "finance_source_revision": 11,
            "role": "員工",
        }
        company = {"id": "FINCO-E100", "name": "去識別化測試公司", "address": "", "status": "active"}

        def cas_response(method: str, path: str, body: dict, prefer: str = "return=representation") -> list[dict]:
            self.assertEqual(body["status"], "停用")
            self.assertEqual(body["finance_source_status"], "inactive")
            return [{**existing, **body}]

        with (
            patch.object(backend, "_supabase_finance_snapshot_user_candidate", side_effect=[existing, existing]),
            patch.object(backend, "supabase_upsert_finance_company_snapshot", return_value=(company, "applied")),
            patch.object(backend, "supabase_request", side_effect=cas_response),
            patch.object(backend, "supabase_upsert_finance_module_link", return_value={}) as link,
            patch.object(backend, "supabase_update_many", return_value=[]) as revoke,
            patch.object(backend, "supabase_get", return_value=company),
            patch.object(
                backend,
                "supabase_patch",
                side_effect=lambda _table, _row_id, values: {**existing, **values},
            ),
        ):
            result = backend.supabase_apply_finance_member_sync_event(payload)

        self.assertEqual(result["projectionState"], "inactive")
        self.assertEqual(link.call_args.kwargs["sync_status"], "inactive")
        revoke.assert_called_once()

    def test_inactive_company_forces_member_projection_inactive(self) -> None:
        payload = member_event(revision=13, active=True, auth_ready=True, role="staff")
        payload["company"]["active"] = False
        snapshot = finance_bridge.finance_member_event_snapshot(payload)
        normalized = backend.normalize_finance_bridge_snapshot(snapshot)
        self.assertEqual(normalized["applicant"]["projection_state"], "inactive")

    def test_active_unsupported_role_fails_before_creating_projection(self) -> None:
        payload = member_event(revision=1, active=True, auth_ready=True, role="unknown_role")
        with (
            patch.object(backend, "_supabase_finance_snapshot_user_candidate", return_value=None),
            patch.object(backend, "supabase_upsert_finance_company_snapshot") as company_write,
        ):
            with self.assertRaisesRegex(backend.FinanceBridgeDenied, "finance_role_unsupported"):
                backend.supabase_apply_finance_member_sync_event(payload)
        company_write.assert_not_called()

    def test_jit_path_uses_shared_company_and_module_link_helpers(self) -> None:
        snapshot = finance_bridge.finance_member_event_snapshot(member_event())
        source = backend.normalize_finance_bridge_snapshot(snapshot)["applicant"]
        company = {"id": "FINCO-E100", "finance_entity_id": "E100", "name": "公司", "address": "", "status": "active"}
        user = {"id": "FIN-U100", "company_id": company["id"], "role": "員工"}
        with (
            patch.object(backend, "supabase_upsert_finance_company_snapshot", return_value=(company, "applied")) as company_upsert,
            patch.object(backend, "supabase_finance_company_by_entity", return_value=company),
            patch.object(backend, "_supabase_finance_snapshot_user_candidate", return_value={"id": "FIN-U100"}),
            patch.object(backend, "_supabase_upsert_finance_snapshot_user", return_value=(user, "applied")),
            patch.object(backend, "supabase_upsert_finance_module_link", return_value={}) as link_upsert,
            patch.object(backend, "supabase_get", return_value=company),
            patch.object(
                backend,
                "supabase_patch",
                side_effect=lambda _table, _row_id, values: {**user, **values},
            ),
        ):
            synced, _ = backend.sync_supabase_finance_snapshot(snapshot)

        self.assertEqual(synced["id"], "FIN-U100")
        company_upsert.assert_called_once()
        self.assertFalse(company_upsert.call_args.kwargs["update_existing"])
        link_upsert.assert_called_once()
        self.assertEqual(link_upsert.call_args.args[1]["finance_user_id"], source["finance_user_id"])

    def test_module_link_metadata_is_canonical_json_text(self) -> None:
        source = backend.normalize_finance_bridge_snapshot(
            finance_bridge.finance_member_event_snapshot(member_event(revision=8))
        )["applicant"]
        user = {"id": "FIN-U100", "role": "員工"}
        inserted: dict = {}

        def capture_insert(table: str, values: dict) -> dict:
            self.assertEqual(table, "module_account_links")
            inserted.update(values)
            return values

        with (
            patch.object(backend, "supabase_filter_rows", return_value=[]),
            patch.object(backend, "supabase_insert", side_effect=capture_insert),
        ):
            backend.supabase_upsert_finance_module_link(
                user,
                source,
                sync_status="active",
                event_id="fin-member-u100-r8",
                source_revision=8,
            )

        self.assertIsInstance(inserted["metadata_json"], str)
        self.assertEqual(
            json.loads(inserted["metadata_json"]),
            {
                "source": "finance_master",
                "eventId": "fin-member-u100-r8",
                "sourceRevision": 8,
            },
        )
        self.assertEqual(
            inserted["metadata_json"],
            '{"eventId":"fin-member-u100-r8","source":"finance_master","sourceRevision":8}',
        )

    def test_old_member_snapshot_cannot_roll_back_revisioned_company(self) -> None:
        company = {
            "id": "FINCO-E100",
            "finance_entity_id": "E100",
            "name": "公司事件更新後名稱",
            "tax_id": "00000000",
            "address": "公司事件更新後地址",
            "status": "inactive",
            "source_system": "finance",
            "finance_source_revision": 20,
            "finance_source_updated_at": "2026-08-22T11:00:00+08:00",
        }
        old_member_company = {
            "tenantId": "tenant-1",
            "entityId": "E100",
            "name": "舊名稱",
            "taxId": "11111111",
            "address": "舊地址",
            "active": True,
            "sourceUpdatedAt": "2026-08-22T09:00:00+08:00",
        }
        with (
            patch.object(backend, "supabase_filter_rows", return_value=[company]),
            patch.object(backend, "supabase_patch") as patch_company,
            patch.object(backend, "supabase_request") as cas_company,
        ):
            resolved, disposition = backend.supabase_upsert_finance_company_snapshot(
                old_member_company,
                update_existing=False,
            )

        self.assertEqual(disposition, "resolved")
        self.assertEqual(resolved, company)
        patch_company.assert_not_called()
        cas_company.assert_not_called()

    def test_company_inactive_after_member_cascades_user_session_and_link(self) -> None:
        company = {
            "id": "FINCO-E100", "name": "停用公司", "address": "最新地址", "status": "inactive",
        }
        user = {
            "id": "FIN-U100", "account_source": "finance", "company_id": "FINCO-E100",
            "status": "啟用", "finance_source_status": "active",
        }
        link = {"id": "LINK-U100", "sync_status": "active"}

        def rows(table: str, filters: dict, **kwargs: object) -> list[dict]:
            if table == "users":
                return [user]
            if table == "module_account_links":
                return [link]
            return []

        patched: list[tuple[str, str, dict]] = []

        def capture_patch(table: str, row_id: str, values: dict) -> dict:
            patched.append((table, row_id, values))
            return {**(user if table == "users" else link), **values}

        with (
            patch.object(backend, "supabase_filter_rows", side_effect=rows),
            patch.object(backend, "supabase_patch", side_effect=capture_patch),
            patch.object(backend, "supabase_update_many", return_value=[{"id": "SES-1"}]) as revoke,
        ):
            result = backend.supabase_cascade_finance_company_projection(company)

        self.assertEqual(result["affectedUsers"], 1)
        self.assertEqual(result["inactivatedLinks"], 1)
        user_values = next(values for table, _row_id, values in patched if table == "users")
        self.assertEqual(user_values["status"], "停用")
        self.assertEqual(user_values["finance_source_status"], "inactive")
        self.assertEqual(user_values["company_address"], "最新地址")
        link_values = next(values for table, _row_id, values in patched if table == "module_account_links")
        self.assertEqual(link_values["sync_status"], "inactive")
        revoke.assert_called_once()

    def test_company_inactive_before_member_final_check_wins_race(self) -> None:
        user = {
            "id": "FIN-U100", "role": "員工", "status": "啟用",
            "company_name": "舊公司", "company_address": "舊地址",
        }
        source = self.normalized_source(auth_ready=True)
        observed_company = {"id": "FINCO-E100", "name": "舊公司", "address": "舊地址", "status": "active"}
        latest_company = {"id": "FINCO-E100", "name": "新公司", "address": "新地址", "status": "inactive"}
        disabled = {**user, "status": "停用", "finance_source_status": "inactive", "company_name": "新公司", "company_address": "新地址"}
        with (
            patch.object(backend, "supabase_get", return_value=latest_company),
            patch.object(backend, "supabase_patch", return_value=disabled) as patch_user,
            patch.object(backend, "supabase_upsert_finance_module_link", return_value={}) as link,
            patch.object(backend, "supabase_update_many", return_value=[]) as revoke,
        ):
            projected, inactive = backend.supabase_enforce_finance_company_state(
                user,
                source,
                observed_company,
                event_id="fin-member-u-100-r20",
                source_revision=20,
            )

        self.assertTrue(inactive)
        self.assertEqual(projected["status"], "停用")
        self.assertEqual(patch_user.call_args.args[2]["company_name"], "新公司")
        self.assertEqual(link.call_args.kwargs["sync_status"], "inactive")
        revoke.assert_called_once()

    def test_company_changed_uses_entity_revision_cas(self) -> None:
        existing = {
            "id": "FINCO-E100", "finance_entity_id": "E100", "name": "舊公司名稱",
            "address": "舊地址", "status": "active", "finance_source_revision": 11,
        }
        source = {
            "tenantId": "tenant-1", "entityId": "E100", "name": "新公司名稱",
            "taxId": "00000000", "address": "新地址", "active": True,
            "sourceUpdatedAt": "2026-08-22T10:00:00+08:00",
        }

        def cas_response(method: str, path: str, body: dict, prefer: str = "return=representation") -> list[dict]:
            self.assertIn("finance_source_revision=eq.11", path)
            self.assertEqual(body["finance_source_revision"], 12)
            self.assertEqual(body["name"], "新公司名稱")
            return [{**existing, **body}]

        with (
            patch.object(backend, "supabase_filter_rows", return_value=[existing]),
            patch.object(backend, "supabase_request", side_effect=cas_response),
        ):
            company, disposition = backend.supabase_upsert_finance_company_snapshot(
                source, source_revision=12, event_id="fin-company-E100-r12"
            )
        self.assertEqual(disposition, "applied")
        self.assertEqual(company["finance_source_revision"], 12)

        with (
            patch.object(backend, "supabase_filter_rows", return_value=[company]),
            patch.object(backend, "supabase_request") as request,
        ):
            stale, disposition = backend.supabase_upsert_finance_company_snapshot(
                source, source_revision=10, event_id="fin-company-E100-r10"
            )
        self.assertEqual(disposition, "stale")
        self.assertEqual(stale["finance_source_revision"], 12)
        request.assert_not_called()

    def test_nonce_replay_is_rejected_after_atomic_claim_conflict(self) -> None:
        verified = {
            "nonceHash": "a" * 64,
            "timestamp": int(time.time()),
        }
        with (
            patch.object(backend, "supabase_request", side_effect=[[], RuntimeError("duplicate")]),
            patch.object(backend, "supabase_filter_rows", return_value=[{"nonce_hash": "a" * 64}]),
        ):
            self.assertFalse(backend.claim_supabase_finance_member_sync_nonce(verified))


class FinanceMemberSyncHandlerTestCase(unittest.TestCase):
    def test_handler_returns_enum_and_exact_matching_boolean(self) -> None:
        payload = member_event(revision=14)
        raw, _ = signed_request(payload)
        handler = object.__new__(backend.Handler)
        handler.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(raw)),
            "X-Finance-Timestamp": "1787300000",
            "X-Finance-Nonce": "abcdefghijklmnopqrstuvwx",
            "X-Finance-Signature": "a" * 64,
        }
        handler.rfile = io.BytesIO(raw)
        handler.send_json = Mock()
        verified = {
            "payload": payload,
            "payloadSha256": "b" * 64,
            "nonceHash": "c" * 64,
            "timestamp": 1_787_300_000,
        }
        result = {
            "status": "applied",
            "userId": "FIN-U100",
            "companyId": "FINCO-E100",
        }
        with (
            patch.object(backend, "USE_SUPABASE", True),
            patch.object(backend, "verify_finance_member_sync_request", return_value=verified),
            patch.object(backend, "claim_supabase_finance_member_sync_nonce", return_value=True),
            patch.object(backend, "supabase_finance_sync_receipt", return_value=None),
            patch.object(backend, "supabase_apply_finance_member_sync_event", return_value=result),
            patch.object(backend, "supabase_record_finance_sync_receipt", return_value={}),
        ):
            handler.handle_finance_member_sync()

        response, status, _headers = handler.send_json.call_args.args
        self.assertEqual(status, 200)
        self.assertEqual(response["status"], "applied")
        self.assertTrue(response["applied"])
        self.assertFalse(response["stale"])
        self.assertFalse(response["replayed"])


class FinanceMirrorMigrationContractTestCase(unittest.TestCase):
    def test_migration_is_fail_closed_and_service_role_only(self) -> None:
        sql = (Path(__file__).resolve().parents[1] / "supabase" / "migrations" / "20260821181430_finance_master_auto_mirror.sql").read_text()
        self.assertIn("finance legacy alias preflight failed", sql)
        self.assertIn("u_1779419271785", sql)
        self.assertIn("u_entrepreneur", sql)
        self.assertIn("u_1779426092633", sql)
        self.assertIn("finance system-account preflight failed", sql)
        self.assertIn("LOG-71EA5F5B96", sql)
        self.assertIn("LOG-748CCCF0BE", sql)
        self.assertIn("LOG-88B71ACA68", sql)
        self.assertIn("LOG-A0DD7667AA", sql)
        self.assertIn("LINK-FINANCE-EDOC-A0DD7667AA", sql)
        self.assertIn("md5(lower(btrim(coalesce(l.source_email, '')))) = e.email_md5", sql)
        self.assertIn("where auth_user_id is not null", sql.lower())
        self.assertNotIn("btrim(auth_user_id)", sql.lower())
        self.assertIn("alter table public.finance_member_sync_nonces enable row level security", sql.lower())
        self.assertIn("alter table public.finance_member_sync_receipts enable row level security", sql.lower())
        self.assertIn("revoke all on public.finance_member_sync_nonces from public, anon, authenticated", sql.lower())
        self.assertIn("grant select, insert, update on public.finance_member_sync_receipts to service_role", sql.lower())
        self.assertIn("create unique index if not exists users_finance_employee_uq", sql.lower())
        self.assertIn("create unique index if not exists companies_finance_entity_id_uq", sql.lower())
        self.assertIn("add column if not exists finance_employee_id text", sql.lower())
        self.assertIn("add column if not exists manager_employee_id text", sql.lower())
        self.assertIn("add column if not exists approval_manager_employee_id text", sql.lower())
        self.assertIn("add column if not exists finance_entity_id text", sql.lower())
        self.assertIn("add column if not exists last_synced_from_finance_at text", sql.lower())
        self.assertNotIn("on_conflict", sql.lower())


if __name__ == "__main__":
    unittest.main()
