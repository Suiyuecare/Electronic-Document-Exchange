"""DOM contracts for the simplified compose form; no production data."""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class ElementIndex(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.elements = {}
        self.duplicates = []
        self.stack = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        identity = attrs.get("id")
        element = {"tag": tag, "attrs": attrs, "ancestors": tuple(self.stack), "position": self.getpos()}
        if identity:
            if identity in self.elements:
                self.duplicates.append(identity)
            self.elements[identity] = element
        if tag not in VOID_TAGS:
            self.stack.append((tag, identity))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                self.stack = self.stack[:index]
                break


class ComposeLayoutV2ContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.css = (ROOT / "styles.css").read_text(encoding="utf-8")
        cls.js = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.dom = ElementIndex(cls.html)

    def test_compose_fields_follow_the_printed_document_order_without_duplicate_ids(self):
        ids = [
            "composeCompanySelect", "docType", "contactAddress", "contactOwner",
            "contactPhone", "contactFax", "contactEmail", "recipient", "originalRecipients",
            "copyRecipients", "dispatchDate", "dispatchNo", "priority",
            "documentPurpose", "generateFromPurposeBtn", "subject", "bodyText",
            "attachments", "attachmentDetails",
            "composeOutputMode", "largeSealType", "smallSealType", "composeApprovalCategorySelect",
        ]
        positions = [self.dom.elements[identity]["position"] for identity in ids]
        self.assertEqual(positions, sorted(positions))
        self.assertFalse(set(ids).intersection(self.dom.duplicates))
        for identity in ids:
            self.assertIn(("form", "composeForm"), self.dom.elements[identity]["ancestors"])

    def test_sender_info_fields_are_directly_visible_and_editable(self):
        group = self.dom.elements["composeContactFields"]["attrs"]
        self.assertEqual(group["role"], "group")
        self.assertEqual(group["aria-labelledby"], "composeContactHeading")
        self.assertIn("寄件資訊</h4>", self.html)
        self.assertNotIn("composeContactToggleBtn", self.html)
        self.assertNotIn("composeContactSummaryText", self.html)
        for identity in ("contactAddress", "contactOwner", "contactPhone", "contactFax", "contactEmail"):
            field = self.dom.elements[identity]
            self.assertIn(("div", "composeContactFields"), field["ancestors"])
            self.assertNotIn("hidden", field["attrs"])
            self.assertNotIn("readonly", field["attrs"])
            self.assertNotIn("disabled", field["attrs"])
        self.assertNotIn("renderComposeContactSummary", self.js)
        self.assertNotIn("toggleComposeContactSummary", self.js)
        self.assertNotIn(".compose-contact-fields label[hidden]", self.css)

    def test_date_is_editable_but_document_number_has_no_regenerate_action(self):
        date = self.dom.elements["dispatchDate"]["attrs"]
        self.assertEqual(date["type"], "date")
        self.assertIn("required", date)
        self.assertNotIn("readonly", date)
        number = self.dom.elements["dispatchNo"]["attrs"]
        self.assertIn("readonly", number)
        self.assertEqual(number["placeholder"], "儲存時自動配號")
        self.assertNotIn("generateDispatchNoBtn", self.dom.elements)

    def test_ai_button_keeps_handler_identity_and_has_an_accessible_primary_style(self):
        button = self.dom.elements["generateFromPurposeBtn"]["attrs"]
        self.assertIn("primary-button", button["class"])
        self.assertEqual(button["type"], "button")
        self.assertRegex(self.html, r'id="generateFromPurposeBtn"[^>]*>AI產生公文主旨與說明</button>')
        rule = re.search(r"\.compose-purpose-generate\s*\{([^}]+)\}", self.css).group(1)
        self.assertIn("min-height: 44px", rule)
        self.assertIn("color: #fff", rule)
        self.assertIn("background: #b45309", rule)

    def test_ai_assistance_is_open_above_subject_and_recipients_are_editable(self):
        ai = re.search(r'<details\s+class="compose-optional-fields compose-ai-assist-disclosure"(?P<attrs>[^>]*)>', self.html)
        self.assertIsNotNone(ai)
        self.assertRegex(ai.group("attrs"), r'\bopen\b')
        self.assertLess(self.dom.elements["documentPurpose"]["position"], self.dom.elements["subject"]["position"])
        for identity in ("originalRecipients", "copyRecipients"):
            field = self.dom.elements[identity]
            self.assertEqual(field["tag"], "textarea")
            self.assertNotIn("readonly", field["attrs"])
            self.assertNotIn("disabled", field["attrs"])
        self.assertLess(self.dom.elements["recipient"]["position"], self.dom.elements["originalRecipients"]["position"])

    def test_dispatch_method_label_and_submit_confirmation_are_one_flow(self):
        self.assertRegex(self.html, r'公文寄送方式\s*<select id="composeOutputMode"')
        self.assertNotIn("confirmDraftBtn", self.dom.elements)
        self.assertNotIn("resetDraftConfirmBtn", self.dom.elements)
        submit = self.dom.elements["submitDispatchBtn"]["attrs"]
        self.assertEqual(submit["type"], "submit")
        dialog = self.dom.elements["composeSubmitModal"]["attrs"]
        self.assertEqual(dialog["role"], "dialog")
        self.assertEqual(dialog["aria-modal"], "true")
        self.assertEqual(dialog["aria-labelledby"], "composeSubmitModalTitle")
        self.assertIn("hidden", dialog["class"].split())
        self.assertIn("composeSubmitCancelBtn", self.dom.elements)
        self.assertIn("composeSubmitConfirmBtn", self.dom.elements)
        self.assertIn("composeSubmitModalError", self.dom.elements)
        readiness = self.dom.elements["composeConfirmWorkflowReadinessNotice"]
        self.assertIn(("form", "composeForm"), readiness["ancestors"])
        self.assertEqual(readiness["attrs"]["role"], "status")

    def test_output_mode_owns_seal_fields_and_preserves_existing_physical_default(self):
        select = re.search(r'<select id="composeOutputMode"[^>]*>(.*?)</select>', self.html, re.S).group(1)
        self.assertRegex(select, r'<option value="electronic">A\. 電子公文（不放大小章）</option>')
        self.assertRegex(select, r'<option value="physical" selected>B\. 實體公文（可放大小章）</option>')
        for identity in ("largeSealType", "smallSealType"):
            self.assertIn(("div", "composeSealFields"), self.dom.elements[identity]["ancestors"])
        self.assertRegex(self.css, r'#composeSealFields\[hidden\]\s*\{\s*display:\s*none;')

    def test_approval_remains_visible_and_scrolling_is_limited_to_the_flow(self):
        flow = self.dom.elements["composeApprovalRoutePreview"]["attrs"]
        self.assertEqual(flow["tabindex"], "0")
        self.assertIn("左右捲動", flow["aria-label"])
        self.assertIn("composeApprovalCategoryHint", self.dom.elements)
        self.assertIn("composeApprovalRouteOutcome", self.dom.elements)
        rule = re.search(r'#composeApprovalSection \.compose-approval-flow,\s*\.compose-confirm-page \.compose-approval-flow\s*\{([^}]+)\}', self.css).group(1)
        self.assertIn("display: flex", rule)
        self.assertIn("overflow-x: auto", rule)
        self.assertIn("max-width: 100%", rule)
        self.assertIn("overscroll-behavior-inline: contain", rule)

    def test_duplicate_format_workbench_is_removed_but_compose_fields_remain(self):
        for identity in ("format", "formatDocNo", "formatAgencyForm", "formatCheckList"):
            self.assertNotIn(identity, self.dom.elements)
        self.assertIn("subjectHint", self.dom.elements)
        self.assertIn("recipientHint", self.dom.elements)
        self.assertIn("submitDispatchBtn", self.dom.elements)

    def test_contact_block_respects_textbook_body_margin_without_changing_font(self):
        rule = re.findall(r'\.draft-preview-panel\.live \.official-draft-preview \.draft-contact-block\s*\{([^}]+)\}', self.css)[-1]
        self.assertIn("width: 37.22cqw", rule)
        self.assertIn("margin-right: 0", rule)
        self.assertIn('font-family: "EDoc MOE EduKai", "標楷體"', self.css)


if __name__ == "__main__":
    unittest.main()
