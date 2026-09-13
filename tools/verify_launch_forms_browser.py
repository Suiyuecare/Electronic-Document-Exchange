"""Four-role six-page browser gate; isolated synthetic data and no submissions."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import sys
import time
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.six_role_browser_acceptance import AUDIT_JS, Browser, TELEMETRY, require_local_origin
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler

FETCH_TELEMETRY = """<script>
window.__fixtureHttpErrors=[];
const fixtureFetch=window.fetch;
window.fetch=async (...args)=>{
 const response=await fixtureFetch(...args);
 if(!response.ok){const url=new URL(args[0]?.url||String(args[0]),location.href);if(url.origin===location.origin)window.__fixtureHttpErrors.push({path:url.pathname,status:response.status});}
 return response;
};
</script>"""


def run(output: Path) -> dict:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    fixture = FiveAccountHttpAcceptanceTest
    original_head = QuietAcceptanceHandler.send_head

    def head(handler):
        if urlparse(handler.path).path in {"/", "/index.html"}:
            data = (ROOT / "index.html").read_text().replace("<head>", "<head>" + TELEMETRY + FETCH_TELEMETRY, 1).encode()
            handler.send_response(200)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.send_header("Content-Security-Policy", "connect-src 'self'")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            return io.BytesIO(data)
        return original_head(handler)

    report = {
        "scope": "synthetic_local_no_production_mutations_no_real_google_login",
        "expectedReadinessFailure": "The production-branch fixture uses temporary SQLite/local storage; /api/production/go-live-audit must return 503 NO_GO. This does not verify production readiness.",
        "rows": [],
    }
    with mock.patch.object(QuietAcceptanceHandler, "send_head", head):
        fixture.setUpClass()
        require_local_origin(fixture.origin)
        config = Path(fixture.tmp.name) / "launch-forms-browser.json"
        config.write_text(json.dumps({"headed": False}))
        browser = Browser(config, session=f"lf-{time.monotonic_ns():x}"[-18:], namespace="launch-forms")
        try:
            for role in ("staff", "section_chief", "ga_chief", "ceo"):
                auth = isolated_browser_session(fixture, role)
                for device, dimensions in (("desktop", (1440, 1000)), ("mobile", (390, 844))):
                    browser.run("set", "viewport", *map(str, dimensions))
                    browser.run("open", fixture.origin + "/assets/favicon-32.png")
                    browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                    browser.run("open", fixture.origin + "/#dashboard")
                    browser.until("window.__fixtureTiming?.appInteractiveMs")
                    browser.run("snapshot", "-i")
                    for route in ("dashboard", "compose", "electronicSeal", "approvalLog", "inbound", "settings"):
                        if device == "mobile":
                            browser.run("click", "#mobileMenuButton")
                            browser.until("Math.abs(document.querySelector('#primarySidebar').getBoundingClientRect().left)<.5")
                        selector = '.sidebar .nav-item[data-target="' + route + '"]'
                        exposed = browser.evaluate("!!document.querySelector(" + json.dumps(selector) + ")?.getClientRects().length")
                        expected = route != "settings" or role in {"ga_chief", "ceo"}
                        checks = {"roleNavigationMatches": exposed == expected}
                        if expected:
                            browser.run("click", selector)
                            browser.until("document.querySelector('.view.active')?.id===" + json.dumps(route))
                            checks["routeReachable"] = True
                        else:
                            if device == "mobile":
                                browser.run("click", "#mobileDrawerCloseBtn")
                                browser.until("!document.body.classList.contains('mobile-navigation-open')")
                            browser.run("open", fixture.origin + "/#settings")
                            browser.until("window.__fixtureTiming?.appInteractiveMs")
                            checks["directHashCannotBypassRole"] = browser.evaluate("document.querySelector('.view.active')?.id!=='settings'&&!document.querySelector('#settings')?.classList.contains('active')")
                        browser.run("snapshot", "-i")
                        filename = f"{role}-{device}-{route}.png"
                        browser.run("screenshot", str(output / filename))
                        layout = browser.evaluate(AUDIT_JS)
                        checks["noDocumentOverflow"] = not layout["overflow"]
                        checks["noBrowserErrors"] = not layout["errors"]
                        checks["meaningfulPage"] = browser.evaluate("document.querySelector('.view.active')?.innerText.trim().length>10")
                        http_errors = browser.evaluate("window.__fixtureHttpErrors")
                        checks["noUnexpectedHttpErrors"] = all(item == {"path": "/api/production/go-live-audit", "status": 503} for item in http_errors)
                        report["rows"].append({"role": role, "device": device, "route": route, "checks": checks, "layout": layout, "httpErrors": http_errors, "screenshot": filename})
                        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
                        if not all(checks.values()):
                            raise AssertionError(f"role_page_failed:{role}:{device}:{route}")
                    print(json.dumps({"role": role, "device": device, "pages": 6, "passed": True}), flush=True)
            report["passed"] = True
        except Exception as error:
            report["passed"] = False
            report["errorCode"] = str(error) if isinstance(error, AssertionError) or str(error).startswith("browser_") else type(error).__name__
            try:
                browser.run("screenshot", str(output / "failure.png"))
                report["failureState"] = browser.evaluate("({active:document.querySelector('.view.active')?.id,errors:window.__fixtureErrors})")
            except Exception:
                pass
        finally:
            try:
                browser.run("close")
            finally:
                fixture.tearDownClass()
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output)
    raise SystemExit(0 if result["passed"] else 1)
