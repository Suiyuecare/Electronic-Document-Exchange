"""Formal read-query inventory and deterministic scoped shared migration."""
import json
import re
import unittest

from tools.workflow_readiness_shared_forward import SOURCE, FORWARD_NAME, render_shared_forward
from tools.shared_supabase_bootstrap import ROOT, sha256_text, transform_sql


class WorkflowReadinessForwardContractTest(unittest.TestCase):
    def test_forward_is_exact_and_formal_inventory_is_sorted_without_candidate_handover(self):
        self.assertEqual(render_shared_forward(), (ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text())
        names = json.loads((ROOT / "supabase/verification/migration_manifest.json").read_text())["migrations"]
        self.assertEqual(sorted(names), names)
        self.assertEqual(1, names.count(SOURCE))
        self.assertFalse(any("offboarding_handover" in name for name in names))

    def test_shared_preflight_hash_ledger_and_non_bypass_backend_are_preserved(self):
        forward = render_shared_forward()
        for clause in ("shared_workflow_readiness_preflight_failed", "shared_workflow_readiness_source_hash_mismatch",
                       "20260827050436_complete_edoc_runtime_schema_parity.sql", "not rolbypassrls"):
            self.assertIn(clause, forward)
        for forbidden in ("grant all", "grant execute on all functions", "create table public.",
                          "update public.", "insert into public.", "delete from public."):
            self.assertNotIn(forbidden, forward.lower())

    def test_new_read_rpcs_are_invoker_only_backend_and_scope_checked_before_paging(self):
        sql = (ROOT / "supabase/migrations" / SOURCE).read_text()
        self.assertEqual(2, sql.lower().count("stable security invoker set search_path=''"))
        for name in ("edoc_list_inbound_candidates", "edoc_timeliness_candidates"):
            self.assertIn(f"revoke all on function public.{name}(jsonb) from public,anon,authenticated;", sql)
            self.assertIn(f"grant execute on function public.{name}(jsonb) to service_role;", sql)
            self.assertIn(f"grant execute on function edoc.{name}(jsonb) to edoc_backend;", transform_sql(sql))
        self.assertLess(sql.index("inbound_list_scope_forbidden"), sql.index("with filtered as materialized"))
        self.assertLess(sql.index("timeliness_scope_forbidden"), sql.index("with metrics as"))

    def test_live_verification_checks_new_rpc_privileges_and_exact_ledger_hashes(self):
        verification = ROOT / "supabase/verification"
        source = (ROOT / "supabase/migrations" / SOURCE).read_text()
        shared = (verification / "shared_project_cutover_checks.sql").read_text()
        manifest = json.loads((verification / "migration_manifest.json").read_text())
        self.assertIn(f"migration_ledger) = {len(manifest['migrations']) + 1}", shared)
        self.assertIn(f"file_name='{SOURCE}'", shared)
        self.assertIn(f"source_sha256='{sha256_text(source)}'", shared)
        self.assertIn(f"transformed_sha256='{sha256_text(transform_sql(source))}'", shared)
        pattern = r"do \$worklist_receipt_rpc_gate\$.*?\$worklist_receipt_rpc_gate\$;"
        for filename, namespace, backend_role in (
            ("fresh_bootstrap_smoke.sql", "public", "service_role"),
            ("shared_project_cutover_checks.sql", "edoc", "edoc_backend"),
        ):
            gate = re.search(pattern, (verification / filename).read_text(), re.S).group(0)
            for rpc in ("edoc_list_inbound_candidates", "edoc_timeliness_candidates"):
                self.assertIn(f"'{rpc}(jsonb)'", gate)
            self.assertIn(f"'{namespace}.' || v_rpc", gate)
            self.assertIn(f"has_function_privilege('{backend_role}',v_proc.oid,'EXECUTE')", gate)
            self.assertIn("v_proc.prosecdef", gate)
            self.assertIn("pg_get_userbyid(v_proc.proowner)<>'postgres'", gate)
            self.assertIn("search_path=\"\"", gate)
            self.assertIn("a.grantee=0", gate)
            self.assertIn("worklist_receipt_rpc_browser_grant", gate)
            self.assertNotIn("edoc_manage_official_handover", gate)


if __name__ == "__main__":
    unittest.main()
