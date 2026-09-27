"""Real localhost editor UI resilience, with abort-aware delays around real fetch.

Synthetic documents only. The local_direct fixture verifies the common upload
workflow, not hosted Supabase TUS or a physical mobile device. Responses are
never fabricated: delayed requests still use the fixture HTTP server.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import sys
import time
from unittest import mock
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from tools.editor_race_browser_acceptance import Journey
from tools.six_role_browser_acceptance import Browser, TELEMETRY, require_local_origin
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler


TRANSPORT = r"""(()=>{
 window.fetch=window.__raceRealFetch;window.__raceRules=[];window.__raceHolds={};window.__raceRequests=[];
 window.fetch=async(...args)=>{
  const url=new URL(args[0]?.url||String(args[0]),location.href),signal=args[1]?.signal||args[0]?.signal;
  const method=String(args[1]?.method||args[0]?.method||'GET').toUpperCase();
  const row={method,path:url.pathname,status:null,started:performance.now(),aborted:false};window.__raceRequests.push(row);
  const rule=window.__raceRules.find(r=>!r.used&&r.method===method&&(r.path===url.pathname||(r.pattern&&new RegExp(r.pattern).test(url.pathname))));
  const hold=()=>new Promise((resolve,reject)=>{
   rule.used=true;let settled=false;
   const end=()=>{if(settled)return;settled=true;signal?.removeEventListener('abort',abort);resolve()};
   const abort=()=>{if(settled)return;settled=true;row.aborted=true;signal?.removeEventListener('abort',abort);reject(new DOMException('Synthetic user cancellation','AbortError'))};
   window.__raceHolds[rule.key]={release:end,row};signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
  });
  try{if(rule?.when==='before')await hold();const response=await window.__raceRealFetch(...args);row.status=response.status;
   if(rule?.when==='after')await hold();row.finished=performance.now();return response;
  }catch(error){row.aborted ||= signal?.aborted||error.name==='AbortError';row.finished=performance.now();throw error}
 };return true;
})()"""


class ResilienceJourney(Journey):
    def login(self, browser, auth=None, width=1440, height=1000):
        super().login(browser, auth, width, height)
        browser.evaluate(TRANSPORT)

    def synthetic_pdf(self, name):
        path = self.output / f"synthetic-{name}.pdf"
        writer = canvas.Canvas(str(path), pagesize=A4)
        writer.drawString(60, 780, "SYNTHETIC FILE RESILIENCE - " + name)
        writer.showPage(); writer.save()
        return path

    def failed_preload_recovery(self, browser, transport):
        transport.update(armed=True, failed=False, requests=[])
        self.login(browser)
        browser.until("window.pdfjsLibLoadAttempts>=1&&!window.pdfjsLibPromise&&!window.pdfjsLib")
        before = browser.evaluate("({timeOrigin:performance.timeOrigin,errors:[...window.__fixtureErrors],attempts:window.pdfjsLibLoadAttempts})")
        # This input invokes the actual shipping retry, never an injected import
        # or a manually assigned successful library/promise.
        document_id = self.upload(browser, "failed-preload-recovery")
        browser.add_pdf_text("合成元件失敗後恢復編輯")
        self.saved(browser)
        state = self.state(document_id)
        time.sleep(0.5)
        checks = {
            "bootstrapActuallyReceivedHttp503": any(row["status"] == 503 and row["retry"] == "" for row in transport["requests"]),
            "userUploadFetchedRealRetry1Module": any(row["status"] == 200 and row["retry"] == "1" for row in transport["requests"]),
            "noAutomaticRetryLoop": len(transport["requests"]) == 2,
            "handledPreloadRejection": not before["errors"],
            "samePageWithoutReload": browser.evaluate("performance.timeOrigin===" + json.dumps(before["timeOrigin"])),
            "recoveredEditorVisibleAndUsable": browser.evaluate("uploadedSealEditorState.pages.length===1&&window.pdfjsLib?.getDocument&&document.querySelector('#uploadedPdfCanvas').width>0"),
            "editedTextReallyPersisted": any((element.get("properties") or {}).get("text") == "合成元件失敗後恢復編輯" for element in state["elements"]),
        }
        transport["armed"] = False
        return self.finish("failed-preload-recovery", browser, checks, {"moduleHttpAttempts": transport["requests"], "bootstrapLoadAttempts": before["attempts"]})

    def delayed_upload(self, label, width, height):
        browser = self.a
        self.login(browser, width=width, height=height)
        category = browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(e=>e.textContent.includes('服務委託合約')).value")
        browser.run("select", "#uploadedSealApprovalCategorySelect", category)
        browser.run("fill", "#uploadedSealTitle", "合成等待驗收 " + label)
        browser.run("fill", "#uploadedSealReason", "去識別化 localhost，測試取消及同步。")
        browser.evaluate("window.__raceRules.push({key:'transfer',method:'PUT',pattern:'/editor-uploads/[^/]+/content$',when:'before'});window.__selectionAt=performance.now();true")
        browser.run("upload", "#uploadedSealPdfInput", str(self.synthetic_pdf(label)))
        self.held(browser, "transfer")
        browser.until("uploadedSealEditorState.pages.length===1&&!uploadedSealEditorRuntime.uploading&&uploadedSealEditorRuntime.finalizingAsset&&document.querySelector('#uploadedPdfCanvas').width>0")
        first = browser.evaluate("({readyMs:uploadedSealEditorRuntime.lastEditorReadyMs,sendDisabled:document.querySelector('#submitUploadedSealBtn').disabled,transferFinished:window.__raceHolds.transfer.row.status!==null})")
        text = "合成未同步文字 " + label
        browser.add_pdf_text(text)
        browser.run("screenshot", str(self.output / f"{label}-editable-before-transfer.png"), "--full")
        checks = {"localEditorReadyBeforeTransfer": not first["transferFinished"],
                  "sendDisabledUntilUploaded": first["sendDisabled"],
                  "localTextBeforeUploadComplete": browser.evaluate("uploadedSealEditorState.elements.some(e=>e.properties?.text===" + json.dumps(text) + ")")}
        browser.click_visible("#uploadedPdfCancelTransferBtn")
        browser.until("uploadedSealEditorRuntime.finalizationError&&!uploadedSealEditorRuntime.uploadAbortController&&!uploadedSealEditorRuntime.pendingFinalization?.finalizePromise")
        checks["cancelAbortedActualTransport"] = browser.evaluate("window.__raceHolds.transfer.row.aborted")
        checks["cancelRetainsTextAndDisablesSend"] = browser.evaluate("uploadedSealEditorState.elements.some(e=>e.properties?.text===" + json.dumps(text) + ")&&document.querySelector('#submitUploadedSealBtn').disabled")
        browser.run("screenshot", str(self.output / f"{label}-cancelled-local-text.png"), "--full")
        browser.click_visible("#uploadedEditorRetryUploadBtn")
        browser.until("!uploadedSealEditorRuntime.finalizingAsset&&!uploadedSealEditorRuntime.saving&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration", timeout=40)
        document_id = browser.evaluate("uploadedSealEditorRuntime.documentId")
        state = self.state(document_id)
        checks["retryPersistedLocalText"] = any((element.get("properties") or {}).get("text") == text for element in state["elements"])
        checks["retryUsedRealSuccessfulUpload"] = browser.evaluate(r"window.__raceRequests.some(r=>r.method==='PUT'&&/editor-uploads\/[^/]+\/content$/.test(r.path)&&r.status>=200&&r.status<300)")
        return self.finish(label, browser, checks, {"readyMs": first["readyMs"], "uploadProtocol": "local_direct", "pendingDurationIsControlled": True})

    def multi_source_cancel(self, label, width, height):
        self.login(self.b, width=width, height=height)
        new_id = self.upload(self.b, label + "-new")
        self.b.run("upload", "#uploadedEditorImportPdfInput", str(self.synthetic_pdf(label + "-secondary")))
        self.b.until("uploadedSealEditorState.pages.length===2&&!uploadedSealEditorRuntime.uploading&&!uploadedSealEditorRuntime.finalizingAsset&&!uploadedSealEditorRuntime.saving&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration", timeout=40)
        result = self.fixture._expect_json("GET", f"/api/official-documents/{new_id}/editor-state", 200, token=self.auth["token"])
        sources = result["state"]["sourceFiles"]
        primary = result["state"]["pages"][0]["sourceAssetId"]
        urls = {}
        for source in sources:
            asset_id = source.get("assetId") or source.get("asset_id") or source.get("id")
            manifest = next((asset for asset in result.get("assets", []) if (asset.get("assetId") or asset.get("asset_id") or asset.get("id")) == asset_id), {})
            item = source if any(source.get(key) for key in ("authorizedUrl", "authorized_url", "downloadUrl", "download_url", "url")) else manifest
            url = next((item.get(key) for key in ("authorizedUrl", "authorized_url", "downloadUrl", "download_url", "url") if item.get(key)), "")
            urls[asset_id] = urlparse(url).path
        secondary = next(asset_id for asset_id in urls if asset_id != primary)
        if not urls[primary] or not urls[secondary]:
            raise AssertionError("synthetic_asset_authorization_missing")
        self.login(self.a, width=width, height=height)
        old_id = self.upload(self.a, label + "-old")
        old_text = "合成舊案必須保留 " + label
        self.a.add_pdf_text(old_text); self.saved(self.a)
        old_rect = self.a.evaluate("(()=>{const r=document.querySelector('#uploadedPdfEditor').getBoundingClientRect();return {x:r.x,width:r.width}})()")
        self.hold(self.a, "secondary", "GET", urls[secondary], when="before")
        self.open_case(self.a, new_id, wait=False)
        self.held(self.a, "secondary")
        self.a.until("document.querySelector('#uploadedEditorOpeningPreview figure')&&!document.querySelector('#uploadedEditorOpeningPreview figure').hidden&&document.querySelector('#uploadedEditorOpeningPreview canvas').width>0")
        partial = self.a.evaluate("({active:uploadedSealEditorRuntime.documentId,text:document.querySelector('#uploadedEditorOpeningPreview')?.textContent,requests:window.__raceRequests.filter(r=>r.method==='GET'&&" + json.dumps(list(urls.values())) + ".includes(r.path))})")
        checks = {"primaryPreviewBeforeSecondaryFinishes": self.a.evaluate("window.__raceHolds.secondary.row.status===null&&document.querySelector('#uploadedEditorOpeningPreview canvas').width>0"),
                  "sourceReadsBothStarted": len(partial["requests"]) == 2,
                  "previewExplicitlyOriginalAndLoading": "原稿預覽・尚在載入" in partial["text"],
                  "oldCanonicalCaseRetainedDuringPreview": partial["active"] == old_id,
                  "previewStaysInsideEditorColumn": self.a.evaluate("document.querySelector('#uploadedEditorOpeningPreview').parentElement.id==='uploadedPdfEditor'"),
                  "editorColumnWidthAndPositionUnchanged": self.a.evaluate("(()=>{const r=document.querySelector('#uploadedPdfEditor').getBoundingClientRect(),old=" + json.dumps(old_rect) + ";return Math.abs(r.x-old.x)<1&&Math.abs(r.width-old.width)<1})()"),
                  "temporaryPreviewHasNoEditControls": self.a.evaluate("!document.querySelector('#uploadedEditorOpeningPreview input,#uploadedEditorOpeningPreview [data-editor-tool]')")}
        self.a.run("screenshot", str(self.output / f"{label}-readonly-first-preview.png"), "--full")
        self.a.click_visible("#uploadedEditorOpeningPreview [data-editor-open-cancel]")
        self.a.until("!uploadedSealApplicationRuntime.openPromise&&!document.querySelector('#uploadedEditorOpeningPreview')", timeout=40)
        checks["cancelStopsSecondaryFetch"] = self.a.evaluate("window.__raceHolds.secondary.row.aborted")
        checks["cancelLeavesOldCaseAndText"] = self.a.evaluate("uploadedSealEditorRuntime.documentId===" + json.dumps(old_id) + "&&uploadedSealEditorState.elements.some(e=>e.properties?.text===" + json.dumps(old_text) + ")&&document.querySelector('#uploadedPdfCanvas').width>0")
        self.open_case(self.a, new_id)
        checks["retryOpensOnlyFullyLoadedNewCase"] = self.a.evaluate("uploadedSealEditorRuntime.documentId===" + json.dumps(new_id) + "&&uploadedSealEditorState.pages.length===2&&!document.querySelector('#uploadedEditorOpeningPreview')")
        return self.finish(label, self.a, checks, {"sourceStartGapMs": abs(partial["requests"][0]["started"] - partial["requests"][1]["started"]), "viewport": [width, height]})


def run(output, *, cases=None):
    output = output.resolve(); output.mkdir(parents=True, exist_ok=True)
    fixture = FiveAccountHttpAcceptanceTest
    original_head = QuietAcceptanceHandler.send_head
    instrumented = (ROOT / "index.html").read_bytes().replace(b"<head>", b"<head>" + TELEMETRY.encode(), 1)
    preload = {"armed": False, "failed": False, "requests": []}
    def head(handler):
        parsed = urlparse(handler.path)
        if parsed.path == "/vendor/pdfjs/pdf.min.mjs" and preload["armed"]:
            retry = parse_qs(parsed.query).get("retry", [""])[0]
            if not preload["failed"] and not retry:
                preload["failed"] = True
                preload["requests"].append({"retry": retry, "status": 503})
                data = b"Synthetic localhost module unavailable on the first request only."
                handler.send_response(503); handler.send_header("Content-Type", "text/plain")
                handler.send_header("Cache-Control", "no-store")
                handler.send_header("Content-Length", str(len(data))); handler.end_headers()
                return io.BytesIO(data)
            preload["requests"].append({"retry": retry, "status": 200})
            return original_head(handler)
        if parsed.path not in {"/", "/index.html"}:
            return original_head(handler)
        handler.send_response(200); handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(instrumented))); handler.end_headers()
        return io.BytesIO(instrumented)
    report = {"scope": "isolated_local_real_ui_http_no_production_mutation", "uploadProtocol": "local_direct_not_supabase_tus", "physicalMobileVerified": False, "journeys": []}
    with mock.patch.object(QuietAcceptanceHandler, "send_head", head):
        fixture.setUpClass(); require_local_origin(fixture.origin)
        config = Path(fixture.tmp.name) / "file-resilience-browser.json"
        config.write_text(json.dumps({"headed": False}))
        suffix = f"{time.monotonic_ns():x}"[-9:]
        browsers = [Browser(config, session=f"ef-{name}-{suffix}", namespace="edoc-file-qa") for name in ("a", "b", "c")]
        try:
            journey = ResilienceJourney(fixture, browsers[:2], output)
            methods = {f"{label}-{kind}": lambda name=f"{label}-{kind}", width=width, height=height, method=method: method(name, width, height)
                       for label, width, height in (("desktop", 1440, 1000), ("mobile", 390, 844))
                       for kind, method in (("pending-upload", journey.delayed_upload), ("reopen-cancel", journey.multi_source_cancel))}
            methods["failed-preload-recovery"] = lambda: journey.failed_preload_recovery(browsers[2], preload)
            for name in cases or methods:
                try:
                    result = methods[name]()
                except Exception as error:
                    result = {"name": name, "passed": False, "errorCode": str(error) if str(error).startswith(("browser_", "invalid_")) else type(error).__name__}
                    try:
                        failed_browser = browsers[2] if name == "failed-preload-recovery" else journey.a
                        result["failureState"] = failed_browser.evaluate("({pageCount:uploadedSealEditorState.pages.length,save:document.querySelector('#uploadedEditorSaveStatus')?.textContent,toast:document.querySelector('#toast')?.textContent,preview:document.querySelector('#uploadedEditorOpeningPreview')?.textContent,errors:window.__fixtureErrors,requests:window.__raceRequests})")
                        failed_browser.run("screenshot", str(output / f"{name}-failed.png"), "--full")
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
    parser.add_argument("--cases", nargs="+", choices=("desktop-pending-upload", "desktop-reopen-cancel", "mobile-pending-upload", "mobile-reopen-cancel", "failed-preload-recovery"))
    arguments = parser.parse_args()
    raise SystemExit(0 if run(arguments.output, cases=arguments.cases)["passed"] else 1)
