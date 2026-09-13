import json
import unittest

from tools.editor_applicant_shared_forward import ROOT, SOURCES, FORWARD_NAME, render_shared_forward
from tools.shared_supabase_bootstrap import sha256_text, transform_sql
from tests import test_compose_resilience_postgres as resilience


class EditorApplicantSharedForwardTest(unittest.TestCase):
    def test_exact_two_frozen_forwards_with_verified_hashes(self):
        shared = (ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text()
        self.assertEqual(shared, render_shared_forward())
        self.assertEqual(len(SOURCES), 2)
        for name in SOURCES:
            source = (ROOT / "supabase/migrations" / name).read_text()
            transformed = transform_sql(source)
            self.assertIn(transformed, shared)
            self.assertIn(sha256_text(source), shared)
            self.assertIn(sha256_text(transformed), shared)
        self.assertNotIn("public.", shared)
        self.assertEqual(shared.lower().count("\nbegin;\n"), 1)
        self.assertTrue(shared.endswith("commit;\n"))

    def test_narrow_forward_never_replays_bootstrap_or_changes_existing_privileges(self):
        shared = render_shared_forward()
        self.assertIn("where rolname='edoc_backend' and not rolbypassrls", shared)
        self.assertIn("shared_editor_applicant_source_hash_mismatch", shared)
        self.assertIn("source_sha256,transformed_sha256,bundle_version", shared)
        self.assertNotIn("create table", shared.lower())
        self.assertNotIn("grant ", shared.lower())
        self.assertNotIn("security definer", shared.lower())
        self.assertIn("security invoker set search_path = ''", shared)

    def test_cutover_checks_include_both_forwards(self):
        manifest = json.loads((ROOT / "supabase/verification/migration_manifest.json").read_text())
        shared = (ROOT / "supabase/verification/shared_project_cutover_checks.sql").read_text()
        self.assertIn(f"migration_ledger) = {len(manifest['migrations']) + 1}", shared)
        for name in SOURCES:
            self.assertIn(name, manifest["migrations"])
            self.assertIn(f"file_name='{name}'", shared)


@unittest.skipUnless(resilience.fixture.PORT, "isolated PostgreSQL forward gate not enabled")
class EditorApplicantSharedForwardPostgresTest(unittest.TestCase):
    namespace = "edoc"
    backend_role = "edoc_backend"
    cleanup = classmethod(resilience.fixture.ComposeOutputPostgresTest.cleanup.__func__)

    @classmethod
    def setUpClass(cls):
        resilience.ComposeResiliencePostgresTest.setUpClass.__func__(cls)
        cls.pg.execute("SET ROLE postgres")
        try:
            # Match the already-released syntax repair omitted by the minimal
            # historical fixture; do not alter actor/lock/access predicates.
            signature = "edoc.edoc_apply_official_document_correction(text,text,text,jsonb,text,jsonb,jsonb,text,jsonb,jsonb,text,text,text,text,text,text,jsonb,text,text)"
            definition = cls.pg.execute("SELECT pg_get_functiondef(%s::regprocedure)", (signature,)).fetchone()[0]
            if definition.count("pg_catalog.coalesce(") != 15 or definition.count("pg_catalog.nullif(") != 1:
                raise AssertionError("released_correction_special_form_fixture_drift")
            cls.pg.execute(definition.replace("pg_catalog.coalesce(", "coalesce(").replace("pg_catalog.nullif(", "nullif("))
            cls.pg.execute(render_shared_forward())
            cls.pg.execute(render_shared_forward())
        finally:
            cls.pg.execute("RESET ROLE")

    def test_exact_forward_and_replay_preserve_ledger_hashes_and_private_helpers(self):
        for name in SOURCES:
            source = (ROOT / "supabase/migrations" / name).read_text()
            row = self.pg.execute("SELECT source_sha256,transformed_sha256 FROM edoc_private.shared_project_migration_ledger WHERE file_name=%s", (name,)).fetchone()
            self.assertEqual(row, (sha256_text(source), sha256_text(transform_sql(source))))
        self.assertEqual(self.pg.execute("SELECT count(*) FROM edoc_private.shared_project_migration_ledger WHERE file_name=ANY(%s)", (list(SOURCES),)).fetchone()[0], 2)
        for role in ("anon", "authenticated", "service_role", "authenticator", "edoc_backend"):
            self.assertFalse(self.pg.execute("SELECT has_function_privilege(%s,'edoc_private.editor_v2_case_participant(text,text)','EXECUTE')", (role,)).fetchone()[0])
