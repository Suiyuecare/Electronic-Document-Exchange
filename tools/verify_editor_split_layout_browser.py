"""Synthetic electronic-seal split-layout browser acceptance; never submits.

The baseline option serves committed markup/styles for equivalent Before/After
evidence. All uploads, sessions and API readback use isolated local fixtures.
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
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from tools.six_role_browser_acceptance import Browser, TELEMETRY, require_local_origin
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler

LAYOUT_JS = """(()=>{
 const rect=s=>{const e=document.querySelector(s),r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom,scrollWidth:e.scrollWidth,clientWidth:e.clientWidth}};
 const a=rect('#uploadedSealApplicationPanel'),e=rect('#uploadedPdfEditor'),c=rect('.pdf-editor-canvas-column'),s=rect('.pdf-editor-shell');
 return {width:innerWidth,application:a,editor:e,canvas:c,shell:s,ratio:e.width/(a.width+e.width),sideBySide:Math.abs(a.y-e.y)<2&&e.x>a.right,
 overflow:document.documentElement.scrollWidth>innerWidth+1,editorOverflow:s.scrollWidth>s.clientWidth+1,
 errors:window.__fixtureErrors||[],fieldValues:[...document.querySelectorAll('#uploadedSealApplicationFields input,#uploadedSealApplicationFields select,#uploadedSealApplicationFields textarea')].map(e=>e.value),
 missingActions:['#uploadedPdfReplaceBtn','#submitUploadedSealBtn'].filter(s=>!document.querySelector(s)),
 stageVisible:document.querySelector('#uploadedPdfStage').getBoundingClientRect().width>0};})()"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    baseline = {}
    if args.baseline:
        for name in ("index.html", "styles.css"):
            baseline[name] = subprocess.check_output(["git", "show", "HEAD:" + name], cwd=ROOT)
    original_head = QuietAcceptanceHandler.send_head

    def instrument(handler):
        path = urlparse(handler.path).path
        name = "index.html" if path in {"/", "/index.html"} else path.lstrip("/")
        if name == "index.html" or name in baseline:
            data = baseline.get(name) or (ROOT / name).read_bytes()
            if name == "index.html":
                data = data.replace(b"<head>", ("<head>" + TELEMETRY).encode(), 1)
            handler.send_response(200)
            handler.send_header("Content-Type", "text/css" if name.endswith(".css") else "text/html; charset=utf-8")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            return io.BytesIO(data)
        return original_head(handler)

    report = {"scope": "isolated_fixture_no_submission_no_real_seals", "baseline": args.baseline, "layouts": [], "checks": {}}
    fixture = FiveAccountHttpAcceptanceTest
    with mock.patch.object(QuietAcceptanceHandler, "send_head", instrument):
        fixture.setUpClass()
        require_local_origin(fixture.origin)
        config = Path(fixture.tmp.name) / "browser.json"
        config.write_text(json.dumps({"allowedDomains": ["127.0.0.1", "fonts.googleapis.com", "fonts.gstatic.com"], "headed": False}))
        browser = Browser(config, session="editor-split-0913", namespace="editor-split-0913")
        try:
            auth = isolated_browser_session(fixture, "staff")
            browser.run("open", fixture.origin + "/assets/favicon-32.png")
            browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
            browser.run("set", "viewport", "1440", "1000")
            browser.run("open", fixture.origin + f"/?editor_split={time.monotonic_ns()}#electronicSeal")
            browser.until("window.__fixtureTiming?.appInteractiveMs&&document.querySelector('#uploadedSealApprovalCategorySelect')?.options.length>1")
            browser.run("snapshot", "-i")
            report["checks"]["meaningfulPageWithoutOverlay"] = browser.evaluate("document.querySelector('.view.active')?.id==='electronicSeal'&&!document.querySelector('[data-nextjs-dialog],.vite-error-overlay')&&window.__fixtureErrors.length===0")
            category = browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(e=>e.textContent.includes('合作意向書')).value")
            browser.run("select", "#uploadedSealApprovalCategorySelect", category)
            browser.run("fill", "#uploadedSealTitle", "年度合作文件用印（合成測試）")
            browser.run("fill", "#uploadedSealReason", "版面驗收用合成文件；不送簽、不用印、不寄發。")
            expected_fields = browser.evaluate(LAYOUT_JS)["fieldValues"]
            for state in ("empty", "loaded", "selected"):
                if state == "loaded":
                    pdf = Path(fixture.tmp.name) / "synthetic-layout.pdf"
                    writer = canvas.Canvas(str(pdf), pagesize=A4)
                    for number, size in enumerate((A4, landscape(A4)), 1):
                        writer.setPageSize(size)
                        writer.drawString(50, size[1] - 65, f"SYNTHETIC A4 PAGE {number}")
                        writer.showPage()
                    writer.save()
                    browser.run("upload", "#uploadedSealPdfInput", str(pdf))
                    browser.until("uploadedSealEditorState.pages.length===2&&!uploadedSealEditorRuntime.uploading")
                elif state == "selected":
                    browser.click_visible('#uploadedPdfEditor [data-editor-tool="text"]')
                    browser.run("fill", "#uploadedSealTextInput", "合成測試文字")
                    browser.click_visible("#addUploadedTextBtn")
                    browser.until("uploadedSealEditorState.elements.some(e=>e.kind==='text')&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration&&!uploadedSealEditorRuntime.saving")
                for width in (1920, 1440, 1280, 900, 760, 430, 390, 375):
                    browser.run("set", "viewport", str(width), "844" if width < 821 else "1000")
                    if width <= 760:
                        browser.until("!document.body.classList.contains('mobile-navigation-open')&&document.querySelector('#primarySidebar').getBoundingClientRect().right<=1")
                    browser.evaluate("window.scrollTo({top:0,behavior:'instant'});true")
                    row = browser.evaluate(LAYOUT_JS)
                    row["state"] = state
                    report["layouts"].append(row)
                    if width in (1440, 390):
                        browser.run("screenshot", str(output / f"{'desktop' if width == 1440 else 'mobile'}-{state}.png"), "--full")
                        browser.evaluate("document.querySelector('.pdf-editor-canvas-column').scrollIntoView({block:'center',behavior:'instant'});true")
                        browser.run("screenshot", str(output / f"{'desktop' if width == 1440 else 'mobile'}-{state}-editor.png"), "--full")
                browser.run("set", "viewport", "1440", "1000")
            report["checks"].update({
                "noDocumentOverflow": all(not row["overflow"] for row in report["layouts"]),
                "noEditorClipping": all(not row["editorOverflow"] for row in report["layouts"]),
                "desktopEditorIs65Percent": all(row["sideBySide"] and 0.64 <= row["ratio"] <= 0.66 for row in report["layouts"] if row["width"] >= 1180),
                "narrowScreensStack": all(not row["sideBySide"] for row in report["layouts"] if row["width"] < 1180),
                "canvasUsesEditorWidth": all(row["canvas"]["width"] >= row["shell"]["width"] * 0.95 for row in report["layouts"]),
                "applicationValuesPreserved": all(row["fieldValues"] == expected_fields for row in report["layouts"]),
                "uploadAndSubmitRemainReachable": all(not row["missingActions"] for row in report["layouts"]),
                "noUnhandledErrors": all(not row["errors"] for row in report["layouts"]),
            })
            document_id = browser.evaluate("uploadedSealEditorRuntime.documentId")
            saved = fixture._expect_json("GET", f"/api/official-documents/{document_id}/editor-state", 200, token=auth["token"])
            state = saved.get("state") or saved.get("editor_state")
            report["checks"]["textSavedAndReadBack"] = any(e.get("properties", {}).get("text") == "合成測試文字" for e in state["elements"])
            print(json.dumps(report["checks"], ensure_ascii=False), flush=True)
            return 0 if args.baseline else int(not all(report["checks"].values()))
        finally:
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            try:
                browser.run("close")
            finally:
                fixture.tearDownClass()


if __name__ == "__main__":
    raise SystemExit(main())
