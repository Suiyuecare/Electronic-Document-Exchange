"""Real localhost policy/calibration UI with only synthetic raster seals."""
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
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as Fixture, QuietAcceptanceHandler
from tests.support.five_account_browser_fixture import isolated_browser_session
from tools.ux_complete_browser_acceptance import BRIDGE, TRANSPORT, TELEMETRY, require_local_origin
import tools.backup_drill_browser_acceptance as transport


def run(output:Path):
    output=output.resolve();output.mkdir(parents=True,exist_ok=True)
    report={'scope':'loopback_synthetic_browser','hostedVerified':False,'physicalDeviceVerified':False,'humanSSOVerified':False,'governmentExchange':'DISABLED','sourceAppSha256':hashlib.sha256((ROOT/'app.js').read_bytes()).hexdigest(),'cases':[]}
    recorder=r"""<script>window.__sealPolicyHttp=[];(()=>{const real=window.fetch.bind(window);window.fetch=async(...args)=>{const path=new URL(args[0]?.url||String(args[0]),location.href).pathname;const response=await real(...args);const row={path,status:response.status};if(path==='/api/production/go-live-audit'){const body=await response.clone().json();row.decision=body.decision;row.formalGo=body.formalGo;row.internalGo=body.internalGo;}window.__sealPolicyHttp.push(row);return response;};})();</script>"""
    original=QuietAcceptanceHandler.send_head;html=(ROOT/'index.html').read_bytes().replace(b'<head>',b'<head>'+TELEMETRY.encode()+recorder.encode(),1)
    def head(handler):
        if urlparse(handler.path).path not in {'/','/index.html'}:return original(handler)
        handler.send_response(200);handler.send_header('Content-Type','text/html; charset=utf-8');handler.send_header('Content-Length',str(len(html)));handler.end_headers();return io.BytesIO(html)
    browser=None;executable=Path.home()/'Library/Caches/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell'
    with mock.patch.object(QuietAcceptanceHandler,'send_head',head),mock.patch.object(transport,'PLAYWRIGHT_BRIDGE',BRIDGE),mock.patch.dict(os.environ,{'EDOC_TEST_BROWSER_PATH':str(executable)}):
        Fixture.setUpClass();require_local_origin(Fixture.origin)
        try:
            auth=isolated_browser_session(Fixture,'ceo',entity_id='E1')
            Fixture._expect_json('PATCH','/api/companies/CO-001/seal-policy',200,token=auth['token'],json_body={'owner_kind':'company'})
            browser=transport.LocalPlaywrightBrowser(Fixture.origin)
            for device,width,height in (('desktop',1440,1000),('phone',390,844)):
                row={'case':device,'passed':False}
                try:
                    # Return to company policy for an independent page journey.
                    Fixture._expect_json('PATCH','/api/companies/CO-001/seal-policy',200,token=auth['token'],json_body={'owner_kind':'company'})
                    browser.run('open',Fixture.origin+'/assets/favicon-32.png');browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session',"+json.dumps(json.dumps(auth))+");true")
                    browser.run('set','viewport',str(width),str(height));browser.run('open',Fixture.origin+f'/?policy={time.monotonic_ns()}#seals')
                    browser.until("typeof companySealPolicy==='object'&&companySealPolicy?.company_id==='CO-001'&&companySealLoadState.status==='loaded'",timeout=40)
                    browser.evaluate('window.__raceRealFetch=window.fetch;true');browser.evaluate(TRANSPORT)
                    browser.evaluate("setCompanySealVaultTab('upload');fillSimpleSealRecord('');true")
                    browser.run('select','#simpleSealCategorySelect','continuous_seal')
                    row['continuousNoInventedDimensions']=browser.evaluate("document.querySelector('#simpleSealRenderSizeMmInput').value===''&&document.querySelector('#simpleSealRenderHeightMmInput').value===''&&document.querySelector('#simpleSealSizeSelect').value==='single_seal'&&document.querySelector('#simpleSealSizeLabel').hidden")
                    raster=Image.new('RGBA',(500,200),(255,255,255,0));draw=ImageDraw.Draw(raster);draw.rectangle((5,5,495,195),outline=(150,0,0,255),width=6);draw.line((25,100,475,100),fill=(150,0,0,255),width=4)
                    asset=output/f'synthetic-continuous-{device}.png';raster.save(asset)
                    browser.run('fill','#simpleSealNameInput','合成連續章 '+device);browser.run('fill','#simpleSealRenderSizeMmInput','35');browser.run('fill','#simpleSealRenderHeightMmInput','14');browser.run('upload','#simpleSealFileInput',str(asset))
                    browser.click_visible('#simpleSealUploadBtn');browser.until("companySealLibrary.some(s=>s.seal_name==="+json.dumps('合成連續章 '+device)+"&&s.current_file?.usable)",timeout=40)
                    rows=Fixture._expect_json('GET','/api/companies/CO-001/seals',200,token=auth['token']);continuous=next(s for s in rows if s['seal_name']=='合成連續章 '+device)
                    row['continuousActualFileReadback']=continuous['selectable'] is True and continuous['seal_size_type']=='single_seal' and continuous['current_file']['dimension_policy_version']=='continuous-seal-v1-calibrated' and continuous['current_file']['render_width_mm']==35 and continuous['current_file']['render_height_mm']==14
                    policy=Fixture._expect_json('GET','/api/companies/CO-001/seal-policy',200,token=auth['token'])
                    row['fiveSlotsReportedSeparately']=len(policy['required_slots'])==5 and any(s['category']=='continuous_seal' and s['size_type']=='single_seal' and s['digital_status']=='ready' for s in policy['required_slots'])
                    # Classification uses the canonical confirmation owner.
                    browser.run('select','#companySealOwnerKind','institution');browser.evaluate('window.__policyBefore=window.__raceRequests.length;true');browser.click_visible('#companySealPolicySaveBtn')
                    browser.until("!document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')");browser.click_visible('#workspaceTypedConfirmCancelBtn');browser.until("document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')")
                    row['classificationCancelZeroWrite']=browser.evaluate("!window.__raceRequests.slice(window.__policyBefore).some(r=>r.method==='PATCH'&&r.path.endsWith('/seal-policy'))") and Fixture._expect_json('GET','/api/companies/CO-001/seal-policy',200,token=auth['token'])['owner_kind']=='company'
                    browser.click_visible('#companySealPolicySaveBtn');browser.until("!document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')");browser.click_visible('#workspaceTypedConfirmSubmitBtn');browser.until("companySealPolicy?.owner_kind==='institution'&&!companySealPolicySaving&&companySealLoadState.status==='loaded'",timeout=40)
                    row['classificationExactlyOneWrite']=browser.evaluate("window.__raceRequests.slice(window.__policyBefore).filter(r=>r.method==='PATCH'&&r.path.endsWith('/seal-policy')).length===1")
                    browser.evaluate("fillSimpleSealRecord('');true");browser.run('select','#simpleSealCategorySelect','official_seal')
                    row['officialManualNoSquareDefault']=browser.evaluate("document.querySelector('#simpleSealRenderSizeMmInput').value===''&&document.querySelector('#simpleSealRenderHeightMmInput').value===''&&!document.querySelector('#simpleSealRenderHeightLabel').hidden")
                    raster=Image.new('RGBA',(400,1100),(255,255,255,0));draw=ImageDraw.Draw(raster);draw.rectangle((8,8,392,1092),outline=(120,0,0,255),width=8)
                    asset=output/f'synthetic-official-{device}.png';raster.save(asset)
                    browser.run('fill','#simpleSealNameInput','合成圖記章 '+device);browser.run('fill','#simpleSealRenderSizeMmInput','20');browser.run('fill','#simpleSealRenderHeightMmInput','55');browser.run('upload','#simpleSealFileInput',str(asset));browser.click_visible('#simpleSealUploadBtn')
                    browser.until("companySealLibrary.some(s=>s.seal_name==="+json.dumps('合成圖記章 '+device)+"&&s.current_file?.usable)",timeout=40)
                    rows=Fixture._expect_json('GET','/api/companies/CO-001/seals',200,token=auth['token']);official=next(s for s in rows if s['seal_name']=='合成圖記章 '+device)
                    row['officialActualRectangularProfile']=official['selectable'] is True and official['current_file']['dimension_policy_version']=='official-seal-v1-calibrated' and official['current_file']['render_width_mm']==20 and official['current_file']['render_height_mm']==55
                    browser.evaluate("setView('compose');true");browser.until("composeSealOptionsCompanyId==='CO-001'&&!composeSealOptionsLoading")
                    row['composeOwnOptionalSingleSlot']=browser.evaluate("!document.querySelector('#composeContinuousSealField').hidden&&[...document.querySelector('#continuousSealType').options].some(o=>o.value==='連續章')&&![...document.querySelector('#largeSealType').options].some(o=>o.value==='連續章')")
                    browser.run('select','#continuousSealType','連續章');browser.until("(()=>{const e=document.querySelector('#draftPreview .draft-seal-placeholder.single');return e&&e.getBoundingClientRect().width>0})()")
                    row['composeSinglePreviewUsesActualAspect']=browser.evaluate("(()=>{const e=document.querySelector('#draftPreview .draft-seal-placeholder.single .draft-seal-calibrated-mark'),r=e.getBoundingClientRect();return Math.abs(r.width/r.height-2.5)<0.05})()")
                    report.setdefault('composeDiagnostics',[]).append(browser.evaluate("(()=>{const e=document.querySelector('#draftPreview .draft-seal-placeholder.single'),r=e.getBoundingClientRect(),s=getComputedStyle(e);return {width:r.width,height:r.height,inline:e.style.cssText,computed:{width:s.width,height:s.height,minWidth:s.minWidth,minHeight:s.minHeight,maxWidth:s.maxWidth,maxHeight:s.maxHeight,boxSizing:s.boxSizing},parent:e.parentElement.getBoundingClientRect().toJSON(),profile:composeSealOptions.find(s=>s.seal_category==='continuous_seal')?.current_file}})()"))
                    report['stage']=device+':electronicSeal'
                    browser.evaluate("setView('electronicSeal');true");browser.until("!uploadedSealEditorRuntime.sealOptionsLoading&&!uploadedSealEditorRuntime.directoryLoading&&uploadedSealOptions.some(s=>s.seal_category==='official_seal'&&s.current_file?.usable)")
                    category=browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(e=>e.textContent.includes('服務委託合約')).value")
                    browser.run('select','#uploadedSealApprovalCategorySelect',category);browser.run('fill','#uploadedSealTitle','合成矩形章驗收 '+device);browser.run('fill','#uploadedSealReason','本機合成印章驗收，非真實印章。')
                    pdf=output/f'synthetic-seal-{device}.pdf';writer=canvas.Canvas(str(pdf),pagesize=A4);writer.drawString(60,780,'SYNTHETIC SEAL GEOMETRY');writer.showPage();writer.save()
                    browser.run('upload','#uploadedSealPdfInput',str(pdf));browser.until("uploadedSealEditorState.pages.length===1&&!uploadedSealEditorRuntime.finalizingAsset&&!uploadedSealEditorRuntime.saving",timeout=40)
                    browser.click_visible('[data-editor-tool="seal"]');browser.run('select','#uploadedSealCategorySelect','official_seal')
                    row['frontlineInstitutionTaxonomyOnly']=browser.evaluate("[...document.querySelector('#uploadedSealCategorySelect').options].every(o=>['official_seal','general_seal','continuous_seal'].includes(o.value))")
                    row['officialPickerKeepsActualDimensions']=browser.evaluate("document.querySelector('#uploadedSealPickerStatus').textContent.includes('20.00 × 55.00 mm')")
                    browser.click_visible('#addSelectedStampBtn');browser.evaluate('window.__rectSaved=false;void saveUploadedEditorState({immediate:true}).then(()=>window.__rectSaved=true);true');browser.until('window.__rectSaved')
                    doc_id=browser.evaluate('uploadedSealEditorRuntime.documentId');state=Fixture._expect_json('GET','/api/official-documents/'+doc_id+'/editor-state',200,token=auth['token'])['state'];element=next(e for e in state['elements'] if e['kind']=='seal')
                    row['actualPdfElementImmutableRectangle']=abs(element['width']/(20*72/25.4)-1)<0.0001 and abs(element['height']/(55*72/25.4)-1)<0.0001 and element['properties']['sealFileId']==official['current_file']['id']
                    row['noHorizontalOverflow']=browser.evaluate('document.documentElement.scrollWidth<=innerWidth+1');row['errorsEmpty']=browser.evaluate('window.__fixtureErrors.length===0')
                    api_failures=browser.evaluate('window.__sealPolicyHttp.filter(r=>r.status>=500)')
                    report.setdefault('readinessHttpEvidence',[]).append({'device':device,'responses':api_failures})
                    row['onlyExplicitReadinessNoGoResponse']=bool(api_failures) and all(r['path']=='/api/production/go-live-audit' and r['status']==503 and r.get('decision')=='NO_GO' and r.get('formalGo') is False and r.get('internalGo') is False for r in api_failures)
                    browser.run('screenshot',str(output/f'{device}-taxonomy-after.png'));row['passed']=all(v is True for k,v in row.items() if k not in {'case','passed'})
                except Exception as error:
                    row['errorCode']=type(error).__name__;row['lastCommand']=browser.last_command
                    try:row['runtime']=browser.evaluate("({errors:window.__fixtureErrors,policy:companySealPolicy?.owner_kind,status:document.querySelector('#simpleSealUploadStatus')?.textContent,category:document.querySelector('#simpleSealCategorySelect')?.value,width:document.querySelector('#simpleSealRenderSizeMmInput')?.value,height:document.querySelector('#simpleSealRenderHeightMmInput')?.value,uploadedCompany:document.querySelector('#uploadedSealCompany')?.value,loading:uploadedSealEditorRuntime.sealOptionsLoading,directory:uploadedSealEditorRuntime.directoryLoading,loadedSeals:uploadedSealOptions.map(s=>({kind:s.seal_category,owner:s.owner_kind,selectable:s.selectable,usable:s.current_file?.usable})),composeRatio:(()=>{const e=document.querySelector('#draftPreview .draft-seal-placeholder.single');if(!e)return null;const r=e.getBoundingClientRect();return {width:r.width,height:r.height}})()})")
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
    report['sourceAppSha256After']=hashlib.sha256((ROOT/'app.js').read_bytes()).hexdigest();report['passed']=len(report['cases'])==2 and all(row['passed'] for row in report['cases']) and report['sourceAppSha256']==report['sourceAppSha256After']
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();raise SystemExit(0 if run(args.output)['passed'] else 1)
