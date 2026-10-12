"""Local synthetic browser acceptance for editable upload application context.

Real loopback API, actual PDF editing and server readback; no production or
government calls. Desktop/tablet/phone are viewport simulations, not devices.
"""
from __future__ import annotations
import argparse
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as Fixture, QuietAcceptanceHandler
from tests.support.five_account_browser_fixture import isolated_browser_session
from tools.ux_complete_browser_acceptance import BRIDGE, TRANSPORT, TELEMETRY, require_local_origin
import tools.backup_drill_browser_acceptance as transport

FIELDS = ['uploadedSealCompany', 'uploadedSealDepartment', 'uploadedSealApprovalCategorySelect', 'uploadedSealTitle', 'uploadedSealReason']
DEVICES = (('desktop',1440,1000),('tablet',900,1100),('phone',390,844))


def run(output: Path):
    output = output.resolve(); output.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256((ROOT/'app.js').read_bytes()).hexdigest()
    report = {'scope':'loopback_synthetic_browser','hostedVerified':False,'physicalDeviceVerified':False,
              'humanSSOVerified':False,'governmentExchange':'DISABLED','sourceAppSha256':source_hash,'cases':[]}
    original = QuietAcceptanceHandler.send_head
    html = (ROOT/'index.html').read_bytes().replace(b'<head>', b'<head>'+TELEMETRY.encode(),1)
    def head(handler):
        if urlparse(handler.path).path not in {'/','/index.html'}: return original(handler)
        handler.send_response(200); handler.send_header('Content-Type','text/html; charset=utf-8')
        handler.send_header('Content-Length',str(len(html))); handler.end_headers(); return io.BytesIO(html)
    browser = None
    executable = Path.home()/'Library/Caches/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell'
    with mock.patch.object(QuietAcceptanceHandler,'send_head',head), mock.patch.object(transport,'PLAYWRIGHT_BRIDGE',BRIDGE), mock.patch.dict(os.environ,{'EDOC_TEST_BROWSER_PATH':str(executable)}):
        Fixture.setUpClass(); require_local_origin(Fixture.origin)
        try:
            custodian = isolated_browser_session(Fixture,'ceo',entity_id='E1')
            auth = isolated_browser_session(Fixture,'staff',entity_id='E1')
            # Explicit same-tenant test directory: permission is still checked
            # by the shipping API. No impersonation or production records.
            with backend.connect() as conn:
                tenant = auth['user']['finance_tenant_id']
                conn.execute("UPDATE companies SET finance_tenant_id=?,finance_entity_id='E2' WHERE id='CO-002'",(tenant,))
                company_name = conn.execute("SELECT name FROM companies WHERE id='CO-002'").fetchone()[0]
                conn.execute("INSERT INTO department_registry(id,company_name,name,manager_role,status,created_at,updated_at) VALUES ('QA-ALT',?,'合成同租戶部門','隔離測試主管','active',?,?)",(company_name,backend.now(),backend.now()))
                conn.commit()
            for company in ('CO-001','CO-002'):
                Fixture._expect_json('PATCH',f'/api/companies/{company}/seal-policy',200,token=custodian['token'],json_body={'owner_kind':'company'})
            browser = transport.LocalPlaywrightBrowser(Fixture.origin)
            for device,width,height in DEVICES:
                row={'case':device,'passed':False}; report['stage']=device
                try:
                    browser.run('open',Fixture.origin+'/assets/favicon-32.png')
                    browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session',"+json.dumps(json.dumps(auth))+");true")
                    browser.run('set','viewport',str(width),str(height));browser.run('open',Fixture.origin+f'/?application={time.monotonic_ns()}#electronicSeal')
                    browser.until("typeof uploadedSealApplicationRuntime==='object'&&!uploadedSealEditorRuntime.directoryLoading&&document.querySelector('#uploadedSealApprovalCategorySelect').options.length>1",timeout=40)
                    browser.evaluate('window.__raceRealFetch=window.fetch;true');browser.evaluate(TRANSPORT)
                    category=browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(e=>e.textContent.includes('服務委託合約')).value")
                    browser.run('select','#uploadedSealApprovalCategorySelect',category)
                    browser.run('fill','#uploadedSealTitle','合成原始申請 '+device);browser.run('fill','#uploadedSealReason','合成測試用途，無個資。')
                    path=output/f'synthetic-{device}.pdf';writer=canvas.Canvas(str(path),pagesize=A4)
                    for page in range(2):writer.drawString(60,780,f'SYNTHETIC APPLICATION {device} page {page+1}');writer.showPage()
                    writer.save()
                    browser.evaluate("window.__raceRules.push({key:'transfer',method:'PUT',pattern:'/editor-uploads/[^/]+/content$',when:'before'});true")
                    browser.run('upload','#uploadedSealPdfInput',str(path))
                    browser.until("!!window.__raceHolds.transfer&&uploadedSealEditorState.pages.length===2&&!uploadedSealEditorRuntime.uploading&&uploadedSealEditorRuntime.finalizingAsset",timeout=40)
                    row['fieldsEditableDuringTransfer']=browser.evaluate('['+','.join(json.dumps('#'+name) for name in FIELDS)+'].every(s=>!document.querySelector(s).disabled)')
                    browser.run('fill','#uploadedSealTitle','合成最後申請 '+device)
                    reason='合成最後用途 '+device;browser.run('fill','#uploadedSealReason',reason)
                    browser.add_pdf_text('合成上傳中編輯 '+device)
                    # Wait beyond the real debounce: no premature metadata PATCH.
                    browser.evaluate('window.__queueResult=null;void syncUploadedSealApplicationDraft().then(()=>window.__queueResult=true);true')
                    browser.until('window.__queueResult===true')
                    row['queuedZeroMetadataWrites']=browser.evaluate(r"uploadedSealApplicationRuntime.queued&&!window.__raceRequests.some(r=>r.method==='PATCH'&&/^\/api\/official-documents\/[^/]+$/.test(r.path))")
                    browser.run('screenshot',str(output/f'{device}-held-editable.png'))
                    browser.evaluate('window.__raceHolds.transfer.release();true')
                    browser.until("!uploadedSealEditorRuntime.finalizingAsset&&!uploadedSealEditorRuntime.saving&&!uploadedSealApplicationRuntime.promise&&!uploadedSealApplicationHasUnsavedChanges()",timeout=50)
                    doc_id=browser.evaluate('uploadedSealEditorRuntime.documentId')
                    detail=Fixture._expect_json('GET','/api/official-documents/'+doc_id,200,token=auth['token'])
                    state=Fixture._expect_json('GET','/api/official-documents/'+doc_id+'/editor-state',200,token=auth['token'])['state']
                    row['latestMetadataReadback']=detail['title']=='合成最後申請 '+device and detail['request_reason']==reason
                    row['actualPdfTextReadback']=any(e.get('properties',{}).get('text')=='合成上傳中編輯 '+device for e in state['elements'])
                    row['categoryEditableAfterSave']=browser.evaluate("!document.querySelector('#uploadedSealApprovalCategorySelect').disabled")
                    row['sourceHashPreserved']=state['sourceFiles'][0]['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
                    # Real seal placement, then cancel a context switch.
                    browser.click_visible('[data-editor-tool="seal"]');browser.click_visible('#addSelectedStampBtn')
                    browser.until('uploadedSealEditorState.elements.some(e=>e.kind===\'seal\')')
                    browser.evaluate('window.__pdfSaveDone=false;void saveUploadedEditorState({immediate:true}).then(()=>window.__pdfSaveDone=true);true');browser.until('window.__pdfSaveDone')
                    before=Fixture._expect_json('GET','/api/official-documents/'+doc_id+'/editor-state',200,token=auth['token'])['state']
                    browser.run('select','#uploadedSealCompany','CO-002')
                    browser.until("!document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')")
                    browser.click_visible('#workspaceTypedConfirmCancelBtn')
                    browser.until("document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')")
                    row['cancelCompanyKeepsPdfAndSelection']=browser.evaluate("document.querySelector('#uploadedSealCompany').value==='CO-001'&&uploadedSealEditorRuntime.documentId==="+json.dumps(doc_id)) and Fixture._expect_json('GET','/api/official-documents/'+doc_id+'/editor-state',200,token=auth['token'])['state']==before
                    browser.run('select','#uploadedSealCompany','CO-002');browser.until("!document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')")
                    browser.click_visible('#workspaceTypedConfirmSubmitBtn')
                    browser.until("document.querySelector('#uploadedSealDepartment').options.length>1&&!uploadedSealEditorRuntime.sealOptionsLoading")
                    department=browser.evaluate("[...document.querySelector('#uploadedSealDepartment').options].find(e=>e.dataset.financeUnitCode==='QA-ALT').value")
                    browser.run('select','#uploadedSealDepartment',department)
                    browser.evaluate('window.__metadataDone=false;void syncUploadedSealApplicationDraft().then(()=>window.__metadataDone=true);true')
                    browser.until('window.__metadataDone&&!uploadedSealApplicationRuntime.promise&&!uploadedSealApplicationHasUnsavedChanges()',timeout=40)
                    changed=Fixture._expect_json('GET','/api/official-documents/'+doc_id,200,token=auth['token'])
                    changed_state=Fixture._expect_json('GET','/api/official-documents/'+doc_id+'/editor-state',200,token=auth['token'])['state']
                    row['sameIdCompanyAndDepartmentReadback']=changed['id']==doc_id and changed['company_id']=='CO-002' and changed['applicant_department_id']=='QA-ALT'
                    row['companyChangeKeepsSourcePagesText']=changed_state['sourceFiles']==before['sourceFiles'] and changed_state['pages']==before['pages'] and any(e.get('properties',{}).get('text')=='合成上傳中編輯 '+device for e in changed_state['elements'])
                    row['oldSealsRemovedUndoCleared']=not any(e['kind']=='seal' for e in changed_state['elements']) and browser.evaluate('uploadedSealEditorRuntime.undoStack.length===0&&uploadedSealEditorRuntime.redoStack.length===0')
                    # Last-wins metadata while a real committed PATCH response is held.
                    browser.evaluate("window.__raceRules.push({key:'metadata',method:'PATCH',path:'/api/official-documents/"+doc_id+"',when:'after'});true")
                    browser.run('fill','#uploadedSealReason','合成第一版本')
                    browser.evaluate('window.__lastSave=false;void syncUploadedSealApplicationDraft().then(()=>window.__lastSave=true);true')
                    browser.until('!!window.__raceHolds.metadata')
                    browser.run('fill','#uploadedSealReason','合成最後版本')
                    browser.evaluate('window.__raceHolds.metadata.release();true');browser.until('window.__lastSave&&!uploadedSealApplicationRuntime.promise&&!uploadedSealApplicationHasUnsavedChanges()',timeout=40)
                    row['lastWinsReadback']=Fixture._expect_json('GET','/api/official-documents/'+doc_id,200,token=auth['token'])['request_reason']=='合成最後版本'
                    # Chinese IME is retained, not saved before compositionend.
                    browser.evaluate("window.__imeRequests=window.__raceRequests.length;const e=document.querySelector('#uploadedSealTitle');e.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));e.value='合成中文輸入';e.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true}));true")
                    browser.evaluate('window.__imeBlocked=false;void syncUploadedSealApplicationDraft().catch(()=>window.__imeBlocked=true);true');browser.until('window.__imeBlocked')
                    row['imeNoPartialWrite']=browser.evaluate("!window.__raceRequests.slice(window.__imeRequests).some(r=>r.method==='PATCH')")
                    browser.evaluate("document.querySelector('#uploadedSealTitle').dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));true")
                    browser.evaluate('window.__imeSaved=false;void syncUploadedSealApplicationDraft().then(()=>window.__imeSaved=true);true');browser.until('window.__imeSaved')
                    row['imeLatestReadback']=Fixture._expect_json('GET','/api/official-documents/'+doc_id,200,token=auth['token'])['title']=='合成中文輸入'
                    # Final company/route and PDF versions are confirmed after
                    # all edits. No background save is treated as submission.
                    browser.run('select','#uploadedSealCompany','CO-001')
                    browser.until("document.querySelector('#uploadedSealCompany').value==='CO-001'&&!uploadedSealEditorRuntime.sealOptionsLoading")
                    browser.evaluate('window.__finalContext=false;void syncUploadedSealApplicationDraft().then(()=>window.__finalContext=true);true');browser.until('window.__finalContext&&!uploadedSealApplicationHasUnsavedChanges()')
                    browser.click_visible('[data-editor-tool="seal"]');browser.click_visible('#addSelectedStampBtn')
                    browser.evaluate('window.__finalPdf=false;void saveUploadedEditorState({immediate:true}).then(()=>window.__finalPdf=true);true');browser.until('window.__finalPdf&&!uploadedSealEditorRuntime.saving')
                    browser.click_visible('#submitUploadedSealBtn')
                    browser.until("uploadedSealEditorRuntime.reviewMode==='prepared'&&!uploadedSealApplicationRuntime.submissionBusy",timeout=45)
                    row['finalSummaryExactContextAndPdf']=browser.evaluate("document.querySelector('#uploadedEditorSubmissionSummary').textContent.includes(document.querySelector('#uploadedSealCompany').selectedOptions[0].textContent)&&document.querySelector('#uploadedEditorSubmissionSummary').textContent.includes(uploadedSealEditorRuntime.preparedSha256)&&uploadedEditorSubmissionPreviewIsCurrent()")
                    browser.evaluate('window.__submitBefore=window.__raceRequests.length;true');browser.click_visible('#submitUploadedSealBtn')
                    browser.until("!document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')")
                    browser.click_visible('#workspaceTypedConfirmCancelBtn');browser.until('!uploadedSealApplicationRuntime.submissionBusy')
                    row['finalConfirmCancelZeroSubmit']=browser.evaluate("!window.__raceRequests.slice(window.__submitBefore).some(r=>r.method==='POST'&&r.path.endsWith('/submit'))")
                    browser.click_visible('#submitUploadedSealBtn');browser.until("!document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')")
                    browser.click_visible('#workspaceTypedConfirmSubmitBtn');browser.until('uploadedSealEditorRuntime.locked&&!uploadedSealApplicationRuntime.submissionBusy',timeout=45)
                    final_detail=Fixture._expect_json('GET','/api/official-documents/'+doc_id,200,token=auth['token'])
                    row['exactOneSubmitAndFinalContext']=browser.evaluate("window.__raceRequests.slice(window.__submitBefore).filter(r=>r.method==='POST'&&r.path.endsWith('/submit')).length===1") and final_detail['company_id']=='CO-001' and final_detail['title']=='合成中文輸入' and final_detail['request_reason']=='合成最後版本' and final_detail['current_status'].startswith('pending_')
                    row['submittedUiIsReadonlyNotStaleReview']=browser.evaluate("document.querySelector('#submitUploadedSealBtn').disabled&&document.querySelector('#submitUploadedSealBtn').textContent==='已送出簽核'&&document.querySelector('#uploadedEditorPreflightStatus').textContent.includes('文件唯讀')&&!document.querySelector('#uploadedEditorPreflightStatus').textContent.includes('重新產生')")
                    row['noHorizontalOverflow']=browser.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    row['errorsEmpty']=browser.evaluate('window.__fixtureErrors.length===0')
                    browser.run('screenshot',str(output/f'{device}-after.png'))
                    row['passed']=all(value is True for key,value in row.items() if key not in {'case','passed'})
                except Exception as error:
                    row['errorCode']=type(error).__name__;row['lastCommand']=browser.last_command
                    try:row['runtime']=browser.evaluate("({errors:window.__fixtureErrors,company:document.querySelector('#uploadedSealCompany')?.value,department:document.querySelector('#uploadedSealDepartment')?.value,applicationError:uploadedSealApplicationRuntime.error,metadataReadonly:uploadedSealApplicationMetadataReadOnly(),companyReadonly:uploadedSealApplicationCompanyReadOnly(),savedGeneration:uploadedSealEditorRuntime.savedGeneration,dirtyGeneration:uploadedSealEditorRuntime.dirtyGeneration,reviewMode:uploadedSealEditorRuntime.reviewMode,readiness:officialWorkflowReadinessByRoute.get(workflowReadinessCacheKey('uploadedSeal')),preflightStatus:document.querySelector('#uploadedEditorPreflightStatus')?.textContent})")
                    except Exception:pass
                    try:browser.run('screenshot',str(output/f'{device}-failed.png'))
                    except Exception:pass
                report['cases'].append(row);(output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(row,ensure_ascii=False),flush=True)
                if not row['passed']:break
        finally:
            try:
                if browser:
                    try:browser.run('close')
                    except Exception:browser._stop()
            finally:Fixture.tearDownClass()
    report['sourceAppSha256After']=hashlib.sha256((ROOT/'app.js').read_bytes()).hexdigest()
    report['passed']=len(report['cases'])==len(DEVICES) and all(row['passed'] for row in report['cases']) and report['sourceAppSha256']==report['sourceAppSha256After']
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();raise SystemExit(0 if run(args.output)['passed'] else 1)
