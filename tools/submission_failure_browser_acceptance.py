"""Local browser proof for safe failed-submit feedback and draft retention.

PDF upload/edit/preflight use the real isolated HTTP backend. Only the final
submit response is deliberately fault-injected, never sent to production.
Viewport simulations do not establish physical-device or human SSO acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as Fixture, QuietAcceptanceHandler
from tests.support.five_account_browser_fixture import isolated_browser_session
from tools.ux_complete_browser_acceptance import BRIDGE, TELEMETRY, require_local_origin
import tools.backup_drill_browser_acceptance as transport

DEVICES = (("desktop",1440,1000),("phone",390,844))
FAULTS = (
    ("validation_failed",500,"official_submission_validation_failed","not_submitted","尚未送出","ERR-111111111111111111111111"),
    ("outcome_unknown",503,"official_document_submit_commit_state_unknown","unknown","尚未確認送簽結果","ERR-222222222222222222222222"),
)


def run(output: Path):
    output=output.resolve();output.mkdir(parents=True,exist_ok=True)
    report={"scope":"loopback_synthetic_browser_with_submit_fault_injection","hostedVerified":False,
        "humanSSOVerified":False,"physicalDeviceVerified":False,"governmentExchange":"DISABLED",
        "sourceAppSha256":hashlib.sha256((ROOT/"app.js").read_bytes()).hexdigest(),"cases":[]}
    original=QuietAcceptanceHandler.send_head
    html=(ROOT/"index.html").read_bytes().replace(b"<head>",b"<head>"+TELEMETRY.encode(),1)
    def head(handler):
        if urlparse(handler.path).path not in {"/","/index.html"}:return original(handler)
        handler.send_response(200);handler.send_header("Content-Type","text/html; charset=utf-8")
        handler.send_header("Content-Length",str(len(html)));handler.end_headers();return io.BytesIO(html)
    browser=None
    executable=Path.home()/"Library/Caches/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell"
    with mock.patch.object(QuietAcceptanceHandler,"send_head",head),mock.patch.object(transport,"PLAYWRIGHT_BRIDGE",BRIDGE),mock.patch.dict(os.environ,{"EDOC_TEST_BROWSER_PATH":str(executable)}):
        Fixture.setUpClass();require_local_origin(Fixture.origin)
        try:
            auth=isolated_browser_session(Fixture,"staff",entity_id="E1")
            custodian=isolated_browser_session(Fixture,"ceo",entity_id="E1")
            Fixture._expect_json("PATCH","/api/companies/CO-001/seal-policy",200,token=custodian["token"],json_body={"owner_kind":"company"})
            browser=transport.LocalPlaywrightBrowser(Fixture.origin)
            for device,width,height in DEVICES:
                for name,status,code,submission_status,message,error_id in FAULTS:
                    label=device+"-"+name;row={"case":label,"passed":False}
                    try:
                        print(json.dumps({"case":label,"stage":"open"}),flush=True)
                        browser.run("open",Fixture.origin+"/assets/favicon-32.png")
                        browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session',"+json.dumps(json.dumps(auth))+");true")
                        browser.run("set","viewport",str(width),str(height))
                        browser.run("open",Fixture.origin+f"/?submission-fault={time.monotonic_ns()}#electronicSeal")
                        browser.until("typeof uploadedSealApplicationRuntime==='object'&&!uploadedSealEditorRuntime.directoryLoading&&document.querySelector('#uploadedSealApprovalCategorySelect').options.length>1",timeout=40)
                        category=browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(e=>e.textContent.includes('服務委託合約')).value")
                        browser.run("select","#uploadedSealApprovalCategorySelect",category)
                        title="合成送簽保留測試 "+label;text="合成已編輯文字 "+label
                        browser.run("fill","#uploadedSealTitle",title)
                        browser.run("fill","#uploadedSealReason","隔離驗收，沒有真實個資。")
                        path=output/f"synthetic-{label}.pdf"
                        writer=canvas.Canvas(str(path),pagesize=A4)
                        for page in range(2):writer.drawString(60,780,f"SYNTHETIC SUBMIT FAILURE {label} page {page+1}");writer.showPage()
                        writer.save()
                        browser.run("upload","#uploadedSealPdfInput",str(path))
                        browser.until("uploadedSealEditorState.pages.length===2&&!uploadedSealEditorRuntime.uploading&&!uploadedSealEditorRuntime.finalizingAsset&&!uploadedSealEditorRuntime.saving&&!uploadedSealApplicationRuntime.promise",timeout=50)
                        browser.add_pdf_text(text)
                        browser.click_visible('[data-editor-tool="seal"]');browser.click_visible("#addSelectedStampBtn")
                        browser.until("uploadedSealEditorState.elements.some(e=>e.kind==='seal')")
                        browser.evaluate("window.__qaSaved=false;void saveUploadedEditorState({immediate:true}).then(()=>syncUploadedSealApplicationDraft()).then(()=>window.__qaSaved=true);true")
                        browser.until("window.__qaSaved&&!uploadedSealEditorRuntime.saving&&!uploadedSealApplicationHasUnsavedChanges()",timeout=40)
                        document_id=browser.evaluate("uploadedSealEditorRuntime.documentId")
                        before=Fixture._expect_json("GET",f"/api/official-documents/{document_id}/editor-state",200,token=auth["token"])["state"]
                        print(json.dumps({"case":label,"stage":"preflight"}),flush=True)
                        browser.click_visible("#submitUploadedSealBtn")
                        browser.until("uploadedSealEditorRuntime.reviewMode==='prepared'&&!uploadedSealApplicationRuntime.submissionBusy",timeout=45)
                        row["realPreparedPreviewReady"]=browser.evaluate("uploadedEditorSubmissionPreviewIsCurrent()&&Boolean(uploadedSealEditorRuntime.preparedSha256)&&document.querySelector('#uploadedPdfCanvas').width>0")
                        # Preflight can persist a new revision; compare with
                        # the exact saved version immediately before submit.
                        before=Fixture._expect_json("GET",f"/api/official-documents/{document_id}/editor-state",200,token=auth["token"])["state"]
                        failure={"error":code,"detail":code,"errorId":error_id,"retryable":False,"submissionStatus":submission_status}
                        browser.evaluate("window.__qaSubmitRequests=[];window.__qaFetch=window.fetch;window.fetch=async(...args)=>{const u=new URL(args[0]?.url||String(args[0]),location.href);const method=String(args[1]?.method||args[0]?.method||'GET').toUpperCase();if(method==='POST'&&u.pathname==="+json.dumps(f"/api/official-documents/{document_id}/submit")+"){window.__qaSubmitRequests.push({method,path:u.pathname});return new Response("+json.dumps(json.dumps(failure))+",{status:"+str(status)+",headers:{'Content-Type':'application/json'}})}return window.__qaFetch(...args)};true")
                        browser.click_visible("#submitUploadedSealBtn")
                        browser.until("!document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')")
                        browser.click_visible("#workspaceTypedConfirmSubmitBtn")
                        browser.until("window.__qaSubmitRequests.length===1&&!uploadedSealApplicationRuntime.submissionBusy",timeout=20)
                        # Leave enough time for the toast to disappear and any
                        # accidental retry to occur; evidence is persistent UI.
                        time.sleep(4.5)
                        displayed=browser.evaluate("document.querySelector('#uploadedEditorPreflightStatus').textContent")
                        row["persistentFailureReasonAndId"]=message in displayed and error_id in displayed
                        row["noMisleadingTryAgain"]= "稍後再試" not in displayed
                        row["exactlyOneSubmit"]=browser.evaluate("window.__qaSubmitRequests.length===1")
                        row["notFalselyLocked"]=browser.evaluate("!uploadedSealEditorRuntime.locked")
                        after=Fixture._expect_json("GET",f"/api/official-documents/{document_id}/editor-state",200,token=auth["token"])["state"]
                        detail=Fixture._expect_json("GET",f"/api/official-documents/{document_id}",200,token=auth["token"])
                        row["draftTextAndPdfPreserved"]=detail["current_status"]=="draft" and detail["title"]==title and before==after and any(e.get("properties",{}).get("text")==text for e in after["elements"])
                        browser.evaluate("document.querySelector('#uploadedEditorPreflightStatus').scrollIntoView({block:'center'});true")
                        browser.run("screenshot",str(output/f"{label}-failure.png"))
                        browser.click_visible("#uploadedEditorBackToEditBtn")
                        browser.until("uploadedSealEditorRuntime.reviewMode==='edited'")
                        browser.add_pdf_text("合成失敗後繼續修改 "+label)
                        browser.evaluate("window.__qaResaved=false;void saveUploadedEditorState({immediate:true}).then(()=>window.__qaResaved=true);true")
                        browser.until("window.__qaResaved&&!uploadedSealEditorRuntime.saving")
                        final=Fixture._expect_json("GET",f"/api/official-documents/{document_id}/editor-state",200,token=auth["token"])["state"]
                        row["returnToEditAndPersist"]=any(e.get("properties",{}).get("text")=="合成失敗後繼續修改 "+label for e in final["elements"])
                        row["sourcePreserved"]=final["sourceFiles"]==before["sourceFiles"] and final["pages"]==before["pages"]
                        row["noHorizontalOverflow"]=browser.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                        row["noUnhandledErrors"]=browser.evaluate("window.__fixtureErrors.length===0")
                        browser.run("screenshot",str(output/f"{label}-editable.png"))
                        row["passed"]=all(value is True for key,value in row.items() if key not in {"case","passed"})
                        row["failureText"]=displayed
                    except Exception as error:
                        row["errorCode"]=type(error).__name__;row["lastCommand"]=browser.last_command
                        try:row["runtime"]=browser.evaluate("({errors:window.__fixtureErrors,preflight:document.querySelector('#uploadedEditorPreflightStatus')?.textContent,busy:uploadedSealApplicationRuntime.submissionBusy,reviewMode:uploadedSealEditorRuntime.reviewMode,saveStatus:uploadedSealEditorRuntime.saveStatus,applicationError:uploadedSealApplicationRuntime.error,requests:window.__qaSubmitRequests})")
                        except Exception:pass
                        try:browser.run("screenshot",str(output/f"{label}-failed.png"))
                        except Exception:pass
                    report["cases"].append(row)
                    (output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
                    print(json.dumps(row,ensure_ascii=False),flush=True)
                    if not row["passed"]:break
                if not report["cases"][-1]["passed"]:break
        finally:
            try:
                if browser:
                    try:browser.run("close")
                    except Exception:browser._stop()
            finally:Fixture.tearDownClass()
    report["sourceAppSha256After"]=hashlib.sha256((ROOT/"app.js").read_bytes()).hexdigest()
    report["passed"]=len(report["cases"])==len(DEVICES)*len(FAULTS) and all(row["passed"] for row in report["cases"]) and report["sourceAppSha256"]==report["sourceAppSha256After"]
    (output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2));return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();raise SystemExit(0 if run(args.output)["passed"] else 1)
