"""Six-role local browser audit. No real Google login, send, seal or exchange.

The synthetic session is created only inside a newly initialized temporary
SQLite fixture. Tokens travel through stdin to a dedicated agent-browser
session, never into report files. Timing excludes real SSO/hosted database.
"""
from __future__ import annotations

import argparse
import fcntl
import io
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
from unittest import mock
from urllib.parse import urlparse
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.support.five_account_browser_fixture import BROWSER_ROLES, isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler

ROUTES = ("dashboard", "compose", "electronicSeal", "approvalLog", "inbound", "settings")
VIEWPORTS = {"desktop": (1440, 1000), "mobile": (390, 844)}
SESSION = "edoc-roles-20260908"
TELEMETRY = """<script>
window.__fixtureTiming={loaderVisibleMs:null,appInteractiveMs:null};
window.__fixtureErrors=[];
window.addEventListener('error',e=>{if(e.message)window.__fixtureErrors.push(e.message)});
window.addEventListener('unhandledrejection',e=>window.__fixtureErrors.push(String(e.reason?.message||e.reason)));
function fixtureFrame(){
 const t=window.__fixtureTiming;
 const visible=e=>!!e&&e.getBoundingClientRect().width>0&&getComputedStyle(e).visibility!=='hidden';
 const loader=document.querySelector('#moduleEntryProgress'),shell=document.querySelector('#appShell');
 if(t.loaderVisibleMs===null&&visible(loader))t.loaderVisibleMs=performance.now();
 if(t.appInteractiveMs===null&&visible(shell)&&!shell.inert&&!visible(loader)&&document.querySelector('.view.active')&&typeof hasAuthenticatedBackendSession==='function'&&hasAuthenticatedBackendSession())t.appInteractiveMs=performance.now();
 if(t.appInteractiveMs===null&&performance.now()<30000)requestAnimationFrame(fixtureFrame);
}
requestAnimationFrame(fixtureFrame);
</script>"""
AUDIT_JS = """(()=>{
 const visible=e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const page=document.querySelector('.view.active');
 const controls=page?[...page.querySelectorAll('button,input:not([type=hidden]),select,textarea,a[href]'),...document.querySelectorAll('.topbar button')].filter(visible):[];
 return {route:page?.id,documentWidth:document.documentElement.scrollWidth,viewportWidth:innerWidth,
 overflow:document.documentElement.scrollWidth>innerWidth+1,
 shortTargets:controls.filter(e=>{let r=e.getBoundingClientRect();return r.width<44||r.height<44}).map(e=>({id:e.id,tag:e.tagName,text:(e.getAttribute('aria-label')||e.textContent||e.type||'').trim().slice(0,50),width:Math.round(e.getBoundingClientRect().width),height:Math.round(e.getBoundingClientRect().height)})),
 smallInputs:controls.filter(e=>e.matches('input,select,textarea')&&parseFloat(getComputedStyle(e).fontSize)<16).map(e=>({id:e.id,fontSize:getComputedStyle(e).fontSize})),
 errors:window.__fixtureErrors||[],timing:window.__fixtureTiming||{},
 firstContentfulPaintMs:performance.getEntriesByName('first-contentful-paint')[0]?.startTime??null,
 navigationLinks:[...document.querySelectorAll('.sidebar .nav-item')].map(e=>({route:e.dataset.target,hidden:!visible(e)}))};})()"""


def require_local_origin(origin: str) -> None:
    parsed = urlparse(origin)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port or parsed.path:
        raise ValueError("local_fixture_origin_required")


def editor_case(browser, fixture, auth, role, device, output):
    result = {"role": role, "device": device, "scope": "local_fixture_no_seals_no_submission"}
    try:
        if device == "mobile" and not browser.evaluate("document.body.classList.contains('mobile-navigation-open')"):
            browser.run("click", "#mobileMenuButton")
        if device == "mobile":
            browser.until("Math.abs(document.querySelector('#primarySidebar').getBoundingClientRect().left)<0.5")
        browser.run("click", '.sidebar .nav-item[data-target="electronicSeal"]')
        browser.until("document.querySelector('#uploadedSealApprovalCategorySelect')?.options.length>1")
        category = browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(e=>e.textContent.includes('合作意向書')).value")
        browser.run("select", "#uploadedSealApprovalCategorySelect", category)
        browser.run("fill", "#uploadedSealTitle", "上線驗收測試：合成 A4 文字編輯")
        browser.run("fill", "#uploadedSealReason", "隔離測試，不送簽、不用印、不寄發。")
        pdf = Path(fixture.tmp.name) / f"synthetic-{role}-{device}.pdf"
        writer = canvas.Canvas(str(pdf), pagesize=A4)
        writer.drawString(60, 780, "ISOLATED A4 ACCEPTANCE - NO PERSONAL DATA")
        writer.showPage()
        writer.save()
        browser.run("upload", "#uploadedSealPdfInput", str(pdf))
        browser.until("(uploadedSealEditorState.pages.length>0&&!uploadedSealEditorRuntime.uploading)||(!document.querySelector('#uploadedEditorUploadError').hidden)")
        if not browser.evaluate("uploadedSealEditorState.pages.length>0"):
            result.update(status="upload_failed", message=browser.evaluate("document.querySelector('#uploadedEditorUploadErrorMessage').textContent"))
            return result
        browser.click_visible('#uploadedPdfEditor [data-editor-tool="text"]')
        browser.until("uploadedSealEditorRuntime.tool==='text'")
        browser.run("fill", "#uploadedSealTextInput", "六角色隔離驗收文字")
        browser.click_visible("#addUploadedTextBtn")
        browser.until("uploadedSealEditorState.elements.some(e=>e.kind==='text')&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration&&!uploadedSealEditorRuntime.saving")
        document_id = browser.evaluate("uploadedSealEditorRuntime.documentId")
        saved = fixture._expect_json("GET", f"/api/official-documents/{document_id}/editor-state", 200, token=auth["token"])
        state = saved.get("state") or saved.get("editor_state") or saved.get("editor_revision", {}).get("state", {})
        result["readbackTextMatched"] = any(element.get("properties", {}).get("text") == "六角色隔離驗收文字" for element in state.get("elements", []))
        stale = fixture._request("PUT", f"/api/official-documents/{document_id}/editor-state", token=auth["token"], json_body={"revisionNo": 0, "baseManifestSha256": "0" * 64, "state": state})
        result["staleSaveStatus"] = stale.status
        outsider = isolated_browser_session(fixture, "department_head", entity_id="E2" if auth["user"]["company_id"] == "CO-001" else "E1")
        denial = fixture._request("GET", f"/api/official-documents/{document_id}/editor-state", token=outsider["token"])
        result["crossCompanyStatus"] = denial.status
        result["documentId"] = document_id
        result["revisionNo"] = state.get("revisionNo")
        result["pageCount"] = len(state.get("pages", []))
        result["sealCount"] = sum(e.get("kind") == "seal" for e in state.get("elements", []))
        result["autosaveStatus"] = browser.evaluate("document.querySelector('#uploadedEditorSaveStatus').textContent")
        result["status"] = "passed" if result["readbackTextMatched"] and denial.status == 403 and stale.status == 409 else "failed"
        browser.run("screenshot", str(output / f"{role}-{device}-editor-saved.png"), "--full")
        result["layout"] = browser.evaluate(AUDIT_JS)
    except Exception as error:
        result.update(status="failed", errorCode=str(error) if str(error).startswith(("browser_", "local_")) else type(error).__name__)
        result["failureState"] = browser.evaluate("({active:document.querySelector('.view.active')?.id,menuOpen:document.body.classList.contains('mobile-navigation-open'),textTools:document.querySelectorAll('[data-editor-tool=text]').length,textToolsVisible:[...document.querySelectorAll('[data-editor-tool=text]')].map(e=>({rect:e.getBoundingClientRect().toJSON(),disabled:e.disabled})),toast:document.querySelector('.toast')?.textContent})")
        browser.run("screenshot", str(output / f"{role}-{device}-editor-failed.png"), "--full")
    return result


class Browser:
    def __init__(self, config: Path, *, session=SESSION, namespace="edoc-roles-isolated"):
        self.config = config
        self.session = session
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("AGENT_BROWSER_")}
        self.env["AGENT_BROWSER_NAMESPACE"] = namespace
    def run(self, *args, script=None):
        result = subprocess.run(["agent-browser", "--config", str(self.config), "--session", self.session, "--json", *args], input=script, text=True, capture_output=True, env=self.env, timeout=60)
        if result.returncode:
            # Never echo eval input/auth state, backend responses or arbitrary logs.
            selector = str(args[1]) if args[0] in {"click", "fill", "select", "upload"} else ""
            raise RuntimeError("browser_command_failed:" + str(args[0]) + ":" + selector)
        payload = json.loads(result.stdout)
        if not payload.get("success", True):
            raise RuntimeError("browser_action_failed:" + str(args[0]))
        return payload.get("data", payload)
    def evaluate(self, script):
        result = self.run("eval", "--stdin", script=script)
        return result.get("result", result) if isinstance(result, dict) else result
    def click_visible(self, selector):
        encoded = json.dumps(selector)
        self.evaluate("document.querySelector(" + encoded + ").scrollIntoView({block:'center',behavior:'instant'});true")
        self.until("(()=>{const e=document.querySelector(" + encoded + "),r=e.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return !e.disabled&&r.width>0&&r.height>0&&(hit===e||e.contains(hit))})()")
        self.run("click", selector)
    def until(self, expression, timeout=25):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.evaluate(expression)
            if result:
                return result
            time.sleep(0.2)
        raise RuntimeError("browser_condition_timeout")


def audit(args) -> dict:
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    fixture = FiveAccountHttpAcceptanceTest
    original_send_head = QuietAcceptanceHandler.send_head
    original_get = QuietAcceptanceHandler.do_GET
    def instrumented_get(handler):
        if urlparse(handler.path).path == "/__fixture_slow-interface-font.css":
            time.sleep(args.slow_font_ms / 1000)
            data = b"/* deliberately delayed UI-only stylesheet */"
            handler.send_response(200)
            handler.send_header("Content-Type", "text/css")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
            return
        if urlparse(handler.path).path == "/api/fixture-runtime-error":
            handler.send_json({"error": "server_error", "detail": "internal_server_error", "errorId": "ERR-1234567890ABCDEF12345678", "privateDiagnostic": "fixture-private-sentinel"}, 503)
            return
        original_get(handler)
    def instrumented_head(handler):
        if urlparse(handler.path).path in {"/", "/index.html"}:
            html = (ROOT / "index.html").read_text().replace("<head>", "<head>" + TELEMETRY, 1)
            if args.slow_font_ms:
                html = re.sub(r'href="https://fonts.googleapis.com/[^\"]+"', 'href="/__fixture_slow-interface-font.css"', html)
            data = html.encode()
            handler.send_response(200)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            return io.BytesIO(data)
        return original_send_head(handler)
    report = {"scope": "isolated_fixture_not_real_google_acceptance", "realGoogleLoginVerified": False,
              "timingScope": "local navigation including CSS/JS and session validation; excludes real SSO, hosted DB, production cached-shell branch", "slowInterfaceFontMs": args.slow_font_ms, "rows": [], "editor": []}
    with mock.patch.object(QuietAcceptanceHandler, "send_head", instrumented_head), mock.patch.object(QuietAcceptanceHandler, "do_GET", instrumented_get):
        fixture.setUpClass()
        require_local_origin(fixture.origin)
        config = Path(fixture.tmp.name) / "agent-browser.json"
        config.write_text(json.dumps({"allowedDomains": ["127.0.0.1", "fonts.googleapis.com", "fonts.gstatic.com"], "headed": False}))
        browser = Browser(config)
        try:
            for role in args.roles:
                auth = isolated_browser_session(fixture, role)
                browser.run("open", fixture.origin + "/assets/favicon-32.png")
                browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                for device in args.devices:
                    width, height = VIEWPORTS[device]
                    browser.run("set", "viewport", str(width), str(height))
                    for navigation in ("cold" if role == args.roles[0] and device == "desktop" else "cached", "warm"):
                        browser.run("open", fixture.origin + f"/?fixture_navigation={time.monotonic_ns()}#dashboard")
                        browser.until("window.__fixtureTiming?.appInteractiveMs")
                        report.setdefault("navigation", []).append({"role": role, "device": device, "kind": navigation, **browser.evaluate("window.__fixtureTiming")})
                    for route in ROUTES:
                        # Actual navigation handler, preserving permission checks.
                        if device == "mobile" and not browser.evaluate("document.body.classList.contains('mobile-navigation-open')"):
                            browser.run("click", "#mobileMenuButton")
                        if device == "mobile":
                            browser.until("Math.abs(document.querySelector('#primarySidebar').getBoundingClientRect().left)<0.5")
                        allowed = browser.evaluate("(()=>{const e=document.querySelector('.sidebar .nav-item[data-target=" + json.dumps(route) + "]');return !!e&&e.getClientRects().length>0&&!e.disabled})()")
                        if not allowed:
                            report["rows"].append({"role": role, "device": device, "route": route, "access": "not_exposed_by_role", "overflow": False})
                            if device == "mobile":
                                browser.run("click", "#mobileDrawerCloseBtn")
                                browser.until("!document.body.classList.contains('mobile-navigation-open')")
                            continue
                        browser.run("click", '.sidebar .nav-item[data-target="' + route + '"]')
                        browser.until("document.querySelector('.view.active')?.id===" + json.dumps(route))
                        time.sleep(0.4)
                        result = browser.evaluate(AUDIT_JS)
                        filename = f"{role}-{device}-{route}.png"
                        browser.run("screenshot", str(output / filename), "--full")
                        report["rows"].append({"role": role, "device": device, "screenshot": filename, **result})
                    report["editor"].append(editor_case(browser, fixture, auth, role, device, output))
                    if role == args.roles[0]:
                        error_result = browser.evaluate("(async()=>{try{await backendRequest('/fixture-runtime-error');return {failed:false};}catch(error){showToast(error.message);return {failed:true,status:error.status,errorId:error.errorId,message:error.message,visibleToast:document.querySelector('#toast').textContent}}})()")
                        report.setdefault("errorPresentation", []).append({"device": device, **error_result})
                        browser.run("screenshot", str(output / f"{role}-{device}-error-reference.png"))
                    (output / "report.partial.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
                    print(json.dumps({"completed": role, "device": device}), flush=True)
            report["screenshots"] = sum("screenshot" in row for row in report["rows"])
            report["documentOverflowCount"] = sum(row["overflow"] for row in report["rows"])
            return report
        except Exception:
            diagnostics = browser.evaluate("({errors:window.__fixtureErrors,menuOpen:document.body.classList.contains('mobile-navigation-open'),closeButtonRect:document.querySelector('#mobileDrawerCloseBtn')?.getBoundingClientRect().toJSON(),activeElement:document.activeElement?.id,closeBefore:window.__closeBefore,closeObserved:window.__closeObserved,closeStateAtClick:window.__closeStateAtClick})")
            (output / "failure.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2))
            raise
        finally:
            browser.run("close")
            fixture.tearDownClass()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "tests/.artifacts/six-role-browser")
    parser.add_argument("--roles", nargs="+", choices=BROWSER_ROLES, default=list(BROWSER_ROLES))
    parser.add_argument("--devices", nargs="+", choices=VIEWPORTS, default=list(VIEWPORTS))
    parser.add_argument("--slow-font-ms", type=int, default=0)
    args = parser.parse_args()
    # A named browser session must never be driven by two audit processes.
    with open("/tmp/edoc-six-role-browser.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        report = audit(args)
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"report": str(args.output / "report.json"), "screenshots": report["screenshots"], "overflow": report["documentOverflowCount"]}))
    return int(bool(report["documentOverflowCount"] or any(item["status"] != "passed" for item in report["editor"])))


if __name__ == "__main__":
    raise SystemExit(main())
