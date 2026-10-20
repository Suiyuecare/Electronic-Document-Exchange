"""Actual Chromium + temporary synthetic HTTP DB, no hosted writes or real seals."""
import argparse
import io
import json
import os
from pathlib import Path
import sys
import time
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as Fixture, QuietAcceptanceHandler
from tests.support.five_account_browser_fixture import isolated_browser_session
from tools.ux_complete_browser_acceptance import BRIDGE, TELEMETRY, require_local_origin
import tools.backup_drill_browser_acceptance as transport


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    report = {"scope": "local_synthetic_chromium", "hostedVerified": False, "humanSSOVerified": False, "cases": []}
    original = QuietAcceptanceHandler.send_head
    html = (ROOT / "index.html").read_bytes().replace(b"<head>", b"<head>" + TELEMETRY.encode(), 1)

    def head(handler):
        if urlparse(handler.path).path not in {"/", "/index.html"}:
            return original(handler)
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(html)))
        handler.end_headers()
        return io.BytesIO(html)

    browser_path = Path.home() / "Library/Caches/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-mac-arm64/chrome-headless-shell"
    with mock.patch.object(QuietAcceptanceHandler, "send_head", head), mock.patch.object(transport, "PLAYWRIGHT_BRIDGE", BRIDGE), mock.patch.dict(os.environ, {"EDOC_TEST_BROWSER_PATH": str(browser_path)}):
        Fixture.setUpClass()
        require_local_origin(Fixture.origin)
        browser = None
        try:
            auth = isolated_browser_session(Fixture, "staff", entity_id="E1")
            browser = transport.LocalPlaywrightBrowser(Fixture.origin)
            for device, width, height in (("desktop", 1440, 1000), ("tablet", 820, 1100), ("mobile", 390, 844)):
                row = {"device": device, "checks": {}}
                report["cases"].append(row)
                checks = row["checks"]
                browser.run("open", Fixture.origin + "/assets/favicon-32.png")
                browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                browser.run("set", "viewport", str(width), str(height))
                browser.run("open", Fixture.origin + "/?fixture=" + str(time.monotonic_ns()) + "#compose")
                browser.until("window.__fixtureTiming?.appInteractiveMs&&document.querySelector('#composeApprovalCategorySelect').options.length>1&&!composeSealOptionsLoading", timeout=40)
                browser.until("composeSealCatalogState.status==='ready'", timeout=30)
                checks["contactsAlwaysExpanded"] = browser.evaluate("!document.querySelector('#composeContactToggleBtn')&&[...document.querySelectorAll('#composeContactFields input')].every(e=>e.getBoundingClientRect().height>=44&&!e.closest('label').hidden)")
                browser.evaluate("document.querySelector('#composeContactFields').scrollIntoView({block:'center'});true")
                time.sleep(.45)
                browser.run("screenshot", str(output / f"{device}-contacts.png"))
                category = browser.evaluate("[...document.querySelector('#composeApprovalCategorySelect').options].find(e=>e.textContent.includes('服務委託合約')).value")
                browser.run("select", "#composeApprovalCategorySelect", category)
                for selector, value in {"#recipient": "合成收文機關", "#subject": "隔離測試實體公文印章預檢 " + device, "#bodyText": "隔離測試公文內容，沒有真實個資或正式交換。", "#contactAddress": "合成測試地址", "#contactOwner": "合成承辦人", "#contactPhone": "02-66045432 #123", "#contactEmail": "fixture@example.invalid"}.items():
                    browser.run("fill", selector, value)
                browser.evaluate("window.__submitCalls=[];window.__preflightFetch=window.fetch;window.fetch=(...args)=>{if(/\\/(submit|resubmit)(?:\\?|$)/.test(String(args[0])))window.__submitCalls.push(String(args[0]));return window.__preflightFetch(...args)};true")

                # Empty current-company catalog, without changing any product guards.
                browser.evaluate("window.__catalogFetch=window.fetch;window.fetch=(...a)=>String(a[0]).includes('/companies/CO-001/seals')?Promise.resolve(new Response('[]',{status:200,headers:{'Content-Type':'application/json'}})):window.__catalogFetch(...a);true")
                browser.evaluate("loadComposeSealOptions(undefined,{force:true}).then(()=>true)")
                browser.click_visible("#composeNextBtn")
                checks["emptyStopsBeforeReviewAndFocuses"] = browser.evaluate("activeComposeStep==='fill'&&document.activeElement.id==='composeSealFields'&&document.querySelector('#composeSealFields').getAttribute('aria-invalid')==='true'&&document.querySelector('#composeSealValidationHint').textContent.includes('沒有已啟用')&&document.querySelector('#composeSubmitModal').classList.contains('hidden')&&window.__submitCalls.length===0")
                time.sleep(.45)
                browser.run("screenshot", str(output / f"{device}-no-seal.png"))
                browser.click_visible("#saveDispatchDraftBtn")
                browser.until("!composeSaveInFlight&&!composeCloudOperation&&!!currentComposeDraftId", timeout=40)
                saved_id = browser.evaluate("dispatchDocs.find(d=>d.id===currentComposeDraftId)?.officialDocumentId")
                saved = Fixture._expect_json("GET", "/api/official-documents/" + saved_id, 200, token=auth["token"])
                checks["emptyCanSaveDraft"] = saved["current_status"] == "draft" and browser.evaluate("window.__submitCalls.length===0")
                row["draftId"] = saved_id
                browser.evaluate("window.fetch=window.__catalogFetch;loadComposeSealOptions(undefined,{force:true}).then(()=>true)")
                row["catalog"] = browser.evaluate("composeSealOptions.map(s=>({id:s.id,active:s.is_active,selectable:s.selectable,category:s.seal_category}))")
                checks["physicalReadyAfterRecovery"] = browser.evaluate("composeSealSubmissionReadiness().valid&&document.querySelector('#composeSealFields').getAttribute('aria-invalid')!=='true'")
                if not checks["physicalReadyAfterRecovery"]:
                    raise AssertionError({"catalog": row["catalog"], "readiness": browser.evaluate("composeSealSubmissionReadiness()")})
                browser.click_visible("#composeNextBtn")
                browser.until("activeComposeStep==='confirm'", timeout=40)
                checks["physicalCanReachReview"] = browser.evaluate("window.__submitCalls.length===0")
                browser.click_visible("#composePrevBtn")
                # Real inactive state in disposable test DB, not a mocked success.
                seal_id = Fixture.seals["CO-001"]["seal_id"]
                with backend.connect() as conn:
                    conn.execute("UPDATE company_seals SET is_active=0 WHERE id=?", (seal_id,))
                    conn.commit()
                browser.evaluate("loadComposeSealOptions(undefined,{force:true}).then(()=>true)")
                browser.click_visible("#composeNextBtn")
                checks["inactiveStopsBeforeReview"] = browser.evaluate("activeComposeStep==='fill'&&!composeSealSubmissionReadiness().valid&&window.__submitCalls.length===0")
                browser.run("select", "#composeOutputMode", "electronic")
                browser.click_visible("#composeNextBtn")
                browser.until("activeComposeStep==='confirm'", timeout=40)
                checks["electronicNeedsNoSeal"] = browser.evaluate("composeSealSubmissionReadiness().valid&&document.querySelector('#composeSealFields').getAttribute('aria-invalid')!=='true'")
                browser.click_visible("#submitDispatchBtn")
                browser.until("!document.querySelector('#composeSubmitModal').classList.contains('hidden')", timeout=30)
                checks["electronicConfirmationNoMutation"] = browser.evaluate("window.__submitCalls.length===0")
                browser.click_visible("#composeSubmitCancelBtn")
                with backend.connect() as conn:
                    conn.execute("UPDATE company_seals SET is_active=1 WHERE id=?", (seal_id,))
                    conn.commit()
                checks["noHorizontalOverflow"] = browser.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                checks["noJavascriptErrors"] = not browser.evaluate("window.__fixtureErrors||[]")
                row["passed"] = all(checks.values())
                print(json.dumps(row, ensure_ascii=False), flush=True)
                (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
                assert row["passed"], row
            # A permitted company switch is exercised with a synthetic custodian,
            # because ordinary employee identity correctly locks the issuer.
            custodian = isolated_browser_session(Fixture, "ceo", entity_id="E1")
            browser.run("open", Fixture.origin + "/assets/favicon-32.png")
            browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(custodian)) + ");true")
            browser.run("open", Fixture.origin + "/?switch=" + str(time.monotonic_ns()) + "#compose")
            browser.until("window.__fixtureTiming?.appInteractiveMs&&composeSealCatalogState.status==='ready'", timeout=40)
            row = {"device": "mobile", "case": "authorized-company-switch", "checks": {}}
            report["cases"].append(row)
            companies = browser.evaluate("[...document.querySelector('#composeCompanySelect').options].map(o=>({value:o.value,id:composeCompanyForOfficialApplication(o.value)?.id}))")
            target = next(company for company in companies if company["id"] == "CO-002")
            browser.evaluate("window.__switchFetch=window.fetch;window.fetch=(...a)=>String(a[0]).includes('/companies/CO-002/seals')?new Promise(resolve=>{window.__releaseCatalog=()=>resolve(new Response('[]',{status:200,headers:{'Content-Type':'application/json'}}))}):window.__switchFetch(...a);true")
            browser.run("select", "#composeCompanySelect", target["value"])
            browser.until("composeSealOptionsLoading&&typeof window.__releaseCatalog==='function'")
            row["checks"]["oldCompanySealsImmediatelyExcluded"] = browser.evaluate("composeSealOptionsForSelectedCompany().length===0&&!composeSealSubmissionReadiness().valid")
            browser.evaluate("window.__releaseCatalog();true")
            browser.until("!composeSealOptionsLoading&&composeSealCatalogState.status==='ready'")
            row["checks"]["newCompanyEmptyCannotUseOldSeal"] = browser.evaluate("!composeSealSubmissionReadiness().valid&&document.querySelector('#largeSealType').value==='無'&&document.querySelector('#smallSealType').value==='無'")
            browser.evaluate("document.querySelector('#composeSealFields').scrollIntoView({block:'center'});true")
            time.sleep(.45)
            browser.run("screenshot", str(output / "mobile-company-switch.png"))
            row["passed"] = all(row["checks"].values())
            assert row["passed"], row
            report["status"] = "passed"
        finally:
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            if browser:
                try:
                    browser.run("close")
                except Exception:
                    browser._stop()
            Fixture.tearDownClass()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output.resolve())
