"""Synthetic two-request cookie race through real HTTP and Chromium's cookie jar.

The first anonymous response is delayed until a fixture installs a new handoff.
No JS cookie/token injection, auth function replacement or production requests.
"""
from __future__ import annotations

import argparse
import ast
import io
import json
from pathlib import Path
import subprocess
import sys
import textwrap
import threading
import time
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend
from tools.six_role_browser_acceptance import Browser, require_local_origin
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler


def run(output: Path, baseline: str | None = None):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    fixture = FiveAccountHttpAcceptanceTest
    original_head = QuietAcceptanceHandler.send_head
    original_post = QuietAcceptanceHandler.do_POST
    original_json = QuietAcceptanceHandler.send_json
    release, pending = threading.Event(), threading.Event()
    current_auth = {}
    observed = {}

    def head(handler):
        if urlparse(handler.path).path != "/fixture-entry":
            return original_head(handler)
        data = b'<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Isolated cookie test</title><body><h1>Isolated handoff test</h1><p>No production session or documents.</p></body>'
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Security-Policy", "default-src 'self'")
        handler.end_headers()
        return io.BytesIO(data)

    def post(handler):
        if urlparse(handler.path).path == "/fixture-new-handoff":
            handler.rfile.read(int(handler.headers.get("Content-Length", "0")))
            return original_json(handler, {"ok": True}, 200, backend.Handler.handoff_cookie_headers(current_auth["token"]))
        return original_post(handler)

    def send_json(handler, payload, status=200, extra_headers=None):
        if handler.headers.get("X-Fixture-Delay") == "1" and status == 401 and payload.get("error") == "handoff_session_missing":
            observed["delayedStatus"] = status
            observed["delayedSetCookieCount"] = sum(name.lower() == "set-cookie" for name, _ in (extra_headers or []))
            pending.set()
            if not release.wait(20):
                raise RuntimeError("fixture_release_timeout")
        return original_json(handler, payload, status, extra_headers)

    method = QuietAcceptanceHandler.handle_handoff_session_exchange
    if baseline:
        source = subprocess.check_output(["git", "show", f"{baseline}:backend.py"], cwd=ROOT, text=True)
        handler_class = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "Handler")
        node = next(node for node in handler_class.body if isinstance(node, ast.FunctionDef) and node.name == "handle_handoff_session_exchange")
        namespace = {}
        exec(textwrap.dedent("\n".join(source.splitlines()[node.lineno-1:node.end_lineno])), vars(backend), namespace)
        method = namespace["handle_handoff_session_exchange"]

    report = {"scope": "isolated_synthetic_real_http_chromium_cookies", "baseline": baseline, "productionRequests": False, "secretsSaved": False, "journeys": []}
    with mock.patch.object(QuietAcceptanceHandler, "send_head", head), mock.patch.object(QuietAcceptanceHandler, "do_POST", post), mock.patch.object(QuietAcceptanceHandler, "send_json", send_json), mock.patch.object(QuietAcceptanceHandler, "handle_handoff_session_exchange", method):
        fixture.setUpClass()
        require_local_origin(fixture.origin)
        config = Path(fixture.tmp.name) / "cookie-browser.json"
        config.write_text(json.dumps({"headed": False}))
        try:
            for device, size in (("desktop", (1440, 1000)), ("mobile", (390, 844))):
                current_auth = isolated_browser_session(fixture, "staff")
                release.clear(); pending.clear(); observed = {}
                browser = Browser(config, session=f"cookie-{device}-{time.monotonic_ns():x}"[-25:], namespace="cookie-race-isolated")
                try:
                    browser.run("set", "viewport", *map(str, size))
                    browser.run("open", fixture.origin + "/fixture-entry")
                    browser.evaluate("window.__oldResponse=null;window.__oldRequest=fetch('/api/auth/handoff-session',{method:'POST',headers:{'Content-Type':'application/json','X-EDOC-Handoff-Exchange':'1','X-Fixture-Delay':'1'},body:'{}'}).then(r=>window.__oldResponse=r.status);true")
                    assert pending.wait(5), "anonymous_response_not_held"
                    assert browser.evaluate("fetch('/fixture-new-handoff',{method:'POST',body:'{}'}).then(r=>r.status)") == 200
                    marker_before = browser.evaluate("document.cookie.includes('suiyuecare-edoc-handoff-pending=1')")
                    assert marker_before, "secure_fixture_cookie_not_accepted"
                    http_only_hidden = browser.evaluate("!document.cookie.includes('__Secure-suiyuecare-edoc-handoff')")
                    release.set()
                    browser.until("window.__oldResponse===401")
                    marker_after = browser.evaluate("document.cookie.includes('suiyuecare-edoc-handoff-pending=1')")
                    final = browser.evaluate("fetch('/api/auth/handoff-session',{method:'POST',headers:{'Content-Type':'application/json','X-EDOC-Handoff-Exchange':'1'},body:'{}'}).then(async r=>{const d=await r.json();return {status:r.status,validSession:!!(d.token&&d.user?.id)}})")
                    consumed = browser.evaluate("!document.cookie.includes('suiyuecare-edoc-handoff-pending=1')")
                    checks = {"oldRequestRemainsUnauthorized": observed["delayedStatus"] == 401, "newCookieInstalledOverHttp": marker_before, "httpOnlyTokenNotVisibleToJs": http_only_hidden, "lateMissingDoesNotSendCookieDeletion": observed["delayedSetCookieCount"] == 0, "lateMissingPreservesNewMarker": marker_after, "newHandoffAuthenticatedByBackend": final["status"] == 200 and final["validSession"], "successfulExchangeConsumesMarker": consumed}
                    result = {"device": device, "checks": checks, "delayedSetCookieCount": observed["delayedSetCookieCount"], "finalStatus": final["status"]}
                    report["journeys"].append(result)
                    print(json.dumps(result), flush=True)
                    if baseline:
                        assert marker_before and http_only_hidden and not marker_after and final["status"] == 401 and observed["delayedSetCookieCount"] == 2, "baseline_not_reproduced"
                    else:
                        assert all(checks.values()), "late_cookie_race_not_fixed"
                finally:
                    release.set()
                    browser.run("close")
            report["passed"] = True
        except Exception as error:
            report.update(passed=False, errorCode=str(error) if isinstance(error, AssertionError) or str(error).startswith("browser_") else type(error).__name__)
        finally:
            release.set()
            fixture.tearDownClass()
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--baseline")
    args = parser.parse_args()
    raise SystemExit(0 if run(args.output, args.baseline)["passed"] else 1)
