"""Isolated editor UI -> upload -> save -> reopen regression acceptance.

Uses synthetic sessions, local SQLite and deterministic AV fixtures only.
Never submits, stamps or calls a production service.
"""
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
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from PIL import Image
import fitz
from tools.six_role_browser_acceptance import Browser, AUDIT_JS, TELEMETRY, require_local_origin
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "tests/.artifacts/editor-correctness-browser")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    original_head = QuietAcceptanceHandler.send_head

    def instrument(handler):
        if urlparse(handler.path).path in {"/", "/index.html"}:
            data = (ROOT / "index.html").read_text().replace("<head>", "<head>" + TELEMETRY, 1).encode()
            handler.send_response(200)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            return io.BytesIO(data)
        return original_head(handler)

    fixture = FiveAccountHttpAcceptanceTest
    report = {"scope": "isolated_fixture_no_submission_no_real_seals", "journeys": []}
    with mock.patch.object(QuietAcceptanceHandler, "send_head", instrument):
        fixture.setUpClass()
        require_local_origin(fixture.origin)
        config = Path(fixture.tmp.name) / "browser.json"
        config.write_text(json.dumps({"allowedDomains": ["127.0.0.1", "fonts.googleapis.com", "fonts.gstatic.com"], "headed": False}))
        browser = Browser(config, session="editor-fix-0912", namespace="editor-fix-0912")
        try:
            auth = isolated_browser_session(fixture, "staff")
            for device, dimensions in [("desktop", (1440, 1000)), ("mobile", (390, 844))]:
                row = {"device": device, "checks": {}}
                report["journeys"].append(row)
                browser.run("open", fixture.origin + "/assets/favicon-32.png")
                browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                browser.run("set", "viewport", *map(str, dimensions))
                browser.run("open", fixture.origin + f"/?editor_correctness={time.monotonic_ns()}#electronicSeal")
                browser.until("window.__fixtureTiming?.appInteractiveMs&&document.querySelector('#uploadedSealApprovalCategorySelect')?.options.length>1")
                browser.run("snapshot", "-i")
                row["checks"]["existingCasesCollapsed"] = browser.evaluate("!document.querySelector('#electronicSealWorkQueue').open")
                row["queueLayouts"] = []
                widths = [1440] if device == "desktop" else [375, 390, 430, 760, 820]
                for width in widths:
                    browser.run("set", "viewport", str(width), str(dimensions[1]))
                    layout = browser.evaluate("(()=>{const q=document.querySelector('#electronicSealWorkQueue'),s=q.querySelector('summary'),r=q.getBoundingClientRect();return {width:innerWidth,height:r.height,summaryHeight:s.getBoundingClientRect().height,closed:!q.open,overflow:document.documentElement.scrollWidth>innerWidth+1}})()")
                    row["queueLayouts"].append(layout)
                row["checks"]["closedQueueIsCompactAtAllWidths"] = all(
                    layout["closed"] and 44 <= layout["summaryHeight"] <= 100
                    and layout["height"] <= 110 and not layout["overflow"]
                    for layout in row["queueLayouts"]
                )
                browser.run("set", "viewport", *map(str, dimensions))
                if device == "mobile":
                    browser.until("!document.body.classList.contains('mobile-navigation-open')&&document.querySelector('#primarySidebar').getBoundingClientRect().right<=1")
                browser.run("screenshot", str(output / f"{device}-queue-collapsed.png"))
                category = browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(e=>e.textContent.includes('合作意向書')).value")
                browser.run("select", "#uploadedSealApprovalCategorySelect", category)
                browser.run("fill", "#uploadedSealTitle", f"合成測試 {device} PDF 編輯")
                browser.run("fill", "#uploadedSealReason", "隔離測試，不送簽、不用印、不寄發。")
                pdf_path = Path(fixture.tmp.name) / f"synthetic-{device}.pdf"
                writer = canvas.Canvas(str(pdf_path), pagesize=A4)
                for index, size in enumerate([A4, landscape(A4), A4], 1):
                    writer.setPageSize(size)
                    writer.drawString(50, size[1] - 70, f"SYNTHETIC PAGE {index}")
                    writer.showPage()
                writer.save()
                browser.run("upload", "#uploadedSealPdfInput", str(pdf_path))
                browser.until("uploadedSealEditorState.pages.length===3&&!uploadedSealEditorRuntime.uploading")
                browser.click_visible("#uploadedSealApplicationToggleBtn")
                row["checks"]["applicationCollapsedWithoutLosingValues"] = browser.evaluate("document.querySelector('#uploadedSealApplicationFields').hidden&&document.querySelector('#uploadedSealTitle').value.includes('合成測試')")
                row["checks"]["approvalRouteStillVisible"] = browser.evaluate("document.querySelector('#uploadedSealApprovalRouteBadge').getClientRects().length>0")
                browser.click_visible("#uploadedEditorModeAdvanced")
                # A plain synthetic rectangle, never a real seal image.
                image_path = Path(fixture.tmp.name) / "synthetic.png"
                Image.new("RGB", (32, 32), (250, 180, 80)).save(image_path, format="PNG")
                browser.run("upload", "#uploadedEditorImageInput", str(image_path))
                browser.until("uploadedSealEditorState.elements.some(e=>e.kind==='image')&&!uploadedSealEditorRuntime.uploading")
                browser.until("uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration&&!uploadedSealEditorRuntime.saving")
                row["checks"]["imageInsertedAndAutosaved"] = browser.evaluate("uploadedSealEditorState.elements.filter(e=>e.kind==='image').length===1")
                document_id = browser.evaluate("uploadedSealEditorRuntime.documentId")
                image_readback = fixture._expect_json("GET", f"/api/official-documents/{document_id}/editor-state", 200, token=auth["token"])
                image_state = image_readback.get("state") or image_readback.get("editor_state")
                row["checks"]["serverReadbackContainsImage"] = sum(e.get("kind") == "image" for e in image_state["elements"]) == 1
                # Deleting source page one must not shift retained source bindings.
                browser.click_visible('[data-editor-page-action="delete"]')
                browser.until("uploadedSealEditorState.pages.length===2&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration&&!uploadedSealEditorRuntime.saving")
                document_id = browser.evaluate("uploadedSealEditorRuntime.documentId")
                browser.run("open", fixture.origin + f"/?editor_reopen={time.monotonic_ns()}#electronicSeal")
                browser.until("window.__fixtureTiming?.appInteractiveMs")
                browser.until("Boolean(document.querySelector('[data-electronic-seal-open=" + json.dumps(document_id) + "]'))")
                browser.click_visible("#electronicSealWorkQueue > summary")
                browser.run("fill", "#electronicSealWorkQueueSearch", f"合成測試 {device}")
                browser.click_visible('[data-electronic-seal-open="' + document_id + '"]')
                browser.until("uploadedSealEditorState.pages.length===2&&uploadedSealEditorRuntime.pageProxies.size===2&&!uploadedSealEditorRuntime.locked")
                row["sourcePages"] = browser.evaluate("(async()=>{const out=[];for(const page of uploadedSealEditorState.pages){const proxy=uploadedSealEditorRuntime.pageProxies.get(page.pageId).proxy;out.push({sourcePageIndex:page.sourcePageIndex,pageNumber:proxy.pageNumber,text:(await proxy.getTextContent()).items.map(e=>e.str).join('')})}return out})()")
                row["checks"]["reopenUsesCorrectSourcePages"] = all(item["pageNumber"] == item["sourcePageIndex"] + 1 and item["text"] == f'SYNTHETIC PAGE {item["pageNumber"]}' for item in row["sourcePages"])
                browser.click_visible('#uploadedPdfEditor [data-editor-tool="text"]')
                browser.run("fill", "#uploadedSealTextInput", "合成頁緣貼上")
                browser.click_visible("#addUploadedTextBtn")
                if device == "mobile":
                    browser.click_visible("#uploadedEditorPropertiesToggleBtn")
                browser.click_visible(".editor-precision-settings > summary")
                edge = browser.evaluate("(()=>{const e=[...uploadedSealEditorRuntime.selectedIds].map(editorElementById)[0],p=currentUploadedEditorPage();return {x:p.widthPt-e.width,y:p.heightPt-e.height}})()")
                browser.run("fill", "#uploadedEditorPropertyX", str(edge["x"]))
                browser.run("fill", "#uploadedEditorPropertyY", str(edge["y"]))
                browser.run("press", "Tab")
                if device == "mobile":
                    browser.click_visible("#uploadedEditorPropertiesCloseBtn")
                browser.evaluate("document.activeElement?.blur();true")
                browser.run("press", "Control+c")
                browser.run("press", "Control+v")
                browser.until("uploadedSealEditorState.elements.filter(e=>e.kind==='text').length===2&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration&&!uploadedSealEditorRuntime.saving")
                row["checks"]["edgePasteInBounds"] = browser.evaluate("uploadedSealEditorState.elements.every(e=>{const p=uploadedSealEditorState.pages.find(p=>p.pageId===e.pageId);return e.x>=0&&e.y>=0&&e.x+e.width<=p.widthPt+0.001&&e.y+e.height<=p.heightPt+0.001})")
                saved = fixture._expect_json("GET", f"/api/official-documents/{document_id}/editor-state", 200, token=auth["token"])
                saved_state = saved.get("state") or saved.get("editor_state")
                row["checks"]["serverReadbackContainsBothPastedObjects"] = sum(e.get("kind") == "text" for e in saved_state["elements"]) == 2
                prepared = browser.evaluate("(async()=>{await preflightUploadedEditor();return {fileId:uploadedSealEditorRuntime.preparedFileId}})()")
                response = fixture._request("GET", f'/api/official-documents/{document_id}/files/{prepared["fileId"]}/download', token=auth["token"])
                assert response.status == 200, "prepared_download_failed"
                with fitz.open(stream=response.body, filetype="pdf") as generated:
                    row["checks"]["preparedPdfPreservesCorrectPages"] = generated.page_count == 2 and "SYNTHETIC PAGE 2" in generated[0].get_text() and "SYNTHETIC PAGE 3" in generated[1].get_text() and "SYNTHETIC PAGE 1" not in "".join(page.get_text() for page in generated)
                    row["checks"]["preparedPdfContainsPastedText"] = generated[0].get_text().count("合成頁緣貼上") == 2
                    for number, page in enumerate(generated, 1):
                        page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2)).save(str(output / f"{device}-prepared-page-{number}.png"))
                row["layout"] = browser.evaluate(AUDIT_JS)
                row["checks"]["noDocumentOverflow"] = not row["layout"]["overflow"]
                row["checks"]["noUnhandledErrors"] = not row["layout"]["errors"]
                browser.run("snapshot", "-i")
                browser.run("screenshot", str(output / f"{device}-editor-verified.png"), "--full")
                (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
                print(json.dumps({"completed": device, "checks": row["checks"]}), flush=True)
            return int(any(not all(row["checks"].values()) for row in report["journeys"]))
        except Exception as error:
            report["errorCode"] = str(error) if str(error).startswith("browser_") else type(error).__name__
            report["failure"] = browser.evaluate("({route:document.querySelector('.view.active')?.id,toast:document.querySelector('#toast')?.textContent,status:document.querySelector('#uploadedEditorSaveStatus')?.textContent,uploadError:document.querySelector('#uploadedEditorUploadErrorMessage')?.textContent,pages:uploadedSealEditorState.pages.length,elements:uploadedSealEditorState.elements.map(e=>({kind:e.kind,pageId:e.pageId,x:e.x,y:e.y,width:e.width,height:e.height})),errors:window.__fixtureErrors})")
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            browser.run("screenshot", str(output / "failure.png"), "--full")
            raise
        finally:
            try:
                browser.run("close")
            finally:
                fixture.tearDownClass()


if __name__ == "__main__":
    raise SystemExit(main())
