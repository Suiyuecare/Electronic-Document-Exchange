"""Exact forward artifacts and closed, backend-only release boundaries."""
import json
from pathlib import Path
import re
import unittest

from tools.editor_metadata_seal_shared_forward import FORWARDS, render_shared_forward
from tools.shared_supabase_bootstrap import ROOT, sha256_text, transform_sql


class EditorMetadataSealSharedForwardTest(unittest.TestCase):
    def test_shared_artifacts_are_exact_hash_bound_atomic_and_ordered(self):
        manifest = json.loads((ROOT / "supabase/verification/migration_manifest.json").read_text())
        for kind, (source_name, forward_name, prerequisite) in FORWARDS.items():
            with self.subTest(kind=kind):
                source = (ROOT / "supabase/migrations" / source_name).read_text()
                transformed = transform_sql(source)
                rendered = render_shared_forward(kind)
                self.assertEqual(rendered, (ROOT / "supabase/shared-project-migrations" / forward_name).read_text())
                self.assertIn(source_name, manifest["migrations"])
                self.assertIn(sha256_text(source), rendered)
                self.assertIn(sha256_text(transformed), rendered)
                self.assertIn(transformed, rendered)
                self.assertIn(f"file_name='{prerequisite}'", rendered)
                self.assertEqual(rendered.count("\nbegin;\n"), 1)
                self.assertTrue(rendered.endswith("commit;\n"))
                self.assertIn("and not rolbypassrls", rendered)
                self.assertIn("shared_editor_metadata_seal_source_hash_mismatch", rendered)
                self.assertNotIn("public.company_seals", rendered)
                self.assertNotIn("to service_role", rendered)
                self.assertNotRegex(rendered.lower(), r"grant execute on all functions")

    def test_shipping_gate_matches_schema_role_and_denial_transform(self):
        public = (ROOT / "supabase/verification/fresh_bootstrap_smoke.sql").read_text()
        shared = (ROOT / "supabase/verification/shared_project_cutover_checks.sql").read_text()
        pattern = r"do \$editor_application_seal_policy_gate\$.*?\$editor_application_seal_policy_gate\$;"
        public_gate = re.search(pattern, public, re.S).group()
        shared_gate = re.search(pattern, shared, re.S).group()
        expected = public_gate.replace("public.", "edoc.").replace("'service_role'", "'edoc_backend'").replace(
            "array['anon','authenticated']", "array['anon','authenticated','service_role','authenticator']")
        self.assertEqual(shared_gate, expected)
        for name in ("edoc_set_company_seal_policy", "edoc_update_editor_application", "edoc_save_editor_revision", "edoc_commit_editor_preflight"):
            self.assertIn(name, public_gate)
            self.assertIn(name, shared_gate)
        self.assertIn("DELETE,TRUNCATE,REFERENCES,TRIGGER", public_gate)
        self.assertIn("v_proc.prosecdef", public_gate)
        self.assertIn("search_path=\"\"", public_gate)


if __name__ == "__main__":
    unittest.main()
