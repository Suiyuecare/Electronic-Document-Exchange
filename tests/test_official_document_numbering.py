from __future__ import annotations

import concurrent.futures
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from edoc_numbering import install_sqlite_numbering


MINIMAL_SCHEMA = """
CREATE TABLE companies(id TEXT PRIMARY KEY);
INSERT INTO companies VALUES ('CO-TEST-A'), ('CO-TEST-B');
CREATE TABLE documents(id TEXT PRIMARY KEY, doc_no TEXT, direction TEXT);
CREATE TABLE official_documents(
 id TEXT PRIMARY KEY, company_id TEXT NOT NULL, applicant_id TEXT NOT NULL,
 source_type TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
 dispatch_date TEXT, subject TEXT
);
"""


def prefix() -> str:
    today = datetime.now(ZoneInfo("Asia/Taipei"))
    return f"歲悅字第{today.year - 1911}{today:%m%d}"


class OfficialNumberingSQLiteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "numbering.sqlite3"
        with self.connection() as conn:
            conn.executescript(MINIMAL_SCHEMA)
            install_sqlite_numbering(conn)

    def connection(self):
        conn = sqlite3.connect(self.path, timeout=20)
        conn.execute("PRAGMA foreign_keys = ON")
        self.addCleanup(conn.close)
        return conn

    def insert(self, conn, doc_id, *, company="CO-TEST-A", actor="staff-a", source="blank_editor"):
        conn.execute(
            "INSERT INTO official_documents(id,company_id,applicant_id,source_type) VALUES (?,?,?,?)",
            (doc_id, company, actor, source),
        )
        return conn.execute("SELECT dispatch_no FROM official_documents WHERE id=?", (doc_id,)).fetchone()[0]

    def test_concurrent_drafts_across_users_and_companies_are_unique(self):
        def save(index):
            with sqlite3.connect(self.path, timeout=20) as conn:
                conn.execute("PRAGMA foreign_keys=ON")
                return self.insert(conn, f"DOC-{index}", company="CO-TEST-A" if index % 2 else "CO-TEST-B", actor=f"staff-{index}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            numbers = list(pool.map(save, range(30)))
        self.assertEqual(len(set(numbers)), 30)
        self.assertEqual(set(numbers), {f"{prefix()}{i:03d}號" for i in range(1, 31)})

    def test_duplicate_id_retry_does_not_consume_number(self):
        with self.connection() as conn:
            first = self.insert(conn, "ONE")
        with self.connection() as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                self.insert(conn, "ONE")
            self.assertEqual(first, conn.execute("SELECT dispatch_no FROM official_documents WHERE id='ONE'").fetchone()[0])
            self.assertEqual(f"{prefix()}002號", self.insert(conn, "TWO"))

    def test_legacy_floor_and_wide_sequence(self):
        with self.connection() as conn:
            conn.execute("INSERT INTO documents VALUES ('OLD', ?, '發文')", (f"{prefix()}998號",))
            self.insert(conn, "LEGACY", source="uploaded_pdf")
            conn.execute("UPDATE official_documents SET metadata_json=? WHERE id='LEGACY'", (json.dumps({"extra": {"dispatch_no": f"{prefix()}9999號"}}, ensure_ascii=False),))
            self.assertEqual(f"{prefix()}10000號", self.insert(conn, "NEW"))

    def test_number_is_immutable_on_edit_or_tenant_change(self):
        with self.connection() as conn:
            first = self.insert(conn, "ONE")
            conn.execute("UPDATE official_documents SET dispatch_date='2030-01-01',subject='updated' WHERE id='ONE'")
            self.assertEqual(first, conn.execute("SELECT dispatch_no FROM official_documents WHERE id='ONE'").fetchone()[0])
            for field, value in (("dispatch_no", None), ("dispatch_no", "chosen"), ("company_id", "CO-TEST-B"), ("applicant_id", "other"), ("source_type", "uploaded_pdf")):
                with self.assertRaisesRegex(sqlite3.IntegrityError, "official_document_number_immutable"):
                    conn.execute(f"UPDATE official_documents SET {field}=? WHERE id='ONE'", (value,))

    def test_client_cannot_choose_number_and_uploaded_contracts_are_not_numbered(self):
        with self.connection() as conn:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "official_document_number_server_owned"):
                conn.execute("INSERT INTO official_documents(id,company_id,applicant_id,source_type,dispatch_no) VALUES ('CHOSEN','CO-TEST-A','a','blank_editor','custom')")
            self.assertIsNone(self.insert(conn, "CONTRACT", source="uploaded_pdf"))
            self.assertEqual(f"{prefix()}001號", self.insert(conn, "LETTER"))

    def test_rollback_does_not_leave_reservation(self):
        conn = self.connection()
        first = self.insert(conn, "ABANDONED")
        conn.rollback()
        with conn:
            self.assertEqual(first, self.insert(conn, "SAVED"))
            self.assertEqual(1, conn.execute("SELECT count(*) FROM official_document_number_allocations").fetchone()[0])

    def test_allocations_cannot_be_reassigned_or_deleted(self):
        with self.connection() as conn:
            self.insert(conn, "ONE")
            for statement in (
                "UPDATE official_document_number_allocations SET applicant_id='other'",
                "DELETE FROM official_document_number_allocations",
            ):
                with self.assertRaisesRegex(sqlite3.IntegrityError, "official_document_number_immutable"):
                    conn.execute(statement)

    def test_upgrade_keeps_existing_letter_metadata_unchanged(self):
        with sqlite3.connect(":memory:") as conn:
            conn.executescript(MINIMAL_SCHEMA)
            old = json.dumps({"extra": {"dispatch_no": "歲悅字第1140101001號"}})
            conn.execute("INSERT INTO official_documents VALUES ('OLD','CO-TEST-A','a','blank_editor',?,NULL,'old')", (old,))
            install_sqlite_numbering(conn)
            row = conn.execute("SELECT dispatch_no,metadata_json FROM official_documents").fetchone()
            self.assertEqual(row, (None, old))
            install_sqlite_numbering(conn)
            self.assertEqual(0, conn.execute("SELECT count(*) FROM official_document_number_allocations").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
