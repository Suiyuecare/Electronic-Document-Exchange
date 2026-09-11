import unittest
import json
import re
from tools.compose_editor_shared_forward import FORWARD_NAME, SOURCES, ROOT, render_shared_forward
from tools.shared_supabase_bootstrap import sha256_text, transform_sql

class ComposeEditorSharedForwardTest(unittest.TestCase):
    def test_release_artifact_matches_frozen_source_hashes(self):
        shared = (ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text()
        self.assertEqual(shared, render_shared_forward())
        for name in SOURCES:
            source = (ROOT / "supabase/migrations" / name).read_text()
            self.assertIn(transform_sql(source), shared)
            self.assertIn(sha256_text(source), shared)
        self.assertNotIn("public.", shared)
        self.assertEqual(shared.lower().count("\nbegin;\n"), 1)
        self.assertTrue(shared.endswith("commit;\n"))

    def test_shared_backend_only_privileges_and_non_bypass_role(self):
        shared = render_shared_forward()
        self.assertIn("where rolname='edoc_backend' and not rolbypassrls", shared)
        self.assertIn("create policy edoc_backend_compose_drafts", shared)
        self.assertIn("from public,anon,authenticated,service_role,authenticator", shared)
        self.assertIn("shared_compose_editor_source_hash_mismatch", shared)

    def test_active_cutover_gates_cover_current_manifest_and_match_security_rules(self):
        public = (ROOT / "supabase/verification/fresh_bootstrap_smoke.sql").read_text()
        shared = (ROOT / "supabase/verification/shared_project_cutover_checks.sql").read_text()
        pattern = r"do \$compose_editor_resilience_gate\$.*?\$compose_editor_resilience_gate\$;"
        public_gate = re.search(pattern, public, re.S).group(0)
        expected_shared = public_gate.replace("v_schema text := 'public';", "v_schema text := 'edoc';").replace(
            "v_backend text := 'service_role';", "v_backend text := 'edoc_backend';",
        ).replace("v_denied text[] := array['anon','authenticated'];", "v_denied text[] := array['anon','authenticated','service_role','authenticator'];")
        self.assertEqual(re.search(pattern, shared, re.S).group(0), expected_shared)
        manifest = json.loads((ROOT / "supabase/verification/migration_manifest.json").read_text())
        self.assertIn(f"migration_ledger) = {len(manifest['migrations']) + 1}", shared)
        self.assertIn("('r','p','v','m')) = 96", shared)
        for name in SOURCES:
            self.assertIn(f"file_name='{name}'", shared)
