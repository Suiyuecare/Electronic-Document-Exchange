"""Actual backup confirmation/HTTP UI on disposable local synthetic data.

Blocked and delayed server responses are explicit fault injections. The success
case executes the shipping SQLite restore drill; it proves no hosted/offsite DR.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import select
import subprocess
import sys
import threading
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend
from tools.six_role_browser_acceptance import Browser, VIEWPORTS, require_local_origin
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as Fixture


# Reuse the shipping acceptance steps, but keep one Playwright connection for
# all keyboard/evaluate commands. The native agent-browser daemon intermittently
# stalls even on a DOM read after IME Escape and then captures a black frame.
# This is test transport only: it neither changes the page nor relaxes assertions.
PLAYWRIGHT_BRIDGE = r"""
const {createRequire}=require('node:module');
const {createInterface}=require('node:readline');
const {chromium}=createRequire(process.argv[1])('playwright');
const origin=process.argv[2], executablePath=process.argv[3];
let browser, page;
const send=value=>process.stdout.write(JSON.stringify(value)+'\n');
async function start(){
  browser=await chromium.launch({headless:true,executablePath});
  const context=await browser.newContext();
  // Abort every non-fixture request, including redirects and third-party fonts.
  await context.route('**/*',route=>{
    const url=new URL(route.request().url());
    return url.origin===origin||['data:','blob:'].includes(url.protocol)
      ?route.continue():route.abort();
  });
  page=await context.newPage();
  page.setDefaultTimeout(10000);
}
async function execute(message){
  const [command,...args]=message.args;
  if(command==='open'){
    if(new URL(args[0]).origin!==origin)throw Error('local_fixture_only');
    await page.goto(args[0],{waitUntil:'domcontentloaded',timeout:15000});
  }else if(command==='eval')return page.evaluate(message.script);
  else if(command==='set'&&args[0]==='viewport')await page.setViewportSize({width:Number(args[1]),height:Number(args[2])});
  else if(command==='click')await page.locator(args[0]).click();
  else if(command==='fill')await page.locator(args[0]).fill(args[1]);
  else if(command==='press')await page.keyboard.press(args[0]);
  else if(command==='screenshot')await page.screenshot({path:args[0],timeout:10000});
  else if(command==='close')await browser.close();
  else throw Error('unsupported_command');
  return null;
}
(async()=>{
  try{await start();send({success:true,ready:true});}
  catch{send({success:false,errorCode:'browser_launch_failed'});process.exitCode=1;return;}
  for await(const line of createInterface({input:process.stdin,crlfDelay:Infinity})){
    let message;
    try{message=JSON.parse(line);}catch{send({success:false,errorCode:'browser_invalid_command'});continue;}
    let timer;
    try{
      const data=await Promise.race([execute(message),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('deadline')),20000);})]);
      send({success:true,data});
    }catch{send({success:false,errorCode:'browser_command_failed'});}
    finally{clearTimeout(timer);}
    if(message.args[0]==='close')break;
  }
  await browser.close().catch(()=>{});
})().catch(()=>{send({success:false,errorCode:'browser_transport_failed'});process.exitCode=1;});
"""


class LocalPlaywrightBrowser(Browser):
    """Bounded, stdin-only transport; synthetic auth never enters CLI arguments."""

    def __init__(self, origin: str):
        require_local_origin(origin)
        runtime = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/package.json"
        executable = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        # createRequire uses this package anchor even when the runtime ships
        # only node_modules; verify the real installed dependency, not the anchor.
        if not (runtime.parent / "node_modules/playwright/package.json").is_file() or not executable.is_file():
            raise RuntimeError("browser_local_runtime_unavailable")
        self.last_command = "launch"
        self.process = subprocess.Popen(
            ["node", "-e", PLAYWRIGHT_BRIDGE, str(runtime), origin, str(executable)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1,
        )
        try:
            self._receive()
        except Exception:
            self._stop()
            self.process.stdin.close()
            self.process.stdout.close()
            raise

    def _receive(self):
        if not select.select([self.process.stdout], [], [], 30)[0]:
            self._stop()
            raise RuntimeError("browser_command_timeout:" + self.last_command)
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("browser_transport_closed:" + self.last_command)
        try:
            payload = json.loads(line)
        except (ValueError, TypeError):
            raise RuntimeError("browser_invalid_response:" + self.last_command) from None
        if payload.get("success") is not True:
            raise RuntimeError("browser_command_failed:" + self.last_command)
        return payload.get("data")

    def _stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def run(self, *args, script=None):
        self.last_command = args[0]
        if self.process.poll() is not None:
            raise RuntimeError("browser_transport_closed:" + self.last_command)
        self.process.stdin.write(json.dumps({"args": args, "script": script}) + "\n")
        self.process.stdin.flush()
        try:
            return self._receive()
        finally:
            if args[0] == "close":
                self._stop()
                self.process.stdin.close()
                self.process.stdout.close()


def run(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    Fixture.setUpClass()
    require_local_origin(Fixture.origin)
    browser = None
    report = {"scope": "isolated_synthetic_browser_http", "hostedRestoreVerified": False,
              "offsiteRestoreVerified": False, "humanSSOVerified": False,
              "browserTransport": "persistent_local_playwright", "externalRequestsAllowed": False, "cases": []}
    actual_drill = backend.run_backup_restore_drill
    mode = {"value": "blocked", "calls": 0}
    release = threading.Event()

    def drill(conn, payload):
        mode["calls"] += 1
        if mode["value"] == "success":
            return actual_drill(conn, payload)
        if mode["value"] == "delayed" and not release.wait(30):
            raise RuntimeError("synthetic_delay_not_released")
        return {"id": "DRILL-SYNTHETIC-BLOCKED", "ok": False, "blocked": True, "result": "blocked",
                "created_at": "2026-10-08 00:00:00", "scope": payload["scope"], "target_env": payload["target_env"],
                "checks": {"database_restored": False, "storage_restored": False, "hash_match": False}}

    def confirm():
        original_stage = report["stage"]
        report["stage"] = original_stage + ":open_confirmation"
        browser.click_visible("#backupDrillRunBtn")
        browser.until("!document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')")
        if browser.evaluate("document.activeElement.id") != "workspaceTypedConfirmCancelBtn":
            raise AssertionError("confirmation_default_focus_not_cancel")
        report["stage"] = original_stage + ":type_confirmation"
        browser.run("fill", "#workspaceTypedConfirmInput", "確認演練")
        browser.until("!document.querySelector('#workspaceTypedConfirmSubmitBtn').disabled")
        report["stage"] = original_stage + ":submit_confirmation"
        browser.click_visible("#workspaceTypedConfirmSubmitBtn")
        report["stage"] = original_stage + ":wait_result"

    try:
        browser = LocalPlaywrightBrowser(Fixture.origin)
        with mock.patch.object(backend, "run_backup_restore_drill", side_effect=drill):
            for device in ("desktop", "mobile"):
                report["stage"] = device + ":opening_isolated_fixture"
                auth = isolated_browser_session(Fixture, "ceo", entity_id="E1")
                browser.run("open", Fixture.origin + "/assets/favicon-32.png")
                browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                browser.run("set", "viewport", *map(str, VIEWPORTS[device]))
                browser.run("open", Fixture.origin + "/#complianceOps")
                browser.until("typeof hasAuthenticatedBackendSession==='function'&&hasAuthenticatedBackendSession()&&!document.querySelector('#moduleEntryProgress')?.getClientRects().length")
                browser.until("document.querySelector('#backupDrillRunBtn').getClientRects().length>0")
                report["stage"] = device + ":confirmation_keyboard_and_ime"
                # Escape preserves values, does not dispatch, and restores focus.
                for trigger in ("backupDrillRunBtn", "complianceDrillBtn"):
                    before = mode["calls"]
                    browser.click_visible("#" + trigger)
                    browser.until("!document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')")
                    for _ in range(6):
                        browser.run("press", "Tab")
                        if not browser.evaluate("document.querySelector('#workspaceTypedConfirmModal').contains(document.activeElement)"):
                            raise AssertionError("confirmation_keyboard_focus_escaped")
                    browser.evaluate("(()=>{const input=document.querySelector('#workspaceTypedConfirmInput');input.focus();input.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));input.value='確認演練';input.dispatchEvent(new Event('input',{bubbles:true}));return true})()")
                    if not browser.evaluate("document.querySelector('#workspaceTypedConfirmSubmitBtn').disabled"):
                        raise AssertionError("ime_composition_enabled_submit")
                    browser.run("press", "Escape")
                    if browser.evaluate("document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')"):
                        raise AssertionError("ime_escape_closed_confirmation")
                    browser.evaluate("document.querySelector('#workspaceTypedConfirmInput').dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));true")
                    browser.run("press", "Escape")
                    browser.until("document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')&&!backupRestoreDrillPending")
                    if mode["calls"] != before or browser.evaluate("document.activeElement.id") != trigger:
                        raise AssertionError("cancel_dispatched_or_focus_not_restored")

                mode["value"] = "success"
                report["stage"] = device + ":local_restore"
                confirm()
                browser.until("!backupRestoreDrillPending&&latestBackupDrill?.passed===true", timeout=45)
                saved_date = browser.evaluate("complianceLastDrill")
                saved_count = browser.evaluate("opsBackups.length")
                if saved_count != 1:
                    raise AssertionError("real_local_snapshot_not_recorded_once")
                report["stage"] = device + ":capture_success"
                browser.run("screenshot", str(output / (device + "-success.png")))

                mode["value"] = "delayed"
                report["stage"] = device + ":blocked_http_503"
                # Exercise the shipping HTTP 503 handler rather than resolving
                # a stubbed backendRequest with an impossible success status.
                browser.evaluate("(()=>{const original=window.fetch;window.fetch=async (...args)=>{const r=await original(...args);if(String(args[0]).endsWith('/backup/restore-drill')&&r.ok){const data=await r.clone().json();if(data.blocked===true)return new Response(JSON.stringify(data),{status:503,headers:{'Content-Type':'application/json'}})}return r};return true})()")
                release.clear()
                before = mode["calls"]
                confirm()
                browser.until("backupRestoreDrillPending&&document.querySelector('#backupDrillRunBtn').disabled")
                browser.evaluate("void runBackupRestoreDrill();true")
                release.set()
                browser.until("!backupRestoreDrillPending&&latestBackupDrill?.blocked===true")
                if mode["calls"] != before + 1:
                    raise AssertionError("duplicate_backup_request")
                if browser.evaluate("opsBackups.length") != saved_count or browser.evaluate("complianceLastDrill") != saved_date:
                    raise AssertionError("blocked_attempt_counted_as_success")
                state = browser.evaluate("({summary:document.querySelector('#backupDrillSummaryGrid').textContent,green:document.querySelectorAll('#backupDrillStepList .ok').length,overflow:document.documentElement.scrollWidth>innerWidth+1,focus:document.activeElement.id})")
                if state["green"] or state["overflow"] or "未量測" not in state["summary"] or "已阻擋" not in state["summary"]:
                    raise AssertionError("blocked_status_or_layout_incorrect")
                if state["focus"] != "backupDrillRunBtn":
                    raise AssertionError("result_focus_not_restored")
                report["stage"] = device + ":capture_blocked"
                browser.run("screenshot", str(output / (device + "-blocked.png")))
                report["cases"].append({"device": device, "passed": True, "cancelNoRequest": True,
                                         "localRestorePassed": True, "blockedNoSuccess": True,
                                         "duplicatePrevented": True, "keyboardFocusPreserved": True, "overflow": False})
                print(json.dumps(report["cases"][-1]), flush=True)
    except Exception as error:
        report["errorCode"] = str(error) if isinstance(error, AssertionError) or (isinstance(error, RuntimeError) and str(error).startswith("browser_")) else type(error).__name__
        if browser is not None:
            report["lastBrowserCommand"] = browser.last_command
        try:
            if browser is not None:
                browser.run("screenshot", str(output / "failure.png"))
        except Exception:
            pass
    finally:
        release.set()
        try:
            if browser is not None:
                browser.run("close")
        except Exception:
            report["cleanupErrorCode"] = "isolated_browser_cleanup_failed"
        finally:
            Fixture.tearDownClass()
    report["passed"] = len(report["cases"]) == 2 and not report.get("errorCode")
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(0 if run(parser.parse_args().output.resolve())["passed"] else 1)
