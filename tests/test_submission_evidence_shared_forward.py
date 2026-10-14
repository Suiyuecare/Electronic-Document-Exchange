"""Migration packaging contract; execution lives in submission-constraint PG tests."""
import json
import unittest

from tools.submission_evidence_shared_forward import (
    ROOT, SOURCE, FORWARD_NAME, render_shared_forward,
)
from tools.shared_supabase_bootstrap import sha256_text, transform_sql


class SubmissionEvidenceSharedForwardTest(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "supabase/migrations" / SOURCE).read_text()
        self.shared = (ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text()

    def test_generated_forward_is_hash_bound_and_in_cutover_inventory(self):
        self.assertEqual(self.shared, render_shared_forward())
        source_hash = sha256_text(self.source)
        shared_hash = sha256_text(transform_sql(self.source))
        self.assertIn(source_hash, self.shared)
        self.assertIn(shared_hash, self.shared)
        self.assertNotIn("public.", self.shared)
        self.assertIn(SOURCE, json.loads((ROOT / "supabase/verification/migration_manifest.json").read_text())["migrations"])
        checks = (ROOT / "supabase/verification/shared_project_cutover_checks.sql").read_text()
        self.assertIn("file_name='" + SOURCE + "'", checks)
        self.assertIn(source_hash, checks)
        self.assertIn(shared_hash, checks)
        self.assertIn("'atomic_submission_step_evidence_contract'", checks)
        self.assertIn("and column_row.attnotnull and not column_row.attisdropped", checks)

    def test_migration_updates_existing_definition_without_weakening_access_or_constraints(self):
        self.assertIn("pg_catalog.pg_get_functiondef", self.source)
        self.assertIn("'public.edoc_commit_official_document_submission(jsonb)'::regprocedure", self.source)
        self.assertIn("official_submission_step_evidence_migration_drift", self.source)
        self.assertIn("pg_catalog.length(v_guard_anchor)", self.source)
        self.assertIn("pg_catalog.length(v_old)", self.source)
        # Editing the existing definition preserves its security attributes,
        # owner, ACLs, CAS checks, and prepared-file hash witnesses.
        for forbidden in ("drop constraint", "drop policy", "disable trigger", "security definer", "grant ", "alter table"):
            self.assertNotIn(forbidden, self.source.lower())

    def test_only_missing_evidence_gets_the_pending_default(self):
        self.assertIn("item.value ? 'decision_evidence_json'", self.source)
        self.assertIn("pg_catalog.jsonb_typeof(item.value->'decision_evidence_json') is distinct from 'object'", self.source)
        self.assertIn("coalesce(v_step.decision_evidence_json, '{}'::jsonb)", self.source)
        self.assertIn("id, document_id, workflow_generation, step_order, step_key, step_name", self.source)
        self.assertIn("approved_at, decision_actor_user_id, decision_evidence_json", self.source)
        # Guard is inserted before workflow-generation parsing, which precedes
        # the existing idempotent-return path; replay cannot skip type checks.
        self.assertIn("v_guard || v_guard_anchor", self.source)

    def test_shared_forward_preserves_scope_and_requires_the_prior_snapshot_migration(self):
        self.assertIn("file_name='20261012115431_editor_application_final_snapshot.sql'", self.shared)
        self.assertIn("rolname='edoc_backend' and not rolbypassrls", self.shared)
        self.assertIn("shared_submission_evidence_source_hash_mismatch", self.shared)
        self.assertIn("pg_advisory_xact_lock", self.shared)
        self.assertTrue(self.shared.rstrip().endswith("commit;"))


if __name__ == "__main__":
    unittest.main()
