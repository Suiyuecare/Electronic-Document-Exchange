from __future__ import annotations

import copy
import re
import unittest
from pathlib import Path

import backend


ROOT = Path(__file__).resolve().parents[1]


def html_element(source: str, element_id: str) -> str:
    """Return one balanced HTML element identified by id."""
    id_index = source.index(f'id="{element_id}"')
    start = source.rfind("<", 0, id_index)
    opening = re.match(r"<([a-zA-Z][\w-]*)\b[^>]*>", source[start:])
    if opening is None:
        raise AssertionError(f"opening tag not found for #{element_id}")
    tag = opening.group(1)
    token_pattern = re.compile(rf"</?{re.escape(tag)}\b[^>]*>", re.IGNORECASE)
    depth = 0
    for token in token_pattern.finditer(source, start):
        raw = token.group(0)
        if raw.startswith("</"):
            depth -= 1
            if depth == 0:
                return source[start:token.end()]
        elif not raw.endswith("/>"):
            depth += 1
    raise AssertionError(f"closing tag not found for #{element_id}")


def javascript_function(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?:async\s+)?function\s+{re.escape(name)}\([^)]*\)\s*\{{", source))
    if not matches:
        raise AssertionError(f"JavaScript function not found: {name}")
    # JavaScript uses the final declaration at runtime. Selecting it here keeps
    # the behavioral assertions useful while a separate test rejects duplicates.
    match = matches[-1]
    depth = 0
    quote = ""
    escaped = False
    index = match.end() - 1
    for position in range(index, len(source)):
        char = source[position]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {'"', "'", "`"}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[match.start():position + 1]
    raise AssertionError(f"JavaScript function is not balanced: {name}")


def control_ids(fragment: str) -> list[str]:
    return [
        attributes.group(1)
        for attributes in re.finditer(
            r"<(?:input|select|textarea)\b[^>]*\bid=\"([^\"]+)\"[^>]*>",
            fragment,
            re.IGNORECASE,
        )
        if not re.search(
            r'(?:\btype="hidden"|\bhidden(?:\s|>|=)|\baria-hidden="true")',
            attributes.group(0),
            re.IGNORECASE,
        )
    ]


class ElectronicSealPageContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "styles.css").read_text(encoding="utf-8")
        cls.page = html_element(cls.html, "electronicSeal")

    def test_page_is_two_vertical_sections_with_application_first(self) -> None:
        application = html_element(self.page, "uploadedSealApplicationPanel")
        editor = html_element(self.page, "uploadedPdfEditor")

        self.assertRegex(application, r'^<section\b[^>]*class="[^"]*electronic-seal-application-panel')
        self.assertLess(self.page.index(application), self.page.index(editor))
        self.assertNotIn("<aside", application)

        normalized_css = re.sub(r"\s+", " ", self.css)
        self.assertRegex(
            normalized_css,
            r"\.electronic-seal-layout\.electronic-seal-layout-stacked\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)",
        )

    def test_application_section_has_exactly_the_six_requested_fields(self) -> None:
        application = html_element(self.page, "uploadedSealApplicationPanel")
        form = html_element(application, "uploadedSealForm")
        expected = [
            "uploadedSealApplicant",
            "uploadedSealApprovalCategorySelect",
            "uploadedSealDepartment",
            "uploadedSealCompany",
            "uploadedSealTitle",
            "uploadedSealReason",
        ]
        self.assertEqual(control_ids(form), expected)

        labels = {
            "uploadedSealApplicant": "申請人",
            "uploadedSealApprovalCategorySelect": "用印文件類型",
            "uploadedSealDepartment": "部門",
            "uploadedSealCompany": "公司",
            "uploadedSealTitle": "申請主旨",
            "uploadedSealReason": "用印原因",
        }
        for field_id, label in labels.items():
            self.assertRegex(
                form,
                rf"<label\b[^>]*>\s*{re.escape(label)}\s*<(?:input|select|textarea)\b[^>]*id=\"{field_id}\"",
            )

        for removed_field in (
            "uploadedSealEmail",
            "uploadedSealPhone",
            "uploadedSealType",
            "uploadedSealCounterparty",
            "uploadedSealPdfInput",
        ):
            match = re.search(
                rf'<(?:input|select|textarea)\b(?=[^>]*id="{removed_field}")(?P<attrs>[^>]*)>',
                form,
            )
            if match is not None:
                self.assertRegex(
                    match.group(0),
                    r'(?:\btype="hidden"|\bhidden(?:\s|>|=)|\baria-hidden="true")',
                    f"#{removed_field} 只能作為隱藏技術欄位，不可出現在申請資訊畫面。",
                )

    def test_pdf_source_control_lives_in_editor_and_opens_native_picker(self) -> None:
        application = html_element(self.page, "uploadedSealApplicationPanel")
        editor = html_element(self.page, "uploadedPdfEditor")
        self.assertNotIn('id="uploadedSealPdfInput"', application)
        self.assertEqual(self.page.count('id="uploadedSealPdfInput"'), 1)
        self.assertIn('id="uploadedSealPdfInput"', editor)
        self.assertRegex(
            editor,
            r'<input\b(?=[^>]*id="uploadedSealPdfInput")(?=[^>]*type="file")(?=[^>]*accept="[^"]*application/pdf[^"]*\.pdf)[^>]*>',
        )
        for button_id in ("uploadedPdfEmptyUploadBtn", "uploadedPdfReplaceBtn"):
            upload_button = re.search(
                rf'<button\b(?=[^>]*id="{button_id}")(?=[^>]*aria-controls="uploadedSealPdfInput")[^>]*>[^<]*PDF[^<]*</button>',
                editor,
            )
            self.assertIsNotNone(upload_button)

        self.assertEqual(
            len(re.findall(r"async\s+function\s+handleUploadedSealPdfChange\s*\(", self.js)),
            1,
            "上傳 handler 不可重複宣告，否則前面的驗證路徑會被靜默覆寫。",
        )
        self.assertRegex(
            self.js,
            r'document\.querySelector\("#uploadedSealPdfInput"\)\?\.addEventListener\("change",\s*handleUploadedSealPdfChange\)',
        )
        picker = javascript_function(self.js, "openUploadedPdfPicker")
        self.assertNotIn('document.querySelector("#uploadedSealForm")', picker)
        self.assertNotIn("reportValidity()", picker)
        self.assertIn('document.querySelector("#uploadedSealPdfInput")', picker)
        self.assertRegex(picker, r"input\.value\s*=\s*\"\"")
        self.assertIn("input.click()", picker)
        for button_id in ("uploadedPdfEmptyUploadBtn", "uploadedPdfReplaceBtn"):
            self.assertRegex(
                self.js,
                rf'document\.querySelector\("#{button_id}"\)\?\.addEventListener\("click",\s*openUploadedPdfPicker\)',
            )

    def test_empty_state_stays_clickable_and_hides_the_editor_layer_without_a_page(self) -> None:
        empty_rule = re.search(r"\.uploaded-pdf-empty\s*\{(?P<body>[^}]*)}", self.css)
        layer_rule = re.search(r"\.pdf-editor-v2\s+\.uploaded-stamp-layer\s*\{(?P<body>[^}]*)}", self.css)
        self.assertIsNotNone(empty_rule)
        self.assertIsNotNone(layer_rule)
        empty_z = re.search(r"z-index:\s*(\d+)", empty_rule.group("body"))
        layer_z = re.search(r"z-index:\s*(\d+)", layer_rule.group("body"))
        self.assertIsNotNone(empty_z)
        self.assertIsNotNone(layer_z)
        self.assertGreater(
            int(empty_z.group(1)),
            int(layer_z.group(1)),
            "空白狀態必須高於 SVG 編輯層，否則編輯層會攔截上傳按鈕。",
        )

        render = javascript_function(self.js, "renderUploadedPdfPage")
        no_page = render.index("if (!page || !runtime)")
        page_ready = render.index("canvas.hidden = false", no_page)
        no_page_branch = render[no_page:page_ready]
        self.assertRegex(
            no_page_branch,
            r'(?:(?:stampLayer|layer)\?\.toggleAttribute\("hidden",\s*true\)|(?:stampLayer|layer)\.hidden\s*=\s*true)',
        )
        ready_branch = render[page_ready:]
        self.assertRegex(
            ready_branch,
            r'(?:(?:stampLayer|layer)\?\.toggleAttribute\("hidden",\s*false\)|(?:stampLayer|layer)\.hidden\s*=\s*false)',
        )

    def test_a4_upload_becomes_an_editable_pdfjs_canvas(self) -> None:
        handler = javascript_function(self.js, "handleUploadedSealPdfChange")
        for operation in (
            "requestEditorUpload(file, \"source_pdf\")",
            "performTusUpload(file, intent",
            "finalizeEditorUpload(intent, file)",
            "loadUploadedPdfIntoEditor(file, intent, finalized, { append: false })",
            "ensureUploadedEditorPagesA4(uploadedSealEditorState.pages)",
        ):
            self.assertIn(operation, handler)

        loader = javascript_function(self.js, "loadUploadedPdfIntoEditor")
        for editable_state in (
            "pages: incomingPages",
            "elements: []",
            "uploadedSealEditorRuntime.currentPageId",
            "markUploadedEditorDirty()",
            "renderUploadedSealWorkbench()",
        ):
            self.assertIn(editable_state, loader)

        editor = html_element(self.page, "uploadedPdfEditor")
        self.assertIn('id="uploadedPdfCanvas"', editor)
        self.assertIn('id="uploadedEditorSvgLayer"', editor)
        self.assertIn('role="application"', editor)
        for tool in ("select", "seal", "text"):
            self.assertIn(f'data-editor-tool="{tool}"', editor)

    def test_review_versions_are_consolidated_into_one_compact_picker(self) -> None:
        editor = html_element(self.page, "uploadedPdfEditor")
        picker = html_element(editor, "uploadedEditorReviewSwitch")
        self.assertIn('id="uploadedEditorReviewSelect"', picker)
        self.assertNotIn('data-editor-review=', picker)
        self.assertNotIn("<button", picker)
        self.assertEqual(
            re.findall(r'<option value="([^"]+)">', picker),
            ["edited", "original", "prepared", "changes"],
        )
        self.assertRegex(
            self.js,
            r'document\.querySelector\("#uploadedEditorReviewSelect"\)\?\.addEventListener\("change",\s*\(event\)\s*=>\s*void showUploadedEditorReview\(event\.target\.value\)\)',
        )
        show_review = javascript_function(self.js, "showUploadedEditorReview")
        self.assertIn('document.querySelector("#uploadedEditorReviewSelect")', show_review)
        self.assertIn("reviewGeneration", show_review)
        self.assertIn('uploadedSealEditorRuntime.reviewMode = "edited"', show_review)
        self.assertIn("await renderUploadedPdfPage()", show_review)
        self.assertRegex(
            self.js,
            r'document\.addEventListener\("keydown",[\s\S]*?uploadedSealEditorRuntime\.reviewMode\s*!==\s*"edited"',
        )

        dirty = javascript_function(self.js, "markUploadedEditorDirty")
        for stale_preview in (
            'uploadedSealEditorRuntime.preparedPdfDocument = null',
            'uploadedSealEditorRuntime.preparedUrl = ""',
            'uploadedSealEditorRuntime.changeSummary = null',
        ):
            self.assertIn(stale_preview, dirty)

        mutation = javascript_function(self.js, "commitUploadedEditorMutation")
        self.assertIn('uploadedSealEditorRuntime.reviewMode !== "edited"', mutation)

        picker_rule = re.search(r"\.pdf-editor-review-picker select\s*\{(?P<body>[^}]*)}", self.css)
        self.assertIsNotNone(picker_rule)
        self.assertRegex(picker_rule.group("body"), r"min-height:\s*44px")
        self.assertIn(':not([data-review-mode="edited"])', self.css)

    def test_invalid_or_non_a4_file_fails_without_destroying_current_editor(self) -> None:
        handler = javascript_function(self.js, "handleUploadedSealPdfChange")
        self.assertIn('file.type !== "application/pdf"', handler)
        self.assertIn("file.size > PDF_EDITOR_MAX_FILE_BYTES", handler)
        self.assertRegex(handler, r"catch\s*\(error\)\s*\{[\s\S]*?input\.value\s*=\s*\"\"")
        self.assertIn('setUploadedPdfA4Status("error", pdfA4UiErrorMessage(error))', handler)
        self.assertIn('setUploadedEditorSaveStatus("error", "PDF 未通過上傳或預檢")', handler)

        validation = javascript_function(self.js, "validateUploadedPdfDocument")
        self.assertIn("requirePdfPagesA4(await readPdfA4Pages(pdfDocument))", validation)

        loader = javascript_function(self.js, "loadUploadedPdfIntoEditor")
        validate_at = loader.index("const incomingPages = await loadPdfJsAsset")
        replace_at = loader.index("uploadedSealEditorRuntime.pdfDocuments.clear()")
        self.assertLess(
            validate_at,
            replace_at,
            "新 PDF 必須先完整解析及通過 A4 驗證，才可清除目前編輯中的文件。",
        )

    def test_responsive_contract_keeps_mobile_editor_controls_usable(self) -> None:
        normalized = re.sub(r"\s+", " ", self.css)
        self.assertIn(".pdf-editor-v2 button { min-height: 44px;", normalized)
        self.assertRegex(
            normalized,
            r"@media\s*\(max-width:\s*820px\)[^@]*?\.pdf-editor-shell\s*\{[^}]*display:\s*block",
        )
        self.assertRegex(
            normalized,
            r"@media\s*\(max-width:\s*820px\)[^@]*?\.pdf-editor-thumbnails,\s*\.pdf-editor-properties\s*\{[^}]*position:\s*fixed",
        )

    def test_signed_tus_upload_uses_only_public_client_credentials_and_official_metadata(self) -> None:
        upload_start = self.js.index("async function performTusUpload")
        upload_end = self.js.index("\nasync function finalizeEditorUpload", upload_start)
        upload = self.js[upload_start:upload_end]
        headers = javascript_function(self.js, "editorTusIntentHeaders")
        endpoint = javascript_function(self.js, "validateEditorTusEndpoint")

        self.assertIn("validateEditorTusEndpoint(intent)", upload)
        self.assertIn("editorTusIntentHeaders(intent)", upload)
        self.assertIn('"x-signature": signature', headers)
        self.assertIn("headers.apikey = publicKey", headers)
        self.assertIn('key.startsWith("sb_secret_")', self.js)
        self.assertIn('payload?.role === "anon"', self.js)
        self.assertNotIn("...intent.headers", upload)
        self.assertNotIn("Authorization", headers)
        self.assertIn('url.hostname.endsWith(".storage.supabase.co")', endpoint)
        self.assertIn('=== "/storage/v1/upload/resumable/sign"', endpoint)

        for metadata_key in ("bucketName", "objectName", "contentType", "cacheControl"):
            self.assertIn(f"`{metadata_key} ${{tusMetadataValue(", upload)
        self.assertNotIn("`filename ${tusMetadataValue", upload)
        self.assertNotIn("`filetype ${tusMetadataValue", upload)
        self.assertIn("const chunkSize = 6 * 1024 * 1024", upload)
        self.assertIn("uploadLocation.origin !== endpointUrl.origin", upload)
        self.assertIn('uploadLocation.pathname.startsWith("/storage/v1/upload/resumable/sign/")', upload)
        self.assertIn("editorTusRemoteOffset(uploadUrl, baseHeaders)", upload)
        self.assertIn("onProgress(Math.min(1, offset / Math.max(1, file.size)))", upload)

    def test_upload_failure_is_visible_retryable_and_closes_pending_intent(self) -> None:
        editor = html_element(self.page, "uploadedPdfEditor")
        failure_panel = html_element(editor, "uploadedEditorUploadError")
        self.assertIn('role="alert"', failure_panel)
        self.assertIn('id="uploadedEditorRetryUploadBtn"', failure_panel)
        self.assertIn('id="uploadedEditorDismissUploadErrorBtn"', failure_panel)

        reporter = javascript_function(self.js, "reportEditorUploadFailure")
        self.assertIn("/editor-uploads/${encodeURIComponent(intent.upload_id)}/fail", reporter)
        self.assertIn('JSON.stringify({ error_code: editorUploadFailureCode(error) })', reporter)

        handler = javascript_function(self.js, "handleUploadedSealPdfChange")
        self.assertIn("await reportEditorUploadFailure(intent, error)", handler)
        self.assertIn("showUploadedEditorUploadError(", handler)
        self.assertIn("handleUploadedSealPdfChange(file)", handler)
        self.assertIn('clearUploadedEditorUploadError()', handler)

    def test_mobile_editor_drawers_have_close_backdrop_escape_and_safe_bottom_clearance(self) -> None:
        editor = html_element(self.page, "uploadedPdfEditor")
        for element_id in (
            "uploadedEditorThumbnailCloseBtn",
            "uploadedEditorPropertiesCloseBtn",
            "uploadedEditorMobileBackdrop",
        ):
            self.assertIn(f'id="{element_id}"', editor)
        self.assertRegex(
            editor,
            r'id="uploadedEditorThumbnailToggleBtn"[^>]*aria-controls="uploadedEditorThumbnailPane"[^>]*aria-haspopup="dialog"',
        )
        self.assertRegex(
            editor,
            r'id="uploadedEditorPropertiesToggleBtn"[^>]*aria-controls="uploadedEditorProperties"[^>]*aria-haspopup="dialog"',
        )

        normalized = re.sub(r"\s+", " ", self.css)
        self.assertRegex(
            normalized,
            r"\.pdf-editor-thumbnails, \.pdf-editor-properties \{[^}]*bottom: calc\(var\(--mobile-nav-height, 0px\) \+ var\(--mobile-safe-bottom,[^}]*z-index: 220",
        )
        self.assertIn(".pdf-editor-mobile-backdrop { position: fixed; inset: 0; z-index: 210;", normalized)
        self.assertIn(".uploaded-page-chip { width: 44px; min-width: 44px; height: 44px; min-height: 44px;", normalized)
        self.assertIn('if (event.key === "Escape")', self.js)
        self.assertIn('closeUploadedEditorMobileDrawer()', self.js)
        self.assertIn('if (event.key !== "Tab") return', self.js)
        self.assertIn('document.activeElement === last', self.js)


class ElectronicSealA4BackendContractTest(unittest.TestCase):
    @staticmethod
    def editor_state(width: float, height: float) -> dict:
        return {
            "schemaVersion": backend.EDOC_EDITOR_SCHEMA_VERSION,
            "revisionNo": 0,
            "sourceFiles": [
                {
                    "assetId": "ASSET-TEST-A4",
                    "kind": "source_pdf",
                    "fileName": "sanitized.pdf",
                    "mimeType": "application/pdf",
                    "sizeBytes": 1024,
                    "sha256": "A" * 64,
                }
            ],
            "pages": [
                {
                    "pageId": "PAGE-TEST-A4-1",
                    "sourceAssetId": "ASSET-TEST-A4",
                    "sourcePageIndex": 0,
                    "widthPt": width,
                    "heightPt": height,
                    "cropBox": [0, 0, width, height],
                    "rotation": 0,
                    "order": 0,
                }
            ],
            "elements": [],
            "manifestSha256": "",
        }

    def test_backend_accepts_a4_portrait_and_landscape(self) -> None:
        for width, height in (
            (backend.EDOC_A4_WIDTH_PT, backend.EDOC_A4_HEIGHT_PT),
            (backend.EDOC_A4_HEIGHT_PT, backend.EDOC_A4_WIDTH_PT),
        ):
            state = backend.validate_editor_state(self.editor_state(width, height))
            self.assertTrue(state["manifestSha256"])

    def test_backend_rejects_letter_page_even_if_frontend_is_bypassed(self) -> None:
        with self.assertRaisesRegex(ValueError, r"pdf_page_not_a4:page=1"):
            backend.validate_editor_state(copy.deepcopy(self.editor_state(612, 792)))


if __name__ == "__main__":
    unittest.main()
