"""Approve a synthetic electronic letter and download its locked PDF through the UI.

Uses isolated local Finance/SQLite fixtures, real authorization checks, actual
approval HTTP endpoints, and a real browser download. Never dispatches mail or
uses a production account, database, seal, or exchange provider.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from unittest import mock
from urllib.parse import urlparse
import uuid


def run(root: Path, output: Path) -> dict:
    sys.path.insert(0, str(root))
    import backend
    from pypdf import PdfReader
    from tools.six_role_browser_acceptance import AUDIT_JS, Browser, TELEMETRY, require_local_origin
    from tests.support.five_account_browser_fixture import isolated_browser_session
    from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler

    output.mkdir(parents=True, exist_ok=True)
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

    def require(condition, code):
        if not condition:
            raise AssertionError(code)

    report = {"scope": "isolated_local_synthetic_approval_no_dispatch", "rows": []}
    with mock.patch.object(QuietAcceptanceHandler, "send_head", instrumented_head):
        fixture.setUpClass()
        require_local_origin(fixture.origin)
        config = Path(fixture.tmp.name) / "electronic-download-browser.json"
        config.write_text(json.dumps({"allowedDomains": ["127.0.0.1", "fonts.googleapis.com", "fonts.gstatic.com"], "headed": False}))
        browser = Browser(config, session="electronic-final-download", namespace="edoc-electronic-final")
        try:
            auth = isolated_browser_session(fixture, "staff")
            document_id = "OD-BROWSER-ELECTRONIC-" + str(uuid.uuid4())
            subject = "有關隔離測試電子公文核准下載一案，請查照。"
            detail = fixture._expect_json("POST", "/api/official-documents", 201, token=auth["token"], json_body={
                "id": document_id, "source_type": "blank_editor",
                "company_id": auth["user"]["company_id"], "document_type": "outgoing_official_document",
                "output_mode": "electronic", "title": subject, "subject": subject,
                "description": "一、本函只用於本機隔離驗收，不包含真實個人資料。\n二、本驗收不寄發、不用印、不連接正式交換環境。",
                "recipient": "隔離測試收文單位", "request_reason": "測試核准後電子公文主下載按鈕。",
                "document_category": "主管機關 申請或回覆文件（與 費用、法令無關）",
                "dispatch_method": "email_by_general_affairs", "dispatch_date": "2026-09-16",
                "submit": False,
                "metadata": {"source": "compose_form", "contact_owner": "隔離測試申請人", "contact_phone": "02-66045432 #999", "contact_fax": "N/A", "contact_email": "fixtureapplicant@example.test"},
            })
            detail = fixture._expect_json("POST", f"/api/official-documents/{document_id}/submit", 200, token=auth["token"], json_body={"comment": "隔離驗收送簽，不寄發。"})
            require(detail.get("output_mode") == "electronic" and not detail.get("requires_stamp"), "electronic_submission_mode_mismatch")
            approvals = []
            while detail["current_status"] != "pending_general_affairs_dispatch":
                require(len(approvals) < 8, "approval_progress_stalled")
                step = next(item for item in detail["approval_steps"] if item["step_key"] == detail["current_step"])
                token = fixture._token_for_user_id(step["approver_user_id"])
                for file in detail.get("files", []):
                    if file["file_type"] in {"generated_pdf", "original_pdf", "attachment"}:
                        response = fixture._request("GET", f"/api/official-documents/{document_id}/files/{file['id']}/download", token=token)
                        require(response.status == 200 and response.body, "approver_source_download_failed")
                detail = fixture._expect_json("POST", f"/api/official-documents/{document_id}/approve", 200, token=token, json_body={
                    "expected_step_id": step["id"], "comment": "隔離測試已檢閱並核准。",
                    "review_acknowledgements": {"original_reviewed": True, "edited_version_reviewed": True, "attachments_reviewed": True},
                })
                approvals.append(step["step_key"])
            final_id = detail["stamped_file_id"]
            final_file = next(item for item in detail["files"] if item["id"] == final_id)
            require(final_file["file_type"] == "generated_pdf", "released_file_not_generated_pdf")
            require(not any(item["file_type"] == "stamped_pdf" for item in detail["files"]), "electronic_output_has_stamped_pdf")
            with backend.connect() as conn:
                metadata = backend.parse_json_field(backend.official_document_row(conn, document_id)["metadata_json"])
            locked = metadata["electronic_output"]
            require(locked["source_file_id"] == final_id, "released_file_not_locked_source")
            expected = fixture._request("GET", f"/api/official-documents/{document_id}/files/{final_id}/download", token=auth["token"])
            require(expected.status == 200 and expected.body.startswith(b"%PDF"), "applicant_final_download_unavailable")
            expected_hash = hashlib.sha256(expected.body).hexdigest().upper()
            require(expected_hash == locked["source_sha256"].upper(), "locked_source_hash_mismatch")
            report.update(documentId=document_id, fileId=final_id, lockedSha256=expected_hash, approvedSteps=approvals, finalStatus=detail["current_status"], noDispatch=True)

            for device, size in (("desktop", (1440, 1000)), ("mobile", (390, 844))):
                browser.run("set", "viewport", *map(str, size))
                browser.run("open", fixture.origin + "/assets/favicon-32.png")
                browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                browser.run("open", fixture.origin + f"/?electronic_final_fixture={time.monotonic_ns()}#dashboard")
                browser.until("Boolean(window.__fixtureTiming?.appInteractiveMs)")
                browser.run("snapshot", "-i")
                require(browser.evaluate("document.body.innerText.trim().length>0&&!document.querySelector('[data-nextjs-dialog],.vite-error-overlay')"), "page_verification_failed")
                browser.run("screenshot", str(output / f"{device}-home.png"))
                if device == "mobile":
                    browser.run("click", "#mobileMenuButton")
                    browser.until("Math.abs(document.querySelector('#primarySidebar').getBoundingClientRect().left)<0.5")
                browser.run("click", '.sidebar .nav-item[data-target="approvalLog"]')
                browser.until("document.querySelector('.view.active')?.id==='approvalLog'")
                browser.click_visible('[data-approval-log-filter="processed"]')
                browser.until("document.querySelector('#approvalLogList').textContent.includes(" + json.dumps(subject) + ")")
                task_id = browser.evaluate("[...document.querySelectorAll('#approvalLogList .address-card')].find(e=>e.textContent.includes(" + json.dumps(subject) + ")).querySelector('[data-approval-log-select]').dataset.approvalLogSelect")
                browser.click_visible('[data-approval-log-select="' + task_id + '"]')
                selector = '#approvalLogDetail [data-final-stamped-download] button.primary-button'
                browser.until("document.querySelector(" + json.dumps(selector) + ")?.textContent==='下載已核准電子公文'")
                button = browser.evaluate("(()=>{const e=document.querySelector(" + json.dumps(selector) + ");return {text:e.textContent,documentId:e.dataset.documentId,fileId:e.dataset.officialDownload,heading:e.closest('[data-final-stamped-download]').textContent}})()")
                require(button["documentId"] == document_id and button["fileId"] == final_id, "main_button_not_locked_source")
                require("已核准電子公文" in button["heading"], "approved_electronic_heading_missing")
                browser.evaluate("document.querySelector(" + json.dumps(selector) + ").scrollIntoView({block:'center',behavior:'instant'});true")
                browser.run("screenshot", str(output / f"{device}-approved-electronic-download.png"))
                destination = output / f"{device}-approved-electronic.pdf"
                browser.run("download", selector, str(destination))
                data = destination.read_bytes()
                require(data == expected.body, "browser_download_differs_from_locked_file")
                reader = PdfReader(io.BytesIO(data))
                require(bool(reader.pages) and all(page.extract_text() for page in reader.pages), "browser_download_pdf_unreadable")
                text = "".join(page.extract_text() for page in reader.pages)
                require("隔離測試電子公文核准下載" in text and "115年9月16日" in text, "browser_download_content_mismatch")
                row = {"device": device, "mainButtonText": button["text"], "mainButtonFileId": button["fileId"], "lockedDownloadMatches": True, "pageCount": len(reader.pages), "pdfReadable": True, "layout": browser.evaluate(AUDIT_JS), "status": "passed"}
                require(not row["layout"]["errors"] and not row["layout"]["overflow"], "approval_browser_errors_or_overflow")
                report["rows"].append(row)
                (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
                print(json.dumps({"device": device, "status": "passed", "fileType": "generated_pdf"}), flush=True)
            poppler = shutil.which("pdftoppm")
            if poppler:
                subprocess.run([poppler, "-f", "1", "-singlefile", "-scale-to", "1200", "-png", str(output / "desktop-approved-electronic.pdf"), str(output / "approved-electronic-render")], check=True, capture_output=True, timeout=30)
                report["renderedPage"] = str(output / "approved-electronic-render.png")
            report["status"] = "passed"
        except Exception as error:
            report["status"] = "failed"
            report["errorCode"] = str(error) if isinstance(error, AssertionError) or str(error).startswith("browser_") else type(error).__name__
            try:
                report["failureState"] = browser.evaluate("({active:document.querySelector('.view.active')?.id,errors:window.__fixtureErrors,detail:document.querySelector('#approvalLogDetail')?.textContent})")
                browser.run("screenshot", str(output / "failure.png"), "--full")
            except RuntimeError:
                report["failureState"] = {"browserUnavailable": True}
        finally:
            try:
                browser.run("close")
            finally:
                fixture.tearDownClass()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.root.resolve(), args.output.resolve())
    (args.output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({"status": result["status"], "report": str(args.output / "report.json")}), flush=True)
    raise SystemExit(0 if result["status"] == "passed" else 1)
