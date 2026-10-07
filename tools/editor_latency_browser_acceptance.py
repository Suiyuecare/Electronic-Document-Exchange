"""Measure synthetic PDF readiness on loopback, never human SSO or hosted TUS.

Transfer is deliberately held until the local editor accepts real text. This
distinguishes editing latency from server durability; no fake successful HTTP
responses, percentage or 2-second claim is used.
"""
from __future__ import annotations

import argparse
import io
import json
import random
import sys
import time
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
from reportlab.lib.pagesizes import A4, A5, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from tools.editor_file_resilience_browser_acceptance import ResilienceJourney
from tools.six_role_browser_acceptance import Browser, TELEMETRY, require_local_origin
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as Fixture, QuietAcceptanceHandler

CASES = (("vector-1", 1, A4, False), ("vector-25", 25, A4, False),
         ("vector-300", 300, A4, False), ("scan-1", 1, A4, True),
         ("scan-4", 4, A4, True), ("non-a4", 2, landscape(A5), False))


def make_pdf(path, name, pages, size, scanned):
    writer = canvas.Canvas(str(path), pagesize=size, pageCompression=1)
    for page in range(pages):
        if scanned:
            # Incompressible seeded synthetic pixels approximate scan transfer
            # weight without storing any real personal or business document.
            pixels = random.Random(1000 + page).randbytes(1400 * 1900 * 3)
            image = Image.frombytes("RGB", (1400, 1900), pixels)
            writer.drawImage(ImageReader(image), 20, 20, width=size[0]-40, height=size[1]-40)
        writer.setFillColorRGB(0, 0, 0)
        writer.drawString(35, size[1]-35, f"SYNTHETIC LATENCY {name} page {page+1}")
        writer.showPage()
    writer.save()


def run(output):
    output = output.resolve(); output.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, pages, size, scanned in CASES:
        path = output / f"synthetic-{name}.pdf"
        make_pdf(path, name, pages, size, scanned)
        files[name] = path
    original = QuietAcceptanceHandler.send_head
    document = (ROOT / "index.html").read_bytes().replace(b"<head>", b"<head>"+TELEMETRY.encode(), 1)
    def head(handler):
        if urlparse(handler.path).path not in {"/", "/index.html"}: return original(handler)
        handler.send_response(200); handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(document))); handler.end_headers()
        return io.BytesIO(document)
    report = {"scope": "loopback_synthetic_browser_local_direct", "humanSSOVerified": False,
              "physicalMobileVerified": False, "hostedUploadMeasured": False,
              "networkProfile": "local transfer held until actual edit then released", "cases": []}
    with mock.patch.object(QuietAcceptanceHandler, "send_head", head):
        Fixture.setUpClass(); require_local_origin(Fixture.origin)
        config = Path(Fixture.tmp.name) / "latency-browser.json"
        config.write_text(json.dumps({"headed": False}))
        browser = Browser(config, session=f"latency-{time.monotonic_ns()}", namespace="edoc-latency-qa")
        try:
            journey = ResilienceJourney(Fixture, [browser, browser], output)
            for device, width, height in (("desktop", 1440, 1000), ("mobile", 390, 844)):
                for name, pages, size, scanned in CASES:
                    label = f"{device}-{name}"
                    row = {"name": label, "pages": pages, "bytes": files[name].stat().st_size,
                           "nonA4": size != A4, "scanned": scanned}
                    try:
                        journey.login(browser, width=width, height=height)
                        browser.evaluate("""(()=>{
                          window.__latencyPaintMs=null;window.__latencySelectionAt=null;
                          document.querySelector('#uploadedSealPdfInput').addEventListener('change',()=>{
                            window.__latencySelectionAt=performance.now();
                          },{capture:true,once:true});
                          const original=paintUploadedPdfCanvas;
                          paintUploadedPdfCanvas=async(...args)=>{
                            const painted=await original(...args);
                            if(painted&&window.__latencySelectionAt!==null&&window.__latencyPaintMs===null){
                              await new Promise(requestAnimationFrame);
                              window.__latencyPaintMs=performance.now()-window.__latencySelectionAt;
                            }return painted;
                          };return true;
                        })()""")
                        category = browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(e=>e.textContent.includes('服務委託合約')).value")
                        browser.run("select", "#uploadedSealApprovalCategorySelect", category)
                        browser.run("fill", "#uploadedSealTitle", "合成速度驗收 " + label)
                        browser.run("fill", "#uploadedSealReason", "隔離測試，無正式個資。")
                        if size == A4:
                            browser.evaluate("window.__raceRules.push({key:'transfer',method:'PUT',pattern:'/editor-uploads/[^/]+/content$',when:'before'});true")
                        browser.run("upload", "#uploadedSealPdfInput", str(files[name]))
                        if size != A4:
                            browser.until("document.querySelector('#editorA4Dialog')?.open", timeout=40)
                            browser.click_visible("#editorA4Dialog [data-a4-confirm]")
                            browser.until("document.querySelector('#editorA4Title')?.textContent==='請確認 A4 轉換結果'&&!document.querySelector('#editorA4Dialog [data-a4-confirm]').disabled", timeout=40)
                            browser.click_visible("#editorA4Dialog [data-a4-confirm]")
                        if size == A4: journey.held(browser, "transfer")
                        browser.until("uploadedSealEditorState.pages.length==="+str(pages)+"&&!uploadedSealEditorRuntime.uploading&&document.querySelector('#uploadedPdfCanvas').width>0", timeout=60)
                        browser.until("window.__latencyPaintMs!==null", timeout=60)
                        row["firstPagePaintMs"] = browser.evaluate("Math.round(window.__latencyPaintMs)")
                        row["localModelReadyMs"] = browser.evaluate("uploadedSealEditorRuntime.lastEditorReadyMs??null")
                        row["includesConversionConsent"] = size != A4
                        row["editableBeforeTransfer"] = browser.evaluate("window.__raceHolds.transfer.row.status===null&&document.querySelector('#submitUploadedSealBtn').disabled") if size == A4 else None
                        browser.add_pdf_text("合成可編輯 " + label)
                        row["actualTextAdded"] = browser.evaluate("uploadedSealEditorState.elements.some(e=>e.properties?.text==="+json.dumps("合成可編輯 "+label)+")")
                        if size == A4: journey.release(browser, "transfer")
                        browser.until("!uploadedSealEditorRuntime.finalizingAsset&&!uploadedSealEditorRuntime.saving&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration", timeout=90)
                        state = journey.state(browser.evaluate("uploadedSealEditorRuntime.documentId"))
                        row["serverSavedText"] = any((e.get("properties") or {}).get("text") == "合成可編輯 "+label for e in state["elements"])
                        row["errors"] = browser.evaluate("window.__fixtureErrors")
                        row["passed"] = (size != A4 or row["editableBeforeTransfer"]) and row["actualTextAdded"] and row["serverSavedText"] and not row["errors"]
                        browser.run("screenshot", str(output / f"{label}.png"))
                    except Exception as error:
                        row.update(passed=False, errorCode=type(error).__name__)
                        try: browser.run("screenshot", str(output / f"{label}-failed.png"))
                        except Exception: pass
                    report["cases"].append(row)
                    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
                    print(json.dumps(row), flush=True)
        finally:
            try: browser.run("close")
            finally: Fixture.tearDownClass()
    report["passed"] = all(row["passed"] for row in report["cases"])
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(0 if run(parser.parse_args().output)["passed"] else 1)
