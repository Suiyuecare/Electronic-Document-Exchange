"""Opt-in PostgreSQL execution gate for compose output migrations/RPCs.

Only an ephemeral randomly named database on a local test cluster is touched.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import unittest
import uuid
from pathlib import Path

import backend
from tools.shared_supabase_bootstrap import transform_sql
from tools.compose_shared_forward import FORWARD_NAME


PORT = os.getenv("EDOC_COMPOSE_TEST_PG_PORT")
ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [
    "20260827050436_complete_edoc_runtime_schema_parity.sql",
    "20260827050450_atomic_official_submission_editor_finalize_forward.sql",
    "20260827133545_fix_official_document_function_type_resolution.sql",
    "20260908135730_immutable_official_document_numbering.sql",
    "20260908135911_compose_electronic_output_dispatch_date.sql",
]


def canonical_column_types():
    """Read SQL-declared types so SQLite's booleans/JSON use real PG types."""
    types = {}
    pattern = r"(?:timestamp with time zone|timestamp without time zone|double precision|bigint|integer|boolean|jsonb|json|numeric|real|text|timestamptz|date|bytea)"
    for migration in sorted((ROOT / "supabase/migrations").glob("*.sql")):
        sql = migration.read_text()
        for table, body in re.findall(r"create table(?: if not exists)? (?:public\.)?(\w+)\s*\((.*?)\n\);", sql, re.I | re.S):
            for column, kind in re.findall(r"^\s{1,6}(\w+)\s+(" + pattern + r")\b", body, re.I | re.M):
                types[table, column] = kind.lower()
        for table, body in re.findall(r"alter table (?:public\.)?(\w+)\s+(.*?);", sql, re.I | re.S):
            for column, kind in re.findall(r"add column(?: if not exists)?\s+(\w+)\s+(" + pattern + r")\b", body, re.I):
                types[table, column] = kind.lower()
    return types


@unittest.skipUnless(PORT, "isolated PostgreSQL compose gate not enabled")
class ComposeOutputPostgresTest(unittest.TestCase):
    namespace = "public"
    backend_role = "service_role"

    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.psycopg = psycopg
        cls.dbname = "edoc_compose_test_" + uuid.uuid4().hex[:12]
        cls.admin = psycopg.connect(host="127.0.0.1", port=int(PORT), user=os.getenv("EDOC_TEST_PG_USER", "seniorlifepr"), dbname="postgres", autocommit=True)
        cls.admin.execute(f'CREATE DATABASE "{cls.dbname}"')
        cls.pg = psycopg.connect(host="127.0.0.1", port=int(PORT), user=os.getenv("EDOC_TEST_PG_USER", "seniorlifepr"), dbname=cls.dbname, autocommit=True)
        cls.addClassCleanup(cls.cleanup)
        for role in ("anon", "authenticated", "service_role", "authenticator", "edoc_backend"):
            if not cls.admin.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                cls.admin.execute(f'CREATE ROLE "{role}" NOLOGIN' + (" BYPASSRLS" if role == "service_role" else ""))
        if not cls.admin.execute("SELECT 1 FROM pg_roles WHERE rolname='postgres'").fetchone():
            cls.admin.execute("CREATE ROLE postgres SUPERUSER NOLOGIN")
        local = sqlite3.connect(":memory:")
        backend.register_sqlite_functions(local)
        local.executescript(backend.SCHEMA)
        types = canonical_column_types()
        if cls.namespace != "public":
            cls.pg.execute("CREATE SCHEMA edoc")
            cls.pg.execute("CREATE TABLE public.hr_untouched(id text PRIMARY KEY, payload text); INSERT INTO public.hr_untouched VALUES ('HR','unchanged')")
        for (table,) in local.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            if table.startswith("official_document_number_"):
                continue
            definitions = []
            primary = []
            for _, name, kind, _, default, pk in local.execute(f'PRAGMA table_info("{table}")'):
                pgtype = types.get((table, name), "integer" if kind == "INTEGER" else "numeric" if kind == "REAL" else "text")
                suffix = ""
                if default and (re.fullmatch(r"'[^']*'", default) or re.fullmatch(r"[0-9]+", default)):
                    if pgtype == "boolean":
                        suffix = " DEFAULT " + ("true" if default == "1" else "false")
                    elif pgtype not in {"timestamp with time zone", "timestamp without time zone", "timestamptz", "date"}:
                        suffix = " DEFAULT " + default
                definitions.append(f'"{name}" {pgtype}{suffix}')
                if pk:
                    primary.append('"' + name + '"')
            if primary:
                definitions.append("PRIMARY KEY(" + ",".join(primary) + ")")
            cls.pg.execute(f'CREATE TABLE {cls.namespace}."{table}" ({",".join(definitions)})')
        local.close()
        # Some audit-only PostgreSQL relations are not part of the SQLite
        # runtime. Include their declared column types for the real RPC DDL.
        for table in sorted({table for table, _ in types}):
            if table.startswith("official_document_number_") or cls.pg.execute("SELECT to_regclass(%s)", (cls.namespace + "." + table,)).fetchone()[0]:
                continue
            definitions = [f'"{column}" {kind}' + (" PRIMARY KEY" if column == "id" else "") for (owner, column), kind in types.items() if owner == table]
            cls.pg.execute(f'CREATE TABLE {cls.namespace}."{table}" ({",".join(definitions)})')
        cls.pg.execute("CREATE SCHEMA IF NOT EXISTS edoc_private")
        cls.pg.execute("CREATE SCHEMA extensions; CREATE EXTENSION pgcrypto WITH SCHEMA extensions")
        cls.pg.execute(f"SET search_path={cls.namespace},edoc_private,extensions,pg_catalog")
        for name in (MIGRATIONS if cls.namespace == "public" else MIGRATIONS[:3]):
            sql = (ROOT / "supabase/migrations" / name).read_text()
            cls.pg.execute(sql if cls.namespace == "public" else transform_sql(sql))
        if cls.namespace == "edoc":
            cls.pg.execute("CREATE TABLE edoc_private.shared_project_migration_ledger(file_name text PRIMARY KEY,source_sha256 text,transformed_sha256 text,bundle_version text)")
            for name in MIGRATIONS[:3]:
                cls.pg.execute("INSERT INTO edoc_private.shared_project_migration_ledger(file_name) VALUES (%s)", (name,))
            cls.pg.execute((ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text())
            # Match the shared bootstrap's backend-only row-policy boundary.
            for (table,) in cls.pg.execute("SELECT relname FROM pg_class JOIN pg_namespace n ON n.oid=relnamespace WHERE n.nspname='edoc' AND relkind='r' AND relrowsecurity"):
                if table.startswith("official_document_number_"):
                    continue  # Exercise the new forward's actual RLS policies.
                cls.pg.execute(f'CREATE POLICY fixture_backend_rls ON edoc."{table}" TO edoc_backend USING (true) WITH CHECK (true)')
        cls.pg.execute(f"GRANT USAGE ON SCHEMA {cls.namespace},edoc_private TO {cls.backend_role}")
        cls.pg.execute(f"GRANT SELECT,INSERT,UPDATE ON {cls.namespace}.official_documents TO {cls.backend_role}")
        cls.pg.execute(f"GRANT SELECT ON {cls.namespace}.companies,{cls.namespace}.documents TO {cls.backend_role}")
        cls.pg.execute("INSERT INTO companies(id,name) VALUES ('CO-COMPOSE','Test Company')")

    @classmethod
    def cleanup(cls):
        cls.pg.close()
        cls.admin.execute(f'DROP DATABASE "{cls.dbname}" WITH (FORCE)')
        cls.admin.close()

    def create(self, doc_id, **kwargs):
        values = {
            "id": doc_id, "company_id": "CO-COMPOSE", "applicant_id": "APPLICANT",
            "source_type": "blank_editor", "document_type": "outgoing_official_document",
            "requires_stamp": False, "output_mode": "electronic", "dispatch_date": "2026-09-08",
            "current_status": "draft", "current_step": "", "updated_at": "2026-09-08 13:00:00",
            "metadata_json": "{}", "title": "Synthetic letter", **kwargs,
        }
        columns = ",".join('"' + key + '"' for key in values)
        return self.pg.execute(f"INSERT INTO official_documents({columns}) VALUES ({','.join('%s' for _ in values)}) RETURNING dispatch_no", tuple(values.values())).fetchone()[0]

    def test_01_valid_electronic_and_physical_documents(self):
        self.assertTrue(self.create("valid-electronic"))
        self.assertTrue(self.create("valid-physical", output_mode="physical", requires_stamp=True))

    def test_02_electronic_uploaded_pdf_and_forged_no_stamp_rejected(self):
        for index, values in enumerate((
            {"source_type": "uploaded_pdf"}, {"document_type": "uploaded_pdf_for_stamp"},
            {"output_mode": "physical"}, {"requires_stamp": True}, {"output_mode": "invalid"},
        )):
            with self.assertRaisesRegex(self.psycopg.Error, "official_document_output_mode_invalid"):
                self.create(f"invalid-{index}", **values)

    def test_03_date_changes_do_not_renumber_and_submitted_fields_lock(self):
        original = self.create("lock")
        self.pg.execute("UPDATE official_documents SET dispatch_date='2026-10-01' WHERE id='lock'")
        self.assertEqual(original, self.pg.execute("SELECT dispatch_no FROM official_documents WHERE id='lock'").fetchone()[0])
        self.pg.execute("UPDATE official_documents SET current_status='pending_applicant_manager' WHERE id='lock'")
        with self.assertRaisesRegex(self.psycopg.Error, "official_document_dispatch_date_locked"):
            self.pg.execute("UPDATE official_documents SET dispatch_date='2026-10-02' WHERE id='lock'")
        with self.assertRaisesRegex(self.psycopg.Error, "official_document_output_mode_locked"):
            self.pg.execute("UPDATE official_documents SET output_mode='physical',requires_stamp=true WHERE id='lock'")

    def test_04_invalid_calendar_dates_rejected(self):
        for index, date in enumerate(("2026-02-30", "2026-9-8", "bad", "2026-13-01")):
            with self.assertRaises(self.psycopg.Error):
                self.create(f"date-{index}", dispatch_date=date)

    def test_05_private_finalize_not_directly_callable(self):
        for role in set(("anon", "authenticated", "service_role", self.backend_role)):
            with self.pg.transaction():
                self.pg.execute(f"SET LOCAL ROLE {role}")
                with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                    with self.pg.transaction():
                        self.pg.execute("SELECT edoc_private.complete_electronic_compose('valid-electronic','APPLICANT')")

    def submission(self, doc_id):
        self.create(doc_id)
        self.pg.execute("INSERT INTO file_objects(id,document_id,mime_type,sha256,size_bytes) VALUES (%s,%s,'application/pdf',%s,123)", ("OBJ-" + doc_id, doc_id, "A" * 64))
        self.pg.execute("INSERT INTO official_document_files(id,document_id,file_object_id,file_type,file_hash,file_size,version,created_at) VALUES (%s,%s,%s,'generated_pdf',%s,123,1,'2026-09-08 13:00:00')", ("FILE-" + doc_id, doc_id, "OBJ-" + doc_id, "A" * 64))
        operation = "SUBMIT-" + doc_id
        step_id = "STEP-" + doc_id
        return {
            "operation_id": operation, "document_id": doc_id, "company_id": "CO-COMPOSE", "applicant_id": "APPLICANT",
            "expected_status": "draft", "expected_updated_at": "2026-09-08 13:00:00", "submitted_at": "2026-09-08 13:01:00",
            "first_step_id": step_id, "first_step_key": "general_affairs_review", "first_status": "pending_general_affairs_review",
            "workflow_generation": 1, "stamp_request": {}, "stamp_positions": [], "actor_snapshots": [],
            "steps": [
                {"id": step_id, "document_id": doc_id, "step_order": 1, "step_key": "general_affairs_review", "step_name": "總務", "approver_user_id": "REVIEWER", "workflow_generation": 1, "status": "pending"},
                {"id": "CONFIRM-" + doc_id, "document_id": doc_id, "step_order": 2, "step_key": "applicant_confirm", "step_name": "申請人收件", "approver_user_id": "APPLICANT", "workflow_generation": 1, "status": "pending"},
            ],
            "submit_log": {"id": operation, "document_id": doc_id, "actor_id": "APPLICANT", "action": "submit", "created_at": "2026-09-08 13:01:00", "decision_evidence_json": {"operation_id": operation, "workflow_generation": 1, "source_file_id": "FILE-" + doc_id, "source_sha256": "A" * 64}},
            "submit_audit": {"id": "AUDIT-" + doc_id, "target_id": doc_id, "created_at": "2026-09-08 13:01:00"},
        }

    def call_submit(self, payload):
        with self.pg.transaction():
            self.pg.execute(f"SET LOCAL ROLE {self.backend_role}")
            return self.pg.execute(f"SELECT {self.namespace}.edoc_commit_official_document_submission(%s::jsonb)", (json.dumps(payload),)).fetchone()[0]

    def test_06_electronic_submission_rpc_commits_without_seals_and_is_idempotent(self):
        payload = self.submission("rpc-submit")
        result = self.call_submit(payload)
        self.assertTrue(result["committed"])
        self.assertTrue(self.call_submit(payload)["idempotent"])
        self.assertEqual(0, self.pg.execute("SELECT count(*) FROM official_document_stamp_requests WHERE document_id='rpc-submit'").fetchone()[0])
        self.assertEqual(2, self.pg.execute("SELECT count(*) FROM official_document_approval_steps WHERE document_id='rpc-submit'").fetchone()[0])

    def test_07_tampered_source_or_cross_company_submit_is_atomic_rejection(self):
        payload = self.submission("rpc-reject")
        payload["submit_log"]["decision_evidence_json"]["source_sha256"] = "B" * 64
        with self.assertRaisesRegex(self.psycopg.Error, "official_document_electronic_source_invalid"):
            self.call_submit(payload)
        self.assertEqual(0, self.pg.execute("SELECT count(*) FROM official_document_approval_steps WHERE document_id='rpc-reject'").fetchone()[0])
        payload["company_id"] = "OTHER"
        with self.assertRaisesRegex(self.psycopg.Error, "official_document_submit_forbidden"):
            self.call_submit(payload)

    def test_08_v3_final_approval_creates_dispatch_once_without_stamp(self):
        doc_id = "rpc-approve"
        payload = self.submission(doc_id)
        self.call_submit(payload)
        self.pg.execute("INSERT INTO users(id,name,status,company_id,role,email) VALUES ('REVIEWER','Synthetic Reviewer','啟用','CO-COMPOSE','總務','reviewer@example.invalid')")
        file_id = "FILE-" + doc_id
        self.pg.execute("INSERT INTO official_document_approval_logs(id,document_id,actor_id,file_id,action,created_at) VALUES ('ACCESS',%s,'REVIEWER',%s,'download_file','2026-09-08 13:02:00')", (doc_id, file_id))
        evidence = {
            "schema_version": 2, "decision_type": "approve", "expected_step_id": "STEP-" + doc_id,
            "principal_actor_id": "REVIEWER", "decision_actor_user_id": "REVIEWER",
            "review_acknowledgements": {"original_reviewed": True, "edited_version_reviewed": True, "attachments_reviewed": True},
            "source_file": {"id": file_id, "type": "generated_pdf", "sha256": "A" * 64, "version": 1, "size": 123},
            "legacy_renderer": True, "prepared_file": None, "attachments": [],
            "attachments_manifest_sha256": hashlib.sha256(b"").hexdigest(),
            "review_access": {"server_verified": True, "step_started_at": "2026-09-08 13:01:00", "required_file_ids": [file_id], "access_logs": [{"file_id": file_id, "access_log_id": "ACCESS", "action": "download_file", "accessed_at": "2026-09-08 13:02:00"}]},
        }
        def decide():
            with self.pg.transaction():
                self.pg.execute(f"SET LOCAL ROLE {self.backend_role}")
                return self.pg.execute(f"SELECT {self.namespace}.edoc_claim_official_document_approval_v3(%s,%s,'REVIEWER','REVIEWER','Checked',%s::jsonb)", (doc_id, "STEP-" + doc_id, json.dumps(evidence))).fetchone()[0]
        result = decide()
        self.assertTrue(result["claimed"])
        self.assertEqual(result["document_status"], "pending_general_affairs_dispatch")
        self.assertFalse(decide()["claimed"])
        self.assertEqual(("pending_general_affairs_dispatch", file_id), self.pg.execute("SELECT current_status,stamped_file_id FROM official_documents WHERE id=%s", (doc_id,)).fetchone())
        self.assertEqual(1, self.pg.execute("SELECT count(*) FROM official_document_dispatch_records WHERE document_id=%s", (doc_id,)).fetchone()[0])
        self.assertEqual(0, self.pg.execute("SELECT count(*) FROM official_document_stamp_requests WHERE document_id=%s", (doc_id,)).fetchone()[0])


class ComposeOutputSharedPostgresTest(ComposeOutputPostgresTest):
    namespace = "edoc"
    backend_role = "edoc_backend"

    def test_09_shared_forward_replay_preserves_hr_and_numbers(self):
        before = self.pg.execute("SELECT id,dispatch_no FROM edoc.official_documents ORDER BY id").fetchall()
        self.pg.execute((ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text())
        self.assertEqual(before, self.pg.execute("SELECT id,dispatch_no FROM edoc.official_documents ORDER BY id").fetchall())
        self.assertEqual([("HR", "unchanged")], self.pg.execute("SELECT * FROM public.hr_untouched").fetchall())

    def test_10_backend_can_create_numbered_draft_with_rls_but_no_public_access(self):
        with self.pg.transaction():
            self.pg.execute("SET LOCAL ROLE edoc_backend")
            self.assertTrue(self.create("shared-backend-draft"))
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                with self.pg.transaction():
                    self.pg.execute("SELECT * FROM public.hr_untouched")


if __name__ == "__main__":
    unittest.main()
