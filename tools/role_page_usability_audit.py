"""Local-only role usability probes; synthetic data, never production writes."""
from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.six_role_browser_acceptance import Browser, AUDIT_JS, require_local_origin
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest


def run(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    fixture = FiveAccountHttpAcceptanceTest
    fixture.setUpClass()
    require_local_origin(fixture.origin)
    config = Path(fixture.tmp.name) / "usability-browser.json"
    config.write_text(json.dumps({"allowedDomains": ["127.0.0.1", "fonts.googleapis.com", "fonts.gstatic.com"], "headed": False}))
    browser = Browser(config)
    report = {"scope": "isolated_synthetic_fixture_not_production_or_google_login", "probes": []}

    def login(auth, route="dashboard", width=390):
        browser.run("open", fixture.origin + "/assets/favicon-32.png")
        browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
        browser.run("set", "viewport", str(width), "844" if width < 700 else "1000")
        browser.run("open", fixture.origin + "/#" + route)
        browser.until("typeof hasAuthenticatedBackendSession==='function'&&hasAuthenticatedBackendSession()&&document.querySelector('.view.active')?.id===" + json.dumps(route))
        browser.until("!document.querySelector('#moduleEntryProgress')?.getClientRects().length")

    def capture(name):
        browser.run("screenshot", str(output / (name + ".png")))
        return name + ".png"

    def flush():
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))

    try:
        staff = isolated_browser_session(fixture, "staff", entity_id="E1")
        ga = isolated_browser_session(fixture, "ga_chief", entity_id="E1")
        ceo = isolated_browser_session(fixture, "ceo", entity_id="E1")
        login(ga, "inbound")
        browser.click_visible("#openInboundArchiveBtn")
        browser.until("document.querySelector('[data-inbound-section-panel=archive]').hidden===false")
        report["probes"].append({"case": "archive-empty", "receivedDate": browser.evaluate("document.querySelector('#inboundArchiveReceivedDate').value"), "attachmentAccept": browser.evaluate("document.querySelector('#inboundArchiveFiles').accept"), "attachmentHint": browser.evaluate("document.querySelector('#inboundArchiveFiles').parentElement.innerText"), "screenshot": capture("ga-mobile-archive-empty")})
        flush()
        browser.run("fill", "#inboundArchiveSenderName", "隔離驗收來文單位")
        browser.run("fill", "#inboundArchiveSubject", "隔離派發流程驗收文件")
        browser.run("fill", "#inboundArchiveBody", "純合成資料；僅於暫存 SQLite 執行，不寄正式郵件。")
        browser.click_visible("#inboundArchiveSubmitBtn")
        browser.until("!document.querySelector('#inboundArchiveSubmitBtn').disabled")
        report["probes"].append({"case": "archive-submit-result", "toast": browser.evaluate("document.querySelector('#toast').textContent"), "form": browser.evaluate("({sender:document.querySelector('#inboundArchiveSenderName').value,subject:document.querySelector('#inboundArchiveSubject').value,section:inboundSection})"), "listReflectsCreatedRecord": browser.evaluate("document.querySelector('#inboundRows').innerText.includes('隔離派發流程驗收文件')"), "inMemoryRecordCount": browser.evaluate("inboundDocs.length"), "recordScope": browser.evaluate("({role:activeRole(),unit:activeUnit(),rows:inboundDocs.map(x=>({owner:x.owner,dept:x.dept,visible:canSeeDepartmentDoc(x)}))})"), "screenshot": capture("ga-mobile-archive-submit-result")})
        flush()
        # A fresh second role must load the saved record without opening any
        # maintenance page or injecting rows into browser state.
        login(ceo, "inbound")
        report["dispatchActor"] = "ceo"
        time.sleep(.7)
        preloaded = browser.evaluate("document.querySelector('#inboundRows').innerText.includes('隔離派發流程驗收文件')")
        report["probes"].append({"case": "fresh-inbound-load", "actor": report["dispatchActor"], "visibleWithoutMaintenanceSync": preloaded, "backendRecordCount": len(fixture._expect_json("GET", "/api/inbound-documents", 200, token=(ceo if report["dispatchActor"] == "ceo" else ga)["token"])), "screenshot": capture("fresh-inbound-load")})
        if not preloaded:
            # Existing maintenance loader is a documented fixture workaround,
            # not evidence that the normal inbound entry loaded correctly.
            browser.evaluate("(async()=>{await syncDatabaseFromBackend(true);return true})()")
            report["maintenanceSyncWorkaroundRequired"] = True
        flush()
        browser.until("document.querySelector('#inboundRows').innerText.includes('隔離派發流程驗收文件')")
        report["probes"].append({"case": "archive-created", "recordText": browser.evaluate("document.querySelector('#inboundRows').innerText"), "screenshot": capture("ga-mobile-archive-created")})
        browser.evaluate("document.querySelector('#inboundRows tr').scrollIntoView({block:'center',behavior:'instant'});true")
        report["probes"].append({"case": "inbound-mobile-record-card", "columnsFit": browser.evaluate("[...document.querySelectorAll('#inboundRows td')].every(e=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1})"), "tableMinWidth": browser.evaluate("getComputedStyle(document.querySelector('.inbound-list-panel table')).minWidth"), "layout": browser.evaluate(AUDIT_JS), "screenshot": capture("inbound-mobile-record-card")})
        browser.run("set", "viewport", "1440", "1000")
        report["probes"].append({"case": "inbound-desktop-record-table", "tableMinWidth": browser.evaluate("getComputedStyle(document.querySelector('.inbound-list-panel table')).minWidth"), "headerVisible": browser.evaluate("!!document.querySelector('.inbound-list-panel thead').getClientRects().length"), "layout": browser.evaluate(AUDIT_JS), "screenshot": capture("inbound-desktop-record-table")})
        browser.run("set", "viewport", "390", "844")
        if browser.evaluate("!!document.querySelector('#inboundReloadBtn')"):
            browser.evaluate("window.__inboundOriginalFetch=window.fetch;window.fetch=async function(input,init){if(String(input).endsWith('/api/inbound-documents'))return new Response(JSON.stringify({error:'server_error',detail:'internal_server_error',errorId:'ERR-FIXTURE-LOAD'}),{status:503,headers:{'Content-Type':'application/json'}});return window.__inboundOriginalFetch(input,init)};true")
            browser.click_visible("#inboundReloadBtn")
            browser.until("inboundDocumentLoadState.status==='error'")
            report["probes"].append({"case": "inbound-load-failure", "notice": browser.evaluate("document.querySelector('#inboundLoadNotice').innerText"), "count": browser.evaluate("document.querySelector('#inboundCount').innerText"), "retainedRecord": browser.evaluate("document.querySelector('#inboundRows').innerText.includes('隔離派發流程驗收文件')"), "screenshot": capture("ceo-mobile-inbound-load-error")})
            browser.evaluate("window.fetch=window.__inboundOriginalFetch;true")
            browser.click_visible("#inboundReloadBtn")
            browser.until("inboundDocumentLoadState.status==='loaded'")
            report["probes"].append({"case": "inbound-load-retry", "noticeHidden": browser.evaluate("document.querySelector('#inboundLoadNotice').hidden"), "visibleRecord": browser.evaluate("document.querySelector('#inboundRows').innerText.includes('隔離派發流程驗收文件')"), "screenshot": capture("ceo-mobile-inbound-load-retry")})
            flush()
        browser.click_visible('[data-inbound-section="dispatch"]')
        browser.until("document.querySelectorAll('.internal-dispatch-recipient-check').length>0")
        document_id = browser.evaluate("[...document.querySelector('#internalDispatchDocumentSelect').options].find(e=>e.textContent.includes('隔離派發流程驗收文件')).value")
        browser.run("select", "#internalDispatchDocumentSelect", document_id)
        recipient_selector = '.internal-dispatch-recipient-check[value="' + staff["user"]["id"] + '"]'
        browser.evaluate("document.querySelector(" + json.dumps(recipient_selector) + ").scrollIntoView({block:'center'});true")
        browser.run("check", recipient_selector)
        report["probes"].append({"case": "dispatch-form", "prefilledTitle": browser.evaluate("document.querySelector('#internalDispatchTitleInput').value"), "prefilledBody": browser.evaluate("document.querySelector('#internalDispatchBodyInput').value"), "recipientSelectFontSizes": browser.evaluate("[...document.querySelectorAll('.internal-dispatch-recipient-action')].map(e=>parseFloat(getComputedStyle(e).fontSize))"), "layout": browser.evaluate(AUDIT_JS), "screenshot": capture("ga-mobile-dispatch-filled")})
        # Slow only this local request so a realistic double tap happens before completion.
        browser.evaluate("window.__dispatchPosts=0;window.__originalFixtureFetch=window.fetch;window.fetch=async function(input,init){if(String(input).endsWith('/api/internal-dispatches')&&init?.method==='POST'){window.__dispatchPosts++;await new Promise(r=>setTimeout(r,700));}return window.__originalFixtureFetch(input,init)};true")
        browser.click_visible("#internalDispatchSubmitBtn")
        immediately_disabled = browser.evaluate("document.querySelector('#internalDispatchSubmitBtn').disabled")
        if not immediately_disabled:
            browser.run("click", "#internalDispatchSubmitBtn")
        browser.until("internalDispatchItems.length>0")
        time.sleep(1.3)
        dispatches = fixture._expect_json("GET", "/api/internal-dispatches", 200, token=(ceo if report["dispatchActor"] == "ceo" else ga)["token"])
        matches = [item for item in dispatches if item.get("inbound_document_id") == document_id]
        report["probes"].append({"case": "dispatch-double-tap", "buttonDisabledDuringRequest": immediately_disabled, "postCount": browser.evaluate("window.__dispatchPosts"), "persistedDispatchCount": len(matches), "screenshot": capture("ga-mobile-dispatch-result")})
        flush()

        login(staff)
        time.sleep(1)
        staff_dispatches = fixture._expect_json("GET", "/api/internal-dispatches", 200, token=staff["token"])
        task_buttons = browser.evaluate("[...document.querySelectorAll('#dailyActionGrid button')].map(e=>({text:e.textContent.trim(),id:e.dataset.workItemId,attributes:[...e.attributes].map(x=>[x.name,x.value])}))")
        report["probes"].append({"case": "staff-received-dashboard", "apiDispatchCount": len(staff_dispatches), "buttons": task_buttons, "screenshot": capture("staff-mobile-received-dashboard")})
        visible_dispatch_action = browser.evaluate("[...document.querySelectorAll('#dailyActionGrid button')].find(e=>(e.innerText+' '+(e.closest('article')?.innerText||'')).includes('隔離派發流程驗收文件'))?.outerHTML||null")
        if visible_dispatch_action:
            selector = "#dailyActionGrid button"
            browser.click_visible(selector)
            time.sleep(.7)
        report["probes"].append({"case": "staff-open-dispatch-from-home", "activeRoute": browser.evaluate("document.querySelector('.view.active')?.id"), "activeInboundSection": browser.evaluate("inboundSection"), "dispatchTabHidden": browser.evaluate("document.querySelector('[data-inbound-section=dispatch]').hidden"), "dispatchPanelHidden": browser.evaluate("document.querySelector('[data-inbound-section-panel=dispatch]').hidden"), "replyVisible": browser.evaluate("!!document.querySelector('#internalDispatchReplyForm')?.getClientRects().length"), "screenshot": capture("staff-mobile-open-dispatch")})
        flush()

        browser.run("open", fixture.origin + "/#inbound")
        browser.until("typeof internalDispatchItems!=='undefined'&&internalDispatchItems.length>0")
        tab_hidden = browser.evaluate("document.querySelector('[data-inbound-section=dispatch]').hidden")
        if not tab_hidden:
            browser.click_visible('[data-inbound-section="dispatch"]')
            browser.until("!!document.querySelector('#internalDispatchReplyForm')?.getClientRects().length")
            browser.run("fill", "#internalDispatchReplyText", "已收到隔離驗收公文，合成流程確認完成。")
            browser.click_visible('#internalDispatchReplyForm button[type="submit"]')
            browser.until("!document.querySelector('#internalDispatchReplyForm')")
            detail = fixture._expect_json("GET", "/api/internal-dispatches/" + staff_dispatches[0]["id"], 200, token=staff["token"])
            report["probes"].append({"case": "staff-dispatch-reply", "tabVisible": True, "createAreaHidden": browser.evaluate("document.querySelector('#internalDispatchCreateArea').hidden"), "replyPersisted": any(item.get("reply_text") == "已收到隔離驗收公文，合成流程確認完成。" for item in detail.get("replies", [])), "screenshot": capture("staff-mobile-dispatch-replied")})
        else:
            report["probes"].append({"case": "staff-dispatch-reply", "tabVisible": False, "replyPersisted": False, "screenshot": capture("staff-mobile-dispatch-blocked")})
        flush()

        login(staff, "approvalLog")
        before = browser.evaluate("({route:document.querySelector('.view.active').id,buttonDisabled:document.querySelector('#approvalLogOpenWorkflowBtn').disabled,list:document.querySelector('#approvalLogList').innerText})")
        if not before["buttonDisabled"]:
            browser.click_visible("#approvalLogOpenWorkflowBtn")
        report["probes"].append({"case": "empty-approval-view-action", "before": before, "afterRoute": browser.evaluate("document.querySelector('.view.active').id"), "toast": browser.evaluate("document.querySelector('#toast').textContent"), "screenshot": capture("staff-mobile-empty-approval-action")})
        browser.evaluate("document.querySelector('[data-approval-log-filter=my_pending]').focus();true")
        browser.run("press", "ArrowRight")
        report["probes"].append({"case": "approval-tab-keyboard", "activeFilter": browser.evaluate("approvalLogFilter"), "focusedFilter": browser.evaluate("document.activeElement.dataset.approvalLogFilter||null"), "tabs": browser.evaluate("[...document.querySelectorAll('[data-approval-log-filter]')].map(e=>({key:e.dataset.approvalLogFilter,role:e.getAttribute('role'),selected:e.getAttribute('aria-selected'),tabindex:e.getAttribute('tabindex')}))")})
        browser.run("press", "End")
        end_filter = browser.evaluate("approvalLogFilter")
        browser.run("press", "Home")
        report["probes"].append({"case": "approval-tab-home-end", "endFilter": end_filter, "homeFilter": browser.evaluate("approvalLogFilter")})
        flush()
        return report
    except Exception as error:
        report["failure"] = {"error": str(error) if str(error).startswith("browser_") else type(error).__name__, "toast": browser.evaluate("document.querySelector('#toast')?.textContent"), "active": browser.evaluate("document.querySelector('.view.active')?.id"), "screenshot": capture("failed")}
        flush()
        raise
    finally:
        browser.run("close")
        fixture.tearDownClass()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with open("/tmp/edoc-six-role-browser.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = run(args.output)
    print(json.dumps({"scope": result["scope"], "probes": len(result["probes"]), "report": str(args.output / "report.json")}))
