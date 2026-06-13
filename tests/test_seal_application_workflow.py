from __future__ import annotations

import sqlite3
import unittest

import backend


class SealApplicationWorkflowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(backend.SCHEMA)
        backend.seed(self.conn)
        backend.seed_auth(self.conn)
        backend.seed_persistent_registries(self.conn)
        backend.seed_signing_certificates(self.conn)
        backend.seed_certificate_authorities(self.conn)
        backend.seed_seal_assets(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def login_session(self, email: str) -> dict:
        session, status = backend.authenticate_local(
            self.conn,
            {"email": email, "password": "demo1234", "provider": "unittest"},
            "127.0.0.1",
            "unittest",
        )
        self.assertEqual(status, 200)
        return session

    def source_pdf_file_id(self) -> str:
        pdf = backend.build_official_pdf(
            {
                "doc_no": "歲悅字第1150613001號",
                "company_name": "歲悅股份有限公司",
                "doc_type": "函",
                "agency_name": "測試機關",
                "subject": "測試用印 PDF",
                "body": "去識別化測試資料。",
            }
        )
        row = backend.store_file_object(
            self.conn,
            "DOC-OUT-1140522-007",
            "uploaded-source.pdf",
            pdf,
            "source-pdf",
            "uploaded-source",
            "員工測試",
        )
        self.conn.execute("UPDATE file_objects SET scan_status = '已通過' WHERE id = ?", (row["id"],))
        return row["id"]

    def submit_payload(self, file_id: str) -> dict:
        return {
            "document_id": "DOC-OUT-1140522-007",
            "application_type": "official_document",
            "company_name": "歲悅股份有限公司",
            "department": "行政部",
            "title": "測試多章位用印",
            "seal_id": "SEAL-001",
            "source_pdf_file_object_id": file_id,
            "approval_route_code": "B",
            "stamp_positions": [
                {"page": 1, "x": 420, "y": 130, "w": 85, "h": 85, "label": "公司章", "type": "一般章", "seal_id": "SEAL-001"},
                {"page": 1, "x": 500, "y": 130, "w": 52, "h": 52, "label": "負責人章", "type": "圖記章", "seal_id": "SEAL-002"},
                {"page": "all", "x": 560, "y": 385, "w": 24, "h": 96, "label": "騎縫章", "type": "多頁章", "seal_id": "SEAL-003"},
            ],
        }

    def test_employee_submit_locks_pdf_positions_and_actor_snapshots(self) -> None:
        employee = self.login_session("sales-assistant@suiyuecare.com")
        result = backend.seal_application_submit(self.conn, self.submit_payload(self.source_pdf_file_id()), employee)

        self.assertEqual(result["status"], "待主管簽核")
        self.assertEqual(result["application_type"], "official_document")
        self.assertEqual(len(result["stamp_positions"]), 3)
        self.assertTrue(result["locked_pdf_sha256"])
        self.assertTrue(result["locked_positions_sha256"])
        snapshots = self.conn.execute(
            "SELECT * FROM approval_step_actor_snapshots WHERE source_id = ? ORDER BY step_no",
            (result["id"],),
        ).fetchall()
        self.assertGreaterEqual(len(snapshots), 6)
        self.assertEqual(snapshots[0]["status"], "已完成")
        self.assertEqual(snapshots[1]["approver_role"], "主管")

    def test_supervisor_approval_auto_stamps_pdf_and_notifies_applicant(self) -> None:
        employee = self.login_session("sales-assistant@suiyuecare.com")
        supervisor = self.login_session("director@suiyuecare.com")
        submitted = backend.seal_application_submit(self.conn, self.submit_payload(self.source_pdf_file_id()), employee)

        approved = backend.seal_application_approve(self.conn, submitted["id"], {"comment": "測試核准"}, supervisor)

        self.assertEqual(approved["status"], "已押章")
        self.assertTrue(approved["stamp_no"].startswith("STAMP-"))
        self.assertTrue(approved["pdf_after_version_id"])
        self.assertEqual(approved["pdf_after"]["version_type"], "after_seal")
        self.assertTrue(approved["signature"]["id"].startswith("ESIG-"))
        notices = self.conn.execute("SELECT * FROM notifications WHERE source = ?", (submitted["id"],)).fetchall()
        self.assertGreaterEqual(len(notices), 2)
        with self.assertRaises(ValueError):
            backend.seal_application_approve(self.conn, submitted["id"], {}, supervisor)

    def test_changed_stamp_position_hash_is_rejected_before_approval(self) -> None:
        employee = self.login_session("sales-assistant@suiyuecare.com")
        supervisor = self.login_session("director@suiyuecare.com")
        submitted = backend.seal_application_submit(self.conn, self.submit_payload(self.source_pdf_file_id()), employee)
        self.conn.execute(
            "UPDATE seal_applications SET stamp_positions_json = ? WHERE id = ?",
            ('[{"page":1,"x":1,"y":1,"w":10,"h":10,"label":"竄改"}]', submitted["id"]),
        )

        with self.assertRaisesRegex(ValueError, "locked_stamp_positions_mismatch"):
            backend.seal_application_approve(self.conn, submitted["id"], {}, supervisor)

    def test_supervisor_can_return_application_to_applicant(self) -> None:
        employee = self.login_session("sales-assistant@suiyuecare.com")
        supervisor = self.login_session("director@suiyuecare.com")
        submitted = backend.seal_application_submit(self.conn, self.submit_payload(self.source_pdf_file_id()), employee)

        returned = backend.seal_application_return(self.conn, submitted["id"], {"reason": "請補附件"}, supervisor)

        self.assertEqual(returned["status"], "退回補正")
        self.assertEqual(returned["reject_reason"], "請補附件")
        notices = self.conn.execute("SELECT * FROM notifications WHERE source = ?", (submitted["id"],)).fetchall()
        self.assertGreaterEqual(len(notices), 2)


if __name__ == "__main__":
    unittest.main()
