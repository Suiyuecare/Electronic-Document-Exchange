from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

try:
    from pglast import parse_sql
except ImportError:  # pragma: no cover - CI installs the pinned SQL parser.
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
CUTOVER_CHECKS = ROOT / "supabase" / "verification" / "production_cutover_checks.sql"
STORAGE_CUTOVER_CHECKS = ROOT / "supabase" / "verification" / "dedicated_storage_cutover_checks.sql"
MANIFEST = ROOT / "supabase" / "verification" / "migration_manifest.json"
ROLES_BOOTSTRAP = ROOT / "supabase" / "roles.sql"


class SupabaseRuntimeRecoveryTestCase(unittest.TestCase):
    def test_roles_bootstrap_only_supplies_legacy_permission_fk_prerequisites(self) -> None:
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
        self.assertNotRegex(sql, r"\bgrant\b")
        if parse_sql is not None:
            self.assertGreaterEqual(len(parse_sql(sql)), 2)

    def test_recovery_snapshot_and_storage_sql_are_outside_main_migration_chain(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        names = set(manifest["migrations"])
        self.assertIn(SCHEMA_PARITY.name, names)
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
        for exact_id in ("USR-001", "DOC-IN-1140522-00018", "NTF-001", "CERT-SEAL-001"):
            self.assertIn(exact_id, cleanup)

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
            ROOT / "supabase" / "seed.sql",
            ROOT / "supabase" / "verification" / "production_cutover_checks.sql",
            STORAGE_CUTOVER_CHECKS,
        )
        for path in paths:
            with self.subTest(path=path.name):
                parse_sql(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
