"""Desktop/mobile compose resilience, real localhost API, synthetic identities only."""
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
import backend
from tools.six_role_browser_acceptance import Browser, TELEMETRY, AUDIT_JS, require_local_origin
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    fixture = FiveAccountHttpAcceptanceTest
    original = QuietAcceptanceHandler.send_head
    def instrumented(handler):
        if urlparse(handler.path).path in {"/", "/index.html"}:
            data = (ROOT / "index.html").read_text().replace("<head>", "<head>" + TELEMETRY, 1).encode()
            handler.send_response(200); handler.send_header("Content-Type", "text/html; charset=utf-8"); handler.send_header("Content-Length", str(len(data))); handler.end_headers()
            return io.BytesIO(data)
        return original(handler)
    report = {"scope": "isolated_synthetic_local_no_submission", "rows": []}
    with mock.patch.object(QuietAcceptanceHandler, "send_head", instrumented):
        fixture.setUpClass()
        require_local_origin(fixture.origin)
        config = Path(fixture.tmp.name) / "browser.json"
        config.write_text(json.dumps({"allowedDomains": ["127.0.0.1", "fonts.googleapis.com", "fonts.gstatic.com"], "headed": False}))
        browser = Browser(config, session="compose-resilience", namespace="compose-sep11")
        try:
            for role in ("staff", "ceo"):
                auth = isolated_browser_session(fixture, role)
                for device, size in (("desktop", (1440, 1000)), ("mobile", (390, 844))):
                    browser.run("set", "viewport", *map(str, size))
                    browser.run("open", fixture.origin + "/assets/favicon-32.png")
                    browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                    browser.run("open", fixture.origin + f"/?fixture={time.monotonic_ns()}#compose")
                    browser.until("window.__fixtureTiming?.appInteractiveMs&&document.querySelector('.view.active')?.id==='compose'&&document.querySelector('#composeApprovalCategorySelect').options.length>1")
                    browser.run("snapshot", "-i")
                    browser.run("screenshot", str(output / f"{role}-{device}-initial.png"))
                    if not browser.evaluate("document.body.innerText.trim().length>0&&!document.querySelector('[data-nextjs-dialog],.vite-error-overlay')"):
                        raise AssertionError("initial_browser_verification_failed")
                    row = {"role": role, "device": device, "checks": {}}
                    checks = row["checks"]
                    browser.run("fill", "#documentPurpose", "去識別化測試，申請更新公文資料。")
                    browser.until("composeSaveState.title==='私人雲端草稿已保存'&&!composeCloudOperation")
                    cloud_id = browser.evaluate("composeCloudDraftId")
                    with backend.connect() as conn:
                        saved = conn.execute("SELECT revision,snapshot_json FROM official_document_compose_drafts WHERE id=?", (cloud_id,)).fetchone()
                        checks["incompleteSnapshotPersisted"] = bool(saved and "去識別化測試" in saved["snapshot_json"])
                    browser.evaluate("window.__fixtureFetch=window.fetch;window.fetch=(url,opts)=>String(url).includes('/api/ai/compose')?new Promise(resolve=>{window.__resolveFixtureAi=()=>resolve(new Response(JSON.stringify({subject:'有關隔離測試一案，請查照。',body:'一、本函僅供測試。',usedOpenAI:false}),{status:200,headers:{'Content-Type':'application/json'}}))}):window.__fixtureFetch(url,opts);true")
                    browser.click_visible("#generateFromPurposeBtn")
                    browser.run("fill", "#subject", "人工保留的主旨")
                    browser.evaluate("window.__resolveFixtureAi();true")
                    browser.until("!!composeAiSuggestion&&!document.querySelector('#composeAiSuggestion').hidden")
                    checks["delayedAiPreservesManualText"] = browser.evaluate("document.querySelector('#subject').value==='人工保留的主旨'")
                    browser.run("screenshot", str(output / f"{role}-{device}-ai-suggestion.png"))
                    browser.click_visible("#composeAiApplyBtn")
                    checks["explicitAiApply"] = browser.evaluate("document.querySelector('#subject').value==='有關隔離測試一案，請查照。'")
                    browser.click_visible("#composeAiUndoBtn")
                    checks["aiUndoRestoresManualText"] = browser.evaluate("document.querySelector('#subject').value==='人工保留的主旨'")
                    browser.evaluate("window.fetch=window.__fixtureFetch;true")
                    category = browser.evaluate("[...document.querySelector('#composeApprovalCategorySelect').options].find(e=>e.textContent.includes('合作意向書')).value")
                    browser.run("select", "#composeApprovalCategorySelect", category)
                    browser.run("select", "#composeOutputMode", "electronic")
                    for name, value in {"recipient": "隔離受文機關", "contactOwner": "隔離承辦人", "contactAddress": "測試路一號", "contactEmail": "test@example.test", "bodyText": "一、本文件僅供本地隔離測試。"}.items():
                        browser.run("fill", "#"+name, value)
                    # Select real synthetic PDF attachments and fail only the second request.
                    first = output / f"fixture-{role}-{device}-a.pdf"
                    second = output / f"fixture-{role}-{device}-b.pdf"
                    first.write_bytes(fixture._make_attachment_pdf(1)); second.write_bytes(fixture._make_attachment_pdf(2))
                    browser.run("upload", "#attachments", str(first), str(second))
                    browser.evaluate("window.__uploadNames=[];window.__failSecond=true;window.fetch=async(url,opts)=>{if(/\\/official-documents\\/[^/]+\\/files$/.test(String(url))&&opts?.method==='POST'){const b=JSON.parse(opts.body);window.__uploadNames.push(b.file_name);if(b.file_name.endsWith('-b.pdf')&&window.__failSecond)return new Response(JSON.stringify({detail:'fixture_attachment_offline'}),{status:503,headers:{'Content-Type':'application/json'}})}return window.__fixtureFetch(url,opts)};true")
                    browser.click_visible("#saveDispatchDraftBtn")
                    browser.until("!composeSaveInFlight&&composeSaveState.tone==='error'")
                    browser.run("screenshot", str(output / f"{role}-{device}-attachment-retry.png"))
                    browser.evaluate("window.__failSecond=false;true")
                    browser.click_visible("#saveDispatchDraftBtn")
                    browser.until("!composeSaveInFlight&&composeSaveState.tone==='saved'&&!!currentComposeDraftId")
                    checks["onlyFailedAttachmentRetried"] = browser.evaluate("window.__uploadNames.length===3&&window.__uploadNames[1]===window.__uploadNames[2]&&window.__uploadNames[0]!==window.__uploadNames[2]")
                    doc_id = browser.evaluate("dispatchDocs.find(item=>item.id===currentComposeDraftId).officialDocumentId")
                    with backend.connect() as conn:
                        checks["twoAttachmentsNoDuplicate"] = conn.execute("SELECT count(*) FROM official_document_files WHERE document_id=? AND file_type='attachment'", (doc_id,)).fetchone()[0] == 2
                        checks["notSubmitted"] = conn.execute("SELECT current_status FROM official_documents WHERE id=?", (doc_id,)).fetchone()[0] == "draft"
                    browser.evaluate("window.fetch=window.__fixtureFetch;true")
                    browser.evaluate("void refreshComposeCloudDrafts();document.querySelector('.compose-cloud-drafts').open=true;true")
                    browser.until("document.querySelector('#composeCloudDraftSelect').options.length>1")
                    browser.evaluate("document.querySelector('.compose-cloud-drafts').scrollIntoView({block:'center',behavior:'instant'});true")
                    browser.run("screenshot", str(output / f"{role}-{device}-cloud-recovery.png"))
                    # Explicit recovery simulates a device without the local
                    # case cache. Its pending local FileList must not follow.
                    browser.evaluate("void(async()=>{await saveComposeCloudDraft();await refreshComposeCloudDrafts();window.__cloudLoadReady=true})();true")
                    browser.until("window.__cloudLoadReady&&!composeCloudOperation")
                    browser.run("select", "#composeCloudDraftSelect", cloud_id)
                    browser.run("upload", "#attachments", str(first))
                    browser.evaluate("window.__originalConfirm=window.confirm;window.confirm=()=>true;const i=dispatchDocs.findIndex(item=>item.officialDocumentId===" + json.dumps(doc_id) + ");if(i>=0)dispatchDocs.splice(i,1);true")
                    browser.click_visible("#composeCloudLoadBtn")
                    browser.until("currentComposeDraftId.startsWith('COMPOSE-RESTORED-')")
                    checks["explicitCloudRecoveryRestoresCaseAndVersion"] = browser.evaluate("document.querySelector('#subject').value==='人工保留的主旨'&&dispatchDocs.find(x=>x.id===currentComposeDraftId)?.officialDocumentId===" + json.dumps(doc_id) + "&&Number.isInteger(composeOfficialContentRevision)")
                    checks["cloudRecoveryDropsPreviousFileSelection"] = browser.evaluate("document.querySelector('#attachments').files.length===0")
                    browser.evaluate("window.confirm=window.__originalConfirm;true")
                    # Simulate device B editing the same cloud snapshot through the real API.
                    browser.evaluate("void(async()=>{await saveComposeCloudDraft();const rows=await backendRequest('/compose-drafts');const row=rows.find(x=>x.id===composeCloudDraftId);await backendRequest('/compose-drafts/'+row.id,{method:'PUT',body:JSON.stringify({expected_revision:row.revision,snapshot:{...row.snapshot,values:{...row.snapshot.values,'#subject':'另一裝置的文字'}}})});document.querySelector('#subject').value='本機需保留文字';markDraftDirty();await saveComposeCloudDraft();window.__conflictReady=true})();true")
                    browser.until("window.__conflictReady&&composeCloudConflict")
                    checks["cloudConflictVisibleAndPreservesText"] = browser.evaluate("document.querySelector('#subject').value==='本機需保留文字'&&!document.querySelector('#composeKeepNewDraftBtn').hidden")
                    browser.run("screenshot", str(output / f"{role}-{device}-conflict.png"))
                    browser.click_visible("#composeKeepNewDraftBtn")
                    browser.until("!composeCloudOperation&&composeSaveState.title==='私人雲端草稿已保存'&&!composeCloudConflict")
                    checks["conflictForkGetsNewId"] = browser.evaluate("composeCloudDraftId!=" + json.dumps(cloud_id) + "&&document.querySelector('#subject').value==='本機需保留文字'&&!currentComposeDraftId")
                    browser.run("upload", "#attachments", str(first))
                    browser.evaluate("window.__originalConfirm=window.confirm;window.confirm=()=>true;void(async()=>{const detail=await backendRequest('/official-documents/" + doc_id + "');beginComposeOfficialCorrection(detail);window.__correctionLoadReady=true})();true")
                    browser.until("window.__correctionLoadReady")
                    checks["officialCorrectionDropsOtherDraftFileSelection"] = browser.evaluate("document.querySelector('#attachments').files.length===0&&dispatchDocs.find(x=>x.id===currentComposeDraftId)?.officialDocumentId===" + json.dumps(doc_id))
                    browser.evaluate("window.confirm=window.__originalConfirm;true")
                    row["layout"] = browser.evaluate(AUDIT_JS)
                    checks["noOverflow"] = not row["layout"]["overflow"]
                    checks["noWindowErrors"] = not row["layout"]["errors"]
                    report["rows"].append(row)
                    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
                    print(json.dumps({"role": role, "device": device, "checks": checks}), flush=True)
        except Exception:
            browser.run("screenshot", str(output / "failure.png"))
            report["failure"] = browser.evaluate("({title:composeSaveState.title,detail:composeSaveState.detail,cloudBusy:!!composeCloudOperation,saveBusy:!!composeSaveInFlight,aiBusy:!!composeAiOperation,errors:window.__fixtureErrors})")
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            raise
        finally:
            try: browser.run("close")
            finally: fixture.tearDownClass()
    report["passed"] = all(all(row["checks"].values()) for row in report["rows"])
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if run(args.output)["passed"] else 1)
