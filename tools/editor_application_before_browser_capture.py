"""Read-only historical UI capture against the current isolated synthetic API.

This records the old field locks, not acceptance of the old client against the
new API. It serves Git blob bytes without changing checkout files or branches.
"""
from __future__ import annotations
import argparse
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
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as Fixture, QuietAcceptanceHandler
from tests.support.five_account_browser_fixture import isolated_browser_session
from tools.ux_complete_browser_acceptance import BRIDGE, TRANSPORT, TELEMETRY, require_local_origin
import tools.backup_drill_browser_acceptance as transport
BASELINE='2eaaa60ff12997946b266a2c295f5af10be35243'


def run(output:Path,pdfs:Path):
    output=output.resolve();output.mkdir(parents=True,exist_ok=True)
    blobs={name:subprocess.run(['git','show',BASELINE+':'+name],cwd=ROOT,check=True,capture_output=True).stdout for name in ('app.js','index.html','styles.css')}
    report={'scope':'loopback_historical_ui_visual_only','baselineCommit':BASELINE,'baselineAppSha256':hashlib.sha256(blobs['app.js']).hexdigest(),'currentBackendApi':True,'oldClientAcceptanceClaimed':False,'hostedVerified':False,'physicalDeviceVerified':False,'governmentExchange':'DISABLED','captures':[]}
    original=QuietAcceptanceHandler.send_head
    def head(handler):
        path=urlparse(handler.path).path;name='index.html' if path in ('/','/index.html') else path.removeprefix('/')
        if name not in blobs:return original(handler)
        data=blobs[name].replace(b'<head>',b'<head>'+TELEMETRY.encode(),1) if name=='index.html' else blobs[name]
        handler.send_response(200);handler.send_header('Content-Type',{'app.js':'application/javascript','styles.css':'text/css','index.html':'text/html; charset=utf-8'}[name]);handler.send_header('Content-Length',str(len(data)));handler.end_headers();return io.BytesIO(data)
    browser=None;executable=Path.home()/'Library/Caches/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell'
    with mock.patch.object(QuietAcceptanceHandler,'send_head',head),mock.patch.object(transport,'PLAYWRIGHT_BRIDGE',BRIDGE),mock.patch.dict(os.environ,{'EDOC_TEST_BROWSER_PATH':str(executable)}):
        Fixture.setUpClass();require_local_origin(Fixture.origin)
        try:
            custodian=isolated_browser_session(Fixture,'ceo',entity_id='E1');auth=isolated_browser_session(Fixture,'staff',entity_id='E1')
            Fixture._expect_json('PATCH','/api/companies/CO-001/seal-policy',200,token=custodian['token'],json_body={'owner_kind':'company'})
            browser=transport.LocalPlaywrightBrowser(Fixture.origin)
            for device,width,height in (('desktop',1440,1000),('phone',390,844)):
                browser.run('open',Fixture.origin+'/assets/favicon-32.png');browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session',"+json.dumps(json.dumps(auth))+");true")
                browser.run('set','viewport',str(width),str(height));browser.run('open',Fixture.origin+f'/?before={time.monotonic_ns()}#electronicSeal')
                browser.until("typeof uploadedSealApplicationRuntime==='object'&&!uploadedSealEditorRuntime.directoryLoading&&document.querySelector('#uploadedSealApprovalCategorySelect').options.length>1",timeout=40)
                browser.evaluate('window.__raceRealFetch=window.fetch;true');browser.evaluate(TRANSPORT)
                category=browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(e=>e.textContent.includes('服務委託合約')).value")
                browser.run('select','#uploadedSealApprovalCategorySelect',category);browser.run('fill','#uploadedSealTitle','合成原始申請 '+device);browser.run('fill','#uploadedSealReason','合成測試用途，無個資。')
                browser.evaluate("window.__raceRules.push({key:'transfer',method:'PUT',pattern:'/editor-uploads/[^/]+/content$',when:'before'});true")
                pdf=pdfs.resolve()/f'synthetic-{device}.pdf'
                if not pdf.is_file() or not pdf.is_relative_to(ROOT.parent):raise ValueError('synthetic_fixture_pdf_required')
                browser.run('upload','#uploadedSealPdfInput',str(pdf));browser.until("!!window.__raceHolds.transfer&&uploadedSealEditorState.pages.length===2&&!uploadedSealEditorRuntime.uploading&&uploadedSealEditorRuntime.finalizingAsset",timeout=40)
                locks=browser.evaluate("({company:document.querySelector('#uploadedSealCompany').disabled,department:document.querySelector('#uploadedSealDepartment').disabled,category:document.querySelector('#uploadedSealApprovalCategorySelect').disabled})")
                browser.evaluate("document.querySelector('#uploadedSealForm').scrollIntoView({block:'start',behavior:'instant'});true");browser.run('screenshot',str(output/f'{device}-before-held.png'))
                browser.evaluate('window.__raceHolds.transfer.release();true');browser.until('!uploadedSealEditorRuntime.finalizingAsset&&!uploadedSealEditorRuntime.saving',timeout=40)
                after=browser.evaluate("({company:document.querySelector('#uploadedSealCompany').disabled,department:document.querySelector('#uploadedSealDepartment').disabled,category:document.querySelector('#uploadedSealApprovalCategorySelect').disabled})")
                browser.evaluate("document.querySelector('#uploadedSealForm').scrollIntoView({block:'start',behavior:'instant'});true");browser.run('screenshot',str(output/f'{device}-before-saved.png'))
                report['captures'].append({'device':device,'syntheticPdfSha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),'heldFieldLocks':locks,'savedFieldLocks':after})
        finally:
            try:
                if browser:
                    try:browser.run('close')
                    except Exception:browser._stop()
            finally:Fixture.tearDownClass()
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--pdf-fixtures',type=Path,required=True);args=parser.parse_args();run(args.output,args.pdf_fixtures)
