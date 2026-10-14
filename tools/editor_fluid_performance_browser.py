"""Local synthetic editor timing; no hosted network, human SSO, or real seals."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import sys
import time
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from tools.editor_latency_browser_acceptance import PAINT_PROBE, INSTALL_PAINT_PROBE, LATENCY_BRIDGE
from tools.six_role_browser_acceptance import TELEMETRY, require_local_origin
import tools.backup_drill_browser_acceptance as transport
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as Fixture, QuietAcceptanceHandler
from tests.support.five_account_browser_fixture import isolated_browser_session

PROBE = r"""(()=>{
 const p=window.__fluidTiming={pdfStart:null,pdfDurable:null,imageStart:null,imageVisible:null,imageDurable:null,drag:[],fullRenders:0,requests:[]};
 const pdf=document.querySelector('#uploadedSealPdfInput'),image=document.querySelector('#uploadedEditorImageInput');
 pdf.addEventListener('change',()=>p.pdfStart=performance.now(),{capture:true,once:true});
 image.addEventListener('change',()=>p.imageStart=performance.now(),{capture:true,once:true});
 const realFetch=window.fetch;window.fetch=async(...args)=>{const row={path:new URL(args[0]?.url||String(args[0]),location.href).pathname,method:args[1]?.method||'GET',start:performance.now()};p.requests.push(row);const response=await realFetch(...args);row.end=performance.now();row.status=response.status;return response;};
 const queue=queueUploadedEditorPointerRender,flush=flushUploadedEditorPointerRender,render=renderUploadedEditorSvgLayer;
 queueUploadedEditorPointerRender=function(ids){if(!uploadedSealEditorRuntime.pointerFrame)p.frameStart=performance.now();return queue(ids)};
 flushUploadedEditorPointerRender=function(){const result=flush();if(p.frameStart!==undefined){p.drag.push(performance.now()-p.frameStart);delete p.frameStart;}return result;};
 renderUploadedEditorSvgLayer=function(...args){p.fullRenders++;return render(...args);};
 const sample=()=>{const r=uploadedSealEditorRuntime,s=uploadedSealEditorState,now=performance.now();
  const durable=r.documentId&&s.pages.length&&!r.uploading&&!r.finalizingAsset&&!r.pendingEditorSave&&!r.saving&&!r.pendingImage&&r.savedGeneration>=r.dirtyGeneration&&!s.sourceFiles.some(x=>String(x.assetId).startsWith('LOCAL-'));
  if(p.pdfStart!==null&&p.pdfDurable===null&&durable)p.pdfDurable=now-p.pdfStart;
  if(p.imageStart!==null){const e=s.elements.find(e=>e.kind==='image');
   if(p.imageVisible===null&&e&&document.querySelector('#uploadedEditorSvgLayer image')&&!r.uploading)p.imageVisible=now-p.imageStart;
   if(p.imageDurable===null&&e&&durable&&!e.properties.localPending)p.imageDurable=now-p.imageStart;}
  p.timer=requestAnimationFrame(sample);};sample();return true;
})()"""

def stats(values):
    ordered=sorted(values)
    return {"n":len(ordered),"p50Ms":round(ordered[math.ceil(.5*len(ordered))-1],2),"p95Ms":round(ordered[math.ceil(.95*len(ordered))-1],2),"maxMs":round(ordered[-1],2)} if ordered else None

def run(output, samples):
    output.mkdir(parents=True,exist_ok=True)
    noise=Image.frombytes('RGB',(2000,2000),random.Random(910).randbytes(2000*2000*3))
    compressed=io.BytesIO();noise.save(compressed,'JPEG',quality=92)
    source=output/'synthetic-20-page-scan.pdf';writer=canvas.Canvas(str(source),pagesize=A4,pageCompression=1)
    for number in range(20):
        writer.drawImage(ImageReader(io.BytesIO(compressed.getvalue())),20,20,width=A4[0]-40,height=A4[1]-40)
        writer.drawString(35,A4[1]-35,f'SYNTHETIC PERFORMANCE PAGE {number+1}');writer.showPage()
    writer.save()
    image=output/'synthetic-image.png';Image.frombytes('RGB',(400,200),random.Random(912).randbytes(400*200*3)).save(image)
    assert source.stat().st_size<=10*1024*1024
    source_hash=hashlib.sha256((ROOT/'app.js').read_bytes()).hexdigest()
    report={"scope":"localhost_synthetic_sqlite_direct_upload","hostedNetworkMeasured":False,"physicalDevicesMeasured":False,"humanSSOVerified":False,
      "pdfPages":20,"pdfBytes":source.stat().st_size,"imageBytes":image.stat().st_size,"sourceAppSha256":source_hash,"samples":[],"summaries":[]}
    original=QuietAcceptanceHandler.send_head
    def head(handler):
        if urlparse(handler.path).path not in {'/','/index.html'}:return original(handler)
        data=(ROOT/'index.html').read_bytes().replace(b'<head>',b'<head>'+TELEMETRY.encode(),1)
        handler.send_response(200);handler.send_header('Content-Type','text/html; charset=utf-8');handler.send_header('Content-Length',str(len(data)));handler.end_headers();return io.BytesIO(data)
    executable=Path.home()/'Library/Caches/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell'
    with mock.patch.object(QuietAcceptanceHandler,'send_head',head),mock.patch.object(transport,'PLAYWRIGHT_BRIDGE',LATENCY_BRIDGE),mock.patch.dict(os.environ,{'EDOC_TEST_BROWSER_PATH':str(executable)}):
        Fixture.setUpClass();require_local_origin(Fixture.origin);browser=transport.LocalPlaywrightBrowser(Fixture.origin)
        try:
            auth=isolated_browser_session(Fixture,'staff')
            for device,width,height in [('desktop',1440,1000),('tablet',820,1000),('mobile',390,844)]:
                for sample in range(samples):
                    row={"device":device,"sample":sample+1};report['samples'].append(row)
                    print(json.dumps({**row,"stage":"start"}),flush=True)
                    browser.run('open',Fixture.origin+'/assets/favicon-32.png')
                    browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session',"+json.dumps(json.dumps(auth))+");true")
                    browser.run('set','viewport',str(width),str(height));browser.run('open',Fixture.origin+f'/?fluidperf={time.monotonic_ns()}#electronicSeal')
                    browser.until("window.__fixtureTiming?.appInteractiveMs&&document.querySelector('#uploadedSealApprovalCategorySelect')?.options.length>1&&!uploadedSealEditorRuntime.directoryLoading")
                    browser.run('fill','#uploadedSealApprovalCategorySelect-ts-control','合作意向書');browser.run('press','Enter')
                    browser.run('fill','#uploadedSealTitle',f'合成效能 {device} {sample+1}');browser.run('fill','#uploadedSealReason','隔離測試，不用印、不寄發。')
                    browser.evaluate(PAINT_PROBE+';true');browser.evaluate(INSTALL_PAINT_PROBE);browser.evaluate(PROBE)
                    browser.run('upload','#uploadedSealPdfInput',str(source))
                    browser.until("window.__latencyProbe.firstFrame!==null&&window.__fluidTiming.pdfDurable!==null",timeout=60)
                    row.update(browser.evaluate("({pdfFirstPaintMs:window.__latencyProbe.firstFrame.frameMs,pdfModelReadyMs:uploadedSealEditorRuntime.lastEditorReadyMs,pdfDurableMs:window.__fluidTiming.pdfDurable})"))
                    row['pdfFirstEditableMs']=max(row['pdfFirstPaintMs'],row['pdfModelReadyMs'])
                    browser.run('upload','#uploadedEditorImageInput',str(image))
                    browser.until("window.__fluidTiming.imageVisible!==null&&window.__fluidTiming.imageDurable!==null",timeout=45)
                    row.update(browser.evaluate("({imageFirstEditableMs:window.__fluidTiming.imageVisible,imageDurableMs:window.__fluidTiming.imageDurable})"))
                    browser.evaluate("document.querySelector('#uploadedEditorSvgLayer image').scrollIntoView({block:'center',behavior:'instant'});true")
                    point=browser.evaluate("(()=>{const r=document.querySelector('#uploadedEditorSvgLayer image').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
                    browser.run('mouse','move',str(point['x']),str(point['y']));browser.run('mouse','down')
                    assert browser.evaluate("Boolean(uploadedSealEditorRuntime.pointerAction)"),'pointer_not_started'
                    browser.evaluate("window.__fluidTiming.drag=[];window.__fluidTiming.fullRenders=0;window.__fluidTiming.dragRequestStart=window.__fluidTiming.requests.length;true")
                    for frame in range(12):browser.run('mouse','move',str(point['x']+10+frame),str(point['y']+6+frame))
                    browser.evaluate("new Promise(resolve=>requestAnimationFrame(()=>resolve(true)))")
                    row.update(browser.evaluate("({dragFrameMs:window.__fluidTiming.drag,fullSvgRendersDuringDrag:window.__fluidTiming.fullRenders,requestsDuringDrag:window.__fluidTiming.requests.length-window.__fluidTiming.dragRequestStart,errors:window.__fixtureErrors})"))
                    browser.run('mouse','up');browser.until("!uploadedSealEditorRuntime.saving&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration")
                    row['passed']=len(row['dragFrameMs'])>0 and row['fullSvgRendersDuringDrag']==0 and not row['errors']
                    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(row),flush=True)
                subset=[r for r in report['samples'] if r['device']==device]
                summary={"device":device}
                for key in ['pdfFirstEditableMs','pdfFirstPaintMs','pdfDurableMs','imageFirstEditableMs','imageDurableMs']:
                    summary[key]=stats([r[key] for r in subset])
                summary['dragFrameMs']=stats([v for r in subset for v in r['dragFrameMs']]);report['summaries'].append(summary)
            report['runtimeSourceUnchanged']=source_hash==hashlib.sha256((ROOT/'app.js').read_bytes()).hexdigest()
            report['passed']=all(r['passed'] for r in report['samples']) and report['runtimeSourceUnchanged']
        except Exception as error:
            report['errorCode']=str(error) if str(error).startswith('browser_') else type(error).__name__
            report['lastCommand']=browser.last_command
            try:report['failure']=browser.evaluate("({timing:window.__fluidTiming,paint:window.__latencyProbe?.firstFrame,status:document.querySelector('#uploadedEditorSaveStatus')?.textContent,uploading:uploadedSealEditorRuntime.uploading,finalizing:uploadedSealEditorRuntime.finalizingAsset,error:uploadedSealEditorRuntime.uploadRetry?true:false})")
            except Exception:pass
            report['passed']=False
        finally:
            browser.run('close');Fixture.tearDownClass();(output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--samples',type=int,default=10)
    args=parser.parse_args();raise SystemExit(0 if run(args.output.resolve(),args.samples)['passed'] else 1)
