from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import unittest
from unittest.mock import patch

from pypdf import PdfReader
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

from tools import live_editor_launch_acceptance as acceptance


def revision() -> dict:
    return {"id": "REV-TEST", "revisionNo": 2, "manifestSha256": "A" * 64, "state": {
        "schemaVersion": 2, "revisionNo": 2, "sourceFiles": [{"assetId": "ASSET-TEST"}],
        "pages": [
            {"pageId": "PAGE-P", "widthPt": A4[0], "heightPt": A4[1]},
            {"pageId": "PAGE-L", "widthPt": A4[1], "heightPt": A4[0]},
        ], "elements": [],
    }}


class LiveEditorLaunchAcceptanceTest(unittest.TestCase):
    def test_fixture_is_two_a4_orientations_and_contains_no_personal_data(self) -> None:
        data = acceptance.synthetic_a4_pdf()
        pdf = PdfReader(io.BytesIO(data), strict=True)
        self.assertEqual(len(pdf.pages), 2)
        self.assertAlmostEqual(float(pdf.pages[0].mediabox.width), A4[0], places=3)
        self.assertAlmostEqual(float(pdf.pages[1].mediabox.width), A4[1], places=3)
        self.assertIn("No personal data", pdf.pages[0].extract_text())
        self.assertEqual(data, acceptance.synthetic_a4_pdf())

    def test_text_edit_preserves_source_page_identity_and_never_adds_stamp(self) -> None:
        original = revision()
        snapshot = copy.deepcopy(original)
        state = acceptance.text_edit_state(original)
        self.assertEqual(original, snapshot)
        self.assertEqual(state["pages"], original["state"]["pages"])
        self.assertEqual([item["kind"] for item in state["elements"]], ["text"])

    def test_non_a4_source_is_rejected_before_save(self) -> None:
        source = revision()
        source["state"]["pages"][0]["widthPt"] = 612
        with self.assertRaisesRegex(acceptance.sso.AcceptanceError, "a4_geometry_invalid"):
            acceptance.text_edit_state(source)

    def test_download_rejects_cross_origin_before_sending_session(self) -> None:
        with patch.object(acceptance, "raw_request") as request:
            with self.assertRaisesRegex(acceptance.sso.AcceptanceError, "download_url_invalid"):
                acceptance.download("private-session", "https://untrusted.example.invalid/file")
        request.assert_not_called()

    def test_tus_rejects_service_secret_before_any_network_request(self) -> None:
        with patch.object(acceptance, "raw_request") as request:
            with self.assertRaisesRegex(acceptance.sso.AcceptanceError, "tus_credentials_invalid"):
                acceptance.tus_upload({
                    "protocol": "tus", "upload_url": "https://example.storage.supabase.co/storage/v1/upload/resumable/sign",
                    "storage_publishable_key": "sb_secret_private", "upload_token": "short-lived-capability",
                }, b"%PDF-test")
        request.assert_not_called()

    def test_missing_or_redacted_secret_stops_before_identity_inventory_or_writes(self) -> None:
        for secret in ("", "[sensitive]"):
            with self.subTest(secret_present=bool(secret)):
                output = io.StringIO()
                with (
                    patch.dict(os.environ, {"PORTAL_HANDOFF_SIGNING_SECRET": secret}),
                    patch.object(acceptance.sso, "portal_google_accounts") as inventory,
                    patch.object(acceptance, "raw_request") as request,
                    contextlib.redirect_stdout(output),
                ):
                    self.assertEqual(acceptance.main(), 1)
                result = json.loads(output.getvalue())
                self.assertEqual(result["retainedDraftIds"], [])
                self.assertEqual(result["sessionsRevoked"], 0)
                inventory.assert_not_called()
                request.assert_not_called()

    def test_flow_records_hash_conflict_acl_and_retains_only_unsubmitted_draft(self) -> None:
        source = acceptance.synthetic_a4_pdf()
        source_hash = hashlib.sha256(source).hexdigest().upper()
        prepared_stream = io.BytesIO()
        pdf = canvas.Canvas(prepared_stream, pagesize=A4)
        pdf.drawString(72, 100, "EDOC-LIVE-EDITOR-SAVED")
        pdf.showPage()
        pdf.setPageSize(landscape(A4))
        pdf.showPage()
        pdf.save()
        prepared_bytes = prepared_stream.getvalue()
        prepared_hash = hashlib.sha256(prepared_bytes).hexdigest().upper()
        initial = revision()
        saved = {**copy.deepcopy(initial), "id": "REV-SAVED", "revisionNo": 3, "manifestSha256": "B" * 64,
                 "state": acceptance.text_edit_state(initial)}
        calls = []

        def api(token, method, path, expected, body=None):
            calls.append((token, method, path, expected))
            self.assertNotIn("/submit", path)
            self.assertNotIn("/resubmit", path)
            self.assertNotIn("/seal", path)
            self.assertNotEqual(method, "DELETE")
            if path.endswith("editor-drafts"):
                self.assertIn("上線驗收測試", body["title"])
                self.assertEqual(body["dispatch_method"], "no_dispatch_required")
                return {"document_id": "OD-TEST"}
            if path.endswith("/editor-uploads"):
                return {"upload_id": "ASSET-TEST", "protocol": "tus"}
            if path.endswith("/finalize"):
                return {"asset": {"scanStatus": "passed", "preflightStatus": "passed", "sha256": source_hash, "officialFileId": "FILE-SOURCE"}, "editor_revision": initial}
            if path.endswith("/editor-state"):
                return saved if expected == 200 else {"error": "conflict_or_forbidden"}
            if path.endswith("/editor-preflight"):
                return {"preparedUrl": "/api/official-documents/OD-TEST/files/FILE-PREPARED/download", "preparedSha256": prepared_hash}
            if path.endswith("/editor-change-summary"):
                return {"changes": {"total": 1}}
            return {"current_status": "draft", "approval_steps": []}

        def download(token, path, expected=200):
            if expected != 200:
                return b""
            return source if "FILE-SOURCE" in path else prepared_bytes

        report = {"checks": {}, "retainedDraftIds": [], "notExercised": []}
        with patch.object(acceptance, "api", side_effect=api), patch.object(acceptance, "tus_upload"), patch.object(acceptance, "download", side_effect=download):
            acceptance.run_editor_checks("owner", {"company_id": "CO-TEST"}, "other", report)
        self.assertEqual(report["retainedDraftIds"], ["OD-TEST"])
        self.assertTrue(report["checks"]["remainsUnsubmittedDraft"])
        self.assertTrue(report["checks"]["crossCompanyReadAndDownloadDenied"])
        self.assertTrue(report["checks"]["originalSourceHashPreserved"])
        self.assertTrue(any(call[3] == 409 and call[1] == "PUT" for call in calls))


if __name__ == "__main__":
    unittest.main()
