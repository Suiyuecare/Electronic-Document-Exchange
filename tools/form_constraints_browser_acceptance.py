"""Exercise the shipping constraints boundary on real product form DOM.

Synthetic local sessions only; no real SSO, email or government exchange.
The valid-submit count proves one event reaches the existing form handlers;
it does not claim the downstream domain workflow or external delivery passed.
"""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as Fixture, QuietAcceptanceHandler
from tests.support.five_account_browser_fixture import isolated_browser_session
from tools.six_role_browser_acceptance import TELEMETRY, require_local_origin
from tools.ux_complete_browser_acceptance import BRIDGE
import tools.backup_drill_browser_acceptance as transport


def run(output: Path) -> dict:
    output = output.resolve(); output.mkdir(parents=True, exist_ok=True)
    original = QuietAcceptanceHandler.send_head
    document = (ROOT / "index.html").read_bytes().replace(b"<head>", b"<head>" + TELEMETRY.encode(), 1)
    def head(handler):
        if urlparse(handler.path).path not in {"/", "/index.html"}: return original(handler)
        handler.send_response(200); handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(document))); handler.end_headers(); return io.BytesIO(document)
    headless = Path.home() / "Library/Caches/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell"
    env = {"EDOC_TEST_BROWSER_PATH": str(headless)} if headless.is_file() else {}
    report = {"scope": "local_synthetic_constraints_boundary", "humanSSOVerified": False,
              "physicalDeviceVerified": False, "governmentExchange": "DISABLED", "domainWorkflowVerified": False,
              "sourceAppSha256": hashlib.sha256((ROOT / "app.js").read_bytes()).hexdigest(), "cases": []}
    browser = None
    with mock.patch.object(QuietAcceptanceHandler, "send_head", head), mock.patch.object(transport, "PLAYWRIGHT_BRIDGE", BRIDGE), mock.patch.dict(os.environ, env):
        Fixture.setUpClass(); require_local_origin(Fixture.origin)
        try:
            browser = transport.LocalPlaywrightBrowser(Fixture.origin)
            auth = isolated_browser_session(Fixture, "ceo")
            for device, width, height in (("desktop", 1440, 1000), ("tablet", 900, 1100), ("phone", 390, 844)):
                for route, form_id, field_id in (("compose", "composeForm", "dispatchDate"),
                    ("electronicSeal", "uploadedSealForm", "uploadedSealTitle"),
                    ("inbound", "inboundArchiveForm", "inboundArchiveSenderName"),
                    ("settings", "notificationForm", "notificationTarget")):
                    label = f"{device}-{route}"
                    browser.run("open", Fixture.origin + "/assets/favicon-32.png")
                    browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                    browser.run("set", "viewport", str(width), str(height))
                    browser.run("open", Fixture.origin + f"/?constraints={time.monotonic_ns()}#{route}")
                    browser.until("window.__fixtureTiming?.appInteractiveMs&&typeof validateWorkspaceForm==='function'", timeout=40)
                    browser.until("!uploadedSealEditorRuntime.directoryLoading&&document.querySelector('#uploadedSealApprovalCategorySelect')?.options.length>1", timeout=40)
                    if route == "inbound": browser.evaluate("setInboundSection('archive',{load:false});true")
                    if route == "settings":
                        browser.evaluate("(()=>{const parents=[];for(let p=document.querySelector('#notificationForm').parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')parents.unshift(p);parents.forEach(p=>p.open=true);return true})()")
                        browser.until("document.querySelector('#notificationTarget').getClientRects().length>0")
                    script = r"""(()=>{
                      const form=document.getElementById(FORM),field=document.getElementById(FIELD);
                      window.__constraintForm=form;window.__constraintField=field;window.__constraintEvents=0;window.__constraintMutations=[];
                      const originalFetch=window.fetch;window.fetch=(...args)=>{
                        const method=String(args[1]?.method||args[0]?.method||'GET').toUpperCase();
                        const path=new URL(args[0]?.url||String(args[0]),location.href).pathname;
                        if(!['GET','HEAD'].includes(method)&&!path.includes('ui-usage'))window.__constraintMutations.push({method,path});
                        return originalFetch(...args);
                      };
                      form.addEventListener('submit',()=>{window.__constraintEvents++},{capture:true});
                      for(const control of form.elements){
                        if(!control.matches('input,select,textarea')||control.disabled||control.readOnly||control.willValidate===false)continue;
                        if(control.tagName==='SELECT')control.value=[...control.options].find(e=>e.value&&!e.disabled)?.value||control.value;
                        else if(control.type==='checkbox'||control.type==='radio')control.checked=true;
                        else if(control.type==='date')control.value='2026-10-12';
                        else if(control.type==='number')control.value=control.min||'1';
                        else if(control.type==='email')control.value='synthetic@example.invalid';
                        else if(control.id==='contactPhone')control.value='02-66045432 #31';
                        else if(control.required)control.value='Synthetic constraints acceptance';
                      }
                      field.value='';field.dispatchEvent(new Event('input',{bubbles:true}));
                      form.requestSubmit();
                      return {noValidate:form.noValidate,invalidZeroDispatch:window.__constraintEvents===0,
                        inlineError:field.getAttribute('aria-invalid')==='true'&&!!document.getElementById(field.getAttribute('aria-describedby')?.split(' ').at(-1)),
                        firstInvalidFocused:document.activeElement===field,valuePreserved:field.value===''};
                    })()""".replace("FORM", json.dumps(form_id)).replace("FIELD", json.dumps(field_id))
                    row = {"case": label, **browser.evaluate(script)}
                    browser.run("screenshot", str(output / f"{label}-invalid.png"))
                    row["invalidZeroMutationRequests"] = browser.evaluate("window.__constraintMutations.length===0")
                    browser.evaluate("window.__constraintField.value=window.__constraintField.type==='date'?'2026-10-12':window.__constraintField.type==='email'?'synthetic@example.invalid':'Synthetic valid field';window.__constraintField.dispatchEvent(new Event('input',{bubbles:true}));window.__constraintField.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));window.__constraintForm.requestSubmit();true")
                    row["imeZeroDispatch"] = browser.evaluate("window.__constraintEvents===0")
                    row["imeZeroMutationRequests"] = browser.evaluate("window.__constraintMutations.length===0")
                    browser.evaluate("window.__constraintField.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));true")
                    row["recoveryClearsSharedError"] = browser.evaluate("window.__constraintField.getAttribute('aria-invalid')!=='true'&&!window.__constraintForm.querySelector(':scope > .workspace-form-errors')?.getClientRects().length")
                    browser.evaluate("window.__constraintForm.requestSubmit();true")
                    row["validOneHandlerDispatch"] = browser.evaluate("window.__constraintEvents===1")
                    row["noPageOverflow"] = browser.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                    row["handoverDefaultOff"] = browser.evaluate("!officialHandoverFeatureEnabled()&&!document.querySelector('#officialHandoverPanel')?.getClientRects().length")
                    row["passed"] = all(value is True for key, value in row.items() if key != "case")
                    report["cases"].append(row)
                    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
                    print(json.dumps(row, ensure_ascii=False), flush=True)
                    if not row["passed"]: raise RuntimeError("constraints_acceptance_failed")
        finally:
            try:
                if browser:
                    try: browser.run("close")
                    except RuntimeError: browser._stop()
            finally: Fixture.tearDownClass()
    report["passed"] = all(row["passed"] for row in report["cases"])
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)); return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); raise SystemExit(0 if run(args.output)["passed"] else 1)
