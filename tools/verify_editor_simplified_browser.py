"""Local, synthetic browser evidence for the compact PDF editor.

Serves the shipping HTTP API against an isolated temporary database/storage.
No hosted project, real session, document, stamp, submission or exchange is used.
The optional baseline ref freezes only UI assets, keeping fixtures identical.
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

import backend
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler
from tools.six_role_browser_acceptance import AUDIT_JS, Browser, TELEMETRY, require_local_origin
from tools.verify_editor_applicant_browser import FinanceMirror


def synthetic_pdf(path: Path) -> None:
    writer = canvas.Canvas(str(path), pagesize=landscape(A4))
    width, height = landscape(A4)
    for page in range(1, 3):
        writer.setFont("Helvetica-Bold", 18)
        writer.drawString(50, height - 55, "SYNTHETIC DOCUMENT - EDITOR ACCEPTANCE")
        writer.setFont("Helvetica", 12)
        writer.drawString(50, height - 82, "No personal, financial or production information")
        writer.setFont("Helvetica-Bold", 11)
        writer.drawString(65, height - 130, "Item")
        writer.drawString(460, height - 130, "Status")
        for row in range(9):
            y = height - 145 - row * 32
            writer.line(50, y, width - 50, y)
            if row < 8:
                writer.setFont("Helvetica", 11)
                writer.drawString(65, y - 22, f"Sample entry {page}-{row + 1}")
                writer.drawString(460, y - 22, "For visual verification only")
        writer.line(50, height - 110, width - 50, height - 110)
        writer.line(50, height - 110, 50, height - 401)
        writer.line(width - 50, height - 110, width - 50, height - 401)
        writer.line(440, height - 110, 440, height - 401)
        writer.drawCentredString(width / 2, 35, f"Page {page} / 2")
        writer.showPage()
    writer.save()


EDITOR_AUDIT = """(()=>{
 const root=document.querySelector('#uploadedPdfEditor');
 const visible=e=>{const collapsed=e.closest('details:not([open])');return e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden'&&(!collapsed||collapsed.querySelector(':scope > summary')?.contains(e));};
 const controls=[...root.querySelectorAll('button,summary,input:not([type=hidden]),select,textarea')].filter(visible);
 const rect=root.getBoundingClientRect();
 return {height:Math.round(rect.height),visibleControls:controls.length,
   shortTargets:controls.filter(e=>{const r=e.getBoundingClientRect();return r.width<43.5||r.height<43.5}).map(e=>({id:e.id,text:(e.getAttribute('aria-label')||e.textContent||e.type||'').trim().slice(0,40),width:Math.round(e.getBoundingClientRect().width),height:Math.round(e.getBoundingClientRect().height)})),
   pageWidth:document.documentElement.scrollWidth,viewport:innerWidth,
   mode:uploadedSealEditorRuntime.mode,tool:uploadedSealEditorRuntime.tool,
   saveText:document.querySelector('#uploadedEditorSaveStatus').textContent,
   seamVisible:visible(document.querySelector('#uploadedEditorSeamPanel')),
   pages:uploadedSealEditorState.pages.length,
   canvas:{width:document.querySelector('#uploadedPdfCanvas').width,height:document.querySelector('#uploadedPdfCanvas').height},
   geometry:{stage:document.querySelector('#uploadedPdfStage').getBoundingClientRect().toJSON(),canvas:document.querySelector('#uploadedPdfCanvas').getBoundingClientRect().toJSON(),overlay:document.querySelector('#uploadedEditorSvgLayer').getBoundingClientRect().toJSON()},
   errors:window.__fixtureErrors||[]};})()"""


def run(args) -> int:
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = {name: subprocess.check_output(["git", "show", args.baseline_ref + ":" + name], cwd=ROOT)
              for name in ("index.html", "app.js", "styles.css")} if args.baseline_ref else {}
    original_head = QuietAcceptanceHandler.send_head
    original_json = QuietAcceptanceHandler.send_json
    api = []

    def instrument(handler):
        path = urlparse(handler.path).path
        name = "index.html" if path in {"/", "/index.html"} else path.lstrip("/")
        if name == "index.html" or name in source:
            data = source.get(name) or (ROOT / name).read_bytes()
            if name == "index.html":
                data = data.replace(b"<head>", ("<head>" + TELEMETRY).encode(), 1)
            handler.send_response(200)
            handler.send_header("Content-Type", "application/javascript" if name.endswith(".js") else "text/css" if name.endswith(".css") else "text/html; charset=utf-8")
            # agent-browser's allowedDomains intercepts binary upload requests;
            # keep the equivalent page-level network boundary without interception.
            handler.send_header("Content-Security-Policy", "connect-src 'self'")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            return io.BytesIO(data)
        return original_head(handler)

    def trace(handler, data, status=200, extra_headers=None):
        path = urlparse(handler.path).path
        if path.startswith("/api/"):
            api.append({"method": handler.command, "path": path, "status": status})
        return original_json(handler, data, status, extra_headers)

    report = {"scope": "synthetic_local_sqlite_real_http_shipping_ui", "baselineRef": args.baseline_ref, "noSeals": args.no_seals,
              "productionChanged": False, "hostedSsoVerified": False, "journeys": [], "requests": api}
    fixture = FiveAccountHttpAcceptanceTest
    fixture.setUpClass()
    require_local_origin(fixture.origin)
    with backend.connect() as conn:
        conn.execute("UPDATE companies SET name='隔離驗收公司一' WHERE id='CO-001'")
        conn.execute("UPDATE companies SET name='隔離驗收公司二' WHERE id='CO-002'")
        if args.no_seals:
            conn.execute("UPDATE company_seals SET is_active=0")
    mirror = FinanceMirror(fixture)
    directory = mirror.production_function(backend.supabase_finance_directory)
    authority = mirror.production_function(backend.authoritative_finance_unit)
    authority.__kwdefaults__ = backend.authoritative_finance_unit.__kwdefaults__
    application_authority = mirror.production_function(backend.authoritative_editor_applicant_department)
    config = Path(fixture.tmp.name) / "browser.json"
    config.write_text(json.dumps({"headed": False}))
    namespace = "eds-" + str(time.monotonic_ns())[-7:]
    browser = Browser(config, session=namespace, namespace=namespace)
    pdf = Path(fixture.tmp.name) / "合成文件－電子用印驗收.pdf"
    synthetic_pdf(pdf)
    label = "before" if args.baseline_ref else "after"
    try:
        with mock.patch.object(QuietAcceptanceHandler, "send_head", instrument), mock.patch.object(QuietAcceptanceHandler, "send_json", trace), mock.patch.object(backend, "local_finance_directory", side_effect=lambda conn, session: directory(session)), mock.patch.object(backend, "authoritative_finance_unit", side_effect=authority), mock.patch.object(backend, "authoritative_editor_applicant_department", side_effect=application_authority):
            for role in args.roles:
                auth = isolated_browser_session(fixture, role, entity_id="E1")
                for device, dimensions in (("desktop", (1440, 1000)), ("mobile", (390, 844))):
                    row = {"role": role, "device": device, "checks": {}}
                    report["journeys"].append(row)
                    request_start = len(api)
                    browser.run("open", fixture.origin + "/assets/favicon-32.png")
                    browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                    browser.run("set", "viewport", *map(str, dimensions))
                    browser.run("open", fixture.origin + f"/?simplification={time.monotonic_ns()}#electronicSeal")
                    browser.until("window.__fixtureTiming?.appInteractiveMs&&document.querySelector('#uploadedSealApprovalCategorySelect')?.options.length>1&&!uploadedSealEditorRuntime.directoryLoading")
                    browser.run("snapshot", "-i")
                    if not args.baseline_ref:
                        row["checks"]["emptyStateOneUploadAction"] = browser.evaluate("['#uploadedPdfReplaceBtn','#uploadedPdfEmptyUploadBtn'].map(id=>document.querySelector(id)).filter(e=>e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden').length===1")
                        browser.evaluate("document.querySelector('#uploadedPdfEditor').scrollIntoView({block:'start',behavior:'instant'});true")
                        browser.run("screenshot", str(output / f"after-{role}-{device}-empty.png"))
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
                    if args.baseline_ref:
                        browser.click_visible("#uploadedEditorModeAdvanced")
                    browser.click_visible("#uploadedPdfNextBtn")
                    browser.until("uploadedSealCurrentPage===2")
                    browser.click_visible('#uploadedPdfEditor [data-editor-tool="text"]')
                    browser.run("fill", "#uploadedSealTextInput", "合成文件編輯驗收")
                    browser.click_visible("#addUploadedTextBtn")
                    browser.until("uploadedSealEditorState.elements.some(e=>e.kind==='text')&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration&&!uploadedSealEditorRuntime.saving")
                    browser.click_visible('#uploadedPdfEditor [data-editor-tool="select"]')
                    browser.evaluate("uploadedSealEditorRuntime.selectedIds.clear();renderUploadedSealWorkbench();true")
                    browser.until("!document.querySelector('.toast.show')")
                    browser.evaluate("document.querySelector('#uploadedPdfEditor').scrollIntoView({block:'start',behavior:'instant'});true")
                    browser.run("snapshot", "-i")
                    browser.run("screenshot", str(output / f"{label}-{role}-{device}-viewport.png"))
                    browser.evaluate("document.querySelector('#uploadedPdfCanvas').scrollIntoView({block:'center',behavior:'instant'});true")
                    browser.run("screenshot", str(output / f"{label}-{role}-{device}-canvas.png"))
                    row["editor"] = browser.evaluate(EDITOR_AUDIT)
                    row["layout"] = browser.evaluate(AUDIT_JS)
                    row["checks"]["noDocumentOverflow"] = not row["layout"]["overflow"]
                    row["checks"]["noUnhandledErrors"] = not row["layout"]["errors"]
                    row["checks"]["canvasRendered"] = row["editor"]["canvas"]["width"] > 0
                    row["checks"]["noSubmissionOrStamp"] = not browser.evaluate("uploadedSealEditorState.elements.some(e=>e.kind==='seal')")
                    if args.no_seals:
                        row["checks"]["noSealLimitationVisible"] = browser.evaluate("!document.querySelector('#uploadedSealAvailabilityNotice').hidden&&document.querySelector('#uploadedPdfEditor [data-editor-tool=seal]').disabled")
                    row["mutationCount"] = sum(e["method"] != "GET" for e in api[request_start:])
                    if not args.baseline_ref:
                        geometry = row["editor"]["geometry"]
                        row["checks"]["canvasStageOverlayGeometryMatches"] = all(abs(geometry["canvas"][axis] - geometry[part][axis]) <= 1 for part in ("stage", "overlay") for axis in ("width", "height"))
                        verify_after(browser, fixture, auth, row, output)
                    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
                    print(json.dumps({"stage": label, "role": role, "device": device, "checks": row["checks"], "editor": row["editor"]}, ensure_ascii=False), flush=True)
            return int(any(not all(row["checks"].values()) for row in report["journeys"]))
    except Exception as error:
        report["errorCode"] = str(error) if str(error).startswith(("browser_", "synthetic_")) else type(error).__name__
        try:
            report["failure"] = browser.evaluate("(()=>{const e=document.querySelector('#uploadedEditorSvgLayer [data-editor-element-id]'),r=e?.getBoundingClientRect(),hit=r&&document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return {pages:uploadedSealEditorState.pages.length,tool:uploadedSealEditorRuntime.tool,uploading:uploadedSealEditorRuntime.uploading,errors:window.__fixtureErrors||[],objectRect:r?.toJSON(),objectCenterHit:hit?{tag:hit.tagName,id:hit.id,kind:hit.getAttribute('class')}:null}})()")
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
    """Common editing and secondary surfaces remain operable and non-destructive."""
    document_id = browser.evaluate("uploadedSealEditorRuntime.documentId")
    saved = fixture._expect_json("GET", f"/api/official-documents/{document_id}/editor-state", 200, token=auth["token"])
    state = saved.get("state") or saved.get("editor_state")
    row["checks"]["textPersisted"] = any(e.get("properties", {}).get("text") == "合成文件編輯驗收" for e in state.get("elements", []))
    browser.click_visible("#uploadedEditorUndoBtn")
    browser.until("!uploadedSealEditorState.elements.some(e=>e.kind==='text')")
    browser.click_visible("#uploadedEditorRedoBtn")
    browser.until("uploadedSealEditorState.elements.some(e=>e.kind==='text')")
    row["checks"]["undoRedo"] = True
    browser.until("uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration&&!uploadedSealEditorRuntime.saving")
    browser.evaluate("window.__compactStateBefore=JSON.stringify(uploadedSealEditorState);window.__compactGeneration=uploadedSealEditorRuntime.dirtyGeneration;true")
    browser.click_visible("#uploadedEditorMoreTools > summary")
    browser.run("snapshot", "-i")
    browser.run("screenshot", str(output / f"after-{row['role']}-{row['device']}-more-tools.png"))
    row["checks"]["allAdvancedToolsReachable"] = browser.evaluate("['replacement','image','shape','checkmark','highlight','redaction'].every(kind=>{const e=document.querySelector('#uploadedEditorMoreTools [data-editor-tool='+kind+']');return !!e&&e.getClientRects().length>0&&!e.disabled})")
    browser.run("press", "Escape")
    row["checks"]["moreToolsEscapeReturnsFocus"] = browser.evaluate("!document.querySelector('#uploadedEditorMoreTools').open&&document.activeElement===document.querySelector('#uploadedEditorMoreTools > summary')")
    browser.click_visible("#uploadedEditorMoreTools > summary")
    browser.click_visible('#uploadedEditorMoreTools [data-editor-tool="shape"]')
    row["checks"]["advancedToolSelection"] = browser.evaluate("uploadedSealEditorRuntime.tool==='shape'&&!document.querySelector('#uploadedEditorMoreTools').open")
    row["checks"]["advancedToolReturnsFocus"] = browser.evaluate("document.activeElement===document.querySelector('#uploadedEditorMoreTools > summary')")
    browser.click_visible('#uploadedPdfEditor [data-editor-tool="select"]')
    browser.click_visible("#uploadedEditorSeamToggleBtn")
    browser.run("snapshot", "-i")
    browser.run("screenshot", str(output / f"after-{row['role']}-{row['device']}-seam.png"))
    row["checks"]["seamOnDemand"] = browser.evaluate("!document.querySelector('#uploadedEditorSeamPanel').hidden&&document.querySelector('#uploadedEditorSeamToggleBtn').getAttribute('aria-expanded')==='true'")
    browser.click_visible("#uploadedEditorSeamCloseBtn")
    row["checks"]["seamCloseReturnsFocus"] = browser.evaluate("document.querySelector('#uploadedEditorSeamPanel').hidden&&document.activeElement===document.querySelector('#uploadedEditorSeamToggleBtn')")
    row["checks"]["seamCloseRestoresCompactSelect"] = browser.evaluate("uploadedSealEditorRuntime.tool==='select'&&document.querySelector('#uploadedEditorGeneralOptions').hidden")
    browser.click_visible("#uploadedEditorThumbnailToggleBtn")
    browser.run("snapshot", "-i")
    browser.run("screenshot", str(output / f"after-{row['role']}-{row['device']}-pages.png"))
    row["checks"]["pageManagementReachable"] = browser.evaluate("[...document.querySelectorAll('#uploadedEditorPageActions button')].length===5&&[...document.querySelectorAll('#uploadedEditorPageActions button')].every(e=>e.getClientRects().length>0)&&document.querySelector('#uploadedEditorImportPdfBtn').getClientRects().length>0")
    browser.until("[...document.querySelectorAll('#uploadedPdfThumbnailList canvas')].every(e=>e.dataset.rendered==='0')")
    browser.evaluate("document.querySelector('#uploadedPdfThumbnailList canvas').dataset.rendered='error';renderUploadedSealWorkbench();true")
    browser.until("document.querySelector('#uploadedPdfThumbnailList canvas').dataset.rendered==='0'")
    row["checks"]["thumbnailRetryWhileOpen"] = True
    browser.click_visible("#uploadedEditorThumbnailCloseBtn")
    browser.click_visible("#uploadedEditorViewOptions > summary")
    browser.run("select", "#uploadedEditorReviewSelect", "original")
    browser.until("uploadedSealEditorRuntime.reviewMode==='original'&&document.querySelector('#uploadedEditorViewSummary').textContent.includes('唯讀')")
    browser.run("screenshot", str(output / f"after-{row['role']}-{row['device']}-original.png"))
    row["checks"]["originalReadonly"] = browser.evaluate("[...document.querySelectorAll('#uploadedPdfEditor [data-editor-tool]')].every(e=>e.disabled)")
    if not browser.evaluate("document.querySelector('#uploadedEditorViewOptions').open"):
        browser.click_visible("#uploadedEditorViewOptions > summary")
    browser.run("select", "#uploadedEditorReviewSelect", "edited")
    browser.until("uploadedSealEditorRuntime.reviewMode==='edited'&&!document.querySelector('#uploadedPdfEditor [data-editor-tool=text]').disabled")
    browser.run("press", "Escape")
    row["checks"]["viewAndMenusPreserveState"] = browser.evaluate("JSON.stringify(uploadedSealEditorState)===window.__compactStateBefore&&uploadedSealEditorRuntime.dirtyGeneration===window.__compactGeneration")
    row["checks"]["thumbnailNodesReused"] = browser.evaluate("(()=>{const first=document.querySelector('#uploadedPdfThumbnailList canvas');renderUploadedSealWorkbench();return first===document.querySelector('#uploadedPdfThumbnailList canvas')})()")
    browser.click_visible('#uploadedPdfEditor [data-editor-tool="select"]')
    browser.click_visible('#uploadedEditorSvgLayer .editor-object-hit')
    row["checks"]["directCanvasSelection"] = browser.evaluate("uploadedSealEditorRuntime.selectedIds.has(uploadedSealEditorState.elements[0].id)")
    point = browser.evaluate("(()=>{window.__beforeDrag=JSON.stringify(uploadedSealEditorState.elements);const r=document.querySelector('#uploadedEditorSvgLayer .editor-object-hit').getBoundingClientRect();return {x:r.x+4,y:r.y+r.height/2+8}})()")
    browser.run("mouse", "move", str(round(point["x"])), str(round(point["y"])))
    browser.run("mouse", "down")
    browser.run("mouse", "move", str(round(point["x"] + 24)), str(round(point["y"] + 16)))
    browser.run("mouse", "up")
    browser.until("JSON.stringify(uploadedSealEditorState.elements)!==window.__beforeDrag&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration&&!uploadedSealEditorRuntime.saving")
    moved = fixture._expect_json("GET", f"/api/official-documents/{document_id}/editor-state", 200, token=auth["token"])
    moved_state = moved.get("state") or moved.get("editor_state")
    row["checks"]["directDragPersisted"] = any(moved_state["elements"][0][axis] != state["elements"][0][axis] for axis in ("x", "y"))
    browser.click_visible("#uploadedEditorUndoBtn")
    browser.until("JSON.stringify(uploadedSealEditorState.elements)===window.__beforeDrag&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration&&!uploadedSealEditorRuntime.saving")
    row["checks"]["dragUndoRestoresCoordinates"] = True
    if row["device"] == "mobile":
        browser.click_visible('#uploadedPdfEditor [data-editor-tool="select"]')
        browser.click_visible('#uploadedEditorSvgLayer .editor-object-hit')
        browser.click_visible("#uploadedEditorPropertiesToggleBtn")
        browser.until("document.activeElement===document.querySelector('#uploadedEditorPropertiesCloseBtn')")
        found_copy_summary = False
        for _ in range(18):
            browser.run("press", "Tab")
            if browser.evaluate("document.activeElement?.tagName==='SUMMARY'&&document.activeElement.textContent.includes('複製到其他頁')"):
                found_copy_summary = True
                break
        row["checks"]["mobileKeyboardReachesCopyDisclosure"] = found_copy_summary
        if found_copy_summary:
            browser.run("press", "Enter")
            browser.run("press", "Tab")
            row["checks"]["mobileKeyboardEntersCopyInput"] = browser.evaluate("document.activeElement===document.querySelector('#uploadedEditorCopyPages')")
        browser.run("screenshot", str(output / f"after-{row['role']}-{row['device']}-properties.png"))
        browser.run("press", "Escape")
        row["checks"]["mobilePropertiesEscapeReturnsFocus"] = browser.evaluate("document.activeElement===document.querySelector('#uploadedEditorPropertiesToggleBtn')&&!document.body.classList.contains('pdf-editor-mobile-drawer-open')")
        browser.evaluate("uploadedSealEditorRuntime.selectedIds.clear();renderUploadedSealWorkbench();true")
    row["afterInteractionLayout"] = browser.evaluate(EDITOR_AUDIT)
    row["checks"]["allEditorTargets44px"] = not row["afterInteractionLayout"]["shortTargets"]
    row["checks"]["noInteractionErrors"] = not row["afterInteractionLayout"]["errors"]
    row["checks"]["noInteractionOverflow"] = row["afterInteractionLayout"]["pageWidth"] <= row["afterInteractionLayout"]["viewport"] + 1
    stale = fixture._request("PUT", f"/api/official-documents/{document_id}/editor-state", token=auth["token"], json_body={"revisionNo": 0, "baseManifestSha256": "0" * 64, "state": state})
    outsider = isolated_browser_session(fixture, "department_head", entity_id="E2")
    denied = fixture._request("GET", f"/api/official-documents/{document_id}/editor-state", token=outsider["token"])
    row["checks"]["staleSaveStill409"] = stale.status == 409
    row["checks"]["crossCompanyStill403"] = denied.status == 403
    if row["role"] == "staff" and row["device"] == "mobile":
        row["responsiveWidths"] = []
        for width in (375, 430, 760):
            browser.run("set", "viewport", str(width), "844")
            browser.evaluate("renderUploadedPdfPage().then(()=>true)")
            audit = browser.evaluate(EDITOR_AUDIT)
            geometry = audit["geometry"]
            result = {"width": width, "noOverflow": audit["pageWidth"] <= width + 1, "targets44px": not audit["shortTargets"], "geometryMatches": all(abs(geometry["canvas"][axis] - geometry[part][axis]) <= 1 for part in ("stage", "overlay") for axis in ("width", "height"))}
            row["responsiveWidths"].append(result)
        row["checks"]["additionalMobileTabletWidths"] = all(all(item[key] for key in ("noOverflow", "targets44px", "geometryMatches")) for item in row["responsiveWidths"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-ref", default="")
    parser.add_argument("--no-seals", action="store_true")
    parser.add_argument("--roles", nargs="+", choices=("staff", "section_chief", "department_head", "admin_director", "ga_chief", "ceo"), default=["staff"])
    raise SystemExit(run(parser.parse_args()))
