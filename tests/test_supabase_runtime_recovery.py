from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path

try:
    from pglast import parse_plpgsql, parse_sql
except ImportError:  # pragma: no cover - CI installs the pinned SQL parser.
    parse_plpgsql = None
    parse_sql = None


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "supabase" / "migrations"
RECOVERY = ROOT / "supabase" / "recovery" / "complete_edoc_runtime_recovery_20260827.sql"
SCHEMA_PARITY = MIGRATIONS / "20260827050436_complete_edoc_runtime_schema_parity.sql"
STORAGE_MIGRATIONS = ROOT / "supabase" / "storage-migrations"
STORAGE_BASE = STORAGE_MIGRATIONS / "20260824034730_dedicated_edoc_private_storage_buckets.sql"
STORAGE_HARDEN = STORAGE_MIGRATIONS / "20260827042214_harden_edoc_storage_buckets.sql"
STORAGE_POLICY_ALLOWLIST = STORAGE_MIGRATIONS / "20260827050000_enforce_empty_storage_client_policy_allowlist.sql"
NOTIFICATIONS = MIGRATIONS / "20260827042306_safe_notification_bootstrap.sql"
CLEANUP = MIGRATIONS / "20260827050447_remove_exact_demo_bootstrap_records_forward.sql"
ATOMIC_FORWARD = MIGRATIONS / "20260827050450_atomic_official_submission_editor_finalize_forward.sql"
FK_INDEX_FORWARD = MIGRATIONS / "20260827050452_add_confirmed_edoc_fk_indexes_forward.sql"
BUSINESS_CONFLICT_FORWARD = (
    MIGRATIONS / "20260827101636_avoid_postgrest_business_conflict_retries.sql"
)
EDITOR_IMMUTABLE_PROMOTION = (
    MIGRATIONS / "20260827194500_promote_editor_tus_staging_to_immutable.sql"
)
COMPANY_SEAL_DIMENSION_FORWARD = (
    MIGRATIONS / "20260827133432_add_company_seal_file_dimension_metadata.sql"
)
FUNCTION_TYPE_RESOLUTION_FORWARD = (
    MIGRATIONS / "20260827133545_fix_official_document_function_type_resolution.sql"
)
FINANCE_DELEGATION_HELPERS_FORWARD = (
    MIGRATIONS / "20260827133700_add_finance_delegation_profile_helpers.sql"
)
INBOUND_MUTATION_CONTRACT = (
    MIGRATIONS / "20260826033323_inbound_mutation_contract.sql"
)
EDITOR_STORAGE_PREFLIGHT = (
    ROOT / "supabase" / "verification" / "editor_storage_promotion_preflight.sql"
)
FINANCE_TENANT_BACKFILL = MIGRATIONS / "20260825143558_backfill_finance_tenant_scope.sql"
FRESH_FINANCE_SENTINEL_CLEANUP = (
    MIGRATIONS / "20260827064100_remove_fresh_finance_bootstrap_sentinel.sql"
)
AUDIT_HASH_HARDENING = MIGRATIONS / "20260827061915_harden_audit_hash_runtime.sql"
CUTOVER_CHECKS = ROOT / "supabase" / "verification" / "production_cutover_checks.sql"
FRESH_BOOTSTRAP_SMOKE = ROOT / "supabase" / "verification" / "fresh_bootstrap_smoke.sql"
STORAGE_CUTOVER_CHECKS = ROOT / "supabase" / "verification" / "dedicated_storage_cutover_checks.sql"
AUDIT_CONCURRENCY_CHECKS = ROOT / "supabase" / "verification" / "audit_chain_concurrency_check.sql"
MANIFEST = ROOT / "supabase" / "verification" / "migration_manifest.json"
ROLES_BOOTSTRAP = ROOT / "supabase" / "roles.sql"


class SupabaseRuntimeRecoveryTestCase(unittest.TestCase):
    def test_applied_finance_backfill_is_immutable_and_fresh_reset_uses_forward_sentinel(self) -> None:
        raw = FINANCE_TENANT_BACKFILL.read_bytes()
        sql = raw.decode("utf-8").lower()
        roles = ROLES_BOOTSTRAP.read_text(encoding="utf-8").lower()
        cleanup = FRESH_FINANCE_SENTINEL_CLEANUP.read_text(encoding="utf-8").lower()
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

        # This migration predates the current hardening branch and may already
        # be recorded remotely. Its repository checksum is a provenance gate.
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            "78730e2bb61da03b8826940a4ca8f316c8c8877404b608219ac0e69281e968f1",
        )
        self.assertNotIn("if v_tenant_count = 0 then", sql)
        self.assertEqual(
            sql.count("finance_tenant_backfill_requires_exactly_one_projection_tenant"),
            1,
        )

        # roles.sql is fresh-reset-only. The sentinel lets the immutable
        # migration run, then a later exact forward migration removes it.
        self.assertIn("create table if not exists public.finance_organization_projection_state", roles)
        self.assertIn("'__edoc_fresh_bootstrap_only__'", roles)
        self.assertIn(FRESH_FINANCE_SENTINEL_CLEANUP.name, manifest["migrations"])
        self.assertIn("fresh_finance_bootstrap_sentinel_signature_mismatch", cleanup)
        self.assertIn("fresh_finance_bootstrap_sentinel_has_reference", cleanup)
        self.assertIn("fresh_finance_bootstrap_sentinel_delete_failed", cleanup)
        self.assertIn("delete from public.finance_organization_projection_state", cleanup)
        self.assertIn("join public.users linked_user", cleanup)
        self.assertNotIn(
            "from public.module_account_links\n    where finance_tenant_id",
            cleanup,
        )
        for relation in (
            "companies",
            "users",
            "finance_member_sync_receipts",
            "finance_organization_revisions",
            "finance_organization_units",
        ):
            self.assertIn(f"select 1 from public.{relation}", cleanup)
        self.assertIn("from public.module_account_links account_link", cleanup)
        if parse_sql is not None:
            parse_sql(sql)
            parse_sql(cleanup)

    def test_roles_bootstrap_supplies_only_structural_fresh_reset_prerequisites(self) -> None:
        sql = ROLES_BOOTSTRAP.read_text(encoding="utf-8").lower()
        expected = {
            "perm-inbound",
            "perm-dispatch",
            "perm-jagent",
            "perm-workflow",
            "perm-seal",
            "perm-audit",
            "perm-security",
            "perm-report",
            "perm-settings",
        }
        for permission_id in expected:
            self.assertIn(f"'{permission_id}'", sql)
        self.assertNotRegex(sql, r"insert\s+into\s+public\.(users|companies|documents)\b")
        self.assertNotIn("password", sql)
        self.assertIn("create extension if not exists pgcrypto with schema extensions", sql)
        self.assertIn("edoc_pgcrypto_extensions_schema_required", sql)
        self.assertIn("pg_catalog.to_regprocedure('extensions.digest(bytea,text)')", sql)
        self.assertIn("function public.digest(data text, digest_type text)", sql)
        self.assertIn("function public.digest(data bytea, digest_type text)", sql)
        self.assertGreaterEqual(sql.count("set search_path = ''"), 2)
        self.assertIn("extensions.digest(pg_catalog.convert_to(data, 'utf8'), digest_type)", sql)
        for signature in ("public.digest(text, text)", "public.digest(bytea, text)"):
            self.assertIn(
                f"revoke all on function {signature} from public, anon, authenticated",
                sql,
            )
            self.assertIn(
                f"grant execute on function {signature} to postgres, service_role",
                sql,
            )
        self.assertIn("create schema if not exists private authorization postgres", sql)
        self.assertIn(
            "revoke all on schema private from public, anon, authenticated",
            sql,
        )
        self.assertIn("grant usage on schema private to service_role", sql)
        self.assertIn("'__edoc_fresh_bootstrap_only__'", sql)
        self.assertIn("'edoc-fresh-bootstrap-compat-v1'", sql)
        if parse_sql is not None:
            self.assertGreaterEqual(len(parse_sql(sql)), 2)

    def test_recovery_snapshot_and_storage_sql_are_outside_main_migration_chain(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        names = set(manifest["migrations"])
        self.assertIn(SCHEMA_PARITY.name, names)
        self.assertIn(COMPANY_SEAL_DIMENSION_FORWARD.name, names)
        self.assertIn(FUNCTION_TYPE_RESOLUTION_FORWARD.name, names)
        self.assertIn(FINANCE_DELEGATION_HELPERS_FORWARD.name, names)
        self.assertLess(
            manifest["migrations"].index(SCHEMA_PARITY.name),
            manifest["migrations"].index(COMPANY_SEAL_DIMENSION_FORWARD.name),
        )
        self.assertLess(
            manifest["migrations"].index(COMPANY_SEAL_DIMENSION_FORWARD.name),
            manifest["migrations"].index(FUNCTION_TYPE_RESOLUTION_FORWARD.name),
        )
        self.assertLess(
            manifest["migrations"].index(FUNCTION_TYPE_RESOLUTION_FORWARD.name),
            manifest["migrations"].index(FINANCE_DELEGATION_HELPERS_FORWARD.name),
        )
        self.assertLess(
            manifest["migrations"].index(FINANCE_DELEGATION_HELPERS_FORWARD.name),
            manifest["migrations"].index(EDITOR_IMMUTABLE_PROMOTION.name),
        )
        self.assertNotIn(RECOVERY.name, names)
        self.assertFalse((MIGRATIONS / RECOVERY.name).exists())
        for storage_path in (STORAGE_BASE, STORAGE_HARDEN, STORAGE_POLICY_ALLOWLIST):
            self.assertTrue(storage_path.exists())
            self.assertNotIn(storage_path.name, names)
            self.assertFalse((MIGRATIONS / storage_path.name).exists())

    def test_recovery_defines_every_live_only_runtime_table(self) -> None:
        sql = RECOVERY.read_text(encoding="utf-8").lower()
        required = {
            "inbound_document_attachments",
            "internal_dispatches",
            "internal_dispatch_recipients",
            "internal_dispatch_replies",
            "internal_dispatch_logs",
            "official_document_stamp_positions",
            "official_document_text_overlays",
            "official_document_editor_revisions",
            "official_document_editor_assets",
            "official_document_rejection_jobs",
            "official_document_dispatch_events",
            "official_document_archive_exports",
            "official_workflow_delegations",
        }
        for table in required:
            self.assertRegex(sql, rf"create table if not exists public\.{table}\b")
            self.assertIn(f"alter table public.{table} enable row level security", sql)

    def test_forward_schema_parity_defines_runtime_tables_rpcs_and_live_columns(self) -> None:
        sql = SCHEMA_PARITY.read_text(encoding="utf-8").lower()
        required_tables = {
            "official_document_stamp_positions",
            "official_document_text_overlays",
            "official_document_editor_revisions",
            "official_document_editor_assets",
            "official_document_rejection_jobs",
            "official_document_dispatch_events",
            "official_document_archive_exports",
            "official_workflow_delegations",
        }
        required_rpcs = {
            "edoc_create_official_workflow_delegation",
            "edoc_revoke_official_workflow_delegation",
            "edoc_create_official_document_dispatch_record",
            "edoc_complete_official_document_dispatch",
            "edoc_apply_official_document_correction",
            "edoc_finalize_official_document_resubmit",
            "edoc_claim_official_document_approval_v3",
            "edoc_claim_official_document_rejection_v3",
            "edoc_complete_official_document_stamp",
            "edoc_fail_official_document_stamp",
            "edoc_resolve_portal_finance_user",
            "edoc_register_official_archive_export",
        }
        required_columns = {
            "workflow_template_key",
            "requires_stamp",
            "correction_missing_items_json",
            "workflow_generation",
            "decision_actor_user_id",
            "decision_evidence_json",
            "principal_actor_id",
            "stamp_request_id",
            "locked_editor_revision_id",
            "prepared_file_id",
            "editor_manifest_sha256",
            "claim_expires_at",
            "claim_attempt_count",
        }
        for table in required_tables:
            self.assertRegex(sql, rf"create table if not exists public\.{table}\b")
        for function in required_rpcs:
            self.assertRegex(sql, rf"create or replace function public\.{function}\b")
        for column in required_columns:
            self.assertIn(f"add column if not exists {column}", sql)
        self.assertIn("official_document_steps_generation_order_key", sql)
        self.assertIn("official_documents_stamped_file_id_fkey", sql)
        self.assertIn("official_document_files_stamp_request_id_fkey", sql)
        self.assertIn("official_document_dispatch_records_document_key", sql)
        self.assertNotIn("drop index", sql)

    def test_company_seal_dimension_forward_adds_rpc_rowtype_fields_without_fabricating_legacy_metadata(self) -> None:
        migration_sql = COMPANY_SEAL_DIMENSION_FORWARD.read_text(encoding="utf-8").lower()
        recovery_sql = RECOVERY.read_text(encoding="utf-8").lower()
        fresh_smoke_sql = FRESH_BOOTSTRAP_SMOKE.read_text(encoding="utf-8").lower()
        cutover_sql = CUTOVER_CHECKS.read_text(encoding="utf-8").lower()
        expected_columns = {
            "pixel_width": "integer",
            "pixel_height": "integer",
            "source_aspect_ratio": "numeric",
            "render_width_mm": "numeric",
            "render_height_mm": "numeric",
            "dimension_policy_version": "text",
            "dimension_validated": "boolean not null default false",
        }

        for sql in (migration_sql, recovery_sql):
            with self.subTest(contract="migration_or_recovery"):
                self.assertNotIn("pg_catalog.coalesce", sql)
                for column, definition in expected_columns.items():
                    self.assertIn(
                        f"add column if not exists {column} {definition}",
                        sql,
                    )
                self.assertIn("set is_current = false", sql)
                self.assertIn("seal_file.is_current is true", sql)
                self.assertIn("from public.company_seals as seal", sql)
                self.assertIn(
                    "seal_file.dimension_policy_version is distinct from\n       "
                    "'institution-seal-v2-calibrated'",
                    sql,
                )
                self.assertIn("public.edoc_company_seal_dimensions_are_valid(", sql)
                self.assertIn("seal_file.dimension_validated", sql)
                self.assertIn("set dimension_validated = false", sql)
                self.assertIn("where dimension_validated is null", sql)
                self.assertIn("alter column dimension_validated set default false", sql)
                self.assertIn("alter column dimension_validated set not null", sql)
                for column in (
                    "pixel_width",
                    "pixel_height",
                    "source_aspect_ratio",
                    "render_width_mm",
                    "render_height_mm",
                    "dimension_policy_version",
                ):
                    self.assertNotRegex(sql, rf"set\s+{column}\s*=")
                self.assertNotRegex(sql, r"set\s+dimension_validated\s*=\s*true")

        self.assertLess(
            recovery_sql.index("add column if not exists pixel_width"),
            recovery_sql.index(
                "create or replace function public.edoc_company_seal_dimensions_are_valid"
            ),
        )
        self.assertIn("fresh_bootstrap_company_seal_dimension_columns_missing", fresh_smoke_sql)
        self.assertIn("fresh_bootstrap_company_seal_dimension_guard_invalid", fresh_smoke_sql)
        for column, definition in expected_columns.items():
            expected_data_type = definition.split()[0]
            expected_nullable = "false" if column == "dimension_validated" else "true"
            self.assertIn(
                f"('company_seal_files', '{column}', '{expected_data_type}', {expected_nullable})",
                cutover_sql,
            )
        if parse_sql is not None:
            parse_sql(migration_sql)

    def test_official_document_function_type_resolution_is_explicit_and_forward_compatible(self) -> None:
        schema_sql = SCHEMA_PARITY.read_text(encoding="utf-8").lower()
        recovery_sql = RECOVERY.read_text(encoding="utf-8").lower()
        inbound_sql = INBOUND_MUTATION_CONTRACT.read_text(encoding="utf-8").lower()
        forward_sql = FUNCTION_TYPE_RESOLUTION_FORWARD.read_text(
            encoding="utf-8"
        ).lower()
        fresh_smoke_sql = FRESH_BOOTSTRAP_SMOKE.read_text(encoding="utf-8").lower()
        cutover_sql = CUTOVER_CHECKS.read_text(encoding="utf-8").lower()

        validator_signature = (
            "edoc_private.validate_official_document_decision_evidence("
            "text,text,text,text,text,jsonb)"
        )
        validator_definition = (
            "create or replace function "
            "edoc_private.validate_official_document_decision_evidence("
        )

        for sql in (schema_sql, recovery_sql):
            with self.subTest(contract="schema_or_recovery"):
                self.assertIn(
                    "p_position_ids->>((v_position_index - 1)::integer)",
                    sql,
                )
                self.assertIn(
                    "p_overlay_ids->>((v_overlay_index - 1)::integer)",
                    sql,
                )
                self.assertIn("'approve'::text,", sql)
                self.assertIn("'reject'::text,", sql)
                self.assertIn(validator_definition, sql)
                self.assertIn("security definer\n set search_path to ''", sql)
                self.assertIn("for share", sql)
                for evidence_marker in (
                    "official_document_source_evidence_mismatch",
                    "official_document_prepared_evidence_mismatch",
                    "official_document_attachment_manifest_mismatch",
                    "official_document_review_acknowledgements_required",
                    "official_document_review_access_required",
                    "official_document_rejection_reason_category_required",
                    "official_document_rejection_missing_items_invalid",
                    "official_document_correction_due_date_invalid",
                ):
                    self.assertIn(evidence_marker, sql)
                self.assertIn(
                    f"revokeallonfunction{validator_signature}"
                    "frompublic,anon,authenticated,service_role",
                    re.sub(r"\s+", "", sql),
                )

        self.assertIn("v_now timestamptz := clock_timestamp();", inbound_sql)
        self.assertNotIn(
            "v_now text := to_char(clock_timestamp(), 'yyyy-mm-dd hh24:mi:ss');",
            inbound_sql,
        )
        self.assertGreaterEqual(
            inbound_sql.count("to_char(v_now, 'yyyy-mm-dd hh24:mi:ss')"),
            2,
        )

        signature = "create or replace function public.edoc_mutate_inbound_document_v1("
        self.assertEqual(forward_sql.count(signature), 1)
        self.assertIn("set search_path = pg_catalog, extensions", forward_sql)
        self.assertIn("v_now timestamptz := clock_timestamp();", forward_sql)
        self.assertEqual(forward_sql.count("errcode = 'pt409'"), 7)
        self.assertNotIn("errcode = '40001'", forward_sql)
        self.assertGreaterEqual(
            forward_sql.count("to_char(v_now, 'yyyy-mm-dd hh24:mi:ss')"),
            2,
        )
        for marker in (
            "v_legacy_position constant text",
            "v_fixed_position constant text",
            "v_legacy_overlay constant text",
            "v_fixed_overlay constant text",
            "v_legacy_approve constant text",
            "v_fixed_approve constant text",
            "v_legacy_reject constant text",
            "v_fixed_reject constant text",
            "edoc_function_type_resolution_definition_drift",
            "edoc_function_type_resolution_rewrite_failed",
        ):
            self.assertIn(marker, forward_sql)
        self.assertEqual(forward_sql.count(validator_definition), 1)
        self.assertLess(
            forward_sql.index(validator_definition),
            forward_sql.index("do $official_document_function_type_resolution$"),
        )
        self.assertIn(
            f"alterfunction{validator_signature}ownertopostgres",
            re.sub(r"\s+", "", forward_sql),
        )
        self.assertIn(
            f"revokeallonfunction{validator_signature}"
            "frompublic,anon,authenticated,service_role",
            re.sub(r"\s+", "", forward_sql),
        )
        self.assertIn("notify pgrst, 'reload schema'", forward_sql)
        self.assertIn(validator_signature, fresh_smoke_sql)
        self.assertIn(
            "fresh_bootstrap_decision_evidence_validator_security_invalid",
            fresh_smoke_sql,
        )
        self.assertIn(validator_signature, cutover_sql)
        self.assertIn("service_role_execute_revoked", cutover_sql)

        if parse_sql is not None:
            parse_sql(INBOUND_MUTATION_CONTRACT.read_text(encoding="utf-8"))
            parse_sql(FUNCTION_TYPE_RESOLUTION_FORWARD.read_text(encoding="utf-8"))
        if parse_plpgsql is not None:
            parse_plpgsql(
                FUNCTION_TYPE_RESOLUTION_FORWARD.read_text(encoding="utf-8")
            )

    def test_finance_delegation_helpers_fail_closed_and_remain_private(self) -> None:
        schema_sql = SCHEMA_PARITY.read_text(encoding="utf-8").lower()
        recovery_sql = RECOVERY.read_text(encoding="utf-8").lower()
        forward_sql = FINANCE_DELEGATION_HELPERS_FORWARD.read_text(
            encoding="utf-8"
        ).lower()
        fresh_smoke_sql = FRESH_BOOTSTRAP_SMOKE.read_text(encoding="utf-8").lower()
        cutover_sql = CUTOVER_CHECKS.read_text(encoding="utf-8").lower()
        profile_signature = "edoc_private.assert_finance_delegation_profile(text)"
        manage_signature = (
            "edoc_private.finance_actor_has_delegation_manage(jsonb)"
        )

        for sql in (schema_sql, recovery_sql, forward_sql):
            with self.subTest(contract="schema_recovery_or_forward"):
                self.assertIn(
                    "function edoc_private.assert_finance_delegation_profile(",
                    sql,
                )
                self.assertIn(
                    "function edoc_private.finance_actor_has_delegation_manage(",
                    sql,
                )
                for identity_marker in (
                    "account_source",
                    "auth_user_id",
                    "finance_employee_id",
                    "company_id",
                    "logging_role_key",
                    "job_level",
                    "official_workflow_delegation_finance_actor_ineligible",
                ):
                    self.assertIn(identity_marker, sql)
                for role_marker in (
                    "admin_director",
                    "department_head",
                    "section_chief",
                    "staff",
                ):
                    self.assertIn(role_marker, sql)
                compact = re.sub(r"\s+", "", sql)
                self.assertIn(
                    f"revokeallonfunction{profile_signature}"
                    "frompublic,anon,authenticated,service_role",
                    compact,
                )
                self.assertIn(
                    f"revokeallonfunction{manage_signature}"
                    "frompublic,anon,authenticated,service_role",
                    compact,
                )

        compact_forward = re.sub(r"\s+", "", forward_sql)
        self.assertNotIn("pg_catalog.coalesce", forward_sql)
        self.assertIn(
            f"alterfunction{profile_signature}ownertopostgres",
            compact_forward,
        )
        self.assertIn(
            f"alterfunction{manage_signature}ownertopostgres",
            compact_forward,
        )
        self.assertIn("security definer", forward_sql)
        self.assertIn("set search_path = ''", forward_sql)
        self.assertIn("finance_actor_has_delegation_manage", fresh_smoke_sql)
        self.assertIn(
            "fresh_bootstrap_finance_delegation_helper_security_invalid",
            fresh_smoke_sql,
        )
        self.assertIn(
            "fresh_bootstrap_finance_delegation_manage_guard_invalid",
            fresh_smoke_sql,
        )
        self.assertIn(profile_signature, cutover_sql)
        self.assertIn(manage_signature, cutover_sql)

        if parse_sql is not None:
            parse_sql(FINANCE_DELEGATION_HELPERS_FORWARD.read_text(encoding="utf-8"))
        if parse_plpgsql is not None:
            parse_plpgsql(
                FINANCE_DELEGATION_HELPERS_FORWARD.read_text(encoding="utf-8")
            )

    def test_recovery_defines_backend_rpc_inventory_and_atomic_contracts(self) -> None:
        sql = RECOVERY.read_text(encoding="utf-8").lower()
        required = {
            "edoc_create_official_workflow_delegation",
            "edoc_revoke_official_workflow_delegation",
            "edoc_create_company_seal_file_version",
            "edoc_set_current_company_seal_file",
            "edoc_create_official_document_dispatch_record",
            "edoc_complete_official_document_dispatch",
            "edoc_apply_official_document_correction",
            "edoc_finalize_official_document_resubmit",
            "edoc_claim_official_document_approval_v3",
            "edoc_claim_official_document_rejection_v3",
            "edoc_cancel_official_document",
            "edoc_complete_official_document_stamp",
            "edoc_fail_official_document_stamp",
            "edoc_resolve_portal_finance_user",
            "edoc_register_official_archive_export",
            "edoc_commit_official_document_submission",
            "edoc_finalize_editor_asset_v2",
        }
        for function in required:
            self.assertRegex(sql, rf"create or replace function public\.{function}\b")

        for function in (
            "edoc_commit_official_document_submission",
            "edoc_finalize_editor_asset_v2",
        ):
            self.assertIn(
                f"revoke all on function public.{function}(jsonb) from public, anon, authenticated",
                sql,
            )
            self.assertIn(
                f"grant execute on function public.{function}(jsonb) to service_role",
                sql,
            )

        self.assertIn("pg_catalog.lower(v_asset.expected_sha256)", sql)
        self.assertIn("sha256 = pg_catalog.upper(v_expected_sha)", sql)
        self.assertIn("v_snapshot.source_id is distinct from v_document_id", sql)
        self.assertIn("v_snapshot.snapshot_json->>'step_id'", sql)
        self.assertIn("current production stores these workflow timestamps as canonical text", sql)
        self.assertIn("v_expected_updated_at text", sql)
        self.assertIn("v_submitted_at text", sql)

    def test_atomic_rpc_forward_migration_is_small_and_service_only(self) -> None:
        sql = ATOMIC_FORWARD.read_text(encoding="utf-8").lower()
        self.assertNotRegex(sql, r"\b(create|alter|drop)\s+table\b")
        self.assertEqual(sql.count("create or replace function public.edoc_"), 2)
        for function in (
            "edoc_commit_official_document_submission",
            "edoc_finalize_editor_asset_v2",
        ):
            self.assertIn(f"create or replace function public.{function}(p_request jsonb)", sql)
            self.assertIn(
                f"revoke all on function public.{function}(jsonb) from public, anon, authenticated",
                sql,
            )
            self.assertIn(
                f"grant execute on function public.{function}(jsonb) to service_role",
                sql,
            )
        self.assertIn("notify pgrst, 'reload schema'", sql)
        self.assertIn("current production stores these workflow timestamps as canonical text", sql)
        self.assertIn("v_expected_updated_at text", sql)
        self.assertIn("v_submitted_at text", sql)
        if parse_sql is not None:
            self.assertEqual(
                [type(statement.stmt).__name__ for statement in parse_sql(sql)],
                [
                    "CreateFunctionStmt",
                    "GrantStmt",
                    "GrantStmt",
                    "CreateFunctionStmt",
                    "GrantStmt",
                    "GrantStmt",
                    "NotifyStmt",
                ],
            )

    def test_exposed_rpcs_do_not_leave_manual_serialization_failures_retryable(self) -> None:
        hardening = BUSINESS_CONFLICT_FORWARD.read_text(encoding="utf-8").lower()
        expected = {
            "public.edoc_mutate_inbound_document_v1(text,text,text,text,text,bigint,jsonb)": 7,
            "public.edoc_claim_official_document_approval(text,text,text,text)": 1,
            "public.edoc_claim_official_document_rejection(text,text,text,text)": 1,
            "public.edoc_claim_official_document_approval_v2(text,text,text,text,text,jsonb)": 1,
            "public.edoc_claim_official_document_rejection_v2(text,text,text,text,text,jsonb)": 2,
            "public.edoc_revoke_official_workflow_delegation(text,text)": 1,
            "public.edoc_complete_official_document_dispatch(text,text,text,text,text,text,text,text,text,text)": 2,
            "public.edoc_claim_official_document_approval_v3(text,text,text,text,text,jsonb)": 1,
            "public.edoc_commit_official_document_submission(jsonb)": 2,
            "public.edoc_finalize_editor_asset_v2(jsonb)": 3,
        }
        expected_unique_business_conflicts = {
            "public.edoc_apply_finance_organization_projection_v2(text,text,bigint,text,text,jsonb)": 2,
            "public.edoc_create_official_document_dispatch_record(text,text)": 1,
            "public.edoc_finalize_official_document_resubmit(text,text,text,timestamp with time zone,text,text,text,text,text)": 2,
            "public.edoc_commit_official_document_submission(jsonb)": 2,
            "public.edoc_finalize_editor_asset_v2(jsonb)": 5,
        }
        expected_qualified_coalesce_rewrites = {
            "public.edoc_apply_official_document_correction(text,text,text,jsonb,text,jsonb,jsonb,text,jsonb,jsonb,text,text,text,text,text,text,jsonb,text,text)": 15,
            "public.edoc_finalize_official_document_resubmit(text,text,text,timestamp with time zone,text,text,text,text,text)": 7,
            "edoc_private.capture_official_dispatch_event_v1()": 3,
        }
        expected_qualified_nullif_rewrites = {
            "public.edoc_apply_official_document_correction(text,text,text,jsonb,text,jsonb,jsonb,text,jsonb,jsonb,text,text,text,text,text,text,jsonb,text,text)": 1,
            "edoc_private.capture_official_dispatch_event_v1()": 2,
        }

        # Find every public function whose source manually labels a permanent
        # business conflict as PostgreSQL serialization_failure.  A newly
        # introduced offender must be explicitly reviewed and added to the
        # fail-closed forward migration instead of silently reaching PostgREST.
        offenders = set()
        function_pattern = re.compile(
            r"create\s+(?:or\s+replace\s+)?function\s+public\.([a-z0-9_]+)\s*"
            r"\(([^)]*)\).*?\bas\s+(\$[a-z0-9_]*\$)(.*?)\3\s*;",
            re.IGNORECASE | re.DOTALL,
        )
        manual_retry = re.compile(
            r"(?:errcode\s*=\s*|sqlstate\s+)['\"]40001['\"]",
            re.IGNORECASE,
        )
        manual_unique_business_conflict = re.compile(
            r"(?:errcode\s*=\s*|sqlstate\s+)['\"]23505['\"]",
            re.IGNORECASE,
        )
        recovery = RECOVERY.read_text(encoding="utf-8")
        unique_business_offenders = set()
        for migration in sorted(MIGRATIONS.glob("*.sql")):
            if migration == BUSINESS_CONFLICT_FORWARD:
                continue
            source = migration.read_text(encoding="utf-8")
            for match in function_pattern.finditer(source):
                body = match.group(4)
                if not manual_retry.search(body) and not manual_unique_business_conflict.search(body):
                    continue
                argument_types = []
                for argument in match.group(2).split(","):
                    without_default = re.split(
                        r"\s+default\s+|\s+=\s+",
                        argument.strip(),
                        maxsplit=1,
                        flags=re.IGNORECASE,
                    )[0]
                    tokens = without_default.split()
                    if tokens and tokens[0].lower() in {"in", "out", "inout", "variadic"}:
                        tokens = tokens[1:]
                    if len(tokens) < 2:
                        self.fail(f"manual_conflict_signature_unparseable:{match.group(1)}")
                    argument_types.append(" ".join(tokens[1:]).lower())
                signature = (
                    f"public.{match.group(1).lower()}({','.join(argument_types)})"
                )
                if manual_retry.search(body):
                    offenders.add(signature)
                if manual_unique_business_conflict.search(body):
                    unique_business_offenders.add(signature)

        self.assertEqual(offenders, set(expected))
        self.assertEqual(
            unique_business_offenders,
            set(expected_unique_business_conflicts),
        )
        self.assertNotRegex(recovery, manual_retry)
        self.assertNotRegex(recovery, manual_unique_business_conflict)
        self.assertIn("errcode = 'PT409'", recovery)
        self.assertNotRegex(hardening, r"\b(create|alter|drop)\s+table\b")
        self.assertIn("pg_catalog.pg_get_functiondef", hardening)
        self.assertIn("v_retry_code constant text := '''40001'''", hardening)
        self.assertIn("v_unique_code constant text := '''23505'''", hardening)
        self.assertIn("v_conflict_code constant text := '''pt409'''", hardening)
        self.assertIn(
            "v_qualified_coalesce constant text := 'pg_catalog.coalesce('",
            hardening,
        )
        self.assertIn(
            "v_qualified_nullif constant text := 'pg_catalog.nullif('",
            hardening,
        )
        self.assertIn("edoc_business_conflict_rpc_definition_drift", hardening)
        self.assertIn("notify pgrst, 'reload schema'", hardening)
        for signature, count in expected.items():
            self.assertIn(f"('{signature}', {count})", hardening)
        for signature, count in expected_unique_business_conflicts.items():
            self.assertIn(f"('{signature}', {count})", hardening)
        for signature, count in expected_qualified_coalesce_rewrites.items():
            self.assertIn(f"('{signature}', {count})", hardening)
        for signature, count in expected_qualified_nullif_rewrites.items():
            self.assertIn(f"('{signature}', {count})", hardening)
        self.assertNotIn("pg_catalog.coalesce(", recovery.lower())
        self.assertNotIn("pg_catalog.nullif(", recovery.lower())
        if parse_sql is not None:
            parse_sql(hardening)
        if parse_plpgsql is not None:
            parse_plpgsql(hardening)

    def test_fk_forward_migration_matches_confirmed_edoc_advisor_set(self) -> None:
        sql = FK_INDEX_FORWARD.read_text(encoding="utf-8").lower()
        self.assertNotRegex(sql, r"\b(drop|alter|create)\s+table\b")
        self.assertNotRegex(sql, r"\bon\s+public\.cms")
        self.assertNotIn("drop index", sql)
        self.assertEqual(sql.count("create index if not exists"), 40)
        if parse_sql is not None:
            statements = parse_sql(sql)
            self.assertEqual(len(statements), 40)
            self.assertEqual({type(statement.stmt).__name__ for statement in statements}, {"IndexStmt"})
        for relation in (
            "public.inbound_document_attachments(file_object_id)",
            "public.internal_dispatches(official_document_id)",
            "public.internal_dispatch_replies(recipient_id)",
            "public.internal_dispatch_replies(attachment_file_id)",
            "public.official_document_archive_exports(requested_by)",
            "public.official_document_approval_logs(step_id)",
            "public.official_document_approval_logs(file_id)",
            "public.official_document_files(file_object_id)",
            "public.official_document_stamp_positions(seal_id)",
            "public.official_workflow_delegations(delegate_user_id)",
        ):
            self.assertIn(relation, sql)

    def test_dedicated_storage_migrations_are_storage_only_and_hardened(self) -> None:
        base = STORAGE_BASE.read_text(encoding="utf-8").lower()
        harden = STORAGE_HARDEN.read_text(encoding="utf-8").lower()
        policy_allowlist = STORAGE_POLICY_ALLOWLIST.read_text(encoding="utf-8").lower()
        checks = STORAGE_CUTOVER_CHECKS.read_text(encoding="utf-8").lower()
        for sql in (base, harden, policy_allowlist):
            executable = "\n".join(
                line for line in sql.splitlines() if not line.lstrip().startswith("--")
            )
            self.assertNotIn("public.", executable)
            self.assertNotRegex(executable, r"\b(auth|vault|realtime)\.")

        self.assertIn("'application/zip'", harden)
        self.assertIn("array_remove(allowed_mime_types, 'image/svg+xml')", harden)
        self.assertIn("roles && array['public', 'anon', 'authenticated']::name[]", policy_allowlist)
        self.assertIn("drop policy if exists %i on storage.objects", policy_allowlist)
        self.assertNotIn("policyname in (", checks)
        self.assertIn("roles && array['public', 'anon', 'authenticated']::name[]", checks)
        self.assertIn("dedicated_storage_unexpected_bucket_count", checks)
        self.assertIn("dedicated_storage_project_not_isolated", checks)
        self.assertIn("from auth.users", checks)
        self.assertIn("dependency_row.deptype = 'e'", checks)

    def test_notification_bootstrap_does_not_fake_external_readiness(self) -> None:
        sql = NOTIFICATIONS.read_text(encoding="utf-8").lower()
        self.assertIn("disabled_pending_credentials", sql)
        self.assertIn("pending:no_credential_configured", sql)
        self.assertNotRegex(sql, r"(?i)(sk-proj-|service_role_key|bearer\s+[a-z0-9_.-]+)")
        self.assertGreaterEqual(sql.count("'待驗證'"), 3)
        self.assertIn("when public.notification_channel_credentials.status in ('有效', '即將到期')", sql)

    def test_seed_is_empty_and_cleanup_is_exact_identifier_only(self) -> None:
        seed = (ROOT / "supabase" / "seed.sql").read_text(encoding="utf-8")
        cleanup = CLEANUP.read_text(encoding="utf-8")
        self.assertIn("edoc_seed_is_intentionally_empty", seed)
        self.assertNotRegex(seed, r"\b(USR-|DOC-|NTF-|CERT-|ACC-DEV-)\w+")
        self.assertNotRegex(seed.lower(), r"\binsert\s+into\s+public\.")
        self.assertNotRegex(cleanup.lower(), r"\b(like|similar to|regexp|~\*?)\b")
        for exact_id in (
            "USR-001",
            "DOC-IN-1140522-00018",
            "DOC-ADMIN-1140523-001",
            "NTF-001",
            "CERT-SEAL-001",
        ):
            self.assertIn(exact_id, cleanup)
        self.assertIn("retention_until = current_date", cleanup.lower())
        self.assertIn("工作區範例", cleanup)
        self.assertIn("admin_demo_document_signature_mismatch", cleanup)
        self.assertIn("admin_demo_document_has_reference", cleanup)
        self.assertIn("pg_catalog.pg_constraint", cleanup)
        cutover = CUTOVER_CHECKS.read_text(encoding="utf-8")
        self.assertIn("DOC-ADMIN-1140523-001", cutover)
        for object_type in (
            "attachments",
            "attachment_security",
            "exchange_tasks",
            "document_acl",
            "document_acl_events",
            "seal_applications",
            "recipients",
        ):
            self.assertIn(f"select '{object_type}', count(*)", cutover)
        self.assertIn("forced_private_chain_state", cutover)

    def test_demo_cleanup_fails_closed_on_fixture_drift_and_all_references(self) -> None:
        cleanup = CLEANUP.read_text(encoding="utf-8").lower()

        # Catalog-driven guards cover composite/alternate-key FKs. After all
        # signed fixture deletes, one bounded public-schema pass checks every
        # retired ID against denormalized scalar history references.
        self.assertIn("pg_temp.edoc_demo_assert_no_fk_references", cleanup)
        self.assertIn("constraint_row.confrelid = p_parent_relation", cleanup)
        self.assertIn("pg_catalog.string_agg", cleanup)
        self.assertIn("pg_temp.edoc_demo_assert_no_exact_scalar_references", cleanup)
        self.assertIn("p_fixture_ids text[]", cleanup)
        self.assertIn("namespace_row.nspname = 'public'", cleanup)
        self.assertIn(
            "attribute_row.atttypid = 'pg_catalog.text'::pg_catalog.regtype",
            cleanup,
        )
        self.assertIn("pg_catalog.right(attribute_row.attname, 3) = '_id'", cleanup)
        self.assertIn("table_row.%i = any($1)", cleanup)
        self.assertIn("group by namespace_row.nspname, relation_row.relname", cleanup)
        self.assertIn("lock table %i.%i in share row exclusive mode", cleanup)
        self.assertIn("demo_cleanup_has_non_fk_reference", cleanup)
        self.assertIn("set local statement_timeout = '120s'", cleanup)
        self.assertIn("set local lock_timeout = '5s'", cleanup)
        self.assertTrue(cleanup.startswith("-- remove only"))
        self.assertRegex(cleanup, r"(?s)begin;.*commit;\s*$")
        self.assertEqual(
            cleanup.count(
                "perform pg_temp.edoc_demo_assert_no_exact_scalar_references("
            ),
            1,
        )

        # Historical seed departments must match the seed, not a later UI
        # normalization migration.
        self.assertGreaterEqual(cleanup.count("department = '總管理處'"), 2)
        self.assertIn("department = '居家照顧課'", cleanup)

        # Every deterministic document/attachment default introduced after the
        # seed is part of the immutable cleanup signature.
        for fragment in (
            "retention_policy_code = 'edoc-std-07y'",
            "retention_years = 7",
            "retention_until is null",
            "retention_policy_code = 'edoc-seal-15y'",
            "retention_years = 15",
            "pg_catalog.make_interval(years => retention_years)",
            "disposition_status = '保存中'",
            "disposed_at is null",
            "confidentiality_scope = '一般'",
            "company_name = '歲悅長照股份有限公司'",
            "seal_plan_json = '{}'",
            "metadata_json = '{}'",
            "scan_status = '雜湊通過'",
            "sensitive_hits_json = '[\"身分證\",\"電話\"]'::jsonb",
            "last_accessed_by is null",
            "last_accessed_at is null",
            "retry_count = 1",
            "next_check_at = '2026-05-23 09:00'",
            "expires_at is null",
        ):
            self.assertIn(fragment, cleanup)

        for object_name in (
            "attachment_security",
            "attachment",
            "exchange_task",
            "acl_event",
            "acl",
            "seal_application",
            "document",
        ):
            self.assertIn(f"legacy_demo_{object_name}_has_fk_reference", cleanup)
            self.assertIn(f"legacy_demo_{object_name}_delete_failed", cleanup)

        # The seed seal row must remain untouched if any workflow snapshot has
        # recorded it, even though that historical table has no FK constraint.
        self.assertIn("approval_step_actor_snapshots", cleanup)
        self.assertIn("seal_application_id = 'useal-seed-001'", cleanup)
        self.assertIn("source_id = 'useal-seed-001'", cleanup)
        self.assertIn("legacy_demo_seal_application_has_actor_snapshot", cleanup)
        for fragment in (
            "stamp_no is null",
            "pdf_before_version_id is null",
            "pdf_after_version_id is null",
            "approved_at is null",
            "signature_id is null",
            "provider_status is null",
            "failure_reason is null",
            "evidence_json is null",
            "updated_at is null",
            "application_type = 'official_document'",
            "company_name = '歲悅股份有限公司'",
            "stamp_positions_json = '[]'::jsonb",
            "approval_snapshot_json = '{}'::jsonb",
            "current_step_no = 1",
            "notification_id is null",
        ):
            self.assertIn(fragment, cleanup)

        # Notification rules are signatures first, catalog guards second, and
        # an asserted delete last; they are never removed by identifier alone.
        self.assertIn("do $cleanup_demo_notification_rules$", cleanup)
        self.assertIn("demo_notification_rule_signature_mismatch", cleanup)
        self.assertIn("demo_notification_rule_has_fk_reference", cleanup)
        self.assertIn("demo_notification_rule_delete_failed", cleanup)
        self.assertRegex(cleanup, r"nrule-001[^\n]+status = '啟用'")
        for rule_id in range(2, 6):
            self.assertRegex(cleanup, rf"nrule-00{rule_id}[^\n]+status = '停用'")
        for rule_id in range(1, 6):
            self.assertIn(f"nrule-00{rule_id}", cleanup)

        # Account/device fixtures also fail closed when their activity state or
        # a catalog/non-FK reference differs from the retired seed.
        self.assertIn("last_seen_at = created_at", cleanup)
        self.assertIn("last_login_at is not null", cleanup)
        self.assertIn("finance_source_revision is distinct from 0", cleanup)
        self.assertIn("demo_trusted_device_delete_failed", cleanup)
        self.assertIn("demo_account_has_fk_reference", cleanup)

    def test_demo_document_cleanup_matches_predecessor_retention_trigger(self) -> None:
        cleanup = CLEANUP.read_text(encoding="utf-8").lower()
        predecessor = (
            MIGRATIONS / "202605230010_formal_database_security_policy.sql"
        ).read_text(encoding="utf-8").lower()

        self.assertIn("create trigger trg_documents_set_retention", predecessor)
        self.assertIn("before insert or update of security_level, status, direction, created_at, retention_until", predecessor)
        self.assertIn("or new.direction = '發文'", predecessor)
        self.assertIn("update public.documents\nset retention_until = null", predecessor)

        # The trigger runs before cleanup: the inbound fixture is seven-year
        # standard retention, while all three outbound fixtures are 15-year
        # seal retention, computed from each row's generated created_at date.
        self.assertEqual(cleanup.count("retention_policy_code = 'edoc-std-07y'"), 1)
        self.assertEqual(cleanup.count("retention_policy_code = 'edoc-seal-15y'"), 3)
        self.assertEqual(cleanup.count("retention_years = 7"), 1)
        self.assertEqual(cleanup.count("retention_years = 15"), 3)
        self.assertEqual(cleanup.count("updated_at = created_at"), 4)
        self.assertEqual(
            cleanup.count(
                "retention_until = (pg_catalog.left(created_at, 10)::date + "
                "pg_catalog.make_interval(years => retention_years))::date"
            ),
            4,
        )

    def test_audit_hash_forward_hardening_is_serialized_and_fixed_path(self) -> None:
        sql = AUDIT_HASH_HARDENING.read_text(encoding="utf-8").lower()
        self.assertIn("create table if not exists edoc_private.audit_log_chain_heads", sql)
        self.assertIn(
            "create table if not exists edoc_private.audit_log_chain_transitions",
            sql,
        )
        self.assertIn("lock table public.audit_logs in share row exclusive mode", sql)
        self.assertIn("create index if not exists idx_audit_logs_chain_parent", sql)
        self.assertIn("edoc_audit_chain_parent_index_invalid", sql)
        self.assertIn("index_row.indisvalid", sql)
        self.assertIn("index_row.indisready", sql)
        self.assertIn("index_row.indkey[0]", sql)
        self.assertIn("index_row.indkey[1]", sql)
        self.assertRegex(sql, r"begin;\s+set local lock_timeout")
        self.assertIn("set local lock_timeout = '5s'", sql)
        self.assertIn("set local statement_timeout = '120s'", sql)
        self.assertRegex(sql, r"notify pgrst, 'reload schema';\s+commit;")
        self.assertIn("edoc_audit_v1_chain_invalid", sql)
        self.assertIn("v_walked <> v_total", sql)
        self.assertIn("edoc_audit_pretransition_version_invalid", sql)
        self.assertIn("edoc_audit_v1_fork_requires_manual_attestation", sql)
        self.assertIn("join public.users linked_user", sql)
        self.assertNotIn(
            "from public.module_account_links\n      where finance_tenant_id",
            sql,
        )
        self.assertIn("edoc-audit-v1-set-commitment-v1", sql)
        self.assertIn("sha256-sorted-entry-hash-set-v1-c-collation", sql)
        self.assertIn('entry_hash collate "c"', sql)
        self.assertIn("v_terminals < 1", sql)
        self.assertIn("audit_row.immutable is distinct from true", sql)
        self.assertIn("enable row level security", sql)
        self.assertIn("force row level security", sql)
        self.assertIn("pg_catalog.pg_advisory_xact_lock", sql)
        self.assertIn("for update", sql)
        self.assertIn("where audit_row.id = new.id", sql)
        self.assertIn("new.chain_version := 2", sql)
        self.assertIn("new.previous_hash := coalesce(v_previous_hash, 'genesis')", sql)
        self.assertIn("extensions.digest(", sql)
        self.assertGreaterEqual(sql.count("set search_path = ''"), 2)
        self.assertIn("security definer", sql)
        self.assertIn(
            "revoke all on public.audit_log_chain_check from public, anon, authenticated",
            sql,
        )
        self.assertIn("grant select on public.audit_log_chain_check to service_role", sql)
        self.assertIn(
            "set search_path = pg_catalog, extensions",
            sql,
        )
        self.assertIn(
            "alter function public.edoc_mutate_inbound_document_v1",
            sql,
        )
        self.assertIn("extensions.gen_random_bytes(integer)", sql)
        self.assertNotIn("update public.audit_logs", sql)
        self.assertIn(
            "before update or delete on edoc_private.audit_log_chain_transitions",
            sql,
        )
        self.assertIn(
            "before truncate on edoc_private.audit_log_chain_transitions",
            sql,
        )
        self.assertIn(
            "revoke all on table edoc_private.audit_log_chain_heads\n  from public, anon, authenticated, service_role",
            sql,
        )
        self.assertIn(
            "revoke all on table edoc_private.audit_log_chain_transitions\n  from public, anon, authenticated, service_role",
            sql,
        )
        cutover = CUTOVER_CHECKS.read_text(encoding="utf-8").lower()
        self.assertIn("chain_continuity_valid", cutover)
        self.assertIn("private_head_matches_terminal", cutover)
        self.assertIn("source_transition_valid", cutover)
        self.assertIn("unsupported_version_count", cutover)
        self.assertGreaterEqual(
            cutover.count("chain_check.hash_valid is distinct from true"),
            2,
        )
        self.assertGreaterEqual(
            cutover.count("immutable is distinct from true"),
            2,
        )
        self.assertIn("v1_fork_count", cutover)
        self.assertIn("v2_fork_count", cutover)
        self.assertIn("version_order_violation_count", cutover)
        fresh = FRESH_BOOTSTRAP_SMOKE.read_text(encoding="utf-8").lower()
        self.assertIn("source_row_count = 7", fresh)
        self.assertIn("source_root_count = 1", fresh)
        self.assertIn("source_fork_count = (", fresh)
        self.assertIn("source_terminal_count = (", fresh)
        self.assertIn(
            "fresh_bootstrap_audit_transition_service_accessible",
            fresh,
        )
        self.assertIn(
            "fresh_bootstrap_audit_transition_truncate_accepted",
            fresh,
        )
        current_head_probe = (
            "select head_hash into strict v_expected_previous_hash"
        )
        first_chain_insert = "'aud-ci-fresh-chain-001'"
        self.assertIn(current_head_probe, fresh)
        self.assertIn(
            "v_first_previous_hash is distinct from v_expected_previous_hash",
            fresh,
        )
        self.assertLess(
            fresh.index(current_head_probe),
            fresh.index(first_chain_insert),
        )
        if parse_sql is not None:
            parse_sql(sql)

    def test_sql_files_have_balanced_dollar_quotes(self) -> None:
        for path in sorted(MIGRATIONS.glob("*.sql")) + sorted(STORAGE_MIGRATIONS.glob("*.sql")) + [RECOVERY]:
            sql = path.read_text(encoding="utf-8")
            tags = re.findall(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", sql)
            counts = {tag: tags.count(tag) for tag in set(tags)}
            self.assertFalse(
                {tag: count for tag, count in counts.items() if count % 2},
                f"unbalanced dollar quote in {path.name}",
            )

    @unittest.skipIf(parse_sql is None, "pglast is not installed")
    def test_new_sql_artifacts_parse_as_postgresql(self) -> None:
        paths = (
            RECOVERY,
            SCHEMA_PARITY,
            STORAGE_BASE,
            STORAGE_HARDEN,
            STORAGE_POLICY_ALLOWLIST,
            NOTIFICATIONS,
            CLEANUP,
            ATOMIC_FORWARD,
            FK_INDEX_FORWARD,
            AUDIT_HASH_HARDENING,
            FRESH_FINANCE_SENTINEL_CLEANUP,
            FUNCTION_TYPE_RESOLUTION_FORWARD,
            FINANCE_DELEGATION_HELPERS_FORWARD,
            EDITOR_IMMUTABLE_PROMOTION,
            EDITOR_STORAGE_PREFLIGHT,
            ROOT / "supabase" / "seed.sql",
            ROOT / "supabase" / "verification" / "production_cutover_checks.sql",
            FRESH_BOOTSTRAP_SMOKE,
            STORAGE_CUTOVER_CHECKS,
            AUDIT_CONCURRENCY_CHECKS,
        )
        for path in paths:
            with self.subTest(path=path.name):
                parse_sql(path.read_text(encoding="utf-8"))

        # parse_sql validates the outer DO/CREATE FUNCTION statement, but
        # PostgreSQL treats its dollar-quoted PL/pgSQL body as a string. Parse
        # the procedural layer for the audit cutover artifacts as well so a
        # malformed fail-closed guard cannot reach the database reset job.
        for path in (
            AUDIT_HASH_HARDENING,
            FRESH_FINANCE_SENTINEL_CLEANUP,
            FUNCTION_TYPE_RESOLUTION_FORWARD,
            FINANCE_DELEGATION_HELPERS_FORWARD,
            EDITOR_IMMUTABLE_PROMOTION,
            EDITOR_STORAGE_PREFLIGHT,
            FRESH_BOOTSTRAP_SMOKE,
            AUDIT_CONCURRENCY_CHECKS,
        ):
            with self.subTest(plpgsql_path=path.name):
                parse_plpgsql(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
