"""Source-integrity tests for the separate six-image approval, never activation."""
import re
import json
import unittest

import seal_scan_20261013 as native
import seal_scan_exceptions as original
from tools import seal_native120_forward as forward
from tools.shared_supabase_bootstrap import sha256_text


class Native120ForwardTest(unittest.TestCase):
    def test_generated_source_and_shared_are_exact_and_atomic(self):
        source = forward.source_sql()
        shared = forward.shared_sql(source)
        self.assertEqual(source, (forward.ROOT / "supabase/migrations" / forward.SOURCE).read_text())
        self.assertEqual(shared, (forward.ROOT / "supabase/shared-project-migrations" / forward.SHARED).read_text())
        self.assertIn(forward.transformed_sql(source), shared)
        self.assertIn(sha256_text(source), shared)
        self.assertIn(sha256_text(forward.transformed_sql(source)), shared)
        self.assertEqual(shared.lower().count("\nbegin;\n"), 1)
        self.assertTrue(shared.endswith("commit;\n"))
        self.assertNotIn("public.", shared)
        self.assertIn("native120_scan_forward_prerequisite_missing", shared)
        self.assertIn("native120_scan_forward_hash_mismatch", shared)
        self.assertIn(forward.PREREQUISITE_SHA, shared)

    def test_six_raw_dct_assets_only_and_original_twenty_two_immutable(self):
        source = forward.source_sql()
        self.assertEqual(len(native._ROWS), 6)
        self.assertEqual(len({row[0] for row in native._ROWS}), 6)
        for row in native._ROWS:
            self.assertIn(row[0], source)
            self.assertIn(row[2], source)
        self.assertNotIn("CO-008", source)
        self.assertNotIn("c61033f", source)
        self.assertNotIn("6c644d095198eb0d", source)  # Superseded lossy-pypdf asset.
        old = (forward.ROOT / "supabase/migrations" / forward.PREREQUISITE).read_text()
        self.assertEqual(sha256_text(old), forward.PREREQUISITE_SHA)
        self.assertNotRegex(source, r"(?:insert into|update|delete from|create table) public\.approved_original_scan_import_batches")
        self.assertNotIn("create or replace function public.edoc_import_approved_original_scan_file", source)
        self.assertNotIn("create or replace function public.edoc_approved_original_scan_dimensions_are_valid", source)
        self.assertIn(f"p_policy_version not in ('{original.POLICY}','{native.POLICY}')", source)

    def test_no_open_permit_activation_or_global_dpi_relaxation(self):
        source = forward.source_sql()
        self.assertNotIn("create or replace function public.edoc_company_seal_dimensions_are_valid(", source)
        self.assertNotRegex(source, r"insert into public\.approved_native120_scan_import_batches")
        self.assertIn("completed_file_count between 0 and 6", source)
        self.assertIn("expires_at_epoch-started_at_epoch<=3600", source)
        self.assertIn("actor constant text := 'system:codex-operator-import'", source)
        self.assertIn("status=case when total=6 then 'completed' else 'open' end", source)
        self.assertIn("clock_timestamp()", source)
        self.assertIn("approved_native120_scan_metadata_invalid", source)
        self.assertIn("native120_small_slot_conflict", source)
        self.assertIn("native120_small_slot_owner_mismatch", source)
        for entity in ("E7", "E9", "E8"):
            self.assertIn("'" + entity + "'", source)
        rpc = source.split("create or replace function public.edoc_import_approved_native120_scan_file", 1)[1]
        params = rpc.split("returns jsonb", 1)[0]
        self.assertNotIn("p_actor", params)
        self.assertNotIn("p_owner", params)

    def test_privileges_are_closed_and_shared_backend_select_only(self):
        source = forward.source_sql()
        transformed = forward.transformed_sql(source)
        self.assertIn("force row level security", source)
        self.assertIn("grant select on public.approved_native120_scan_import_batches to service_role;", source)
        self.assertNotRegex(source, r"grant (?:insert|update|delete|all)[^;]*approved_native120_scan_import_batches")
        self.assertNotRegex(source, r"grant execute[^;]*to (?:public|anon|authenticated)")
        self.assertIn("revoke all on edoc.approved_native120_scan_import_batches from service_role,authenticator;", transformed)
        self.assertIn("security definer set search_path='' set lock_timeout='5s'", source)

    def test_fresh_and_shared_gates_match_exact_current_source_and_inventory(self):
        for name, schema in (("fresh_bootstrap_smoke.sql", "public"), ("shared_project_cutover_checks.sql", "edoc")):
            text = (forward.ROOT / "supabase/verification" / name).read_text()
            self.assertIn(forward.gate_sql(schema), text)
            self.assertIn("native120_scan_import_exact_constraints_mismatch", text)
            self.assertIn("native120_scan_import_attestation_trigger_mismatch", text)
            if schema == "edoc":
                manifest = json.loads((forward.ROOT / "supabase/verification/migration_manifest.json").read_text())
                self.assertIn(f"migration_ledger) = {len(manifest['migrations']) + 1}", text)
                self.assertIn("('r','p','v','m')) = 99", text)
                self.assertIn(sha256_text(forward.source_sql()), text)
                self.assertIn(sha256_text(forward.transformed_sql(forward.source_sql())), text)


if __name__ == "__main__":
    unittest.main()
