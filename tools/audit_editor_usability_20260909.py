"""Deidentified browser-only PDF editor journeys, no production or submission.

Uses a temporary SQLite fixture with scoped local sessions. Authentication is
not under test and tokens are never written to the evidence directory.
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
import backend
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from tools.six_role_browser_acceptance import Browser, AUDIT_JS, TELEMETRY
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler


FORM_JS = """Object.fromEntries(['Applicant','ApprovalCategorySelect','Department','Company','Title','Reason'].map(k=>{let e=document.querySelector('#uploadedSeal'+k);return [k,{value:e.value,disabled:e.disabled,valid:e.checkValidity()}]}))"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/edoc-role-ux-evidence-20260909/editor-before'))
    parser.add_argument('--roles', nargs='+', default=['staff', 'section_chief', 'ceo'])
    parser.add_argument('--devices', nargs='+', default=['desktop', 'mobile'])
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    original_head = QuietAcceptanceHandler.send_head

    def instrument(handler):
        if urlparse(handler.path).path in {'/', '/index.html'}:
            html = (ROOT / 'index.html').read_text().replace('<head>', '<head>' + TELEMETRY, 1)
            data = html.encode()
            handler.send_response(200)
            handler.send_header('Content-Type', 'text/html; charset=utf-8')
            handler.send_header('Content-Length', str(len(data)))
            handler.end_headers()
            return io.BytesIO(data)
        return original_head(handler)

    fixture = FiveAccountHttpAcceptanceTest
    report = {'scope': 'isolated_local_fixture_browser_no_submission', 'realGoogleLoginVerified': False, 'journeys': []}
    with mock.patch.object(QuietAcceptanceHandler, 'send_head', instrument):
        fixture.setUpClass()
        config = Path(fixture.tmp.name) / 'editor-agent-browser.json'
        config.write_text(json.dumps({'allowedDomains': ['127.0.0.1', 'fonts.googleapis.com', 'fonts.gstatic.com'], 'headed': False}))
        browser = Browser(config, session='edoc-editor-ux-20260909', namespace='edoc-editor-ux-isolated')
        try:
            for role in args.roles:
                auth = isolated_browser_session(fixture, role)
                for device in args.devices:
                    result = {'role': role, 'device': device, 'checks': {}}
                    report['journeys'].append(result)
                    prefix = f'{role}-{device}'
                    try:
                        # Only the first role has synthetic test seals; the other
                        # roles must retain full text editing without a current seal.
                        with backend.connect() as conn:
                            conn.execute('UPDATE company_seal_files SET is_current=?', (int(role == args.roles[0]),))
                            conn.commit()
                        browser.run('set', 'offline', 'off')
                        browser.run('open', fixture.origin + '/assets/favicon-32.png')
                        browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                        width, height = (1440, 1000) if device == 'desktop' else (390, 844)
                        browser.run('set', 'viewport', str(width), str(height))
                        browser.run('open', fixture.origin + f'/?editor_audit={time.monotonic_ns()}#electronicSeal')
                        browser.until("window.__fixtureTiming?.appInteractiveMs && document.querySelector('#uploadedSealApprovalCategorySelect')?.options.length>1")
                        browser.run('snapshot', '-i')
                        result['initialForm'] = browser.evaluate(FORM_JS)
                        result['sealNotice'] = browser.evaluate("document.querySelector('#uploadedSealAvailabilityNotice')?.textContent || ''")
                        # Attempting an upload before selecting a category must not lose data.
                        pdf = Path(fixture.tmp.name) / f'{prefix}-synthetic-three-a4.pdf'
                        writer = canvas.Canvas(str(pdf), pagesize=A4)
                        for index, pagesize in enumerate([A4, landscape(A4), A4], 1):
                            writer.setPageSize(pagesize)
                            writer.drawString(50, pagesize[1] - 70, f'ISOLATED PAGE {index} - NO PERSONAL DATA')
                            writer.showPage()
                        writer.save()
                        if role == args.roles[0] and device == 'desktop':
                            browser.run('upload', '#uploadedSealPdfInput', str(pdf))
                            browser.until("!uploadedSealEditorRuntime.uploading")
                            result['emptyFormUpload'] = browser.evaluate("({message:document.querySelector('#uploadedEditorUploadErrorMessage')?.textContent,toast:document.querySelector('#toast')?.textContent,pages:uploadedSealEditorState.pages.length,form:" + FORM_JS + "})")
                        category = browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(e=>e.textContent.includes('合作意向書')).value")
                        browser.run('select', '#uploadedSealApprovalCategorySelect', category)
                        browser.run('fill', '#uploadedSealTitle', f'隔離測試 {prefix} 原主旨')
                        browser.run('fill', '#uploadedSealReason', '隔離測試原原因，不送簽、不寄發。')
                        browser.run('upload', '#uploadedSealPdfInput', str(pdf))
                        browser.until("(uploadedSealEditorState.pages.length===3&&!uploadedSealEditorRuntime.uploading)||(!document.querySelector('#uploadedEditorUploadError').hidden&&!uploadedSealEditorRuntime.uploading)")
                        if not browser.evaluate('uploadedSealEditorState.pages.length===3'):
                            raise RuntimeError('browser_three_a4_upload_failed')
                        browser.until("uploadedSealEditorRuntime.currentViewport?.width>0 && document.querySelector('#uploadedPdfCanvas').width>0")
                        result['checks']['uploadThreeMixedA4'] = True
                        result['pages'] = browser.evaluate('uploadedSealEditorState.pages.map(p=>({id:p.pageId,width:p.widthPt,height:p.heightPt,rotation:p.rotation}))')
                        browser.click_visible('#uploadedPdfEditor [data-editor-tool="text"]')
                        browser.run('fill', '#uploadedSealTextInput', f'隔離編輯測試 {prefix} 第一頁')
                        browser.click_visible('#addUploadedTextBtn')
                        browser.until('uploadedSealEditorState.elements.length===1')
                        first_id = browser.evaluate('uploadedSealEditorState.elements[0].id')
                        result['checks']['textWithoutSealAvailable'] = True
                        browser.click_visible('#uploadedEditorUndoBtn')
                        browser.until('uploadedSealEditorState.elements.length===0')
                        browser.click_visible('#uploadedEditorRedoBtn')
                        browser.until('uploadedSealEditorState.elements.length===1')
                        result['checks']['undoRedo'] = True
                        browser.click_visible('#uploadedPdfNextBtn')
                        browser.until('uploadedSealCurrentPage===2 && uploadedSealEditorRuntime.currentViewport.width>uploadedSealEditorRuntime.currentViewport.height')
                        result['checks']['landscapePageSwitch'] = True
                        browser.click_visible('#uploadedPdfEditor [data-editor-tool="text"]')
                        browser.run('fill', '#uploadedSealTextInput', f'隔離編輯測試 {prefix} 第二頁')
                        browser.click_visible('#addUploadedTextBtn')
                        browser.until('uploadedSealEditorState.elements.length===2')
                        second_id = browser.evaluate('uploadedSealEditorState.elements[1].id')
                        browser.click_visible('[data-editor-summary-delete="' + second_id + '"]')
                        browser.until('uploadedSealEditorState.elements.length===1')
                        browser.click_visible('#uploadedEditorUndoBtn')
                        browser.until('uploadedSealEditorState.elements.length===2')
                        result['checks']['deleteUndo'] = True
                        browser.click_visible('#uploadedEditorModeAdvanced')
                        browser.click_visible('#uploadedEditorModeGeneral')
                        result['checks']['modeSwitchPreservesObjects'] = browser.evaluate('uploadedSealEditorState.elements.length===2')
                        browser.click_visible('[data-editor-summary-id="' + first_id + '"]')
                        browser.until('uploadedSealCurrentPage===1 && uploadedSealEditorRuntime.selectedIds.size===1')
                        result['checks']['summarySelectNavigatesPage'] = True
                        browser.until('uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration&&!uploadedSealEditorRuntime.saving')
                        doc_id = browser.evaluate('uploadedSealEditorRuntime.documentId')
                        result['documentId'] = doc_id
                        result['savedStatus'] = browser.evaluate("document.querySelector('#uploadedEditorSaveStatus').textContent")
                        result['beforeLayout'] = browser.evaluate(AUDIT_JS)
                        browser.run('screenshot', str(output / f'{prefix}-edited.png'), '--full')
                        browser.run('fill', '#uploadedSealTitle', f'隔離測試 {prefix} 已修改主旨')
                        browser.run('fill', '#uploadedSealReason', '隔離測試已修改原因，不送簽、不寄發。')
                        browser.run('press', 'Tab')
                        time.sleep(3)
                        result['formBeforeReload'] = browser.evaluate(FORM_JS)
                        saved = fixture._expect_json('GET', f'/api/official-documents/{doc_id}', 200, token=auth['token'])
                        result['serverApplicationBeforeReload'] = {k: saved.get(k) for k in ['title', 'subject', 'description', 'request_reason', 'document_category', 'company_id', 'dispatch_unit']}
                        result['checks']['applicationAutosave'] = saved.get('title') == f'隔離測試 {prefix} 已修改主旨' and saved.get('request_reason') == '隔離測試已修改原因，不送簽、不寄發。'
                        browser.run('open', fixture.origin + f'/?editor_reload={time.monotonic_ns()}#electronicSeal')
                        browser.until("window.__fixtureTiming?.appInteractiveMs")
                        browser.until("Boolean(document.querySelector('[data-electronic-seal-open=" + json.dumps(doc_id) + "]'))")
                        browser.click_visible('[data-electronic-seal-open="' + doc_id + '"]')
                        browser.until('uploadedSealEditorState.pages.length===3 && uploadedSealEditorState.elements.length===2 && uploadedSealEditorRuntime.pageProxies.size===3 && (typeof uploadedSealApplicationRuntime === "undefined" || !uploadedSealApplicationRuntime.openPromise)')
                        result['checks']['reloadPreservesPdfAndObjects'] = True
                        result['formAfterReload'] = browser.evaluate(FORM_JS)
                        result['checks']['reloadRestoresForm'] = all(result['formAfterReload'][k]['value'] == result['formBeforeReload'][k]['value'] for k in result['formBeforeReload'])
                        result['checks']['reopenedCategoryUsable'] = bool(result['formAfterReload']['ApprovalCategorySelect']['value'])
                        result['afterLayout'] = browser.evaluate(AUDIT_JS)
                        browser.run('snapshot', '-i')
                        browser.run('screenshot', str(output / f'{prefix}-reopened.png'), '--full')
                        if role == args.roles[0] and browser.evaluate('typeof uploadedSealApplicationRuntime !== "undefined"'):
                            browser.run('set', 'offline', 'on')
                            browser.run('fill', '#uploadedSealTitle', f'隔離測試 {prefix} 離線保留')
                            browser.run('press', 'Tab')
                            browser.until('Boolean(uploadedSealApplicationRuntime.error)')
                            result['checks']['offlineKeepsFormAndShowsUnsaved'] = browser.evaluate("!navigator.onLine&&uploadedSealApplicationHasUnsavedChanges()&&document.querySelector('#uploadedSealApplicationSaveStatus').textContent.includes('離線')&&document.querySelector('#uploadedSealTitle').value.includes('離線保留')")
                            browser.run('screenshot', str(output / f'{prefix}-offline-retained.png'), '--full')
                            browser.run('set', 'offline', 'off')
                            browser.until('!uploadedSealApplicationHasUnsavedChanges()&&!uploadedSealApplicationRuntime.promise')
                            result['checks']['onlineAutomaticallyRetriesMetadata'] = fixture._expect_json('GET', f'/api/official-documents/{doc_id}', 200, token=auth['token']).get('title') == f'隔離測試 {prefix} 離線保留'
                            # Fail only this synthetic draft's local PATCH. Never
                            # write the token, request payload or interception log.
                            browser.evaluate("window.__editorAuditFetch=window.fetch;window.__editorAuditFailPatch=true;window.fetch=async(input,options={})=>{if(options.method==='PATCH'&&String(input).endsWith('/official-documents/" + doc_id + "')&&window.__editorAuditFailPatch)return new Response(JSON.stringify({error:'service_unavailable',detail:'service_unavailable'}),{status:503,headers:{'Content-Type':'application/json'}});return window.__editorAuditFetch(input,options)};true")
                            browser.run('fill', '#uploadedSealTitle', f'隔離測試 {prefix} 失敗後重試')
                            browser.run('press', 'Tab')
                            browser.until('Boolean(uploadedSealApplicationRuntime.error)')
                            result['checks']['saveFailureVisible'] = browser.evaluate("document.querySelector('#uploadedSealApplicationSaveStatus').textContent.includes('未保存')&&!document.querySelector('#uploadedSealApplicationRetryBtn').hidden")
                            browser.click_visible('[data-electronic-seal-open="' + doc_id + '"]')
                            browser.until('!uploadedSealApplicationRuntime.openPromise')
                            result['checks']['unsavedSwitchBlocked'] = browser.evaluate("uploadedSealApplicationHasUnsavedChanges()&&uploadedSealEditorState.pages.length===3&&document.querySelector('#uploadedSealTitle').value.includes('失敗後重試')")
                            browser.run('screenshot', str(output / f'{prefix}-save-failure-protected.png'), '--full')
                            browser.evaluate('window.__editorAuditFailPatch=false;true')
                            browser.click_visible('#uploadedSealApplicationRetryBtn')
                            browser.until('!uploadedSealApplicationHasUnsavedChanges()&&!uploadedSealApplicationRuntime.promise')
                            result['checks']['explicitRetrySaved'] = fixture._expect_json('GET', f'/api/official-documents/{doc_id}', 200, token=auth['token']).get('title') == f'隔離測試 {prefix} 失敗後重試'
                            browser.evaluate('window.fetch=window.__editorAuditFetch;delete window.__editorAuditFetch;true')
                            # Synthetic seal preview only. Trap the submission
                            # request in-browser so no approval is ever created.
                            browser.click_visible('#uploadedPdfEditor [data-editor-tool="seal"]')
                            browser.click_visible('#addSelectedStampBtn')
                            browser.until("uploadedSealEditorState.elements.some(e=>e.kind==='seal')&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration&&!uploadedSealEditorRuntime.saving")
                            browser.evaluate("window.__editorAuditFetch=window.fetch;window.__editorAuditSubmitCalls=0;window.fetch=async(input,options={})=>{if(options.method==='POST'&&String(input).endsWith('/official-documents/" + doc_id + "/submit')){window.__editorAuditSubmitCalls++;return new Response(JSON.stringify({error:'fixture_no_submission',detail:'fixture_no_submission'}),{status:418,headers:{'Content-Type':'application/json'}});}return window.__editorAuditFetch(input,options)};true")
                            browser.click_visible('#submitUploadedSealBtn')
                            browser.until("uploadedEditorSubmissionPreviewIsCurrent()&&!uploadedSealApplicationRuntime.submissionBusy")
                            result['checks']['firstActionShowsPreparedWithoutSubmitting'] = browser.evaluate("window.__editorAuditSubmitCalls===0&&uploadedSealEditorRuntime.reviewMode==='prepared'&&uploadedSealEditorRuntime.preparedPdfDocument.numPages===3&&document.querySelector('#submitUploadedSealBtn').textContent==='確認內容並送簽'")
                            result['preparedLayout'] = browser.evaluate(AUDIT_JS)
                            result['checks']['preparedHasNoDocumentOverflow'] = not result['preparedLayout']['overflow']
                            browser.run('screenshot', str(output / f'{prefix}-prepared-before-confirm.png'), '--full')
                            browser.run('fill', '#uploadedSealTitle', f'隔離測試 {prefix} 確認前修改')
                            result['checks']['applicationChangeInvalidatesConfirmation'] = browser.evaluate("!uploadedEditorSubmissionPreviewIsCurrent()&&document.querySelector('#submitUploadedSealBtn').disabled&&!document.querySelector('#uploadedEditorBackToEditBtn').hidden")
                            browser.click_visible('#uploadedEditorBackToEditBtn')
                            browser.until("uploadedSealEditorRuntime.reviewMode==='edited'")
                            browser.click_visible('#submitUploadedSealBtn')
                            browser.until('uploadedEditorSubmissionPreviewIsCurrent()&&!uploadedSealApplicationRuntime.submissionBusy')
                            browser.click_visible('#submitUploadedSealBtn')
                            browser.until('window.__editorAuditSubmitCalls===1&&!uploadedSealApplicationRuntime.submissionBusy')
                            result['checks']['onlySecondExplicitActionAttemptsSubmit'] = browser.evaluate('window.__editorAuditSubmitCalls===1&&!uploadedSealEditorRuntime.locked')
                            browser.evaluate('window.fetch=window.__editorAuditFetch;delete window.__editorAuditFetch;true')
                            result['checks']['noRealFixtureSubmissionCreated'] = fixture._expect_json('GET', f'/api/official-documents/{doc_id}', 200, token=auth['token']).get('current_status') == 'draft'
                        result['status'] = 'passed' if all(result['checks'].values()) else 'issues_found'
                    except Exception as exc:
                        result['status'] = 'incomplete'
                        result['errorCode'] = str(exc) if str(exc).startswith('browser_') else type(exc).__name__
                        try:
                            result['failureState'] = browser.evaluate("({route:document.querySelector('.view.active')?.id,toast:document.querySelector('#toast')?.textContent,error:document.querySelector('#uploadedEditorUploadErrorMessage')?.textContent,pages:uploadedSealEditorState.pages.length,elements:uploadedSealEditorState.elements.length,errors:window.__fixtureErrors})")
                            browser.run('screenshot', str(output / f'{prefix}-failed.png'), '--full')
                        except Exception:
                            pass
                    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
                    print(json.dumps({'completed': prefix, 'status': result['status'], 'checks': result['checks']}, ensure_ascii=False), flush=True)
        finally:
            browser.run('close')
            fixture.tearDownClass()
    return 0 if all(row['status'] == 'passed' for row in report['journeys']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
