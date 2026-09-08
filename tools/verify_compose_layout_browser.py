"""Local compose-layout acceptance using synthetic identities and real browser DOM.

Optional --source-root serves a frozen frontend for an equivalent before capture.
The API always uses this checkout's isolated temporary SQLite test fixture.
No production account, external provider, submission, or seal operation is used.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import sys
import time
from unittest import mock
from urllib.parse import urlparse


def run(root: Path, output: Path, phase: str, source_root: Path | None = None, *, save_flow: bool = False) -> dict:
    sys.path.insert(0, str(root))
    from tools.six_role_browser_acceptance import AUDIT_JS, Browser, TELEMETRY, require_local_origin
    from tests.support.five_account_browser_fixture import isolated_browser_session
    from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler

    output.mkdir(parents=True, exist_ok=True)
    frontend = source_root or root
    fixture = FiveAccountHttpAcceptanceTest
    original_head = QuietAcceptanceHandler.send_head

    def frontend_head(handler):
        name = urlparse(handler.path).path
        mapping = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/styles.css": "styles.css"}
        if name in mapping:
            filename = mapping[name]
            source = (frontend / filename).read_text(encoding="utf-8")
            if filename == "index.html":
                source = source.replace("<head>", "<head>" + TELEMETRY, 1)
            data = source.encode()
            handler.send_response(200)
            handler.send_header("Content-Type", {"index.html": "text/html", "app.js": "text/javascript", "styles.css": "text/css"}[filename] + "; charset=utf-8")
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            return io.BytesIO(data)
        return original_head(handler)

    report = {"scope": "isolated_local_synthetic_no_submission", "phase": phase, "rows": []}
    with mock.patch.object(QuietAcceptanceHandler, "send_head", frontend_head):
        fixture.setUpClass()
        require_local_origin(fixture.origin)
        config = Path(fixture.tmp.name) / "compose-browser.json"
        config.write_text(json.dumps({"allowedDomains": ["127.0.0.1", "fonts.googleapis.com", "fonts.gstatic.com"], "headed": False}))
        browser = Browser(config, session="compose-layout-" + phase, namespace="edoc-compose-layout")

        def require(condition, code):
            if not condition:
                raise AssertionError(code)

        def capture(selector, filename, *, full=False):
            browser.evaluate("document.querySelector(" + json.dumps(selector) + ").scrollIntoView({block:'center',behavior:'instant'});true")
            args = ["screenshot", str(output / filename)]
            if full:
                args.append("--full")
            browser.run(*args)

        def set_date(value):
            browser.evaluate("(()=>{const e=document.querySelector('#dispatchDate');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e," + json.dumps(value) + ");e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));return e.value})()")

        def save_and_read(auth):
            browser.click_visible("#saveDispatchDraftBtn")
            browser.until("['saved','error'].includes(composeSaveState.tone)", timeout=40)
            require(browser.evaluate("composeSaveState.tone==='saved'"), "draft_save_failed")
            document_id = browser.evaluate("dispatchDocs.find(e=>e.id===currentComposeDraftId)?.officialDocumentId")
            require(bool(document_id), "saved_document_id_missing")
            detail = fixture._expect_json("GET", f"/api/official-documents/{document_id}", 200, token=auth["token"])
            require(detail["id"] == document_id, "saved_document_id_mismatch")
            return detail

        def verify_saved_draft(auth, device):
            browser.run("select", "#composeOutputMode", "electronic")
            set_date("2026-09-15")
            browser.until("document.querySelectorAll('#draftPreview .draft-seal-placeholder').length===0")
            first = save_and_read(auth)
            number = first.get("dispatch_no")
            require(bool(number) and "儲存" not in number, "backend_number_missing")
            require(first.get("dispatch_date") == "2026-09-15", "first_saved_date_mismatch")
            require(first.get("output_mode") == "electronic", "first_saved_output_mode_mismatch")
            require(browser.evaluate("document.querySelector('#dispatchNo').value") == number, "visible_number_mismatch")
            require(browser.evaluate("document.querySelector('#dispatchNo').readOnly"), "saved_number_not_readonly")
            set_date("2026-09-16")
            browser.until("document.querySelector('#draftPreview').textContent.includes('115年9月16日')")
            second = save_and_read(auth)
            require(second.get("id") == first["id"], "second_save_created_another_document")
            require(second.get("dispatch_no") == number, "second_save_reallocated_number")
            require(second.get("dispatch_date") == "2026-09-16", "second_saved_date_mismatch")
            require(second.get("output_mode") == "electronic", "second_saved_output_mode_mismatch")
            # This invokes the same authorized loader as Edit draft and performs a fresh API GET.
            browser.evaluate("(async()=>{await beginOfficialCorrection(officialWorkflowItems.find(e=>e.id===" + json.dumps(first["id"]) + "));return true})()")
            browser.until("document.querySelector('#dispatchDate').value==='2026-09-16'&&document.querySelector('#composeOutputMode').value==='electronic'")
            require(browser.evaluate("document.querySelector('#dispatchNo').value") == number, "reopened_number_mismatch")
            require(browser.evaluate("document.querySelector('#dispatchNo').readOnly&&document.querySelector('#composeSealFields').hidden"), "reopened_number_or_output_controls_mismatch")
            capture("#dispatchDate", f"{phase}-{device}-saved-draft-reopened.png")
            browser.click_visible("#composeNextBtn")
            browser.until("document.querySelector('[data-compose-pane=confirm]')?.classList.contains('active')")
            require(browser.evaluate("document.querySelector('#draftReviewPreview').textContent.includes('115年9月16日')"), "confirmation_date_mismatch")
            require(browser.evaluate("document.querySelectorAll('#draftReviewPreview .draft-seal-placeholder').length===0"), "confirmation_electronic_has_seals")
            final = fixture._expect_json("GET", f"/api/official-documents/{first['id']}", 200, token=auth["token"])
            require(final.get("current_status") == "draft", "confirmation_submitted_document")
            require(final.get("dispatch_no") == number, "confirmation_reallocated_number")
            capture("#draftReviewPreview", f"{phase}-{device}-saved-draft-confirmation.png")
            return {
                "documentId": first["id"], "dispatchNo": number,
                "firstDate": first["dispatch_date"], "secondDate": second["dispatch_date"],
                "sameDocumentAndNumber": True, "savedOutputMode": second["output_mode"],
                "reopenedFieldsMatched": True, "confirmationOpened": True,
                "finalStatus": final["current_status"], "noSubmission": True,
            }

        try:
            auth = isolated_browser_session(fixture, "staff")
            for device, dimensions in (("desktop", (1440, 1000)), ("mobile", (390, 844))):
                browser.run("set", "viewport", *map(str, dimensions))
                browser.run("open", fixture.origin + "/assets/favicon-32.png")
                browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                browser.run("open", fixture.origin + f"/?compose_layout_fixture={time.monotonic_ns()}#dashboard")
                browser.until("Boolean(window.__fixtureTiming?.appInteractiveMs)")
                browser.run("snapshot", "-i")
                require(browser.evaluate("document.body.innerText.trim().length>0&&!document.querySelector('[data-nextjs-dialog],.vite-error-overlay')"), "page_verification_failed")
                browser.run("screenshot", str(output / f"{phase}-{device}-home.png"))
                if device == "mobile":
                    browser.run("click", "#mobileMenuButton")
                    browser.until("Math.abs(document.querySelector('#primarySidebar').getBoundingClientRect().left)<0.5")
                browser.run("click", '.sidebar .nav-item[data-target="compose"]')
                browser.until("document.querySelector('.view.active')?.id==='compose'&&document.querySelector('#composeApprovalCategorySelect')?.options.length>1")
                category = browser.evaluate("[...document.querySelector('#composeApprovalCategorySelect').options].find(e=>e.textContent.includes('合作意向書')).value")
                browser.run("select", "#composeApprovalCategorySelect", category)
                values = {
                    "contactAddress": "110臺北市測試區測試路一段364巷6號1樓",
                    "contactOwner": "測試申請人", "contactPhone": "02-66045432 #999",
                    "contactFax": "N/A", "contactEmail": "fixtureapplicant@example.test",
                    "recipient": "隔離測試受文單位", "attachmentDetails": "附件一：申請資料；附件二：補充說明",
                    "documentPurpose": "辦理測試資料更新，請受文單位查照。本資料只用於隔離驗收。",
                    "subject": "有關測試資料更新一案，請查照。",
                    "bodyText": "一、本函僅供隔離驗收，不送簽、不寄發。\n二、請協助更新測試資料。",
                }
                for identity, value in values.items():
                    browser.run("fill", "#" + identity, value)
                browser.until("document.querySelector('#draftPreview')?.textContent.includes('有關測試資料更新一案')")
                row = {"device": device, "fixtureContent": "same_synthetic_compose_document"}
                capture("#composeForm", f"{phase}-{device}-compose-full.png", full=True)
                capture("#composeCompanySelect", f"{phase}-{device}-form-top.png")
                capture("#composeApprovalRoutePreview", f"{phase}-{device}-approval.png")
                capture("#draftPreview .draft-contact-block", f"{phase}-{device}-contact-preview.png")
                row["layout"] = browser.evaluate(AUDIT_JS)
                require(not row["layout"]["errors"], "browser_errors")
                if phase == "after":
                    require(not row["layout"]["overflow"], "document_overflow")
                    row["defaultDate"] = browser.evaluate("document.querySelector('#dispatchDate').value")
                    today = browser.evaluate("new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())")
                    require(row["defaultDate"] == today, "date_not_today")
                    # Browser CLI text typing does not reliably fill a segmented native date control.
                    # Exercise its native value setter and the same input/change events as the picker.
                    set_date("2026-09-15")
                    browser.until("document.querySelector('#draftPreview').textContent.includes('115年9月15日')")
                    row["customDatePreview"] = True
                    require(browser.evaluate("document.querySelector('#dispatchNo').readOnly&&!document.querySelector('#generateDispatchNoBtn')"), "number_editable_or_regeneration_present")
                    require(browser.evaluate("!document.querySelector('#format')&&!document.querySelector('#formatDocNo')"), "duplicate_format_form_remains")
                    row["aiButton"] = browser.evaluate("(()=>{const e=document.querySelector('#generateFromPurposeBtn'),s=getComputedStyle(e),r=e.getBoundingClientRect();return{text:e.textContent.trim(),background:s.backgroundColor,color:s.color,height:r.height}})()")
                    require(row["aiButton"]["text"] == "AI產生公文主旨與說明" and row["aiButton"]["color"] == "rgb(255, 255, 255)" and row["aiButton"]["height"] >= 44, "ai_button_style_mismatch")
                    browser.run("select", "#composeOutputMode", "electronic")
                    browser.until("document.querySelector('#composeSealFields').hidden&&document.querySelector('#largeSealType').disabled&&document.querySelector('#smallSealType').disabled")
                    browser.until("document.querySelectorAll('#draftPreview .draft-seal-placeholder').length===0")
                    require(browser.evaluate("document.querySelectorAll('#draftPreview .draft-seal-placeholder').length===0"), "electronic_preview_has_seals")
                    capture("#composeOutputMode", f"{phase}-{device}-electronic-no-seals.png")
                    row["electronicHasNoSealControlsOrPreview"] = True
                    browser.run("select", "#composeOutputMode", "physical")
                    browser.until("!document.querySelector('#composeSealFields').hidden&&!document.querySelector('#largeSealType').disabled")
                    row["physicalSealControlsRestored"] = True
                    row["approvalFlow"] = browser.evaluate("(()=>{const e=document.querySelector('#composeApprovalRoutePreview'),r=[...e.children].map(n=>n.getBoundingClientRect());return{display:getComputedStyle(e).display,clientWidth:e.clientWidth,scrollWidth:e.scrollWidth,top:r.map(n=>n.top),pageOverflow:document.documentElement.scrollWidth>innerWidth+1}})()")
                    require(row["approvalFlow"]["display"] == "flex" and len(set(round(x) for x in row["approvalFlow"]["top"])) == 1 and not row["approvalFlow"]["pageOverflow"], "approval_not_horizontal_or_overflow")
                    if device == "mobile":
                        require(row["approvalFlow"]["scrollWidth"] > row["approvalFlow"]["clientWidth"], "mobile_flow_has_no_local_scroll")
                    row["layoutAfterInteractions"] = browser.evaluate(AUDIT_JS)
                    require(not row["layoutAfterInteractions"]["errors"], "browser_errors_after_interaction")
                    if save_flow:
                        row["draftSaveFlow"] = verify_saved_draft(auth, device)
                        row["layoutAfterSaveFlow"] = browser.evaluate(AUDIT_JS)
                        require(not row["layoutAfterSaveFlow"]["errors"], "browser_errors_after_save_flow")
                        require(not row["layoutAfterSaveFlow"]["overflow"], "confirmation_document_overflow")
                row["status"] = "passed"
                report["rows"].append(row)
                (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
                print(json.dumps({"phase": phase, "device": device, "status": "passed"}), flush=True)
            report["status"] = "passed"
        except Exception as error:
            report["status"] = "failed"
            report["errorCode"] = str(error) if isinstance(error, AssertionError) or str(error).startswith("browser_") else type(error).__name__
            try:
                report["failureState"] = browser.evaluate("({active:document.querySelector('.view.active')?.id,errors:window.__fixtureErrors,date:document.querySelector('#dispatchDate')?.value,mode:document.querySelector('#composeOutputMode')?.value,overflow:document.documentElement.scrollWidth>innerWidth+1})")
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
    parser.add_argument("--phase", choices=("before", "after"), default="after")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--save-flow", action="store_true", help="Exercise local draft save, stable number, reopen, and confirmation without submission.")
    args = parser.parse_args()
    result = run(args.root.resolve(), args.output.resolve(), args.phase, args.source_root.resolve() if args.source_root else None, save_flow=args.save_flow)
    (args.output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({"status": result["status"], "report": str(args.output / "report.json")}), flush=True)
    raise SystemExit(0 if result["status"] == "passed" else 1)
