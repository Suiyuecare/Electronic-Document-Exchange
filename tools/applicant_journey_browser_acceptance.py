"""Applicant A01-A06 regressions on disposable loopback data and real Chromium.

No hosted identity, government exchange, mail, production DB or real seals.
Fault injection only affects synthetic local fetches. No forced clicks or
disabled-control bypasses. DOM composition events are not physical IME proof.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from urllib.parse import urlparse
from unittest import mock

ROOT = Path(os.environ.get("EDOC_ACCEPTANCE_SOURCE_ROOT", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT))
import backend
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as Fixture, QuietAcceptanceHandler
from tests.support.five_account_browser_fixture import isolated_browser_session
from tools.ux_complete_browser_acceptance import BRIDGE, TELEMETRY, require_local_origin
import tools.backup_drill_browser_acceptance as transport


CONTACTS = ["contactAddress", "contactOwner", "contactEmail", "copyRecipients"]
DEVICES = [("desktop", 1440, 1000), ("tablet", 820, 1100), ("mobile", 390, 844)]


def browser_bridge():
    executable = os.environ.get("EDOC_TEST_BROWSER_PATH")
    if not executable:
        candidates = sorted((Path.home() / "Library/Caches/ms-playwright").glob(
            "chromium_headless_shell-*/chrome-headless-shell-mac-arm64/chrome-headless-shell"), reverse=True)
        if candidates:
            executable = str(candidates[0])
    bridge = BRIDGE
    if executable:
        bridge = bridge.replace("process.env.EDOC_TEST_BROWSER_PATH||process.argv[3]", json.dumps(executable))
    return bridge


def run(output: Path, devices=None, cases=None):
    output = output.resolve()
    os.chdir(ROOT)
    output.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 1, "scope": "loopback_synthetic_chromium", "humanSSOVerified": False,
              "hostedVerified": False, "physicalDeviceVerified": False, "externalRequestsAllowed": False,
              "governmentExchange": "DISABLED", "sourceRoot": str(ROOT), "cases": []}
    source_files = ("app.js", "index.html", "backend.py", "compose_resilience.py", "workspace_drafts.py")
    source_hashes = lambda: {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_files}
    report["sourceHashesAtStart"] = source_hashes()
    original_head = QuietAcceptanceHandler.send_head
    html = (ROOT / "index.html").read_bytes().replace(b"<head>", b"<head>" + TELEMETRY.encode(), 1)

    def head(handler):
        if urlparse(handler.path).path not in {"/", "/index.html"}:
            return original_head(handler)
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(html)))
        handler.end_headers()
        return io.BytesIO(html)

    def persist():
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))

    with mock.patch.object(QuietAcceptanceHandler, "send_head", head), mock.patch.object(transport, "PLAYWRIGHT_BRIDGE", browser_bridge()):
        Fixture.setUpClass()
        require_local_origin(Fixture.origin)
        browser = None
        try:
            auth = isolated_browser_session(Fixture, "staff", entity_id="E1")
            custodian = isolated_browser_session(Fixture, "ceo", entity_id="E1")
            Fixture._expect_json("PATCH", "/api/companies/CO-001/seal-policy", 200, token=custodian["token"], json_body={"owner_kind": "company"})
            browser = transport.LocalPlaywrightBrowser(Fixture.origin)

            def shot(row, suffix=""):
                name = row["device"] + "-" + row["case"] + suffix + ".png"
                browser.run("screenshot", str(output / name))
                row.setdefault("screenshots", []).append(name)

            def check(row, name, value):
                row.setdefault("checks", {})[name] = bool(value)

            def navigate(route):
                if browser.evaluate("innerWidth<768&&!document.body.classList.contains('mobile-navigation-open')"):
                    browser.click_visible("#mobileMenuButton")
                    browser.until("Math.abs(document.querySelector('#primarySidebar').getBoundingClientRect().left)<0.5")
                browser.click_visible('.sidebar .nav-item[data-target="' + route + '"]')
                browser.until("document.querySelector('.view.active')?.id===" + json.dumps(route))

            def login(width, height, route="compose"):
                browser.run("open", Fixture.origin + "/assets/favicon-32.png")
                browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                browser.run("set", "viewport", str(width), str(height))
                browser.run("open", Fixture.origin + "/?applicant=" + str(time.monotonic_ns()) + "#" + route)
                browser.until("window.__fixtureTiming?.appInteractiveMs&&document.querySelector('#composeApprovalCategorySelect').options.length>1", timeout=40)
                browser.until("!composeCloudOperation", timeout=20)

            def contact_values():
                return browser.evaluate("Object.fromEntries(" + json.dumps(CONTACTS) + ".map(id=>[id,document.getElementById(id).value]))")

            def open_contacts_if_collapsed():
                if browser.evaluate("!document.querySelector('#contactAddress').getClientRects().length"):
                    browser.click_visible("#composeContactToggleBtn")

            def fill_valid(title, mode="electronic"):
                category = browser.evaluate("[...document.querySelector('#composeApprovalCategorySelect').options].find(e=>e.textContent.includes('服務委託合約')).value")
                browser.run("select", "#composeApprovalCategorySelect", category)
                browser.run("select", "#composeOutputMode", mode)
                open_contacts_if_collapsed()
                for selector, value in {
                    "#recipient": "合成驗收受文機關", "#subject": title,
                    "#bodyText": "這是本機隔離驗收使用的合成說明，不寄送至真實機關。",
                    "#contactAddress": "合成地址一號", "#contactOwner": "合成申請人",
                    "#contactPhone": "02-66045432 #123", "#contactEmail": "fixture@example.invalid",
                }.items():
                    browser.run("fill", selector, value)

            def wait_cloud():
                browser.until("!!composeCloudDraftId&&!composeCloudOperation&&composeSaveState.title==='私人雲端草稿已保存'", timeout=25)
                return browser.evaluate("composeCloudDraftId")

            def database_state():
                with sqlite3.connect(backend.DB_PATH) as conn:
                    conn.row_factory = sqlite3.Row
                    return {
                        "documents": [dict(x) for x in conn.execute("SELECT id,dispatch_no,subject,current_status FROM official_documents WHERE applicant_id=? ORDER BY id", (auth["user"]["id"],))],
                        "draftIds": [x[0] for x in conn.execute("SELECT id FROM official_document_compose_drafts WHERE applicant_id=? ORDER BY id", (auth["user"]["id"],))],
                        "numbers": [dict(x) for x in conn.execute("SELECT document_id,dispatch_no FROM official_document_number_allocations WHERE applicant_id=? ORDER BY document_id", (auth["user"]["id"],))],
                        "counters": [tuple(x) for x in conn.execute("SELECT date_key,last_serial FROM official_document_number_counters ORDER BY date_key")],
                    }

            def no_new_rows(before, after):
                return (before["draftIds"] == after["draftIds"] and before["numbers"] == after["numbers"]
                        and before["counters"] == after["counters"]
                        and [x["id"] for x in before["documents"]] == [x["id"] for x in after["documents"]])

            def ui_state():
                return browser.evaluate("({route:activeRouteTarget,hash:location.hash,step:activeComposeStep,subject:document.querySelector('#subject').value,number:document.querySelector('#dispatchNo').value,nextEnabled:!!document.querySelector('#composeNextBtn').getClientRects().length&&!document.querySelector('#composeNextBtn').disabled,status:composeSaveState,selected:typeof selectedOfficialDocumentId==='undefined'?'':selectedOfficialDocumentId})")

            def a01(row, storage_blocked=False):
                # Keep a real in-app predecessor so Back tests SPA history,
                # not the fixture login bootstrap's favicon document.
                navigate("dashboard")
                navigate("compose")
                title = "合成已送出公文返回保護 " + row["device"] + (" storage" if storage_blocked else "")
                fill_valid(title)
                wait_cloud()
                if storage_blocked:
                    browser.evaluate("Object.defineProperty(sessionStorage,'setItem',{configurable:true,value(){throw new DOMException('synthetic quota','QuotaExceededError')}});true")
                browser.click_visible("#composeNextBtn")
                browser.until("activeComposeStep==='confirm'", timeout=45)
                official_id = browser.evaluate("dispatchDocs.find(d=>d.id===currentComposeDraftId)?.officialDocumentId")
                browser.click_visible("#submitDispatchBtn")
                browser.until("!document.querySelector('#composeSubmitModal').classList.contains('hidden')")
                browser.click_visible("#composeSubmitConfirmBtn")
                browser.until("!composeSubmitInFlight&&document.querySelector('#composeSubmitModal').classList.contains('hidden')", timeout=45)
                submitted = Fixture._expect_json("GET", "/api/official-documents/" + official_id, 200, token=auth["token"])
                check(row, "submittedAuthoritatively", submitted["current_status"] not in {"draft", "rejected"})
                before = database_state()
                row["submittedId"] = official_id
                row["beforeHistory"] = before
                row["historyStates"] = []
                for action in ("back", "forward", "reload"):
                    if action == "reload":
                        browser.run("open", Fixture.origin + browser.evaluate("location.pathname+location.search+location.hash"))
                        browser.until("window.__fixtureTiming?.appInteractiveMs", timeout=40)
                    else:
                        browser.evaluate("history." + action + "();true")
                    time.sleep(1.1)
                    state = ui_state()
                    row["historyStates"].append({"action": action, **state})
                    check(row, action + "CannotEditSubmittedContents", not (state["route"] == "compose" and state["subject"] == title and state["nextEnabled"]))
                    check(row, action + "NoNewDocumentDraftOrNumber", no_new_rows(before, database_state()))
                    if action in {"forward", "reload"}:
                        check(row, action + "KeepsCaseRoute", state["route"] == "approvalLog")
                    if action in {"forward", "reload"} and state["route"] == "approvalLog":
                        browser.until("!officialCaseNavigation.loading", timeout=20)
                        check(row, action + "ShowsSameAuthorizedCase", browser.evaluate("officialCaseNavigation.detail?.id===" + json.dumps(official_id) + "&&!officialCaseNavigation.error"))
                    if action == "back" and state["route"] == "compose" and state["subject"] == title and state["nextEnabled"]:
                        browser.click_visible("#composeNextBtn")
                        time.sleep(1.5)
                        check(row, "backExposedNextCannotAllocate", no_new_rows(before, database_state()))
                # If a regression exposes a genuinely enabled next button, use
                # the ordinary click to demonstrate whether it allocates again.
                state = ui_state()
                if state["route"] == "compose" and state["subject"] == title and state["nextEnabled"]:
                    browser.click_visible("#composeNextBtn")
                    time.sleep(1.5)
                    check(row, "exposedNextStillCannotAllocate", no_new_rows(before, database_state()))
                shot(row, "-history")
                navigate("drafts")
                browser.until("!workspaceDraftState.loading")
                before_new = database_state()
                browser.click_visible("#draftNewComposeBtn")
                browser.until("activeRouteTarget==='compose'", timeout=20)
                time.sleep(.8)
                check(row, "explicitNewHasBlankContent", browser.evaluate("!document.querySelector('#subject').value&&!document.querySelector('#bodyText').value&&!document.querySelector('#dispatchNo').value"))
                check(row, "explicitBlankNewDoesNotResaveSubmittedContents", no_new_rows(before_new, database_state()))
                row["afterHistory"] = database_state()
                original_after = next(x for x in row["afterHistory"]["documents"] if x["id"] == official_id)
                original_before = next(x for x in before["documents"] if x["id"] == official_id)
                check(row, "submittedRecordRemainsUnchanged", original_after == original_before)

            def a02(row):
                initial = contact_values()
                row["initial"] = initial
                check(row, "initialAuthoritativeNameAndEmail", initial["contactOwner"] == auth["user"]["name"] and initial["contactEmail"] == auth["user"]["email"])
                expected_company = browser.evaluate("(()=>{const name=composeCompanySelect.value,c=companyRegistry.find(x=>x.name===name);return {name,address:c?.address||authState.user.company_address||''}})()")
                row["expectedCompany"] = expected_company
                check(row, "initialAddressAndCopyMatchSelectedCompany", bool(expected_company["address"]) and initial["contactAddress"] == expected_company["address"] and initial["copyRecipients"] == expected_company["name"])
                browser.run("fill", "#subject", "合成舊私人草稿預設值保存 " + row["device"])
                browser.run("fill", "#bodyText", "合成舊稿內容應保留，另開新稿不沿用手動寄件值。")
                open_contacts_if_collapsed()
                for selector, value in {"#contactOwner": "合成手動承辦人", "#contactAddress": "合成手動地址", "#contactEmail": "manual@example.invalid", "#copyRecipients": "合成手動副本"}.items():
                    browser.run("fill", selector, value)
                draft_id = wait_cloud()
                navigate("drafts")
                browser.until("!workspaceDraftState.loading")
                browser.click_visible("#draftNewComposeBtn")
                browser.until("activeRouteTarget==='compose'&&!document.querySelector('#subject').value")
                current = contact_values()
                row["new"] = current
                check(row, "newAuthoritativeDefaultsRestored", current == initial)
                payload = browser.evaluate("(()=>{const p=composePayload();return {contactAddress:p.contactAddress,contactOwner:p.contactOwner,contactEmail:p.contactEmail,copyRecipients:p.copyRecipients}})()")
                row["payload"] = payload
                check(row, "visibleAndPayloadMatch", payload == current)
                previous = Fixture._expect_json("GET", "/api/compose-drafts/" + draft_id, 200, token=auth["token"])
                check(row, "oldManualDraftPreserved", previous["snapshot"]["values"]["#contactOwner"] == "合成手動承辦人" and previous["snapshot"]["values"]["#copyRecipients"] == "合成手動副本")
                browser.evaluate("document.querySelector('#composeContactFields').scrollIntoView({block:'center',behavior:'instant'});true")
                shot(row)
                navigate("drafts")
                browser.until("!workspaceDraftState.loading&&workspaceDraftState.rows.some(x=>x.id===" + json.dumps(draft_id) + ")")
                key = browser.evaluate("workspaceDraftState.rows.find(x=>x.id===" + json.dumps(draft_id) + ").key")
                browser.click_visible('[data-workspace-draft-open="' + key + '"]')
                time.sleep(.3)
                if browser.evaluate("!!document.querySelector('#workspaceTypedConfirmModal').getClientRects().length"):
                    browser.click_visible("#workspaceTypedConfirmSubmitBtn")
                browser.until("activeRouteTarget==='compose'&&composeCloudDraftId===" + json.dumps(draft_id))
                check(row, "restoringOldDraftKeepsManualValues", browser.evaluate("contactOwner.value==='合成手動承辦人'&&contactAddress.value==='合成手動地址'&&contactEmail.value==='manual@example.invalid'&&copyRecipients.value==='合成手動副本'"))

            def a01_recovery(row):
                old_title = "合成送出後另開合法舊稿 " + row["device"]
                browser.run("fill", "#subject", old_title)
                browser.run("fill", "#bodyText", "這份合法私人草稿應可從已送出案件切換回來編輯。")
                old_id = wait_cloud()
                navigate("drafts")
                browser.until("!workspaceDraftState.loading")
                browser.click_visible("#draftNewComposeBtn")
                browser.until("activeRouteTarget==='compose'&&!document.querySelector('#subject').value")
                fill_valid("合成送出後重新授權驗收 " + row["device"])
                wait_cloud()
                browser.click_visible("#composeNextBtn")
                browser.until("activeComposeStep==='confirm'", timeout=45)
                official_id = browser.evaluate("dispatchDocs.find(d=>d.id===currentComposeDraftId)?.officialDocumentId")
                browser.click_visible("#submitDispatchBtn")
                browser.until("!document.querySelector('#composeSubmitModal').classList.contains('hidden')")
                browser.click_visible("#composeSubmitConfirmBtn")
                browser.until("!composeSubmitInFlight&&document.querySelector('#composeSubmitModal').classList.contains('hidden')", timeout=45)
                before = database_state()
                navigate("drafts")
                browser.until("!workspaceDraftState.loading&&workspaceDraftState.rows.some(x=>x.id===" + json.dumps(old_id) + ")")
                key = browser.evaluate("workspaceDraftState.rows.find(x=>x.id===" + json.dumps(old_id) + ").key")
                selector = '[data-workspace-draft-open="' + key + '"]'
                browser.evaluate("window.__draftAuthorizeFetch=window.fetch;window.fetch=(i,o)=>String(i).endsWith('/compose-drafts/" + old_id + "')&&(!o?.method||o.method==='GET')?Promise.resolve(new Response(JSON.stringify({error:'synthetic_draft_scope_forbidden'}),{status:403,headers:{'Content-Type':'application/json'}})):window.__draftAuthorizeFetch(i,o);true")
                browser.click_visible(selector)
                browser.until("!document.querySelector(" + json.dumps(selector) + ").disabled")
                check(row, "deniedDraftDoesNotClearSubmittedGuard", browser.evaluate("typeof composeSubmittedDocumentId==='function'&&composeSubmittedDocumentId()===" + json.dumps(official_id)))
                check(row, "deniedDraftDoesNotCreateAnyRows", no_new_rows(before, database_state()))
                browser.evaluate("window.fetch=window.__draftAuthorizeFetch;true")
                browser.click_visible(selector)
                time.sleep(.3)
                if browser.evaluate("!!document.querySelector('#workspaceTypedConfirmModal').getClientRects().length"):
                    browser.click_visible("#workspaceTypedConfirmSubmitBtn")
                browser.until("activeRouteTarget==='compose'&&composeCloudDraftId===" + json.dumps(old_id))
                check(row, "authorizedOldDraftOpensCorrectContent", browser.evaluate("document.querySelector('#subject').value===" + json.dumps(old_title)))
                check(row, "authorizedOldDraftClearsSubmittedGuard", browser.evaluate("typeof composeSubmittedDocumentId==='function'&&!composeSubmittedDocumentId()"))
                check(row, "loadingOldDraftDoesNotAllocateNewNumber", no_new_rows(before, database_state()))
                shot(row)

            def a03(row):
                fill_valid("合成實體公文缺章前置檢核 " + row["device"], "physical")
                browser.until("!composeSealOptionsAreLoadingForSelectedCompany()")
                for selector in ("#largeSealType", "#smallSealType", "#continuousSealType"):
                    if browser.evaluate("!document.querySelector(" + json.dumps(selector) + ").disabled"):
                        browser.run("select", selector, "無")
                row["seals"] = browser.evaluate("({large:largeSealType.value,small:smallSealType.value,single:continuousSealType.value})")
                wait_cloud()
                browser.evaluate("window.__applicantSubmits=[];window.__applicantOriginalFetch=window.fetch;window.fetch=(i,o)=>{if(o?.method==='POST'&&String(i).endsWith('/submit'))window.__applicantSubmits.push(String(i));return window.__applicantOriginalFetch(i,o)};true")
                before = database_state()
                browser.click_visible("#composeNextBtn")
                time.sleep(1.5)
                row["state"] = ui_state()
                check(row, "blockedBeforeConfirmation", row["state"]["step"] == "fill")
                check(row, "noSubmitRequest", browser.evaluate("window.__applicantSubmits.length===0"))
                check(row, "draftRemainsAvailable", bool(browser.evaluate("composeCloudDraftId")))
                row["visibleErrors"] = browser.evaluate("[...document.querySelectorAll('#compose [aria-invalid=true],#compose [role=alert],#compose .field-hint,#composeSealModeHint')].filter(e=>e.getClientRects().length).map(e=>e.textContent).join(' ')")
                check(row, "actionableSealReasonVisible", "章" in row["visibleErrors"])
                row["newNumberCount"] = len(database_state()["numbers"]) - len(before["numbers"])
                check(row, "missingSealDoesNotAllocateNumber", row["newNumberCount"] == 0)
                shot(row)

            def a04(row):
                browser.run("fill", "#subject", "合成中文組字搜尋草稿 " + row["device"])
                browser.run("fill", "#bodyText", "合成草稿搜尋內容保留測試。")
                wait_cloud()
                navigate("drafts")
                browser.until("!workspaceDraftState.loading&&workspaceDraftState.rows.length>0")
                browser.run("fill", "#workspaceDraftSearch", "")
                browser.evaluate("window.__applicantSearches=[];window.__applicantSearchFetch=window.fetch;window.fetch=(i,o)=>{if(String(i).includes('/workspace-drafts')&&!String(i).includes('summary=1'))window.__applicantSearches.push({url:String(i),composing:!!bindWorkspaceDraftControls.composing,stack:new Error().stack});return window.__applicantSearchFetch(i,o)};true")
                before = browser.evaluate("workspaceDraftState.rows.map(x=>x.key)")
                browser.evaluate("(()=>{const e=document.querySelector('#workspaceDraftSearch');e.focus();e.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));e.value='合成中文';e.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true}));return true})()")
                time.sleep(1.1)
                row["duringComposition"] = browser.evaluate("({requests:window.__applicantSearches,rows:workspaceDraftState.rows.map(x=>x.key),focus:document.activeElement.id})")
                check(row, "compositionSendsZeroQueries", not row["duringComposition"]["requests"])
                check(row, "compositionKeepsRows", row["duringComposition"]["rows"] == before)
                browser.evaluate("(()=>{const e=document.querySelector('#workspaceDraftSearch');e.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));e.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:false}));return true})()")
                browser.until("!workspaceDraftState.loading&&workspaceDraftState.search==='合成中文'")
                time.sleep(.35)
                check(row, "completedCompositionExactlyOneQuery", browser.evaluate("window.__applicantSearches.length===1"))
                check(row, "searchFocusRetained", browser.evaluate("document.activeElement.id==='workspaceDraftSearch'"))
                clear = browser.evaluate("!!document.querySelector('#workspaceDraftSearchClearBtn')?.getClientRects().length")
                check(row, "clearSearchAvailable", clear)
                if clear:
                    browser.click_visible("#workspaceDraftSearchClearBtn")
                    browser.until("!workspaceDraftState.loading&&workspaceDraftState.search===''")
                    check(row, "clearRestoresFullList", browser.evaluate("workspaceDraftState.rows.length>0"))
                shot(row)

            def a05(row):
                title = "合成可封存私人草稿 " + row["device"]
                browser.run("fill", "#subject", title)
                browser.run("fill", "#bodyText", "合成封存取消失敗及恢復測試。")
                draft_id = wait_cloud()
                navigate("drafts")
                browser.until("!workspaceDraftState.loading&&workspaceDraftState.rows.some(x=>x.id===" + json.dumps(draft_id) + ")")
                key = browser.evaluate("workspaceDraftState.rows.find(x=>x.id===" + json.dumps(draft_id) + ").key")
                archive_selector = '[data-workspace-draft-archive="' + key + '"]'
                available = browser.evaluate("!!document.querySelector(" + json.dumps(archive_selector) + ")")
                check(row, "archiveActionAvailable", available)
                if not available:
                    shot(row)
                    return
                total = Fixture._expect_json("GET", "/api/workspace-drafts?summary=1", 200, token=auth["token"])["total"]
                before_cancel = Fixture._expect_json("GET", "/api/compose-drafts/" + draft_id, 200, token=auth["token"])
                browser.click_visible(archive_selector)
                browser.until("!!document.querySelector('#workspaceTypedConfirmModal').getClientRects().length")
                browser.click_visible("#workspaceTypedConfirmCancelBtn")
                check(row, "cancelDoesNotArchive", Fixture._request("GET", "/api/compose-drafts/" + draft_id, token=auth["token"]).status == 200)
                check(row, "cancelDoesNotChangeRevision", Fixture._expect_json("GET", "/api/compose-drafts/" + draft_id, 200, token=auth["token"])["revision"] == before_cancel["revision"])
                browser.evaluate("window.__archiveGoodFetch=window.fetch;window.fetch=(i,o)=>String(i).endsWith('/archive')&&o?.method==='PATCH'?Promise.resolve(new Response(JSON.stringify({error:'synthetic_archive_unavailable'}),{status:503,headers:{'Content-Type':'application/json'}})):window.__archiveGoodFetch(i,o);true")
                browser.click_visible(archive_selector)
                browser.until("!!document.querySelector('#workspaceTypedConfirmModal').getClientRects().length")
                browser.click_visible("#workspaceTypedConfirmSubmitBtn")
                browser.until("!workspaceDraftState.actionPending")
                check(row, "failedArchiveKeepsRow", browser.evaluate("workspaceDraftState.rows.some(x=>x.id===" + json.dumps(draft_id) + ")"))
                check(row, "failedArchiveKeepsCount", Fixture._expect_json("GET", "/api/workspace-drafts?summary=1", 200, token=auth["token"])["total"] == total)
                row["failureText"] = browser.evaluate("document.querySelector('#workspaceDraftActionStatus')?.textContent||''")
                check(row, "failedArchiveHasPersistentReason", bool(row["failureText"]) and any(word in row["failureText"] for word in ("未確認", "失敗", "再試")))
                shot(row, "-failure")
                browser.evaluate("window.fetch=window.__archiveGoodFetch;true")
                if browser.evaluate("!!document.querySelector('#workspaceTypedConfirmModal').getClientRects().length"):
                    browser.click_visible("#workspaceTypedConfirmCancelBtn")
                browser.click_visible(archive_selector)
                browser.until("!!document.querySelector('#workspaceTypedConfirmModal').getClientRects().length")
                browser.click_visible("#workspaceTypedConfirmSubmitBtn")
                browser.until("!workspaceDraftState.loading&&!workspaceDraftState.actionPending&&!workspaceDraftState.rows.some(x=>x.id===" + json.dumps(draft_id) + ")")
                check(row, "archiveDecrementsCountExactlyOne", Fixture._expect_json("GET", "/api/workspace-drafts?summary=1", 200, token=auth["token"])["total"] == total - 1)
                check(row, "archiveUpdatesSidebarBadge", browser.evaluate("document.querySelector('#draftNavCount').textContent.trim()") == str(total - 1))
                browser.run("open", Fixture.origin + "/#drafts")
                browser.until("window.__fixtureTiming?.appInteractiveMs&&!workspaceDraftState.loading")
                browser.click_visible("#workspaceDraftArchivedBtn")
                browser.until("!workspaceDraftState.loading&&workspaceDraftState.rows.some(x=>x.id===" + json.dumps(draft_id) + ")")
                restore_key = browser.evaluate("workspaceDraftState.rows.find(x=>x.id===" + json.dumps(draft_id) + ").key")
                browser.click_visible('[data-workspace-draft-restore="' + restore_key + '"]')
                time.sleep(.4)
                if browser.evaluate("!!document.querySelector('#workspaceTypedConfirmModal').getClientRects().length"):
                    browser.click_visible("#workspaceTypedConfirmSubmitBtn")
                browser.until("!workspaceDraftState.loading&&!workspaceDraftState.actionPending")
                check(row, "restoreReturnsSameDraft", Fixture._request("GET", "/api/compose-drafts/" + draft_id, token=auth["token"]).status == 200)
                check(row, "restoreIncrementsCountExactlyOne", Fixture._expect_json("GET", "/api/workspace-drafts?summary=1", 200, token=auth["token"])["total"] == total)
                check(row, "restoreUpdatesSidebarBadge", browser.evaluate("document.querySelector('#draftNavCount').textContent.trim()") == str(total))
                check(row, "restoreDoesNotUnexpectedlyOpenEditor", browser.evaluate("activeRouteTarget==='drafts'"))
                check(row, "restoreFocusesDraftHeading", browser.evaluate("document.activeElement.id==='workspaceDraftTitle'"))
                shot(row, "-restored")

            def a06(row):
                row["fields"] = browser.evaluate("Object.fromEntries(['contactAddress','contactOwner','contactPhone','contactFax','contactEmail'].map(id=>{const e=document.getElementById(id),r=e.getBoundingClientRect();return [id,{visible:r.width>0&&r.height>0,disabled:e.disabled,hidden:e.closest('label').hidden}]}))")
                check(row, "allSenderFieldsExpanded", all(v["visible"] and not v["hidden"] and not v["disabled"] for v in row["fields"].values()))
                check(row, "noEditOrCollapseGate", not browser.evaluate("!!document.querySelector('#composeContactToggleBtn')?.getClientRects().length"))
                if row["checks"]["allSenderFieldsExpanded"]:
                    browser.run("fill", "#contactOwner", "合成直接修改承辦人")
                    check(row, "canEditWithoutExtraButton", browser.evaluate("document.querySelector('#contactOwner').value==='合成直接修改承辦人'"))
                browser.evaluate("document.querySelector('#composeContactFields').scrollIntoView({block:'center',behavior:'instant'});true")
                shot(row)

            functions = {"A01": a01, "A01-storage": lambda r: a01(r, True), "A01-recovery": a01_recovery, "A02": a02, "A03": a03, "A04": a04, "A05": a05, "A06": a06}
            for device, width, height in DEVICES:
                if devices and device not in devices:
                    continue
                for case, function in functions.items():
                    if cases and case not in cases:
                        continue
                    row = {"device": device, "case": case, "checks": {}}
                    report["cases"].append(row)
                    print(json.dumps({"device": device, "case": case, "stage": "start"}), flush=True)
                    try:
                        login(width, height)
                        function(row)
                        check(row, "noPageHorizontalOverflow", browser.evaluate("document.documentElement.scrollWidth<=innerWidth+1"))
                        check(row, "noUnhandledBrowserErrors", browser.evaluate("window.__fixtureErrors.length===0"))
                    except Exception as error:
                        # A transport/precondition error is not a verified
                        # product regression. Keep it separate for triage.
                        row["runnerError"] = {"type": type(error).__name__, "code": str(error)[:160], "lastCommand": browser.last_command}
                        try:
                            row["failureState"] = ui_state()
                            shot(row, "-runner-error")
                        except Exception:
                            pass
                    row["passed"] = bool(row["checks"]) and all(row["checks"].values()) and "runnerError" not in row
                    persist()
                    print(json.dumps({"device": device, "case": case, "passed": row["passed"], "failedChecks": [k for k, v in row["checks"].items() if not v], "runnerError": row.get("runnerError")}, ensure_ascii=False), flush=True)
        finally:
            if browser:
                try:
                    browser.run("close")
                except Exception:
                    browser._stop()
            Fixture.tearDownClass()
    report["sourceHashesAtEnd"] = source_hashes()
    report["sourceStableDuringRun"] = report["sourceHashesAtStart"] == report["sourceHashesAtEnd"]
    report["passed"] = bool(report["cases"]) and all(row["passed"] for row in report["cases"]) and report["sourceStableDuringRun"]
    if not report["sourceStableDuringRun"]:
        report["environmentError"] = "source_changed_during_run"
    persist()
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--devices", nargs="*", choices=[x[0] for x in DEVICES])
    parser.add_argument("--cases", nargs="*", choices=["A01", "A01-storage", "A01-recovery", "A02", "A03", "A04", "A05", "A06"])
    args = parser.parse_args()
    args.output = args.output.resolve()
    result = run(args.output, args.devices, args.cases)
    print(json.dumps({"passed": result["passed"], "cases": len(result["cases"]), "report": str(args.output.resolve() / "report.json")}, ensure_ascii=False))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
