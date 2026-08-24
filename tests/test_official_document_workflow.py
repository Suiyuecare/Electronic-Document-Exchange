from __future__ import annotations

import base64
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

import backend
from PIL import Image, ImageDraw


class OfficialDocumentWorkflowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.original_storage_dir = backend.STORAGE_DIR
        self.original_private_seal_dir = backend.PRIVATE_SEAL_STORAGE_DIR
        backend.STORAGE_DIR = Path(self.tmp.name) / "storage"
        backend.PRIVATE_SEAL_STORAGE_DIR = backend.STORAGE_DIR / "seal-vault" / "seals"
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        backend.register_sqlite_functions(self.conn)
        self.conn.executescript(backend.SCHEMA)
        backend.seed(self.conn)
        backend.seed_auth(self.conn)
        backend.ensure_allowed_edoc_users(self.conn)
        backend.seed_persistent_registries(self.conn)
        backend.seed_jobs(self.conn)
        backend.seed_company_seal_module(self.conn)
        backend.seed_signing_certificates(self.conn)
        backend.seed_certificate_authorities(self.conn)
        self.conn.execute(
            "UPDATE users SET company_id = 'CO-001', company_name = '歲悅股份有限公司'"
        )

    def tearDown(self) -> None:
        self.conn.close()
        backend.STORAGE_DIR = self.original_storage_dir
        backend.PRIVATE_SEAL_STORAGE_DIR = self.original_private_seal_dir
        self.tmp.cleanup()

    def login_session(self, email: str) -> dict:
        session, status = backend.authenticate_local(
            self.conn,
            {"email": email, "password": "demo1234", "provider": "unittest"},
            "127.0.0.1",
            "unittest",
        )
        self.assertEqual(status, 200)
        return session

    def session_for_user_id(self, user_id: str) -> dict:
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        self.assertIsNotNone(row)
        return {
            "token": "unit-test",
            "expiresAt": "2099-12-31 23:59:59",
            "user": backend.public_user(row),
            "permissions": backend.role_permission_codes(self.conn, row["role"]),
        }

    def seed_seal_id(self) -> str:
        row = self.conn.execute(
            """
            SELECT id FROM company_seals
            WHERE company_id = 'CO-001' AND seal_category = 'general_seal' AND seal_size_type = 'large_seal'
            LIMIT 1
            """
        ).fetchone()
        self.assertIsNotNone(row)
        image = Image.new("RGBA", (400, 400), (255, 255, 255, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((24, 24, 376, 376), outline=(190, 0, 0, 255), width=18)
        draw.line((80, 200, 320, 200), fill=(190, 0, 0, 255), width=14)
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        backend.upload_company_seal_file(
            self.conn,
            row["id"],
            {
                "file_name": "official-company-seal.png",
                "file_mime_type": "image/png",
                "content_base64": base64.b64encode(stream.getvalue()).decode("ascii"),
                "actor": "unit-test",
            },
        )
        return row["id"]

    def uploaded_pdf_base64(self) -> str:
        data = backend.build_official_pdf(
            {
                "doc_no": "測試字第1150702001號",
                "company_name": "歲悅股份有限公司",
                "doc_type": "函",
                "agency_name": "測試機關",
                "subject": "上傳 PDF 用印測試",
                "body": "去識別化測試資料。",
            }
        )
        return base64.b64encode(data).decode("ascii")

    def approve_until_after_stamp(self, detail: dict) -> dict:
        terminal = {
            "pending_general_affairs_dispatch",
            "returned_to_applicant_for_send",
            "closed",
            "stamping_failed",
        }
        while detail["current_status"] not in terminal:
            current_step = next(step for step in detail["approval_steps"] if step["step_key"] == detail["current_step"])
            approver = self.session_for_user_id(current_step["approver_user_id"])
            source_type = "original_pdf" if detail["source_type"] == "uploaded_pdf" else "generated_pdf"
            review_file_types = {source_type, "prepared_pdf", "attachment"}
            for file_meta in detail["files"]:
                if file_meta["file_type"] in review_file_types:
                    backend.official_document_download_file(
                        self.conn,
                        detail["id"],
                        file_meta["id"],
                        approver,
                        "127.0.0.1",
                        "unit-test-review",
                    )
            detail = backend.approve_official_document(
                self.conn,
                detail["id"],
                {
                    "expected_step_id": current_step["id"],
                    "comment": f"{current_step['step_name']}核准",
                    "review_acknowledgements": {
                        "original_reviewed": True,
                        "edited_version_reviewed": True,
                        "attachments_reviewed": True,
                    },
                },
                approver,
            )
        return detail

    def test_blank_document_runs_workflow_stamps_then_general_affairs_dispatches(self) -> None:
        employee = self.login_session("sales-assistant@suiyuecare.com")
        seal_id = self.seed_seal_id()

        detail = backend.create_official_document(
            self.conn,
            {
                "source_type": "blank_editor",
                "company_id": "CO-001",
                "seal_id": seal_id,
                "title": "測試空白公文用印",
                "subject": "測試空白公文用印",
                "description": "去識別化說明文字。",
                "method": "去識別化辦法文字。",
                "recipient": "測試機關",
                "request_reason": "正式流程上線前測試。",
                "document_category": "主管機關 申請或回覆文件（與 費用、法令無關）",
                "dispatch_method": "electronic_official_document_by_general_affairs",
                "submit": True,
                "stamp_position": {"page": 1, "x": 420, "y": 130, "width": 85, "height": 85},
            },
            employee,
        )

        self.assertEqual(detail["current_status"], "pending_applicant_manager")
        self.assertEqual([step["step_key"] for step in detail["approval_steps"]], ["applicant_manager", "department_head", "admin_director", "general_affairs_review", "applicant_confirm"])
        self.assertIn("generated_pdf", {file["file_type"] for file in detail["files"]})
        self.assertEqual(detail["application_package"]["record_type"], "official_document_application")
        self.assertEqual(detail["application_package"]["summary"]["version_count"], len(detail["document_versions"]))
        self.assertEqual(detail["attachments"], [])
        self.assertNotIn("file_storage_key", detail["files"][0])
        self.assertNotIn("file_object_id", detail["files"][0])
        with self.assertRaises(PermissionError):
            backend.approve_official_document(self.conn, detail["id"], {}, employee)

        detail = self.approve_until_after_stamp(detail)

        self.assertEqual(detail["current_status"], "pending_general_affairs_dispatch")
        self.assertEqual(detail["current_step"], "general_affairs_dispatch")
        self.assertEqual(detail["stamp_request"]["status"], "stamped")
        self.assertEqual(detail["dispatch_record"]["dispatch_method"], "electronic_official_document_by_general_affairs")
        self.assertEqual(detail["dispatch_record"]["dispatch_owner_type"], "general_affairs")
        self.assertEqual(detail["dispatch_record"]["dispatch_status"], "pending")
        stamped_files = [file for file in detail["files"] if file["file_type"] == "stamped_pdf"]
        self.assertEqual(len(stamped_files), 1)
        self.assertTrue(stamped_files[0]["is_stamped"])
        self.assertEqual(stamped_files[0]["display_label"], "已用印版本")
        self.assertNotIn("file_storage_key", stamped_files[0])
        self.assertNotIn("file_object_id", stamped_files[0])
        self.assertEqual(detail["application_package"]["id"], detail["id"])
        self.assertEqual(detail["application_package"]["summary"]["has_stamped_pdf"], True)
        self.assertIn("stamped_pdf", {file["file_type"] for file in detail["application_package"]["document_versions"]})

        actions = {
            row["action"]
            for row in self.conn.execute("SELECT action FROM official_document_approval_logs WHERE document_id = ?", (detail["id"],))
        }
        self.assertTrue({"submit", "approve", "read_seal_vault_for_stamp", "auto_stamp"}.issubset(actions))

        review_download_count = self.conn.execute(
            "SELECT COUNT(*) AS count FROM official_document_approval_logs WHERE action = 'download_file' AND document_id = ?",
            (detail["id"],),
        ).fetchone()["count"]
        _, file_meta, data = backend.official_document_download_file(
            self.conn,
            detail["id"],
            stamped_files[0]["id"],
            employee,
            "127.0.0.1",
            "unit-test",
        )
        self.assertEqual(file_meta["file_type"], "stamped_pdf")
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) AS count FROM official_document_approval_logs WHERE action = 'download_file' AND document_id = ?", (detail["id"],)).fetchone()["count"],
            review_download_count + 1,
        )
        refreshed = backend.official_document_detail(self.conn, detail["id"], employee)
        self.assertEqual(refreshed["application_package"]["download_logs"][0]["document_id"], detail["id"])
        self.assertEqual(refreshed["download_logs"][0]["action"], "download_file")
        self.assertEqual(refreshed["application_package"]["summary"]["download_count"], review_download_count + 1)

        general_affairs = self.login_session("edoc@suiyuecare.com")
        proof = backend.upload_official_dispatch_proof_file(
            self.conn,
            detail["id"],
            {
                "file_name": "dispatch-proof.pdf",
                "file_mime_type": "application/pdf",
                "content_base64": base64.b64encode(b"%PDF-1.4\nproof").decode("ascii"),
            },
            general_affairs,
        )
        self.assertEqual(proof["file"]["file_type"], "dispatch_proof")
        self.assertNotIn("file_storage_key", proof["file"])
        completed = backend.complete_official_dispatch(
            self.conn,
            detail["id"],
            {
                "external_official_document_number": "外部字第001號",
                "dispatch_date": "2026-07-02",
                "recipient": "測試機關",
                "dispatch_note": "已至外部電子公文系統完成發文。",
            },
            general_affairs,
        )
        self.assertEqual(completed["current_status"], "dispatched")
        self.assertEqual(completed["dispatch_record"]["dispatch_status"], "dispatched")
        self.assertEqual(completed["dispatch_record"]["proof_file"]["display_label"], "寄發證明")

        hr = self.login_session("hr@suiyuecare.com")
        document = backend.official_document_row(self.conn, detail["id"])
        steps = backend.official_document_steps(self.conn, detail["id"])
        self.assertFalse(backend.canDownloadOfficialDocument(hr["user"], document, steps))
        with self.assertRaises(PermissionError):
            backend.official_document_download_file(self.conn, detail["id"], stamped_files[0]["id"], hr)

    def test_blank_document_cannot_bypass_managed_dispatch(self) -> None:
        employee = self.login_session("sales-assistant@suiyuecare.com")
        seal_id = self.seed_seal_id()
        with self.assertRaisesRegex(ValueError, "official_document_dispatch_must_be_managed_in_system"):
            backend.create_official_document(
                self.conn,
                {
                    "source_type": "blank_editor",
                    "company_id": "CO-001",
                    "seal_id": seal_id,
                    "title": "自行寄發測試",
                    "subject": "自行寄發測試",
                    "recipient": "測試機關",
                    "request_reason": "自行寄發。",
                    "document_category": "主管機關 申請或回覆文件（與 費用、法令無關）",
                    "dispatch_method": "return_to_applicant_for_manual_send",
                    "submit": True,
                },
                employee,
            )

    def test_blank_document_cannot_choose_no_dispatch(self) -> None:
        employee = self.login_session("sales-assistant@suiyuecare.com")
        seal_id = self.seed_seal_id()
        with self.assertRaisesRegex(ValueError, "official_document_dispatch_must_be_managed_in_system"):
            backend.create_official_document(
                self.conn,
                {
                    "source_type": "blank_editor",
                    "company_id": "CO-001",
                    "seal_id": seal_id,
                    "title": "不寄發歸檔測試",
                    "subject": "不寄發歸檔測試",
                    "recipient": "內部留存",
                    "request_reason": "僅用印歸檔。",
                    "document_category": "主管機關 申請或回覆文件（與 費用、法令無關）",
                    "dispatch_method": "no_dispatch_required",
                    "submit": True,
                },
                employee,
            )

    def test_uploaded_pdf_source_is_private_original_pdf_and_rejects_non_pdf(self) -> None:
        employee = self.login_session("sales-assistant@suiyuecare.com")
        seal_id = self.seed_seal_id()

        draft = backend.create_official_document(
            self.conn,
            {
                "source_type": "uploaded_pdf",
                "company_id": "CO-001",
                "seal_id": seal_id,
                "title": "測試上傳 PDF 用印",
                "subject": "測試上傳 PDF 用印",
                "recipient": "測試機關",
                "request_reason": "測試既有 PDF 用印。",
                "document_category": "主管機關 申請或回覆文件（與 費用、法令無關）",
                "file_name": "source.pdf",
                "content_base64": self.uploaded_pdf_base64(),
                "submit": False,
            },
            employee,
        )

        files = draft["files"]
        self.assertEqual([file["file_type"] for file in files], ["original_pdf"])
        self.assertEqual(draft["application_package"]["record_type"], "official_document_application")
        self.assertEqual(draft["document_versions"][0]["file_type"], "original_pdf")
        self.assertNotIn("file_storage_key", files[0])
        self.assertNotIn("file_object_id", files[0])
        stored = self.conn.execute("SELECT * FROM official_document_files WHERE id = ?", (files[0]["id"],)).fetchone()
        self.assertIn("official-documents", stored["file_storage_key"])
        self.assertTrue((backend.STORAGE_DIR / stored["file_storage_key"]).exists())

        with self.assertRaisesRegex(ValueError, "original_pdf_must_be_pdf"):
            backend.create_official_document(
                self.conn,
                {
                    "source_type": "uploaded_pdf",
                    "company_id": "CO-001",
                    "seal_id": seal_id,
                    "title": "錯誤檔案",
                    "document_category": "主管機關 申請或回覆文件（與 費用、法令無關）",
                    "content_base64": base64.b64encode(b"not a pdf").decode("ascii"),
                    "submit": False,
                },
                employee,
            )


if __name__ == "__main__":
    unittest.main()
