from __future__ import annotations

import base64
import io
import json
import random
import sqlite3
import tempfile
import unittest
from pathlib import Path

import backend
from PIL import Image, ImageDraw
from pypdf import PdfReader


class FiveAccountEditorWorkflowTestCase(unittest.TestCase):
    """Exercise the complete PDF-editor workflow with five isolated users.

    The accounts and seal below exist only in the in-memory test database.  The
    test never signs in as, mutates, or downloads data belonging to a production
    employee.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.original_storage_dir = backend.STORAGE_DIR
        self.original_private_seal_dir = backend.PRIVATE_SEAL_STORAGE_DIR
        self.original_use_supabase = backend.USE_SUPABASE
        self.original_deployment_env = backend.DEPLOYMENT_ENV
        self.original_editor_mode = backend.EDOC_PDF_EDITOR_V2_COMPANY_MODE
        self.original_editor_ids = backend.EDOC_PDF_EDITOR_V2_COMPANY_IDS
        backend.STORAGE_DIR = Path(self.tmp.name) / "storage"
        backend.PRIVATE_SEAL_STORAGE_DIR = backend.STORAGE_DIR / "seal-vault" / "seals"
        backend.USE_SUPABASE = False
        backend.DEPLOYMENT_ENV = "test"
        backend.EDOC_PDF_EDITOR_V2_COMPANY_MODE = "manual_allowlist"
        backend.EDOC_PDF_EDITOR_V2_COMPANY_IDS = "CO-001"

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
        self.seal_id = self._seed_test_only_seal()
        self.applicant_ids = self._seed_five_test_accounts()

    def tearDown(self) -> None:
        self.conn.close()
        backend.STORAGE_DIR = self.original_storage_dir
        backend.PRIVATE_SEAL_STORAGE_DIR = self.original_private_seal_dir
        backend.USE_SUPABASE = self.original_use_supabase
        backend.DEPLOYMENT_ENV = self.original_deployment_env
        backend.EDOC_PDF_EDITOR_V2_COMPANY_MODE = self.original_editor_mode
        backend.EDOC_PDF_EDITOR_V2_COMPANY_IDS = self.original_editor_ids
        self.tmp.cleanup()

    def _session_for_user_id(self, user_id: str) -> dict:
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        self.assertIsNotNone(row)
        return {
            "token": "isolated-five-account-test",
            "expiresAt": "2099-12-31 23:59:59",
            "user": backend.public_user(row),
            "permissions": backend.role_permission_codes(self.conn, row["role"]),
        }

    def _seed_five_test_accounts(self) -> list[str]:
        template_row = self.conn.execute("SELECT * FROM users WHERE id = 'USR-008'").fetchone()
        self.assertIsNotNone(template_row)
        template = dict(template_row)
        rng = random.Random(20260827)
        aliases = rng.sample(
            ["松", "竹", "梅", "蘭", "雲", "海", "山", "星", "月", "川"],
            5,
        )
        account_ids: list[str] = []
        for index, alias in enumerate(aliases, start=1):
            row = dict(template)
            row.update(
                {
                    "id": f"E2E-APPLICANT-{index}",
                    "auth_user_id": None,
                    "account_source": "edoc",
                    "logging_account_id": None,
                    "logging_role_key": None,
                    "finance_employee_id": None,
                    "finance_tenant_id": None,
                    "name": f"隔離測試{alias}{index}",
                    "email": f"e2e-applicant-{index}@example.test",
                    "password_hash": None,
                    "company_id": "CO-001",
                    "company_name": "歲悅股份有限公司",
                    "unit": "去識別化測試部門",
                    "title": "測試申請人",
                    "job_level": "職員",
                    "role": "員工",
                    "provider": "isolated-e2e",
                    "mfa_status": "已啟用",
                    "status": "啟用",
                    "last_login_at": None,
                    "created_at": backend.now(),
                }
            )
            backend.insert_row(self.conn, "users", row)
            account_ids.append(row["id"])
        return account_ids

    def _seed_test_only_seal(self) -> str:
        seal = self.conn.execute(
            """
            SELECT id FROM company_seals
            WHERE company_id = 'CO-001'
              AND seal_category = 'general_seal'
              AND seal_size_type = 'large_seal'
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()
        self.assertIsNotNone(seal)
        image = Image.new("RGBA", (400, 400), (255, 255, 255, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((24, 24, 376, 376), outline=(180, 0, 0, 255), width=18)
        draw.line((90, 200, 310, 200), fill=(180, 0, 0, 255), width=14)
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        backend.upload_company_seal_file(
            self.conn,
            seal["id"],
            {
                "file_name": "isolated-test-only-seal.png",
                "file_mime_type": "image/png",
                "content_base64": base64.b64encode(stream.getvalue()).decode("ascii"),
                "actor": "isolated-e2e",
            },
        )
        return str(seal["id"])

    @staticmethod
    def _a4_pdf_bytes(case_number: int) -> bytes:
        return backend.build_official_pdf(
            {
                "doc_no": f"隔離測試字第{case_number:04d}號",
                "company_name": "歲悅股份有限公司",
                "doc_type": "函",
                "agency_name": "去識別化測試機關",
                "subject": f"PDF 編輯器五帳號驗收第 {case_number} 件",
                "body": "本文件僅供隔離自動化測試，不含真實人員或業務資料。",
            }
        )

    def _add_editor_elements(self, revision: dict, case_number: int) -> dict:
        state = json.loads(json.dumps(revision["state"], ensure_ascii=False))
        self.assertEqual(len(state["pages"]), 1)
        page_id = state["pages"][0]["pageId"]
        seal = backend.company_seal_row(self.conn, self.seal_id)
        seal_file = backend.require_current_company_seal_file(self.conn, self.seal_id)
        profile = backend.company_seal_file_dimension_profile(
            seal["seal_size_type"], seal_file, current=True
        )
        state["elements"] = [
            {
                "id": f"E2E-TEXT-{case_number}",
                "pageId": page_id,
                "kind": "text",
                "x": 60,
                "y": 665,
                "width": 330,
                "height": 36,
                "rotation": 0,
                "opacity": 1,
                "zIndex": 20,
                "properties": {
                    "text": f"隔離測試案件 {case_number}：文字保持在印章前景",
                    "fontSize": 13,
                    "fontFamily": "edukai",
                    "color": "#222222",
                },
            },
            {
                "id": f"E2E-SEAL-{case_number}",
                "pageId": page_id,
                "kind": "seal",
                "x": 450,
                "y": 72,
                "width": profile["width_pt"],
                "height": profile["height_pt"],
                "rotation": 0,
                "opacity": 1,
                "zIndex": 10,
                "properties": {
                    "sealId": self.seal_id,
                    "sealFileId": seal_file["id"],
                    "sealFileSha256": seal_file["file_hash"],
                    "renderWidthMm": profile["width_mm"],
                    "renderHeightMm": profile["height_mm"],
                    "dimensionPolicyVersion": profile["dimension_policy_version"],
                },
            },
        ]
        return state

    def _approve_and_stamp(self, detail: dict) -> dict:
        while detail["current_status"] not in {"stamped", "stamping_failed"}:
            current_step = next(
                step
                for step in detail["approval_steps"]
                if step["step_key"] == detail["current_step"]
            )
            approver = self._session_for_user_id(current_step["approver_user_id"])
            for file_meta in detail["files"]:
                if file_meta["file_type"] in {"original_pdf", "prepared_pdf", "attachment"}:
                    backend.official_document_download_file(
                        self.conn,
                        detail["id"],
                        file_meta["id"],
                        approver,
                        "127.0.0.1",
                        "five-account-e2e-review",
                    )
            detail = backend.approve_official_document(
                self.conn,
                detail["id"],
                {
                    "expected_step_id": current_step["id"],
                    "comment": f"{current_step['step_name']}隔離驗收核准",
                    "prepared_sha256": detail["stamp_request"]["prepared_sha256"],
                    "manifest_sha256": detail["stamp_request"]["editor_manifest_sha256"],
                    "review_acknowledgements": {
                        "original_reviewed": True,
                        "edited_version_reviewed": True,
                        "attachments_reviewed": True,
                    },
                },
                approver,
            )
        self.assertEqual(detail["current_status"], "stamped")
        self.assertEqual(detail["current_step"], "applicant_confirm")
        self.assertEqual(detail["stamp_request"]["status"], "stamped")
        return detail

    def test_five_randomized_accounts_complete_editor_approval_stamp_and_download(self) -> None:
        category_route_pairs = [
            ("合作意向書", "A"),
            ("商務合約", "B"),
            ("服務委託合約", "C"),
            ("採購合約", "D"),
            ("勞保、健保、退休金文件", "A"),
        ]
        randomized_cases = list(zip(self.applicant_ids, category_route_pairs))
        random.Random(20260827).shuffle(randomized_cases)
        completed: list[dict] = []

        for case_number, (applicant_id, (category, expected_route)) in enumerate(
            randomized_cases, start=1
        ):
            applicant = self._session_for_user_id(applicant_id)
            draft = backend.create_official_editor_draft(
                self.conn,
                {
                    "company_id": "CO-001",
                    "title": f"隔離五帳號驗收第 {case_number} 件",
                    "subject": f"隔離五帳號驗收第 {case_number} 件",
                    "request_reason": "上線前完整流程驗收",
                    "document_category": category,
                    "dispatch_method": "no_dispatch_required",
                },
                applicant,
            )
            document_id = draft["document_id"]
            pdf_bytes = self._a4_pdf_bytes(case_number)
            pdf_hash = backend.sha256_bytes(pdf_bytes)
            intent = backend.create_official_editor_upload_intent(
                self.conn,
                document_id,
                {
                    "asset_kind": "source_pdf",
                    "file_name": f"isolated-case-{case_number}.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": len(pdf_bytes),
                    "sha256": pdf_hash,
                },
                applicant,
            )
            backend.store_official_editor_local_upload(
                self.conn,
                document_id,
                intent["upload_id"],
                pdf_bytes,
                applicant,
                "application/pdf",
            )
            finalized = backend.finalize_official_editor_upload(
                self.conn,
                document_id,
                intent["upload_id"],
                {"sha256": pdf_hash},
                applicant,
            )
            revision = finalized["editor_revision"]
            edited_state = self._add_editor_elements(revision, case_number)
            saved = backend.save_official_editor_state(
                self.conn,
                document_id,
                {
                    "revisionNo": revision["revisionNo"],
                    "baseManifestSha256": revision["manifestSha256"],
                    "state": edited_state,
                },
                applicant,
            )
            preflight = backend.preflight_official_editor(
                self.conn,
                document_id,
                {
                    "editorRevisionId": saved["id"],
                    "manifestSha256": saved["manifestSha256"],
                },
                applicant,
            )
            detail = backend.submit_official_document(
                self.conn,
                document_id,
                {
                    "editorRevisionId": preflight["editorRevisionId"],
                    "manifestSha256": preflight["manifestSha256"],
                    "preparedFileId": preflight["preparedFileId"],
                    "preparedSha256": preflight["preparedSha256"],
                    "comment": "五帳號隔離流程送簽",
                },
                applicant,
            )
            self.assertEqual(
                detail["metadata"]["official_seal"]["approval_route_code"],
                expected_route,
            )
            with self.assertRaisesRegex(ValueError, "editor_locked_after_submit"):
                backend.save_official_editor_state(
                    self.conn,
                    document_id,
                    {
                        "revisionNo": preflight["revisionNo"],
                        "baseManifestSha256": preflight["manifestSha256"],
                        "state": preflight["revision"]["state"],
                    },
                    applicant,
                )

            detail = self._approve_and_stamp(detail)
            stamped_file = next(
                file_meta
                for file_meta in detail["files"]
                if file_meta["file_type"] == "stamped_pdf"
            )
            _, _, applicant_copy = backend.official_document_download_file(
                self.conn,
                document_id,
                stamped_file["id"],
                applicant,
                "127.0.0.1",
                "five-account-e2e-applicant-receipt",
            )
            self.assertTrue(applicant_copy.startswith(b"%PDF"))
            self.assertEqual(len(PdfReader(io.BytesIO(applicant_copy)).pages), 1)
            detail = backend.confirm_official_document(
                self.conn,
                document_id,
                {"comment": "申請人已收到隔離測試用印檔"},
                applicant,
            )
            self.assertEqual(detail["current_status"], "closed")

            participant_ids = {
                applicant_id,
                *(
                    step["approver_user_id"]
                    for step in detail["approval_steps"]
                    if step.get("approver_user_id")
                ),
            }
            for participant_id in participant_ids:
                participant = self._session_for_user_id(participant_id)
                _, _, downloaded = backend.official_document_download_file(
                    self.conn,
                    document_id,
                    stamped_file["id"],
                    participant,
                    "127.0.0.1",
                    "five-account-e2e-completed-download",
                )
                self.assertEqual(backend.sha256_bytes(downloaded), stamped_file["file_hash"])
            completed.append(
                {
                    "document_id": document_id,
                    "route": expected_route,
                    "participants": len(participant_ids),
                }
            )

        self.assertEqual(len(completed), 5)
        self.assertEqual(sorted(item["route"] for item in completed), ["A", "A", "B", "C", "D"])
        # The isolated seed assigns the same supervisory account to two
        # consecutive roles, so four distinct people can cover five steps.
        # Every stored step participant is nevertheless exercised above.
        self.assertTrue(all(item["participants"] >= 4 for item in completed))

    def test_finance_seniority_shortening_is_server_derived(self) -> None:
        self.assertEqual(
            [step["key"] for step in backend.official_workflow_steps_for_finance_applicant("C", "staff")],
            [
                "applicant_manager",
                "department_head",
                "ceo",
                "admin_director",
                "general_affairs_review",
                "applicant_confirm",
            ],
        )
        self.assertEqual(
            [step["key"] for step in backend.official_workflow_steps_for_finance_applicant("D", "section_chief")],
            [
                "department_head",
                "ceo",
                "admin_director",
                "general_affairs_review",
                "applicant_confirm",
            ],
        )
        self.assertEqual(
            [step["key"] for step in backend.official_workflow_steps_for_finance_applicant("D", "department_head")],
            ["ceo", "admin_director", "general_affairs_review", "applicant_confirm"],
        )


if __name__ == "__main__":
    unittest.main()
