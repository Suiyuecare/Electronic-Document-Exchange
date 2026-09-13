"""Verify direct PDF text editing with synthetic, isolated browser journeys.

No production session, customer file, submission, exchange, or seal is used.
--baseline-ref serves immutable UI assets for comparable Before evidence.
"""
from __future__ import annotations

import argparse
import html
import hashlib
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

import backend
import fitz
from PIL import Image
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler
from tools.six_role_browser_acceptance import AUDIT_JS, Browser, TELEMETRY, require_local_origin
from tools.verify_editor_applicant_browser import FinanceMirror
from tools.verify_editor_simplified_browser import EDITOR_AUDIT, synthetic_pdf


def saved(browser):
    browser.until("uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration&&!uploadedSealEditorRuntime.saving")


def screenshot(browser, output, label, role, device, state):
    browser.until("!document.querySelector('.toast.show')")
    browser.evaluate("document.querySelector('#uploadedPdfEditor').scrollIntoView({block:'start',behavior:'instant'});true")
    browser.run("snapshot", "-i")
    browser.run("screenshot", str(output / f"{label}-{role}-{device}-{state}.png"))


def click_canvas(browser, x=0.18, y=0.80):
    browser.evaluate("document.querySelector('#uploadedPdfCanvas').scrollIntoView({block:'center',behavior:'instant'});true")
    point = browser.evaluate(f"(()=>{{const r=document.querySelector('#uploadedPdfCanvas').getBoundingClientRect(),x=Math.round(r.x+r.width*{x}),y=Math.round(r.y+r.height*{y});return {{x,y,canvas:r.toJSON(),hitElementId:document.elementFromPoint(x,y)?.closest('[data-editor-element-id]')?.dataset.editorElementId||''}}}})()")
    browser.run("mouse", "move", str(point["x"]), str(point["y"]))
    browser.run("mouse", "down")
    browser.run("mouse", "up")
    return point


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = {name: (subprocess.check_output(["git", "show", args.baseline_ref + ":" + name], cwd=ROOT)
                     if args.baseline_ref else (ROOT / name).read_bytes())
              for name in ("index.html", "app.js", "styles.css")}
    original_head, original_json = QuietAcceptanceHandler.send_head, QuietAcceptanceHandler.send_json
    requests = []

    def instrument(handler):
        path = urlparse(handler.path).path
        name = "index.html" if path in {"/", "/index.html"} else path.lstrip("/")
        if name == "index.html" or name in source:
            data = source.get(name) or (ROOT / name).read_bytes()
            if name == "index.html":
                data = data.replace(b"<head>", ("<head>" + TELEMETRY).encode(), 1)
            handler.send_response(200)
            handler.send_header("Content-Type", "application/javascript" if name.endswith(".js") else "text/css" if name.endswith(".css") else "text/html; charset=utf-8")
            handler.send_header("Content-Security-Policy", "connect-src 'self'")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            return io.BytesIO(data)
        return original_head(handler)

    def trace(handler, data, status=200, extra_headers=None):
        path = urlparse(handler.path).path
        if path.startswith("/api/"):
            requests.append({"method": handler.command, "path": path, "status": status})
        return original_json(handler, data, status, extra_headers)

    report = {"scope": "synthetic_local_sqlite_real_http_shipping_ui", "baselineRef": args.baseline_ref,
              "productionChanged": False, "hostedSsoVerified": False, "realDevicesVerified": False,
              "uiAssetSha256": {name: hashlib.sha256(data).hexdigest() for name, data in source.items()},
              "journeys": [], "requests": requests}
    fixture = FiveAccountHttpAcceptanceTest
    fixture.setUpClass()
    require_local_origin(fixture.origin)
    with backend.connect() as conn:
        conn.execute("UPDATE companies SET name='隔離驗收公司一' WHERE id='CO-001'")
        conn.execute("UPDATE companies SET name='隔離驗收公司二' WHERE id='CO-002'")
    mirror = FinanceMirror(fixture)
    directory = mirror.production_function(backend.supabase_finance_directory)
    authority = mirror.production_function(backend.authoritative_finance_unit)
    authority.__kwdefaults__ = backend.authoritative_finance_unit.__kwdefaults__
    applicant = mirror.production_function(backend.authoritative_editor_applicant_department)
    config = Path(fixture.tmp.name) / "browser.json"
    config.write_text(json.dumps({"headed": False}))
    namespace = "edi-" + str(time.monotonic_ns())[-7:]
    browser = Browser(config, session=namespace, namespace=namespace)
    pdf = Path(fixture.tmp.name) / "合成文件－電子用印驗收.pdf"
    synthetic_pdf(pdf)
    label = "before" if args.baseline_ref else "after"
    try:
        with mock.patch.object(QuietAcceptanceHandler, "send_head", instrument), mock.patch.object(QuietAcceptanceHandler, "send_json", trace), mock.patch.object(backend, "local_finance_directory", side_effect=lambda conn, session: directory(session)), mock.patch.object(backend, "authoritative_finance_unit", side_effect=authority), mock.patch.object(backend, "authoritative_editor_applicant_department", side_effect=applicant):
            for role in args.roles:
                auth = isolated_browser_session(fixture, role, entity_id="E1")
                devices = (("desktop", (1440, 1000)),) if args.rotation_only else (("desktop", (1440, 1000)), ("mobile", (390, 844)))
                for device, dimensions in devices:
                    row = {"role": role, "device": device, "checks": {}}
                    report["journeys"].append(row)
                    browser.run("open", fixture.origin + "/assets/favicon-32.png")
                    browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                    browser.run("set", "viewport", *map(str, dimensions))
                    browser.run("open", fixture.origin + f"/?directEdit={time.monotonic_ns()}#electronicSeal")
                    browser.until("window.__fixtureTiming?.appInteractiveMs&&document.querySelector('#uploadedSealApprovalCategorySelect')?.options.length>1&&!uploadedSealEditorRuntime.directoryLoading")
                    browser.run("snapshot", "-i")
                    row["checks"]["devServerLoaded"] = browser.evaluate("document.body.innerText.trim().length>0&&!document.querySelector('[data-nextjs-dialog],.vite-error-overlay')")
                    category = browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(e=>e.textContent.includes('合作意向書')).value")
                    browser.run("select", "#uploadedSealApprovalCategorySelect", category)
                    browser.run("fill", "#uploadedSealTitle", "合成文件用印驗收")
                    browser.run("fill", "#uploadedSealReason", "隔離測試，不送簽、不用印、不寄發。")
                    browser.run("upload", "#uploadedSealPdfInput", str(pdf))
                    browser.until("uploadedSealEditorState.pages.length===2&&!uploadedSealEditorRuntime.uploading||!document.querySelector('#uploadedEditorUploadError').hidden", timeout=40)
                    row["checks"]["uploadAccepted"] = browser.evaluate("uploadedSealEditorState.pages.length===2")
                    if not row["checks"]["uploadAccepted"]:
                        raise AssertionError("synthetic_upload_failed")
                    browser.until("document.querySelector('#uploadedPdfCanvas').width>0")
                    saved(browser)
                    browser.click_visible("#uploadedPdfNextBtn")
                    browser.until("uploadedSealCurrentPage===2")
                    if args.rotation_only:
                        verify_rotation(browser, row)
                        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
                        print(json.dumps(row, ensure_ascii=False), flush=True)
                        continue
                    browser.click_visible('#uploadedPdfEditor [data-editor-tool="text"]')
                    if args.baseline_ref:
                        browser.run("fill", "#uploadedSealTextInput", "合成文件編輯驗收")
                        screenshot(browser, output, label, role, device, "editing")
                        browser.click_visible("#addUploadedTextBtn")
                    else:
                        initial_count = browser.evaluate("uploadedSealEditorState.elements.length")
                        click_canvas(browser)
                        browser.until("document.querySelector('#uploadedEditorInlineText')?.getClientRects().length>0")
                        row["checks"]["noEmptyObjectBeforeCommit"] = browser.evaluate("uploadedSealEditorState.elements.length") == initial_count
                        browser.run("fill", "#uploadedEditorInlineText", "合成文件編輯驗收")
                        screenshot(browser, output, label, role, device, "editing")
                        browser.run("press", "Enter")
                    browser.until("uploadedSealEditorState.elements.some(e=>e.kind==='text')")
                    saved(browser)
                    screenshot(browser, output, label, role, device, "viewport")
                    browser.evaluate("document.querySelector('#uploadedPdfCanvas').scrollIntoView({block:'center',behavior:'instant'});true")
                    browser.run("screenshot", str(output / f"{label}-{role}-{device}-canvas.png"))
                    row["editor"] = browser.evaluate(EDITOR_AUDIT)
                    row["layout"] = browser.evaluate(AUDIT_JS)
                    row["checks"]["noDocumentOverflow"] = not row["layout"]["overflow"]
                    row["checks"]["noUnhandledErrors"] = not row["layout"]["errors"]
                    row["checks"]["canvasRendered"] = row["editor"]["canvas"]["width"] > 0
                    document_id = browser.evaluate("uploadedSealEditorRuntime.documentId")
                    data = fixture._expect_json("GET", f"/api/official-documents/{document_id}/editor-state", 200, token=auth["token"])
                    state = data.get("state") or data.get("editor_state")
                    row["checks"]["textPersisted"] = any(e.get("properties", {}).get("text") == "合成文件編輯驗收" for e in state.get("elements", []))
                    if not args.baseline_ref:
                        verify_after(browser, fixture, auth, row, output)
                    row["checks"]["noSubmissionOrStamp"] = not any("/submit" in e["path"] or "/stamp" in e["path"] for e in requests)
                    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
                    print(json.dumps({"stage": label, "role": role, "device": device, "checks": row["checks"]}, ensure_ascii=False), flush=True)
        return int(any(not all(row["checks"].values()) for row in report["journeys"]))
    except Exception as error:
        report["errorCode"] = str(error) if str(error).startswith(("browser_", "synthetic_")) else type(error).__name__
        try:
            report["failure"] = browser.evaluate("({pages:uploadedSealEditorState.pages.length,tool:uploadedSealEditorRuntime.tool,uploading:uploadedSealEditorRuntime.uploading,editing:!!document.querySelector('#uploadedEditorInlineText')?.getClientRects().length,errors:window.__fixtureErrors||[]})")
            browser.run("screenshot", str(output / "failure.png"), "--full")
        except Exception:
            pass
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        raise
    finally:
        try:
            browser.run("close")
        finally:
            fixture.tearDownClass()


def verify_after(browser, fixture, auth, row, output):
    """Drive direct add/edit/IME/cancel through DOM events and shipping HTTP API."""
    row["checks"]["commitReturnsToSelection"] = browser.evaluate("uploadedSealEditorRuntime.tool==='select'&&!uploadedSealEditorRuntime.textEdit")
    browser.evaluate("window.__directOriginal=JSON.stringify(uploadedSealEditorState.elements[0]);window.__directOriginalId=uploadedSealEditorState.elements[0].id;true")
    browser.click_visible("#uploadedEditorUndoBtn")
    browser.until("!uploadedSealEditorState.elements.some(e=>e.kind==='text')")
    browser.click_visible("#uploadedEditorRedoBtn")
    browser.until("uploadedSealEditorState.elements.some(e=>e.kind==='text')")
    row["checks"]["undoRedo"] = True
    saved(browser)
    browser.click_visible('#uploadedPdfEditor [data-editor-tool="text"]')
    browser.evaluate("window.__directState=JSON.stringify(uploadedSealEditorState);window.__directGeneration=uploadedSealEditorRuntime.dirtyGeneration;true")
    click_canvas(browser, 0.22, 0.64)
    browser.until("!!uploadedSealEditorRuntime.textEdit")
    browser.run("fill", "#uploadedEditorInlineText", "這一段取消，不應存入文件")
    browser.run("press", "Escape")
    row["checks"]["escapeCancelsWithoutMutation"] = browser.evaluate("!uploadedSealEditorRuntime.textEdit&&JSON.stringify(uploadedSealEditorState)===window.__directState&&uploadedSealEditorRuntime.dirtyGeneration===window.__directGeneration")
    row["checks"]["escapeReturnsCanvasFocus"] = browser.evaluate("document.activeElement===document.querySelector('#uploadedEditorSvgLayer')")
    browser.click_visible('#uploadedPdfEditor [data-editor-tool="select"]')
    browser.click_visible("#uploadedEditorSvgLayer .editor-object-hit")
    browser.click_visible("#uploadedEditorEditTextBtn")
    browser.until("!!uploadedSealEditorRuntime.textEdit")
    row["checks"]["selectionEditOpensInline"] = browser.evaluate("document.querySelector('#uploadedEditorInlineText').value==='合成文件編輯驗收'")
    browser.run("fill", "#uploadedEditorInlineText", "鍵盤取消測試")
    row["inlineTabOrder"] = []
    for _ in range(8):
        browser.run("press", "Tab")
        active_id = browser.evaluate("document.activeElement?.id||document.activeElement?.tagName")
        row["inlineTabOrder"].append(active_id)
        if active_id == "uploadedEditorInlineCancel":
            break
    row["checks"]["cancelKeyboardReachable"] = browser.evaluate("document.activeElement===document.querySelector('#uploadedEditorInlineCancel')")
    if not row["checks"]["cancelKeyboardReachable"]:
        raise AssertionError("synthetic_keyboard_cancel_unreachable")
    browser.run("press", "Enter")
    row["checks"]["keyboardCancelDoesNotCommit"] = browser.evaluate("!uploadedSealEditorRuntime.textEdit&&uploadedSealEditorState.elements[0]?.properties.text==='合成文件編輯驗收'")
    browser.click_visible("#uploadedEditorEditTextBtn")
    browser.until("!!uploadedSealEditorRuntime.textEdit")
    browser.run("fill", "#uploadedEditorInlineText", "修改後的合成驗收文字")
    browser.evaluate("(()=>{const input=document.querySelector('#uploadedEditorInlineText');input.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true,data:'修'}));input.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,key:'Enter',isComposing:true}));return true})()")
    row["checks"]["imeEnterDoesNotCommit"] = browser.evaluate("!!uploadedSealEditorRuntime.textEdit&&uploadedSealEditorState.elements[0].properties.text==='合成文件編輯驗收'")
    browser.evaluate("document.querySelector('#uploadedEditorInlineText').dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'修改'}));true")
    row["checks"]["compositionEndKeepsEditorOpen"] = browser.evaluate("!!uploadedSealEditorRuntime.textEdit")
    browser.run("fill", "#uploadedEditorInlineFontSize", "18")
    # A native OS colour picker is outside Chromium automation. Apply the same
    # input/change events that selecting a colour produces, not a state mutation.
    browser.evaluate("(()=>{const input=document.querySelector('#uploadedEditorInlineColor');input.value='#336699';input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));return true})()")
    row["inlineGeometry"] = browser.evaluate("(()=>{const panel=document.querySelector('#uploadedEditorTextEdit'),input=document.querySelector('#uploadedEditorInlineText'),rect=panel.getBoundingClientRect();return {fontSize:parseFloat(getComputedStyle(input).fontSize),rect:rect.toJSON(),viewport:innerWidth,targets:[...panel.querySelectorAll('input,button')].map(e=>({id:e.id,width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height}))}})()")
    row["checks"]["inlineInputAtLeast16px"] = row["inlineGeometry"]["fontSize"] >= 16
    row["checks"]["inlineControls44px"] = all(e["width"] >= 43.5 and e["height"] >= 43.5 for e in row["inlineGeometry"]["targets"])
    row["checks"]["inlineEditorWithinWidth"] = row["inlineGeometry"]["rect"]["left"] >= 0 and row["inlineGeometry"]["rect"]["right"] <= row["inlineGeometry"]["viewport"] + 1
    browser.evaluate("window.__beforeInlineCommitGeneration=uploadedSealEditorRuntime.dirtyGeneration;true")
    browser.click_visible("#uploadedEditorInlineDone")
    browser.until("!uploadedSealEditorRuntime.textEdit&&uploadedSealEditorState.elements[0].properties.text==='修改後的合成驗收文字'")
    row["checks"]["editingPreservesIdAndTopAnchor"] = browser.evaluate("(()=>{const old=JSON.parse(window.__directOriginal),now=uploadedSealEditorState.elements[0];return ['id','pageId','x','width','rotation'].every(k=>old[k]===now[k])&&Math.abs(old.y+old.height-now.y-now.height)<0.01})()")
    row["checks"]["inlineCommitIsOneMutation"] = browser.evaluate("uploadedSealEditorRuntime.dirtyGeneration===window.__beforeInlineCommitGeneration+1")
    row["checks"]["inlineFontAndColorApplied"] = browser.evaluate("uploadedSealEditorState.elements[0].properties.fontSize===18&&uploadedSealEditorState.elements[0].properties.color==='#336699'")
    saved(browser)
    browser.click_visible("#uploadedEditorUndoBtn")
    browser.until("uploadedSealEditorState.elements[0].properties.text==='合成文件編輯驗收'")
    browser.click_visible("#uploadedEditorRedoBtn")
    browser.until("uploadedSealEditorState.elements[0].properties.text==='修改後的合成驗收文字'")
    row["checks"]["inlineEditUndoRedo"] = True
    browser.evaluate("window.__inlinePointerTrace=[];['pointerdown','pointerup','pointercancel','click','dblclick'].forEach(type=>document.querySelector('#uploadedStampLayer').addEventListener(type,event=>{const entry={type,at:event.timeStamp,target:event.target.tagName,kind:event.target.getAttribute('class'),id:event.target.closest('[data-editor-element-id]')?.dataset.editorElementId,detail:event.detail};window.__inlinePointerTrace.push(entry);queueMicrotask(()=>Object.assign(entry,{action:uploadedSealEditorRuntime.pointerAction?.type,lastTap:uploadedSealEditorRuntime.lastTextTap,editing:!!uploadedSealEditorRuntime.textEdit}))},true));true")
    browser.evaluate("document.querySelector('#uploadedEditorSvgLayer .editor-object-hit').scrollIntoView({block:'center',behavior:'instant'});true")
    point = browser.evaluate("(()=>{const r=document.querySelector('#uploadedEditorSvgLayer .editor-object-hit').getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()")
    browser.run("mouse", "move", str(point["x"]), str(point["y"]))
    # The CLI dblclick emits one pointer pair with clickCount=2; exercise two
    # actual pointer pairs so the canvas behaves like a real desktop double tap.
    for _ in range(2):
        browser.run("mouse", "down")
        browser.run("mouse", "up")
    row["doubleClickPointerTrace"] = browser.evaluate("window.__inlinePointerTrace")
    browser.until("!!uploadedSealEditorRuntime.textEdit")
    row["checks"]["doubleClickEditsText"] = browser.evaluate("document.querySelector('#uploadedEditorInlineText').value==='修改後的合成驗收文字'")
    browser.click_visible("#uploadedEditorInlineCancel")
    row["checks"]["cancelActionClosesInline"] = browser.evaluate("!uploadedSealEditorRuntime.textEdit")
    browser.click_visible("#uploadedEditorDuplicateBtn")
    browser.until("uploadedSealEditorState.elements.filter(e=>e.kind==='text').length===2")
    browser.click_visible("#uploadedEditorDeleteBtn")
    browser.until("uploadedSealEditorState.elements.filter(e=>e.kind==='text').length===1")
    row["checks"]["contextDuplicateDelete"] = True
    browser.click_visible('#uploadedPdfEditor [data-editor-tool="image"]')
    image_path = Path(fixture.tmp.name) / "synthetic-editor-image.png"
    Image.new("RGB", (32, 32), (250, 180, 80)).save(image_path, format="PNG")
    browser.run("upload", "#uploadedEditorImageInput", str(image_path))
    browser.until("uploadedSealEditorState.elements.some(e=>e.kind==='image')&&!uploadedSealEditorRuntime.uploading")
    saved(browser)
    row["checks"]["primaryImageUploadWorks"] = browser.evaluate("uploadedSealEditorState.elements.filter(e=>e.kind==='image').length===1")
    browser.click_visible("#uploadedEditorViewOptions > summary")
    browser.run("select", "#uploadedEditorReviewSelect", "original")
    browser.until("uploadedSealEditorRuntime.reviewMode==='original'")
    row["checks"]["originalReadonly"] = browser.evaluate("[...document.querySelectorAll('#uploadedPdfEditor [data-editor-tool]')].every(e=>e.disabled)&&!uploadedSealEditorRuntime.textEdit")
    if not browser.evaluate("document.querySelector('#uploadedEditorViewOptions').open"):
        browser.click_visible("#uploadedEditorViewOptions > summary")
    browser.run("select", "#uploadedEditorReviewSelect", "edited")
    browser.until("uploadedSealEditorRuntime.reviewMode==='edited'")
    browser.run("press", "Escape")
    saved(browser)
    document_id = browser.evaluate("uploadedSealEditorRuntime.documentId")
    data = fixture._expect_json("GET", f"/api/official-documents/{document_id}/editor-state", 200, token=auth["token"])
    state = data.get("state") or data.get("editor_state")
    row["checks"]["editedTextPersisted"] = any(e.get("properties", {}).get("text") == "修改後的合成驗收文字" for e in state.get("elements", []))
    row["checks"]["imagePersisted"] = any(e.get("kind") == "image" for e in state.get("elements", []))
    browser.click_visible('#uploadedPdfEditor [data-editor-tool="text"]')
    # The synthetic source reserves the lower-right area for added text, so the
    # output visual check can detect clipping without overlapping source rows.
    click_canvas(browser, 0.58, 0.70)
    browser.until("!!uploadedSealEditorRuntime.textEdit")
    long_text = "這是合成驗收長文字，用於確認新增文字會依文字框寬度換行，且輸出完整保留所有內容。" * 2
    final_line = "第二行必須完整保存，尾碼驗收完成ABC987。"
    browser.run("fill", "#uploadedEditorInlineText", long_text)
    browser.run("press", "Shift+Enter")
    browser.run("type", "#uploadedEditorInlineText", final_line)
    row["checks"]["shiftEnterAddsNewlineWithoutCommit"] = browser.evaluate("!!uploadedSealEditorRuntime.textEdit&&document.querySelector('#uploadedEditorInlineText').value.includes('\\n')&&uploadedSealEditorState.elements.filter(e=>e.kind==='text').length===1")
    browser.run("press", "Enter")
    browser.until("!uploadedSealEditorRuntime.textEdit&&uploadedSealEditorState.elements.filter(e=>e.kind==='text').length===2")
    saved(browser)
    row["checks"]["longTextExpandsBoxInBounds"] = browser.evaluate("(()=>{const e=uploadedSealEditorState.elements.find(e=>e.properties?.text?.includes('ABC987')),p=uploadedSealEditorState.pages.find(p=>p.pageId===e.pageId);return e.height>20&&e.x>=0&&e.y>=0&&e.x+e.width<=p.widthPt+.01&&e.y+e.height<=p.heightPt+.01})()")
    prepared = browser.evaluate("(async()=>{await preflightUploadedEditor();return {fileId:uploadedSealEditorRuntime.preparedFileId}})()")
    response = fixture._request("GET", f'/api/official-documents/{document_id}/files/{prepared["fileId"]}/download', token=auth["token"])
    if response.status != 200:
        raise AssertionError("synthetic_prepared_download_failed")
    prepared_path = output / f"after-{row['role']}-{row['device']}-prepared.pdf"
    prepared_path.write_bytes(response.body)
    with fitz.open(stream=response.body, filetype="pdf") as pdf:
        text = "".join(page.get_text() for page in pdf)
        compact = "".join(text.split())
        row["checks"]["preparedHasBothSourcePages"] = pdf.page_count == 2 and text.count("SYNTHETIC DOCUMENT - EDITOR ACCEPTANCE") == 2
        row["checks"]["preparedHasEditedText"] = "修改後的合成驗收文字" in compact
        row["checks"]["preparedHasCompleteLongText"] = "".join((long_text + final_line).split()) in compact
    subprocess.run(["pdftoppm", "-png", "-r", "90", str(prepared_path), str(output / f"after-{row['role']}-{row['device']}-prepared")], check=True, capture_output=True, timeout=45)
    if row["role"] == "staff" and row["device"] == "desktop":
        verify_rotation(browser, row)
    row["checks"]["finalNoUnhandledErrors"] = not browser.evaluate("window.__fixtureErrors||[]")


def verify_rotation(browser, row):
    browser.click_visible("#uploadedEditorThumbnailToggleBtn")
    browser.click_visible('[data-editor-page-action="rotate-right"]')
    browser.click_visible("#uploadedEditorThumbnailCloseBtn")
    browser.until("currentUploadedEditorPage().rotation===90&&uploadedSealEditorRuntime.currentViewport.rotation===90")
    browser.click_visible('#uploadedPdfEditor [data-editor-tool="text"]')
    point = click_canvas(browser, 0.75, 0.75)
    browser.until("!!uploadedSealEditorRuntime.textEdit")
    row["checks"]["rotated90ClickTargetsBlankCanvas"] = not point["hitElementId"] and browser.evaluate("uploadedSealEditorRuntime.textEdit.elementId===''")
    anchor = browser.evaluate("(()=>{const r=uploadedEditorViewportRect(uploadedSealEditorRuntime.textEdit.element),c=document.querySelector('#uploadedPdfCanvas').getBoundingClientRect(),v=uploadedSealEditorRuntime.currentViewport;return {x:r.left,y:r.top,canvas:c.toJSON(),viewport:{width:v.width,height:v.height,rotation:v.rotation,scale:v.scale,transform:v.transform},overlay:document.querySelector('#uploadedEditorSvgLayer').getBoundingClientRect().toJSON(),element:uploadedSealEditorRuntime.textEdit.element}})()")
    row["rotated90Anchor"] = {"click": point, "text": anchor}
    # Opening the inline control may scroll the page; compare coordinates in
    # the PDF canvas, not viewport positions before/after that scroll.
    row["checks"]["rotated90ClickAnchorMatches"] = abs(anchor["x"] - (point["x"] - point["canvas"]["x"])) <= 1 and abs(anchor["y"] - (point["y"] - point["canvas"]["y"])) <= 1
    browser.run("fill", "#uploadedEditorInlineText", "旋轉頁面直接編輯驗收")
    browser.run("press", "Enter")
    browser.until("!uploadedSealEditorRuntime.textEdit&&uploadedSealEditorState.elements.some(e=>e.properties?.text==='旋轉頁面直接編輯驗收')")
    saved(browser)
    row["checks"]["rotated90TextSaved"] = True


def comparison_boards(output):
    """Compose unaltered browser screenshots into clearly labelled evidence."""
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = output / "comparison-browser.json"
    config.write_text(json.dumps({"headed": False}))
    namespace = "edic-" + str(time.monotonic_ns())[-6:]
    browser = Browser(config, session=namespace, namespace=namespace)
    try:
        for device, dimensions in (("desktop", (1440, 800)), ("mobile", (900, 1080))):
            before = output / "before" / f"before-staff-{device}-editing.png"
            after = output / "after" / f"after-staff-{device}-editing.png"
            if not before.is_file() or not after.is_file():
                raise RuntimeError("synthetic_comparison_evidence_missing")
            title = "桌機" if device == "desktop" else "手機（390px 模擬）"
            content = f"""<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>PDF 直接編輯比較</title><style>
            *{{box-sizing:border-box}}body{{margin:0;padding:28px;background:#faf5ed;color:#2f2b27;font-family:Arial,'PingFang TC',sans-serif}}h1{{margin:0 0 10px;font-size:28px}}p{{margin:0 0 20px;color:#766a5b;font-size:16px}}main{{display:grid;grid-template-columns:1fr 1fr;gap:22px}}article{{background:white;border:1px solid #e5cdaa;border-radius:14px;overflow:hidden}}h2{{font-size:20px;margin:0;padding:15px 16px;background:#fff0dc}}article:last-child h2{{background:#ef8907;color:white}}article p{{font-size:14px;padding:14px 16px;margin:0;min-height:68px}}img{{display:block;width:100%;height:auto}}footer{{margin-top:16px;font-size:13px;color:#7d7265}}
            </style><h1>PDF 直接編輯｜{title}</h1><p>相同合成文件、相同驗收帳號；真實瀏覽器操作畫面。</p><main>
            <article><h2>Before｜先填欄位，再加入文件</h2><p>文字輸入與 PDF 分開，必須在兩個區域之間操作。</p><img src="{html.escape(before.as_uri())}"></article>
            <article><h2>After｜點文件，直接輸入</h2><p>選文字 → 點位置 → 輸入；在原位置調整字級、顏色並完成。</p><img src="{html.escape(after.as_uri())}"></article>
            </main><footer>本機隔離驗收，不含個資；未部署正式前台。手機為 Chromium 模擬，非實機 Safari 驗收。</footer></html>"""
            page = output / f"comparison-{device}.html"
            page.write_text(content)
            browser.run("set", "viewport", *map(str, dimensions))
            browser.run("open", page.as_uri())
            browser.until("[...document.images].every(e=>e.complete&&e.naturalWidth>0)")
            browser.run("screenshot", str(output / f"comparison-{device}.png"), "--full")
        return 0
    finally:
        browser.run("close")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-ref", default="")
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--rotation-only", action="store_true")
    parser.add_argument("--roles", nargs="+", choices=("staff", "ceo"), default=["staff"])
    arguments = parser.parse_args()
    raise SystemExit(comparison_boards(arguments.output) if arguments.compare else run(arguments))
