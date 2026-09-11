"""Actual isolated PostgreSQL RPC checks; never targets a hosted project."""
import json
import os
import re
import unittest
import uuid
from tests import test_compose_output_postgres as fixture
from tools.shared_supabase_bootstrap import transform_sql
from tools.compose_editor_shared_forward import FORWARD_NAME, render_shared_forward


@unittest.skipUnless(fixture.PORT, "isolated PostgreSQL compose gate not enabled")
class ComposeResiliencePostgresTest(unittest.TestCase):
    namespace = "public"
    backend_role = "service_role"
    cleanup = classmethod(fixture.ComposeOutputPostgresTest.cleanup.__func__)
    create = fixture.ComposeOutputPostgresTest.create
    submission = fixture.ComposeOutputPostgresTest.submission
    call_submit = fixture.ComposeOutputPostgresTest.call_submit

    @classmethod
    def setUpClass(cls):
        fixture.ComposeOutputPostgresTest.setUpClass.__func__(cls)
        # Exercise the actual new DDL (constraints/ownership included), not
        # SQLite's loose fixture projection of these newly-added objects.
        cls.pg.execute(f"DROP TABLE {cls.namespace}.official_document_compose_drafts")
        cls.pg.execute(f"ALTER TABLE {cls.namespace}.official_documents DROP COLUMN content_revision")
        sql = (fixture.ROOT / "supabase/migrations/20260911133144_compose_resilience_drafts_revision.sql").read_text()
        cls.pg.execute("SET ROLE postgres")
        try:
            if cls.namespace == "public":
                cls.pg.execute(sql)
                cls.pg.execute((fixture.ROOT / "supabase/migrations/20260911133603_editor_conflict_copy_atomic.sql").read_text())
            else:
                shared = (fixture.ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text()
                if shared != render_shared_forward(): raise AssertionError("shared_forward_source_drift")
                cls.pg.execute(shared)
                cls.pg.execute(shared)  # Exact release replay is safe and does not reapply source changes.
        finally:
            cls.pg.execute("RESET ROLE")
        cls.pg.execute("INSERT INTO users(id,name,status,company_id,email) VALUES ('APPLICANT','Isolated applicant','啟用','CO-COMPOSE','isolated@example.test') ON CONFLICT(id) DO NOTHING")
        cls.pg.execute(f"GRANT SELECT ON {cls.namespace}.users TO {cls.backend_role}")

    def save(self, key, revision, subject, actor="APPLICANT", company="CO-COMPOSE"):
        payload = {"userId": actor, "companyId": company, "values": {"#subject": subject}}
        with self.pg.transaction():
            self.pg.execute(f"SET LOCAL ROLE {self.backend_role}")
            return self.pg.execute(f"SELECT {self.namespace}.edoc_save_compose_draft(%s,%s,%s,%s,%s::jsonb,%s,false)", (key, actor, company, revision, json.dumps(payload), subject)).fetchone()[0]

    def test_cloud_rpc_replay_conflict_and_scope(self):
        key = "OD-" + str(uuid.uuid4())
        first = self.save(key, 0, "one")
        self.assertEqual(self.save(key, 0, "one")["revision"], 1)
        self.assertEqual(self.save(key, 1, "two")["revision"], 2)
        with self.assertRaisesRegex(self.psycopg.Error, "compose_draft_revision_conflict"):
            self.save(key, 1, "stale")
        with self.assertRaisesRegex(self.psycopg.Error, "scope_forbidden"):
            self.save(key, 2, "cross", company="OTHER")
        self.assertEqual(first["revision"], 1)

    def test_anon_authenticated_have_no_table_or_rpc_access(self):
        for role in ("anon", "authenticated"):
            for sql in (f"SELECT * FROM {self.namespace}.official_document_compose_drafts", f"SELECT {self.namespace}.edoc_save_compose_draft('x','x','x',0,'{{}}'::jsonb,'x',false)"):
                with self.pg.transaction():
                    self.pg.execute(f"SET LOCAL ROLE {role}")
                    with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                        with self.pg.transaction(): self.pg.execute(sql)

    def test_submission_same_timestamp_changed_revision_refused(self):
        doc_id = "revision-submit-" + uuid.uuid4().hex
        payload = self.submission(doc_id)
        payload["expected_content_revision"] = 0
        self.pg.execute("UPDATE official_documents SET content_revision=1 WHERE id=%s", (doc_id,))
        with self.assertRaisesRegex(self.psycopg.Error, "compose_content_revision_conflict"):
            self.call_submit(payload)
        self.assertEqual(self.pg.execute("SELECT current_status FROM official_documents WHERE id=%s", (doc_id,)).fetchone()[0], "draft")

    def test_correction_version_check_runs_inside_rpc_row_lock(self):
        doc_id = "revision-correction-" + uuid.uuid4().hex
        self.create(doc_id)
        patch = {"workflow_template_key": "fixture", "metadata_json": {}, "_expected_content_revision": 8}
        arguments = [doc_id, "APPLICANT", "CO-COMPOSE", json.dumps(patch), "", "[]", "[]", "", "[]", "[]", "", "", "", "Fixture", "", "", "[]", "", ""]
        sql = f"SELECT {self.namespace}.edoc_apply_official_document_correction(%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)"
        with self.pg.transaction():
            self.pg.execute(f"SET LOCAL ROLE {self.backend_role}")
            with self.assertRaisesRegex(self.psycopg.Error, "compose_content_revision_conflict"):
                with self.pg.transaction(): self.pg.execute(sql, arguments)

    def repair_gate(self):
        name = "fresh_bootstrap_smoke.sql" if self.namespace == "public" else "shared_project_cutover_checks.sql"
        sql = (fixture.ROOT / "supabase/verification" / name).read_text()
        return re.search(r"do \$compose_editor_resilience_gate\$.*?\$compose_editor_resilience_gate\$;", sql, re.S).group(0)

    def test_active_release_repair_gate_passes_real_ddl(self):
        self.pg.execute(self.repair_gate())

    def test_active_release_repair_gate_rejects_partial_migration_or_grant_drift(self):
        changes = (
            (f"ALTER TABLE {self.namespace}.official_document_compose_drafts DISABLE ROW LEVEL SECURITY", "draft_table_security_missing"),
            (f"REVOKE UPDATE ON {self.namespace}.official_document_compose_drafts FROM {self.backend_role}", "backend_table_grant_missing"),
            (f"GRANT SELECT ON {self.namespace}.official_document_compose_drafts TO anon", "browser_table_grant"),
            (f"ALTER TABLE {self.namespace}.official_documents DROP COLUMN content_revision", "content_revision_missing"),
            (f"DROP INDEX {self.namespace}.idx_compose_draft_owner", "draft_relationships_missing"),
            (f"GRANT EXECUTE ON FUNCTION {self.namespace}.edoc_copy_editor_conflict(jsonb) TO PUBLIC", "browser_rpc_grant"),
            (f"REVOKE EXECUTE ON FUNCTION {self.namespace}.edoc_save_compose_draft(text,text,text,integer,jsonb,text,boolean) FROM {self.backend_role}", "rpc_security_mismatch"),
        )
        for mutation, code in changes:
            with self.subTest(code=code), self.pg.transaction(force_rollback=True):
                self.pg.execute(mutation)
                with self.assertRaisesRegex(self.psycopg.Error, code):
                    with self.pg.transaction(): self.pg.execute(self.repair_gate())


@unittest.skipUnless(fixture.PORT, "isolated PostgreSQL compose gate not enabled")
class SharedComposeResiliencePostgresTest(ComposeResiliencePostgresTest):
    namespace = "edoc"
    backend_role = "edoc_backend"
