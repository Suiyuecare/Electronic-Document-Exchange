"""Real PostgreSQL contract gate for opaque v2 upload intent and final binding.

Uses a random loopback-only database, actual released trigger/CHECK DDL and
the shipping Python intent builder. All names and bytes are synthetic.
"""
from __future__ import annotations

import json
import re
import unittest
import uuid
from contextlib import ExitStack
from datetime import datetime, timedelta
from unittest import mock

import backend
from tests import test_compose_output_postgres as fixture
from tools.shared_supabase_bootstrap import transform_sql
from tools.editor_storage_paths_shared_forward import FORWARD_NAME, render_shared_forward


MIGRATION = "20260913130517_editor_storage_v2_opaque_paths.sql"
BASE_MIGRATION = "20260827194500_promote_editor_tus_staging_to_immutable.sql"


@unittest.skipUnless(fixture.PORT, "isolated PostgreSQL opaque storage gate not enabled")
class EditorStorageV2PathsPostgresTest(unittest.TestCase):
    namespace = "public"
    backend_role = "service_role"
    cleanup = classmethod(fixture.ComposeOutputPostgresTest.cleanup.__func__)
    create = fixture.ComposeOutputPostgresTest.create

    @classmethod
    def setUpClass(cls):
        fixture.ComposeOutputPostgresTest.setUpClass.__func__(cls)
        cls.pg.execute("SET ROLE postgres")
        try:
            # Replace only this lightweight fixture's constraint-free table
            # with the exact released Storage lifecycle table and triggers.
            cls.pg.execute(f"DROP TABLE {cls.namespace}.official_document_editor_storage_jobs")
            base = (fixture.ROOT / "supabase/migrations" / BASE_MIGRATION).read_text()
            cls.pg.execute(base if cls.namespace == "public" else transform_sql(base))
            cls.pg.execute(f"GRANT SELECT,INSERT,UPDATE ON {cls.namespace}.official_document_editor_assets TO {cls.backend_role}")
            if cls.namespace == "edoc":
                cls.pg.execute("CREATE POLICY fixture_storage_backend ON edoc.official_document_editor_storage_jobs TO edoc_backend USING (true) WITH CHECK (true)")
            cls.sql = (fixture.ROOT / "supabase/migrations" / MIGRATION).read_text()
            cls.verification = (fixture.ROOT / "supabase/verification/editor_storage_v2_paths.sql").read_text()
            if cls.namespace != "public":
                for predecessor in (BASE_MIGRATION, "20260913060040_editor_cross_company_workflow_scope.sql"):
                    cls.pg.execute("INSERT INTO edoc_private.shared_project_migration_ledger(file_name) VALUES (%s) ON CONFLICT DO NOTHING", (predecessor,))
                cls.sql = (fixture.ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text()
                if cls.sql != render_shared_forward():
                    raise AssertionError("shared_storage_forward_stale")
                cls.verification = transform_sql(cls.verification)
            # Reproduce the production failure before installing the fix.
            instance = cls(methodName="test_current_python_intent_and_final_binding")
            with cls.pg.transaction(force_rollback=True):
                instance.pre_fix_case = instance.seed()
                asset, job = instance.pre_fix_case
                instance.insert("official_document_editor_assets", asset)
                try:
                    with cls.pg.transaction():
                        instance.insert("official_document_editor_storage_jobs", job)
                except cls.psycopg.Error as error:
                    cls.pre_fix_error = str(error).splitlines()[0]
                else:
                    raise AssertionError("v2_path_regression_not_reproduced")
            cls.pg.execute(cls.sql)
            cls.pg.execute(cls.verification)
        finally:
            cls.pg.execute("RESET ROLE")

    def insert(self, table, values):
        from psycopg import sql
        query = sql.SQL("INSERT INTO {}.{} ({}) VALUES ({}) RETURNING *").format(
            sql.Identifier(self.namespace), sql.Identifier(table),
            sql.SQL(",").join(map(sql.Identifier, values)),
            sql.SQL(",").join(sql.Placeholder() for _ in values),
        )
        with self.pg.transaction():
            self.pg.execute(f"SET LOCAL ROLE {self.backend_role}")
            cursor = self.pg.execute(query, tuple(values.values()))
            return dict(zip((column.name for column in cursor.description), cursor.fetchone()))

    def seed(self, *, version=2, mime="application/pdf", name="測試合約.pdf", kind="source_pdf"):
        suffix = uuid.uuid4().hex
        doc_id, asset_id = "OD-QA-" + suffix, "ODASSET-QA-" + suffix
        self.create(doc_id, source_type="uploaded_pdf", document_type="electronic_seal_pdf_editor_v2", output_mode="physical", requires_stamp=True)
        revision_id = "ODREV-QA-" + suffix
        self.pg.execute("INSERT INTO official_document_editor_revisions(id,document_id,revision_no) VALUES (%s,%s,1)", (revision_id, doc_id))
        digest = "A" * 64
        extension = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}.get(mime, "bin")
        is_v2 = version is not None
        staging = f"editor/{doc_id}/{asset_id}.{extension}" if is_v2 else f"editor/{doc_id}/{asset_id}-{name}"
        final = f"editor-final/{doc_id}/{asset_id}/{digest}.{extension}" if is_v2 else f"editor-final/{doc_id}/{asset_id}/{digest}-{name}"
        expires = (datetime.now() + timedelta(hours=2)).isoformat(timespec="seconds")
        metadata = {"base_revision_no": 1, "expires_at": expires}
        if version is not None:
            metadata["storage_key_version"] = version
        asset = {
            "id": asset_id, "document_id": doc_id, "editor_revision_id": revision_id,
            "asset_kind": kind, "file_name": name, "mime_type": mime, "size_bytes": 128,
            "sha256": "", "expected_sha256": digest, "storage_bucket": "edoc-private", "storage_path": staging,
            "upload_status": "pending", "scan_status": "pending", "preflight_status": "pending", "page_count": 0,
            "metadata_json": json.dumps(metadata), "created_by": "APPLICANT", "created_at": backend.now(),
        }
        job = {
            "id": "JOB-" + asset_id, "asset_id": asset_id, "document_id": doc_id,
            "staging_bucket": "edoc-private", "staging_path": staging,
            "final_bucket": "edoc-private", "final_path": final, "expected_sha256": digest,
            "expected_size_bytes": 128, "token_expires_at": expires, "status": "pending",
            "lease_token": "", "lease_expires_at": "", "attempt_count": 0, "last_error_code": "",
            "created_at": backend.now(), "updated_at": backend.now(),
        }
        return asset, job

    def intent(self, *, mime="application/pdf", name="測試合約.pdf", kind="source_pdf"):
        template, _ = self.seed(mime=mime, name=name, kind=kind)
        with ExitStack() as stack:
            patches = {
                "require_production_editor_runtime_ready": None,
                "supabase_official_document_row": {"id": template["document_id"], "company_id": "CO-COMPOSE"},
                "_supabase_editor_assert_document_access": {"id": "APPLICANT"},
                "supabase_cleanup_stale_official_editor_uploads": None,
                "_supabase_editor_latest_revision": {"id": template["editor_revision_id"], "revision_no": 1},
            }
            for name_, value in patches.items():
                stack.enter_context(mock.patch.object(backend, name_, return_value=value))
            stack.enter_context(mock.patch.object(backend, "supabase_insert", side_effect=self.insert))
            return backend.supabase_create_official_editor_upload_intent(template["document_id"], {
                "asset_kind": kind, "file_name": name, "mime_type": mime, "size_bytes": 128, "sha256": "A" * 64,
            }, {"user": {"id": "APPLICANT"}}, issue_upload_capability=False)

    def rows(self, asset_id):
        from psycopg.rows import dict_row
        with self.pg.cursor(row_factory=dict_row) as cursor:
            asset = cursor.execute("SELECT * FROM official_document_editor_assets WHERE id=%s", (asset_id,)).fetchone()
            job = cursor.execute("SELECT * FROM official_document_editor_storage_jobs WHERE asset_id=%s", (asset_id,)).fetchone()
        return asset, job

    def promote(self, asset, job):
        file_id = "FILE-" + uuid.uuid4().hex
        self.pg.execute("INSERT INTO file_objects(id,document_id,file_name,mime_type,storage_key,bucket,storage_provider,sha256,size_bytes) VALUES (%s,%s,%s,%s,%s,'edoc-private','supabase',%s,128)",
                        (file_id, asset["document_id"], asset["file_name"], asset["mime_type"], job["final_path"], asset["expected_sha256"]))
        lease = (datetime.now() + timedelta(minutes=4)).isoformat(timespec="seconds")
        with self.pg.transaction():
            self.pg.execute(f"SET LOCAL ROLE {self.backend_role}")
            self.pg.execute("UPDATE official_document_editor_storage_jobs SET status='promoting',lease_token=%s,lease_expires_at=%s,attempt_count=1 WHERE id=%s", ("B" * 32, lease, job["id"]))
        return file_id

    def finalize(self, asset, file_id, **patch):
        from psycopg import sql
        values = {"file_object_id": file_id, "sha256": asset["expected_sha256"], "upload_status": "finalized", **patch}
        assignments = sql.SQL(",").join(sql.SQL("{}=%s").format(sql.Identifier(key)) for key in values)
        with self.pg.transaction():
            self.pg.execute(f"SET LOCAL ROLE {self.backend_role}")
            self.pg.execute(sql.SQL("UPDATE official_document_editor_assets SET {} WHERE id=%s").format(assignments), (*values.values(), asset["id"]))

    def test_current_python_intent_and_final_binding(self):
        self.assertIn("editor_storage_job_binding_invalid", self.pre_fix_error)
        for mime, name, kind in (("application/pdf", "測試聘僱合約.pdf", "source_pdf"), ("application/pdf", "合併😀[2]%.pdf", "import_pdf"), ("image/png", "圖片.png", "image"), ("image/jpeg", "圖片.jpg", "image")):
            with self.subTest(mime=mime, kind=kind):
                intent = self.intent(mime=mime, name=name, kind=kind)
                asset, job = self.rows(intent["asset_id"])
                self.assertEqual(asset["file_name"], name)
                self.assertNotIn(name, job["final_path"])
                file_id = self.promote(asset, job)
                self.finalize(asset, file_id)
                final, committed = self.rows(asset["id"])
                self.assertEqual(final["storage_path"], job["final_path"])
                self.assertEqual((committed["status"], committed["final_file_object_id"]), ("committed", file_id))
                with self.assertRaisesRegex(self.psycopg.Error, "editor_finalized_asset_immutable"):
                    self.finalize(final, file_id, mime_type="text/plain")

    def test_legacy_pending_and_finalized_rows_survive_forward_replay(self):
        asset, job = self.seed(version=None, name="legacy-ascii.pdf")
        self.insert("official_document_editor_assets", asset)
        self.insert("official_document_editor_storage_jobs", job)
        file_id = self.promote(asset, job)
        self.finalize(asset, file_id)
        before = self.rows(asset["id"])
        self.pg.execute("SET ROLE postgres")
        try:
            self.pg.execute(self.sql)
        finally:
            self.pg.execute("RESET ROLE")
        self.assertEqual(before, self.rows(asset["id"]))
        if self.namespace == "edoc":
            self.assertEqual([("HR", "unchanged")], self.pg.execute("SELECT * FROM public.hr_untouched").fetchall())

    def test_version_mime_hash_and_identity_tampering_rejected(self):
        mutations = (
            ({"metadata_json": '{"storage_key_version":"2"}'}, {}),
            ({"metadata_json": '{"storage_key_version":3}'}, {}),
            ({"metadata_json": '{}'}, {}),
            ({"mime_type": "image/png"}, {}),
            ({}, {"expected_sha256": "B" * 64}),
            ({}, {"final_path": "editor-final/OTHER/ASSET/" + "A" * 64 + ".pdf"}),
            ({}, {"staging_path": "editor/OTHER/ASSET.pdf"}),
            ({}, {"expected_size_bytes": 129}),
        )
        for asset_patch, job_patch in mutations:
            with self.subTest(asset_patch=sorted(asset_patch), job_patch=sorted(job_patch)):
                asset, job = self.seed()
                self.insert("official_document_editor_assets", {**asset, **asset_patch})
                with self.assertRaises(self.psycopg.Error):
                    self.insert("official_document_editor_storage_jobs", {**job, **job_patch})

    def test_final_binding_rejects_version_and_mime_changes(self):
        for patch in ({"metadata_json": '{}'}, {"metadata_json": '{"storage_key_version":"2"}'}, {"mime_type": "image/png"}, {"file_name": "changed.pdf"}, {"sha256": "B" * 64}):
            asset, job = self.seed()
            self.insert("official_document_editor_assets", asset)
            self.insert("official_document_editor_storage_jobs", job)
            file_id = self.promote(asset, job)
            with self.assertRaises(self.psycopg.Error):
                self.finalize(asset, file_id, **patch)
            self.assertEqual("pending", self.rows(asset["id"])[0]["upload_status"])

    def test_table_and_trigger_access_remains_private(self):
        for role in ("anon", "authenticated"):
            self.assertFalse(self.pg.execute("SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE')", (role, self.namespace + ".official_document_editor_storage_jobs")).fetchone()[0])
        for function, definer in (("edoc_guard_editor_storage_job", False), ("edoc_bind_finalized_editor_asset_storage", True)):
            row = self.pg.execute("SELECT prosecdef,pg_get_userbyid(proowner),proconfig FROM pg_proc WHERE oid=%s::regprocedure", (self.namespace + "." + function + "()",)).fetchone()
            self.assertEqual(row[:2], (definer, "postgres"))
            self.assertTrue(any(item in ('search_path=', 'search_path=""') for item in row[2]))
        self.assertEqual((True, True), self.pg.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass", (self.namespace + ".official_document_editor_storage_jobs",)).fetchone())

    def test_readonly_gate_rejects_legacy_trigger_or_unvalidated_constraint(self):
        base = (fixture.ROOT / "supabase/migrations" / BASE_MIGRATION).read_text()
        if self.namespace == "edoc":
            base = transform_sql(base)
        original_guard = re.search(r"create or replace function [a-z_]+\.edoc_guard_editor_storage_job\(\).*?\$function\$;", base, re.S).group(0)
        with self.pg.transaction(force_rollback=True):
            self.pg.execute("SET LOCAL ROLE postgres")
            self.pg.execute(original_guard)
            with self.assertRaisesRegex(self.psycopg.Error, "editor_storage_v2_trigger_missing"):
                with self.pg.transaction():
                    self.pg.execute(self.verification)
        original_check = re.search(r"constraint official_editor_storage_job_path_check\s+check \(.*?\n    \),", base, re.S).group(0).rstrip(",")
        with self.pg.transaction(force_rollback=True):
            self.pg.execute("SET LOCAL ROLE postgres")
            self.pg.execute("ALTER TABLE official_document_editor_storage_jobs DROP CONSTRAINT official_editor_storage_job_path_check")
            self.pg.execute("ALTER TABLE official_document_editor_storage_jobs ADD " + original_check + " NOT VALID")
            with self.assertRaisesRegex(self.psycopg.Error, "editor_storage_v2_path_constraint_missing"):
                with self.pg.transaction():
                    self.pg.execute(self.verification)
        self.pg.execute(self.verification)


@unittest.skipUnless(fixture.PORT, "isolated PostgreSQL opaque storage gate not enabled")
class SharedEditorStorageV2PathsPostgresTest(EditorStorageV2PathsPostgresTest):
    namespace = "edoc"
    backend_role = "edoc_backend"
