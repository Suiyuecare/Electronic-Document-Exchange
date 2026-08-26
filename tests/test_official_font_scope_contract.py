from __future__ import annotations

import hashlib
import inspect
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader
from reportlab.pdfgen import canvas as reportlab_canvas

import backend


ROOT = Path(__file__).resolve().parents[1]
EDUKAI_PATH = ROOT / "assets" / "fonts" / "edukai-5.1_20251208.ttf"
EDUKAI_SHA256 = "e2b6b1bd1d6303672a68d5057a1f1e4b5361e3d8842373ff3bd1c71fb9ea9b98"


class OfficialFontScopeContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_official_profile = backend._OFFICIAL_PDF_FONT_PROFILE
        self.original_editor_profile = backend._EDITOR_PDF_FONT_PROFILE
        backend._OFFICIAL_PDF_FONT_PROFILE = None
        backend._EDITOR_PDF_FONT_PROFILE = None

    def tearDown(self) -> None:
        backend._OFFICIAL_PDF_FONT_PROFILE = self.original_official_profile
        backend._EDITOR_PDF_FONT_PROFILE = self.original_editor_profile

    def test_supplied_edukai_asset_is_preserved_unchanged_with_attribution(self) -> None:
        self.assertTrue(EDUKAI_PATH.is_file())
        self.assertEqual(hashlib.sha256(EDUKAI_PATH.read_bytes()).hexdigest(), EDUKAI_SHA256)
        notice = (ROOT / "assets" / "fonts" / "EDUKAI-NOTICE.txt").read_text(encoding="utf-8")
        self.assertIn("中華民國教育部", notice)
        self.assertIn("不轉檔", notice)
        self.assertIn("依實際", notice)
        self.assertIn("使用字圖內嵌字型子集", notice)
        self.assertIn("https://creativecommons.org/licenses/by-nd/3.0/tw/legalcode.zh-hant", notice)
        self.assertIn(EDUKAI_SHA256, notice)

    def test_frontend_uses_edukai_only_for_formal_document_previews_and_print(self) -> None:
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        javascript = (ROOT / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('font-family: "EDoc MOE EduKai";', css)
        self.assertIn('/assets/fonts/edukai-5.1_20251208.ttf?v=5.1-20251208', css)
        self.assertIn('font-family: "EDoc MOE EduKai", "標楷體"', css)
        self.assertIn('const officialDraftFontQuery = \'16px "EDoc MOE EduKai"\';', javascript)
        self.assertIn('faces.length > 0 && faces.every((face) => face.status === "loaded")', javascript)
        self.assertIn("教育部標準楷書載入失敗，已停止列印", javascript)
        self.assertIn('if (!composeView?.classList.contains("active")) return;', javascript)
        self.assertIn('if (activeMajorRoute === "compose") scheduleOfficialDraftFontRerender();', javascript)
        self.assertIn('composeView.dataset.officialFontState = "loading";', javascript)
        self.assertIn("font-display: block", css)
        self.assertIn("official_pdf_font_missing_glyphs", javascript)
        self.assertIn("內容含教育部標準楷書不支援的罕見字元", javascript)
        self.assertIn("styles.css?v=20260826-finance-sso-edukai-r1", html)
        self.assertIn("app.js?v=20260826-finance-sso-edukai-r1", html)

        editor_rule = css[css.index("#uploadedSealTextInput") : css.index(".draft-preview-heading-actions")]
        self.assertIn("EDoc LXGW WenKai TC", editor_rule)
        self.assertNotIn("EDoc MOE EduKai", editor_rule)
        self.assertNotIn('body {\n  font-family: "EDoc MOE EduKai"', css)

    def test_vercel_packages_font_for_static_preview_and_python_pdf_renderer(self) -> None:
        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        python_build = next(item for item in config["builds"] if item.get("src") == "api/index.py")
        self.assertIn("assets/fonts/edukai-5.1_20251208.ttf", python_build["config"]["includeFiles"])

        static_sources = {item.get("src") for item in config["builds"] if item.get("use") == "@vercel/static"}
        self.assertIn("assets/fonts/edukai-5.1_20251208.ttf", static_sources)
        self.assertIn("assets/fonts/EDUKAI-NOTICE.txt", static_sources)

        font_header = next(
            item for item in config["headers"] if item.get("source") == "/assets/fonts/edukai-5.1_20251208.ttf"
        )
        self.assertIn("immutable", json.dumps(font_header))
        self.assertTrue(any("edukai-5.1_20251208" in item.get("src", "") for item in config["routes"]))

    def test_formal_pdf_embeds_edukai_but_uploaded_pdf_editor_keeps_lxgw(self) -> None:
        formal_profile = backend.official_pdf_font_profile()
        editor_profile = backend.editor_pdf_font_profile()

        self.assertEqual(formal_profile["family"], "教育部標準楷書")
        self.assertEqual(formal_profile["source"], "repo-bundled-edukai-5.1-20251208")
        self.assertEqual(formal_profile["sha256"], EDUKAI_SHA256)
        self.assertTrue(formal_profile["embedded"])
        self.assertEqual(editor_profile["family"], "LXGW WenKai TC")
        self.assertEqual(backend._editor_kai_font_name(), editor_profile["name"])
        self.assertNotEqual(formal_profile["name"], editor_profile["name"])

        for renderer in (backend.write_asset_stamp_overlay_pdf, backend.write_kai_text_overlay_pdf):
            source = inspect.getsource(renderer)
            self.assertIn("editor_pdf_font_profile", source)
            self.assertNotIn("official_pdf_font_profile", source)

        package = backend.build_official_pdf_package(
            {
                "company_name": "歲悅股份有限公司",
                "doc_type": "函",
                "doc_no": "測試字第1150826001號",
                "agency_name": "測試受文機關",
                "subject": "教育部標準楷書嵌入驗證",
                "body": "本測試資料已去識別化，請查照。",
            }
        )
        self.assertEqual(package["layout"]["font"], "教育部標準楷書")
        self.assertEqual(package["layout"]["renderer_version"], backend.OFFICIAL_PDF_RENDERER_VERSION)

        reader = PdfReader(io.BytesIO(package["data"]))
        extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("教育部標準楷書嵌入驗證", extracted)
        self.assertTrue(backend.official_pdf_uses_current_renderer(package["data"]))
        self.assertEqual(
            reader.metadata.creator,
            f"Module_edoc {backend.OFFICIAL_PDF_RENDERER_VERSION}",
        )
        keywords = str(reader.metadata.get("/Keywords") or "")
        self.assertIn("字型來源=中華民國教育部", keywords)
        self.assertIn(
            "font_license=https://creativecommons.org/licenses/by-nd/3.0/tw/legalcode.zh-hant",
            keywords,
        )
        self.assertIn(f"font_sha256={EDUKAI_SHA256}", keywords)
        self.assertIn(f"renderer_version={backend.OFFICIAL_PDF_RENDERER_VERSION}", keywords)

        base_fonts: set[str] = set()
        has_embedded_truetype = False
        for page in reader.pages:
            resources = page["/Resources"].get_object()
            fonts = resources.get("/Font")
            if not fonts:
                continue
            for font_reference in fonts.get_object().values():
                font = font_reference.get_object()
                base_fonts.add(str(font.get("/BaseFont") or ""))
                descriptor_reference = font.get("/FontDescriptor")
                if descriptor_reference and "/FontFile2" in descriptor_reference.get_object():
                    has_embedded_truetype = True
        self.assertTrue(any("TW-MOE-Std-Kai" in name for name in base_fonts), base_fonts)
        self.assertTrue(has_embedded_truetype)
        self.assertFalse(any("LXGW" in name for name in base_fonts), base_fonts)

    def test_formal_renderer_fails_closed_when_pinned_font_hash_does_not_match(self) -> None:
        backend._OFFICIAL_PDF_FONT_PROFILE = None
        with patch.object(backend, "OFFICIAL_PDF_FONT_SHA256", "0" * 64):
            with self.assertRaisesRegex(RuntimeError, "official_pdf_font_hash_mismatch"):
                backend.official_pdf_font_profile()

    def test_formal_renderer_rejects_characters_missing_from_edukai(self) -> None:
        with self.assertRaisesRegex(ValueError, "official_pdf_font_missing_glyphs"):
            backend.build_official_pdf_package(
                {
                    "company_name": "歲悅股份有限公司",
                    "agency_name": "測試機關",
                    "subject": "罕見字𠮷字型驗證",
                    "body": "去識別化測試資料。",
                }
            )

    def test_supabase_editable_legacy_pdf_gets_a_new_renderer_revision(self) -> None:
        legacy_stream = io.BytesIO()
        legacy_canvas = reportlab_canvas.Canvas(legacy_stream)
        legacy_canvas.setCreator("Module_edoc legacy-renderer")
        legacy_canvas.drawString(72, 720, "legacy Supabase draft")
        legacy_canvas.save()
        legacy = legacy_stream.getvalue()
        legacy_hash = backend.sha256_bytes(legacy)
        old_file = {
            "id": "ODFILE-OLD",
            "document_id": "OD-FONT-UPGRADE",
            "file_object_id": "FILE-OLD",
            "file_type": "generated_pdf",
            "file_hash": legacy_hash,
            "file_size": len(legacy),
            "version": 1,
        }
        old_object = {
            "id": "FILE-OLD",
            "document_id": "OD-FONT-UPGRADE",
            "storage_key": "official-documents/OD-FONT-UPGRADE/legacy.pdf",
            "bucket": backend.EDOC_STORAGE_BUCKET,
            "sha256": legacy_hash,
            "size_bytes": len(legacy),
        }
        replacement = {**old_file, "id": "ODFILE-NEW", "file_hash": "NEW-SHA256", "version": 2}
        package = backend.build_official_pdf_package(
            {
                "company_name": "歲悅股份有限公司",
                "agency_name": "測試機關",
                "subject": "Supabase 草稿字型升版",
                "body": "去識別化測試資料。",
            }
        )
        with (
            patch.object(backend, "supabase_official_raw_document_files", return_value=[old_file]),
            patch.object(backend, "supabase_get", return_value=old_object),
            patch.object(backend, "supabase_storage_download", return_value=legacy),
            patch.object(backend, "supabase_official_pdf_document_payload", return_value={}),
            patch.object(backend, "build_official_pdf_package", return_value=package),
            patch.object(backend, "supabase_store_official_pdf_file", return_value=replacement) as store_mock,
            patch.object(backend, "supabase_insert_official_log") as log_mock,
        ):
            result = backend.supabase_ensure_official_generated_pdf(
                {"id": "OD-FONT-UPGRADE", "current_status": "draft"},
                "unit-test",
            )

        self.assertEqual(result["id"], "ODFILE-NEW")
        store_mock.assert_called_once()
        self.assertEqual(log_mock.call_args.args[1], "regenerate_pdf_font_revision")

    def test_supabase_locked_legacy_pdf_is_not_rewritten(self) -> None:
        locked_file = {
            "id": "ODFILE-LOCKED",
            "document_id": "OD-FONT-LOCKED",
            "file_object_id": "FILE-LOCKED",
            "file_type": "generated_pdf",
            "file_hash": "LOCKED-SHA256",
            "file_size": 100,
            "version": 1,
        }
        with (
            patch.object(backend, "supabase_official_raw_document_files", return_value=[locked_file]),
            patch.object(backend, "supabase_get") as get_mock,
            patch.object(backend, "supabase_store_official_pdf_file") as store_mock,
        ):
            result = backend.supabase_ensure_official_generated_pdf(
                {"id": "OD-FONT-LOCKED", "current_status": "pending_applicant_manager"},
                "unit-test",
            )

        self.assertEqual(result["id"], "ODFILE-LOCKED")
        get_mock.assert_not_called()
        store_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
