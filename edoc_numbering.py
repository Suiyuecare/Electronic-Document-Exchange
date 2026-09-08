"""Database-owned, immutable outgoing letter numbers (no client allocation)."""

from __future__ import annotations

import sqlite3


def install_sqlite_numbering(conn: sqlite3.Connection) -> None:
    """Install on both existing and new databases without renumbering old cases."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(official_documents)")}
    if not columns:
        return
    if "dispatch_no" not in columns:
        conn.execute("ALTER TABLE official_documents ADD COLUMN dispatch_no TEXT")
    conn.executescript(SQLITE_NUMBERING_SQL)


_DATE_KEY = "(CAST(CAST(strftime('%Y','now','+8 hours') AS INTEGER)-1911 AS TEXT) || strftime('%m%d','now','+8 hours'))"
_PREFIX = f"('歲悅字第' || {_DATE_KEY})"
_LEGACY_VALUES = """
SELECT doc_no AS value FROM documents WHERE direction = '發文'
UNION ALL SELECT dispatch_no FROM official_documents
UNION ALL SELECT json_extract(metadata_json, '$.dispatch_no')
  FROM official_documents WHERE json_valid(metadata_json)
UNION ALL SELECT json_extract(metadata_json, '$.extra.dispatch_no')
  FROM official_documents WHERE json_valid(metadata_json)
"""
_FLOOR = f"""(
 SELECT COALESCE(MAX(CAST(serial AS INTEGER)), 0) FROM (
   SELECT substr(value, length({_PREFIX}) + 1,
                        length(value) - length({_PREFIX}) - 1) AS serial
   FROM ({_LEGACY_VALUES})
   WHERE value LIKE {_PREFIX} || '%號'
 ) WHERE length(serial) BETWEEN 1 AND 12 AND serial NOT GLOB '*[^0-9]*'
)"""

SQLITE_NUMBERING_SQL = f"""
CREATE TABLE IF NOT EXISTS official_document_number_counters (
  date_key TEXT PRIMARY KEY,
  last_serial INTEGER NOT NULL CHECK(last_serial > 0)
);
CREATE TABLE IF NOT EXISTS official_document_number_allocations (
  document_id TEXT PRIMARY KEY REFERENCES official_documents(id) ON DELETE RESTRICT,
  company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  applicant_id TEXT NOT NULL,
  dispatch_no TEXT NOT NULL UNIQUE,
  assigned_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_official_documents_dispatch_no
  ON official_documents(dispatch_no) WHERE dispatch_no IS NOT NULL;
CREATE TRIGGER IF NOT EXISTS trg_official_number_server_owned
BEFORE INSERT ON official_documents WHEN NEW.dispatch_no IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'official_document_number_server_owned'); END;
CREATE TRIGGER IF NOT EXISTS trg_official_number_allocate
AFTER INSERT ON official_documents WHEN NEW.source_type = 'blank_editor'
BEGIN
  INSERT INTO official_document_number_counters(date_key, last_serial)
  VALUES ({_DATE_KEY}, {_FLOOR} + 1)
  ON CONFLICT(date_key) DO UPDATE SET last_serial =
    MAX(official_document_number_counters.last_serial, {_FLOOR}) + 1;
  INSERT INTO official_document_number_allocations
    (document_id, company_id, applicant_id, dispatch_no)
  SELECT NEW.id, NEW.company_id, NEW.applicant_id,
    {_PREFIX} || printf('%03d', last_serial) || '號'
  FROM official_document_number_counters WHERE date_key = {_DATE_KEY};
  UPDATE official_documents SET dispatch_no = (
    SELECT dispatch_no FROM official_document_number_allocations WHERE document_id = NEW.id
  ) WHERE id = NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_official_number_immutable
BEFORE UPDATE OF dispatch_no, company_id, applicant_id, source_type ON official_documents
WHEN (NEW.dispatch_no IS NOT OLD.dispatch_no AND (
  OLD.dispatch_no IS NOT NULL OR NOT EXISTS (
    SELECT 1 FROM official_document_number_allocations a
    WHERE a.document_id = NEW.id AND a.dispatch_no = NEW.dispatch_no
      AND a.company_id = NEW.company_id AND a.applicant_id = NEW.applicant_id
  )
)) OR (OLD.dispatch_no IS NOT NULL AND (
  NEW.company_id IS NOT OLD.company_id OR NEW.applicant_id IS NOT OLD.applicant_id
  OR NEW.source_type IS NOT OLD.source_type
))
BEGIN SELECT RAISE(ABORT, 'official_document_number_immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_official_number_allocation_immutable_update
BEFORE UPDATE ON official_document_number_allocations
BEGIN SELECT RAISE(ABORT, 'official_document_number_immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_official_number_allocation_immutable_delete
BEFORE DELETE ON official_document_number_allocations
BEGIN SELECT RAISE(ABORT, 'official_document_number_immutable'); END;
"""
