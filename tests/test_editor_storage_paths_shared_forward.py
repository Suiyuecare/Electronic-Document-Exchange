import json
import unittest

from tools.editor_storage_paths_shared_forward import ROOT, SOURCE, FORWARD_NAME, render_shared_forward
from tools.shared_supabase_bootstrap import sha256_text, transform_sql


class EditorStoragePathsSharedForwardTest(unittest.TestCase):
    def test_single_hashed_forward_does_not_rewrite_user_data_or_privileges(self):
        source = (ROOT / 'supabase/migrations' / SOURCE).read_text()
        shared = (ROOT / 'supabase/shared-project-migrations' / FORWARD_NAME).read_text()
        self.assertEqual(shared, render_shared_forward())
        self.assertIn(transform_sql(source), shared)
        self.assertIn(sha256_text(source), shared)
        self.assertIn(sha256_text(transform_sql(source)), shared)
        self.assertNotIn('public.', shared)
        self.assertNotRegex(shared.lower(), r'(?m)^\s*grant\s')
        self.assertNotIn('create table', shared.lower())
        self.assertIn('shared_editor_storage_paths_source_hash_mismatch', shared)
        self.assertTrue(shared.endswith('commit;\n'))
        self.assertEqual(shared.lower().count('\nbegin;\n'), 1)

    def test_source_is_in_active_manifest_and_cutover_inventory(self):
        manifest = json.loads((ROOT / 'supabase/verification/migration_manifest.json').read_text())
        cutover = (ROOT / 'supabase/verification/shared_project_cutover_checks.sql').read_text()
        self.assertIn(SOURCE, manifest['migrations'])
        self.assertIn(f'file_name=\'{SOURCE}\'', cutover)
        self.assertIn(f'migration_ledger) = {len(manifest["migrations"]) + 1}', cutover)

    def test_ci_checks_current_python_paths_against_real_database(self):
        ci = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertIn('tests.test_editor_storage_v2_paths_postgres', ci)
        self.assertIn('local_supabase_editor_upload_pipeline_gate.py', ci)
        self.assertIn('supabase/verification/editor_storage_v2_paths.sql', ci)
