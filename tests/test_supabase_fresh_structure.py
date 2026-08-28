from __future__ import annotations

import ast
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
SUPABASE = ROOT / "supabase"
MIGRATIONS = SUPABASE / "migrations"
STORAGE_MIGRATIONS = SUPABASE / "storage-migrations"
VERIFICATION = SUPABASE / "verification"
SCHEMA_PARITY = MIGRATIONS / "20260827050436_complete_edoc_runtime_schema_parity.sql"
GRANT_HARDENING = MIGRATIONS / "20260827063824_lock_runtime_table_data_api_grants.sql"
DISPATCH_EVENT_CAPTURE = (
    MIGRATIONS / "20260827101441_capture_official_dispatch_events.sql"
)
EDITOR_IMMUTABLE_PROMOTION = (
    MIGRATIONS / "20260827194500_promote_editor_tus_staging_to_immutable.sql"
)
EDITOR_STORAGE_PREFLIGHT = (
    VERIFICATION / "editor_storage_promotion_preflight.sql"
)
RUNTIME_SMOKE = VERIFICATION / "runtime_schema_parity_smoke.sql"
FRESH_BOOTSTRAP_SMOKE = VERIFICATION / "fresh_bootstrap_smoke.sql"
SERVICE_ROLE_GRANT_SMOKE = VERIFICATION / "service_role_data_api_grant_smoke.sql"
CUTOVER = VERIFICATION / "production_cutover_checks.sql"
MAIN_MANIFEST = VERIFICATION / "migration_manifest.json"
STORAGE_MANIFEST = VERIFICATION / "storage_migration_manifest.json"
STORAGE_BASE = STORAGE_MIGRATIONS / "20260824034730_dedicated_edoc_private_storage_buckets.sql"
STORAGE_HARDEN = STORAGE_MIGRATIONS / "20260827042214_harden_edoc_storage_buckets.sql"
STORAGE_ALLOWLIST = STORAGE_MIGRATIONS / "20260827050000_enforce_empty_storage_client_policy_allowlist.sql"
STORAGE_CHECKS = VERIFICATION / "dedicated_storage_cutover_checks.sql"
LOCAL_STORAGE_TUS_GATE = VERIFICATION / "local_storage_tus_gate.sql"
LOCAL_EDITOR_FINALIZE_RPC_GATE = (
    ROOT / "tests" / "support" / "local_supabase_editor_finalize_rpc_gate.py"
)
MAIN_PUSH_TOOL = ROOT / "tools" / "supabase_main_migration_push.py"
DEPLOYMENT_DOC = ROOT / "docs" / "deployment-production.md"

RUNTIME_TABLES = (
    "inbound_document_attachments",
    "internal_dispatches",
    "internal_dispatch_recipients",
    "internal_dispatch_replies",
    "internal_dispatch_logs",
    "official_document_stamp_positions",
    "official_document_text_overlays",
    "official_document_editor_revisions",
    "official_document_editor_assets",
    "official_document_dispatch_events",
    "official_document_archive_exports",
    "official_workflow_delegations",
)


class SupabaseFreshStructureTestCase(unittest.TestCase):
    def test_editor_tus_finalize_binds_an_immutable_server_path(self) -> None:
        sql = EDITOR_IMMUTABLE_PROMOTION.read_text(encoding="utf-8").lower()
        cutover = CUTOVER.read_text(encoding="utf-8").lower()
        runtime_smoke = RUNTIME_SMOKE.read_text(encoding="utf-8").lower()
        fresh_smoke = FRESH_BOOTSTRAP_SMOKE.read_text(encoding="utf-8").lower()
        manifest = json.loads(MAIN_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["migrations"][-1], EDITOR_IMMUTABLE_PROMOTION.name)
        self.assertIn("editor-final/", sql)
        self.assertIn("trg_edoc_bind_finalized_editor_asset_storage", sql)
        self.assertIn("before insert or update or delete", sql)
        self.assertIn("trg_edoc_guard_editor_storage_job", sql)
        self.assertIn("before insert or update", sql)
        self.assertIn("existing_editor_assets_require_immutable_promotion", sql)
        self.assertIn("official_document_editor_storage_jobs", sql)
        self.assertIn("editor_finalized_asset_immutable", sql)
        self.assertRegex(
            sql,
            r"asset_id text not null unique\s+references public\.official_document_editor_assets\(id\) on delete restrict",
        )
        self.assertRegex(
            sql,
            r"document_id text not null\s+references public\.official_documents\(id\) on delete restrict",
        )
        self.assertIn("editor_finalized_asset_insert_forbidden", sql)
        self.assertIn("editor_storage_job_binding_immutable", sql)
        self.assertIn("editor_storage_job_file_binding_forbidden", sql)
        self.assertIn("editor_storage_job_cleaned_immutable", sql)
        self.assertIn("official_editor_storage_job_commit_file_check", sql)
        self.assertIn("official_editor_storage_job_cleaned_at_check", sql)
        self.assertIn("official_editor_storage_job_error_code_check", sql)
        self.assertIn("official_editor_storage_job_lease_check", sql)
        self.assertIn("lease_token", sql)
        self.assertIn("lease_expires_at", sql)
        self.assertIn("pg_catalog.pg_input_is_valid", sql)
        self.assertIn("staging_bucket = 'edoc-private'", sql)
        self.assertIn("final_bucket = 'edoc-private'", sql)
        self.assertIn("idx_official_editor_storage_jobs_final_file", sql)
        self.assertIn("new.storage_path := v_file.storage_key", sql)
        self.assertIn("new.storage_bucket := v_file.bucket", sql)
        self.assertIn(
            "alter table public.official_document_editor_storage_jobs force row level security",
            sql,
        )
        self.assertIn(
            "revoke all on table public.official_document_editor_storage_jobs",
            sql,
        )
        table_block = re.search(
            r"create table if not exists public\.official_document_editor_storage_jobs\s*\((.*?)\n\);",
            sql,
            re.DOTALL,
        )
        self.assertIsNotNone(table_block)
        for constraint_name in re.findall(
            r"constraint\s+([a-z0-9_]+)",
            table_block.group(1),
        ):
            with self.subTest(storage_job_constraint=constraint_name):
                self.assertIn(
                    f"('official_document_editor_storage_jobs', '{constraint_name}')",
                    cutover,
                )
        for index_name in re.findall(
            r"create index if not exists\s+([a-z0-9_]+)\s+on public\.official_document_editor_storage_jobs",
            sql,
        ):
            with self.subTest(storage_job_index=index_name):
                self.assertIn(index_name, cutover)
                self.assertIn(index_name, runtime_smoke)
        self.assertNotIn("x-upsert", sql)
        for verification_sql in (fresh_smoke, runtime_smoke, cutover):
            self.assertRegex(
                verification_sql,
                r"trg_edoc_bind_finalized_editor_asset_storage[\s\S]*?tgtype = 31",
            )

    def test_editor_storage_promotion_has_fail_closed_preflight_and_runbook(self) -> None:
        preflight = EDITOR_STORAGE_PREFLIGHT.read_text(encoding="utf-8").lower()
        cutover = CUTOVER.read_text(encoding="utf-8").lower()
        runtime_smoke = RUNTIME_SMOKE.read_text(encoding="utf-8").lower()
        docs = DEPLOYMENT_DOC.read_text(encoding="utf-8")

        self.assertIn("active_editor_upload_count", preflight)
        self.assertIn("finalized_assets_requiring_byte_promotion", preflight)
        self.assertIn("nonfinalized_assets_without_durable_job_input", preflight)
        self.assertIn("editor_upload_maintenance_window_not_empty", preflight)
        self.assertIn("editor_storage_promotion_preflight_ok", preflight)
        self.assertNotIn("select asset.id", preflight)
        self.assertNotIn("select asset.storage_path", preflight)
        self.assertIn("invalid_finalized_editor_assets", cutover)
        self.assertIn("invalid_editor_storage_jobs", cutover)
        self.assertIn("editor_storage_cleanup_backlog", cutover)
        self.assertIn("active_editor_storage_job_leases", cutover)
        self.assertIn("expired_editor_storage_job_leases", cutover)
        self.assertIn("pg_catalog.pg_input_is_valid", cutover)
        self.assertIn("editor_storage_preflight_postgres_16_required", preflight)
        self.assertIn("runtime_schema_postgres_16_required", runtime_smoke)
        self.assertIn("constraint_validated", cutover)
        self.assertIn("index_ready", cutover)
        self.assertIn("relforcerowsecurity", cutover)
        self.assertIn("idx_official_editor_storage_jobs_due", cutover)
        self.assertIn("idx_official_editor_storage_jobs_document", cutover)
        self.assertIn("idx_official_editor_storage_jobs_final_file", cutover)
        self.assertIn("trg_edoc_guard_editor_storage_job", cutover)
        self.assertIn("editor_storage_promotion_preflight.sql", docs)
        self.assertIn("active_editor_upload_count=0", docs)
        self.assertIn("finalized_assets_requiring_byte_promotion=0", docs)
        self.assertIn("nonfinalized_assets_without_durable_job_input=0", docs)
        self.assertIn("checkedAssetCount` 必須精確等於 SQL 的 `finalized_editor_asset_count", docs)
        self.assertIn("verify_editor_storage_assets.py --acknowledge-private-document-download", docs)
        self.assertIn("--post-migration", docs)
        self.assertIn("invalid_editor_storage_jobs", docs)
        pre_verify = docs.index(
            "python3 scripts/verify_editor_storage_assets.py --acknowledge-private-document-download"
        )
        preflight_after_verify = docs.index(
            "supabase/verification/editor_storage_promotion_preflight.sql",
            pre_verify,
        )
        migration_boundary = docs.index("\n7.", preflight_after_verify)
        post_verify = docs.index("--post-migration", migration_boundary)
        self.assertLess(pre_verify, preflight_after_verify)
        self.assertLess(preflight_after_verify, migration_boundary)
        self.assertLess(migration_boundary, post_verify)

    def test_twelve_backend_runtime_tables_are_already_forward_migrated(self) -> None:
        sql = SCHEMA_PARITY.read_text(encoding="utf-8").lower()
        manifest = json.loads(MAIN_MANIFEST.read_text(encoding="utf-8"))
        self.assertLess(
            manifest["migrations"].index(SCHEMA_PARITY.name),
            manifest["migrations"].index(
                "20260827050447_remove_exact_demo_bootstrap_records_forward.sql"
            ),
        )
        for table in RUNTIME_TABLES:
            with self.subTest(table=table):
                self.assertRegex(
                    sql,
                    rf"create table if not exists public\.{re.escape(table)}\b",
                )
                self.assertIn(
                    f"alter table public.{table} enable row level security",
                    sql,
                )
                self.assertIn(
                    f"revoke all on table public.{table} from public, anon, authenticated",
                    sql,
                )

    def test_runtime_tables_have_primary_keys_foreign_keys_and_indexes(self) -> None:
        sql = SCHEMA_PARITY.read_text(encoding="utf-8").lower()
        cutover = CUTOVER.read_text(encoding="utf-8").lower()
        for table in RUNTIME_TABLES:
            with self.subTest(table=table):
                block = re.search(
                    rf"create table if not exists public\.{table}\s*\((.*?)\n\);",
                    sql,
                    re.DOTALL,
                )
                self.assertIsNotNone(block)
                self.assertRegex(block.group(1), rf"constraint\s+{table}[^\n]*_pkey\s+primary key")
                for constraint_name in re.findall(
                    r"constraint\s+([a-z0-9_]+)",
                    block.group(1),
                ):
                    self.assertIn(
                        f"('{table}', '{constraint_name}')",
                        cutover,
                    )

        for expected in (
            "inbound_document_attachments_inbound_document_id_fkey",
            "internal_dispatch_recipients_dispatch_id_fkey",
            "internal_dispatch_replies_recipient_id_fkey",
            "internal_dispatch_logs_dispatch_id_fkey",
            "official_document_stamp_positions_locked_seal_file_id_fkey",
            "official_document_editor_revisions_parent_revision_id_fkey",
            "official_document_editor_assets_file_object_id_fkey",
            "official_document_dispatch_events_dispatch_record_id_fkey",
            "official_document_archive_exports_requested_by_fkey",
            "official_workflow_delegations_delegate_user_id_fkey",
        ):
            self.assertIn(expected, sql)

        for expected in (
            "idx_inbound_attachments_document",
            "idx_internal_dispatches_status",
            "idx_internal_dispatch_recipients_action",
            "idx_internal_dispatch_replies_dispatch",
            "idx_internal_dispatch_logs_dispatch",
            "idx_official_stamp_positions_request",
            "idx_official_text_overlays_request",
            "idx_official_editor_revisions_parent",
            "idx_official_editor_assets_revision",
            "idx_official_dispatch_events_document_created",
            "idx_official_archive_exports_document_created",
            "idx_official_workflow_delegations_lookup",
        ):
            self.assertRegex(sql, rf"create (?:unique )?index if not exists {expected}\b")

    def test_text_overlay_grants_are_replace_only(self) -> None:
        schema_sql = SCHEMA_PARITY.read_text(encoding="utf-8").lower()
        recovery_sql = (
            SUPABASE / "recovery" / "complete_edoc_runtime_recovery_20260827.sql"
        ).read_text(encoding="utf-8").lower()
        expected = (
            "grant select, insert, delete on table "
            "public.official_document_text_overlays to service_role"
        )
        overbroad = (
            "grant select, insert, update, delete on table "
            "public.official_document_text_overlays to service_role"
        )
        for sql in (schema_sql, recovery_sql):
            self.assertIn(expected, sql)
            self.assertNotIn(overbroad, sql)

    def test_rpc_owned_runtime_tables_are_direct_read_only(self) -> None:
        schema_sql = SCHEMA_PARITY.read_text(encoding="utf-8").lower()
        recovery_sql = (
            SUPABASE / "recovery" / "complete_edoc_runtime_recovery_20260827.sql"
        ).read_text(encoding="utf-8").lower()
        for table in (
            "official_document_dispatch_events",
            "official_workflow_delegations",
        ):
            expected = f"grant select on table public.{table} to service_role"
            for sql in (schema_sql, recovery_sql):
                self.assertIn(expected, sql)
                self.assertNotRegex(
                    sql,
                    rf"grant [^;]*(?:insert|update|delete)[^;]* on table public\.{table} to service_role",
                )

    def test_dispatch_event_capture_is_private_sequential_and_recoverable(self) -> None:
        migration_sql = DISPATCH_EVENT_CAPTURE.read_text(encoding="utf-8").lower()
        recovery_sql = (
            SUPABASE / "recovery" / "complete_edoc_runtime_recovery_20260827.sql"
        ).read_text(encoding="utf-8").lower()
        runtime_smoke = RUNTIME_SMOKE.read_text(encoding="utf-8").lower()
        fresh_smoke = FRESH_BOOTSTRAP_SMOKE.read_text(encoding="utf-8").lower()
        cutover = CUTOVER.read_text(encoding="utf-8").lower()

        for sql in (migration_sql, recovery_sql):
            with self.subTest(contract="migration_or_recovery"):
                self.assertIn(
                    "edoc_private.capture_official_dispatch_event_v1()",
                    sql,
                )
                self.assertIn("security definer", sql)
                self.assertIn("set search_path to ''", sql)
                self.assertIn("edoc:dispatch-event:", sql)
                self.assertIn("pg_catalog.hashtextextended", sql)
                self.assertIn("pg_catalog.max(event.event_sequence)", sql)
                self.assertIn("0::bigint", sql)
                self.assertNotIn("pg_catalog.coalesce(", sql)
                self.assertNotIn("pg_catalog.nullif(", sql)
                self.assertIn("'created'", sql)
                self.assertIn("'metadata_updated'", sql)
                self.assertIn("'status_transition'", sql)
                self.assertIn("'baseline_snapshot'", sql)
                self.assertIn("extensions.digest", sql)
                self.assertIn("'sha256'", sql)
                self.assertIn("trg_official_dispatch_record_capture_insert", sql)
                self.assertIn("trg_official_dispatch_record_capture_update", sql)
                self.assertIn(
                    "lock table public.official_document_dispatch_records in share row exclusive mode",
                    sql,
                )
                self.assertIn(
                    "revoke all on function edoc_private.capture_official_dispatch_event_v1()",
                    sql,
                )
                self.assertIn(
                    "edoc_private.guard_official_dispatch_identity_v1()",
                    sql,
                )
                self.assertIn("official_dispatch_identity_immutable", sql)
                self.assertIn("trg_official_dispatch_record_identity_guard", sql)
                self.assertIn(
                    "before update of id, document_id, created_by, created_at",
                    sql,
                )
                self.assertIn(
                    "revoke all on function edoc_private.guard_official_dispatch_identity_v1()",
                    sql,
                )
                self.assertIn(
                    "revoke insert, update, delete\n  on table public.official_document_dispatch_events\n  from service_role",
                    sql,
                )
                self.assertNotRegex(
                    sql,
                    r"grant [^;]*(?:insert|update|delete)[^;]* on table public\.official_document_dispatch_events to service_role",
                )

        self.assertNotIn("on conflict do nothing", migration_sql)

        self.assertIn(
            "runtime_schema_dispatch_event_capture_function_missing",
            runtime_smoke,
        )
        self.assertIn(
            "runtime_schema_dispatch_event_capture_execute_exposed",
            runtime_smoke,
        )
        self.assertIn(
            "runtime_schema_dispatch_event_capture_trigger_invalid",
            runtime_smoke,
        )
        for trigger_contract in (
            "trigger_row.tgfoid",
            "trigger_row.tgtype = 5",
            "trigger_row.tgtype = 17",
            "trigger_row.tgtype = 19",
            "trigger_row.tgattr::smallint[]",
            "pg_catalog.pg_get_triggerdef(trigger_row.oid, false)",
            "trigger_row.tgenabled <> 'd'",
        ):
            self.assertIn(trigger_contract, runtime_smoke)
            self.assertIn(trigger_contract, cutover)
        self.assertNotIn("pg_catalog.pg_get_expr(trigger_row.tgqual", runtime_smoke)
        self.assertNotIn("pg_catalog.pg_get_expr(trigger_row.tgqual", cutover)
        self.assertGreaterEqual(runtime_smoke.count("'executefunction'"), 2)
        self.assertGreaterEqual(cutover.count("'executefunction'"), 2)
        self.assertIn("v_dispatch_capture_qual", runtime_smoke)
        self.assertIn("v_dispatch_identity_qual", runtime_smoke)
        self.assertIn("expected.capture_qual", cutover)
        self.assertIn("expected.identity_qual", cutover)
        self.assertNotIn("pg_catalog.coalesce(", runtime_smoke)
        self.assertNotIn("pg_catalog.coalesce(", cutover)
        self.assertGreaterEqual(
            runtime_smoke.count("trigger_row.tgfoid"),
            2,
        )
        self.assertGreaterEqual(cutover.count("trigger_row.tgfoid"), 2)
        self.assertGreaterEqual(runtime_smoke.count("trigger_row.tgenabled <> 'd'"), 2)
        self.assertGreaterEqual(cutover.count("trigger_row.tgenabled <> 'd'"), 2)
        for trigger_check in (runtime_smoke, cutover):
            self.assertGreaterEqual(
                trigger_check.count(
                    "pg_catalog.array_agg(attribute_row.attname::text"
                ),
                2,
            )
            self.assertNotIn(
                "pg_catalog.array_agg(attribute_row.attname order",
                trigger_check,
            )
        for marker in (
            "fresh_bootstrap_dispatch_created_event_invalid",
            "fresh_bootstrap_dispatch_create_replay_duplicated_event",
            "fresh_bootstrap_dispatch_identity_mutation_accepted",
            "fresh_bootstrap_dispatch_identity_mutation_wrong_error",
            "fresh_bootstrap_dispatch_identity_mutation_left_state",
            "fresh_bootstrap_dispatch_metadata_event_invalid",
            "fresh_bootstrap_dispatch_completion_event_invalid",
            "fresh_bootstrap_dispatch_replay_or_sequence_invalid",
            "fresh_bootstrap_dispatch_event_update_accepted",
            "fresh_bootstrap_dispatch_event_delete_accepted",
        ):
            self.assertIn(marker, fresh_smoke)
        self.assertIn(
            "public.edoc_create_official_document_dispatch_record(",
            fresh_smoke,
        )
        self.assertIn(
            "public.edoc_complete_official_document_dispatch(",
            fresh_smoke,
        )
        for marker in (
            "dispatch_capture_function_exists",
            "dispatch_capture_function_hardened",
            "dispatch_capture_function_private",
            "dispatch_capture_triggers_enabled",
            "dispatch_identity_guard_function_exists",
            "dispatch_identity_guard_function_hardened",
            "dispatch_identity_guard_function_private",
            "dispatch_identity_guard_trigger_enabled",
            "dispatch_events_api_read_only",
            "every_dispatch_record_has_evidence",
            "dispatch_event_sequences_contiguous",
        ):
            self.assertIn(marker, cutover)

    def test_cutover_and_ci_smoke_cover_all_runtime_tables(self) -> None:
        cutover = CUTOVER.read_text(encoding="utf-8").lower()
        smoke = RUNTIME_SMOKE.read_text(encoding="utf-8").lower()
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        for table in RUNTIME_TABLES:
            with self.subTest(table=table):
                self.assertIn(f"('{table}')", cutover)
                self.assertIn(f"'{table}'", smoke)
        self.assertIn(
            "--file supabase/verification/runtime_schema_parity_smoke.sql",
            workflow,
        )
        self.assertIn("relrowsecurity", smoke)
        self.assertIn("has_table_privilege", smoke)
        self.assertIn("runtime_schema_required_index_missing", smoke)
        self.assertIn("runtime_schema_text_overlay_grant_invalid", smoke)
        self.assertIn("runtime_schema_rpc_owned_grant_invalid", smoke)
        self.assertIn(
            "v_table_oid := 'public.official_document_text_overlays'::regclass",
            smoke,
        )
        self.assertRegex(
            smoke,
            r"(?s)official_document_text_overlays'::regclass;.*?has_table_privilege\('service_role', v_table_oid, 'insert'\).*?has_table_privilege\('service_role', v_table_oid, 'update'\).*?has_table_privilege\('service_role', v_table_oid, 'delete'\)",
        )

    def test_forward_grant_hardening_removes_legacy_auto_exposure(self) -> None:
        sql = GRANT_HARDENING.read_text(encoding="utf-8").lower()
        manifest = json.loads(MAIN_MANIFEST.read_text(encoding="utf-8"))
        self.assertIn(GRANT_HARDENING.name, manifest["migrations"])
        for table in RUNTIME_TABLES:
            with self.subTest(table=table):
                self.assertIn(
                    f"alter table public.{table} enable row level security",
                    sql,
                )
        self.assertIn("alter default privileges for role postgres in schema public", sql)
        self.assertIn("alter default privileges for role postgres\n  revoke execute on functions from public", sql)
        self.assertIn("do $verify_postgres_api_default_acls$", sql)
        self.assertIn("from pg_catalog.pg_default_acl", sql)
        self.assertIn("edoc_postgres_public_default_acl_revoke_failed", sql)
        self.assertIn("edoc_postgres_global_function_default_acl_exposed", sql)
        self.assertIn("pg_catalog.acldefault('f', 'postgres'::regrole)", sql)
        self.assertNotIn("foreach v_owner in array v_owners", sql)
        self.assertIn(
            "revoke all privileges on tables",
            sql,
        )
        self.assertIn("revoke all privileges on sequences", sql)
        self.assertIn("revoke all privileges on functions", sql)
        self.assertRegex(
            sql,
            r"revoke all privileges on tables\s+from public, anon, authenticated, service_role",
        )
        self.assertRegex(
            sql,
            r"revoke all privileges on sequences\s+from public, anon, authenticated, service_role",
        )
        self.assertIn(
            "revoke all privileges on all tables in schema public",
            sql,
        )
        self.assertIn(
            "revoke all privileges on all sequences in schema public",
            sql,
        )
        self.assertIn(
            "revoke all privileges on all functions in schema public",
            sql,
        )
        self.assertRegex(
            sql,
            r"revoke all privileges on all tables in schema public\s+from public, anon, authenticated, service_role",
        )
        self.assertRegex(
            sql,
            r"revoke all privileges on all functions in schema public\s+from public, anon, authenticated, service_role",
        )
        self.assertNotIn(
            "grant execute on all functions in schema public to service_role",
            sql,
        )
        self.assertNotIn(
            "grant execute on all functions in schema edoc_private to service_role",
            sql,
        )
        self.assertIn(
            "roles && array['public', 'anon', 'authenticated']::name[]",
            sql,
        )
        self.assertIn("drop policy if exists %i on %i.%i", sql)
        self.assertIn("grant usage on schema edoc_private to service_role", sql)
        self.assertIn(
            "grant execute on function edoc_private.audit_log_hash_payload(",
            sql,
        )
        self.assertIn(
            "grant select on public.audit_log_chain_check to service_role",
            sql,
        )

        backend_tree = ast.parse((ROOT / "backend.py").read_text(encoding="utf-8"))
        backend_tables: set[str] = set()
        for node in ast.walk(backend_tree):
            if not isinstance(node, ast.Assign) or not any(
                isinstance(target, ast.Name) and target.id == "TABLES"
                for target in node.targets
            ):
                continue
            self.assertIsInstance(node.value, ast.Dict)
            backend_tables = {
                value.value
                for value in node.value.values
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            }
            break
        extra_tables = {
            "finance_member_sync_nonces",
            "finance_member_sync_receipts",
            "finance_organization_projection_state",
            "finance_organization_units",
            "official_document_rejection_jobs",
            "portal_handoff_nonces",
        }
        select_block = re.search(
            r"grant select on table\s+(.*?)\s+to service_role;",
            sql,
            re.DOTALL,
        )
        self.assertIsNotNone(select_block)
        granted_select = set(re.findall(r"public\.([a-z0-9_]+)", select_block.group(1)))
        later_select = {
            table
            for table in backend_tables
            if f"grant select, insert, update on table public.{table}" in EDITOR_IMMUTABLE_PROMOTION.read_text(encoding="utf-8").lower()
        }
        self.assertEqual(granted_select | later_select, backend_tables | extra_tables)

        matrix_smoke = SERVICE_ROLE_GRANT_SMOKE.read_text(encoding="utf-8").lower()
        expected_matrix = dict(
            re.findall(r"\('([a-z0-9_]+)',\s*'([siud]+)'\)", matrix_smoke)
        )
        self.assertEqual(set(expected_matrix), granted_select | later_select)
        for privilege, marker in (("insert", "i"), ("update", "u"), ("delete", "d")):
            block = re.search(
                rf"grant {privilege} on table\s+(.*?)\s+to service_role;",
                sql,
                re.DOTALL,
            )
            self.assertIsNotNone(block)
            granted = set(re.findall(r"public\.([a-z0-9_]+)", block.group(1)))
            if privilege in {"insert", "update"}:
                granted |= later_select
            self.assertEqual(
                granted,
                {table for table, operations in expected_matrix.items() if marker in operations},
            )

        required_rpc_names: set[str] = set()
        for node in ast.walk(backend_tree):
            if not isinstance(node, ast.Assign) or not any(
                isinstance(target, ast.Name)
                and target.id == "EDOC_READINESS_REQUIRED_RPC_NAMES"
                for target in node.targets
            ):
                continue
            self.assertIsInstance(node.value, (ast.Tuple, ast.List))
            required_rpc_names = {
                item.value
                for item in node.value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            }
            break
        granted_rpc_names = set(
            re.findall(
                r"grant execute on function public\.(edoc_[a-z0-9_]+)\(",
                sql,
            )
        )
        self.assertEqual(
            granted_rpc_names - {"edoc_company_seal_dimensions_are_valid"},
            required_rpc_names,
        )
        self.assertEqual(len(required_rpc_names), 23)
        cutover = CUTOVER.read_text(encoding="utf-8").lower()
        fresh_smoke = FRESH_BOOTSTRAP_SMOKE.read_text(encoding="utf-8").lower()
        self.assertIn("from information_schema.table_privileges", cutover)
        self.assertIn("from information_schema.usage_privileges", cutover)
        self.assertIn("from information_schema.routine_privileges", cutover)
        self.assertNotIn("from information_schema.role_table_grants", cutover)
        self.assertNotIn("from information_schema.role_usage_grants", cutover)
        self.assertNotIn("from information_schema.role_routine_grants", cutover)
        self.assertIn("from pg_catalog.pg_policies", cutover)
        self.assertIn("from pg_catalog.pg_default_acl", cutover)
        self.assertIn("from pg_catalog.pg_default_acl", matrix_smoke)
        self.assertIn("from pg_catalog.pg_default_acl", fresh_smoke)
        self.assertIn("owner_role.rolname = 'postgres'", cutover)
        self.assertIn("owner_role.rolname = 'postgres'", matrix_smoke)
        self.assertIn("owner_role.rolname = 'postgres'", fresh_smoke)
        self.assertIn("pg_catalog.acldefault('f', 'postgres'::regrole)", cutover)
        self.assertIn("pg_catalog.acldefault('f', 'postgres'::regrole)", matrix_smoke)
        self.assertIn("pg_catalog.acldefault('f', 'postgres'::regrole)", fresh_smoke)
        self.assertIn(
            "grantee in ('public', 'anon', 'authenticated')",
            cutover,
        )
        self.assertNotIn("and table_name in (", cutover)
        self.assertIn("88 direct postgrest tables", cutover)
        self.assertIn("unexpected_service_role_function", cutover)
        for rpc_name in required_rpc_names:
            with self.subTest(rpc=rpc_name):
                self.assertGreaterEqual(cutover.count(f"public.{rpc_name}("), 2)
                self.assertIn(f"public.{rpc_name}(", matrix_smoke)
        self.assertIn("notify pgrst, 'reload schema'", sql)

    def test_cloud_push_separates_fresh_roles_from_existing_forward_only(self) -> None:
        tool = MAIN_PUSH_TOOL.read_text(encoding="utf-8")
        docs = DEPLOYMENT_DOC.read_text(encoding="utf-8")
        self.assertIn('choices=("fresh-empty", "existing")', tool)
        self.assertIn('command.append("--include-roles")', tool)
        self.assertIn("fresh_empty_mode_refuses_project_with_migration_history", tool)
        self.assertIn("existing_mode_refuses_empty_project", tool)
        self.assertIn("--dry-run", tool)
        self.assertNotIn("--include-all", tool)
        self.assertNotIn("--include-seed", tool)
        self.assertIn("fresh-empty --project-ref", docs)
        self.assertIn("existing --project-ref", docs)
        self.assertIn("既有 project", docs)
        self.assertIn("不得手動重跑 `roles.sql`", docs)
        self.assertIn("fresh_finance_bootstrap_sentinel", docs)

    def test_storage_manifest_matches_dedicated_chain_only(self) -> None:
        manifest = json.loads(STORAGE_MANIFEST.read_text(encoding="utf-8"))
        actual = sorted(path.name for path in STORAGE_MIGRATIONS.glob("*.sql"))
        main = json.loads(MAIN_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["directory"], "supabase/storage-migrations")
        self.assertEqual(manifest["target"], "dedicated-edoc-storage-project-only")
        self.assertEqual(manifest["migrations"], actual)
        self.assertTrue(set(actual).isdisjoint(main["migrations"]))

    def test_storage_bucket_chain_allows_zip_and_removes_browser_policies(self) -> None:
        base = STORAGE_BASE.read_text(encoding="utf-8").lower()
        harden = STORAGE_HARDEN.read_text(encoding="utf-8").lower()
        allowlist = STORAGE_ALLOWLIST.read_text(encoding="utf-8").lower()
        checks = STORAGE_CHECKS.read_text(encoding="utf-8").lower()

        self.assertIn("'edoc-private'", base)
        self.assertIn("'edoc-seal-vault'", base)
        self.assertIn("'application/zip'", harden)
        self.assertIn("array_remove(allowed_mime_types, 'image/svg+xml')", harden)
        for policy_name in (
            "private bucket document scoped read",
            "private bucket authorized upload",
            "private bucket authorized replace",
        ):
            self.assertIn(f'drop policy if exists "{policy_name}"', harden)

        self.assertIn(
            "roles && array['public', 'anon', 'authenticated']::name[]",
            allowlist,
        )
        self.assertIn("drop policy if exists %i on storage.objects", allowlist)
        self.assertIn("'application/zip'", checks)
        self.assertIn("'image/svg+xml'", checks)
        self.assertIn("dedicated_storage_private_bucket_definition_invalid", checks)
        self.assertIn("dedicated_storage_seal_bucket_definition_invalid", checks)
        self.assertIn("dedicated_storage_browser_policy_exposed", checks)
        self.assertIn("dedicated_storage_unexpected_bucket_count", checks)
        self.assertIn("dedicated_storage_project_not_isolated", checks)
        self.assertIn("from auth.users", checks)
        self.assertIn("public_app_relation_count", checks)
        self.assertIn("public_app_function_count", checks)
        self.assertIn("private_bucket.file_size_limit is distinct from 104857600", checks)
        self.assertIn("seal_bucket.file_size_limit is distinct from 3145728", checks)
        self.assertIn("private_mimes @> coalesce", checks)
        self.assertIn("seal_mimes @> coalesce", checks)
        self.assertIn(
            "roles && array['public', 'anon', 'authenticated']::name[]",
            checks,
        )

    def test_local_supabase_config_is_reproducible_and_fail_closed(self) -> None:
        config = (SUPABASE / "config.toml").read_text(encoding="utf-8")
        self.assertRegex(config, r'(?m)^project_id\s*=\s*"module_edoc"\s*$')
        self.assertRegex(config, r'(?m)^auto_expose_new_tables\s*=\s*false\s*$')
        self.assertRegex(config, r'(?m)^sql_paths\s*=\s*\["\./seed\.sql"\]\s*$')
        self.assertGreaterEqual(len(re.findall(r'(?m)^enabled\s*=\s*true\s*$', config)), 3)
        self.assertRegex(config, r'(?m)^enable_signup\s*=\s*false\s*$')
        self.assertRegex(config, r'(?m)^enable_anonymous_sign_ins\s*=\s*false\s*$')

    def test_ci_runs_real_local_signed_tus_private_storage_gate(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        gate = LOCAL_STORAGE_TUS_GATE.read_text(encoding="utf-8").lower()
        seed = (SUPABASE / "seed.sql").read_text(encoding="utf-8").lower()
        fresh_smoke = (VERIFICATION / "fresh_bootstrap_smoke.sql").read_text(
            encoding="utf-8"
        ).lower()
        self.assertRegex(workflow, r"(?m)^\s*supabase start(?:\s|$)")
        self.assertNotIn("supabase db start", workflow)
        self.assertGreaterEqual(
            workflow.count("--file supabase/verification/local_storage_tus_gate.sql"),
            2,
        )
        self.assertIn("EDOC_ACCEPTANCE_UPLOAD_PROTOCOL=local_supabase_tus", workflow)
        self.assertIn(
            "supabase/setup-cli@46f7f98c7f948ad727d22c1e67fab04c223a0520 # v3.0.0",
            workflow,
        )
        self.assertNotIn("supabase/setup-cli@v1", workflow)
        self.assertIn("supabase status -o env", workflow)
        self.assertIn("local_storage_tus_private_bucket_public", gate)
        self.assertIn("local_storage_tus_browser_policy_exposed", gate)
        self.assertIn("local_storage_tus_synthetic_object_cleanup_failed", gate)
        self.assertIn("edoc_seed_is_intentionally_empty", seed)
        self.assertNotRegex(seed, r"\binsert\s+into\s+public\.")
        self.assertIn("fresh_bootstrap_demo_account_present", fresh_smoke)
        self.assertIn("fresh_bootstrap_finance_sentinel_present", fresh_smoke)
        self.assertIn("fresh_bootstrap_browser_data_api_exposed", fresh_smoke)
        self.assertIn("public.edoc_ci_default_acl_probe()", fresh_smoke)
        self.assertIn("fresh_bootstrap_future_function_default_exposed", fresh_smoke)
        for view in (
            "information_schema.table_privileges",
            "information_schema.usage_privileges",
            "information_schema.routine_privileges",
        ):
            self.assertIn(view, fresh_smoke)
        self.assertNotIn("information_schema.role_table_grants", fresh_smoke)
        self.assertNotIn("information_schema.role_usage_grants", fresh_smoke)
        self.assertNotIn("information_schema.role_routine_grants", fresh_smoke)

    def test_ci_calls_real_postgrest_editor_finalize_atomic_gate(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        gate = LOCAL_EDITOR_FINALIZE_RPC_GATE.read_text(encoding="utf-8")
        self.assertIn(
            "python tests/support/local_supabase_editor_finalize_rpc_gate.py",
            workflow,
        )
        self.assertIn("editor_storage_job_lease_active", gate)
        self.assertIn("editor_storage_job_cleaned_immutable", gate)
        self.assertIn("editor_storage_job_file_binding_forbidden", gate)
        self.assertIn('"storageJobGuardNegativeCases": 9', gate)
        self.assertLess(
            workflow.index("supabase status -o env"),
            workflow.index(
                "python tests/support/local_supabase_editor_finalize_rpc_gate.py"
            ),
        )
        self.assertIn("/rest/v1/rpc/edoc_finalize_editor_asset_v2", gate)
        self.assertIn('"Authorization": f"Bearer {api_key}"', gate)
        self.assertIn("local_editor_finalize_requires_loopback_supabase", gate)
        self.assertIn("local_editor_finalize_backend_storage_origin_invalid", gate)
        self.assertLess(
            gate.index("local_editor_finalize_backend_storage_origin_invalid"),
            gate.index("_supabase_storage_endpoint_issue = lambda"),
        )
        self.assertIn("local_editor_finalize_anon_rpc_exposed", gate)
        self.assertIn("official_editor_write_forbidden", gate)
        self.assertIn("editor_finalize_invalid_payload", gate)
        self.assertIn("editor_upload_new_intent_required", gate)
        self.assertIn("editor_revision_conflict", gate)
        self.assertIn("stale_intent_status == 409", gate)
        self.assertIn("stale_status == 409", gate)
        self.assertIn('get("code") == "PT409"', gate)
        self.assertIn("stale_intent_elapsed < 5.0", gate)
        self.assertIn("stale_revision_elapsed < 5.0", gate)
        self.assertIn("local_editor_finalize_stale_intent_left_rows", gate)
        self.assertIn("local_editor_finalize_stale_revision_left_rows", gate)
        self.assertIn('"businessConflictHttp409": True', gate)
        self.assertIn('"businessConflictUnderFiveSeconds": True', gate)
        self.assertIn("local_editor_finalize_partial_row", gate)
        self.assertIn("local_editor_finalize_replay_not_idempotent", gate)
        self.assertIn("editor_finalize_operation_conflict", gate)
        self.assertIn("/rest/v1/users?select=id&limit=1", gate)
        self.assertIn("/rest/v1/login_events", gate)
        self.assertIn("local_service_login_event_update_not_denied", gate)
        self.assertIn("local_service_login_event_delete_not_denied", gate)
        self.assertIn("/rest/v1/audit_log_chain_check", gate)
        self.assertIn("fixturesRemoved", gate)
        self.assertNotIn("SERVICE_ROLE_KEY=", gate)

    @unittest.skipIf(parse_sql is None, "pglast is not installed")
    def test_new_verification_and_storage_sql_parse_as_postgresql(self) -> None:
        for path in (
            GRANT_HARDENING,
            DISPATCH_EVENT_CAPTURE,
            EDITOR_IMMUTABLE_PROMOTION,
            EDITOR_STORAGE_PREFLIGHT,
            FRESH_BOOTSTRAP_SMOKE,
            RUNTIME_SMOKE,
            SERVICE_ROLE_GRANT_SMOKE,
            STORAGE_BASE,
            STORAGE_HARDEN,
            STORAGE_ALLOWLIST,
            STORAGE_CHECKS,
            LOCAL_STORAGE_TUS_GATE,
        ):
            with self.subTest(path=path.name):
                parse_sql(path.read_text(encoding="utf-8"))
        for path in (
            GRANT_HARDENING,
            DISPATCH_EVENT_CAPTURE,
            EDITOR_IMMUTABLE_PROMOTION,
            EDITOR_STORAGE_PREFLIGHT,
            FRESH_BOOTSTRAP_SMOKE,
            SERVICE_ROLE_GRANT_SMOKE,
        ):
            with self.subTest(plpgsql_path=path.name):
                parse_plpgsql(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
