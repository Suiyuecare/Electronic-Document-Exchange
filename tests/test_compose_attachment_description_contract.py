from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def javascript_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    end = re.search(r"\n(?:async )?function \w+\(", source[start:])
    if end is None:
        raise AssertionError(f"Missing function boundary: {name}")
    return source[start:start + end.start()]


class ComposeAttachmentDescriptionContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")

    def run_js(self, body: str) -> dict:
        helpers = "\n".join(javascript_function(self.js, name) for name in (
            "syncComposeAttachmentDescription", "draftAttachmentText", "officialComposeAttachmentDescription",
        ))
        result = subprocess.run(
            ["node", "-e", helpers + "\n" + body],
            check=True, capture_output=True, text=True, timeout=20,
        )
        return json.loads(result.stdout)

    def test_upload_autofills_multiple_filenames_without_modifying_files(self) -> None:
        result = self.run_js('''
          const files = [{name: "測試附件一.pdf"}, {name: "測試附件二 (1).pdf"}];
          const input = {files};
          const description = {value: "", dataset: {}};
          global.document = {querySelector: selector => selector === "#attachments" ? input : description};
          syncComposeAttachmentDescription();
          console.log(JSON.stringify({value: description.value, sameFiles: input.files === files,
            names: input.files.map(file => file.name),
            preview: draftAttachmentText({attachments: files.map(file => file.name), attachmentDetails: description.value})}));
        ''')
        expected = "測試附件一.pdf、測試附件二 (1).pdf"
        self.assertEqual(result["value"], expected)
        self.assertEqual(result["preview"], expected)
        self.assertTrue(result["sameFiles"])
        self.assertEqual(result["names"], ["測試附件一.pdf", "測試附件二 (1).pdf"])

    def test_reselection_updates_only_the_unedited_default(self) -> None:
        result = self.run_js('''
          const input = {files: [{name: "old.pdf"}]};
          const description = {value: "", dataset: {}};
          global.document = {querySelector: selector => selector === "#attachments" ? input : description};
          syncComposeAttachmentDescription();
          input.files = [{name: "new.pdf"}];
          syncComposeAttachmentDescription();
          const updated = description.value;
          description.value = "附件一：測試補正資料，共二頁。";
          input.files = [{name: "third.pdf"}];
          syncComposeAttachmentDescription();
          input.files = [];
          syncComposeAttachmentDescription();
          console.log(JSON.stringify({updated, custom: description.value}));
        ''')
        self.assertEqual(result["updated"], "new.pdf")
        self.assertEqual(result["custom"], "附件一：測試補正資料，共二頁。")

    def test_preexisting_custom_text_is_not_replaced(self) -> None:
        result = self.run_js('''
          const description = {value: "既有草稿的附件說明", dataset: {}};
          global.document = {querySelector: selector => selector === "#attachments"
            ? {files: [{name: "new.pdf"}]} : description};
          syncComposeAttachmentDescription();
          console.log(JSON.stringify({value: description.value}));
        ''')
        self.assertEqual(result["value"], "既有草稿的附件說明")

    def test_intentionally_edited_or_cleared_text_survives_new_file_selection(self) -> None:
        result = self.run_js('''
          const input = {files: [{name: "next.pdf"}]};
          const description = {value: "same-as-file.pdf", dataset: {
            attachmentFileNames: "same-as-file.pdf", attachmentTextEdited: "true"
          }};
          global.document = {querySelector: selector => selector === "#attachments" ? input : description};
          syncComposeAttachmentDescription();
          const edited = description.value;
          description.value = "";
          syncComposeAttachmentDescription();
          console.log(JSON.stringify({edited, cleared: description.value}));
        ''')
        self.assertEqual(result["edited"], "same-as-file.pdf")
        self.assertEqual(result["cleared"], "")

    def test_preview_preserves_edited_text_and_explicit_empty_without_filenames(self) -> None:
        result = self.run_js('''
          const attachments = ["original (1).pdf"];
          console.log(JSON.stringify({
            edited: draftAttachmentText({attachments, attachmentDetails: "附件一；測試清冊\\n附件二：補充說明"}),
            empty: draftAttachmentText({attachments, attachmentDetails: ""}),
            whitespace: draftAttachmentText({attachments, attachmentDetails: "  "}),
            legacy: draftAttachmentText({attachments})
          }));
        ''')
        self.assertEqual(result["edited"], "附件一；測試清冊\n附件二：補充說明")
        self.assertEqual(result["empty"], "無")
        self.assertEqual(result["whitespace"], "無")
        self.assertEqual(result["legacy"], "original (1).pdf")

    def test_upload_binding_runs_before_preview_and_autosave_handlers(self) -> None:
        binding = 'document.querySelector("#attachments")?.addEventListener("change", syncComposeAttachmentDescription);'
        self.assertIn(binding, self.js)
        self.assertLess(self.js.index(binding), self.js.rindex('["#composeCompanySelect"'))
        autosave = self.js.split("const composeAutosaveSelectors = [", 1)[1].split("];", 1)[0]
        self.assertIn('"#attachmentDetails"', autosave)

    def test_reopen_prefers_saved_edit_including_empty_and_supports_legacy_drafts(self) -> None:
        result = self.run_js('''
          console.log(JSON.stringify({
            edited: officialComposeAttachmentDescription({}, {extra: {attachment_details: "修改後"}, attachment_details: "舊說明", attachments: "old.pdf"}),
            empty: officialComposeAttachmentDescription({attachments_summary: "old.pdf"}, {extra: {attachment_details: ""}}),
            legacyText: officialComposeAttachmentDescription({}, {attachments: "original.pdf"}),
            legacyList: officialComposeAttachmentDescription({}, {attachments: [{file_name: "one.pdf"}, "two.pdf"]})
          }));
        ''')
        self.assertEqual(result, {"edited": "修改後", "empty": "", "legacyText": "original.pdf", "legacyList": "one.pdf、two.pdf"})

    def test_save_reopen_and_pdf_payload_keep_description_separate_from_files(self) -> None:
        create = javascript_function(self.js, "createOfficialApplicationFromCompose")
        self.assertIn("attachments_summary: data.attachmentDetails,", create)
        self.assertNotIn('data.attachmentDetails || data.attachments.join', create)
        self.assertIn("attachment_details: data.attachmentDetails", create)
        self.assertIn("uploadOfficialDocumentAttachments(result.id, attachments)", create)
        correction = javascript_function(self.js, "beginComposeOfficialCorrection")
        self.assertIn('"#attachmentDetails": officialComposeAttachmentDescription(item, metadata)', correction)
        self.assertIn('attachmentDetails: values["#attachmentDetails"]', correction)
        pdf = javascript_function(self.js, "backendPdfPayload")
        self.assertIn("attachments: doc.attachments", pdf)
        self.assertIn("attachmentDetails: doc.attachmentDetails", pdf)
        fallback = javascript_function(self.js, "buildOfficialPdf")
        self.assertIn("draftAttachmentText(doc)", fallback)

    def test_description_remains_editable_and_explains_file_separation(self) -> None:
        field = re.search(r'<textarea id="attachmentDetails"([^>]*)>', self.html)
        self.assertIsNotNone(field)
        self.assertNotRegex(field.group(1), r"\b(readonly|disabled)\b")
        self.assertIn('maxlength="5000"', field.group(1))
        self.assertIn("data.attachmentDetails.length <= 5000", self.js)
        self.assertIn("修改文字不會更改附件檔名或內容", self.html)


if __name__ == "__main__":
    unittest.main()
