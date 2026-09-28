"""Isolated original-recipient persistence and PDF regressions.

Supabase create is intercepted before the REST boundary; no hosted project or
government exchange is contacted. All names and document content are fictitious.
"""

from __future__ import annotations

import copy
import io
import unittest
from contextlib import ExitStack
from unittest import mock

from pypdf import PdfReader

import backend


class ComposeOriginalRecipientsBackendTest(unittest.TestCase):
    company = {"id": "CO-TEST", "name": "虛構發文單位", "address": "虛構地址"}
    category = "主管機關 申請或回覆文件（與 費用、法令無關）"

    def document(
        self,
        *,
        original: str | None = "人工指定正本單位",
        copies: str = "虛構發文單位、人工增補副本單位",
        copies_manual: bool | None = None,
    ) -> dict:
        extra = {"copy_recipients": copies}
        if original is not None:
            extra["original_recipients"] = original
        if copies_manual is not None:
            extra["copy_recipients_manual"] = copies_manual
        return {
            "id": "OD-ORIGINAL-TEST",
            "company_id": self.company["id"],
            "recipient": "虛構受文單位",
            "subject": "去識別化正副本驗收",
            "description": "本函僅供隔離測試，不含真實個資。",
            "metadata_json": {"extra": extra},
        }

    def test_both_pdf_payload_builders_read_metadata_extra_and_legacy_recipient_fallback(self) -> None:
        for original, expected in (
            ("人工指定正本單位", "人工指定正本單位"),
            (None, "虛構受文單位"),
        ):
            with self.subTest(original=original):
                document = self.document(original=original)
                before = copy.deepcopy(document)
                with mock.patch.object(backend, "official_company_row", return_value=self.company), mock.patch.object(
                    backend, "supabase_official_company_row", return_value=self.company
                ):
                    sqlite_payload = backend.official_pdf_document_payload(mock.Mock(), document)
                    supabase_payload = backend.supabase_official_pdf_document_payload(document)
                self.assertEqual(sqlite_payload["original_recipients"], expected)
                self.assertEqual(supabase_payload["original_recipients"], expected)
                self.assertEqual(sqlite_payload["copy_recipients"], "虛構發文單位、人工增補副本單位")
                self.assertEqual(sqlite_payload, supabase_payload)
                self.assertEqual(document, before)

                pdf = backend.build_official_pdf(supabase_payload)
                text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)
                self.assertIn("正本：", text)
                self.assertIn(expected, text)
                self.assertIn("人工增補副本單位", text)

    def test_supabase_create_payload_persists_custom_original_without_a_network_call(self) -> None:
        session = {
            "user": {
                "id": "USER-TEST", "name": "虛構申請人", "email": "synthetic@example.test",
                "company_id": self.company["id"], "unit": "虛構部門",
            },
            "permissions": ["official_documents.compose"],
        }
        payload = {
            "id": "OD-ORIGINAL-CREATE-TEST",
            "company_id": self.company["id"],
            "source_type": "blank_editor",
            "output_mode": "electronic",
            "subject": "去識別化正本建立驗收",
            "description": "虛構說明文字。",
            "recipient": "虛構受文單位",
            "document_category": self.category,
            "submit": False,
            "metadata": {
                "original_recipients": "人工指定正本單位",
                "copy_recipients": "虛構發文單位、人工增補副本單位",
            },
        }
        captured = []

        def capture_insert(table, row):
            self.assertEqual(table, "official_documents")
            stored = {**row, "dispatch_no": "測試字第1150000001號"}
            captured.append(copy.deepcopy(stored))
            return stored

        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(backend, "launch_company_in_scope", return_value=True))
            stack.enter_context(mock.patch.object(
                backend, "authoritative_applicant_department", return_value={"id": "UNIT-TEST", "name": "虛構部門"}
            ))
            stack.enter_context(mock.patch.object(backend, "supabase_official_company_row", return_value=self.company))
            stack.enter_context(mock.patch.object(backend, "supabase_get", return_value=None))
            stack.enter_context(mock.patch.object(backend, "supabase_insert", side_effect=capture_insert))
            stack.enter_context(mock.patch.object(backend, "supabase_ensure_official_generated_pdf"))
            stack.enter_context(mock.patch.object(backend, "supabase_insert_official_log"))
            stack.enter_context(mock.patch.object(
                backend, "supabase_official_document_detail", return_value={"id": payload["id"]}
            ))
            result = backend.supabase_create_official_document(payload, session)
            self.assertEqual(result["id"], payload["id"])
            self.assertEqual(len(captured), 1)
            stored = captured[0]
            self.assertEqual(stored["metadata_json"]["extra"]["original_recipients"], "人工指定正本單位")
            pdf_payload = backend.supabase_official_pdf_document_payload(stored)
            self.assertEqual(pdf_payload["original_recipients"], "人工指定正本單位")
            self.assertEqual(pdf_payload["agency_name"], "虛構受文單位")

    def test_shared_correction_metadata_preserves_custom_original_for_both_renderers(self) -> None:
        document = self.document(original="去識別化初版正本單位")
        context = backend.official_seal_approval_context({"document_category": self.category})
        metadata = backend._official_correction_metadata(
            document,
            context,
            "",
            {"metadata": {"original_recipients": "去識別化補正正本單位"}},
        )
        self.assertEqual(metadata["extra"]["original_recipients"], "去識別化補正正本單位")
        corrected = {**document, "metadata_json": metadata}
        with mock.patch.object(backend, "official_company_row", return_value=self.company), mock.patch.object(
            backend, "supabase_official_company_row", return_value=self.company
        ):
            sqlite_payload = backend.official_pdf_document_payload(mock.Mock(), corrected)
            supabase_payload = backend.supabase_official_pdf_document_payload(corrected)
        self.assertEqual(sqlite_payload["original_recipients"], "去識別化補正正本單位")
        self.assertEqual(supabase_payload["original_recipients"], "去識別化補正正本單位")
        self.assertEqual(document["metadata_json"]["extra"]["original_recipients"], "去識別化初版正本單位")

    def test_manual_copies_are_not_replaced_by_company_in_either_pdf_path(self) -> None:
        for manually_edited, copies, expected in (
            (True, "人工自訂副本單位", "人工自訂副本單位"),
            (True, "", "無"),
            (False, "人工增補副本單位", "虛構發文單位、人工增補副本單位"),
            (None, "人工增補副本單位", "虛構發文單位、人工增補副本單位"),
        ):
            with self.subTest(manually_edited=manually_edited, copies=copies):
                document = self.document(copies=copies, copies_manual=manually_edited)
                with mock.patch.object(backend, "official_company_row", return_value=self.company), mock.patch.object(
                    backend, "supabase_official_company_row", return_value=self.company
                ):
                    sqlite_payload = backend.official_pdf_document_payload(mock.Mock(), document)
                    supabase_payload = backend.supabase_official_pdf_document_payload(document)
                for pdf_payload in (sqlite_payload, supabase_payload):
                    self.assertEqual(pdf_payload["copy_recipients"], expected)
                    self.assertEqual(pdf_payload["copy_recipients_manual"], manually_edited is True)
                    self.assertEqual(backend.official_pdf_info(pdf_payload, "歲悅正式函")["copy_recipients"], expected)
                self.assertEqual(sqlite_payload, supabase_payload)
                pdf = backend.build_official_pdf(sqlite_payload)
                rendered = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)
                self.assertIn("副本：", rendered)
                self.assertIn(expected, rendered)

    def test_mocked_supabase_create_respects_manual_and_automatic_copies(self) -> None:
        session = {
            "user": {
                "id": "USER-TEST", "name": "虛構申請人", "email": "synthetic@example.test",
                "company_id": self.company["id"], "unit": "虛構部門",
            },
            "permissions": ["official_documents.compose"],
        }
        for manually_edited, expected in (
            (True, "人工自訂副本單位"),
            (False, "虛構發文單位、人工自訂副本單位"),
        ):
            with self.subTest(manually_edited=manually_edited):
                payload = {
                    "id": f"OD-COPY-TEST-{manually_edited}",
                    "company_id": self.company["id"],
                    "source_type": "blank_editor",
                    "output_mode": "electronic",
                    "subject": "去識別化副本建立驗收",
                    "description": "虛構說明文字。",
                    "recipient": "虛構受文單位",
                    "document_category": self.category,
                    "submit": False,
                    "metadata": {
                        "copy_recipients": "人工自訂副本單位",
                        "copy_recipients_manual": manually_edited,
                    },
                }
                captured = []

                def capture_insert(table, row):
                    self.assertEqual(table, "official_documents")
                    stored = {**row, "dispatch_no": "測試字第1150000001號"}
                    captured.append(copy.deepcopy(stored))
                    return stored

                with ExitStack() as stack:
                    stack.enter_context(mock.patch.object(backend, "launch_company_in_scope", return_value=True))
                    stack.enter_context(mock.patch.object(
                        backend, "authoritative_applicant_department", return_value={"id": "UNIT-TEST", "name": "虛構部門"}
                    ))
                    stack.enter_context(mock.patch.object(backend, "supabase_official_company_row", return_value=self.company))
                    stack.enter_context(mock.patch.object(backend, "supabase_get", return_value=None))
                    stack.enter_context(mock.patch.object(backend, "supabase_insert", side_effect=capture_insert))
                    stack.enter_context(mock.patch.object(backend, "supabase_ensure_official_generated_pdf"))
                    stack.enter_context(mock.patch.object(backend, "supabase_insert_official_log"))
                    stack.enter_context(mock.patch.object(
                        backend, "supabase_official_document_detail", return_value={"id": payload["id"]}
                    ))
                    backend.supabase_create_official_document(payload, session)
                self.assertEqual(len(captured), 1)
                stored = captured[0]
                self.assertEqual(stored["metadata_json"]["extra"]["copy_recipients_manual"], manually_edited)
                self.assertEqual(stored["metadata_json"]["extra"]["copy_recipients"], expected)
                with mock.patch.object(backend, "supabase_official_company_row", return_value=self.company):
                    pdf_payload = backend.supabase_official_pdf_document_payload(stored)
                self.assertEqual(pdf_payload["copy_recipients"], expected)
                rendered = "\n".join(
                    page.extract_text() or "" for page in PdfReader(io.BytesIO(backend.build_official_pdf(pdf_payload))).pages
                )
                self.assertIn(expected, rendered)

    def test_correction_keeps_manual_override_and_can_switch_to_automatic(self) -> None:
        document = self.document(copies="人工自訂副本單位", copies_manual=True)
        context = backend.official_seal_approval_context({"document_category": self.category})
        corrected = backend._official_correction_metadata(
            document,
            context,
            "",
            {"metadata": {"copy_recipients": "第二版自訂副本單位", "copy_recipients_manual": True}},
        )
        self.assertEqual(corrected["extra"]["copy_recipients"], "第二版自訂副本單位")
        self.assertIs(corrected["extra"]["copy_recipients_manual"], True)
        self.assertIn("copy_recipients", backend._official_correction_render_metadata_changes(document, corrected))
        with mock.patch.object(backend, "supabase_official_company_row", return_value=self.company):
            manual_payload = backend.supabase_official_pdf_document_payload({**document, "metadata_json": corrected})
        self.assertEqual(manual_payload["copy_recipients"], "第二版自訂副本單位")
        self.assertEqual(document["metadata_json"]["extra"]["copy_recipients"], "人工自訂副本單位")

        automatic = backend._official_correction_metadata(
            {**document, "metadata_json": corrected},
            context,
            "",
            {"metadata": {"copy_recipients": "第二版自訂副本單位", "copy_recipients_manual": False}},
        )
        with mock.patch.object(backend, "supabase_official_company_row", return_value=self.company):
            auto_payload = backend.supabase_official_pdf_document_payload({**document, "metadata_json": automatic})
        self.assertIs(automatic["extra"]["copy_recipients_manual"], False)
        self.assertIn(
            "copy_recipients_manual",
            backend._official_correction_render_metadata_changes({**document, "metadata_json": corrected}, automatic),
        )
        self.assertEqual(auto_payload["copy_recipients"], "虛構發文單位、第二版自訂副本單位")


if __name__ == "__main__":
    unittest.main()
