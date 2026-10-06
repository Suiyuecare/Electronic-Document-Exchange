"""Disposable GA -> employee -> CEO browser acceptance, no production writes."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.six_role_browser_acceptance import Browser, AUDIT_JS, VIEWPORTS, require_local_origin
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest


def login(browser, fixture, auth, device):
    browser.run("open", fixture.origin + "/assets/favicon-32.png")
    browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
    browser.run("set", "viewport", *map(str, VIEWPORTS[device]))
    browser.run("open", fixture.origin + "/#inbound")
    browser.until("typeof hasAuthenticatedBackendSession==='function'&&hasAuthenticatedBackendSession()&&document.querySelector('.view.active')?.id==='inbound'&&!document.querySelector('#moduleEntryProgress')?.getClientRects().length")
    browser.until("inboundDocumentLoadState.status==='loaded'")


def audit(output):
    fixture = FiveAccountHttpAcceptanceTest
    fixture.setUpClass()
    require_local_origin(fixture.origin)
    output.mkdir(parents=True, exist_ok=True)
    config = Path(fixture.tmp.name) / "readiness-browser.json"
    config.write_text(json.dumps({"headed": False}))
    browser = Browser(config, session="edoc-inbound", namespace="edoc-readiness")
    report = {"scope": "isolated_fixture", "realGoogleLoginVerified": False, "journeys": []}
    try:
        ga = isolated_browser_session(fixture, "ga_chief", entity_id="E1")
        employee = isolated_browser_session(fixture, "staff", entity_id="E1")
        ceo = isolated_browser_session(fixture, "ceo", entity_id="E1")
        for device in ("desktop", "mobile"):
            login(browser, fixture, ga, device)
            browser.click_visible('[data-inbound-section="archive"]')
            browser.run("fill", "#inboundArchiveSenderName", "去識別化驗收來文單位")
            subject = "收文派發回文驗收-" + device
            browser.run("fill", "#inboundArchiveSubject", subject)
            browser.run("fill", "#inboundArchiveBody", "合成收文資料，請於三日內完成測試回覆。")
            pdf = Path(fixture.tmp.name) / ("synthetic-inbound-" + device + ".pdf")
            pdf.write_bytes(fixture._make_attachment_pdf(900))
            browser.run("upload", "#inboundArchiveFiles", str(pdf))
            browser.click_visible("#inboundArchiveSubmitBtn")
            browser.until("inboundDocs.some(x=>x.subject===" + json.dumps(subject) + "&&x.status==='待分派'&&x.attachments.length===1)")
            inbound_id = browser.evaluate("inboundDocs.find(x=>x.subject===" + json.dumps(subject) + ").id")
            browser.click_visible('[data-inbound-section="records"]')
            browser.click_visible('[data-select-inbound="' + inbound_id + '"]')
            browser.click_visible('#inboundModal [data-inbound-action="assign"]')
            browser.until("inboundAssigneeCandidates.some(x=>x.id===" + json.dumps(employee["user"]["id"]) + ")")
            browser.run("select", "#assignOwner", employee["user"]["id"])
            due_date = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
            browser.evaluate("(()=>{const input=document.querySelector('#assignDueDate');input.value=" + json.dumps(due_date) + ";input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));return input.value})()")
            if not browser.evaluate("isValidFutureOrToday(document.querySelector('#assignDueDate').value)"):
                raise AssertionError("assignment_deadline_not_accepted")
            browser.click_visible('#assignForm button[type="submit"]')
            browser.until("inboundDocs.find(x=>x.id===" + json.dumps(inbound_id) + ")?.assigneeUserId===" + json.dumps(employee["user"]["id"]))
            browser.click_visible('[data-select-inbound="' + inbound_id + '"]')
            browser.click_visible('#inboundModal [data-inbound-action="internal-dispatch"]')
            browser.until("!document.querySelector('#inboundModal').getClientRects().length&&document.querySelector('.internal-dispatch-recipient-check:checked')?.value===" + json.dumps(employee["user"]["id"]))
            if browser.evaluate("document.querySelector('#internalDispatchTitleInput').value") != subject:
                raise AssertionError("dispatch_subject_not_prefilled")
            browser.click_visible("#internalDispatchSubmitBtn")
            browser.until("internalDispatchItems.some(x=>x.inbound_document_id===" + json.dumps(inbound_id) + ")")
            dispatch_id = browser.evaluate("internalDispatchItems.find(x=>x.inbound_document_id===" + json.dumps(inbound_id) + ").id")
            browser.run("screenshot", str(output / (device + "-ga-dispatched.png")), "--full")

            login(browser, fixture, employee, device)
            browser.click_visible('[data-inbound-section="dispatch"]')
            browser.until("internalDispatchItems.some(x=>x.id===" + json.dumps(dispatch_id) + ")")
            browser.click_visible('[data-internal-dispatch-id="' + dispatch_id + '"]')
            browser.until("Boolean(document.querySelector('#internalDispatchReplyText'))")
            browser.run("fill", "#internalDispatchReplyText", "已完成驗收回覆，相關測試資料已確認無誤。")
            browser.click_visible('#internalDispatchReplyForm button[type="submit"]')
            browser.until("internalDispatchItems.find(x=>x.id===" + json.dumps(dispatch_id) + ")?.reply_status==='completed'")
            detail = fixture._expect_json("GET", "/api/internal-dispatches/" + dispatch_id, 200, token=employee["token"])
            if not detail["recipients"][0]["read_at"] or not detail["replies"]:
                raise AssertionError("receipt_or_reply_not_persisted")
            attachment = detail["inbound_document"]["attachments"][0]
            original = fixture._request("GET", "/api/inbound-documents/" + inbound_id + "/attachments/" + attachment["id"] + "/download", token=employee["token"])
            if original.status != 200 or original.body != pdf.read_bytes():
                raise AssertionError("employee_source_attachment_not_downloadable_or_changed")
            browser.run("screenshot", str(output / (device + "-employee-replied.png")), "--full")

            login(browser, fixture, ceo, device)
            browser.click_visible('[data-inbound-section="dispatch"]')
            browser.until("internalDispatchItems.some(x=>x.id===" + json.dumps(dispatch_id) + ")")
            browser.click_visible('[data-internal-dispatch-id="' + dispatch_id + '"]')
            if not browser.evaluate("document.querySelector('#internalDispatchDetail').textContent.includes('已完成驗收回覆')"):
                raise AssertionError("supervisor_cannot_trace_reply")
            layout = browser.evaluate(AUDIT_JS)
            detail_overflow = browser.evaluate("[...document.querySelectorAll('#internalDispatchDetail .official-detail-grid dd')].filter(e=>e.scrollWidth>e.clientWidth+1).length")
            if layout["overflow"] or layout["errors"] or detail_overflow:
                raise AssertionError("browser_layout_or_runtime_error")
            browser.run("screenshot", str(output / (device + "-ceo-trace.png")), "--full")
            report["journeys"].append({"device": device, "status": "passed", "storedAttachmentCount": 1, "sourceAttachmentDownloadVerified": True, "receiptPersisted": True, "replyPersisted": True, "supervisorTraceVerified": True, "overflow": False, "detailValueOverflowCount": detail_overflow})
        return report
    except Exception as error:
        try:
            browser.run("screenshot", str(output / "failure.png"), "--full")
            print(json.dumps({"state": browser.evaluate("(()=>{const x=internalDispatchCurrentItem();return {view:document.querySelector('.view.active')?.id,section:inboundSection,toast:document.querySelector('.toast')?.textContent,userId:authState?.user?.id,dispatch:x&&{id:x.id,reply_required:x.reply_required,status:x.status,closed_at:x.closed_at,recipients:x.recipients},canReply:canReplyInternalDispatch(x)}})()"), "error": type(error).__name__}))
        except RuntimeError:
            print(json.dumps({"error": type(error).__name__}))
        raise
    finally:
        try:
            browser.run("close")
        finally:
            fixture.tearDownClass()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.output.resolve())
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
