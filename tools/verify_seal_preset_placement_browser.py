"""Direct seal placement through the real UI and disposable loopback API.

Uses only deidentified Finance/session/PDF/seal fixtures. Frozen source bytes
bind each result to its tested implementation. Never touches production, real
accounts, approvals, final sealing, or official government exchange.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import time
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as Fixture, QuietAcceptanceHandler
from tools.six_role_browser_acceptance import AUDIT_JS, TELEMETRY, require_local_origin
from tools.ux_complete_browser_acceptance import BRIDGE
from tools.verify_grouped_seam_browser import (
    FinanceMirror, GROUP_SNAPSHOT, check_groups, manual_save, open_editor,
    prepare_company_seal, select_visible, synthetic_pdf, upload_pdf,
)
import tools.backup_drill_browser_acceptance as transport

SOURCE_NAMES = (
    "index.html", "app.js", "styles.css", "editor-seam.js", "editor-fluid.css",
    "workspace-select.js", "workspace-select.css", "workspace-navigation.css", "entry-bootstrap.js",
)
ELEMENT_SNAPSHOT = "JSON.parse(JSON.stringify(uploadedSealEditorState.elements))"
ORDINARY_SNAPSHOT = "JSON.parse(JSON.stringify(uploadedSealEditorState.elements.filter(e=>e.kind==='seal'&&!e.properties?.seamGroupId)))"


def check(row: dict, name: str, passed: bool) -> None:
    row.setdefault("checks", {})[name] = bool(passed)
    if not passed:
        raise AssertionError(name)


def capture(browser, output: Path, device: str, name: str, selector: str, row: dict) -> str:
    browser.evaluate("document.querySelector(" + json.dumps(selector) + ").scrollIntoView({block:'center',behavior:'instant'});true")
    filename = f"{device}-{name}.png"
    browser.run("screenshot", str(output / filename))
    audit = browser.evaluate(AUDIT_JS)
    audit["sealRasterAbsent"] = browser.evaluate("document.querySelectorAll('#uploadedEditorSvgLayer image').length===0&&uploadedSealEditorRuntime.sealPreviewUrls.size===0")
    audit["toolbarDoesNotCoverSealPlaceholders"] = browser.evaluate("""(()=>{const toolbar=document.querySelector('#uploadedEditorToolTray'),t=toolbar.getBoundingClientRect();return !toolbar.getClientRects().length||[...document.querySelectorAll('#uploadedEditorSvgLayer [data-seal-position]')].every(e=>{const r=e.getBoundingClientRect();return r.right<=t.left||r.left>=t.right||r.bottom<=t.top||r.top>=t.bottom;});})()""")
    row.setdefault("visualStates", {})[name] = audit
    check(row, name + "HasNoOverflowOrUnhandledErrors", not audit["overflow"] and not audit["errors"])
    check(row, name + "HasNoRealSealRaster", audit["sealRasterAbsent"])
    check(row, name + "ToolbarDoesNotCoverSealPlaceholders", audit["toolbarDoesNotCoverSealPlaceholders"])
    return filename


def inspect_dropdown(browser, identity: str, output: Path, device: str) -> dict:
    browser.until("!!document.querySelector(" + json.dumps("#" + identity) + ")?.tomselect")
    # The preceding keyboard selection can leave the same Tom Select focused.
    # Start this independent popup interaction from a genuine neutral click.
    browser.click_visible("#uploadedSealPresets legend")
    stage = "click"
    try:
        browser.click_visible("#" + identity + " + .ts-wrapper .ts-control")
        stage = "keyboard_open"
        browser.run("press", "ArrowDown")
        browser.until("document.querySelector(" + json.dumps("#" + identity) + ").tomselect.isOpen", timeout=4)
    except Exception as error:
        diagnostic = browser.evaluate("""(()=>{const s=document.querySelector(ID),t=s.tomselect,r=t.control.getBoundingClientRect();return {disabled:s.disabled,focused:t.isFocused,open:t.isOpen,rect:r.toJSON(),hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.outerHTML.slice(0,600),value:s.value,options:[...s.options].map(o=>o.value),control:t.control.outerHTML};})()""".replace("ID", json.dumps("#" + identity)))
        raise AssertionError("dropdown_" + stage + ":" + json.dumps(diagnostic, ensure_ascii=False)) from error
    result = browser.evaluate("""(()=>{const s=document.querySelector(ID),t=s.tomselect,a=t.control.getBoundingClientRect(),b=t.dropdown.getBoundingClientRect(),toolbar=document.querySelector('#uploadedEditorToolTray').getBoundingClientRect();return {
      trigger:a.toJSON(),popup:b.toJSON(),withinViewport:b.left>=-1&&b.right<=innerWidth+1&&b.top>=-1&&b.bottom<=innerHeight+1,
      sameWidth:Math.abs(a.width-b.width)<=1,anchored:Math.abs(a.left-b.left)<=1,
      separated:b.top>=a.bottom-1||b.bottom<=a.top+1,
      toolbarOverlapsPopup:!(b.right<=toolbar.left||b.left>=toolbar.right||b.bottom<=toolbar.top||b.top>=toolbar.bottom),
      target44:a.width>=44&&a.height>=44,
      open:t.isOpen,optionCount:s.options.length};})()""".replace("ID", json.dumps("#" + identity)))
    browser.run("screenshot", str(output / f"{device}-preset-dropdown.png"))
    browser.run("press", "Escape")
    browser.click_visible("#uploadedSealPresets legend")
    result["selectionVisibleAfterBlur"] = browser.evaluate("""(()=>{const t=document.querySelector(ID).tomselect,item=t.control.querySelector('.item');return !t.isFocused&&!!item&&item.getClientRects().length>0&&getComputedStyle(item).display!=='none'&&item.textContent.trim()==='小章';})()""".replace("ID", json.dumps("#" + identity)))
    return result


def drag_selected(browser) -> dict:
    before = browser.evaluate("(()=>{const id=[...uploadedSealEditorRuntime.selectedIds][0],e=editorElementById(id);return JSON.parse(JSON.stringify(e));})()")
    selector = "#uploadedEditorSvgLayer [data-editor-element-id=" + json.dumps(before["id"]) + "] [data-seal-position]"
    browser.evaluate("document.querySelector(" + json.dumps(selector) + ").scrollIntoView({block:'center',behavior:'instant'});true")
    rect = browser.evaluate("document.querySelector(" + json.dumps(selector) + ").getBoundingClientRect().toJSON()")
    x, y = rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2
    browser.run("mouse", "move", str(x), str(y))
    browser.run("mouse", "down")
    for step in range(1, 6):
        browser.run("mouse", "move", str(x + step * 5), str(y + step * 4))
    browser.run("mouse", "up")
    after = browser.evaluate("JSON.parse(JSON.stringify(editorElementById(" + json.dumps(before["id"]) + ")))")
    return {"before": before, "after": after}


def run(output: Path) -> dict:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sources = {name: (ROOT / name).read_bytes() for name in SOURCE_NAMES}
    report = {
        "scope": "loopback_synthetic_real_ui_shipping_http", "productionChanged": False,
        "realAccountUsed": False, "humanSSOVerified": False, "physicalDeviceVerified": False,
        "approvalSubmitted": False, "finalStampExecuted": False, "governmentExchange": "DISABLED",
        "frozenUiHashes": {name: hashlib.sha256(data).hexdigest() for name, data in sources.items()},
        "cases": [], "requests": [], "getRequestPaths": [], "stage": "setup",
    }
    original_head, original_json, original_get = QuietAcceptanceHandler.send_head, QuietAcceptanceHandler.send_json, QuietAcceptanceHandler.do_GET
    fault = {"catalogStatus": 0}

    def head(handler):
        path = urlparse(handler.path).path
        name = "index.html" if path in {"/", "/index.html"} else path.lstrip("/")
        if name not in sources:
            return original_head(handler)
        data = sources[name]
        if name == "index.html":
            data = data.replace(b"<head>", b"<head>" + TELEMETRY.encode(), 1)
        content_type = "application/javascript" if name.endswith(".js") else "text/css" if name.endswith(".css") else "text/html; charset=utf-8"
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        return io.BytesIO(data)

    def trace(handler, data, status=200, extra_headers=None):
        path = urlparse(handler.path).path
        if path.startswith("/api/"):
            report["requests"].append({"method": handler.command, "path": path, "status": status})
        return original_json(handler, data, status, extra_headers)

    def get(handler):
        path = urlparse(handler.path).path
        # Capture attempted binary downloads as well as JSON responses. A
        # forbidden preview request must fail this assertion even if it errors.
        if path.startswith("/api/"):
            report["getRequestPaths"].append(path)
        if fault["catalogStatus"] and re.fullmatch(r"/api/companies/[^/]+/seals", path):
            return handler.send_json({"error": "synthetic_catalog_failure", "detail": "synthetic_catalog_failure"}, fault["catalogStatus"])
        return original_get(handler)

    browser = None
    executable = Path(os.environ.get("EDOC_TEST_BROWSER_PATH") or str(Path.home() / "Library/Caches/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-mac-arm64/chrome-headless-shell"))
    if not executable.is_file():
        raise RuntimeError("local_chromium_unavailable")
    with mock.patch.object(QuietAcceptanceHandler, "send_head", head), mock.patch.object(QuietAcceptanceHandler, "send_json", trace), mock.patch.object(QuietAcceptanceHandler, "do_GET", get), mock.patch.object(transport, "PLAYWRIGHT_BRIDGE", BRIDGE), mock.patch.dict(os.environ, {"EDOC_TEST_BROWSER_PATH": str(executable)}):
        Fixture.setUpClass()
        require_local_origin(Fixture.origin)
        try:
            seal = prepare_company_seal("company")
            report["syntheticSeal"] = seal
            pdf = output / "synthetic-seven-pages.pdf"
            before_pdf = output.parent / "before" / "synthetic-seven-pages.pdf"
            if before_pdf.is_file():
                pdf.write_bytes(before_pdf.read_bytes())
            else:
                synthetic_pdf(pdf)
            report["syntheticPdfSha256"] = hashlib.sha256(pdf.read_bytes()).hexdigest()
            report["usesExactBeforePdfBytes"] = before_pdf.is_file() and pdf.read_bytes() == before_pdf.read_bytes()
            mirror = FinanceMirror(Fixture)
            directory = mirror.production_function(backend.supabase_finance_directory)
            authority = mirror.production_function(backend.authoritative_finance_unit)
            authority.__kwdefaults__ = backend.authoritative_finance_unit.__kwdefaults__
            applicant = mirror.production_function(backend.authoritative_editor_applicant_department)
            browser = transport.LocalPlaywrightBrowser(Fixture.origin)
            with mock.patch.object(backend, "local_finance_directory", side_effect=lambda conn, session: directory(session)), mock.patch.object(backend, "authoritative_finance_unit", side_effect=authority), mock.patch.object(backend, "authoritative_editor_applicant_department", side_effect=applicant):
                for device, width, height in (("desktop", 1440, 1000), ("tablet", 820, 1100), ("mobile", 390, 844)):
                    row = {"device": device, "width": width, "height": height, "checks": {}, "captures": []}
                    report["cases"].append(row)
                    auth = isolated_browser_session(Fixture, "staff", entity_id="E1")
                    report["stage"] = device + ":preset_before_upload"
                    open_editor(browser, auth, device, width, height)
                    check(row, "selectorsLiveInsideApplicationNotEditor", browser.evaluate("document.querySelector('#uploadedSealForm').contains(document.querySelector('#uploadedSealPicker'))&&document.querySelector('#uploadedSealForm').contains(document.querySelector('#uploadedEditorSeamSealSelect'))&&!document.querySelector('#uploadedPdfEditor').contains(document.querySelector('#uploadedSealPicker'))"))
                    select_visible(browser, "uploadedSealCategorySelect", seal["category"])
                    select_visible(browser, "uploadedSealSizeSelect", "small_seal")
                    check(row, "smallAndPrimaryLargeCanBeSelectedBeforeUpload", browser.evaluate("uploadedSealEditorState.pages.length===0&&selectedUploadedSeal()?.id===" + json.dumps(seal["small_id"]) + "&&selectedUploadedSeamSeal()?.id===" + json.dumps(seal["id"])))
                    row["dropdown"] = inspect_dropdown(browser, "uploadedSealSizeSelect", output, device)
                    check(row, "dropdownAnchoredBoundedWithoutToolbarOverlap", all(row["dropdown"][key] for key in ("withinViewport", "sameWidth", "anchored", "separated", "target44")) and not row["dropdown"]["toolbarOverlapsPopup"])
                    check(row, "smallSelectionVisibleAfterBlur", row["dropdown"]["selectionVisibleAfterBlur"])
                    row["captures"].append(capture(browser, output, device, "application-preset", "#uploadedSealPresets", row))
                    report["stage"] = device + ":upload_pdf"
                    upload_pdf(browser, pdf, device)
                    check(row, "preselectedSmallSurvivesUpload", browser.evaluate("selectedUploadedSeal()?.id===" + json.dumps(seal["small_id"])))
                    report["stage"] = device + ":ordinary_direct_placement"
                    browser.click_visible('#uploadedPdfEditor [data-editor-tool="seal"]')
                    browser.until("uploadedSealEditorState.elements.length===1&&document.activeElement.id==='uploadedEditorSvgLayer'")
                    ordinary = browser.evaluate(ORDINARY_SNAPSHOT)
                    check(row, "singleClickPlacesExactSmallOnceAndFocusesObject", len(ordinary) == 1 and ordinary[0]["properties"]["sealId"] == seal["small_id"] and browser.evaluate("uploadedSealEditorRuntime.tool==='select'&&uploadedSealEditorRuntime.selectedIds.size===1&&!document.querySelector('#uploadedEditorSeamPanel').getClientRects().length"))
                    before_key = ordinary[0]
                    browser.run("press", "ArrowRight")
                    after_key = browser.evaluate(ORDINARY_SNAPSHOT)[0]
                    check(row, "keyboardMoveRetainsPhysicalSizeAndBinding", abs(after_key["x"] - before_key["x"] - 1) < .001 and all(after_key[key] == before_key[key] for key in ("width", "height", "properties")))
                    row["drag"] = drag_selected(browser)
                    check(row, "dragMoveRetainsPhysicalSizeAndBinding", any(row["drag"]["before"][key] != row["drag"]["after"][key] for key in ("x", "y")) and all(row["drag"]["before"][key] == row["drag"]["after"][key] for key in ("width", "height", "properties")))
                    row["captures"].append(capture(browser, output, device, "ordinary-placement", "#uploadedPdfStage", row))
                    select_visible(browser, "uploadedSealStampType", "all_pages")
                    count_before = len(browser.evaluate(ORDINARY_SNAPSHOT))
                    browser.click_visible('#uploadedPdfEditor [data-editor-tool="seal"]')
                    all_ordinary = browser.evaluate(ORDINARY_SNAPSHOT)
                    added = all_ordinary[count_before:]
                    check(row, "allPagesPlacesSevenExactSmallBindings", len(added) == 7 and len({item["pageId"] for item in added}) == 7 and all(item["properties"]["sealId"] == seal["small_id"] for item in added))
                    report["stage"] = device + ":seam_direct_placement"
                    browser.click_visible("#uploadedEditorSeamToggleBtn")
                    browser.until("EDOCSeam.groups(uploadedSealEditorState).size===2&&document.activeElement.id==='uploadedEditorSvgLayer'")
                    groups = browser.evaluate(GROUP_SNAPSHOT)
                    check(row, "seamToolbarDirectlyCreatesFivePlusTwoLarge", check_groups(groups, seal, ("right", "right")))
                    check(row, "seamKeepsOrdinarySmallAndDoesNotOpenSettings", browser.evaluate("selectedUploadedSeal()?.id===" + json.dumps(seal["small_id"]) + "&&document.querySelector('#uploadedEditorSeamPanel').hidden"))
                    check(row, "seamGroupsShareHeightAndTenMmMargins", max(group["offsets"][0] for group in groups) - min(group["offsets"][0] for group in groups) < .01 and browser.evaluate("uploadedSealEditorState.elements.filter(e=>e.properties?.seamGroupId).every(e=>{const p=uploadedSealEditorState.pages.find(p=>p.pageId===e.pageId),top=EDOCSeam.offsetPt(p,e);return e.properties.seamPolicyVersion===EDOCSeam.CURRENT_POLICY&&top>=EDOCSeam.MARGIN_PT-.001&&top+e.height<=EDOCSeam.displayHeight(p)-EDOCSeam.MARGIN_PT+.001})"))
                    prior = browser.evaluate(ELEMENT_SNAPSHOT)
                    browser.click_visible("#uploadedEditorSeamToggleBtn")
                    check(row, "repeatedSeamSelectsExistingWithoutDuplicates", browser.evaluate(ELEMENT_SNAPSHOT) == prior and browser.evaluate("uploadedSealEditorRuntime.selectedIds.size===1&&[...uploadedSealEditorRuntime.selectedIds].every(id=>!!editorElementById(id)?.properties?.seamGroupId)"))
                    row["seamDrag"] = drag_selected(browser)
                    dragged_groups = browser.evaluate(GROUP_SNAPSHOT)
                    check(row, "seamCanDragVerticallyWithoutMovingOtherGroup", dragged_groups[0]["offsets"] != groups[0]["offsets"] and len(set(dragged_groups[0]["offsets"])) == 1 and dragged_groups[1]["offsets"] == groups[1]["offsets"] and all(row["seamDrag"]["before"][key] == row["seamDrag"]["after"][key] for key in ("x", "width", "height")) and all(row["seamDrag"]["before"]["properties"][key] == row["seamDrag"]["after"]["properties"][key] for key in ("sealId", "sealFileId", "sealFileSha256")))
                    row["captures"].append(capture(browser, output, device, "seam-placement", "#uploadedPdfStage", row))
                    browser.click_visible("#uploadedEditorSeamSettingsBtn")
                    browser.run("fill", "#uploadedEditorSeamGroups article:first-child [data-seam-position]", "31")
                    browser.run("press", "Tab")
                    positioned = browser.evaluate(GROUP_SNAPSHOT)
                    check(row, "numericPositionMovesOnlyOneGroup", all(abs(value - 31) < .01 for value in positioned[0]["offsets"]) and positioned[1]["offsets"] == groups[1]["offsets"])
                    browser.click_visible("#uploadedEditorSeamCloseBtn")
                    before_change = browser.evaluate(ELEMENT_SNAPSHOT)
                    select_visible(browser, "uploadedSealSizeSelect", "large_seal")
                    check(row, "changingPresetDoesNotRewriteExistingBindings", browser.evaluate(ELEMENT_SNAPSHOT) == before_change)
                    select_visible(browser, "uploadedSealSizeSelect", "small_seal")
                    report["stage"] = device + ":save_and_readback"
                    manual_save(browser, "uploadedEditorSaveDraftBtn")
                    document_id = browser.evaluate("uploadedSealEditorRuntime.documentId")
                    client_elements = browser.evaluate(ELEMENT_SNAPSHOT)
                    stored = Fixture._expect_json("GET", f"/api/official-documents/{document_id}/editor-state", 200, token=auth["token"])
                    check(row, "manualSavePersistsActualPlacementSnapshot", stored["state"]["elements"] == client_elements)
                    browser.run("open", Fixture.origin + f"/?preset-reopen={time.monotonic_ns()}#electronicSeal")
                    browser.until("document.querySelector('[data-electronic-seal-open=" + json.dumps(document_id) + "]')")
                    browser.click_visible("#electronicSealWorkQueue > summary")
                    browser.click_visible('[data-electronic-seal-open="' + document_id + '"]')
                    browser.until("uploadedSealEditorRuntime.documentId===" + json.dumps(document_id) + "&&uploadedSealEditorState.pages.length===7&&!uploadedSealApplicationRuntime.openPromise&&!uploadedSealEditorRuntime.hydrating&&!uploadedSealEditorRuntime.locked&&!uploadedSealEditorRuntime.sealOptionsLoading", timeout=40)
                    check(row, "reopenRestoresExactPlacementSnapshot", browser.evaluate(ELEMENT_SNAPSHOT) == client_elements)
                    row["captures"].append(capture(browser, output, device, "saved-reopened", "#uploadedPdfStage", row))
                    check(row, "reopenFinishesVisibleLoadingAndEnablesPlacement", browser.evaluate("!document.querySelector('#uploadedEditorSaveStatus').textContent.includes('載入')&&!document.querySelector('#uploadedEditorPreflightStatus').textContent.includes('已送出簽核')&&!document.querySelector('[data-editor-tool=seal]').disabled&&!document.querySelector('#uploadedEditorSeamToggleBtn').disabled"))
                    reopened_seal = browser.evaluate("selectedUploadedSeal().id")
                    browser.click_visible('#uploadedPdfEditor [data-editor-tool="seal"]')
                    browser.until("uploadedSealEditorState.elements.length===" + str(len(client_elements) + 1))
                    check(row, "reopenCanImmediatelyPlaceCurrentPreset", browser.evaluate(ORDINARY_SNAPSHOT)[-1]["properties"]["sealId"] == reopened_seal)
                    manual_save(browser, "uploadedEditorSaveDraftBtn")
                    client_elements = browser.evaluate(ELEMENT_SNAPSHOT)
                    reopened_stored = Fixture._expect_json("GET", f"/api/official-documents/{document_id}/editor-state", 200, token=auth["token"])
                    check(row, "reopenNewPlacementAlsoPersistsOnServer", reopened_stored["state"]["elements"] == client_elements)
                    report["stage"] = device + ":readonly_original"
                    browser.click_visible("#uploadedEditorViewSummary")
                    select_visible(browser, "uploadedEditorReviewSelect", "original")
                    browser.until("uploadedSealEditorRuntime.reviewMode==='original'")
                    check(row, "readonlyReviewBlocksBothPlacementTools", browser.evaluate("document.querySelector('[data-editor-tool=seal]').disabled&&document.querySelector('#uploadedEditorSeamToggleBtn').disabled&&document.querySelector('#uploadedSealPresets').hidden"))
                    check(row, "readonlyReviewDoesNotChangeSnapshot", browser.evaluate(ELEMENT_SNAPSHOT) == client_elements)
                    row["layout"] = browser.evaluate(AUDIT_JS)
                    check(row, "noDocumentOverflowOrUnhandledErrors", not row["layout"]["overflow"] and not row["layout"]["errors"])
                    check(row, "editorNeverHasRealSealRaster", browser.evaluate("document.querySelectorAll('#uploadedEditorSvgLayer image').length===0&&uploadedSealEditorRuntime.sealPreviewUrls.size===0"))
                    row["passed"] = True
                    write_report(output, report)
                    print(json.dumps({"device": device, "passed": True, "checks": len(row["checks"])}), flush=True)

                verify_unavailable(browser, seal, pdf, report, fault, output)
            check(report, "noPrivateSealPixelsRequested", not any(re.search(r"/(?:company-seals|seals)/[^/]+/(?:editor-preview|files|preview|download)", path) for path in report["getRequestPaths"]))
            check(report, "noApprovalOrFinalStampOrGovernmentExchange", not any(request["method"] != "GET" and request["path"].endswith(("/submit", "/stamp", "/send", "/receive")) for request in report["requests"]))
            report["passed"] = True
        except Exception as error:
            report["passed"] = False
            report["error"] = type(error).__name__ + ": " + str(error)
            if browser:
                try:
                    report["failure"] = browser.evaluate("({errors:window.__fixtureErrors,tool:uploadedSealEditorRuntime.tool,review:uploadedSealEditorRuntime.reviewMode,pages:uploadedSealEditorState.pages.length,elementCount:uploadedSealEditorState.elements.length,selected:[...uploadedSealEditorRuntime.selectedIds],catalog:uploadedSealCatalogState.status,status:document.querySelector('#uploadedEditorSaveStatus')?.textContent,hydrating:uploadedSealEditorRuntime.hydrating,locked:uploadedSealEditorRuntime.locked,opening:!!uploadedSealApplicationRuntime.openPromise,active:document.activeElement?.outerHTML.slice(0,500)})")
                    browser.run("screenshot", str(output / "failure.png"))
                except Exception:
                    pass
        finally:
            fault["catalogStatus"] = 0
            if browser:
                try:
                    browser.run("close")
                except Exception:
                    browser._stop()
            Fixture.tearDownClass()
    write_report(output, report)
    return report


def verify_unavailable(browser, seal, pdf, report, fault, output):
    row = {"device": "desktop", "checks": {}}
    report["unavailable"] = row
    auth = isolated_browser_session(Fixture, "staff", entity_id="E1")
    open_editor(browser, auth, "unavailable", 1440, 1000)
    upload_pdf(browser, pdf, "unavailable")
    report["stage"] = "unavailable:catalog_error"
    before = browser.evaluate(ELEMENT_SNAPSHOT)
    fault["catalogStatus"] = 503
    browser.click_visible("#headerRefreshBtn")
    browser.until("uploadedSealCatalogState.status==='error'&&!uploadedSealEditorRuntime.sealOptionsLoading", timeout=40)
    check(row, "catalogFailureDisablesBothTools", browser.evaluate("document.querySelector('[data-editor-tool=seal]').disabled&&document.querySelector('#uploadedEditorSeamToggleBtn').disabled"))
    check(row, "catalogFailureKeepsEditorAndExplainsRecovery", browser.evaluate("uploadedSealEditorState.pages.length===7&&document.querySelector('#uploadedSealPickerStatus').textContent.includes('更新失敗')") and browser.evaluate(ELEMENT_SNAPSHOT) == before)
    capture(browser, output, "desktop", "catalog-failure", "#uploadedSealPresets", row)
    fault["catalogStatus"] = 0
    browser.click_visible("#headerRefreshBtn")
    browser.until("uploadedSealCatalogState.status==='ready'&&!uploadedSealEditorRuntime.sealOptionsLoading", timeout=40)
    check(row, "catalogRetryRestoresSameCompanyAvailability", browser.evaluate("!!selectedUploadedSeal()&&!!selectedUploadedSeamSeal()"))
    report["stage"] = "unavailable:missing_seal"
    with backend.connect() as conn:
        conn.execute("UPDATE company_seals SET is_active=0 WHERE company_id='CO-001'")
        conn.commit()
    browser.click_visible("#headerRefreshBtn")
    browser.until("uploadedSealCatalogState.status==='ready'&&!uploadedSealEditorRuntime.sealOptionsLoading&&!uploadedSealCompanyRecords().length", timeout=40)
    check(row, "missingSealCannotBeSelected", browser.evaluate("selectedUploadedSeal()===null&&selectedUploadedSeamSeal()===null&&document.querySelector('#uploadedSealCategorySelect').disabled&&document.querySelector('#uploadedEditorSeamSealSelect').disabled"))
    browser.click_visible('[data-editor-tool="seal"]')
    browser.click_visible("#uploadedEditorSeamToggleBtn")
    check(row, "missingSealToolbarNeverCreatesFallbackStamp", browser.evaluate(ELEMENT_SNAPSHOT) == before)
    check(row, "missingSealHasPersistentExplanation", browser.evaluate("document.querySelector('#uploadedSealPickerStatus').textContent.includes('尚無')&&document.querySelector('#uploadedSeamPresetStatus').textContent.includes('尚無')"))
    manual_save(browser, "uploadedEditorSaveDraftBtn")
    check(row, "missingSealStillAllowsDraftSave", browser.evaluate("document.querySelector('#uploadedEditorSaveStatus').textContent==='草稿已暫存'"))
    capture(browser, output, "desktop", "missing-seals", "#uploadedSealPresets", row)
    row["passed"] = True


def write_report(output: Path, report: dict) -> None:
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps({"passed": result.get("passed", False), "stage": result["stage"], "error": result.get("error")}, ensure_ascii=False))
    raise SystemExit(0 if result.get("passed") else 1)
