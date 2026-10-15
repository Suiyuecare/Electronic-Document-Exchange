"""Readonly presentation acceptance against deidentified localhost HTTP only."""
import argparse
import hashlib
import json
import sys
import traceback
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as F
from tests.support.five_account_browser_fixture import isolated_browser_session
from tools.six_role_browser_acceptance import Browser, require_local_origin


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['before', 'after'], default='after')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'phase': args.phase, 'scope': 'synthetic localhost HTTP; not real SSO', 'checks': []}
    browser = None
    F.setUpClass()
    try:
        require_local_origin(F.origin)
        auth = isolated_browser_session(F, 'staff')
        case = next(item for item in F.case_definitions if item['role'] == 'staff' and item['route'] == 'A')
        original = F._expect_json
        submitted = {}

        class Captured(Exception):
            pass

        def capture(method, path, *a, **kw):
            result = original(method, path, *a, **kw)
            if method == 'POST' and path.endswith('/submit'):
                submitted.update(result)
                raise Captured()
            return result

        with mock.patch.object(F, '_expect_json', side_effect=capture):
            try:
                F._run_case(case, {case['ordinal']: auth['token']})
            except Captured:
                pass
        doc_id = submitted['id']
        draft_id = ''
        if args.phase == 'after':
            def capture_draft(method, path, *a, **kw):
                nonlocal draft_id
                if method == 'POST' and path.endswith('/submit'):
                    draft_id = path.split('/')[-2]
                    raise Captured()
                return original(method, path, *a, **kw)
            with mock.patch.object(F, '_expect_json', side_effect=capture_draft):
                try:
                    F._run_case({**case, 'orientations': ['portrait', 'portrait']}, {case['ordinal']: auth['token']})
                except Captured:
                    pass
        def revision_digest():
            value = F._expect_json('GET', '/api/official-documents/' + doc_id + '/editor-state', 200, token=auth['token'])
            immutable = {key: value.get(key) for key in ['revisionNo', 'id', 'revision_id', 'manifestSha256', 'state', 'preparedFileId', 'preparedSha256']}
            return hashlib.sha256(json.dumps(immutable, sort_keys=True).encode()).hexdigest()
        before_digest = revision_digest()
        config = args.output / 'browser-config.json'
        config.write_text('{"headed":false}')
        browser = Browser(config, session='p2-readonly-' + args.phase, namespace='p2-readonly-' + args.phase)
        for device, width, height in [('desktop', 1440, 1000), ('mobile', 390, 844)]:
            browser.run('set', 'viewport', str(width), str(height))
            browser.run('open', F.origin + '/assets/favicon-32.png')
            browser.evaluate('localStorage.clear();sessionStorage.clear();localStorage.setItem("suiyuecare-edoc-session",' + json.dumps(json.dumps(auth)) + ');true')
            browser.run('open', F.origin + '/#electronicSeal?case=' + doc_id + '&tab=mine&mode=edited')
            browser.until('hasAuthenticatedBackendSession()&&!document.querySelector("#appShell").inert&&!uploadedSealApplicationRuntime.openPromise&&uploadedSealEditorRuntime.documentId===' + json.dumps(doc_id))
            browser.evaluate('document.querySelector("#uploadedPdfEditor").scrollIntoView({block:"start"});true')
            browser.run('screenshot', str(args.output / (args.phase + '-' + device + '-header.png')))
            state = browser.evaluate('''(()=>{const visible=s=>!!document.querySelector(s)?.getClientRects().length;return {locked:uploadedSealEditorRuntime.locked,title:document.querySelector('#uploadedSealWorkspaceTitle').textContent,status:document.querySelector('#uploadedEditorSaveStatus').textContent,toolbar:visible('#uploadedEditorToolTray'),save:visible('#uploadedEditorSaveDraftBtn'),replace:visible('#uploadedPdfReplaceBtn'),delete:visible('[data-editor-summary-delete]'),footer:visible('.pdf-editor-footer-actions'),readonly:visible('#uploadedEditorReadOnlyNotice'),newApplicationReadiness:visible('#uploadedSealWorkflowReadinessNotice'),back:visible('#uploadedSealReturnBtn'),new:visible('#uploadedSealNewBtn'),overflow:document.documentElement.scrollWidth>innerWidth+1}})()''')
            report['checks'].append({'device': device, 'state': state, 'passed': state['locked'] and not any(state[k] for k in ['toolbar', 'save', 'replace', 'delete', 'footer', 'newApplicationReadiness', 'overflow']) and state['readonly'] and state['back'] and state['new']})
            browser.evaluate('document.querySelector("#uploadedPdfStage").scrollIntoView({block:"center"});true')
            browser.run('screenshot', str(args.output / (args.phase + '-' + device + '-document.png')))
            if args.phase == 'after':
                browser.evaluate('''window.__readonlyDownloads=[];window.__readonlyFetch=window.fetch;window.fetch=async function(input,options){const response=await window.__readonlyFetch.call(this,input,options);if(/\\/files\\/[^/]+\\/download/.test(String(input))){const bytes=await response.clone().arrayBuffer();const digest=await crypto.subtle.digest('SHA-256',bytes);window.__readonlyDownloads.push({status:response.status,type:response.headers.get('content-type'),sha256:Array.from(new Uint8Array(digest)).map(x=>x.toString(16).padStart(2,'0')).join('')});}return response;};true''')
                browser.click_visible('#uploadedEditorReadOnlyDownloadBtn')
                browser.until('window.__readonlyDownloads.length===1&&!document.querySelector("#uploadedEditorReadOnlyDownloadBtn").disabled')
                downloaded = browser.evaluate('window.__readonlyDownloads[0]')
                expected_sha = browser.evaluate('uploadedSealEditorRuntime.preparedSha256')
                report['checks'].append({'device': device, 'name': 'actual authorized prepared download', 'download': downloaded, 'expectedSha256': expected_sha, 'passed': downloaded['status'] == 200 and downloaded['sha256'].lower() == expected_sha.lower()})
                browser.click_visible('#uploadedEditorZoomInBtn')
                report['checks'].append({'device': device, 'name': 'single page has honest page boundary', 'passed': browser.evaluate('document.querySelector("#uploadedPdfNextBtn").disabled&&document.querySelector("#uploadedPdfPrevBtn").disabled')})
                browser.run('reload')
                browser.until('hasAuthenticatedBackendSession()&&!document.querySelector("#appShell").inert&&!uploadedSealApplicationRuntime.openPromise&&uploadedSealEditorRuntime.documentId===' + json.dumps(doc_id))
                report['checks'].append({'device': device, 'name': 'view zoom page refresh preserve exact revision', 'passed': revision_digest() == before_digest})
                browser.run('open', F.origin + '/#electronicSeal?case=' + draft_id + '&tab=mine&mode=edited')
                browser.until('!uploadedSealApplicationRuntime.openPromise&&uploadedSealEditorRuntime.documentId===' + json.dumps(draft_id) + '&&!document.querySelector("#submitUploadedSealBtn").disabled')
                browser.click_visible('#submitUploadedSealBtn')
                browser.until('uploadedSealEditorRuntime.reviewMode==="prepared"&&uploadedEditorSubmissionPreviewIsCurrent()&&!uploadedSealApplicationRuntime.submissionBusy')
                preview_state = browser.evaluate('''(()=>{const visible=s=>!!document.querySelector(s)?.getClientRects().length;return {readonly:visible('#uploadedEditorReadOnlyNotice'),toolbar:visible('#uploadedEditorToolTray'),back:visible('#uploadedEditorBackToEditBtn'),confirm:visible('#submitUploadedSealBtn')&&!document.querySelector('#submitUploadedSealBtn').disabled,label:document.querySelector('#submitUploadedSealBtn').textContent}})()''')
                report['checks'].append({'device': device, 'name': 'own draft preview retains confirmation and return', 'state': preview_state, 'passed': preview_state['readonly'] and not preview_state['toolbar'] and preview_state['back'] and preview_state['confirm'] and preview_state['label'] == '確認內容並送簽'})
                browser.click_visible('#uploadedPdfNextBtn')
                browser.until('currentUploadedEditorPageIndex()===1')
                browser.click_visible('#uploadedPdfPrevBtn')
                browser.until('currentUploadedEditorPageIndex()===0')
                browser.run('screenshot', str(args.output / ('after-' + device + '-draft-confirmation.png')))
                browser.click_visible('#uploadedEditorBackToEditBtn')
                browser.until('uploadedSealEditorRuntime.reviewMode==="edited"')
                edit_state = browser.evaluate('''({toolbar:!!document.querySelector('#uploadedEditorToolTray').getClientRects().length,readonly:!!document.querySelector('#uploadedEditorReadOnlyNotice').getClientRects().length,readiness:!!document.querySelector('#uploadedSealWorkflowReadinessNotice').getClientRects().length,title:document.querySelector('#uploadedSealWorkspaceTitle').textContent,locked:uploadedSealEditorRuntime.locked})''')
                report['checks'].append({'device': device, 'name': 'return to draft restores editing', 'state': edit_state, 'passed': edit_state['toolbar'] and not edit_state['readonly'] and not edit_state['locked'] and edit_state['readiness'] and edit_state['title'] == '電子用印編輯'})
        after = F._expect_json('GET', '/api/official-documents/' + doc_id, 200, token=auth['token'])
        after_digest = revision_digest()
        report['revisionDigests'] = {'before': before_digest, 'after': after_digest}
        report['immutable'] = after['current_status'] == submitted['current_status'] and after['stamp_request'] == submitted['stamp_request'] and before_digest == after_digest
        report['completed'] = report['immutable'] and all(item['passed'] for item in report['checks'])
    except Exception as exc:
        report.update(error=str(exc), trace=traceback.format_exc())
        if browser:
            browser.run('screenshot', str(args.output / (args.phase + '-failure.png')))
    finally:
        if browser:
            try:
                browser.run('close')
            except Exception:
                pass
        F.tearDownClass()
        (args.output / (args.phase + '-report.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get('completed') and report.get('immutable') and all(item['passed'] for item in report['checks']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
