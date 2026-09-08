"""Real PostgreSQL concurrency/privilege contract, opt-in isolated database only."""
from __future__ import annotations

import concurrent.futures
import os
import unittest
from pathlib import Path

DSN = os.getenv("EDOC_NUMBERING_TEST_PG_DSN", "")


@unittest.skipUnless(DSN, "set EDOC_NUMBERING_TEST_PG_DSN to an empty isolated local test database")
class OfficialNumberingPostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict

        cls.psycopg = psycopg
        info = conninfo_to_dict(DSN)
        if info.get("host") not in {"127.0.0.1", "localhost"} or not info.get("dbname", "").startswith("edoc_numbering_test"):
            raise RuntimeError("numbering_tests_require_isolated_loopback_database")
        with psycopg.connect(DSN, autocommit=True) as conn:
            if conn.execute("SELECT to_regclass('public.official_documents')").fetchone()[0]:
                raise RuntimeError("numbering_tests_require_empty_database")
            for role in ("anon", "authenticated", "service_role"):
                if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                    conn.execute(f"CREATE ROLE {role} NOLOGIN" + (" BYPASSRLS" if role == "service_role" else ""))
            conn.execute("""
              CREATE TABLE public.companies(id text PRIMARY KEY);
              INSERT INTO public.companies VALUES ('CO-TEST-A'),('CO-TEST-B');
              CREATE TABLE public.documents(id text PRIMARY KEY, doc_no text, direction text);
              CREATE TABLE public.official_documents(
                id text PRIMARY KEY, company_id text NOT NULL, applicant_id text NOT NULL,
                source_type text NOT NULL, metadata_json text NOT NULL DEFAULT '{}',
                dispatch_date text, subject text
              );
              GRANT USAGE ON SCHEMA public TO service_role,anon,authenticated;
              GRANT SELECT,INSERT,UPDATE ON public.official_documents TO service_role;
              GRANT SELECT ON public.documents,public.companies TO service_role;
            """)
            migration = Path(__file__).parents[1] / "supabase/migrations/20260908135730_immutable_official_document_numbering.sql"
            conn.execute(migration.read_text())
            cls.prefix = conn.execute("SELECT '歲悅字第' || (extract(year FROM now() AT TIME ZONE 'Asia/Taipei')::int-1911)::text || to_char(now() AT TIME ZONE 'Asia/Taipei','MMDD')").fetchone()[0]

    def connection(self, role="service_role"):
        conn = self.psycopg.connect(DSN)
        if role:
            conn.execute(f"SET ROLE {role}")
        return conn

    def insert(self, conn, doc_id, *, company="CO-TEST-A", actor="staff-a", source="blank_editor"):
        return conn.execute(
            "INSERT INTO official_documents(id,company_id,applicant_id,source_type) VALUES (%s,%s,%s,%s) RETURNING dispatch_no",
            (doc_id, company, actor, source),
        ).fetchone()[0]

    def test_01_thirty_concurrent_drafts_are_unique_across_tenants(self):
        def save(index):
            with self.connection() as conn:
                return self.insert(conn, f"parallel-{index}", company="CO-TEST-A" if index % 2 else "CO-TEST-B", actor=f"staff-{index}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as pool:
            numbers = list(pool.map(save, range(30)))
        self.assertEqual(set(numbers), {f"{self.prefix}{i:03d}號" for i in range(1, 31)})

    def test_02_duplicate_id_and_rollback_do_not_allocate_new_numbers(self):
        with self.connection() as conn:
            original = self.insert(conn, "retry")
        with self.connection() as conn:
            with self.assertRaises(self.psycopg.errors.UniqueViolation):
                self.insert(conn, "retry")
            conn.rollback()
        with self.connection() as conn:
            self.assertEqual(original, conn.execute("SELECT dispatch_no FROM official_documents WHERE id='retry'").fetchone()[0])
            number = self.insert(conn, "rolled-back")
            conn.rollback()
        with self.connection() as conn:
            self.assertEqual(number, self.insert(conn, "after-rollback"))

    def test_03_date_edits_keep_number_and_identity_is_locked(self):
        with self.connection() as conn:
            original = self.insert(conn, "immutable")
            conn.execute("UPDATE official_documents SET dispatch_date='2030-01-01' WHERE id='immutable'")
            self.assertEqual(original, conn.execute("SELECT dispatch_no FROM official_documents WHERE id='immutable'").fetchone()[0])
        for field, value in (("dispatch_no", None), ("dispatch_no", "custom"), ("company_id", "CO-TEST-B"), ("applicant_id", "other"), ("source_type", "uploaded_pdf")):
            with self.connection() as conn:
                with self.assertRaisesRegex(self.psycopg.errors.CheckViolation, "official_document_number_immutable"):
                    conn.execute(f"UPDATE official_documents SET {field}=%s WHERE id='immutable'", (value,))
                conn.rollback()

    def test_04_client_numbers_are_refused_and_uploaded_pdf_not_numbered(self):
        with self.connection() as conn:
            with self.assertRaisesRegex(self.psycopg.errors.CheckViolation, "official_document_number_server_owned"):
                conn.execute("INSERT INTO official_documents(id,company_id,applicant_id,source_type,dispatch_no) VALUES ('chosen','CO-TEST-A','a','blank_editor','custom')")
            conn.rollback()
        with self.connection() as conn:
            self.assertIsNone(self.insert(conn, "contract", source="uploaded_pdf"))

    def test_05_legacy_floor_and_four_digit_sequence_are_preserved(self):
        with self.connection(role=None) as conn:
            conn.execute("INSERT INTO documents VALUES ('old',%s,'發文')", (f"{self.prefix}999號",))
            self.insert(conn, "legacy", source="uploaded_pdf")
            conn.execute("UPDATE official_documents SET metadata_json=%s WHERE id='legacy'", ('{"extra":{"dispatch_no":"' + self.prefix + '9999號"}}',))
        with self.connection() as conn:
            self.assertEqual(f"{self.prefix}10000號", self.insert(conn, "floor"))

    def test_06_anonymous_and_authenticated_have_no_data_or_function_access(self):
        for role in ("anon", "authenticated"):
            for query in (
                "SELECT * FROM official_document_number_allocations",
                "SELECT * FROM official_document_number_counters",
                "SELECT edoc_number_safe_metadata('{}')",
            ):
                with self.connection(role=role) as conn:
                    with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                        conn.execute(query)
                    conn.rollback()
        with self.connection(role=None) as conn:
            self.assertEqual(2, conn.execute("SELECT count(*) FROM pg_class WHERE relname IN ('official_document_number_counters','official_document_number_allocations') AND relrowsecurity").fetchone()[0])
            self.assertFalse(conn.execute("SELECT bool_or(prosecdef) FROM pg_proc WHERE proname LIKE 'edoc_%number%'").fetchone()[0])

    def test_07_allocation_ledger_cannot_be_reassigned_or_deleted(self):
        with self.connection(role=None) as conn:
            for statement in (
                "UPDATE official_document_number_allocations SET applicant_id='other' WHERE document_id='retry'",
                "DELETE FROM official_document_number_allocations WHERE document_id='retry'",
            ):
                with self.assertRaisesRegex(self.psycopg.errors.CheckViolation, "official_document_number_immutable"):
                    conn.execute(statement)
                conn.rollback()


if __name__ == "__main__":
    unittest.main()
