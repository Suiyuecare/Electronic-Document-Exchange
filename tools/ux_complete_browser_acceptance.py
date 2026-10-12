"""Local-only synthetic UX and latency evidence, never hosted or physical proof.

Each sample is an independent selection of a deidentified two-page A4 PDF.
The real upload-intent request is held until text is truly added in the editor.
No fake successful server response, account impersonation, or external request.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
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
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as Fixture, QuietAcceptanceHandler
from tests.support.five_account_browser_fixture import isolated_browser_session
from tools.six_role_browser_acceptance import TELEMETRY, require_local_origin
from tools.editor_file_resilience_browser_acceptance import TRANSPORT
import tools.backup_drill_browser_acceptance as transport


BRIDGE = transport.PLAYWRIGHT_BRIDGE.replace(
    "else if(command==='press')await page.keyboard.press(args[0]);",
    """else if(command==='press')await page.keyboard.press(args[0]);
  else if(command==='upload')await page.locator(args[0]).setInputFiles(args[1]);
  else if(command==='select')await page.locator(args[0]).selectOption(args[1]);
  else if(command==='media')await page.emulateMedia({reducedMotion:args[0]});
  else if(command==='mouse'){
    if(args[0]==='move')await page.mouse.move(Number(args[1]),Number(args[2]));
    else if(args[0]==='down')await page.mouse.down();else if(args[0]==='up')await page.mouse.up();
  }""",
).replace("waitUntil:'domcontentloaded'", "waitUntil:'commit'").replace("executablePath=process.argv[3]", "executablePath=process.env.EDOC_TEST_BROWSER_PATH||process.argv[3]")


def run(output: Path, samples=30, candidate=""):
    if not 1 <= samples <= 100:
        raise ValueError("samples_out_of_range")
    output = output.resolve(); output.mkdir(parents=True, exist_ok=True)
    candidate = candidate or subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    original = QuietAcceptanceHandler.send_head
    document = (ROOT / "index.html").read_bytes().replace(b"<head>", b"<head>"+TELEMETRY.encode(), 1)

    def head(handler):
        if urlparse(handler.path).path not in {"/", "/index.html"}: return original(handler)
        handler.send_response(200); handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(document))); handler.end_headers(); return io.BytesIO(document)

    record = {"schema_version":1,"candidate_commit":candidate,"environment":"local_isolated","government_exchange":"DISABLED","profiles":[],"samples":[]}
    report = {"scope":"loopback_synthetic_browser","hostedVerified":False,"physicalDeviceVerified":False,"humanSSOVerified":False,"sourceAppSha256":hashlib.sha256((ROOT / "app.js").read_bytes()).hexdigest(),"cases":[],"stage":"setup"}
    browser = None
    headless = Path.home()/"Library/Caches/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell"
    browser_env = {"EDOC_TEST_BROWSER_PATH":str(headless)} if headless.is_file() else {}
    with mock.patch.object(QuietAcceptanceHandler,"send_head",head), mock.patch.object(transport,"PLAYWRIGHT_BRIDGE",BRIDGE), mock.patch.dict(os.environ,browser_env):
        Fixture.setUpClass(); require_local_origin(Fixture.origin)
        try:
            browser = transport.LocalPlaywrightBrowser(Fixture.origin)
            auth = isolated_browser_session(Fixture,"staff")
            for ordinal,(device,width,height) in enumerate((("desktop",1440,1000),("tablet",900,1100),("phone",390,844)),1):
                profile=f"P-{ordinal:03d}";record["profiles"].append({"id":profile,"device":device,"network":"loopback","physical_device":False})
                for index in range(samples):
                    label=f"{device}-{index+1:02d}";report["stage"]=label
                    path=output/f"synthetic-{label}.pdf"
                    writer=canvas.Canvas(str(path),pagesize=A4)
                    for page in range(2): writer.drawString(60,780,f"SYNTHETIC ACCEPTANCE {label} page {page+1}");writer.showPage()
                    writer.save()
                    row={"case":label,"passed":False}
                    selected_at=None
                    try:
                        print(json.dumps({"case":label,"stage":"open"}),flush=True)
                        browser.run("open",Fixture.origin+"/assets/favicon-32.png")
                        browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session',"+json.dumps(json.dumps(auth))+");true")
                        browser.run("set","viewport",str(width),str(height));browser.run("media","reduce" if index==0 else "no-preference")
                        browser.run("open",Fixture.origin+f"/?ux={time.monotonic_ns()}#electronicSeal")
                        browser.until("window.__fixtureTiming?.appInteractiveMs&&document.querySelector('#uploadedSealApprovalCategorySelect')?.options.length>1&&!uploadedSealEditorRuntime.directoryLoading",timeout=40)
                        print(json.dumps({"case":label,"stage":"interactive"}),flush=True)
                        browser.evaluate("window.__raceRealFetch=window.fetch;true")
                        browser.evaluate(TRANSPORT)
                        browser.evaluate("setView('dashboard');true")
                        browser.until("activeRouteTarget==='dashboard'")
                        browser.evaluate("window.__uxWorkspaceSamples=uiPerformanceWindow.samples.filter(s=>s.stage==='workspace_visible').length;setView('electronicSeal');true")
                        browser.until("uiPerformanceWindow.samples.filter(s=>s.stage==='workspace_visible').length>window.__uxWorkspaceSamples")
                        workspace_ms=browser.evaluate("uiPerformanceWindow.samples.filter(s=>s.stage==='workspace_visible').at(-1).durationMs")
                        category=browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(e=>e.textContent.includes('服務委託合約')).value")
                        browser.run("select","#uploadedSealApprovalCategorySelect",category)
                        browser.run("fill","#uploadedSealTitle","合成完整驗收 "+label);browser.run("fill","#uploadedSealReason","隔離驗收，無真實個資。")
                        browser.evaluate("window.__raceRules.push({key:'intent',method:'POST',pattern:'/official-documents/[^/]+/editor-uploads$',when:'before'});true")
                        browser.run("upload","#uploadedSealPdfInput",str(path))
                        browser.until("!!window.__raceHolds.intent&&uploadedSealEditorState.pages.length===2&&!uploadedSealEditorRuntime.uploading&&document.querySelector('#uploadedPdfCanvas').width>0",timeout=45)
                        local_ms=browser.evaluate("uploadedSealEditorRuntime.lastEditorReadyMs")
                        print(json.dumps({"case":label,"stage":"local_editable"}),flush=True)
                        row["editableBeforeIntent"]=browser.evaluate("window.__raceHolds.intent.row.status===null&&document.querySelector('#submitUploadedSealBtn').disabled&&uploadedSealEditorState.sourceFiles.every(s=>s.assetId.startsWith('LOCAL-'))")
                        text="合成尚未同步文字 "+label;browser.add_pdf_text(text)
                        row["actualTextBeforeIntent"]=browser.evaluate("uploadedSealEditorState.elements.some(e=>e.properties?.text==="+json.dumps(text)+")")
                        if index==0:
                            row.update(check_modal(browser))
                            browser.click_visible("#electronicSeal .workspace-quick-guide summary")
                            row["guidanceActuallyOpened"]=browser.evaluate("document.querySelector('#electronicSeal .workspace-quick-guide').open")
                            row["narrowNoPageOverflow"]=browser.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                            row["reducedMotionApplied"]=browser.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
                        browser.evaluate("window.__raceHolds.intent.release();true")
                        browser.until("!uploadedSealEditorRuntime.finalizingAsset&&!uploadedSealEditorRuntime.saving&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration",timeout=60)
                        state=Fixture._expect_json("GET","/api/official-documents/"+browser.evaluate("uploadedSealEditorRuntime.documentId")+"/editor-state",200,token=auth["token"])["state"]
                        row["savedText"]=any((element.get("properties") or {}).get("text")==text for element in state["elements"])
                        row["noLocalAssetsSaved"]=all(not source["assetId"].startswith("LOCAL-") for source in state["sourceFiles"])
                        cloud_ms=browser.evaluate("uiPerformanceWindow.samples.filter(s=>s.stage==='pdf_cloud_saved').at(-1)?.durationMs")
                        row["errorsEmpty"]=browser.evaluate("window.__fixtureErrors.length===0")
                        row["passed"]=all(value is True for key,value in row.items() if key not in {"case","passed"})
                        for metric,document_profile,duration,bytes_,pages in (("workspace_interactive","workspace",workspace_ms,0,0),("pdf_editable","typical_a4",local_ms,path.stat().st_size,2),("cloud_saved","typical_a4",cloud_ms,path.stat().st_size,2)):
                            record["samples"].append({"id":f"S-{len(record['samples'])+1:04d}","profile_id":profile,"metric":metric,"document_profile":document_profile,"cache_state":"warm","duration_ms":duration,"outcome":"success" if row["passed"] else "error","bytes":bytes_,"pages":pages,"recorded_at":datetime.now(timezone.utc).isoformat()})
                        if index==0: browser.run("screenshot",str(output/f"{device}-acceptance.png"))
                    except Exception as error:
                        row["errorCode"]=type(error).__name__;report["lastCommand"]=browser.last_command
                        # Only fixed runtime state/counters, never auth or business text.
                        try: report["lastState"]=browser.evaluate("({ready:document.readyState,app:typeof uploadedSealEditorRuntime,errors:window.__fixtureErrors?.length||0})")
                        except Exception: pass
                        try: browser.run("screenshot",str(output/f"{label}-failed.png"))
                        except Exception: pass
                    report["cases"].append(row)
                    (output/"latency-record.json").write_text(json.dumps(record,ensure_ascii=False,indent=2))
                    (output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
                    print(json.dumps(row,ensure_ascii=False),flush=True)
                    if not row["passed"]: raise RuntimeError("fixture_acceptance_failed")
        finally:
            try:
                if browser:
                    try: browser.run("close")
                    except RuntimeError: browser._stop()
            finally: Fixture.tearDownClass()
    report["passed"]=all(row["passed"] for row in report["cases"])
    (output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2));return report


def check_modal(browser):
    """Use the shipping delete action, real keyboard and IME event sequence."""
    browser.evaluate("window.__uxCommits=0;const commit=commitUploadedEditorMutation;commitUploadedEditorMutation=(...args)=>{const result=commit(...args);if(result)window.__uxCommits++;return result;};window.__uxDeleteBefore=canonicalEditorJson(uploadedSealEditorState);true")
    if browser.evaluate("document.querySelector('#uploadedEditorThumbnailToggleBtn').getAttribute('aria-expanded')!=='true'"):
        browser.click_visible("#uploadedEditorThumbnailToggleBtn")
    trigger='#uploadedEditorPageActions [data-editor-page-action="delete"]'
    browser.click_visible(trigger);browser.until("!document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')")
    focused=browser.evaluate("document.activeElement.id==='workspaceTypedConfirmCancelBtn'")
    for _ in range(5):
        browser.run("press","Tab")
        if not browser.evaluate("document.querySelector('#workspaceTypedConfirmModal').contains(document.activeElement)"): raise AssertionError("modal_focus_escaped")
    browser.run("press","Escape")
    browser.until("document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')")
    cancelled=browser.evaluate("window.__uxCommits===0&&window.__uxDeleteBefore===canonicalEditorJson(uploadedSealEditorState)")
    browser.click_visible(trigger);browser.click_visible("#workspaceTypedConfirmSubmitBtn")
    browser.until("uploadedSealEditorState.pages.length===1")
    once=browser.evaluate("window.__uxCommits===1")
    browser.click_visible("#uploadedEditorThumbnailCloseBtn")
    browser.click_visible("#uploadedEditorUndoBtn");browser.until("uploadedSealEditorState.pages.length===2")
    browser.evaluate("window.__uxReason=null;void requestWorkspaceDecision('合成補正','取消不得有異動',{reason:true}).then(value=>{window.__uxReason=value;});true")
    browser.until("!document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')")
    browser.evaluate("(()=>{const e=document.querySelector('#workspaceTypedConfirmInput');e.focus();e.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));e.value='合成補正原因';e.dispatchEvent(new Event('input',{bubbles:true}));return true})()")
    browser.run("press","Escape")
    ime=browser.evaluate("!document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')&&document.querySelector('#workspaceTypedConfirmSubmitBtn').disabled")
    browser.evaluate("document.querySelector('#workspaceTypedConfirmInput').dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));true")
    browser.run("press","Escape");browser.until("document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')")
    return {"cancelDefaultFocus":focused,"cancelZeroMutations":cancelled,"confirmOneMutation":once,"imeEscapeSafe":ime}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--output",type=Path,required=True);parser.add_argument("--samples",type=int,default=30);parser.add_argument("--candidate-commit",default="")
    args=parser.parse_args();raise SystemExit(0 if run(args.output,args.samples,args.candidate_commit)["passed"] else 1)
