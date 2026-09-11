"""Local synthetic browser acceptance. No real login, seal, sending or storage."""
from pathlib import Path
import io
import json
import sys
import time
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, letter
from tools.six_role_browser_acceptance import Browser, TELEMETRY, AUDIT_JS
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler


def main():
    output = Path('/tmp/edoc-repair-evidence-20260911/editor')
    output.mkdir(parents=True, exist_ok=True)
    fixture = FiveAccountHttpAcceptanceTest
    original = QuietAcceptanceHandler.send_head
    def instrument(handler):
        if urlparse(handler.path).path in {'/', '/index.html'}:
            data = (ROOT / 'index.html').read_text().replace('<head>', '<head>' + TELEMETRY, 1).encode()
            handler.send_response(200); handler.send_header('Content-Type','text/html; charset=utf-8'); handler.send_header('Content-Length',str(len(data))); handler.end_headers()
            return io.BytesIO(data)
        return original(handler)
    report = {'scope':'isolated_local_synthetic_no_submission', 'journeys': []}
    with mock.patch.object(QuietAcceptanceHandler, 'send_head', instrument):
        fixture.setUpClass()
        config = Path(fixture.tmp.name) / 'browser.json'
        config.write_text(json.dumps({'allowedDomains':['127.0.0.1','fonts.googleapis.com','fonts.gstatic.com'],'headed':False}))
        browser = Browser(config, session='edoc-a4-seam-20260911', namespace='edoc-a4-seam-isolated')
        try:
            # Immediate browser verification after starting the local server.
            browser.run('open', fixture.origin + '/')
            browser.run('snapshot','-i')
            for device in ('desktop','mobile'):
                result = {'device':device,'checks':{}}
                report['journeys'].append(result)
                try:
                    auth = isolated_browser_session(fixture,'ceo')
                    browser.run('open',fixture.origin+'/assets/favicon-32.png')
                    browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session',"+json.dumps(json.dumps(auth))+");true")
                    browser.run('set','viewport',*('1440','1000') if device=='desktop' else ('390','844'))
                    browser.run('open',fixture.origin+f'/?repair={time.monotonic_ns()}#electronicSeal')
                    browser.until("window.__fixtureTiming?.appInteractiveMs && document.querySelector('#uploadedSealApprovalCategorySelect')?.options.length>1")
                    browser.run('snapshot','-i')
                    category = browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(e=>e.textContent.includes('合作意向書')).value")
                    browser.run('select','#uploadedSealApprovalCategorySelect',category)
                    browser.run('fill','#uploadedSealTitle','隔離測試公文修繕')
                    browser.run('fill','#uploadedSealReason','合成 PDF 編輯驗收，不送簽、不寄發。')
                    source = Path(fixture.tmp.name)/f'synthetic-{device}-letter.pdf'
                    pdf = canvas.Canvas(str(source),pagesize=letter)
                    for page in range(3):
                        pdf.drawString(40,740,f'SYNTHETIC LETTER PAGE {page+1}'); pdf.showPage()
                    pdf.save()
                    browser.run('upload','#uploadedSealPdfInput',str(source))
                    browser.until("document.querySelector('#editorA4Dialog')?.open")
                    result['checks']['nonA4ShowsSize'] = browser.evaluate("document.querySelector('#editorA4Details').textContent.includes('215.9')")
                    browser.run('screenshot',str(output/f'{device}-a4-choice.png'))
                    browser.click_visible('[data-a4-confirm]')
                    browser.until("document.querySelector('#editorA4Title')?.textContent==='請確認 A4 轉換結果' || (!uploadedSealEditorRuntime.uploading && !document.querySelector('#uploadedEditorUploadError').hidden)",60)
                    browser.until("document.querySelector('#editorA4Dialog canvas')?.width>0 && !document.querySelector('[data-a4-confirm]')?.disabled",30)
                    browser.click_visible('[data-a4-next]')
                    browser.until("document.querySelector('[data-a4-page]')?.textContent.includes('第 2 /')")
                    browser.run('screenshot',str(output/f'{device}-a4-preview.png'))
                    browser.click_visible('[data-a4-confirm]')
                    browser.until("uploadedSealEditorState.pages.length===3&&!uploadedSealEditorRuntime.uploading",30)
                    result['checks']['convertedThreePages'] = browser.evaluate('uploadedSealEditorState.pages.length===3')
                    result['checks']['originalAndDerivativePreserved'] = browser.evaluate('uploadedSealEditorState.sourceFiles.length===2')
                    browser.run('select','#uploadedEditorReviewSelect','original')
                    browser.until("uploadedSealEditorRuntime.reviewMode==='original' && document.querySelector('#uploadedPdfGeometryLabel').textContent.includes('不可變原稿')")
                    result['checks']['originalPreviewUsesLetterGeometry'] = browser.evaluate('Math.abs(uploadedSealEditorRuntime.currentViewport.width/uploadedSealEditorRuntime.currentViewport.height-612/792)<.001')
                    browser.run('select','#uploadedEditorReviewSelect','edited')
                    browser.until("uploadedSealEditorRuntime.reviewMode==='edited' && Math.abs(uploadedSealEditorRuntime.currentViewport.width/uploadedSealEditorRuntime.currentViewport.height-210/297)<.001")
                    browser.click_visible('#uploadedEditorSeamToggleBtn')
                    browser.click_visible('#uploadedEditorSeamAddBtn')
                    browser.until('EDOCSeam.groups(uploadedSealEditorState).size===2')
                    result['checks']['batchCreatesTwoPairs'] = True
                    result['checks']['batchStaggersPositions'] = browser.evaluate("new Set([...EDOCSeam.groups(uploadedSealEditorState).values()].map(m=>EDOCSeam.topPt(uploadedSealEditorState.pages.find(p=>p.pageId===m[0].pageId),m[0]).toFixed(2))).size===2")
                    browser.run('fill','#uploadedEditorSeamGroups [data-seam-position]','45')
                    browser.run('press','Tab')
                    browser.until("Math.abs(EDOCSeam.topPt(uploadedSealEditorState.pages[0],uploadedSealEditorState.elements[0])/EDOCSeam.ptPerMm-45)<.1")
                    positions = browser.evaluate("[...EDOCSeam.groups(uploadedSealEditorState).values()].map(m=>EDOCSeam.topPt(uploadedSealEditorState.pages.find(p=>p.pageId===m[0].pageId),m[0])/EDOCSeam.ptPerMm)")
                    result['checks']['independentGroupPositions'] = abs(positions[0]-positions[1])>10
                    browser.until('uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration&&!uploadedSealEditorRuntime.saving')
                    document_id = browser.evaluate('uploadedSealEditorRuntime.documentId')
                    browser.evaluate('void loadUploadedEditorState('+json.dumps(document_id)+');true')
                    browser.until('!uploadedSealEditorRuntime.locked&&EDOCSeam.groups(uploadedSealEditorState).size===2&&uploadedSealEditorRuntime.currentViewport?.width>0')
                    result['checks']['reopenPreservesPairsAndA4'] = True
                    browser.run('screenshot',str(output/f'{device}-seam-editor.png'))
                    before = browser.evaluate('canonicalEditorJson({pages:uploadedSealEditorState.pages,elements:uploadedSealEditorState.elements})')
                    browser.run('upload','#uploadedSealPdfInput',str(source))
                    browser.until("document.querySelector('#editorA4Dialog')?.open")
                    browser.click_visible('[data-a4-confirm]')
                    browser.until("document.querySelector('#editorA4Title')?.textContent==='請確認 A4 轉換結果' && !document.querySelector('[data-a4-confirm]')?.disabled",60)
                    browser.click_visible('[data-a4-cancel]')
                    browser.until('!uploadedSealEditorRuntime.uploading && !uploadedSealEditorRuntime.saving')
                    after = browser.evaluate('canonicalEditorJson({pages:uploadedSealEditorState.pages,elements:uploadedSealEditorState.elements})')
                    result['checks']['cancelConversionPreservesEditor'] = before == after
                    if device == 'mobile':
                        browser.evaluate("showToast('隔離驗收：提示訊息不可被底部導覽擋住。');true")
                        browser.until("document.querySelector('#toast').getBoundingClientRect().bottom <= document.querySelector('.mobile-primary-nav').getBoundingClientRect().top")
                        result['checks']['mobileToastAboveNavigation'] = True
                        browser.run('screenshot',str(output/'mobile-toast-visible.png'))
                    result['layout'] = browser.evaluate(AUDIT_JS)
                    result['status'] = 'passed' if all(result['checks'].values()) and not result['layout']['overflow'] and not result['layout']['errors'] else 'failed'
                except Exception as error:
                    result['status']='failed'; result['error']=str(error)
                    result['failureState']=browser.evaluate("({toast:document.querySelector('#toast')?.textContent,error:document.querySelector('#uploadedEditorUploadErrorMessage')?.textContent,dialog:document.querySelector('#editorA4Dialog')?.textContent,save:document.querySelector('#uploadedEditorSaveStatus')?.textContent,js:window.__fixtureErrors})")
                    browser.run('screenshot',str(output/f'{device}-failure.png'))
                (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        finally:
            browser.run('close'); fixture.tearDownClass()
    print(json.dumps(report,ensure_ascii=False))
    return 0 if all(row['status']=='passed' for row in report['journeys']) else 1

if __name__=='__main__': raise SystemExit(main())
