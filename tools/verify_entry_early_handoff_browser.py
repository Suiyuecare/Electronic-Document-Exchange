"""Real browser + anonymous backend regression with a deliberately slow bundle.

Only the production hostname guard and Portal destination are adapted to an
isolated localhost fixture. The actual head script, app, HTML and missing-
HttpOnly-cookie endpoint run unchanged otherwise. No real login or records.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import subprocess
import sys
import time
from unittest import mock
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.six_role_browser_acceptance import Browser, TELEMETRY, require_local_origin
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler


def run(output: Path, baseline: str | None = None) -> dict:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    fixture = FiveAccountHttpAcceptanceTest
    original_head = QuietAcceptanceHandler.send_head
    original_post = QuietAcceptanceHandler.do_POST
    delay_seconds = 8
    events = []
    source = (ROOT / "entry-bootstrap.js").read_text()
    if baseline:
        source = subprocess.check_output(["git", "show", f"{baseline}:entry-bootstrap.js"], cwd=ROOT, text=True)

    def mark(name):
        events.append({"event": name, "at": time.monotonic()})

    def respond(handler, data, content_type):
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Security-Policy", "connect-src 'self'; font-src 'self'; frame-src 'none'")
        handler.end_headers()
        return io.BytesIO(data)

    def adapt(script):
        return script.replace('"edoc.suiyuecare.com"', '"127.0.0.1"').replace(
            '"https://login.suiyuecare.com/portal/"', json.dumps(fixture.origin + "/portal/")
        )

    def head(handler):
        path = urlparse(handler.path).path
        if path in {"/", "/index.html"}:
            mark("entryRequested")
            html = (ROOT / "index.html").read_text().replace("<head>", "<head>" + TELEMETRY, 1)
            return respond(handler, html.encode(), "text/html; charset=utf-8")
        if path == "/entry-bootstrap.js":
            mark("bootstrapRequested")
            return respond(handler, adapt(source).encode(), "text/javascript; charset=utf-8")
        if path == "/app.js":
            mark("bundleRequested")
            bundle_events = events
            time.sleep(delay_seconds)
            bundle_events.append({"event": "bundleReleased", "at": time.monotonic()})
            return respond(handler, adapt((ROOT / "app.js").read_text()).encode(), "text/javascript; charset=utf-8")
        if path == "/portal/":
            mark("portalRequested")
            return respond(handler, ('<!doctype html><html lang="zh-Hant"><meta name="viewport" content="width=device-width,initial-scale=1"><title>隔離登入入口</title><body><h1>已到登入入口</h1><p>本機測試，不登入正式帳號。</p></body></html>').encode(), "text/html; charset=utf-8")
        return original_head(handler)

    def post(handler):
        if urlparse(handler.path).path == "/api/auth/handoff-session":
            mark("handoffRequested")
        return original_post(handler)

    report = {"scope": "isolated_localhost_real_anonymous_backend_no_business_writes", "baseline": baseline, "artificialBundleDelaySeconds": delay_seconds, "journeys": []}
    with mock.patch.object(QuietAcceptanceHandler, "send_head", head), mock.patch.object(QuietAcceptanceHandler, "do_POST", post):
        fixture.setUpClass()
        require_local_origin(fixture.origin)
        config = Path(fixture.tmp.name) / "entry-browser.json"
        config.write_text(json.dumps({"headed": False}))
        try:
            for device, size in (("desktop", (1440, 1000)), ("mobile", (390, 844))):
                browser = Browser(config, session=f"entry-{device}-{time.monotonic_ns():x}"[-25:], namespace="entry-early-isolated")
                events = []
                try:
                    browser.run("set", "viewport", *map(str, size))
                    browser.run("open", fixture.origin + "/#electronicSeal")
                    browser.until("location.pathname==='/portal/'", timeout=30)
                    state = browser.evaluate("({pathname:location.pathname,search:location.search,overflow:document.documentElement.scrollWidth>innerWidth+1})")
                    browser.run("screenshot", str(output / f"{device}-portal.png"))
                    observed = list(events)
                    first = lambda name: next((row["at"] for row in observed if row["event"] == name), None)
                    start, probe, portal, released = (first(name) for name in ("entryRequested", "handoffRequested", "portalRequested", "bundleReleased"))
                    query = parse_qs(state["search"].lstrip("?"))
                    checks = {
                        "arrivesAtIsolatedPortal": state["pathname"] == "/portal/",
                        "exactlyOneHandoffProbe": sum(row["event"] == "handoffRequested" for row in observed) == 1,
                        "sameSafePortalDestination": query == {"module": ["edoc"], "next": [fixture.origin + "/"]},
                        "noHorizontalOverflow": not state["overflow"],
                        "probeDoesNotWaitForBundle": bool(probe and (released is None or probe < released)),
                        "redirectDoesNotWaitForBundle": bool(portal and (released is None or portal < released)),
                    }
                    result = {"device": device, "checks": checks, "localPortalQuery": query, "probeStartMs": round((probe-start)*1000, 2) if probe else None, "portalArrivalMs": round((portal-start)*1000, 2) if portal else None, "events": [{"event": row["event"], "ms": round((row["at"]-start)*1000, 2)} for row in observed]}
                    report["journeys"].append(result)
                    print(json.dumps(result), flush=True)
                    if baseline:
                        assert all(value for key, value in checks.items() if "DoesNotWait" not in key)
                        assert not checks["probeDoesNotWaitForBundle"], "baseline_did_not_reproduce"
                    else:
                        assert all(checks.values()), "early_handoff_browser_failed"
                finally:
                    browser.run("close")
            report["passed"] = True
        except Exception as error:
            report.update(passed=False, errorCode=str(error) if isinstance(error, AssertionError) or str(error).startswith("browser_") else type(error).__name__)
        finally:
            fixture.tearDownClass()
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--baseline", help="Git revision of the head script, to reproduce the old dependency")
    args = parser.parse_args()
    raise SystemExit(0 if run(args.output, args.baseline)["passed"] else 1)
