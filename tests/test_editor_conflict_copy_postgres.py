"""Opt-in execution of the real atomic copy RPC and immutable-storage trigger."""
import copy
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import backend
from tests import test_compose_output_postgres as pg_fixture
from tests import test_editor_conflict_copy as local_fixture


@unittest.skipUnless(os.getenv("EDOC_COMPOSE_TEST_PG_PORT"), "isolated PostgreSQL editor-copy gate not enabled")
class EditorConflictCopyPostgresTest(unittest.TestCase):
    namespace = "public"
    backend_role = "service_role"
    cleanup = classmethod(pg_fixture.ComposeOutputPostgresTest.cleanup.__func__)

    @classmethod
    def setUpClass(cls):
        pg_fixture.ComposeOutputPostgresTest.setUpClass.__func__(cls)
        root = Path(__file__).resolve().parents[1]
        cls.pg.execute("CREATE UNIQUE INDEX fixture_editor_job_asset ON official_document_editor_storage_jobs(asset_id)")
        for name in ("20260827194500_promote_editor_tus_staging_to_immutable.sql", "20260911133603_editor_conflict_copy_atomic.sql"):
            cls.pg.execute((root / "supabase/migrations" / name).read_text())
        cls.pg.execute("GRANT SELECT,INSERT,UPDATE ON ALL TABLES IN SCHEMA public TO service_role")

    def test_atomic_copy_retry_and_backend_only_access(self):
        fixture = local_fixture.EditorConflictCopyTest()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        session, source_id, payload = fixture.source()
        captured = []
        original = backend._editor_conflict_copy_bundle
        def capture(*args, **kwargs):
            result = original(*args, **kwargs)
            captured.append(copy.deepcopy(result))
            return result
        with patch.object(backend, "_editor_conflict_copy_bundle", side_effect=capture):
            backend.copy_official_editor_conflict(fixture.conn, source_id, payload, session)
        bundle = captured[0]
        types = pg_fixture.canonical_column_types()
        for table, row in (("companies", backend.official_company_row(fixture.conn, "CO-001")),
                           ("users", dict(fixture.conn.execute("SELECT * FROM users WHERE id=?", (session["user"]["id"],)).fetchone())),
                           ("official_documents", backend.official_document_row(fixture.conn, source_id))):
            clean = {key: bool(value) if types.get((table, key)) == "boolean" and value is not None else value for key, value in row.items()}
            self.pg.execute(f"INSERT INTO public.{table} SELECT * FROM jsonb_populate_record(NULL::public.{table}, %s::jsonb)", (json.dumps(clean),))
        for item in bundle["file_objects"]:
            item["storage_provider"] = "supabase"
        for role in ("anon", "authenticated"):
            with self.pg.transaction():
                self.pg.execute(f"SET LOCAL ROLE {role}")
                with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                    with self.pg.transaction():
                        self.pg.execute("SELECT public.edoc_copy_editor_conflict(%s::jsonb)", (json.dumps(bundle),))
        with self.pg.transaction():
            self.pg.execute("SET LOCAL ROLE service_role")
            first = self.pg.execute("SELECT public.edoc_copy_editor_conflict(%s::jsonb)", (json.dumps(bundle),)).fetchone()[0]
            second = self.pg.execute("SELECT public.edoc_copy_editor_conflict(%s::jsonb)", (json.dumps(bundle),)).fetchone()[0]
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(first["document_id"], second["document_id"])
        new_id = first["document_id"]
        self.assertEqual(self.pg.execute("SELECT count(*) FROM official_document_editor_revisions WHERE document_id=%s", (new_id,)).fetchone()[0], 1)
        self.assertEqual(self.pg.execute("SELECT status FROM official_document_editor_storage_jobs WHERE document_id=%s", (new_id,)).fetchone()[0], "committed")
        self.assertEqual(self.pg.execute("SELECT count(*) FROM official_document_approval_logs WHERE document_id=%s AND action='editor_conflict_copy'", (new_id,)).fetchone()[0], 1)
        self.pg.execute("UPDATE official_documents SET current_status='pending_applicant_manager' WHERE id=%s", (source_id,))
        with self.pg.transaction():
            self.pg.execute("SET LOCAL ROLE service_role")
            with self.assertRaisesRegex(self.psycopg.Error, "editor_locked_after_submit"):
                with self.pg.transaction():
                    self.pg.execute("SELECT public.edoc_copy_editor_conflict(%s::jsonb)", (json.dumps(bundle),))
