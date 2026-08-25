from __future__ import annotations

import copy
import hashlib
import json
import re
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import backend
import finance_bridge


TEST_SECRET = "finance-organization-sync-test-secret-32-bytes"
TENANT_ID = "00000000-0000-0000-0000-000000000001"
VERSION_ID = "00000000-0000-0000-0000-000000000014"
DEPARTMENT_UNIT_ID = "00000000-0000-0000-0000-000000000100"
SECTION_UNIT_ID = "00000000-0000-0000-0000-000000000110"
APPLICANT_ID = "00000000-0000-0000-0000-000000001000"
DIRECTOR_ID = "00000000-0000-0000-0000-000000002000"
ROOT = Path(__file__).resolve().parents[1]
ORGANIZATION_MIGRATION = ROOT / "supabase" / "migrations" / "20260825101840_finance_organization_directory_v2.sql"
ORGANIZATION_REVISION_LOCK_MIGRATION = ROOT / "supabase" / "migrations" / "20260825102459_lock_finance_organization_revisions.sql"
FINANCE_TENANT_BACKFILL_MIGRATION = ROOT / "supabase" / "migrations" / "20260825143558_backfill_finance_tenant_scope.sql"


def organization_event(*, revision: int = 14) -> dict:
    """Return one complete, de-identified Finance organization v2 event."""
    etag = hashlib.sha256(f"organization-{TENANT_ID}-v{revision}".encode("utf-8")).hexdigest()
    return {
        "source": "finance",
        "schemaVersion": 2,
        "eventId": f"fin-organization-{revision}",
        "eventType": "organization.published",
        "tenantId": TENANT_ID,
        "sourceRevision": revision,
        "occurredAt": "2026-08-25T15:00:00+08:00",
        "organization": {
            "tenantId": TENANT_ID,
            "versionId": VERSION_ID,
            "versionNo": revision,
            "etag": etag,
            "schemaVersion": 2,
            "publishedAt": "2026-08-25T14:59:00+08:00",
            "units": [
                {
                    "id": DEPARTMENT_UNIT_ID,
                    "code": "D100",
                    "name": "去識別化營運部",
                    "parentOrgUnitId": None,
                    "unitType": "department",
                    "sortOrder": 10,
                    "active": True,
                    "isPostingUnit": True,
                    "entityScopeMode": "explicit",
                    "entityCodes": ["E100"],
                },
                {
                    "id": SECTION_UNIT_ID,
                    "code": "S110",
                    "name": "去識別化業務課",
                    "parentOrgUnitId": DEPARTMENT_UNIT_ID,
                    "unitType": "section",
                    "sortOrder": 20,
                    "active": True,
                    "isPostingUnit": True,
                    "entityScopeMode": "explicit",
                    "entityCodes": ["E100"],
                },
            ],
            "assignments": [
                {
                    "id": "assignment-section-chief-0001",
                    "financeUserId": APPLICANT_ID,
                    "orgUnitId": SECTION_UNIT_ID,
                    "positionCode": "SECTION_HEAD",
                    "assignmentKind": "primary",
                    "headKind": "permanent",
                    "canApprove": True,
                    "effectiveFrom": None,
                    "effectiveTo": None,
                    "active": True,
                },
                {
                    "id": "assignment-department-head-0002",
                    "financeUserId": DIRECTOR_ID,
                    "orgUnitId": DEPARTMENT_UNIT_ID,
                    "positionCode": "DEPARTMENT_HEAD",
                    "assignmentKind": "primary",
                    "headKind": "permanent",
                    "canApprove": True,
                    "effectiveFrom": None,
                    "effectiveTo": None,
                    "active": True,
                },
            ],
            "reportingOverrides": [
                {
                    "id": "override-supervisor-0001",
                    "financeUserId": APPLICANT_ID,
                    "supervisorFinanceUserId": DIRECTOR_ID,
                    "effectiveFrom": None,
                    "effectiveTo": None,
                    "active": True,
                },
            ],
        },
    }


def signed_request(
    payload: dict,
    *,
    timestamp: int | None = None,
    nonce: str = "organization_sync_nonce_0001",
) -> tuple[bytes, dict]:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    wire_timestamp = str(timestamp if timestamp is not None else int(time.time()))
    return raw, {
        "x-finance-timestamp": wire_timestamp,
        "x-finance-nonce": nonce,
        "x-finance-signature": finance_bridge.finance_member_sync_signature(
            TEST_SECRET,
            wire_timestamp,
            nonce,
            raw,
        ),
    }


class FinanceOrganizationPublishedContractTest(unittest.TestCase):
    def verify(self, payload: dict) -> dict:
        raw, headers = signed_request(payload, timestamp=1_787_300_000)
        return finance_bridge.verify_finance_member_sync_request(
            raw,
            headers,
            TEST_SECRET,
            now_timestamp=1_787_300_020,
        )

    def test_v2_organization_event_hmac_covers_exact_wire_bytes(self) -> None:
        payload = organization_event()
        raw, headers = signed_request(payload, timestamp=1_787_300_000)

        verified = finance_bridge.verify_finance_member_sync_request(
            raw,
            headers,
            TEST_SECRET,
            now_timestamp=1_787_300_020,
        )

        self.assertEqual(verified["payload"], payload)
        self.assertEqual(verified["payload"]["eventType"], "organization.published")
        self.assertEqual(verified["payload"]["schemaVersion"], 2)
        self.assertEqual(verified["payloadSha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(len(verified["nonceHash"]), 64)

        with self.assertRaises(finance_bridge.FinanceMemberSyncAuthError):
            finance_bridge.verify_finance_member_sync_request(
                raw + b" ",
                headers,
                TEST_SECRET,
                now_timestamp=1_787_300_020,
            )

    def test_complete_organization_payload_is_preserved_without_personal_profile_data(self) -> None:
        payload = organization_event()
        verified = self.verify(payload)["payload"]
        organization = verified["organization"]

        self.assertEqual(
            set(organization),
            {
                "tenantId",
                "versionId",
                "versionNo",
                "etag",
                "schemaVersion",
                "publishedAt",
                "units",
                "assignments",
                "reportingOverrides",
            },
        )
        self.assertEqual(verified["sourceRevision"], organization["versionNo"])
        self.assertEqual(len(organization["units"]), 2)
        self.assertEqual(len(organization["assignments"]), 2)
        self.assertEqual(len(organization["reportingOverrides"]), 1)
        self.assertNotIn("email", json.dumps(organization, ensure_ascii=False).lower())

    def test_organization_payload_is_strict_and_referentially_valid(self) -> None:
        mutations = {
            "revision mismatch": lambda event: event.update({"sourceRevision": 15}),
            "tenant mismatch": lambda event: event.update({"tenantId": "00000000-0000-0000-0000-000000000999"}),
            "organization schema downgrade": lambda event: event["organization"].update({"schemaVersion": 1}),
            "invalid etag": lambda event: event["organization"].update({"etag": "not-a-sha256"}),
            "missing collection": lambda event: event["organization"].pop("reportingOverrides"),
            "unknown nested field": lambda event: event["organization"]["units"][0].update({"managerName": "不應夾帶姓名"}),
            "duplicate unit id": lambda event: event["organization"]["units"][1].update({"id": DEPARTMENT_UNIT_ID}),
            "orphan parent": lambda event: event["organization"]["units"][1].update({"parentOrgUnitId": "00000000-0000-0000-0000-999999999999"}),
            "orphan assignment": lambda event: event["organization"]["assignments"][0].update({"orgUnitId": "00000000-0000-0000-0000-999999999999"}),
            "non-canonical entity scope mode": lambda event: event["organization"]["units"][0].update({"entityScopeMode": "selected"}),
            "self reporting override": lambda event: event["organization"]["reportingOverrides"][0].update({"supervisorFinanceUserId": APPLICANT_ID}),
            "unexpected top-level company": lambda event: event.update({"company": {}}),
        }

        for label, mutate in mutations.items():
            with self.subTest(label=label):
                payload = copy.deepcopy(organization_event())
                mutate(payload)
                raw, headers = signed_request(payload, timestamp=1_787_300_000)
                exception = (
                    self.assertRaisesRegex(
                        finance_bridge.FinanceMemberSyncContractError,
                        "revision_mismatch",
                    )
                    if label == "revision mismatch"
                    else self.assertRaises(finance_bridge.FinanceMemberSyncContractError)
                )
                with exception:
                    finance_bridge.verify_finance_member_sync_request(
                        raw,
                        headers,
                        TEST_SECRET,
                        now_timestamp=1_787_300_020,
                    )

    def test_organization_event_requires_v2_envelope(self) -> None:
        payload = organization_event()
        payload["schemaVersion"] = 1
        raw, headers = signed_request(payload, timestamp=1_787_300_000)
        with self.assertRaisesRegex(
            finance_bridge.FinanceMemberSyncContractError,
            "contract_invalid",
        ):
            finance_bridge.verify_finance_member_sync_request(
                raw,
                headers,
                TEST_SECRET,
                now_timestamp=1_787_300_020,
            )

    def test_revision_history_is_database_enforced_immutable(self) -> None:
        sql = ORGANIZATION_REVISION_LOCK_MIGRATION.read_text(encoding="utf-8").lower()
        self.assertIn("revoke update, delete, truncate", sql)
        self.assertIn("from public, anon, authenticated, service_role", sql)
        self.assertIn("before update or delete", sql)
        self.assertIn("before truncate", sql)
        self.assertIn("finance_organization_revision_immutable", sql)

    def test_legacy_finance_rows_are_backfilled_only_for_one_tenant(self) -> None:
        sql = FINANCE_TENANT_BACKFILL_MIGRATION.read_text(encoding="utf-8").lower()
        self.assertIn("v_tenant_count <> 1", sql)
        self.assertIn("finance_tenant_backfill_requires_exactly_one_projection_tenant", sql)
        self.assertIn("update public.companies", sql)
        self.assertIn("update public.users", sql)
        self.assertIn("update public.finance_member_sync_receipts", sql)
        self.assertIn("finance_tenant_backfill_incomplete", sql)


class FinanceOrganizationRevisionApplyTest(unittest.TestCase):
    @staticmethod
    def projection_state(*, current_version: int) -> dict:
        return {
            "finance_tenant_id": TENANT_ID,
            "version_no": current_version,
            "etag": hashlib.sha256(f"current-{current_version}".encode("utf-8")).hexdigest(),
            "last_synced_from_finance_at": "2026-08-25T15:01:00+08:00",
        }

    def run_apply(self, *, current_version: int, rpc_status: str) -> dict:
        apply_event = getattr(backend, "supabase_apply_finance_organization_sync_event", None)
        self.assertTrue(
            callable(apply_event),
            "backend.supabase_apply_finance_organization_sync_event(payload) 尚未實作",
        )
        projected_version = 14 if rpc_status == "applied" else current_version
        projected_count = 2 if rpc_status == "applied" else 3
        state = self.projection_state(current_version=current_version)
        expected = {
            "status": rpc_status,
            "sourceRevision": 14,
            "organizationVersion": projected_version,
            "organizationUnitCount": projected_count,
            "organizationAssignmentCount": projected_count,
        }

        current_state = {"row": state}

        def projected_rows(kind: str) -> list[dict]:
            return [
                {
                    "id": f"{kind}-{index}",
                    "finance_tenant_id": TENANT_ID,
                    "version_no": current_state["row"]["version_no"],
                    "active": True,
                }
                for index in range(projected_count)
            ]

        def filter_rows(table: str, *_args, **_kwargs) -> list[dict]:
            if table == "finance_organization_projection_state":
                return [copy.deepcopy(current_state["row"])]
            if table == "finance_organization_units":
                return projected_rows("unit")
            if table == "finance_organization_assignments":
                return projected_rows("assignment")
            return []

        def request(method: str, path: str, body=None, prefer: str = "return=representation"):
            del body, prefer
            if method == "GET" and "finance_organization_projection_state" in path:
                return [copy.deepcopy(current_state["row"])]
            if method == "POST" and "rpc/" in path:
                if rpc_status == "applied":
                    current_state["row"] = self.projection_state(current_version=14)
                return [
                    {
                        "status": rpc_status,
                        "sourceRevision": 14,
                        "organizationVersion": projected_version,
                        "organizationUnitCount": projected_count,
                        "organizationAssignmentCount": projected_count,
                    }
                ]
            return []

        with (
            patch.object(backend, "supabase_filter_rows", side_effect=filter_rows),
            patch.object(backend, "supabase_request", side_effect=request),
            patch.object(backend, "supabase_insert", side_effect=lambda _table, row: dict(row)),
            patch.object(
                backend,
                "supabase_patch",
                side_effect=lambda _table, row_id, row: {"id": row_id, **row},
            ),
            patch.object(
                backend,
                "supabase_update_many",
                side_effect=lambda _table, _filters, row: [dict(row)],
            ),
        ):
            payload = organization_event()
            payload_sha256 = hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            result = apply_event(payload, payload_sha256)

        self.assertEqual(
            {key: result.get(key) for key in expected},
            expected,
        )
        return result

    def test_newer_organization_revision_is_applied(self) -> None:
        self.run_apply(current_version=13, rpc_status="applied")

    def test_older_organization_revision_is_stale_and_does_not_replace_current(self) -> None:
        self.run_apply(current_version=15, rpc_status="stale")


class FinanceOrganizationMigrationAndRouteSecurityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = ORGANIZATION_MIGRATION.read_text(encoding="utf-8").lower()
        cls.backend_source = (ROOT / "backend.py").read_text(encoding="utf-8")

    def assert_sql_contains(self, needle: str, message: str) -> None:
        self.assertTrue(needle.lower() in self.sql, message)

    def test_organization_projection_tables_are_force_rls_and_browser_revoked(self) -> None:
        tables = (
            "finance_organization_revisions",
            "finance_organization_projection_state",
            "finance_organization_units",
        )
        for table in tables:
            with self.subTest(table=table):
                self.assert_sql_contains(
                    f"alter table public.{table} enable row level security",
                    f"{table} 必須啟用 RLS。",
                )
                self.assert_sql_contains(
                    f"alter table public.{table} force row level security",
                    f"{table} 必須 FORCE RLS，避免 owner 繞過策略。",
                )
                self.assert_sql_contains(
                    f"revoke all on public.{table} from public, anon, authenticated",
                    f"{table} 不可暴露給 browser roles。",
                )

    def test_projection_rpc_is_service_role_only_and_applies_receipt_atomically(self) -> None:
        signature = "public.edoc_apply_finance_organization_projection_v2"
        start = self.sql.index(f"create or replace function {signature}")
        end = self.sql.index(f"\nalter function {signature}", start)
        rpc = self.sql[start:end]

        self.assertIn("security definer", rpc)
        self.assertIn("pg_advisory_xact_lock", rpc)
        for write in (
            "insert into public.finance_organization_revisions",
            "insert into public.finance_organization_units",
            "insert into public.finance_organization_projection_state",
            "insert into public.finance_member_sync_receipts",
        ):
            with self.subTest(write=write):
                self.assertIn(write, rpc)
        self.assertLess(
            rpc.index("insert into public.finance_organization_projection_state"),
            rpc.index("insert into public.finance_member_sync_receipts"),
            "projection 與 receipt 必須在同一 RPC 交易內，且 projection 成功後才記 receipt。",
        )
        self.assertNotIn("commit;", rpc, "Postgres function 內不可提前提交，錯誤必須整筆 rollback。")

        self.assert_sql_contains(
            f"revoke all on function {signature}",
            "organization apply RPC 必須先 revoke 預設執行權。",
        )
        function_acl_start = self.sql.index(f"revoke all on function {signature}")
        function_acl_end = self.sql.index("alter table public.portal_handoff_nonces", function_acl_start)
        function_acl = self.sql[function_acl_start:function_acl_end]
        self.assertIn("from public, anon, authenticated", function_acl)
        self.assertIn(f"grant execute on function {signature}", function_acl)
        self.assertIn("to service_role", function_acl)

    def test_portal_handoff_nonce_replay_store_is_present_and_private(self) -> None:
        self.assert_sql_contains(
            "create table if not exists public.portal_handoff_nonces",
            "正式 SSO handoff 必須有 durable nonce replay store。",
        )
        self.assert_sql_contains("jti_hash text primary key", "handoff jti hash 必須唯一。")
        self.assert_sql_contains(
            "alter table public.portal_handoff_nonces enable row level security",
            "handoff nonce store 必須啟用 RLS。",
        )
        self.assert_sql_contains(
            "revoke all on public.portal_handoff_nonces from public, anon, authenticated",
            "handoff nonce 不可由 browser roles 讀寫。",
        )

    def test_finance_directory_routes_are_after_authentication_gate(self) -> None:
        marker = 'if method == "GET" and parts == ["finance-directory"]:'
        route_offsets = [match.start() for match in re.finditer(re.escape(marker), self.backend_source)]
        self.assertEqual(len(route_offsets), 2, "Supabase 與 SQLite route 都必須有同一個認證目錄入口。")

        expected_targets = {
            "supabase_finance_directory(session)",
            "local_finance_directory(conn, session)",
        }
        observed_targets: set[str] = set()
        for route_offset in route_offsets:
            with self.subTest(route_offset=route_offset):
                gate_start = self.backend_source.rfind(
                    'if parts and parts[0] == "cron":',
                    0,
                    route_offset,
                )
                self.assertGreaterEqual(gate_start, 0, "finance-directory 前找不到共用 authentication gate。")
                gate = self.backend_source[gate_start:route_offset]
                self.assertIn("session =", gate)
                self.assertIn("if not session:", gate)
                self.assertIn('self.send_json({"error": "unauthorized"}, 401)', gate)

                route = self.backend_source[route_offset:route_offset + 240]
                target = next((item for item in expected_targets if item in route), None)
                self.assertIsNotNone(target, "finance-directory 必須呼叫 scoped directory function。")
                observed_targets.add(str(target))

        self.assertEqual(observed_targets, expected_targets)


if __name__ == "__main__":
    unittest.main()
