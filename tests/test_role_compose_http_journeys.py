"""Real local HTTP journeys; all identities, seals and files are synthetic.

Finance and AV are deterministic fixtures. These tests do not contact hosted
Supabase, real employees, real mail delivery, or the government exchange.
"""
from __future__ import annotations

import base64
import hashlib
import io
import time
import unittest
import uuid

from pypdf import PdfReader

import backend
from tests import test_five_account_http_acceptance as acceptance


class RoleComposeHttpJourneysTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = acceptance.FiveAccountHttpAcceptanceTest
        cls.fixture.setUpClass()
        cls.tokens = {
            case["ordinal"]: cls.fixture._portal_session(case["email"])
            for case in cls.fixture.case_definitions
        }

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDownClass()

    def api(self, method, path, token, payload=None, status=200):
        kwargs = {"token": token}
        if payload is not None:
            kwargs["json_body"] = payload
        return self.fixture._expect_json(method, path, status, **kwargs)

    def create(self, case, mode):
        token = self.tokens[case["ordinal"]]
        payload = {
            "id": "OD-ROLE-COMPOSE-" + uuid.uuid4().hex,
            "source_type": "blank_editor",
            "document_type": "outgoing_official_document",
            "company_id": case["company_id"],
            "title": "隔離驗收公文",
            "subject": "有關隔離驗收流程一案，請查照。",
            "description": "一、本函為去識別化驗收資料。",
            "recipient": "隔離驗收收文單位",
            "request_reason": "測試不同職級完整公文流程",
            "document_category": case["category"],
            "output_mode": mode,
            "dispatch_method": "email_by_general_affairs",
            "dispatch_date": "2026-09-09",
            "metadata": {"contact_email": "isolated@example.test", "attachment_details": "測試附件說明"},
            "submit": False,
        }
        if mode == "physical":
            seal = self.fixture.seals[case["company_id"]]
            payload.update({
                "seal_id": seal["seal_id"],
                "stamp_positions": [{"seal_id": seal["seal_id"], "page": 1, "x": 450, "y": 90}],
            })
        detail = self.api("POST", "/api/official-documents", token, payload, 201)
        attachment = self.fixture._make_attachment_pdf(case["ordinal"])
        self.api("POST", f"/api/official-documents/{detail['id']}/files", token, {
            "file_name": "isolated-attachment.pdf", "file_mime_type": "application/pdf",
            "content_base64": base64.b64encode(attachment).decode("ascii"),
        }, 201)
        return detail

    def test_editor_source_download_reuses_session_and_preserves_access_guards(self):
        case = min(self.fixture.case_definitions, key=lambda item: item["ordinal"])
        token = self.tokens[case["ordinal"]]
        draft = self.api("POST", "/api/official-documents/editor-drafts", token, {
            "company_id": case["company_id"], "title": "隔離下載驗收",
            "subject": "隔離下載驗收", "request_reason": "確認續編可取得原稿",
            "document_category": case["category"], "dispatch_method": "no_dispatch_required",
        }, 201)
        document_id = draft["document_id"]
        source = self.fixture._make_a4_pdf(case)
        digest = backend.sha256_bytes(source)
        intent = self.api("POST", f"/api/official-documents/{document_id}/editor-uploads", token, {
            "asset_kind": "source_pdf", "file_name": "isolated-source.pdf",
            "mime_type": "application/pdf", "size_bytes": len(source), "sha256": digest,
        }, 201)
        if self.fixture.upload_protocol == "local_supabase_tus":
            self.fixture._perform_tus_upload(intent, source)
        else:
            uploaded = self.fixture._request("PUT", intent["upload_url"], token=token, raw_body=source, headers={"Content-Type": "application/pdf"})
            self.assertEqual(uploaded.status, 201)
        self.api("POST", f"/api/official-documents/{document_id}/editor-uploads/{intent['upload_id']}/finalize", token, {"sha256": digest})
        state = self.api("GET", f"/api/official-documents/{document_id}/editor-state", token)
        self.assertEqual(len(state["assets"]), 1)
        url = state["assets"][0]["url"]
        # Production current_session performs Finance projection writes. A nested
        # connection used to block on these writes for the SQLite busy timeout.
        started = time.monotonic()
        result = self.fixture._request("GET", url, token=token)
        self.assertEqual(result.status, 200)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(backend.sha256_bytes(result.body), digest)
        headers = {name.lower(): value for name, value in result.headers}
        self.assertEqual(headers["content-type"], "application/pdf")
        self.assertIn("no-store", headers["cache-control"])
        anonymous = self.fixture._request("GET", url)
        self.assertIn(anonymous.status, {401, 403})
        other = next(item for item in self.fixture.case_definitions if item["company_id"] != case["company_id"])
        forbidden = self.fixture._request("GET", url, token=self.tokens[other["ordinal"]])
        self.assertEqual(forbidden.status, 403)
        self.assertEqual(forbidden.json()["detail"], "official_editor_company_forbidden")
        invalid = self.fixture._request("GET", url.rsplit("token=", 1)[0] + "token=invalid", token=token)
        self.assertEqual(invalid.status, 403)
        self.assertEqual(invalid.json()["detail"], "editor_asset_url_invalid")

    def test_editor_seal_preview_does_not_deadlock_or_disclose_original(self):
        case = min(self.fixture.case_definitions, key=lambda item: item["ordinal"])
        token = self.tokens[case["ordinal"]]
        seal = self.fixture.seals[case["company_id"]]
        url = f"/api/company-seals/{seal['seal_id']}/editor-preview?fileId={seal['seal_file_id']}&fileSha256={seal['seal_file_sha256']}"
        started = time.monotonic()
        result = self.fixture._request("GET", url, token=token)
        self.assertEqual(result.status, 200)
        self.assertLess(time.monotonic() - started, 5)
        self.assertTrue(result.body.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertNotEqual(backend.sha256_bytes(result.body), seal["seal_file_sha256"])
        headers = {name.lower(): value for name, value in result.headers}
        self.assertIn("no-store", headers["cache-control"])
        self.assertEqual(int(headers["x-edoc-preview-expires-in"]), backend.EDOC_EDITOR_PREVIEW_TTL_SECONDS)
        anonymous = self.fixture._request("GET", url)
        self.assertIn(anonymous.status, {401, 403})
        other = next(item for item in self.fixture.case_definitions if item["company_id"] != case["company_id"])
        forbidden = self.fixture._request("GET", url, token=self.tokens[other["ordinal"]])
        self.assertEqual(forbidden.status, 403)
        self.assertEqual(forbidden.json()["detail"], "editor_seal_preview_company_forbidden")
        invalid = self.fixture._request("GET", url.replace(seal["seal_file_sha256"], "0" * 64), token=token)
        self.assertEqual(invalid.status, 422)
        self.assertEqual(invalid.json()["detail"], "editor_seal_file_hash_mismatch")

    def review(self, detail):
        step = next(item for item in detail["approval_steps"] if item["step_key"] == detail["current_step"])
        token = self.fixture._token_for_user_id(step["approver_user_id"])
        for file in detail["files"]:
            if file["file_type"] in {"generated_pdf", "original_pdf", "prepared_pdf", "attachment"}:
                result = self.fixture._request("GET", f"/api/official-documents/{detail['id']}/files/{file['id']}/download", token=token)
                self.assertEqual(result.status, 200)
                self.assertTrue(result.body.startswith(b"%PDF"))
        return step, token, {
            "expected_step_id": step["id"], "comment": "隔離驗收已檢閱。",
            "review_acknowledgements": {"original_reviewed": True, "edited_version_reviewed": True, "attachments_reviewed": True},
        }

    def approve_to_dispatch(self, detail):
        count = 0
        while detail["current_status"] != "pending_general_affairs_dispatch":
            self.assertLess(count, 7)
            step, token, payload = self.review(detail)
            detail = self.api("POST", f"/api/official-documents/{detail['id']}/approve", token, payload)
            # Repeating the same click must not advance another approver's step.
            duplicate = self.fixture._request("POST", f"/api/official-documents/{detail['id']}/approve", token=token, json_body=payload)
            self.assertIn(duplicate.status, {403, 409, 422})
            self.assertIn(duplicate.json().get("detail"), {"not_current_official_document_approver", "official_document_approval_already_claimed", "official_document_not_pending_approval"})
            count += 1
        return detail

    def complete_and_confirm(self, detail, token):
        record = detail["dispatch_record"]
        owner = self.fixture._token_for_user_id(record["dispatch_owner_user_id"])
        proof = self.fixture._make_attachment_pdf(99)
        self.api("POST", f"/api/official-documents/{detail['id']}/dispatch/proof-files", owner, {
            "file_name": "isolated-dispatch-proof.pdf", "file_mime_type": "application/pdf",
            "content_base64": base64.b64encode(proof).decode("ascii"),
        }, 201)
        detail = self.api("POST", f"/api/official-documents/{detail['id']}/dispatch/complete", owner, {
            "dispatch_date": "2026-09-09", "recipient": "隔離驗收收文單位", "dispatch_note": "隔離模擬寄發，沒有發送郵件。",
        })
        self.assertEqual(detail["current_status"], "dispatched")
        detail = self.api("POST", f"/api/official-documents/{detail['id']}/confirm", token, {"comment": "隔離驗收確認收件。"})
        self.assertEqual(detail["current_status"], "closed")
        return detail, owner

    def test_five_applicants_complete_both_compose_modes_and_rejection(self):
        numbers = set()
        for case in sorted(self.fixture.case_definitions, key=lambda item: item["ordinal"]):
            for mode in ("electronic", "physical"):
                with self.subTest(role=case["role"], route=case["route"], mode=mode):
                    token = self.tokens[case["ordinal"]]
                    detail = self.create(case, mode)
                    number = detail["dispatch_no"]
                    self.assertNotIn(number, numbers)
                    numbers.add(number)
                    detail = self.api("POST", f"/api/official-documents/{detail['id']}/submit", token, {})
                    expected = [step["key"] for step in backend.official_workflow_steps_for_finance_applicant(case["route"], case["role"])]
                    self.assertEqual([step["step_key"] for step in detail["approval_steps"]], expected)
                    if case["ordinal"] == 2:
                        old_steps = {step["id"] for step in detail["approval_steps"]}
                        step, reviewer, rejection = self.review(detail)
                        rejection.update({"reason_category": "內容補正", "missing_items": ["補充說明"], "comment": "請補充測試說明。"})
                        detail = self.api("POST", f"/api/official-documents/{detail['id']}/reject", reviewer, rejection)
                        self.assertEqual(detail["current_status"], "rejected")
                        detail = self.api("PATCH", f"/api/official-documents/{detail['id']}", token, {"description": "一、已依意見補充測試說明。", "dispatch_date": "2026-09-10"})
                        self.assertEqual(detail["dispatch_no"], number)
                        detail = self.api("POST", f"/api/official-documents/{detail['id']}/resubmit", token, {"comment": "已補正測試說明。"})
                        self.assertEqual(detail["current_step"], expected[0])
                        self.assertTrue(old_steps.isdisjoint({step["id"] for step in detail["approval_steps"]}))
                    detail = self.approve_to_dispatch(detail)
                    final_id = detail["stamped_file_id"]
                    final = next(file for file in detail["files"] if file["id"] == final_id)
                    self.assertEqual(final["file_type"], "generated_pdf" if mode == "electronic" else "stamped_pdf")
                    detail, _ = self.complete_and_confirm(detail, token)
                    participant_ids = {detail["applicant_id"], *(step["approver_user_id"] for step in detail["approval_steps"])}
                    for participant in participant_ids:
                        participant_token = self.fixture._token_for_user_id(participant)
                        result = self.fixture._request("GET", f"/api/official-documents/{detail['id']}/files/{final_id}/download", token=participant_token)
                        self.assertEqual(result.status, 200)
                        self.assertEqual(hashlib.sha256(result.body).hexdigest().upper(), final["file_hash"].upper())
                        self.assertTrue(PdfReader(io.BytesIO(result.body)).pages)
                    other = next(item for item in self.fixture.case_definitions if item["company_id"] != case["company_id"])
                    for suffix in ("", "/dispatch", f"/files/{final_id}/download"):
                        self.assertEqual(self.fixture._request("GET", f"/api/official-documents/{detail['id']}{suffix}", token=self.tokens[other["ordinal"]]).status, 403)

    def test_completed_dispatch_details_are_immutable(self):
        case = self.fixture.case_definitions[0]
        token = self.tokens[case["ordinal"]]
        detail = self.create(case, "electronic")
        detail = self.api("POST", f"/api/official-documents/{detail['id']}/submit", token, {})
        detail = self.approve_to_dispatch(detail)
        detail, owner = self.complete_and_confirm(detail, token)
        before = detail["dispatch_record"]
        result = self.fixture._request("PATCH", f"/api/official-documents/{detail['id']}/dispatch", token=owner, json_body={"recipient": "不應寫入的收文單位", "dispatch_date": "2026-10-10"})
        self.assertEqual(result.status, 409, "completed dispatch metadata was still editable")
        self.assertEqual(result.json()["detail"], "official_dispatch_record_locked")
        self.assertEqual(self.api("GET", f"/api/official-documents/{detail['id']}/dispatch", owner), before)
        self.assertFalse(self.api("GET", f"/api/official-documents/{detail['id']}", owner)["can_manage_dispatch"])
        proof = self.fixture._make_attachment_pdf(99)
        result = self.fixture._request("POST", f"/api/official-documents/{detail['id']}/dispatch/proof-files", token=owner, json_body={
            "file_name": "must-not-upload.pdf", "file_mime_type": "application/pdf",
            "content_base64": base64.b64encode(proof).decode("ascii"),
        })
        self.assertEqual(result.status, 409)
        self.assertEqual(result.json()["detail"], "official_dispatch_record_locked")
        after = self.api("GET", f"/api/official-documents/{detail['id']}", owner)
        self.assertEqual({file["id"] for file in after["files"]}, {file["id"] for file in detail["files"]})

    def test_internal_dispatch_recipients_read_reply_without_creator_permission(self):
        for role in ("staff", "section_chief", "department_head"):
            case = next(item for item in self.fixture.case_definitions if item["role"] == role)
            token = self.tokens[case["ordinal"]]
            ga_email = self.fixture.snapshots_by_email[case["email"]]["actors"]["generalAffairs"]["email"]
            sender = self.fixture._portal_session(ga_email)
            with backend.connect() as conn:
                recipient = dict(conn.execute("SELECT * FROM users WHERE finance_employee_id = ?", (case["finance_user_id"],)).fetchone())
            payload = {"subject": "隔離內部派文測試", "body": "請回覆測試結果。", "recipients": [{"user_id": recipient["id"], "action_required": True}]}
            forbidden = self.fixture._request("POST", "/api/internal-dispatches", token=token, json_body=payload)
            self.assertEqual(forbidden.status, 403)
            self.assertEqual(forbidden.json()["detail"], "internal_dispatch_create_forbidden")
            detail = self.api("POST", "/api/internal-dispatches", sender, payload, 201)
            dispatch_id = detail["id"]
            self.assertIn(dispatch_id, [item["id"] for item in self.api("GET", "/api/internal-dispatches", token)])
            detail = self.api("PATCH", f"/api/internal-dispatches/{dispatch_id}/read", token, {})
            self.assertTrue(next(item for item in detail["recipients"] if item["recipient_user_id"] == recipient["id"])["read_at"])
            detail = self.api("POST", f"/api/internal-dispatches/{dispatch_id}/replies", token, {"reply_text": "隔離驗收已處理。"}, 201)
            self.assertEqual(detail["reply_status"], "completed")
            self.assertEqual(detail["replies"][0]["replier_user_id"], recipient["id"])
            self.assertEqual(self.api("GET", f"/api/internal-dispatches/{dispatch_id}", sender)["replies"][0]["reply_text"], "隔離驗收已處理。")
            other = next(item for item in self.fixture.case_definitions if item["company_id"] != case["company_id"])
            denied = self.fixture._request("GET", f"/api/internal-dispatches/{dispatch_id}", token=self.tokens[other["ordinal"]])
            self.assertEqual(denied.status, 403)
            closed = self.api("POST", f"/api/internal-dispatches/{dispatch_id}/close", sender, {"comment": "驗收結案。"})
            self.assertEqual(closed["status"], "closed")
            repeated = self.fixture._request("POST", f"/api/internal-dispatches/{dispatch_id}/replies", token=token, json_body={"reply_text": "不應讓結案案件重新開啟。"})
            self.assertEqual(repeated.status, 409)
            self.assertEqual(self.api("GET", f"/api/internal-dispatches/{dispatch_id}", sender)["status"], "closed")
