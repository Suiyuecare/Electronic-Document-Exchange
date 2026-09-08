from __future__ import annotations

import copy
import io
import json
import unittest
from contextlib import ExitStack
from unittest import mock

from pypdf import PdfReader

import backend


class AttachmentDescriptionBackendTest(unittest.TestCase):
    company = {"id": "CO-TEST", "name": "去識別化測試公司", "address": "測試地址"}
    category = "主管機關 申請或回覆文件（與 費用、法令無關）"
    filename = "original-upload-name-duplicate.pdf"
    description = "身分證明文件一份；僅供申請使用。"

    def document(self, description: str) -> dict:
        return {
            "id": "OD-ATTACHMENT-TEST",
            "company_id": "CO-TEST",
            "subject": "附件文字與檔案分離測試",
            "description": "本資料僅供隔離測試，不含真實個資。",
            "recipient": "去識別化測試機關",
            "created_at": "2026-09-08 12:00:00",
            "metadata_json": {
                "attachments": self.filename,
                "extra": {"attachment_details": description},
                "audit": {"original_hash": "a" * 64},
            },
        }

    def test_explicit_description_wins_over_filename_including_empty_text(self) -> None:
        for value in (self.description, "", "第一份；補充說明\n第二份，備查"):
            for fields in (
                {"attachmentDetails": value},
                {"attachment_details": value},
                {"attachments_summary": value},
                {"metadata": {"attachment_details": value}},
                {"metadata_json": {"attachment_details": value}},
                {"metadata_json": {"extra": {"attachment_details": value}}},
            ):
                with self.subTest(value=value, fields=fields):
                    payload = {"attachments": [{"file_name": self.filename}], **fields}
                    self.assertEqual(backend.official_attachment_description(payload), value)
                    info = backend.official_pdf_info(payload, "歲悅正式函")
                    self.assertEqual(info["attachments"], value or "無")

    def test_legacy_only_records_keep_their_attachment_list_and_explicit_empty_is_not_replaced(self) -> None:
        legacy = {
            "attachments": [
                {"file_name": "函稿本文.pdf"},
                {"file_name": "附件清冊.xml"},
                {"file_name": self.filename},
            ]
        }
        self.assertEqual(backend.official_attachment_description(legacy), self.filename)
        self.assertEqual(
            backend.official_attachment_description({
                "attachments": "",
                "metadata_json": {"attachments": self.filename},
            }),
            "",
        )

    def test_sqlite_and_supabase_pdf_payloads_use_the_same_editable_text(self) -> None:
        for description in (self.description, ""):
            document = self.document(description)
            before = copy.deepcopy(document)
            with mock.patch.object(backend, "official_company_row", return_value=self.company), mock.patch.object(
                backend, "supabase_official_company_row", return_value=self.company
            ):
                sqlite_payload = backend.official_pdf_document_payload(mock.Mock(), document)
                supabase_payload = backend.supabase_official_pdf_document_payload(document)
            self.assertEqual(sqlite_payload, supabase_payload)
            self.assertEqual(sqlite_payload["attachments"], description)
            self.assertEqual(sqlite_payload["attachment_details"], description)
            self.assertEqual(document, before)

    def test_create_contracts_store_manual_and_empty_text_without_file_metadata_changes(self) -> None:
        session = {
            "user": {
                "id": "USER-TEST", "name": "測試申請人", "email": "applicant@example.test",
                "company_id": "CO-TEST", "unit": "測試部門",
            },
            "permissions": ["official_documents.compose"],
        }
        for supabase in (False, True):
            for description in (self.description, ""):
                with self.subTest(supabase=supabase, description=description):
                    payload = {
                        "id": "OD-ATTACHMENT-TEST", "company_id": "CO-TEST", "source_type": "blank_editor",
                        "subject": "附件文字測試", "document_category": self.category, "submit": False,
                        "attachments_summary": self.filename,
                        "attachments": [{"file_name": self.filename, "file_hash": "a" * 64}],
                        "metadata": {"attachment_details": description},
                    }
                    before = copy.deepcopy(payload)
                    captured = []

                    def capture_insert(*args):
                        table, row = args if supabase else args[1:]
                        captured.append((table, copy.deepcopy(row)))
                        return row

                    with ExitStack() as stack:
                        stack.enter_context(mock.patch.object(backend, "launch_company_in_scope", return_value=True))
                        stack.enter_context(mock.patch.object(
                            backend, "authoritative_applicant_department", return_value={"id": "UNIT-TEST", "name": "測試部門"}
                        ))
                        prefix = "supabase_" if supabase else ""
                        stack.enter_context(mock.patch.object(backend, f"{prefix}official_company_row", return_value=self.company))
                        stack.enter_context(mock.patch.object(backend, "supabase_insert" if supabase else "insert_row", side_effect=capture_insert))
                        stack.enter_context(mock.patch.object(backend, f"{prefix}ensure_official_generated_pdf"))
                        stack.enter_context(mock.patch.object(backend, f"{prefix}insert_official_log"))
                        stack.enter_context(mock.patch.object(backend, f"{prefix}official_document_detail", return_value={"id": payload["id"]}))
                        if supabase:
                            backend.supabase_create_official_document(payload, session)
                        else:
                            backend.create_official_document(mock.Mock(), payload, session)
                    document = next(row for table, row in captured if table == "official_documents")
                    metadata = document["metadata_json"]
                    self.assertEqual(metadata["attachments"], description)
                    self.assertEqual(metadata["extra"]["attachment_details"], description)
                    self.assertEqual(payload, before)

    def test_corrections_preserve_manual_edits_and_explicit_clear_after_roundtrip(self) -> None:
        context = backend.official_seal_approval_context({"document_category": self.category})
        for description in (self.description, ""):
            for changes in (
                {"metadata": {"attachment_details": description}},
                {"attachments_summary": description},
                {"attachmentDetails": description},
            ):
                with self.subTest(description=description, changes=changes):
                    document = self.document("舊的附件文字")
                    before = copy.deepcopy(document)
                    metadata = backend._official_correction_metadata(document, context, "", changes)
                    restored = {**document, "metadata_json": json.loads(json.dumps(metadata, ensure_ascii=False))}
                    self.assertEqual(metadata["attachments"], description)
                    self.assertEqual(metadata["extra"]["attachment_details"], description)
                    self.assertEqual(backend.official_attachment_description(restored), description)
                    self.assertEqual(metadata["audit"], before["metadata_json"]["audit"])
                    self.assertEqual(document, before)
                    self.assertIn("attachment_details", backend._official_correction_render_metadata_changes(document, metadata))

    def test_missing_description_during_unrelated_correction_does_not_erase_it(self) -> None:
        context = backend.official_seal_approval_context({"document_category": self.category})
        document = self.document(self.description)
        metadata = backend._official_correction_metadata(document, context, "", {"metadata": {"contact_fax": "N/A"}})
        self.assertEqual(backend.official_attachment_description({"metadata_json": metadata}), self.description)
        self.assertNotIn("attachment_details", backend._official_correction_render_metadata_changes(document, metadata))

    def test_generated_pdf_contains_only_description_not_original_filename(self) -> None:
        for description in (self.description, ""):
            with self.subTest(description=description):
                document = self.document(description)
                with mock.patch.object(backend, "official_company_row", return_value=self.company):
                    payload = backend.official_pdf_document_payload(mock.Mock(), document)
                data = backend.build_official_pdf(payload)
                text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
                self.assertIn(f"附件：{description or '無'}", text)
                self.assertNotIn(self.filename, text)
                if description:
                    self.assertEqual(text.count(description), 1)

    def test_description_length_limit_rejects_instead_of_silently_truncating(self) -> None:
        maximum = "字" * 5000
        self.assertEqual(backend.validated_official_attachment_description(maximum), maximum)
        for fields in (
            {"metadata": {"attachment_details": maximum + "字"}},
            {"metadata": {"attachmentDetails": maximum + "字"}},
            {"attachments_summary": maximum + "字"},
            {"attachmentDetails": maximum + "字"},
        ):
            with self.subTest(fields=list(fields)):
                with self.assertRaisesRegex(ValueError, "attachment_description_too_long"):
                    backend._official_correction_client_metadata(fields)

    def test_both_create_paths_reject_oversized_description_before_inserting(self) -> None:
        session = {
            "user": {"id": "USER-TEST", "company_id": "CO-TEST"},
            "permissions": ["official_documents.compose"],
        }
        for supabase in (False, True):
            with self.subTest(supabase=supabase), ExitStack() as stack:
                prefix = "supabase_" if supabase else ""
                stack.enter_context(mock.patch.object(backend, "launch_company_in_scope", return_value=True))
                stack.enter_context(mock.patch.object(backend, f"{prefix}official_company_row", return_value=self.company))
                stack.enter_context(mock.patch.object(
                    backend, "authoritative_applicant_department", return_value={"id": "UNIT-TEST", "name": "測試部門"}
                ))
                insert = stack.enter_context(mock.patch.object(backend, "supabase_insert" if supabase else "insert_row"))
                payload = {
                    "company_id": "CO-TEST", "source_type": "blank_editor", "submit": False,
                    "metadata": {"attachment_details": "字" * 5001},
                }
                with self.assertRaisesRegex(ValueError, "attachment_description_too_long"):
                    if supabase:
                        backend.supabase_create_official_document(payload, session)
                    else:
                        backend.create_official_document(mock.Mock(), payload, session)
                insert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
