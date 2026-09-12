"""Reference-manual PDF layout regression tests; synthetic data only."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import fitz
from reportlab.pdfbase import pdfmetrics

import backend


def synthetic_document(**changes):
    return {
        "company_name": "測試法人研究協會",
        "doc_type": "函",
        "doc_no": "測試字第1150901001號",
        "dispatch_date": "2026-09-01",
        "agency_name": "測試收文機關",
        "subject": "檢送去識別化排版測試計畫1份，請查照。",
        "body": "說明：\n一、本函僅供排版測試，不具正式發文效力。",
        "contact_address": "測試市測試區測試路1號",
        "contact_owner": "測試承辦人",
        "contact_phone": "(00)0000-0000",
        "contact_fax": "N/A",
        "contact_email": "test@example.invalid",
        "attachments_summary": "去識別化測試計畫1份",
        **changes,
    }


class OfficialPdfManualLayoutTest(unittest.TestCase):
    def setUp(self):
        self.font = backend.official_pdf_font_profile()["name"]

    def layout(self, **changes):
        info = backend.official_pdf_info(synthetic_document(**changes), "測試函")
        return backend.paginate_official_pdf(info)

    def test_body_reserves_exactly_25_mm_margins_and_keeps_reference_sizes(self):
        body = "說明：\n" + "\n".join(f"一、此為第{index}項測試內容。" for index in range(90))
        layout = self.layout(body=body)
        self.assertGreater(len(layout["pages"]), 2)
        margin = 25 / 25.4 * 72
        self.assertAlmostEqual(backend.OFFICIAL_PDF_CONTENT_LEFT, margin)
        self.assertAlmostEqual(backend.A4_WIDTH_PT - backend.OFFICIAL_PDF_CONTENT_RIGHT, margin)
        self.assertAlmostEqual(backend.A4_HEIGHT_PT - layout["bottom_top"], margin)
        for page in layout["pages"]:
            for item in page["items"]:
                self.assertGreaterEqual(item["top"], margin)
                self.assertLessEqual(item["top"] + item["font_size"], page["bottom_top"] + 0.01)
                expected_size = 16 if item["kind"] in {"subject", "body"} else 12
                self.assertEqual(item["font_size"], expected_size)
        self.assertEqual(sum(item["kind"] == "original" for page in layout["pages"] for item in page["items"]), 1)
        self.assertEqual(sum(item["kind"] == "copy" for page in layout["pages"] for item in page["items"]), 1)

    def test_long_heading_wraps_at_20_points_and_shifts_contact_block_down(self):
        company = "測試法人全國公共服務與教育訓練品質研究發展推廣協會"
        layout = self.layout(company_name=company)
        header = layout["header"]
        self.assertGreater(len(header["title_lines"]), 1)
        self.assertEqual("".join(header["title_lines"]), f"{company}　函")
        self.assertAlmostEqual(header["contact_top"], header["title_top"] + len(header["title_lines"]) * 28 + 1.52)
        width = backend.OFFICIAL_PDF_CONTENT_RIGHT - backend.OFFICIAL_PDF_CONTENT_LEFT
        for line in header["title_lines"]:
            self.assertLessEqual(pdfmetrics.stringWidth(line, self.font, 20), width)
        package = backend.build_official_pdf_package(synthetic_document(company_name=company))
        with fitz.open(stream=package["data"], filetype="pdf") as doc:
            spans = [span for block in doc[0].get_text("dict")["blocks"] if "lines" in block for line in block["lines"] for span in line["spans"]]
        title_spans = [span for span in spans if span["size"] == 20]
        self.assertEqual(len(title_spans), len(header["title_lines"]))
        for span in title_spans:
            self.assertGreaterEqual(span["bbox"][0], backend.OFFICIAL_PDF_CONTENT_LEFT - 0.1)
            self.assertLessEqual(span["bbox"][2], backend.OFFICIAL_PDF_CONTENT_RIGHT + 0.1)
            self.assertAlmostEqual((span["bbox"][0] + span["bbox"][2]) / 2, backend.A4_WIDTH_PT / 2, delta=0.1)

    def test_contact_and_punctuation_do_not_overflow_the_right_body_margin(self):
        layout = self.layout(contact_address="測試地址" * 20, contact_email="very-long-synthetic-contact@example.invalid")
        for line in layout["header"]["contact_lines"]:
            self.assertLessEqual(layout["header"]["contact_x"] + pdfmetrics.stringWidth(line, self.font, 12), backend.OFFICIAL_PDF_CONTENT_RIGHT + 0.01)
        for source in ("甲乙丙丁。戊己", "甲乙丙。」戊己", "甲乙丙「丁戊」己"):
            lines = backend.official_pdf_wrap_text(source, 64, 64, self.font, 16)
            self.assertEqual("".join(lines), source)
            self.assertTrue(all(pdfmetrics.stringWidth(line, self.font, 16) <= 64 for line in lines))
            self.assertTrue(all(not line.startswith(("。", "」")) for line in lines))
            self.assertTrue(all(not line.endswith("「") for line in lines))
        # Degenerate punctuation-only input must still make progress.
        source = "，，。。」」" * 3
        lines = backend.official_pdf_wrap_text(source, 64, 64, self.font, 16)
        self.assertEqual("".join(lines), source)
        self.assertTrue(all(lines))

    def test_four_list_levels_hang_wrapped_text_after_the_marker(self):
        for level, marker in enumerate(("一、", "(一)", "１、", "(１)"), 1):
            source = marker + "本項為去識別化測試內容，須保留完整文字並確保換行對齊。" * 3
            lines = backend.official_pdf_body_paragraph_lines(source, self.font, 16, backend.OFFICIAL_PDF_BODY_INDENT)
            self.assertGreater(len(lines), 1)
            self.assertEqual("".join(line["text"] for line in lines), source)
            first_x = backend.OFFICIAL_PDF_BODY_INDENT + (level - 1) * 16
            self.assertEqual(lines[0]["text_x"], first_x)
            for line in lines[1:]:
                self.assertEqual(line["text_x"], first_x + pdfmetrics.stringWidth(marker, self.font, 16))
                self.assertLessEqual(line["text_x"] + pdfmetrics.stringWidth(line["text"], self.font, 16), backend.OFFICIAL_PDF_CONTENT_RIGHT)

    def test_section_labels_are_parsed_without_rewriting_body_or_overlapping_long_label(self):
        sections = backend.official_pdf_body_sections("說明：\n一、測試依據。\n辦法：\n一、測試執行。\n擬辦：\n一、測試建議。\n核復事項：\n一、測試回覆。")
        self.assertEqual([item["label"] for item in sections], ["說明", "辦法", "擬辦", "核復事項"])
        layout = self.layout(body="核復事項：\n一、測試回覆。")
        item = next(item for item in layout["pages"][0]["items"] if item["kind"] == "body")
        self.assertEqual(item["text_x"], backend.OFFICIAL_PDF_CONTENT_LEFT + 80)
        self.assertEqual(item["text"], "一、測試回覆。")

    def test_two_line_list_item_does_not_split_across_pages(self):
        paragraph = "(１)以去識別化內容測試多頁輸出，確認末頁正本與副本資料完整，並保留上下邊界。"
        body = "說明：\n" + "\n".join(["一、單行測試。"] * 14 + [paragraph])
        layout = self.layout(body=body)
        self.assertEqual(len(layout["pages"]), 2)
        self.assertFalse(any(item["text"].startswith("(１)") for item in layout["pages"][0]["items"]))
        second_body = [item for item in layout["pages"][1]["items"] if item["kind"] == "body"]
        self.assertEqual(len(second_body), 2)
        self.assertEqual("".join(item["text"] for item in second_body), paragraph)

    def test_renderer_upgrade_never_rewrites_submitted_or_completed_pdf(self):
        existing = {"id": "SYNTHETIC-OLD", "file_type": "generated_pdf", "version": 1}
        for status in ("pending_applicant_manager", "stamping", "stamped", "dispatched", "closed", "cancelled"):
            with self.subTest(status=status), patch.object(backend, "supabase_official_raw_document_files", return_value=[existing]), patch.object(backend, "build_official_pdf_package") as build, patch.object(backend, "supabase_store_official_pdf_file") as store:
                result = backend.supabase_ensure_official_generated_pdf({"id": "SYNTHETIC-DOC", "current_status": status})
                self.assertEqual(result, existing)
                build.assert_not_called()
                store.assert_not_called()


if __name__ == "__main__":
    unittest.main()
