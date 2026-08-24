from __future__ import annotations

import base64
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

import backend
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SEAL_SLOT_MIGRATION = ROOT / "supabase" / "migrations" / "20260823191041_backfill_company_seal_upload_slots.sql"


class CompanySealModuleTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.original_storage_dir = backend.STORAGE_DIR
        self.original_private_seal_dir = backend.PRIVATE_SEAL_STORAGE_DIR
        backend.STORAGE_DIR = Path(self.tmp.name) / "storage"
        backend.PRIVATE_SEAL_STORAGE_DIR = backend.STORAGE_DIR / "seal-vault" / "seals"
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(backend.SCHEMA)
        backend.seed(self.conn)
        backend.seed_auth(self.conn)
        backend.seed_persistent_registries(self.conn)
        backend.seed_company_seal_module(self.conn)
        backend.seed_signing_certificates(self.conn)
        backend.seed_certificate_authorities(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        backend.STORAGE_DIR = self.original_storage_dir
        backend.PRIVATE_SEAL_STORAGE_DIR = self.original_private_seal_dir
        self.tmp.cleanup()

    def seed_seal_id(self) -> str:
        row = self.conn.execute(
            """
            SELECT id FROM company_seals
            WHERE company_id = 'CO-001' AND seal_category = 'general_seal' AND seal_size_type = 'large_seal'
            LIMIT 1
            """
        ).fetchone()
        self.assertIsNotNone(row)
        return row["id"]

    def png_payload(self, name: str = "company-seal.png") -> dict:
        buffer = io.BytesIO()
        Image.new("RGBA", (320, 320), (180, 0, 0, 255)).save(buffer, format="PNG")
        data = buffer.getvalue()
        return {
            "file_name": name,
            "file_mime_type": "image/png",
            "content_base64": base64.b64encode(data).decode("ascii"),
            "actor": "unit-test",
        }

    def test_seed_creates_reference_options_and_default_company_seals(self) -> None:
        seal_count = self.conn.execute("SELECT COUNT(*) AS count FROM company_seals WHERE company_id = 'CO-001'").fetchone()["count"]
        self.assertEqual(seal_count, 8)
        categories = {
            row["code"]
            for row in self.conn.execute("SELECT code FROM seal_reference_options WHERE option_type = 'category'")
        }
        self.assertIn("establishment_seal", categories)
        self.assertIn("bank_seal", categories)
        self.assertIn("general_seal", categories)
        self.assertIn("other", categories)

    def test_upload_seal_file_is_private_metadata_only_and_rejects_unsafe_svg(self) -> None:
        seal_id = self.seed_seal_id()
        result = backend.upload_company_seal_file(self.conn, seal_id, self.png_payload())

        self.assertEqual(result["file"]["version"], 1)
        self.assertNotIn("file_storage_key", result["file"])
        stored = self.conn.execute("SELECT * FROM company_seal_files WHERE seal_id = ?", (seal_id,)).fetchone()
        self.assertIn("seal-vault/seals", stored["file_storage_key"])
        self.assertTrue((backend.STORAGE_DIR / stored["file_storage_key"]).exists())
        file_object = self.conn.execute("SELECT * FROM file_objects WHERE id = ?", (stored["file_object_id"],)).fetchone()
        self.assertEqual(file_object["document_id"], backend.SEAL_VAULT_DOCUMENT_ID)
        self.assertEqual(file_object["purpose"], "seal-vault-original")
        self.assertEqual(file_object["storage_provider"], "seal-vault")

        files = backend.list_company_seal_files(self.conn, seal_id)
        self.assertNotIn("file_storage_key", files[0])
        with self.assertRaisesRegex(ValueError, "unsafe_svg_rejected"):
            backend.upload_company_seal_file(
                self.conn,
                seal_id,
                {
                    "file_name": "bad.svg",
                    "file_mime_type": "image/svg+xml",
                    "content_base64": base64.b64encode(b"<svg><script>alert(1)</script></svg>").decode("ascii"),
                },
            )

    def test_seal_originals_cannot_use_generic_attachment_download_or_upload(self) -> None:
        seal_id = self.seed_seal_id()
        backend.upload_company_seal_file(self.conn, seal_id, self.png_payload())
        stored = self.conn.execute("SELECT * FROM company_seal_files WHERE seal_id = ?", (seal_id,)).fetchone()

        signed = backend.create_file_signed_url(self.conn, stored["file_object_id"], "unit-test")
        self.assertEqual(signed["error"], "seal_vault_download_forbidden")

        generic_upload = backend.upload_file_object(
            self.conn,
            {
                "document_id": "DOC-SEAL-ASSET",
                "file_name": "seal.png",
                "mime_type": "image/png",
                "purpose": "seal-assets",
                "actor": "unit-test",
                "content_base64": self.png_payload()["content_base64"],
            },
        )
        self.assertEqual(generic_upload["error"], "seal_vault_upload_required")
        denied_actions = {
            row["action"]
            for row in self.conn.execute("SELECT action FROM seal_usage_logs WHERE action LIKE 'block_seal_vault%'")
        }
        self.assertIn("block_seal_vault_signed_url", denied_actions)

    def test_request_approve_and_stamp_updates_document_and_logs(self) -> None:
        seal_id = self.seed_seal_id()
        backend.upload_company_seal_file(self.conn, seal_id, self.png_payload())

        request = backend.create_seal_usage_request(
            self.conn,
            "DOC-UNIT-SEAL-001",
            {
                "seal_id": seal_id,
                "usage_type": "official_document",
                "request_reason": "去識別化測試用印。",
                "actor": "employee-test",
                "document": {
                    "document_id": "DOC-UNIT-SEAL-001",
                    "doc_no": "測試字第1150702001號",
                    "doc_type": "函",
                    "agency_name": "測試機關",
                    "subject": "測試公司用印流程",
                    "body": "去識別化測試資料。",
                },
                "stamp_positions": [
                    {"page": 1, "x": 420, "y": 130, "w": 85, "h": 85, "label": "公司章", "type": "general_seal", "seal_id": seal_id}
                ],
            },
        )

        self.assertEqual(request["status"], "pending")
        approved = backend.approve_seal_usage_request(self.conn, request["id"], {"actor": "approver-test", "comment": "核准"})
        self.assertEqual(approved["status"], "approved")

        stamped = backend.stamp_seal_usage_request(self.conn, request["id"], {"actor": "seal-admin-test"})
        self.assertEqual(stamped["request"]["status"], "stamped")
        self.assertTrue(stamped["stamped_file"]["pdf_version_id"])
        doc = self.conn.execute("SELECT status FROM documents WHERE id = 'DOC-UNIT-SEAL-001'").fetchone()
        self.assertEqual(doc["status"], "已用印")
        actions = {row["action"] for row in self.conn.execute("SELECT action FROM seal_usage_logs WHERE usage_request_id = ?", (request["id"],))}
        self.assertTrue({"request_use", "approve_use", "stamp_document"}.issubset(actions))


class CompanySealUploadSlotMigrationTestCase(unittest.TestCase):
    def test_migration_provisions_all_eight_metadata_slots_without_fake_files(self) -> None:
        sql = SEAL_SLOT_MIGRATION.read_text(encoding="utf-8")
        required_slots = {
            ("establishment_seal", "large_seal"),
            ("establishment_seal", "small_seal"),
            ("bank_seal", "large_seal"),
            ("bank_seal", "small_seal"),
            ("general_seal", "large_seal"),
            ("general_seal", "small_seal"),
            ("official_seal", "large_seal"),
            ("other", "large_seal"),
        }

        for category, size_type in required_slots:
            self.assertIn(f"('{category}', '{size_type}'", sql)
        self.assertIn("private.edoc_ensure_company_seal_slots_v1", sql)
        self.assertIn("companies_edoc_seal_slots_v1", sql)
        self.assertIn("from public, anon, authenticated", sql)
        self.assertNotIn("insert into public.company_seal_files", sql.lower())
        self.assertNotIn("file_storage_key", sql.lower())
        self.assertNotIn("file_hash", sql.lower())


if __name__ == "__main__":
    unittest.main()
