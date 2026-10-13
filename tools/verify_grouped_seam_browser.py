"""Real editor/save/seam controls on disposable localhost synthetic records.

This verifies UI -> shipping HTTP API -> authorized server readback and
prepared-PDF bytes. It never signs in a real person, contacts hosted services,
submits approval, final-stamps a real file, or invokes government exchange.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend
from PIL import Image, ImageDraw
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as Fixture, QuietAcceptanceHandler
from tools.six_role_browser_acceptance import AUDIT_JS, TELEMETRY, require_local_origin
from tools.verify_editor_applicant_browser import FinanceMirror
from tools.verify_editor_simplified_browser import EDITOR_AUDIT
from tools.ux_complete_browser_acceptance import BRIDGE
import tools.backup_drill_browser_acceptance as transport


GROUP_SNAPSHOT = """(()=>[...EDOCSeam.groups(uploadedSealEditorState)].map(([id,members])=>({
 id,count:members.length,pages:members.map(e=>uploadedSealEditorState.pages.findIndex(p=>p.pageId===e.pageId)+1),
 parts:members.map(e=>e.properties.seamPartIndex),partCounts:members.map(e=>e.properties.seamPartCount),
 edges:members.map(e=>e.properties.seamEdge),modes:members.map(e=>e.properties.seamMode),
 offsets:members.map(e=>EDOCSeam.offsetPt(uploadedSealEditorState.pages.find(p=>p.pageId===e.pageId),e)/EDOCSeam.ptPerMm),
 dimensions:members.map(e=>({width:e.width,height:e.height})),
 slices:members.map(e=>EDOCSeam.previewSlice(e,e.width,e.height)),
 bindings:members.map(e=>({sealId:e.properties.sealId,fileId:e.properties.sealFileId,sha256:e.properties.sealFileSha256}))
})))()"""


def check_groups(groups: list, seal: dict, edges: tuple[str, str]) -> bool:
    """Require actual 5+2 members with full geometry and fractional crops."""
    if len(groups) != 2:
        return False
    for group, pages, edge in zip(groups, (list(range(1, 6)), [6, 7]), edges):
        count = len(pages)
        if (group["count"] != count or group["pages"] != pages
                or group["parts"] != list(range(count))
                or group["partCounts"] != [count] * count
                or group["edges"] != [edge] * count
                or group["modes"] != ["grouped"] * count):
            return False
        for part, (dimension, crop, binding) in enumerate(zip(group["dimensions"], group["slices"], group["bindings"])):
            expected = seal["width_mm"] * 72 / 25.4
            if abs(dimension["width"] - expected) > 0.001 or abs(dimension["height"] - expected) > 0.001:
                return False
            axis = "height" if edge in {"top", "bottom"} else "width"
            if abs(crop["clip"][axis] / dimension[axis] - 1 / count) > 0.00001:
                return False
            if any(abs(crop["image"][size] - dimension[size]) > 0.001 for size in ("width", "height")):
                return False
            position_axis = "y" if axis == "height" else "x"
            target = dimension[axis] * (1 - 1 / count) if edge in {"right", "bottom"} else 0
            transform = re.fullmatch(r"matrix\(([^)]+)\)", crop["image"].get("transform", ""))
            try:
                matrix = [float(value) for value in transform.group(1).split()] if transform else []
            except ValueError:
                return False
            # These browser cases have unrotated pages. A 1:1 identity linear
            # part plus the exact slice translation proves original-size crops,
            # including the viewport-safe transform now used by the editor.
            expected_shift = target - dimension[axis] * part / count
            expected_matrix = [1, 0, 0, 1, expected_shift if position_axis == "x" else 0,
                               expected_shift if position_axis == "y" else 0]
            if (abs(crop["clip"][position_axis] - target) > 0.001
                    or crop["image"]["x"] != 0 or crop["image"]["y"] != 0
                    or len(matrix) != 6 or any(abs(value - expected) > 0.001 for value, expected in zip(matrix, expected_matrix))):
                return False
            if binding != {"sealId": seal["id"], "fileId": seal["file_id"], "sha256": seal["sha256"]}:
                return False
    return True


def synthetic_pdf(path: Path) -> None:
    writer = canvas.Canvas(str(path), pagesize=A4)
    for number in range(1, 8):
        writer.setFont("Helvetica-Bold", 22)
        writer.drawString(48, 785, f"SYNTHETIC PAGE {number} / 7")
        writer.setFont("Helvetica", 12)
        writer.drawString(48, 758, "Grouped seam acceptance - no real contract or personal data")
        writer.rect(48, 60, A4[0] - 96, A4[1] - 190)
        writer.drawCentredString(A4[0] / 2, 35, f"Page {number} / 7")
        writer.showPage()
    writer.save()


def prepare_company_seal() -> dict:
    """Use the normal file validator against a wholly synthetic 25mm stamp."""
    raster = Image.new("RGBA", (500, 500), (255, 255, 255, 0))
    draw = ImageDraw.Draw(raster)
    for index, color in enumerate(((180, 0, 0, 255), (160, 30, 0, 255), (140, 60, 0, 255), (120, 90, 0, 255), (100, 120, 0, 255))):
        draw.rectangle((index * 100 + 5, 5, index * 100 + 94, 494), outline=color, width=7)
        draw.text((index * 100 + 40, 240), str(index + 1), fill=color)
    stream = io.BytesIO(); raster.save(stream, format="PNG")
    with backend.connect() as conn:
        row = conn.execute("SELECT id FROM company_seals WHERE company_id='CO-001' AND seal_category='establishment_seal' AND seal_size_type='large_seal' AND is_active=1 ORDER BY id LIMIT 1").fetchone()
        if not row:
            raise AssertionError("synthetic_company_large_slot_missing")
        backend.upload_company_seal_file(conn, row["id"], {
            "file_name": "synthetic-company-large-not-a-real-seal.png", "file_mime_type": "image/png",
            "content_base64": base64.b64encode(stream.getvalue()).decode(),
            "actor": "isolated-grouped-seam-fixture", "render_width_mm": 25, "render_height_mm": 25,
        })
        file_meta = backend.require_current_company_seal_file(conn, row["id"])
        conn.commit()
        return {"id": row["id"], "file_id": file_meta["id"], "sha256": file_meta["file_hash"], "width_mm": 25}


def run(output: Path) -> dict:
    output = output.resolve(); output.mkdir(parents=True, exist_ok=True)
    ui_sources = {name: (ROOT / name).read_bytes() for name in ("index.html", "app.js", "styles.css", "editor-seam.js")}
    report = {"scope": "loopback_synthetic_browser_shipping_http", "productionChanged": False,
              "hostedVerified": False, "humanSSOVerified": False, "physicalDeviceVerified": False,
              "governmentExchange": "DISABLED", "approvalSubmitted": False, "finalStampExecuted": False,
              "sourceAppSha256": hashlib.sha256(ui_sources["app.js"]).hexdigest(),
              "frozenUiHashes": {name: hashlib.sha256(data).hexdigest() for name, data in ui_sources.items()},
              "cases": [], "requests": [], "stage": "setup"}
    original_head, original_json, original_put = QuietAcceptanceHandler.send_head, QuietAcceptanceHandler.send_json, QuietAcceptanceHandler.do_PUT
    fault = {"status": 0, "delay": False, "reached": threading.Event(), "release": threading.Event()}

    def head(handler):
        path = urlparse(handler.path).path
        name = "index.html" if path in {"/", "/index.html"} else path.lstrip("/")
        if name not in ui_sources:
            return original_head(handler)
        data = ui_sources[name]
        if name == "index.html":
            data = data.replace(b"<head>", b"<head>" + TELEMETRY.encode(), 1)
        content_type = "application/javascript" if name.endswith(".js") else "text/css" if name.endswith(".css") else "text/html; charset=utf-8"
        handler.send_response(200); handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(data))); handler.end_headers(); return io.BytesIO(data)

    def trace(handler, data, status=200, extra_headers=None):
        path = urlparse(handler.path).path
        if path.startswith("/api/"):
            report["requests"].append({"method": handler.command, "path": path, "status": status})
        return original_json(handler, data, status, extra_headers)

    def put(handler):
        if fault["delay"] and urlparse(handler.path).path.endswith("/editor-state"):
            fault["reached"].set()
            if not fault["release"].wait(15):
                handler.read_json(); handler.send_json({"error": "request_rejected", "detail": "synthetic_delay_timeout"}, 503)
                return
        if fault["status"] and urlparse(handler.path).path.endswith("/editor-state"):
            handler.read_json()
            status = fault["status"]
            handler.send_json({"error": "request_rejected" if status == 409 else "forbidden",
                               "detail": "editor_revision_conflict" if status == 409 else "synthetic_save_forbidden"}, status)
            return
        return original_put(handler)

    browser = None
    headless = Path.home() / "Library/Caches/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell"
    browser_env = {"EDOC_TEST_BROWSER_PATH": str(headless)} if headless.is_file() else {}
    with mock.patch.object(QuietAcceptanceHandler, "send_head", head), mock.patch.object(QuietAcceptanceHandler, "send_json", trace), mock.patch.object(QuietAcceptanceHandler, "do_PUT", put), mock.patch.object(transport, "PLAYWRIGHT_BRIDGE", BRIDGE), mock.patch.dict(os.environ, browser_env):
        Fixture.setUpClass(); require_local_origin(Fixture.origin)
        try:
            seal = prepare_company_seal(); report["syntheticSeal"] = seal
            pdf = output / "synthetic-seven-pages.pdf"; synthetic_pdf(pdf)
            mirror = FinanceMirror(Fixture)
            directory = mirror.production_function(backend.supabase_finance_directory)
            authority = mirror.production_function(backend.authoritative_finance_unit)
            authority.__kwdefaults__ = backend.authoritative_finance_unit.__kwdefaults__
            applicant = mirror.production_function(backend.authoritative_editor_applicant_department)
            browser = transport.LocalPlaywrightBrowser(Fixture.origin)
            with mock.patch.object(backend, "local_finance_directory", side_effect=lambda conn, session: directory(session)), mock.patch.object(backend, "authoritative_finance_unit", side_effect=authority), mock.patch.object(backend, "authoritative_editor_applicant_department", side_effect=applicant):
                for device, width, height in (("desktop", 1440, 1000), ("tablet", 820, 1100), ("mobile", 390, 844)):
                    row = {"device": device, "checks": {}, "edgeCases": []}; report["cases"].append(row)
                    auth = isolated_browser_session(Fixture, "staff", entity_id="E1")
                    open_editor(browser, auth, device, width, height)
                    upload_pdf(browser, pdf, device)
                    row["checks"]["stampActionUsesCanonicalUseSealLabel"] = browser.evaluate("document.querySelector('#uploadedPdfEditor [data-editor-tool=seal]').textContent==='用印'")
                    browser.add_pdf_text("Synthetic edited text " + device)
                    title = "合成七頁用印驗收最新主旨 " + device
                    browser.run("fill", "#uploadedSealTitle", title)
                    manual_save(browser, "uploadedEditorSaveDraftBtn")
                    row["checks"]["headerSaveFocusPreserved"] = browser.evaluate("document.activeElement.id==='uploadedEditorSaveDraftBtn'")
                    before_keyboard = sum(r["method"] == "PUT" and r["path"].endswith("/editor-state") for r in report["requests"])
                    if row["checks"]["headerSaveFocusPreserved"]:
                        browser.run("press", "Enter")
                        browser.until("!uploadedSealApplicationRuntime.manualSaveOperation&&!uploadedSealEditorRuntime.saving&&document.querySelector('#uploadedEditorSaveStatus').textContent==='草稿已暫存'")
                    row["checks"]["keyboardSaveUsesSameHandler"] = sum(r["method"] == "PUT" and r["path"].endswith("/editor-state") for r in report["requests"]) == before_keyboard + 1 and browser.evaluate("document.activeElement.id==='uploadedEditorSaveDraftBtn'")
                    report["stage"] = device + ":save_preserves_new_field_focus"
                    fault["delay"] = True; fault["reached"].clear(); fault["release"].clear()
                    browser.click_visible("#uploadedEditorSaveDraftBtn")
                    browser.until("!!uploadedSealApplicationRuntime.manualSaveOperation&&uploadedSealEditorRuntime.saving")
                    if not fault["reached"].wait(5):
                        raise AssertionError("synthetic_delayed_save_not_reached")
                    browser.click_visible("#uploadedSealReason")
                    edited_reason = "暫存中仍可繼續輸入，完成後不搶焦點 " + device
                    browser.run("fill", "#uploadedSealReason", edited_reason)
                    fault["delay"] = False; fault["release"].set()
                    browser.until("!uploadedSealApplicationRuntime.manualSaveOperation&&!uploadedSealEditorRuntime.saving&&!uploadedSealApplicationRuntime.promise&&document.querySelector('#uploadedEditorSaveStatus').textContent==='草稿已暫存'")
                    row["checks"]["busySaveDoesNotStealNewFieldFocus"] = browser.evaluate("document.activeElement.id==='uploadedSealReason'&&document.querySelector('#uploadedSealReason').value===" + json.dumps(edited_reason))
                    document_id = browser.evaluate("uploadedSealEditorRuntime.documentId")
                    detail = Fixture._expect_json("GET", f"/api/official-documents/{document_id}", 200, token=auth["token"])
                    state = Fixture._expect_json("GET", f"/api/official-documents/{document_id}/editor-state", 200, token=auth["token"])["state"]
                    row["checks"]["latestMetadataAndTextReadback"] = detail["title"] == title and detail["request_reason"] == edited_reason and any(e.get("properties", {}).get("text") == "Synthetic edited text " + device for e in state["elements"])
                    browser.click_visible("#uploadedEditorSeamToggleBtn")
                    row["checks"]["seamAutoSelectsOnlyCompanyLarge"] = browser.evaluate("selectedUploadedSeal()?.seal_category==='establishment_seal'&&selectedUploadedSeal()?.seal_size_type==='large_seal'&&[...document.querySelector('#uploadedSealCategorySelect').options].every(o=>o.value==='establishment_seal')&&[...document.querySelector('#uploadedSealSizeSelect').options].every(o=>o.value==='large_seal')")
                    for edge in ("right", "left", "top", "bottom"):
                        report["stage"] = device + ":edge:" + edge
                        while browser.evaluate("document.querySelectorAll('#uploadedEditorSeamGroups [data-seam-delete]').length"):
                            browser.click_visible("#uploadedEditorSeamGroups article:first-child [data-seam-delete]")
                        browser.run("select", "#uploadedEditorSeamEdge", edge)
                        browser.click_visible("#uploadedEditorSeamAddBtn")
                        groups = browser.evaluate(GROUP_SNAPSHOT)
                        passed = check_groups(groups, seal, (edge, edge))
                        row["edgeCases"].append({"edge": edge, "groups": groups, "passed": passed})
                        row["checks"][edge + "FivePlusTwoFractionalParts"] = passed
                        browser.run("screenshot", str(output / f"{device}-{edge}-seam.png"))
                    report["stage"] = device + ":independent_position"
                    browser.run("select", "#uploadedEditorSeamGroups article:nth-child(1) [data-seam-edge]", "left")
                    browser.run("select", "#uploadedEditorSeamGroups article:nth-child(2) [data-seam-edge]", "top")
                    browser.run("fill", "#uploadedEditorSeamGroups article:nth-child(1) [data-seam-position]", "31")
                    browser.run("press", "Tab")
                    browser.run("fill", "#uploadedEditorSeamGroups article:nth-child(2) [data-seam-position]", "56")
                    browser.run("press", "Tab")
                    groups = browser.evaluate(GROUP_SNAPSHOT)
                    row["checks"]["independentGroupEdgeAndOffset"] = check_groups(groups, seal, ("left", "top")) and all(abs(offset - target) < .01 for group, target in zip(groups, (31, 56)) for offset in group["offsets"])
                    manual_save(browser, "uploadedEditorSaveDraftFooterBtn")
                    row["checks"]["footerSaveFocusPreserved"] = browser.evaluate("document.activeElement.id==='uploadedEditorSaveDraftFooterBtn'")
                    row["layout"] = browser.evaluate(AUDIT_JS); row["editor"] = browser.evaluate(EDITOR_AUDIT)
                    row["checks"]["noOverflowAndAllEditorTargets44"] = not row["layout"]["overflow"] and not row["editor"]["shortTargets"]
                    browser.run("screenshot", str(output / f"{device}-saved.png"))
                    report["stage"] = device + ":reopen_actual_queue"
                    browser.run("open", Fixture.origin + f"/?reopen={time.monotonic_ns()}#electronicSeal")
                    browser.until("document.querySelector('[data-electronic-seal-open=" + json.dumps(document_id) + "]')")
                    browser.click_visible("#electronicSealWorkQueue > summary")
                    browser.click_visible('[data-electronic-seal-open="' + document_id + '"]')
                    browser.until("uploadedSealEditorRuntime.documentId===" + json.dumps(document_id) + "&&uploadedSealEditorState.pages.length===7&&!uploadedSealApplicationRuntime.openPromise&&!uploadedSealEditorRuntime.sealOptionsLoading", timeout=40)
                    row["checks"]["reopenPreservesImmutableBindingsAndGroups"] = check_groups(browser.evaluate(GROUP_SNAPSHOT), seal, ("left", "top"))
                    report["stage"] = device + ":preflight_actual_action"
                    browser.until("!document.querySelector('#submitUploadedSealBtn').disabled")
                    browser.click_visible("#submitUploadedSealBtn")
                    browser.until("uploadedSealEditorRuntime.reviewMode==='prepared'&&uploadedSealEditorRuntime.preparedPdfDocument&&!uploadedSealApplicationRuntime.submissionBusy", timeout=60)
                    prepared = browser.evaluate("({url:uploadedSealEditorRuntime.preparedUrl,hash:uploadedSealEditorRuntime.preparedSha256,locked:uploadedSealEditorRuntime.locked,pages:uploadedSealEditorRuntime.preparedPdfDocument.numPages})")
                    parsed = urlparse(prepared["url"])
                    if parsed.netloc and parsed.netloc != urlparse(Fixture.origin).netloc:
                        raise AssertionError("prepared_url_not_loopback")
                    downloaded = Fixture._request("GET", parsed.path, token=auth["token"])
                    prepared_pdf = output / f"{device}-prepared-confirmation-only.pdf"; prepared_pdf.write_bytes(downloaded.body)
                    downloaded_hash = hashlib.sha256(downloaded.body).hexdigest()
                    row["preparedFile"] = {"downloadStatus": downloaded.status, "sha256": downloaded_hash,
                                           "expectedSha256": prepared["hash"], "pages": prepared["pages"], "locked": prepared["locked"]}
                    row["checks"]["preparedFileSevenPagesExactHashNotSubmitted"] = downloaded.status == 200 and downloaded_hash.upper() == prepared["hash"].upper() and len(PdfReader(io.BytesIO(downloaded.body)).pages) == 7 and prepared["pages"] == 7 and prepared["locked"] is False
                    browser.run("screenshot", str(output / f"{device}-prepared.png"))
                    browser.click_visible("#uploadedEditorBackToEditBtn")
                    browser.until("uploadedSealEditorRuntime.reviewMode==='edited'")
                    verify_failures(browser, fault, row)
                    row["checks"]["noUnhandledBrowserErrors"] = not browser.evaluate("window.__fixtureErrors")
                    row["passed"] = all(row["checks"].values())
                    write_report(output, report); print(json.dumps({"device": device, "passed": row["passed"], "checks": row["checks"]}), flush=True)
                verify_missing_seals(browser, pdf, report)
            report["checks"] = {"noApprovalSubmitOrStampOrExchange": not any(r["method"] != "GET" and r["path"].endswith(("/submit", "/stamp", "/send", "/receive")) for r in report["requests"])}
            report["passed"] = all(row["passed"] for row in report["cases"]) and report["missingSeals"]["passed"] and all(report["checks"].values())
        except Exception as error:
            report["passed"] = False; report["errorCode"] = str(error) if isinstance(error, AssertionError) or str(error).startswith("browser_") else type(error).__name__
            if browser:
                try:
                    report["failure"] = browser.evaluate("({errors:window.__fixtureErrors,doc:uploadedSealEditorRuntime.documentId,pages:uploadedSealEditorState.pages.length,tool:uploadedSealEditorRuntime.tool,status:document.querySelector('#uploadedEditorSaveStatus')?.textContent,preflight:document.querySelector('#uploadedEditorPreflightStatus')?.textContent,notice:document.querySelector('#uploadedSealPickerStatus')?.textContent})")
                    browser.run("screenshot", str(output / "failure.png"))
                except Exception:
                    pass
        finally:
            fault["status"] = 0; fault["delay"] = False; fault["release"].set()
            if browser:
                browser.run("close")
            Fixture.tearDownClass()
    write_report(output, report); return report


def open_editor(browser, auth, device, width, height):
    browser.run("open", Fixture.origin + "/assets/favicon-32.png")
    browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
    browser.run("set", "viewport", str(width), str(height))
    browser.run("open", Fixture.origin + f"/?grouped={device}-{time.monotonic_ns()}#electronicSeal")
    browser.until("window.__fixtureTiming?.appInteractiveMs&&document.querySelector('#uploadedSealApprovalCategorySelect')?.options.length>1&&!uploadedSealEditorRuntime.directoryLoading&&!uploadedSealEditorRuntime.sealOptionsLoading", timeout=40)


def upload_pdf(browser, pdf, label):
    category = browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(e=>e.textContent.includes('合作意向書')).value")
    browser.run("select", "#uploadedSealApprovalCategorySelect", category)
    browser.run("fill", "#uploadedSealTitle", "合成七頁用印驗收 " + label)
    browser.run("fill", "#uploadedSealReason", "僅本機去識別化驗收，不送簽、不正式用印、不寄發。")
    browser.run("upload", "#uploadedSealPdfInput", str(pdf))
    browser.until("uploadedSealEditorState.pages.length===7&&!uploadedSealEditorRuntime.uploading&&!uploadedSealEditorRuntime.finalizingAsset&&!uploadedSealEditorRuntime.pendingEditorSave&&!uploadedSealEditorRuntime.saving&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration", timeout=50)


def manual_save(browser, button):
    browser.click_visible("#" + button)
    browser.until("!uploadedSealApplicationRuntime.manualSaveOperation&&!uploadedSealEditorRuntime.saving&&!uploadedSealApplicationRuntime.promise&&document.querySelector('#uploadedEditorSaveStatus').textContent==='草稿已暫存'", timeout=40)


def verify_failures(browser, fault, row):
    for status in (403, 409):
        fault["status"] = status
        title = "故障注入仍保留的主旨 " + str(status)
        browser.run("fill", "#uploadedSealTitle", title)
        browser.click_visible("#uploadedEditorSaveDraftBtn")
        browser.until("!uploadedSealApplicationRuntime.manualSaveOperation&&!uploadedSealEditorRuntime.saving&&document.querySelector('#uploadedEditorSaveStatus').classList.contains(" + json.dumps("conflict" if status == 409 else "error") + ")")
        row["checks"][f"http{status}KeepsInputNoFalseSaved"] = browser.evaluate("document.querySelector('#uploadedSealTitle').value===" + json.dumps(title) + "&&uploadedSealEditorState.elements.some(e=>e.kind==='text')&&document.querySelector('#uploadedEditorSaveStatus').textContent!=='草稿已暫存'")
        fault["status"] = 0
        if status == 403:
            manual_save(browser, "uploadedEditorSaveDraftBtn")


def verify_missing_seals(browser, pdf, report):
    report["stage"] = "mobile:missing_seals"
    with backend.connect() as conn:
        conn.execute("UPDATE company_seals SET is_active=0 WHERE company_id='CO-001'"); conn.commit()
    auth = isolated_browser_session(Fixture, "staff", entity_id="E1")
    open_editor(browser, auth, "no-seal", 390, 844)
    upload_pdf(browser, pdf, "no-seal")
    browser.add_pdf_text("Synthetic missing-seal draft text")
    manual_save(browser, "uploadedEditorSaveDraftBtn")
    checks = {"draftSavedWithoutStamp": browser.evaluate("document.querySelector('#uploadedEditorSaveStatus').textContent==='草稿已暫存'&&!document.querySelector('#uploadedEditorSaveDraftBtn').disabled")}
    browser.click_visible('#uploadedPdfEditor [data-editor-tool="seal"]')
    checks["stampPickerReachableAndExplainsMissingFile"] = browser.evaluate("!document.querySelector('#uploadedSealPicker').hidden&&!document.querySelector('#uploadedPdfEditor [data-editor-tool=seal]').disabled&&document.querySelector('#uploadedSealPickerStatus').textContent.includes('尚無已登錄並啟用')&&document.querySelector('#addSelectedStampBtn').disabled")
    browser.click_visible("#uploadedEditorSeamToggleBtn")
    checks["seamSettingsReachableWithoutFalseAdd"] = browser.evaluate("!document.querySelector('#uploadedEditorSeamPanel').hidden&&!document.querySelector('#uploadedEditorSeamToggleBtn').disabled&&document.querySelector('#uploadedEditorSeamAddBtn').disabled&&document.querySelector('#uploadedEditorSeamStatus').textContent.includes('尚無可用公司大章')")
    browser.run("screenshot", str(report_output := pdf.parent / "mobile-missing-seals.png"))
    report["missingSeals"] = {"checks": checks, "passed": all(checks.values()), "screenshot": report_output.name}


def write_report(output, report):
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); raise SystemExit(0 if run(args.output)["passed"] else 1)
