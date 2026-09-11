"""Real browser/HTTP conflict-copy check using isolated synthetic accounts only."""
import io
import json
import sys
import time
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from tools.six_role_browser_acceptance import Browser, AUDIT_JS, TELEMETRY
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler


def main():
    output = Path('/tmp/edoc-conflict-copy-evidence-20260911')
    output.mkdir(exist_ok=True)
    original = QuietAcceptanceHandler.send_head
    def instrument(handler):
        if urlparse(handler.path).path in {'/', '/index.html'}:
            data = (ROOT / 'index.html').read_text().replace('<head>', '<head>' + TELEMETRY, 1).encode()
            handler.send_response(200)
            handler.send_header('Content-Type', 'text/html; charset=utf-8')
            handler.send_header('Content-Length', str(len(data)))
            handler.end_headers()
            return io.BytesIO(data)
        return original(handler)
    report = {'scope': 'isolated fixture HTTP, no real Google login, no production writes', 'journeys': []}
    fixture = FiveAccountHttpAcceptanceTest
    with mock.patch.object(QuietAcceptanceHandler, 'send_head', instrument):
        fixture.setUpClass()
        config = Path(fixture.tmp.name) / 'conflict-browser.json'
        config.write_text(json.dumps({'allowedDomains': ['127.0.0.1', 'fonts.googleapis.com', 'fonts.gstatic.com'], 'headed': False}))
        browser = Browser(config, session='edoc-conflict-20260911', namespace='edoc-conflict-local')
        try:
            for device, size in [('desktop', (1440, 1000)), ('mobile', (390, 844))]:
                auth = isolated_browser_session(fixture, 'staff')
                browser.run('open', fixture.origin + '/assets/favicon-32.png')
                browser.evaluate('localStorage.clear();sessionStorage.clear();localStorage.setItem("suiyuecare-edoc-session",' + json.dumps(json.dumps(auth)) + ');true')
                browser.run('set', 'viewport', *map(str, size))
                browser.run('open', fixture.origin + '/?conflict_fixture=' + str(time.monotonic_ns()) + '#electronicSeal')
                browser.until("window.__fixtureTiming?.appInteractiveMs && document.querySelector('#uploadedSealApprovalCategorySelect')?.options.length>1")
                browser.run('snapshot', '-i')
                assert browser.evaluate("document.body.innerText.trim().length>0 && !document.querySelector('.vite-error-overlay,[data-nextjs-dialog]')")
                category = browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(o=>o.textContent.includes('合作意向書')).value")
                browser.run('select', '#uploadedSealApprovalCategorySelect', category)
                browser.run('fill', '#uploadedSealTitle', '隔離測試：保留我的內容')
                browser.run('fill', '#uploadedSealReason', '測試版本衝突，不送簽、不寄發。')
                pdf = Path(fixture.tmp.name) / (device + '-fixture.pdf')
                writer = canvas.Canvas(str(pdf), pagesize=A4)
                writer.drawString(50, 780, 'ISOLATED CONFLICT RECOVERY FIXTURE')
                writer.showPage()
                writer.save()
                browser.run('upload', '#uploadedSealPdfInput', str(pdf))
                browser.until('uploadedSealEditorState.pages.length===1&&!uploadedSealEditorRuntime.uploading')
                old_id = browser.evaluate('uploadedSealEditorRuntime.documentId')
                server = fixture._expect_json('GET', f'/api/official-documents/{old_id}/editor-state', 200, token=auth['token'])
                server['state']['elements'] = []
                fixture._expect_json('PUT', f'/api/official-documents/{old_id}/editor-state', 200, token=auth['token'], json_body={'revisionNo': server['revisionNo'], 'baseManifestSha256': server['manifestSha256'], 'state': server['state']})
                browser.click_visible('#uploadedPdfEditor [data-editor-tool="text"]')
                browser.run('fill', '#uploadedSealTextInput', '這是我要保留的本機修改')
                browser.click_visible('#addUploadedTextBtn')
                browser.until('Boolean(uploadedSealEditorRuntime.conflict)')
                browser.evaluate("document.querySelector('#uploadedEditorConflictCopyBtn').scrollIntoView({block:'center'});true")
                browser.run('screenshot', str(output / (device + '-conflict-choice.png')))
                before = browser.evaluate(AUDIT_JS)
                browser.click_visible('#uploadedEditorConflictCopyBtn')
                browser.until('uploadedSealEditorRuntime.documentId!==' + json.dumps(old_id) + '&&!uploadedSealEditorRuntime.conflict&&!uploadedSealEditorRuntime.locked', timeout=35)
                new_id = browser.evaluate('uploadedSealEditorRuntime.documentId')
                copied = fixture._expect_json('GET', f'/api/official-documents/{new_id}/editor-state', 200, token=auth['token'])
                old = fixture._expect_json('GET', f'/api/official-documents/{old_id}/editor-state', 200, token=auth['token'])
                assert copied['state']['elements'][0]['properties']['text'] == '這是我要保留的本機修改'
                assert old['state']['elements'] == []
                assert browser.evaluate("document.querySelector('#uploadedSealTitle').value==='隔離測試：保留我的內容'")
                browser.run('screenshot', str(output / (device + '-new-draft.png')))
                after = browser.evaluate(AUDIT_JS)
                assert not before['overflow'] and not after['overflow']
                assert not before['errors'] and not after['errors']
                report['journeys'].append({'device': device, 'status': 'passed', 'real409': True, 'newDocumentId': new_id, 'oldRevisionUnchanged': True, 'localTextReadBack': True, 'applicationPreserved': True, 'noOverflow': True, 'noBrowserErrors': True})
                print(json.dumps({'device': device, 'status': 'passed'}), flush=True)
        except Exception:
            try:
                report['failure'] = browser.evaluate("({status:document.querySelector('#uploadedEditorSaveStatus')?.textContent,toast:document.querySelector('#toast')?.textContent,errors:window.__fixtureErrors,conflict:!!uploadedSealEditorRuntime.conflict})")
                browser.run('screenshot', str(output / 'failure.png'))
            except Exception:
                pass
            raise
        finally:
            (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            browser.run('close')
            fixture.tearDownClass()


if __name__ == '__main__':
    main()
