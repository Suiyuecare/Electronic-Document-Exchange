"""Actual slim-list projection plus shipped JavaScript; synthetic in-memory data."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import unittest

import backend


class FileVisibilityResilienceTest(unittest.TestCase):
    def test_real_list_row_and_frontend_recovery_contract(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is required for shipped frontend behavior")
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        backend.register_sqlite_functions(conn)
        conn.executescript(backend.SCHEMA)
        conn.execute("INSERT INTO companies(id,name,created_at,updated_at) VALUES ('TEST-CO','Synthetic company','x','x')")
        conn.execute("""INSERT INTO official_documents
            (id,company_id,source_type,title,applicant_id,current_status,stamped_file_id,created_at,updated_at)
            VALUES ('TEST-DOC','TEST-CO','uploaded_pdf','Synthetic completed file','TEST-ACTOR','stamped','TEST-FINAL','2026-09-24 10:00:00','x')""")
        conn.execute("""INSERT INTO official_document_files
            (id,document_id,file_type,file_name,file_storage_key,file_mime_type,file_size,file_hash,created_at)
            VALUES ('TEST-FINAL','TEST-DOC','stamped_pdf','synthetic.pdf','isolated','application/pdf',100,'synthetic-hash','x')""")
        session = {"user": {"id": "TEST-ACTOR", "company_id": "TEST-CO"}, "permissions": []}
        page = backend.list_official_documents(conn, {"scope": ["mine"], "page_size": ["50"]}, session)
        self.assertEqual(len(page["items"]), 1)
        item = page["items"][0]
        self.assertTrue(item["can_download"])
        self.assertNotIn("files", item)
        files = backend.official_document_files(conn, "TEST-DOC")
        self.assertEqual([file["id"] for file in files], ["TEST-FINAL"])
        root = Path(__file__).resolve().parents[1]
        environment = {**os.environ, "EDOC_FILE_VISIBILITY_FIXTURE": json.dumps({"item": item, "files": files})}
        result = subprocess.run([node, "--test", str(root / "tests/file_visibility_resilience.test.js")], cwd=root,
                                env=environment, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
