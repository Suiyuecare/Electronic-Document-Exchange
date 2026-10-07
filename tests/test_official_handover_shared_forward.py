"""Release contract for the isolated candidate; never calls production."""
import json
import unittest

from tools.offboarding_handover_shared_forward import SOURCE, FORWARD_NAME, render_shared_forward
from tools.shared_supabase_bootstrap import ROOT, transform_sql


class HandoverForwardContractTest(unittest.TestCase):
    def test_checked_in_forward_is_exactly_reproducible(self):
        forward = ROOT / "supabase/shared-project-migrations" / FORWARD_NAME
        self.assertEqual(render_shared_forward(), forward.read_text())

    def test_manifest_appends_candidate_without_rewriting_historical_source(self):
        manifest = json.loads((ROOT / "supabase/verification/migration_manifest.json").read_text())
        self.assertEqual(SOURCE, manifest["migrations"][-1])
        self.assertEqual(1, manifest["migrations"].count(SOURCE))
        self.assertLess(manifest["migrations"].index("20261006154028_terminal_official_decline.sql"),
                        manifest["migrations"].index(SOURCE))

    def test_shared_forward_requires_old_ledger_and_only_targets_edoc(self):
        text = render_shared_forward()
        self.assertIn("shared_offboarding_handover_preflight_failed", text)
        self.assertIn("shared_offboarding_handover_source_hash_mismatch", text)
        self.assertIn("20261006154028_terminal_official_decline.sql", text)
        self.assertIn("not rolbypassrls", text)
        for forbidden in ("create table public.", "update public.", "insert into public.",
                          "grant execute on all functions", "grant all on"):
            self.assertNotIn(forbidden, text.lower())

    def test_candidate_never_grants_browser_or_direct_backend_mutation(self):
        source = (ROOT / "supabase/migrations" / SOURCE).read_text().lower()
        self.assertIn("security definer set search_path=''", source)
        self.assertIn("grant select on public.official_document_handovers,public.official_document_followup_owners to service_role", source)
        self.assertNotIn("grant insert", source)
        self.assertNotIn("grant update", source)
        self.assertNotIn("grant delete", source)
        self.assertIn("from public,anon,authenticated;", source)
        transformed = transform_sql(source)
        self.assertIn("to edoc_backend;", transformed)
        self.assertNotIn("to service_role;", transformed)

    def test_pending_generation_keeps_canonical_provenance_and_null_role_denial(self):
        source = (ROOT / "supabase/migrations" / SOURCE).read_text()
        self.assertIn("coalesce(v_actor.role,'') not in ('行政部主任','行政部門主任')", source)
        self.assertIn("'copied_from_step_id',v_step.id,'added_by_operation_id',v_id", source)
        self.assertNotIn("v_new.decision_evidence_json:=pg_catalog.jsonb_build_object('handover_id'", source)


if __name__ == "__main__":
    unittest.main()
