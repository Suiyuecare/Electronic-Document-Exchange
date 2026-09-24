"""Finance-style EDOC header acceptance using an isolated, synthetic local API.

Run --phase before before changing product assets, then --phase after. Nothing
is sent to real Finance, Supabase, Portal, or electronic-document exchange.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import time
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler
from tests.support.five_account_browser_fixture import isolated_browser_session
from tools.six_role_browser_acceptance import Browser, TELEMETRY, require_local_origin

VIEWPORTS = (375, 390, 430, 760, 820, 900, 1180, 1440, 1920)
OUT = ROOT / "tests/.artifacts/finance-header-20260925"
INSTRUMENT = """<script>
window.__headerAudit={pending:0,requests:[]};const originalFetch=window.fetch;
window.fetch=async function(input,options={}){const u=new URL(typeof input==='string'?input:input.url,location.href),a=window.__headerAudit,api=u.origin===location.origin&&u.pathname.startsWith('/api/');if(api)a.pending++;let status=0;try{const r=await originalFetch.apply(this,arguments);status=r.status;return r;}finally{if(api){a.pending--;a.requests.push({path:u.pathname,method:options.method||'GET',status});}}};
</script>"""
LAYOUT = """(()=>{
 const h=document.querySelector('.topbar'),s=getComputedStyle(h),hr=h.getBoundingClientRect();
 const ids=['pageTitle','headerNotificationBtn','headerRefreshBtn','returnPortalBtn','logoutBtn','topInfo','mobileMenuButton'];
 const nodes=Object.fromEntries(ids.map(id=>{const e=document.getElementById(id),r=e.getBoundingClientRect(),c=getComputedStyle(e);return [id,{x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height,visible:!!e.getClientRects().length&&c.visibility!=='hidden',fontSize:c.fontSize,fontWeight:c.fontWeight,letterSpacing:c.letterSpacing,borderRadius:c.borderRadius,background:c.backgroundColor,overflow:c.overflow,textOverflow:c.textOverflow,text:e.textContent.trim()}]}));
 const declarations=[];const visit=rules=>{for(const rule of rules){if(rule.type===CSSRule.MEDIA_RULE&&!matchMedia(rule.conditionText).matches)continue;if(rule.cssRules)visit(rule.cssRules);if(rule.selectorText&&rule.selectorText.split(',').some(t=>{try{return h.matches(t.trim())}catch{return false}})&&rule.style.gridTemplateColumns)declarations.push(rule.style.gridTemplateColumns)}};for(const sheet of document.styleSheets){try{visit(sheet.cssRules)}catch{}}
 const heading=document.querySelector('.mobile-topbar-heading').getBoundingClientRect();
 return {width:innerWidth,height:hr.height,header:{x:hr.x,right:hr.right,width:hr.width},heading:{x:heading.x,right:heading.right,width:heading.width},grid:s.gridTemplateColumns,declaredGrid:declarations.at(-1),padding:s.padding,columnGap:s.columnGap,nodes,overflow:document.documentElement.scrollWidth>innerWidth+1,errors:window.__fixtureErrors||[]};
})()"""


def validate_layout(row: dict) -> None:
    width, nodes = row["width"], row["nodes"]
    assert not row["overflow"], f"document_overflow_at_{width}"
    assert not row["errors"], f"page_errors_at_{width}"
    assert abs(row["height"] - (56 if width <= 760 else 96 if width <= 1180 else 82)) < 0.5, f"header_height_at_{width}"
    for name, node in nodes.items():
        if node["visible"]:
            assert node["x"] >= row["header"]["x"] - 1 and node["right"] <= row["header"]["right"] + 1, f"clipped_{name}_at_{width}"
    if width <= 760:
        assert not nodes["headerRefreshBtn"]["visible"] and not nodes["topInfo"]["visible"]
        for name in ("headerNotificationBtn", "mobileMenuButton"):
            assert nodes[name]["visible"] and nodes[name]["width"] >= 44 and nodes[name]["height"] >= 44, f"mobile_target_{name}"
        assert nodes["pageTitle"]["right"] <= nodes["headerNotificationBtn"]["x"] + 1
        assert nodes["headerNotificationBtn"]["right"] <= nodes["mobileMenuButton"]["x"] + 1
    else:
        order = [nodes[name] for name in ("pageTitle", "headerNotificationBtn", "headerRefreshBtn", "returnPortalBtn", "logoutBtn")]
        assert all(node["visible"] for node in order), f"desktop_hidden_control_at_{width}"
        assert all(left["right"] <= right["x"] + 1 for left, right in zip(order, order[1:])), f"header_overlap_at_{width}"
        if width > 1180:
            assert nodes["topInfo"]["visible"] and nodes["logoutBtn"]["right"] <= nodes["topInfo"]["x"] + 1
            assert row["declaredGrid"] == "max-content max-content max-content minmax(0px, 1fr)", f"finance_grid_at_{width}:{row['declaredGrid']}"
            assert abs(nodes["headerNotificationBtn"]["x"] - row["heading"]["right"] - 10) < 1, f"header_not_left_clustered_at_{width}"
            assert abs(nodes["headerNotificationBtn"]["x"] - nodes["pageTitle"]["right"] - 10) < 1, f"title_still_stretched_at_{width}"
            assert nodes["headerNotificationBtn"]["width"] == 30 and nodes["headerNotificationBtn"]["height"] == 26
            assert nodes["pageTitle"]["fontSize"] == "22px"
            for name in ("headerRefreshBtn", "returnPortalBtn", "logoutBtn"):
                assert nodes[name]["height"] >= 38
        else:
            assert nodes["topInfo"]["visible"] and nodes["topInfo"]["y"] >= max(node["bottom"] for node in order) - 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    args = parser.parse_args()
    output = OUT / args.phase
    output.mkdir(parents=True, exist_ok=True)
    # Keep the entire before run on the assets present at start, even if a
    # teammate begins the authorized CSS patch while screenshots are running.
    assets = {"/" + name: (ROOT / name).read_bytes() for name in ("index.html", "styles.css", "app.js")}
    (output / "asset-hashes.json").write_text(json.dumps({name: hashlib.sha256(data).hexdigest() for name, data in assets.items()}, indent=2))
    original_head, original_get = QuietAcceptanceHandler.send_head, QuietAcceptanceHandler.do_GET
    mode = {"slow": False}

    def head(handler):
        path = urlparse(handler.path).path
        path = "/index.html" if path == "/" else path
        if path in assets:
            data = assets[path]
            if path == "/index.html":
                data = data.replace(b"<head>", b"<head>" + TELEMETRY.encode() + INSTRUMENT.encode(), 1)
            handler.send_response(200)
            handler.send_header("Content-Type", "text/html; charset=utf-8" if path.endswith(".html") else "text/css" if path.endswith(".css") else "application/javascript")
            handler.send_header("Content-Length", str(len(data)))
            handler.send_header("Content-Security-Policy", "connect-src 'self'")
            handler.end_headers()
            return io.BytesIO(data)
        return original_head(handler)

    def get(handler):
        if mode["slow"] and urlparse(handler.path).path == "/api/official-documents":
            time.sleep(1.5)
        return original_get(handler)

    result = {"phase": args.phase, "scope": "synthetic_loopback_only_no_production", "layouts": [], "interactions": {}}
    with mock.patch.object(QuietAcceptanceHandler, "send_head", head), mock.patch.object(QuietAcceptanceHandler, "do_GET", get):
        fixture = FiveAccountHttpAcceptanceTest
        fixture.setUpClass()
        browser = None
        try:
            require_local_origin(fixture.origin)
            assert backend.USE_SUPABASE is False
            config = Path(fixture.tmp.name) / "header-browser.json"
            config.write_text('{"headed":false}')
            name = f"header-{args.phase}-{time.monotonic_ns() % 1000000}"
            browser = Browser(config, session=name, namespace=name)
            auth = isolated_browser_session(fixture, "ceo", entity_id="E1")
            browser.run("open", fixture.origin + "/assets/favicon-32.png")
            browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
            browser.run("set", "viewport", "1440", "1000")
            browser.run("open", fixture.origin + f"/?header-acceptance={time.monotonic_ns()}#dashboard")
            browser.until("window.__fixtureTiming?.appInteractiveMs&&window.__headerAudit.pending===0")
            browser.run("snapshot", "-i")
            for width in VIEWPORTS:
                browser.run("set", "viewport", str(width), "844" if width <= 760 else "1000")
                browser.evaluate("window.scrollTo(0,0);true")
                row = browser.evaluate(LAYOUT)
                result["layouts"].append(row)
                if width in (390, 1440):
                    browser.run("screenshot", str(output / f"header-{width}.png"))
                if args.phase == "after":
                    validate_layout(row)
                    # Same long content on every viewport; normal content is
                    # restored immediately so application timers stay intact.
                    long_row = browser.evaluate("(()=>{const t=document.querySelector('#pageTitle'),s=document.querySelector('#topInfo'),old=[t.textContent,s.textContent];t.textContent='跨公司電子公文簽核暨收發管理作業中心'.repeat(5);s.textContent='驗收使用者姓名很長 · 行政部門主任與跨公司主管 · 即時同步 · 23:59:59'.repeat(3);const result=" + LAYOUT + ";t.textContent=old[0];s.textContent=old[1];return result})()")
                    validate_layout(long_row)
                    row["longContent"] = long_row
            if args.phase == "after":
                for width in (1440, 390):
                    browser.run("set", "viewport", str(width), "844" if width == 390 else "1000")
                    browser.evaluate("location.hash='#compose';window.scrollTo(0,0);true")
                    browser.until("activeRouteTarget==='compose'&&window.__headerAudit.pending===0")
                    browser.run("snapshot", "-i")
                    browser.click_visible("#headerNotificationBtn")
                    browser.until("activeRouteTarget==='dashboard'&&window.__headerAudit.pending===0")
                    if width == 390:
                        browser.click_visible("#mobileMenuButton")
                        browser.until("document.body.classList.contains('mobile-navigation-open')")
                        browser.run("snapshot", "-i")
                        browser.run("press", "Escape")
                        browser.until("!document.body.classList.contains('mobile-navigation-open')")
                        browser.click_visible("#mobileMenuButton")
                    mode["slow"] = True
                    browser.evaluate("window.__headerAudit.requests=[];true")
                    browser.click_visible("#headerRefreshBtn" if width == 1440 else "#mobileDrawerRefreshBtn")
                    busy = browser.evaluate("document.querySelector('#headerRefreshBtn').disabled&&document.querySelector('#headerRefreshBtn').getAttribute('aria-busy')==='true'")
                    assert busy, "refresh_busy_missing"
                    browser.until("workspaceRefreshRequest===null&&window.__headerAudit.pending===0")
                    mode["slow"] = False
                    requests = browser.evaluate("window.__headerAudit.requests")
                    assert any(row["path"] == "/api/official-documents" and row["status"] == 200 for row in requests), "refresh_read_missing"
                    if width == 390:
                        assert not browser.evaluate("document.body.classList.contains('mobile-navigation-open')")
                        browser.click_visible("#mobileMenuButton")
                        browser.until("document.body.classList.contains('mobile-navigation-open')")
                        browser.click_visible('.sidebar .nav-item[data-target="compose"]')
                        browser.until("activeRouteTarget==='compose'&&!document.body.classList.contains('mobile-navigation-open')")
                    result["interactions"][str(width)] = {"notificationNavigation": True, "refreshBusy": busy, "refreshRead": True, "mobileDrawer": width == 390, "requests": requests}
                assert not browser.evaluate("window.__fixtureErrors.length"), "runtime_errors"
            result["status"] = "captured" if args.phase == "before" else "passed"
        except Exception as error:
            result.update(status="failed", error=str(error))
            if browser:
                try:
                    result["failureState"] = browser.evaluate(LAYOUT)
                    browser.run("screenshot", str(output / "failure.png"))
                except Exception:
                    pass
        finally:
            if browser:
                try:
                    browser.run("close")
                except Exception:
                    pass
            fixture.tearDownClass()
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({"phase": args.phase, "status": result["status"], "error": result.get("error"), "output": str(output)}, ensure_ascii=False))
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
