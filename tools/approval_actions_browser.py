"""Actual dialog/HTTP approval actions on disposable synthetic local data."""
import argparse
import json
from pathlib import Path
import sys
import subprocess
import uuid
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.six_role_browser_acceptance import Browser, VIEWPORTS, AUDIT_JS, require_local_origin
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler


def open_dialog(browser, fixture, auth, device, subject, action):
    browser.run("open", fixture.origin + "/assets/favicon-32.png")
    browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
    browser.run("set", "viewport", *map(str, VIEWPORTS[device]))
    browser.run("open", fixture.origin + "/#approvalLog")
    browser.until("typeof hasAuthenticatedBackendSession==='function'&&hasAuthenticatedBackendSession()&&document.querySelector('.view.active')?.id==='approvalLog'&&!document.querySelector('#moduleEntryProgress')?.getClientRects().length")
    browser.click_visible('[data-approval-log-filter="' + ("processed" if action == "withdraw" else "my_pending") + '"]')
    browser.until("document.querySelector('#approvalLogList').textContent.includes(" + json.dumps(subject) + ")")
    identity = browser.evaluate("[...document.querySelectorAll('#approvalLogList .address-card')].find(e=>e.textContent.includes(" + json.dumps(subject) + ")).querySelector('[data-approval-log-select]').dataset.approvalLogSelect")
    browser.click_visible('[data-approval-log-select="' + identity + '"]')
    selector = '#approvalLogDetail [data-progress-official-action="' + action + '"]'
    browser.until("Boolean(document.querySelector(" + json.dumps(selector) + "))")
    browser.click_visible(selector)
    browser.until("document.querySelector('#officialDecisionModal').getClientRects().length>0")


def audit(output, baseline_ref=None):
    fixture = FiveAccountHttpAcceptanceTest
    fixture.setUpClass()
    require_local_origin(fixture.origin)
    original_headers = QuietAcceptanceHandler.end_headers
    def uncached_headers(handler):
        handler.send_header("Cache-Control", "no-store")
        original_headers(handler)
    header_patch = mock.patch.object(QuietAcceptanceHandler, "end_headers", uncached_headers)
    header_patch.start()
    output.mkdir(parents=True, exist_ok=True)
    config = Path(fixture.tmp.name) / "approval-actions-browser.json"
    config.write_text(json.dumps({"headed": False}))
    browser = Browser(config, session="edoc-approval-actions", namespace="edoc-approval-actions")
    report = {"scope": "isolated_local_synthetic_browser_http", "realGoogleLoginVerified": False, "rows": [], "beforeAfter": []}
    baseline = Path(fixture.tmp.name) / "baseline"
    if baseline_ref:
        baseline.mkdir()
        for filename in ("index.html", "app.js", "styles.css"):
            (baseline / filename).write_bytes(subprocess.check_output(["git", "show", baseline_ref + ":" + filename], cwd=ROOT))
    try:
        applicant = isolated_browser_session(fixture, "staff", entity_id="E1")
        for device in ("desktop", "tablet", "mobile"):
            for action in ("withdraw", "return-previous", "decline", "approve", "reject"):
                doc_id = "OD-ACTION-" + uuid.uuid4().hex
                subject = "隔離簽核驗收-" + device + "-" + action
                draft = fixture._expect_json("POST", "/api/official-documents", 201, token=applicant["token"], json_body={
                    "id": doc_id, "source_type": "blank_editor", "company_id": applicant["user"]["company_id"],
                    "document_type": "outgoing_official_document", "output_mode": "electronic", "title": subject,
                    "subject": subject, "description": "一、本件只用於隔離驗收，不寄發或交換。", "recipient": "合成收文單位",
                    "request_reason": "去識別化簽核測試", "document_category": "主管機關 申請或回覆文件（與 費用、法令無關）",
                    "dispatch_method": "email_by_general_affairs", "dispatch_date": "2026-10-06", "submit": False,
                    "metadata": {"source": "compose_form", "contact_owner": "合成申請人", "contact_phone": "02-00000000 #999", "contact_email": "fixture@example.invalid"}})
                detail = fixture._expect_json("POST", f"/api/official-documents/{doc_id}/submit", 200, token=applicant["token"], json_body={"comment": "合成驗收送簽。", "expected_content_revision": draft["content_revision"]})
                first_step = detail["current_step"]
                if action == "return-previous":
                    step = next(row for row in detail["approval_steps"] if row["step_key"] == detail["current_step"])
                    token = fixture._token_for_user_id(step["approver_user_id"])
                    for file in detail["files"]:
                        fixture._request("GET", f"/api/official-documents/{doc_id}/files/{file['id']}/download", token=token)
                    detail = fixture._expect_json("POST", f"/api/official-documents/{doc_id}/approve", 200, token=token, json_body={
                        "expected_step_id": step["id"], "comment": "合成審核已確認。", "review_acknowledgements": {"original_reviewed": True, "edited_version_reviewed": True, "attachments_reviewed": True}})
                step = next(row for row in detail["approval_steps"] if row["step_key"] == detail["current_step"])
                token = applicant["token"] if action == "withdraw" else fixture._token_for_user_id(step["approver_user_id"])
                auth = {**fixture._expect_json("GET", "/api/auth/me", 200, token=token), "token": token}
                if baseline_ref and action == "reject" and device in ("desktop", "mobile"):
                    original_translate = QuietAcceptanceHandler.translate_path
                    def baseline_translate(handler, path):
                        name = urlparse(path).path.lstrip("/") or "index.html"
                        return str(baseline / name) if name in ("index.html", "app.js", "styles.css") else original_translate(handler, path)
                    with mock.patch.object(QuietAcceptanceHandler, "translate_path", baseline_translate):
                        open_dialog(browser, fixture, auth, device, subject, action)
                        for kind in ("application", "source", "attachments", "editor"):
                            selector = '[data-decision-evidence="' + kind + '"]'
                            browser.click_visible(selector)
                            browser.until("document.querySelector(" + json.dumps(selector) + ").classList.contains('complete')")
                        before = browser.evaluate("['officialReviewOriginal','officialReviewAttachments','officialReviewEdited'].map(id=>({id,disabled:document.getElementById(id).disabled,visible:!!document.getElementById(id).getClientRects().length}))")
                        if not all(row["disabled"] and not row["visible"] for row in before):
                            raise AssertionError("baseline_review_block_not_reproduced")
                        browser.run("screenshot", str(output / (device + "-reject-before.png")), "--full")
                        report["beforeAfter"].append({"device": device, "action": action, "sameDocumentId": doc_id, "baselineRef": baseline_ref, "beforeReviewControls": before, "afterScreenshot": device + "-reject-confirm.png"})
                open_dialog(browser, fixture, auth, device, subject, action)
                if action == "decline" and browser.evaluate("document.activeElement.id") != "officialDecisionCancelBtn":
                    raise AssertionError("destructive_dialog_initial_focus_not_cancel")
                if action == "withdraw":
                    browser.run("fill", "#officialWithdrawComment", "合成驗收抽單修改申請內容。")
                else:
                    for kind in ("application", "source", "attachments", "editor"):
                        evidence_selector = '[data-decision-evidence="' + kind + '"]'
                        browser.click_visible(evidence_selector)
                        browser.until("document.querySelector(" + json.dumps(evidence_selector) + ").classList.contains('complete')")
                        if kind != "application":
                            name = {"source": "officialReviewOriginal", "attachments": "officialReviewAttachments", "editor": "officialReviewEdited"}[kind]
                            browser.click_visible('label:has(#' + name + ')')
                            if not browser.evaluate("document.querySelector('#" + name + "').checked"):
                                raise AssertionError("manual_review_acknowledgement_not_checked")
                    if action == "reject":
                        browser.run("select", "#officialRejectCategory", "content_error")
                        browser.run("fill", "#officialRejectComment", "合成驗收請補正申請內容與附件。")
                    else:
                        browser.run("fill", "#officialApprovalComment", "合成驗收判斷理由及處理原因。")
                browser.until("!document.querySelector('#officialDecisionSubmitBtn').disabled")
                browser.run("screenshot", str(output / (device + "-" + action + "-confirm.png")), "--full")
                browser.click_visible("#officialDecisionSubmitBtn")
                browser.until("!document.querySelector('#officialDecisionModal').getClientRects().length")
                result = fixture._expect_json("GET", f"/api/official-documents/{doc_id}", 200, token=token)
                if action == "decline" and (result["current_status"] != "declined" or result["available_actions"]):
                    raise AssertionError("terminal_result_or_permissions_mismatch")
                if action == "withdraw" and result["current_status"] != "draft": raise AssertionError("withdraw_not_draft")
                if action == "return-previous" and result["current_step"] != first_step: raise AssertionError("previous_step_not_reactivated")
                if action == "approve" and (result["current_step"] == first_step or result["approval_steps"][0]["status"] != "approved"): raise AssertionError("approval_not_advanced")
                if action == "reject" and result["current_status"] != "rejected": raise AssertionError("correction_not_available")
                browser.run("screenshot", str(output / (device + "-" + action + "-result.png")), "--full")
                layout = browser.evaluate(AUDIT_JS)
                if layout["overflow"]: raise AssertionError("browser_horizontal_overflow")
                report["rows"].append({"device": device, "action": action, "status": "passed", "resultStatus": result["current_status"], "layout": layout})
                print(json.dumps({"device": device, "action": action, "status": "passed"}), flush=True)
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["errorCode"] = str(error) if isinstance(error, AssertionError) or str(error).startswith("browser_") else type(error).__name__
        browser.run("screenshot", str(output / "failure.png"), "--full")
        report["failureState"] = browser.evaluate("({route:document.querySelector('.view.active')?.id,modal:document.querySelector('#officialDecisionModal')?.innerText,error:document.querySelector('#officialDecisionError')?.innerText,detail:document.querySelector('#approvalLogDetail')?.innerText})")
    finally:
        browser.run("close")
        header_patch.stop()
        fixture.tearDownClass()
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-ref")
    args = parser.parse_args()
    result = audit(args.output.resolve(), args.baseline_ref)
    print(json.dumps({"status": result["status"], "report": str(args.output / "report.json")}))
    raise SystemExit(0 if result["status"] == "passed" else 1)
