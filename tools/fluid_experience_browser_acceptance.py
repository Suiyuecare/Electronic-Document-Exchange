"""Local-only six-page UX baseline and interaction acceptance.

Use --source-ref HEAD for an immutable before capture, then omit it to test
the working tree. Synthetic sessions never leave loopback or enter reports.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.six_role_browser_acceptance import Browser, ROUTES, VIEWPORTS, TELEMETRY, AUDIT_JS, require_local_origin
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as Fixture, QuietAcceptanceHandler

HIT_AREA_AUDIT_JS = """(()=>{
  const result=""" + AUDIT_JS + """;
  const visible=e=>e.getClientRects().length&&!e.closest('[hidden],.hidden,[inert]')&&getComputedStyle(e).visibility!=='hidden';
  const page=document.querySelector('.view.active');
  const controls=[...(page?.querySelectorAll('button,input:not([type=hidden]),select,textarea,a[href]')||[]),...document.querySelectorAll('.topbar button')].filter(visible);
  const hitTarget=e=>e.matches('input[type=checkbox],input[type=radio]')
    ? e.closest('label')||(e.id?document.querySelector('label[for="'+CSS.escape(e.id)+'"]'):null)||e : e;
  result.shortTargets=controls.map(e=>({control:e,target:hitTarget(e)})).filter(({target})=>{const r=target.getBoundingClientRect();return r.width<44||r.height<44}).map(({control:e,target})=>{
    const r=target.getBoundingClientRect();return {id:e.id,tag:e.tagName,type:e.type||'',text:(e.getAttribute('aria-label')||target.textContent||e.type||'').trim().slice(0,50),width:Math.round(r.width),height:Math.round(r.height),hitArea:target===e?'control':'label'};
  });
  result.smallInputs=controls.filter(e=>e.matches('input:not([type=checkbox]):not([type=radio]),select,textarea')&&parseFloat(getComputedStyle(e).fontSize)<16).map(e=>({id:e.id,fontSize:getComputedStyle(e).fontSize}));
  return result;
})()"""


def sources(ref):
    names = ("index.html", "app.js", "styles.css")
    if ref:
        sha = subprocess.check_output(["git", "rev-parse", ref], cwd=ROOT, text=True).strip()
        files = {name: subprocess.check_output(["git", "show", f"{sha}:{name}"], cwd=ROOT) for name in names}
        return sha, files
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    return sha + "+working-tree", {name: (ROOT / name).read_bytes() for name in names}


def navigate(browser, route, device):
    if device == "mobile":
        browser.run("click", "#mobileMenuButton")
        browser.until("Math.abs(document.querySelector('#primarySidebar').getBoundingClientRect().left)<0.5")
    browser.evaluate("""(()=>{
      window.__fluidNextNavigation=null;
      if(!window.__fluidCaptureInstalled){window.__fluidCaptureInstalled=true;
        document.addEventListener('click',event=>{
          const nav=event.target.closest('.sidebar .nav-item[data-target]');if(!nav)return;
          const start=performance.now(),route=nav.dataset.target;
          requestAnimationFrame(()=>{const view=document.querySelector('.view.active'),r=view?.getBoundingClientRect();
            window.__fluidNextNavigation={route,milliseconds:performance.now()-start,visible:!!view&&view.id===route&&r.width>0&&r.height>0};
          });
        },true);
      }return true;
    })()""")
    browser.run("click", f'.sidebar .nav-item[data-target="{route}"]')
    browser.until("document.querySelector('.view.active')?.id===" + json.dumps(route))
    browser.until("window.__fluidNextNavigation?.route===" + json.dumps(route))
    timing=browser.evaluate("window.__fluidNextNavigation")
    if not timing["visible"]: raise RuntimeError("local_route_paint_not_visible")
    return timing["milliseconds"]


def list_checks(browser):
    # No request or business mutation. Exercise the shipping renderers using
    # synthetic client-side rows, restoring every replaced function afterwards.
    return browser.evaluate("""(async()=>{
      const savedItems=officialWorkflowItems, savedPage={...officialWorkflowPage};
      const savedDownload=downloadElectronicSealFinalFile;
      const savedListRead=loadOfficialWorkflow,savedApprovalRead=loadApprovalProgressFromBackend,savedDashboardRead=loadDashboardOfficialWorkflow;
      const savedRecords=approvalLogRecords, savedFiltered=filteredApprovalLogRecords;
      const savedSelected=selectedWorkflowTaskId;
      const result={}; let finishDownload, calls=0;
      try {
        await loadOfficialWorkflow('all',{source:'editor'});
        loadOfficialWorkflow=async()=>{};loadApprovalProgressFromBackend=async()=>{};loadDashboardOfficialWorkflow=async()=>{};
        setView('electronicSeal');
        officialWorkflowItems=[{id:'UX-SYNTHETIC',title:'Synthetic final file',source_type:'uploaded_pdf',current_status:'stamped',can_download:true,stamped_file_id:'UX-FINAL',applicant_name:'Synthetic',company_name:'Synthetic Company'}];
        Object.assign(officialWorkflowPage,{loading:false,error:false,hasMore:true,query:{scope:'all'}});
        renderElectronicSealWorkQueue(); document.querySelector('#electronicSealWorkQueue').open=true;
        const list=document.querySelector('#electronicSealWorkQueueList');
        const action=list.querySelector('[data-electronic-seal-download]');
        action.focus(); const row=action.closest('article');
        renderElectronicSealWorkQueue(); renderElectronicSealWorkQueue();
        result.unchangedActionIdentity=list.querySelector('[data-electronic-seal-download]')===action&&document.activeElement===action;
        downloadElectronicSealFinalFile=()=>{calls++;return new Promise(resolve=>{finishDownload=resolve})};
        action.click(); await Promise.resolve();
        officialWorkflowItems[0].current_step_name='Updated synthetic status';
        renderElectronicSealWorkQueue();
        result.busyActionSurvives=list.querySelector('[data-electronic-seal-download]')===action&&action.disabled&&action.textContent==='準備下載…';
        action.click(); result.singleAction=calls===1;
        finishDownload(true); await new Promise(resolve=>setTimeout(resolve,0));
        result.busyRecovery=!action.disabled&&action.textContent==='下載用印後檔案';
        officialWorkflowItems.unshift({id:'UX-NEW',title:'Another synthetic case',source_type:'uploaded_pdf',current_status:'draft'});
        action.focus(); renderElectronicSealWorkQueue();
        result.reorderedFocus=document.activeElement===action&&row===action.closest('article');
        renderOfficialWorkflowPagination();
        const page=document.querySelector('#electronicSealPagination'),more=page.querySelector('[data-official-load-more]');
        more.focus(); officialWorkflowPage.loading=true;renderOfficialWorkflowPagination();
        result.paginationIdentity=page.querySelector('[data-official-load-more]')===more;
        officialWorkflowPage.loading=false;renderOfficialWorkflowPagination();
        result.paginationFocus=document.activeElement===more;
        setView('approvalLog');
        const record={task:{id:'UX-APPROVAL',title:'Synthetic approval',role:'Supervisor',step:'Review',status:'待簽核'},doc:{subject:'Synthetic approval'},steps:[],requester:'Synthetic',submittedAt:'2026-09-28'};
        approvalLogRecords=()=>[record];filteredApprovalLogRecords=()=>[record];selectedWorkflowTaskId='UX-APPROVAL';
        renderApprovalLog();
        const approval=document.querySelector('[data-approval-log-select="UX-APPROVAL"]');approval.focus();
        const evidence=document.querySelector('#approvalLogDetail details');if(evidence)evidence.open=true;
        renderApprovalLog(); result.approvalIdentity=document.activeElement===approval&&document.querySelector('[data-approval-log-select="UX-APPROVAL"]')===approval;
        record.task.status='已更新';renderApprovalLog();
        result.approvalChangedFocus=document.activeElement===approval;
        result.expandedEvidencePreserved=!evidence||evidence.open;
        officialWorkflowItems[1].can_download=false;setView('electronicSeal');renderElectronicSealWorkQueue();
        result.revokedDownloadRemoved=!document.querySelector('[data-electronic-seal-download="UX-FINAL"]');
      } finally {
        officialWorkflowItems=savedItems;Object.assign(officialWorkflowPage,savedPage);downloadElectronicSealFinalFile=savedDownload;
        approvalLogRecords=savedRecords;filteredApprovalLogRecords=savedFiltered;selectedWorkflowTaskId=savedSelected;
        loadOfficialWorkflow=savedListRead;loadApprovalProgressFromBackend=savedApprovalRead;loadDashboardOfficialWorkflow=savedDashboardRead;
        renderElectronicSealWorkQueue();renderApprovalLog();renderOfficialWorkflowPagination();
      }
      return result;
    })()""")


def shared_checks(browser, device):
    result = {}
    navigate(browser, "dashboard", device)
    navigate(browser, "settings", device)
    result["routeFocus"] = browser.evaluate("document.activeElement?.id==='pageTitle'&&!document.activeElement?.closest('[aria-hidden=true]')")
    result["scroll"] = browser.evaluate("""(()=>{
      const view=document.querySelector('#settings'),before=frontendSessionScope();
      const spacer=document.createElement('div');spacer.style.height='1400px';spacer.dataset.fluidFixture='true';view.append(spacer);
      view.scrollTop=Math.min(180,view.scrollHeight-view.clientHeight);const expected=view.scrollTop;
      setView('settings');const same=view.scrollTop===expected;
      setView('dashboard');setView('settings');const restored=view.scrollTop===expected;
      const saved=authState;authState={...authState,user:{...authState.user,id:'UX-OTHER-SESSION'}};
      const scopeChanged=before!==frontendSessionScope();
      setView('dashboard');setView('settings');const notReused=view.scrollTop===0;
      authState=saved;setView('dashboard');spacer.remove();return {same,restored,notReused,expected,scopeChanged};
    })()""")
    result["toast"] = browser.evaluate("""(async()=>{
      const toast=document.querySelector('#toast');showToast('Synthetic earlier');
      await new Promise(resolve=>setTimeout(resolve,250));showToast('Synthetic latest');
      await new Promise(resolve=>setTimeout(resolve,3800));
      const latestVisible=toast.classList.contains('show')&&toast.textContent==='Synthetic latest';
      await new Promise(resolve=>setTimeout(resolve,350));return {latestVisible,hiddenAfterOwnTimer:!toast.classList.contains('show')};
    })()""")
    result["headerStable"] = browser.evaluate("""(async()=>{
      updateHeaderStatus();let mutations=0;const observer=new MutationObserver(records=>{mutations+=records.length});
      observer.observe(document.querySelector('#topInfo'),{childList:true,characterData:true,subtree:true});
      for(let i=0;i<5;i++)updateHeaderStatus();await Promise.resolve();observer.disconnect();return mutations===0;
    })()""")
    if device == "mobile":
        browser.run("click", "#mobileMenuButton")
        browser.until("Math.abs(document.querySelector('#primarySidebar').getBoundingClientRect().left)<0.5")
        result["drawer"] = browser.evaluate("""(()=>{
          const controls=mobileNavigationFocusableItems(),first=controls[0],last=controls.at(-1);last.focus();
          last.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));const tabWrapped=document.activeElement===first;
          first.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}));const shiftWrapped=document.activeElement===last;
          last.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
          return {tabWrapped,shiftWrapped,closed:!document.body.classList.contains('mobile-navigation-open'),restored:document.activeElement?.id==='mobileMenuButton'};
        })()""")
    navigate(browser, "inbound", device)
    browser.evaluate("""(()=>{
      window.__fluidSavedInbound=[...inboundDocs];window.__fluidSavedContracts=[...contractRecords];
      inboundDocs.push({id:'UX-INBOUND',receiveNo:'SYNTHETIC-INBOUND',subject:'Synthetic local incoming document',status:'已收文',attachments:[],companyId:authState.user.company_id});
      contractRecords.push({id:'UX-CONTRACT',contractNo:'SYNTHETIC-CONTRACT',title:'Synthetic local contract',summary:'No business data',companyName:'Synthetic Company',companyId:authState.user.company_id,counterparty:'Synthetic',type:'合作意向書',amount:0,currency:'TWD',dept:'Synthetic',owner:'Synthetic',status:'草稿',attachments:[],confidentiality:'普通',sealRequirement:'None',storageStatus:'Local only'});
      return true;
    })()""")
    result["dialogs"] = []
    for kind, opener, closer, selector in (
        ("inbound", "openInboundModal('UX-INBOUND')", "closeInboundModal", "#inboundModal"),
        ("contract", "openContractModal('UX-CONTRACT')", "closeContractModal", "#contractModal"),
    ):
        result["dialogs"].append(browser.evaluate(f"""(()=>{{
          const origin=document.querySelector('#pageTitle');origin.focus();{opener};
          const dialog=document.querySelector({json.dumps(selector)}),focusInside=dialog.contains(document.activeElement);
          const controls=workspaceModalFocusableItems(dialog);
          const first=controls[0],last=controls.at(-1);last?.focus();document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{{key:'Tab',bubbles:true,cancelable:true}}));
          const tabWrapped=document.activeElement===first;first?.focus();document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}}));
          const shiftWrapped=document.activeElement===last;document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{{key:'Escape',bubbles:true,cancelable:true}}));
          const closed=dialog.classList.contains('hidden'),restored=document.activeElement===origin;
          if(!closed){closer}();return {{kind:{json.dumps(kind)},focusInside,tabWrapped,shiftWrapped,closed,restored}};
        }})()"""))
    result["rapidFocus"] = browser.evaluate("""(()=>{
      let passed=true;const heading=document.querySelector('#pageTitle');
      for(let i=0;i<8;i++){
        setView(i%2?'inbound':'settings');passed=passed&&document.activeElement===heading;
        openInboundModal('UX-INBOUND');passed=passed&&document.querySelector('#inboundModal').contains(document.activeElement);
        closeInboundModal();passed=passed&&document.activeElement===heading;
        openContractModal('UX-CONTRACT');passed=passed&&document.querySelector('#contractModal').contains(document.activeElement);
        closeContractModal();passed=passed&&document.activeElement===heading;
      }return passed;
    })()""")
    browser.evaluate("inboundDocs.splice(0,inboundDocs.length,...window.__fluidSavedInbound);contractRecords.splice(0,contractRecords.length,...window.__fluidSavedContracts);delete window.__fluidSavedInbound;delete window.__fluidSavedContracts;true")
    result["lists"] = list_checks(browser)
    return result


def run(args):
    args.output.mkdir(parents=True, exist_ok=True)
    source_sha, files = sources(args.source_ref)
    original = QuietAcceptanceHandler.send_head
    def static(handler):
        name = urlparse(handler.path).path.lstrip("/") or "index.html"
        if name in files:
            data = files[name]
            if name == "index.html": data = data.replace(b"<head>", b"<head>" + TELEMETRY.encode(), 1)
            handler.send_response(200)
            handler.send_header("Content-Type", {"index.html":"text/html; charset=utf-8","app.js":"application/javascript","styles.css":"text/css"}[name])
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            return io.BytesIO(data)
        return original(handler)
    report = {"scope":"isolated_loopback_synthetic_only", "sourceSHA":source_sha,"sourceDigests":{name:hashlib.sha256(data).hexdigest() for name,data in files.items()},"navigationTimingScope":"native capture click to visible active view next animation frame; excludes browser RPC and backend data completion", "pages":[], "checks":[],"accessibility":[]}
    with mock.patch.object(QuietAcceptanceHandler,"send_head",static):
        Fixture.setUpClass();require_local_origin(Fixture.origin)
        config=Path(Fixture.tmp.name)/"fluid-browser.json";config.write_text('{"headed":false}')
        browser=Browser(config,session="fluid",namespace="edoc-fluid")
        try:
            auth=isolated_browser_session(Fixture,"ceo")
            browser.run("open",Fixture.origin+"/assets/favicon-32.png")
            browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session',"+json.dumps(json.dumps(auth))+");true")
            for device in ("desktop","mobile"):
                w,h=VIEWPORTS[device];browser.run("set","viewport",str(w),str(h))
                browser.run("open",Fixture.origin+f"/?fluid={time.monotonic_ns()}#dashboard")
                browser.until("window.__fixtureTiming?.appInteractiveMs")
                for route in ROUTES:
                    duration=navigate(browser,route,device);time.sleep(.15)
                    row=browser.evaluate(HIT_AREA_AUDIT_JS);row.update(device=device,navigationMs=duration,screenshot=f"{device}-{route}.png")
                    browser.run("snapshot","-i")
                    browser.run("screenshot",str(args.output/row["screenshot"]),"--full");report["pages"].append(row)
                if not args.source_ref: report["checks"].append({"device":device,**shared_checks(browser,device)})
            if not args.source_ref:
                browser.run("set","media","light","reduced-motion")
                report["accessibility"].append({"reducedMotion":browser.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches"),"visibleAnimationsBounded":browser.evaluate("[...document.querySelectorAll('#appShell *')].filter(e=>e.getClientRects().length&&!e.closest('[hidden],.hidden')).every(e=>getComputedStyle(e).animationName==='none'||getComputedStyle(e).animationDuration.split(',').every(value=>parseFloat(value)<=0.01))")})
                browser.run("set","viewport","1440","1000")
                browser.evaluate("document.documentElement.style.zoom='2';setView('settings');true")
                time.sleep(.15)
                zoom=browser.evaluate(HIT_AREA_AUDIT_JS)
                browser.run("screenshot",str(args.output/"desktop-settings-200pct-layout-zoom.png"),"--full")
                report["accessibility"].append({"zoomKind":"actual CSS layout zoom, not native browser toolbar zoom","zoomFactor":2,"zoomNoOverflow":not zoom["overflow"],"zoomRouteVisible":browser.evaluate("document.querySelector('.view.active')?.id==='settings'&&document.querySelector('#settings').getBoundingClientRect().width>0"),"screenshot":"desktop-settings-200pct-layout-zoom.png"})
                browser.evaluate("document.documentElement.style.zoom='';true")
            return report
        finally:
            browser.run("close");Fixture.tearDownClass()


def comparison_boards(before, after):
    """Mechanical QA contact sheets; source screenshots are kept unchanged."""
    from PIL import Image, ImageDraw, ImageFont
    board_dir=after/'comparisons';board_dir.mkdir(parents=True,exist_ok=True)
    font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',22)
    paths=[]
    for route in ROUTES:
        board=Image.new('RGB',(1960,1660),'#f5f1e9');draw=ImageDraw.Draw(board)
        draw.text((24,12),f'{route} | immutable baseline vs working tree | synthetic local data',font=font,fill='#332b22')
        for column,(label,directory) in enumerate((('BEFORE',before),('AFTER',after))):
            x=20+column*970;draw.text((x,48),label+' - desktop',font=font,fill='#9b4c07')
            image=Image.open(directory/f'desktop-{route}.png').convert('RGB');image.thumbnail((940,670));board.paste(image,(x,80))
            draw.text((x,770),label+' - mobile',font=font,fill='#9b4c07')
            image=Image.open(directory/f'mobile-{route}.png').convert('RGB');image.thumbnail((390,844));board.paste(image,(x,805))
        destination=board_dir/f'{route}-before-after.png';board.save(destination);paths.append(str(destination))
    return paths


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--source-ref",default="")
    parser.add_argument("--compare-before",type=Path,help="Build six desktop/mobile before-after visual QA boards")
    args=parser.parse_args()
    with open('/tmp/edoc-fluid-browser.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);report=run(args)
    (args.output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
    failures=[]
    for row in report["pages"]:
        if row["overflow"] or row["errors"]:failures.append(row["device"]+":"+row["route"])
        if row.get("shortTargets"):failures.append(row["device"]+":"+row["route"]+":action-hit-area")
    for check in report["checks"]:
        checks={"routeFocus":check["routeFocus"],"headerStable":check["headerStable"],"rapidFocus":check["rapidFocus"]}
        checks.update({"scroll:"+k:v for k,v in check["scroll"].items() if k!="expected"})
        checks["scroll:nonzero"]=check["scroll"]["expected"]>0
        for group in ("toast","lists","drawer"):
            checks.update({group+":"+k:v for k,v in check.get(group,{}).items()})
        for dialog in check["dialogs"]:checks.update({dialog["kind"]+":"+k:v for k,v in dialog.items() if k!="kind"})
        failures.extend(check["device"]+":"+key for key,value in checks.items() if value is not True)
    for case in report["accessibility"]:
        failures.extend('accessibility:'+key for key in ('reducedMotion','visibleAnimationsBounded','zoomNoOverflow','zoomRouteVisible') if key in case and case[key] is not True)
    report['passed']=not failures;report['failures']=failures
    if args.compare_before:report['comparisonBoards']=comparison_boards(args.compare_before,args.output)
    (args.output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({"report":str(args.output/"report.json"),"sourceSHA":report["sourceSHA"],"screenshots":len(report["pages"]),"overflow":sum(row["overflow"] for row in report["pages"]),"failures":failures}))
    return int(bool(failures))


if __name__=="__main__":raise SystemExit(main())
