"""Isolated real-browser regression for editable compose attachment text."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import time
from unittest import mock
from urllib.parse import urlparse


def run(root: Path, output: Path) -> dict:
    sys.path.insert(0, str(root))
    from tools.six_role_browser_acceptance import AUDIT_JS, Browser, TELEMETRY, require_local_origin
    from tests.support.five_account_browser_fixture import isolated_browser_session
    from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    output.mkdir(parents=True, exist_ok=True)
    files = []
    for number in (1, 2, 3):
        path = output / f"synthetic-attachment-{number}.pdf"
        writer = canvas.Canvas(str(path), pagesize=A4)
        writer.drawString(60, 780, f"ISOLATED ATTACHMENT {number} - NO PERSONAL DATA")
        writer.save()
        files.append(path)
    fixture = FiveAccountHttpAcceptanceTest
    original_head = QuietAcceptanceHandler.send_head

    def instrumented_head(handler):
        if urlparse(handler.path).path in {"/", "/index.html"}:
            data = (root / "index.html").read_text().replace("<head>", "<head>" + TELEMETRY, 1).encode()
            handler.send_response(200)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            return io.BytesIO(data)
        return original_head(handler)

    report = {"scope": "isolated_local_browser_no_production_no_submission", "rows": []}
    with mock.patch.object(QuietAcceptanceHandler, "send_head", instrumented_head):
        fixture.setUpClass()
        require_local_origin(fixture.origin)
        config = Path(fixture.tmp.name) / "agent-browser.json"
        config.write_text(json.dumps({"allowedDomains": ["127.0.0.1", "fonts.googleapis.com", "fonts.gstatic.com"], "headed": False}))
        browser = Browser(config, session="attach-qa", namespace="edoc-attach")

        def require(condition, code):
            if not condition:
                raise AssertionError(code)

        def attachment_text():
            return browser.evaluate("[...document.querySelectorAll('#draftPreview .draft-official-meta > div')].find(e=>e.querySelector('span')?.textContent==='附件：')?.querySelector('strong')?.textContent")

        def navigate(route, device):
            if device == "mobile":
                browser.run("click", "#mobileMenuButton")
                browser.until("Math.abs(document.querySelector('#primarySidebar').getBoundingClientRect().left)<0.5")
            browser.run("click", f'.sidebar .nav-item[data-target="{route}"]')
            browser.until("document.querySelector('.view.active')?.id===" + json.dumps(route))

        try:
            auth = isolated_browser_session(fixture, "staff")
            for device, dimensions in (("desktop", (1440, 1000)), ("mobile", (390, 844))):
                browser.run("set", "viewport", *map(str, dimensions))
                browser.run("open", fixture.origin + "/assets/favicon-32.png")
                browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                browser.run("open", fixture.origin + f"/?attachment_fixture={time.monotonic_ns()}#dashboard")
                browser.until("Boolean(window.__fixtureTiming?.appInteractiveMs)")
                browser.run("snapshot", "-i")
                require(browser.evaluate("document.body.innerText.trim().length>0&&!document.querySelector('[data-nextjs-dialog],.vite-error-overlay')"), "page_verification_failed")
                browser.run("screenshot", str(output / f"{device}-home.png"))
                navigate("compose", device)
                browser.until("document.querySelector('#composeApprovalCategorySelect')?.options.length>1")
                category = browser.evaluate("[...document.querySelector('#composeApprovalCategorySelect').options].find(e=>e.textContent.includes('合作意向書')).value")
                browser.run("select", "#composeApprovalCategorySelect", category)
                browser.run("fill", "#recipient", "隔離測試受文單位")
                browser.run("fill", "#subject", "有關隔離測試附件文字獨立顯示一案，請查照。")
                browser.run("fill", "#bodyText", "一、本函僅供隔離測試，不送簽、不寄發。")
                browser.run("fill", "#contactPhone", "02-66045432 #999")
                browser.run("upload", "#attachments", str(files[0]), str(files[1]))
                expected = "、".join(path.name for path in files[:2])
                browser.until("document.querySelector('#attachmentDetails').value===" + json.dumps(expected))
                browser.until("[...document.querySelectorAll('#draftPreview .draft-official-meta > div')].some(e=>e.querySelector('span')?.textContent==='附件：'&&e.querySelector('strong')?.textContent===" + json.dumps(expected) + ")")
                row = {"device": device, "autoFill": True, "autoFillText": attachment_text()}
                custom = "附件一：申請資料；附件二：補充說明（可自行編輯）"
                browser.run("fill", "#attachmentDetails", custom)
                browser.until("[...document.querySelectorAll('#draftPreview .draft-official-meta > div')].some(e=>e.querySelector('span')?.textContent==='附件：'&&e.querySelector('strong')?.textContent===" + json.dumps(custom) + ")")
                row["customPreviewOnly"] = attachment_text() == custom
                browser.run("upload", "#attachments", str(files[2]))
                require(browser.evaluate("document.querySelector('#attachmentDetails').value") == custom, "manual_description_overwritten")
                row["manualEditSurvivesReselection"] = True
                browser.run("fill", "#attachmentDetails", "")
                browser.until("[...document.querySelectorAll('#draftPreview .draft-official-meta > div')].some(e=>e.querySelector('span')?.textContent==='附件：'&&e.querySelector('strong')?.textContent==='無')")
                row["emptyPreviewHasNoFilenameFallback"] = attachment_text() == "無"
                browser.run("upload", "#attachments", str(files[0]))
                require(browser.evaluate("document.querySelector('#attachmentDetails').value") == "", "explicit_empty_description_overwritten")
                row["explicitEmptySurvivesReselection"] = True
                browser.run("fill", "#attachmentDetails", custom)
                browser.run("upload", "#attachments", str(files[2]))
                browser.until("[...document.querySelectorAll('#draftPreview .draft-official-meta > div')].some(e=>e.querySelector('span')?.textContent==='附件：'&&e.querySelector('strong')?.textContent===" + json.dumps(custom) + ")")
                browser.evaluate("document.querySelector('#attachmentDetails').scrollIntoView({block:'center',behavior:'instant'});true")
                browser.run("screenshot", str(output / f"{device}-custom-description.png"), "--full")
                browser.evaluate("document.querySelector('#draftPreview .draft-official-meta').scrollIntoView({block:'center',behavior:'instant'});true")
                browser.run("screenshot", str(output / f"{device}-preview-only-description.png"))
                row["layout"] = browser.evaluate(AUDIT_JS)
                require(not row["layout"]["overflow"], "document_overflow")
                require(not row["layout"]["errors"], "browser_errors")
                browser.click_visible("#saveDispatchDraftBtn")
                browser.until("['saved','error'].includes(composeSaveState.tone)", timeout=40)
                row["saveStatus"] = browser.evaluate("({tone:composeSaveState.tone,title:composeSaveState.title,detail:composeSaveState.detail})")
                require(row["saveStatus"]["tone"] == "saved", "draft_save_failed")
                document_id = browser.evaluate("dispatchDocs.find(e=>e.id===currentComposeDraftId)?.officialDocumentId")
                detail = fixture._expect_json("GET", f"/api/official-documents/{document_id}", 200, token=auth["token"])
                metadata = detail.get("metadata") or json.loads(detail.get("metadata_json") or "{}")
                metadata = {**metadata.get("extra", {}), **metadata}
                require(metadata.get("attachment_details") == custom, "saved_description_mismatch")
                attachments = [item for item in detail.get("files", []) if item.get("file_type") == "attachment"]
                row["savedAttachmentNames"] = [item["file_name"] for item in attachments]
                require(row["savedAttachmentNames"] == [files[2].name], "actual_attachment_name_changed")
                row["savedDescription"] = metadata["attachment_details"]
                row["savedAttachmentHash"] = attachments[0].get("sha256") or attachments[0].get("checksum_sha256") or attachments[0].get("file_hash")
                row["originalFixtureHash"] = hashlib.sha256(files[2].read_bytes()).hexdigest().upper()
                require(row["savedAttachmentHash"] == row["originalFixtureHash"], "actual_attachment_bytes_changed")
                download = fixture._request("GET", f"/api/official-documents/{document_id}/files/{attachments[0]['id']}/download", token=auth["token"])
                require(download.status == 200 and download.body == files[2].read_bytes(), "actual_attachment_download_changed")
                row["downloadBytesUnchanged"] = True
                # Exercise the application's authorized correction loader against the saved API record.
                browser.evaluate("(async()=>{await beginOfficialCorrection(officialWorkflowItems.find(e=>e.id===" + json.dumps(document_id) + "));return true})()")
                browser.until("document.querySelector('#attachmentDetails').value===" + json.dumps(custom))
                row["savedReopenDescriptionMatched"] = True
                require(attachment_text() == custom, "saved_reopen_preview_mismatch")
                row["status"] = "passed"
                report["rows"].append(row)
                (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
                print(json.dumps({"device": device, "status": "passed"}), flush=True)
            report["status"] = "passed"
            return report
        except Exception as error:
            report["status"] = "failed"
            report["errorCode"] = str(error) if isinstance(error, AssertionError) or str(error).startswith("browser_") else type(error).__name__
            try:
                report["failureState"] = browser.evaluate("({active:document.querySelector('.view.active')?.id,errors:window.__fixtureErrors,save:typeof composeSaveState==='undefined'?null:composeSaveState,description:document.querySelector('#attachmentDetails')?.value,toast:document.querySelector('#toast')?.textContent})")
                browser.run("screenshot", str(output / "failure.png"), "--full")
            except RuntimeError:
                report["failureState"] = {"browserUnavailable": True}
            return report
        finally:
            try:
                browser.run("close")
            finally:
                fixture.tearDownClass()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.root.resolve(), args.output.resolve())
    (args.output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({"status": result["status"], "report": str(args.output / "report.json")}), flush=True)
    raise SystemExit(0 if result["status"] == "passed" else 1)
