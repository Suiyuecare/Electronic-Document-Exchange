"""Five editor race journeys through real localhost UI and synthetic HTTP data.

No hosted service, Google login, actual company seal or government exchange is
contacted. Delays wrap the real fetch transport; they never fabricate a success
or conflict response. Mouse and touch interactions use Chromium's input driver;
emulated touch is not physical-device acceptance.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import subprocess
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


TRANSPORT = r"""(()=>{
 window.__raceRealFetch=window.fetch;window.__raceRules=[];window.__raceHolds={};window.__raceRequests=[];
 window.fetch=async (...args)=>{
  const u=new URL(args[0]?.url||String(args[0]),location.href);
  const method=String(args[1]?.method||args[0]?.method||'GET').toUpperCase();
  const row={method,path:u.pathname,status:null};window.__raceRequests.push(row);
  const rule=window.__raceRules.find(r=>!r.used&&r.method===method&&r.path===u.pathname);
  const hold=async()=>{rule.used=true;await new Promise(resolve=>{window.__raceHolds[rule.key]={release:resolve}})};
  if(rule?.when==='before')await hold();
  const response=await window.__raceRealFetch(...args);row.status=response.status;
  if(rule?.when==='after')await hold();
  return response;
 };return true;
})()"""

NATIVE_TOUCH = r"""
const input=JSON.parse(await new Promise(resolve=>{let value='';process.stdin.on('data',part=>value+=part);process.stdin.on('end',()=>resolve(value))}));
if(!/^ws:\/\/127\.0\.0\.1:\d+\//.test(input.cdpUrl))throw Error('local_cdp_required');
const ws=new WebSocket(input.cdpUrl);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject});
let next=1;const pending=new Map();
ws.onmessage=event=>{const message=JSON.parse(event.data);const entry=pending.get(message.id);if(entry){pending.delete(message.id);message.error?entry.reject(Error(message.error.message)):entry.resolve(message.result)}};
const command=(method,params={},sessionId)=>new Promise((resolve,reject)=>{const id=next++;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}))});
try{
 const {targetInfos}=await command('Target.getTargets');const target=targetInfos.find(t=>t.type==='page'&&t.url===input.url);if(!target)throw Error('local_page_target_missing');
 const {sessionId}=await command('Target.attachToTarget',{targetId:target.targetId,flatten:true});
 await command('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:2},sessionId);
 const p=input.point,first={id:901,x:p.x,y:p.y},moved={id:901,x:p.x+35,y:p.y+24},second={id:902,x:p.x+100,y:p.y+60};
 const send=(type,touchPoints)=>command('Input.dispatchTouchEvent',{type,touchPoints},sessionId);
 await send('touchStart',[first]);await send('touchMove',[moved]);
 await command('Runtime.evaluate',{expression:'window.__racePinchMoved={...uploadedSealEditorState.elements.find(e=>e.id==='+JSON.stringify(input.elementId)+')};true'},sessionId);
 await send('touchStart',[moved,second]);await send('touchMove',[moved,{...second,x:second.x+20,y:second.y+10}]);
 await send('touchEnd',[moved]);await send('touchEnd',[]);
 await command('Target.detachFromTarget',{sessionId});
 process.stdout.write(JSON.stringify({nativeTouchDispatched:true}));
}finally{ws.close()}
"""


def source_at(ref: str, path: str) -> bytes:
    if not ref:
        return (ROOT / path).read_bytes()
    if not all(character.isalnum() or character in "/_.-" for character in ref):
        raise ValueError("invalid_source_ref")
    return subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT, check=True, capture_output=True).stdout


class Journey:
    def __init__(self, fixture, browsers, output):
        self.fixture, self.a, self.b, self.output = fixture, *browsers, output
        self.auth = isolated_browser_session(fixture, "staff")

    def login(self, browser, auth=None, width=1440, height=1000):
        auth = auth or self.auth
        browser.run("open", self.fixture.origin + "/assets/favicon-32.png")
        browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
        browser.run("set", "viewport", str(width), str(height))
        browser.run("open", self.fixture.origin + f"/?race={time.monotonic_ns()}#electronicSeal")
        browser.until("window.__fixtureTiming?.appInteractiveMs&&document.querySelector('#uploadedSealApprovalCategorySelect')?.options.length>1")
        browser.run("snapshot", "-i")
        browser.run("screenshot", str(self.output / f"ready-{browser.session}.png"))
        if not browser.evaluate("document.body.innerText.trim().length>0&&!document.querySelector('.vite-error-overlay,[data-nextjs-dialog]')"):
            raise AssertionError("browser_page_verification_failed")
        browser.evaluate(TRANSPORT)

    def upload(self, browser, name):
        category = browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(e=>e.textContent.includes('服務委託合約')).value")
        browser.run("select", "#uploadedSealApprovalCategorySelect", category)
        browser.run("fill", "#uploadedSealTitle", "合成競態驗收 " + name)
        browser.run("fill", "#uploadedSealReason", "去識別化 localhost 測試，沒有正式業務資料。")
        path = self.output / f"synthetic-{name}.pdf"
        writer = canvas.Canvas(str(path), pagesize=A4)
        writer.drawString(60, 780, "SYNTHETIC EDITOR RACE FIXTURE - " + name)
        writer.showPage(); writer.save()
        browser.run("upload", "#uploadedSealPdfInput", str(path))
        browser.until("uploadedSealEditorState.pages.length===1&&!uploadedSealEditorRuntime.uploading&&!uploadedSealEditorRuntime.finalizingAsset&&!uploadedSealEditorRuntime.saving&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration", timeout=40)
        return browser.evaluate("uploadedSealEditorRuntime.documentId")

    def detail(self, document_id):
        return self.fixture._expect_json("GET", f"/api/official-documents/{document_id}", 200, token=self.auth["token"])

    def state(self, document_id):
        return self.fixture._expect_json("GET", f"/api/official-documents/{document_id}/editor-state", 200, token=self.auth["token"])["state"]

    def expose_fields(self, browser):
        if browser.evaluate("document.querySelector('#uploadedSealApplicationFields').hidden"):
            browser.click_visible("#uploadedSealApplicationToggleBtn")

    def open_case(self, browser, document_id, wait=True):
        if not browser.evaluate("document.querySelector('#electronicSealWorkQueue').open"):
            browser.click_visible("#electronicSealWorkQueue > summary")
        browser.until("!!document.querySelector('[data-electronic-seal-open=" + json.dumps(document_id) + "]')")
        browser.click_visible(f'[data-electronic-seal-open="{document_id}"]')
        if wait:
            browser.until("uploadedSealEditorRuntime.documentId===" + json.dumps(document_id) + "&&!uploadedSealApplicationRuntime.openPromise&&!uploadedSealEditorRuntime.uploading", timeout=35)

    def hold(self, browser, key, method, path, when="after"):
        browser.evaluate("window.__raceRules.push(" + json.dumps({"key": key, "method": method, "path": path, "when": when}) + ");true")

    def held(self, browser, key):
        browser.until("!!window.__raceHolds[" + json.dumps(key) + "]", timeout=35)

    def release(self, browser, key):
        browser.evaluate("window.__raceHolds[" + json.dumps(key) + "].release();true")

    def saved(self, browser):
        browser.until("!uploadedSealEditorRuntime.saving&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration&&!uploadedSealApplicationRuntime.promise", timeout=35)

    def add_seal(self, browser):
        browser.click_visible('#uploadedPdfEditor [data-editor-tool="seal"]')
        browser.until("uploadedSealEditorRuntime.tool==='seal'")
        browser.click_visible("#addSelectedStampBtn")
        browser.until("uploadedSealEditorState.elements.some(e=>e.kind==='seal')")
        self.saved(browser)
        browser.click_visible('#uploadedPdfEditor [data-editor-tool="select"]')
        return browser.evaluate("uploadedSealEditorState.elements.find(e=>e.kind==='seal').id")

    def element_point(self, browser, element_id):
        selector = f'[data-editor-element-id="{element_id}"]'
        browser.evaluate("document.querySelector(" + json.dumps(selector) + ").scrollIntoView({block:'center',behavior:'instant'});true")
        return browser.evaluate("(()=>{const e=document.querySelector(" + json.dumps(selector) + "),r=e.getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()")

    def finish(self, name, browser, checks, evidence=None):
        layout = browser.evaluate(AUDIT_JS)
        checks["noBrowserErrors"] = not layout["errors"]
        checks["noOverflow"] = not layout["overflow"]
        browser.run("screenshot", str(self.output / (name + ".png")), "--full")
        return {"name": name, "passed": all(checks.values()), "checks": checks, "evidence": evidence or {}}

    def metadata(self):
        self.login(self.a)
        document_id = self.upload(self.a, "metadata")
        self.login(self.b); self.open_case(self.b, document_id)
        self.expose_fields(self.a); self.expose_fields(self.b)
        title = "合成 A 分頁已保存的新主旨"
        self.a.run("fill", "#uploadedSealTitle", title)
        self.a.until("!uploadedSealApplicationRuntime.promise&&!uploadedSealApplicationHasUnsavedChanges()", timeout=25)
        confirmed = self.detail(document_id)
        local_reason = "合成 B 分頁需要保留的未保存原因"
        self.b.run("fill", "#uploadedSealReason", local_reason)
        self.b.until("window.__raceRequests.some(r=>r.method==='PATCH'&&r.path===" + json.dumps(f"/api/official-documents/{document_id}") + "&&r.status!==null)")
        self.b.until("!uploadedSealApplicationRuntime.promise")
        latest = self.detail(document_id)
        time.sleep(2.1)
        rows = self.b.evaluate("window.__raceRequests.filter(r=>r.method==='PATCH')")
        checks = {"staleMetadataReal409": rows[-1]["status"] == 409,
                  "newerTitlePreserved": latest["title"] == title,
                  "revisionNotAdvancedByStaleWriter": latest["content_revision"] == confirmed["content_revision"],
                  "localReasonStillVisible": self.b.evaluate("document.querySelector('#uploadedSealReason').value===" + json.dumps(local_reason)),
                  "localStillUnsaved": self.b.evaluate("uploadedSealApplicationHasUnsavedChanges()"),
                  "noAutomaticRetry": len(rows) == 1}
        return self.finish("metadata-stale-tab", self.b, checks, {"httpStatuses": [row["status"] for row in rows]})

    def confirm(self):
        self.login(self.a)
        document_id = self.upload(self.a, "confirm")
        self.add_seal(self.a)
        self.a.click_visible("#submitUploadedSealBtn")
        self.a.until("uploadedSealEditorRuntime.reviewMode==='prepared'&&!uploadedSealApplicationRuntime.submissionBusy", timeout=40)
        first_preview = self.a.evaluate("({revisionId:uploadedSealEditorRuntime.revisionId,manifest:uploadedSealEditorState.manifestSha256,fileId:uploadedSealEditorRuntime.preparedFileId,sha256:uploadedSealEditorRuntime.preparedSha256})")
        # Concurrent preflight only, never a direct submit/approval API call.
        # Reuse the exact revision to reproduce two immutable confirmation
        # assets for one revision without manufacturing any server response.
        second_preview = self.fixture._expect_json("POST", f"/api/official-documents/{document_id}/editor-preflight", 201, token=self.auth["token"], json_body={"editorRevisionId": first_preview["revisionId"], "manifestSha256": first_preview["manifest"]})
        self.a.click_visible("#submitUploadedSealBtn")
        self.a.until("!uploadedSealApplicationRuntime.submissionBusy", timeout=40)
        first = self.detail(document_id)
        first_step = next((step for step in first["approval_steps"] if step["step_key"] == first["current_step"] and step["status"] == "pending"), None)
        locked = first.get("stamp_request") or {}
        locked_state = self.fixture._expect_json("GET", f"/api/official-documents/{document_id}/editor-state", 200, token=self.auth["token"])
        checks = {"twoPreviewsForOneRevision": second_preview["editorRevisionId"] == first_preview["revisionId"] and second_preview["preparedFileId"] != first_preview["fileId"],
                  "firstReviewPending": bool(first_step and first["current_status"].startswith("pending_")),
                  "submissionLockedDisplayedFirstPdf": locked.get("prepared_file_id") == first_preview["fileId"],
                  "getStateReturnsLockedFirstPdf": locked_state.get("preparedFileId") == first_preview["fileId"] and locked_state.get("preparedSha256") == first_preview["sha256"]}
        if first_step:
            reviewer_auth = isolated_browser_session(self.fixture, "section_chief")
            self.login(self.a, reviewer_auth)
            self.open_case(self.a, document_id)
            checks["firstManagerReviewReadOnly"] = self.a.evaluate("uploadedSealEditorRuntime.locked&&uploadedSealEditorState.pages.length===1")
            reviewed = self.fixture._expect_json("GET", f"/api/official-documents/{document_id}", 200, token=reviewer_auth["token"])
            checks["managerSeesSamePreparedPdf"] = (reviewed.get("stamp_request") or {}).get("prepared_file_id") == locked.get("prepared_file_id")
            checks["managerEditorBindsLockedFirstPdf"] = self.a.evaluate("uploadedSealEditorRuntime.preparedFileId===" + json.dumps(first_preview["fileId"]))
            self.a.click_visible('.sidebar .nav-item[data-target="approvalLog"]')
            self.a.until("document.querySelector('.view.active')?.id==='approvalLog'")
            self.a.until("!!document.querySelector('[data-approval-log-select=" + json.dumps(document_id) + "]')")
            self.a.click_visible(f'[data-approval-log-select="{document_id}"]')
            self.a.until("!!document.querySelector('[data-progress-official-action=approve][data-progress-official-id=" + json.dumps(document_id) + "]')")
            self.a.click_visible(f'[data-progress-official-action="approve"][data-progress-official-id="{document_id}"]')
            self.a.until("!document.querySelector('#officialDecisionModal').classList.contains('hidden')")
            self.a.click_visible('#officialDecisionModal [data-decision-evidence="editor"]')
            self.a.until("window.__raceRequests.some(r=>r.path===" + json.dumps(f"/api/official-documents/{document_id}/files/{first_preview['fileId']}/download") + "&&r.status===200)")
            checks["managerDecisionEvidenceDownloadsLockedFirstPdf"] = True
            checks["managerDidNotDownloadUnsubmittedSecondPdf"] = not self.a.evaluate("window.__raceRequests.some(r=>r.path===" + json.dumps(f"/api/official-documents/{document_id}/files/{second_preview['preparedFileId']}/download") + ")")
            self.a.click_visible("#officialDecisionModalCloseBtn")
        return self.finish("confirmation-concurrent-previews", self.a, checks, {"secondClientScope": "real_http_preflight_same_revision_not_direct_submission", "firstStep": (first_step or {}).get("step_key")})

    def drag_save(self):
        self.login(self.a)
        document_id = self.upload(self.a, "drag")
        element_id = self.add_seal(self.a)
        initial = next(e for e in self.state(document_id)["elements"] if e["id"] == element_id)
        self.hold(self.a, "drag-save", "PUT", f"/api/official-documents/{document_id}/editor-state")
        # First move schedules the real save. Its response is then delayed while
        # a second, uncommitted drag is active.
        point = self.element_point(self.a, element_id)
        self.a.run("mouse", "move", str(point["x"]), str(point["y"])); self.a.run("mouse", "down")
        self.a.run("mouse", "move", str(point["x"] + 25), str(point["y"] + 20)); self.a.run("mouse", "up")
        self.held(self.a, "drag-save")
        point = self.element_point(self.a, element_id)
        self.a.run("mouse", "move", str(point["x"]), str(point["y"])); self.a.run("mouse", "down")
        self.a.run("mouse", "move", str(point["x"] + 40), str(point["y"] + 30))
        moved = self.a.evaluate("({...uploadedSealEditorState.elements.find(e=>e.id===" + json.dumps(element_id) + ")})")
        self.release(self.a, "drag-save")
        self.a.until("!uploadedSealEditorRuntime.saving")
        visible = self.a.evaluate("uploadedSealEditorState.elements.find(e=>e.id===" + json.dumps(element_id) + ")")
        self.a.run("mouse", "up"); self.saved(self.a)
        stored = next(e for e in self.state(document_id)["elements"] if e["id"] == element_id)
        checks = {"dragActuallyMoved": (moved["x"], moved["y"]) != (initial["x"], initial["y"]),
                  "lateSaveDidNotReplaceActiveDrag": (visible["x"], visible["y"]) == (moved["x"], moved["y"]),
                  "dragEndPersistedExactCoordinates": (stored["x"], stored["y"]) == (moved["x"], moved["y"])}
        return self.finish("drag-during-save", self.a, checks)

    def pinch(self):
        self.login(self.a, width=390, height=844)
        document_id = self.upload(self.a, "pinch")
        element_id = self.add_seal(self.a)
        initial = next(e for e in self.state(document_id)["elements"] if e["id"] == element_id)
        point = self.element_point(self.a, element_id)
        cdp = self.a.run("get", "cdp-url")["cdpUrl"]
        native = subprocess.run(["node", "--input-type=module", "-e", NATIVE_TOUCH], input=json.dumps({"cdpUrl": cdp, "url": self.a.evaluate("location.href"), "point": point, "elementId": element_id}), text=True, capture_output=True, timeout=20)
        if native.returncode:
            raise RuntimeError("browser_native_touch_failed")
        time.sleep(2.2)
        self.saved(self.a)
        moved = self.a.evaluate("window.__racePinchMoved")
        stored = next(e for e in self.state(document_id)["elements"] if e["id"] == element_id)
        checks = {"singleFingerMovedBeforePinch": (moved["x"], moved["y"]) != (initial["x"], initial["y"]),
                  "prePinchMovementPersisted": (stored["x"], stored["y"]) == (moved["x"], moved["y"]),
                  "touchPointersReleased": self.a.evaluate("uploadedSealEditorRuntime.touchPointers.size===0")}
        return self.finish("single-touch-to-pinch", self.a, checks, {"inputScope": "native_chromium_touch_emulation_not_physical_device"})

    def open_delay(self):
        self.login(self.b)
        new_id = self.upload(self.b, "open-new")
        self.login(self.a)
        old_id = self.upload(self.a, "open-old")
        self.expose_fields(self.a)
        self.hold(self.a, "open-delay", "GET", f"/api/official-documents/{new_id}/editor-state")
        self.open_case(self.a, new_id, wait=False)
        self.held(self.a, "open-delay")
        disabled = self.a.evaluate("document.querySelector('#uploadedSealReason').disabled")
        late_reason = "合成舊案載入期間的未保存文字"
        if not disabled:
            # The real form's input handler, not direct application-state mutation.
            self.a.evaluate("(()=>{const e=document.querySelector('#uploadedSealReason');e.value=" + json.dumps(late_reason) + ";e.dispatchEvent(new Event('input',{bubbles:true}));return true})()")
        self.release(self.a, "open-delay")
        self.a.until("!uploadedSealApplicationRuntime.openPromise", timeout=40)
        old = self.detail(old_id)
        current_id = self.a.evaluate("uploadedSealEditorRuntime.documentId")
        local_reason = self.a.evaluate("document.querySelector('#uploadedSealReason').value")
        preserved = disabled or old["request_reason"] == late_reason or (current_id == old_id and local_reason == late_reason)
        checks = {"oldEditsBlockedOrPreserved": preserved,
                  "newCaseEventuallyOpenedOrSafelyAborted": current_id in {old_id, new_id},
                  "noOpenPromiseLeak": self.a.evaluate("!uploadedSealApplicationRuntime.openPromise")}
        return self.finish("open-new-with-delayed-get", self.a, checks, {"oldInputsLockedDuringGet": disabled, "eventualCase": "new" if current_id == new_id else "old"})


def run(output: Path, *, app_ref="", cases=None):
    output = output.resolve(); output.mkdir(parents=True, exist_ok=True)
    fixture = FiveAccountHttpAcceptanceTest
    original_head = QuietAcceptanceHandler.send_head
    frozen_app = source_at(app_ref, "app.js") if app_ref else None
    instrumented_html = source_at(app_ref, "index.html").replace(b"<head>", b"<head>" + TELEMETRY.encode(), 1)
    def head(handler):
        path = urlparse(handler.path).path
        if path in {"/", "/index.html"}:
            data = instrumented_html
            mime = "text/html; charset=utf-8"
        elif path == "/app.js" and frozen_app is not None:
            data, mime = frozen_app, "application/javascript; charset=utf-8"
        else:
            return original_head(handler)
        handler.send_response(200); handler.send_header("Content-Type", mime)
        handler.send_header("Content-Length", str(len(data))); handler.end_headers()
        return io.BytesIO(data)
    report = {"scope": "isolated_local_real_ui_http_no_production_mutation", "appRef": app_ref or "working-tree", "journeys": [], "physicalTouchVerified": False}
    with mock.patch.object(QuietAcceptanceHandler, "send_head", head):
        fixture.setUpClass(); require_local_origin(fixture.origin)
        config = Path(fixture.tmp.name) / "race-browser.json"
        config.write_text(json.dumps({"headed": False}))
        suffix = f"{time.monotonic_ns():x}"[-9:]
        browsers = [Browser(config, session=f"edoc-race-{name}-{suffix}", namespace="edoc-editor-race-isolated") for name in ("a", "b")]
        try:
            journey = Journey(fixture, browsers, output)
            methods = {"metadata": journey.metadata, "confirm": journey.confirm, "drag": journey.drag_save, "pinch": journey.pinch, "open": journey.open_delay}
            for name in cases or methods:
                try:
                    result = methods[name]()
                except Exception as error:
                    result = {"name": name, "passed": False, "errorCode": str(error) if str(error).startswith(("browser_", "invalid_")) else type(error).__name__}
                    try:
                        result["failureState"] = journey.a.evaluate("({pageCount:uploadedSealEditorState.pages.length,save:document.querySelector('#uploadedEditorSaveStatus')?.textContent,toast:document.querySelector('#toast')?.textContent,errors:window.__fixtureErrors})")
                        journey.a.run("screenshot", str(output / f"{name}-failed.png"), "--full")
                    except Exception:
                        pass
                report["journeys"].append(result)
                (output / "report.partial.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
                print(json.dumps({"case": name, "passed": result["passed"], "checks": result.get("checks", {}), "errorCode": result.get("errorCode")}), flush=True)
            report["passed"] = all(row["passed"] for row in report["journeys"])
        finally:
            for browser in browsers:
                try: browser.run("close")
                except Exception: pass
            fixture.tearDownClass()
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--app-ref", default="")
    parser.add_argument("--cases", nargs="+", choices=("metadata", "confirm", "drag", "pinch", "open"))
    arguments = parser.parse_args()
    raise SystemExit(0 if run(arguments.output, app_ref=arguments.app_ref, cases=arguments.cases)["passed"] else 1)
