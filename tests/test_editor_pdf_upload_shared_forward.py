from __future__ import annotations

import json
import unittest

from tools.editor_pdf_upload_shared_forward import ROOT, SOURCE, FORWARD_NAME, render_shared_forward
from tools.shared_supabase_bootstrap import sha256_text, transform_sql
from tests import test_compose_output_postgres as postgres_fixture


class EditorPdfUploadSharedForwardTest(unittest.TestCase):
    def test_committed_forward_is_exactly_generated_and_hash_bound(self):
        source = (ROOT / "supabase/migrations" / SOURCE).read_text()
        transformed = transform_sql(source)
        shared = (ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text()
        self.assertEqual(shared, render_shared_forward())
        self.assertIn(transformed, shared)
        self.assertIn(sha256_text(source), shared)
        self.assertIn(sha256_text(transformed), shared)
        self.assertNotIn("public.", shared)
        self.assertIn("edoc_private.shared_project_migration_ledger", shared)
        self.assertIn("shared_editor_pdf_upload_source_hash_mismatch", shared)
        self.assertTrue(shared.endswith("commit;\n"))
        self.assertEqual(shared.lower().count("\nbegin;\n"), 1)

    def test_migration_and_shared_cutover_inventory_are_complete(self):
        manifest = json.loads((ROOT / "supabase/verification/migration_manifest.json").read_text())
        cutover = (ROOT / "supabase/verification/shared_project_cutover_checks.sql").read_text()
        self.assertIn(SOURCE, manifest["migrations"])
        self.assertIn(f"file_name='{SOURCE}'", cutover)
        self.assertIn(f"migration_ledger) = {len(manifest['migrations']) + 1}", cutover)
        self.assertIn("editor_pdf_preflight_status_guard", cutover)


@unittest.skipUnless(postgres_fixture.PORT, "isolated PostgreSQL shared PDF upload gate not enabled")
class EditorPdfUploadSharedForwardPostgresTest(postgres_fixture.ComposeOutputPostgresTest):
    namespace = "edoc"
    backend_role = "edoc_backend"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pg.execute("SET ROLE postgres")
        try:
            for name in (
                "20260827194500_promote_editor_tus_staging_to_immutable.sql",
                "20260911133603_editor_conflict_copy_atomic.sql",
            ):
                source = (ROOT / "supabase/migrations" / name).read_text()
                cls.pg.execute(transform_sql(source))
            cls.pg.execute(
                "INSERT INTO edoc_private.shared_project_migration_ledger(file_name) VALUES (%s),(%s) ON CONFLICT DO NOTHING",
                (
                    "20260913130517_editor_storage_v2_opaque_paths.sql",
                    "20260922074613_configurable_official_workflows.sql",
                ),
            )
            cls.pg.execute(render_shared_forward())
            cls.pg.execute(render_shared_forward())
        finally:
            cls.pg.execute("RESET ROLE")

    def test_shared_forward_replays_once_and_keeps_pdf_preflight_narrow(self):
        source = (ROOT / "supabase/migrations" / SOURCE).read_text()
        row = self.pg.execute(
            "SELECT source_sha256,transformed_sha256,bundle_version FROM edoc_private.shared_project_migration_ledger WHERE file_name=%s",
            (SOURCE,),
        ).fetchone()
        self.assertEqual(row, (sha256_text(source), sha256_text(transform_sql(source)), "shared-project-schema-v1"))
        self.assertEqual(
            1,
            self.pg.execute(
                "SELECT count(*) FROM edoc_private.shared_project_migration_ledger WHERE file_name=%s",
                (SOURCE,),
            ).fetchone()[0],
        )
        constraint = self.pg.execute(
            "SELECT pg_catalog.pg_get_constraintdef(oid) FROM pg_catalog.pg_constraint WHERE conrelid='edoc.official_document_editor_assets'::regclass AND conname='official_editor_asset_scan_status_check'"
        ).fetchone()[0]
        self.assertIn("not_scanned", constraint)
        validator = self.pg.execute(
            "SELECT pg_catalog.pg_get_functiondef('edoc_private.validate_official_document_decision_evidence(text,text,text,text,text,jsonb)'::regprocedure)"
        ).fetchone()[0]
        finalize = self.pg.execute(
            "SELECT pg_catalog.pg_get_functiondef('edoc.edoc_finalize_editor_asset_v2(jsonb)'::regprocedure)"
        ).fetchone()[0]
        conflict_copy = self.pg.execute(
            "SELECT pg_catalog.pg_get_functiondef('edoc.edoc_copy_editor_conflict(jsonb)'::regprocedure)"
        ).fetchone()[0]
        self.assertIn("preflight_status = 'passed'", validator)
        self.assertIn("asset_kind not in ('source_pdf', 'import_pdf')", finalize)
        self.assertIn("asset_kind' IN ('source_pdf', 'import_pdf')", conflict_copy)


if __name__ == "__main__":
    unittest.main()
