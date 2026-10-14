"""Read-only local browser evidence for visible enabled button event owners.

An ancestor listener is only a candidate delegation owner. This audit does
not inspect handler contents, click mutations, prove a selector matches, or
supersede a static audit/complete functional acceptance. All identities are
synthetic, the application source is unchanged, and external requests abort.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import secrets
import stat
import sys
import time
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as Fixture, QuietAcceptanceHandler
from tests.support.five_account_browser_fixture import BROWSER_ROLES, isolated_browser_session
from tools.six_role_browser_acceptance import TELEMETRY, ROUTES, require_local_origin
from tools.ux_complete_browser_acceptance import BRIDGE
from tools.complete_role_flow_acceptance import loopback_only, source_digest
import tools.backup_drill_browser_acceptance as transport


INSTRUMENT = r"""<script>
(()=>{
 const owners=new WeakMap(),add=EventTarget.prototype.addEventListener,remove=EventTarget.prototype.removeEventListener;
 const capture=options=>typeof options==='boolean'?options:!!options?.capture;
 EventTarget.prototype.addEventListener=function(type,listener,options){
  const result=add.call(this,type,listener,options);
  if(listener&&!options?.signal?.aborted){
   let types=owners.get(this);if(!types)owners.set(this,types=new Map());
   let records=types.get(type);if(!records)types.set(type,records=[]);
   const cap=capture(options);
   if(!records.some(r=>r.listener===listener&&r.capture===cap))records.push({listener,capture:cap,once:!!options?.once,signal:options?.signal});
  }
  return result;
 };
 EventTarget.prototype.removeEventListener=function(type,listener,options){
  const result=remove.call(this,type,listener,options),types=owners.get(this),records=types?.get(type),cap=capture(options);
  if(records)types.set(type,records.filter(r=>r.listener!==listener||r.capture!==cap));
  return result;
 };
 // Only expose types/counts. Handler references stay in the private WeakMap.
 Object.defineProperty(window,'__buttonBindingCount',{value:(target,type)=>owners.get(target)?.get(type)?.filter(r=>!r.once&&!r.signal?.aborted).length||0});
 // A once listener may already have fired. Do not wrap the original callback
 // or claim this lifecycle is live; only retain a separate candidate count.
 Object.defineProperty(window,'__buttonBindingUnknownLifecycleCount',{value:(target,type)=>owners.get(target)?.get(type)?.filter(r=>r.once&&!r.signal?.aborted).length||0});
})();
</script>"""

AUDIT = r"""(()=>{
 const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden'&&!e.closest('[hidden],.hidden,[aria-hidden="true"]');
 const page=document.querySelector('.view.active');
 const candidates=[...(page?.querySelectorAll('button')||[]),...document.querySelectorAll('.topbar button,.sidebar button,.mobile-bottom-nav button')];
 const buttons=[...new Set(candidates)].filter(e=>visible(e)&&!e.disabled&&!e.matches(':disabled')&&e.getAttribute('aria-disabled')!=='true'&&!e.closest('[inert]'));
 const bound=(target,type)=>window.__buttonBindingCount(target,type)>0||typeof target?.['on'+type]==='function';
 const unknown=(target,type)=>(window.__buttonBindingUnknownLifecycleCount?.(target,type)||0)>0;
 const tag=e=>e===document?'document':e===window?'window':e.tagName?.toLowerCase()||'unknown';
 const safeId=(e,index)=>/^[a-zA-Z][a-zA-Z0-9_-]{0,120}$/.test(e.id)?e.id:'anonymous-button-'+(index+1);
 const rows=buttons.map((button,index)=>{
  const form=button.form,type=button.type;
  const directClick=bound(button,'click');
  const directSubmit=type==='submit'&&!!form&&bound(form,'submit');
  const nativeReset=type==='reset'&&!!form;
  const popoverTarget=document.getElementById(button.getAttribute('popovertarget')||'');
  const action=button.getAttribute('popovertargetaction')||'toggle';
  const nativePopover=!!popoverTarget?.hasAttribute('popover')&&typeof popoverTarget.showPopover==='function'&&typeof popoverTarget.hidePopover==='function'&&['toggle','show','hide'].includes(action);
  const ancestors=[];for(let node=button.parentNode;node;node=node.parentNode)ancestors.push(node);ancestors.push(window);
  const delegatedClickOwners=ancestors.filter(n=>bound(n,'click')).map(tag);
  const submitAncestors=[];if(type==='submit'&&form){for(let n=form.parentNode;n;n=n.parentNode)submitAncestors.push(n);submitAncestors.push(window);}
  const delegatedSubmitOwners=submitAncestors.filter(n=>bound(n,'submit')).map(tag);
  const unknownClickLifecycleOwners=[button,...ancestors].filter(n=>unknown(n,'click')).map(tag);
  const unknownSubmitLifecycleOwners=(type==='submit'&&form?[form,...submitAncestors]:[]).filter(n=>unknown(n,'submit')).map(tag);
  const direct=directClick||directSubmit||nativeReset||nativePopover;
  const delegated=!!(delegatedClickOwners.length||delegatedSubmitOwners.length);
  return {id:safeId(button,index),type,directClick,directSubmit,nativeReset,nativePopover,
    delegatedClickOwners,delegatedSubmitOwners,unknownClickLifecycleOwners,unknownSubmitLifecycleOwners,
    classification:direct?'direct_or_native':delegated?'delegation_candidate_only':(unknownClickLifecycleOwners.length||unknownSubmitLifecycleOwners.length)?'unknown_lifecycle_candidate_only':'no_observed_owner'};
 });
 return {activeRoute:page?.id||'',visibleEnabledButtonCount:rows.length,rows,errorCount:window.__fixtureErrors?.length||0};
})()"""


class ReportOutput:
    """Private openat output with no existing-file overwrite or link following."""
    def __init__(self, output):
        self.path=Path(os.path.abspath(Path(output).expanduser()))
        if self.path.is_relative_to(ROOT.resolve()):
            raise ValueError("button_audit_output_must_be_outside_repository")
        self.fd=os.open(self.path.anchor,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        self.report_identity=None
        try:
            for part in self.path.parts[1:]:
                try:child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=self.fd)
                except FileNotFoundError:
                    os.mkdir(part,0o700,dir_fd=self.fd)
                    child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=self.fd)
                os.close(self.fd);self.fd=child
            info=os.fstat(self.fd)
            if info.st_uid!=os.getuid() or info.st_mode&0o077:
                raise ValueError("button_audit_output_must_be_private_owned_directory")
            self.check_slot()
        except BaseException:
            os.close(self.fd);self.fd=None
            raise

    def check_slot(self):
        try:info=os.stat("report.json",dir_fd=self.fd,follow_symlinks=False)
        except FileNotFoundError:
            if self.report_identity is not None:raise ValueError("button_audit_report_changed")
            return
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_nlink!=1):
            raise ValueError("button_audit_report_link_or_permissions_invalid")
        if self.report_identity is None:raise ValueError("button_audit_report_already_exists")
        if (info.st_dev,info.st_ino)!=self.report_identity:raise ValueError("button_audit_report_changed")

    def write(self, report):
        self.check_slot()
        temporary=".report-"+secrets.token_hex(12)+".tmp"
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=self.fd)
        try:
            with os.fdopen(fd,"wb") as stream:
                stream.write(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False).encode())
                stream.flush();os.fsync(stream.fileno())
            self.check_slot()
            os.replace(temporary,"report.json",src_dir_fd=self.fd,dst_dir_fd=self.fd)
            info=os.stat("report.json",dir_fd=self.fd,follow_symlinks=False)
            self.report_identity=(info.st_dev,info.st_ino)
            self.check_slot();os.fsync(self.fd)
        finally:
            try:os.unlink(temporary,dir_fd=self.fd)
            except FileNotFoundError:pass

    def __enter__(self):return self
    def __exit__(self,*_):os.close(self.fd);self.fd=None


def run(output: Path) -> dict:
    with ReportOutput(output) as report_output:
        return run_guarded(report_output)


def run_guarded(report_output) -> dict:
    output=report_output.path
    if output.is_relative_to(ROOT.resolve()):
        raise ValueError("button_audit_output_must_be_outside_repository")
    source_before=source_digest()
    commit=subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,text=True,capture_output=True,check=True).stdout.strip()
    report={"schema_version":1,"scope":"isolated_synthetic_readonly_button_binding_audit",
        "candidate_commit":commit,"source_app_sha256":hashlib.sha256((ROOT/"app.js").read_bytes()).hexdigest(),
        "government_exchange":"DISABLED","production_accounts_changed":False,"real_human_sso_verified":False,
        "physical_device_verified":False,"external_requests_allowed":False,"mutating_buttons_clicked":False,
        "functional_click_coverage":False,"static_audit_superseded":False,
        "delegation_is_only_candidate_not_selector_proof":True,"unknown_listener_lifecycle_is_not_active_owner":True,
        "listener_callbacks_wrapped":False,"promotion_authorized":False,"cases":[]}
    document=(ROOT/"index.html").read_bytes().replace(b"<head>",b"<head>"+INSTRUMENT.encode()+TELEMETRY.encode(),1)
    original=QuietAcceptanceHandler.send_head
    def head(handler):
        if urlparse(handler.path).path not in {"/","/index.html"}:return original(handler)
        handler.send_response(200);handler.send_header("Content-Type","text/html; charset=utf-8")
        handler.send_header("Content-Length",str(len(document)));handler.end_headers();return io.BytesIO(document)
    shell=Path.home()/"Library/Caches/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell"
    env={"EDOC_TEST_BROWSER_PATH":str(shell)} if shell.is_file() else {}
    browser=None
    with mock.patch.object(QuietAcceptanceHandler,"send_head",head),mock.patch.object(transport,"PLAYWRIGHT_BRIDGE",BRIDGE),mock.patch.dict(os.environ,env),loopback_only():
        Fixture.setUpClass()
        try:
            require_local_origin(Fixture.origin)
            browser=transport.LocalPlaywrightBrowser(Fixture.origin)
            browser.run("set","viewport","1440","1000")
            for role in BROWSER_ROLES:
                auth=isolated_browser_session(Fixture,role)
                browser.run("open",Fixture.origin+"/assets/favicon-32.png")
                browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session',"+json.dumps(json.dumps(auth))+");true")
                browser.run("open",Fixture.origin+f"/?bindings={time.monotonic_ns()}#dashboard")
                browser.until("window.__fixtureTiming?.appInteractiveMs&&typeof window.__buttonBindingCount==='function'",timeout=40)
                browser.until("!uploadedSealEditorRuntime.directoryLoading",timeout=40)
                for route in ROUTES:
                    exposed=browser.evaluate("(()=>{const e=document.querySelector('.sidebar .nav-item[data-target="+json.dumps(route)+"]');return !!e&&e.getClientRects().length>0&&!e.disabled})()")
                    if not exposed:
                        report["cases"].append({"role":role,"route":route,"access":"not_exposed_by_role"});continue
                    browser.evaluate("setView("+json.dumps(route)+");true")
                    browser.until("document.querySelector('.view.active')?.id==="+json.dumps(route),timeout=20)
                    row={"role":role,"route":route,"access":"exposed",**browser.evaluate(AUDIT)}
                    report["cases"].append(row)
                    report_output.write(report)
                    print(json.dumps({"role":role,"route":route,"buttons":row["visibleEnabledButtonCount"],
                        "no_observed_owner":sum(item["classification"]=="no_observed_owner" for item in row["rows"])}),flush=True)
        finally:
            try:
                if browser:
                    try:browser.run("close")
                    except RuntimeError:browser._stop()
            finally:Fixture.tearDownClass()
    rows=[(case,item) for case in report["cases"] for item in case.get("rows",[])]
    report["totals"]={"role_route_cases":len(report["cases"]),"exposed_cases":sum(c["access"]=="exposed" for c in report["cases"]),
        "visible_button_observations":len(rows),
        **{kind:sum(item["classification"]==kind for _,item in rows) for kind in ("direct_or_native","delegation_candidate_only","unknown_lifecycle_candidate_only","no_observed_owner")}}
    report["unowned"]=[{"role":case["role"],"route":case["route"],"id":item["id"],"type":item["type"]}
                       for case,item in rows if item["classification"]=="no_observed_owner"]
    report["source_sha256_before"]=source_before;report["source_sha256_after"]=source_digest()
    report["source_unchanged"]=source_before==report["source_sha256_after"]
    report_output.write(report)
    print(json.dumps({"totals":report["totals"],"unowned":report["unowned"],"source_unchanged":report["source_unchanged"]}),flush=True)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();report=run(args.output)
    raise SystemExit(0 if report["source_unchanged"] and not report["unowned"] else 1)
