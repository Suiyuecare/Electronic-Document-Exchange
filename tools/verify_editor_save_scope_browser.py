"""Late autosave response across logout/new fixture login, real local PDF API."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import sys
import time
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from tools.six_role_browser_acceptance import AUDIT_JS, Browser, TELEMETRY, require_local_origin
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler


def run(output: Path) -> dict:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    fixture = FiveAccountHttpAcceptanceTest
    original_head = QuietAcceptanceHandler.send_head

    def head(handler):
        if urlparse(handler.path).path in {"/", "/index.html"}:
            data = (ROOT / "index.html").read_text().replace("<head>", "<head>" + TELEMETRY, 1).encode()
            handler.send_response(200)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.send_header("Content-Security-Policy", "connect-src 'self'")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            return io.BytesIO(data)
        return original_head(handler)

    report = {
        "scope": "synthetic_local_real_http_no_production_mutations",
        "authenticationScope": "Real logout button; next synthetic session is installed by the fixture in the same JS document so the old response can complete. This is not Google/Portal login verification.",
        "journeys": [],
    }
    with mock.patch.object(QuietAcceptanceHandler, "send_head", head):
        fixture.setUpClass()
        require_local_origin(fixture.origin)
        config = Path(fixture.tmp.name) / "scope-browser.json"
        config.write_text(json.dumps({"headed": False}))
        browser = Browser(config, session=f"scope-{time.monotonic_ns():x}"[-18:], namespace="scope-launch")
        try:
            for device, dimensions in (("desktop", (1440, 1000)), ("mobile", (390, 844))):
                auth = isolated_browser_session(fixture, "staff")
                browser.run("set", "viewport", *map(str, dimensions))
                browser.run("open", fixture.origin + "/assets/favicon-32.png")
                browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                browser.run("open", fixture.origin + "/#electronicSeal")
                browser.until("window.__fixtureTiming?.appInteractiveMs&&document.querySelector('#uploadedSealApprovalCategorySelect')?.options.length>1")
                browser.run("snapshot", "-i")
                checks = {}
                browser.evaluate("window.__scopeRealFetch=window.fetch;window.__scopeHoldIds=new Set();window.__scopeHeld={};window.__scopePutPaths=[];window.fetch=async (...args)=>{const u=new URL(args[0]?.url||String(args[0]),location.href),method=args[1]?.method||args[0]?.method||'GET';const response=await window.__scopeRealFetch(...args);const match=u.pathname.match(/^\\/api\\/official-documents\\/([^/]+)\\/editor-state$/);if(method==='PUT'&&match){window.__scopePutPaths.push(u.pathname);if(window.__scopeHoldIds.has(match[1]))return await new Promise(resolve=>{window.__scopeHeld[match[1]]={status:response.status,release:()=>resolve(response)}})}return response};true")

                def upload(name, text):
                    category = browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(e=>e.textContent.includes('合作意向書')).value")
                    browser.run("select", "#uploadedSealApprovalCategorySelect", category)
                    browser.run("fill", "#uploadedSealTitle", "隔離延遲保存測試 " + name)
                    browser.run("fill", "#uploadedSealReason", "去識別化測試，不送簽、不用印、不寄發。")
                    path = output / (device + "-" + name + ".pdf")
                    writer = canvas.Canvas(str(path), pagesize=A4)
                    writer.drawString(60, 780, "ISOLATED SAVE SCOPE - " + name)
                    writer.showPage(); writer.save()
                    browser.run("upload", "#uploadedSealPdfInput", str(path))
                    browser.until("uploadedSealEditorState.pages.length===1&&!uploadedSealEditorRuntime.uploading")
                    document_id = browser.evaluate("uploadedSealEditorRuntime.documentId")
                    browser.evaluate("window.__scopeHoldIds.add(" + json.dumps(document_id) + ");true")
                    browser.add_pdf_text(text)
                    browser.until("!!window.__scopeHeld[" + json.dumps(document_id) + "]&&uploadedSealEditorRuntime.saving", timeout=35)
                    return document_id

                old_id = upload("old", "舊文件專用文字 OLD-SCOPE")
                checks["oldPutCompletedOnRealServer"] = browser.evaluate("window.__scopeHeld[" + json.dumps(old_id) + "].status===200")
                browser.evaluate("window.__oldScopePromise=uploadedSealEditorRuntime.savePromise;true")
                browser.run("screenshot", str(output / (device + "-old-save-pending.png")))
                if device == "mobile":
                    browser.run("click", "#mobileMenuButton")
                    browser.until("Math.abs(document.querySelector('#primarySidebar').getBoundingClientRect().left)<.5")
                    browser.click_visible("#mobileDrawerLogoutBtn")
                else:
                    browser.click_visible("#logoutBtn")
                browser.until("!authState&&!uploadedSealEditorRuntime.documentId&&uploadedSealEditorState.pages.length===0")
                checks["logoutClearedSensitiveEditor"] = True
                new_auth = isolated_browser_session(fixture, "staff")
                # Authentication fixture setup only: do not replace/reload the JS
                # document or the pending old callback would never execute.
                browser.evaluate("authState=" + json.dumps(new_auth) + ";persistAuthenticatedSession(authState);enterAuthenticatedAppSafely('隔離測試新工作階段');true")
                browser.until("hasAuthenticatedBackendSession()&&document.querySelector('.view.active')?.id==='electronicSeal'&&document.querySelector('#uploadedSealApprovalCategorySelect').options.length>1&&!document.querySelector('#moduleEntryProgress').getClientRects().length")
                new_id = upload("new", "新文件專用文字 NEW-SCOPE")
                checks["newDraftHasDifferentId"] = old_id != new_id
                checks["newPutCompletedOnRealServer"] = browser.evaluate("window.__scopeHeld[" + json.dumps(new_id) + "].status===200")
                browser.evaluate("window.__newScopePromise=uploadedSealEditorRuntime.savePromise;window.__newScopeState=JSON.stringify(uploadedSealEditorState);window.__newScopeStatus=document.querySelector('#uploadedEditorSaveStatus').textContent;window.__oldScopeSettled=false;window.__oldScopePromise.finally(()=>window.__oldScopeSettled=true);window.__scopeHeld[" + json.dumps(old_id) + "].release();true")
                browser.until("window.__oldScopeSettled")
                checks["lateOldResponsePreservesNewState"] = browser.evaluate("JSON.stringify(uploadedSealEditorState)===window.__newScopeState&&uploadedSealEditorRuntime.documentId===" + json.dumps(new_id))
                checks["lateOldResponsePreservesNewSavePromise"] = browser.evaluate("uploadedSealEditorRuntime.saving&&uploadedSealEditorRuntime.savePromise===window.__newScopePromise")
                checks["lateOldResponsePreservesNewStatus"] = browser.evaluate("document.querySelector('#uploadedEditorSaveStatus').textContent===window.__newScopeStatus")
                browser.run("screenshot", str(output / (device + "-old-response-ignored.png")))
                browser.evaluate("window.__scopeHoldIds.delete(" + json.dumps(new_id) + ");window.__scopeHeld[" + json.dumps(new_id) + "].release();true")
                browser.until("!uploadedSealEditorRuntime.saving&&!uploadedSealEditorRuntime.savePromise&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration")
                old = fixture._expect_json("GET", f"/api/official-documents/{old_id}/editor-state", 200, token=new_auth["token"])
                new = fixture._expect_json("GET", f"/api/official-documents/{new_id}/editor-state", 200, token=new_auth["token"])
                texts = lambda row: [e.get("properties", {}).get("text") for e in row["state"]["elements"] if e.get("kind") == "text"]
                checks["oldServerDocumentUnchanged"] = texts(old) == ["舊文件專用文字 OLD-SCOPE"]
                checks["newServerDocumentHasOnlyNewText"] = texts(new) == ["新文件專用文字 NEW-SCOPE"]
                checks["putUrlsRemainDocumentScoped"] = browser.evaluate("window.__scopePutPaths.filter(p=>p.includes(" + json.dumps(old_id) + ")).length===1&&window.__scopePutPaths.filter(p=>p.includes(" + json.dumps(new_id) + ")).length===1")
                layout = browser.evaluate(AUDIT_JS)
                checks["noOverflow"] = not layout["overflow"]
                checks["noBrowserErrors"] = not layout["errors"]
                browser.run("screenshot", str(output / (device + "-new-save-completed.png")))
                report["journeys"].append({"device": device, "checks": checks, "layout": layout})
                if not all(checks.values()):
                    raise AssertionError("stale_save_scope_failed:" + device)
                print(json.dumps({"device": device, "checks": len(checks), "passed": True}), flush=True)
            report["passed"] = True
        except Exception as error:
            report["passed"] = False
            report["errorCode"] = str(error) if isinstance(error, AssertionError) or str(error).startswith("browser_") else type(error).__name__
            try:
                browser.run("screenshot", str(output / "failure.png"))
                report["failureState"] = browser.evaluate("({errors:window.__fixtureErrors,status:document.querySelector('#uploadedEditorSaveStatus')?.textContent,uploading:uploadedSealEditorRuntime.uploading,saving:uploadedSealEditorRuntime.saving,pageCount:uploadedSealEditorState.pages.length})")
            except Exception:
                pass
        finally:
            try:
                browser.run("close")
            finally:
                fixture.tearDownClass()
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if run(args.output)["passed"] else 1)
