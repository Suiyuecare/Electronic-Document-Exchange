"""Desktop/mobile UI acceptance with loopback-only synthetic API responses."""
from __future__ import annotations
import io
import json
from pathlib import Path
import sys
import time
from unittest import mock
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler
from tests.support.five_account_browser_fixture import isolated_browser_session
from tools.six_role_browser_acceptance import Browser, TELEMETRY, AUDIT_JS

OUT = ROOT / "tests/.artifacts/seven-fixes-20260924/frontend"
INSTRUMENT = '''<script>
window.__readAudit={pending:0,requests:[]};const baseFetch=window.fetch;
window.fetch=async function(input,options={}){const u=new URL(typeof input==='string'?input:input.url,location.href),a=window.__readAudit,api=u.origin===location.origin&&u.pathname.startsWith('/api/');if(api)a.pending++;let status=0;try{const r=await baseFetch.apply(this,arguments);status=r.status;return r;}finally{if(api){a.pending--;a.requests.push({path:u.pathname,query:u.search,method:options.method||'GET',status});}}};
</script>'''


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    original_head, original_get = QuietAcceptanceHandler.send_head, QuietAcceptanceHandler.do_GET
    mode = {"seal_failure": False, "list_failure": False, "slow": False, "version": "before", "actor": ""}
    def head(handler):
        if urlparse(handler.path).path in {"/", "/index.html"}:
            data = (ROOT / "index.html").read_bytes().replace(b"<head>", b"<head>" + TELEMETRY.encode() + INSTRUMENT.encode(), 1)
            handler.send_response(200)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.send_header("Content-Length", str(len(data)))
            handler.send_header("Content-Security-Policy", "connect-src 'self'")
            handler.end_headers()
            return io.BytesIO(data)
        return original_head(handler)
    def get(handler):
        parsed = urlparse(handler.path)
        if parsed.path.startswith("/api/official-documents/QA-"):
            document_id = parsed.path.rsplit("/", 1)[-1]
            return handler.send_json({"id": document_id, "title": f"Synthetic {mode['version']} {document_id}", "subject": "oldest-case" if document_id == "QA-1201" else "Synthetic approval case", "current_status": "pending_ceo", "current_step": "ceo", "can_act": True, "applicant_id": mode["actor"], "applicant_name": "Fixture applicant", "created_at": "2026-09-24T00:00:00Z", "approval_steps": [{"id": f"STEP-{document_id}", "step_key": "ceo", "step_name": "CEO", "status": "pending", "approver_user_id": mode["actor"]}], "files": [], "approval_logs": []})
        if parsed.path == "/api/official-documents/my-requests":
            return handler.send_json({"items": [{"id": "QA-OWN-OLD", "subject": "Old own case", "current_status": "draft", "applicant_id": mode["actor"], "applicant_name": "Fixture applicant", "created_at": "2025-01-01T00:00:00Z", "approval_steps": []}], "has_more": False, "next_cursor": ""})
        if parsed.path == "/api/official-documents":
            if mode["slow"]:
                time.sleep(1.5)
            if mode["list_failure"]:
                return handler.send_json({"error": "synthetic_read_unavailable"}, 503)
            query = parse_qs(parsed.query)
            index = 50 if query.get("cursor") else 0
            ids = [1201] if query.get("search") else list(range(index, min(index + 50, 51)))
            rows = [{"id": f"QA-{i:04}", "title": f"Synthetic {mode['version']} {i}", "subject": "oldest-case" if i == 1201 else "Synthetic approval case", "current_status": "pending_ceo", "current_step": "ceo", "can_act": True, "applicant_id": mode["actor"], "applicant_name": "Fixture applicant", "created_at": "2026-09-24T00:00:00Z", "approval_steps": [{"id": f"STEP-{i}", "step_key": "ceo", "step_name": "CEO", "status": "pending", "approver_user_id": mode["actor"]}]} for i in ids]
            return handler.send_json({"items": rows, "has_more": index == 0 and not query.get("search"), "next_cursor": "page-two" if index == 0 and not query.get("search") else ""})
        if mode["seal_failure"] and parsed.path.startswith("/api/companies/") and parsed.path.endswith("/seals"):
            return handler.send_json({"error": "synthetic_read_unavailable"}, 503)
        return original_get(handler)
    results = []
    with mock.patch.object(QuietAcceptanceHandler, "send_head", head), mock.patch.object(QuietAcceptanceHandler, "do_GET", get):
        fixture = FiveAccountHttpAcceptanceTest
        fixture.setUpClass()
        try:
            assert backend.USE_SUPABASE is False
            for device, viewport in (("desktop", (1440, 1000)), ("mobile", (390, 844))):
                config = Path(fixture.tmp.name) / f"read-{device}.json"
                config.write_text('{"headed":false}')
                name = f"read-{time.monotonic_ns() % 1000000}"
                browser = Browser(config, session=name, namespace=name)
                result = {"device": device, "scope": "synthetic_loopback_not_production"}
                try:
                    mode.update(seal_failure=False, list_failure=False, slow=False, version="before")
                    auth = isolated_browser_session(fixture, "ceo", entity_id="E1")
                    mode["actor"] = auth["user"]["id"]
                    browser.run("open", fixture.origin + "/assets/favicon-32.png")
                    browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                    browser.run("set", "viewport", *map(str, viewport))
                    browser.run("open", fixture.origin + f"/?acceptance={time.monotonic_ns()}#approvalLog")
                    browser.until("window.__fixtureTiming?.appInteractiveMs")
                    browser.until("window.__readAudit.pending===0&&!officialWorkflowPage.loading")
                    browser.run("snapshot", "-i")
                    assert browser.evaluate("officialWorkflowItems.length===50&&officialWorkflowPage.hasMore")
                    browser.click_visible("#approvalLogPagination button")
                    browser.until("officialWorkflowItems.length===51&&!officialWorkflowPage.loading")
                    result["loadMore"] = browser.evaluate("({count:officialWorkflowItems.length,hasMore:officialWorkflowPage.hasMore,label:document.querySelector('#approvalLogPagination').textContent})")
                    browser.run("fill", "#approvalLogSearch", "oldest-case")
                    browser.until("officialWorkflowItems.length===1&&officialWorkflowItems[0].id==='QA-1201'")
                    result["serverSearch"] = browser.evaluate("window.__readAudit.requests.filter(r=>r.query.includes('search=')).at(-1)")
                    assert browser.evaluate("document.querySelector('#approvalLogList').textContent.includes('oldest-case')")
                    browser.run("fill", "#approvalLogSearch", "")
                    browser.until("officialWorkflowItems.length===50&&!officialWorkflowPage.loading")
                    if device == "mobile":
                        browser.click_visible("#mobileMenuButton")
                        browser.run("snapshot", "-i")
                    mode.update(slow=True, version="after")
                    browser.evaluate("window.__readAudit.requests=[];true")
                    browser.click_visible("#headerRefreshBtn" if device == "desktop" else "#mobileDrawerRefreshBtn")
                    result["busy"] = browser.evaluate("({disabled:document.querySelector('#headerRefreshBtn').disabled,aria:document.querySelector('#headerRefreshBtn').getAttribute('aria-busy')})")
                    assert result["busy"]["disabled"] and result["busy"]["aria"] == "true"
                    browser.until("workspaceRefreshRequest===null&&window.__readAudit.pending===0")
                    assert browser.evaluate("officialWorkflowItems[0].title.includes('after')")
                    result["refreshRequests"] = browser.evaluate("window.__readAudit.requests")
                    browser.evaluate("window.scrollTo(0,0);true")
                    browser.run("screenshot", str(OUT / f"{device}-refresh.png"))
                    mode.update(slow=False, list_failure=True)
                    browser.evaluate("void refreshCurrentWorkspace();true")
                    browser.until("workspaceRefreshRequest===null")
                    assert browser.evaluate("officialWorkflowItems[0].title.includes('after')&&officialWorkflowPage.error&&routeBackendDataErrors.has('approvalLog')")
                    mode["list_failure"] = False
                    browser.click_visible("#workspaceLoadRetryBtn")
                    browser.until("workspaceRefreshRequest===null&&!officialWorkflowPage.error")
                    result["refreshRecovery"] = True
                    # Only synthetic unsaved input; refresh must not erase it.
                    browser.evaluate("location.hash='#compose';true")
                    browser.until("activeRouteTarget==='compose'&&window.__readAudit.pending===0")
                    browser.evaluate("document.querySelector('#officialSubjectInput').value='UNSAVED-SYNTHETIC';void refreshCurrentWorkspace();true")
                    browser.until("workspaceRefreshRequest===null")
                    assert browser.evaluate("document.querySelector('#officialSubjectInput').value==='UNSAVED-SYNTHETIC'")
                    result["unsavedPreserved"] = True
                    mode["seal_failure"] = True
                    browser.evaluate("location.hash='#seals';true")
                    browser.until("activeRouteTarget==='seals'&&routeBackendDataErrors.has('seals')&&window.__readAudit.pending===0")
                    result["sealFailure"] = browser.evaluate("({loaded:routeBackendDataLoaded.has('seals'),error:companySealLoadState.status,noticeHidden:document.querySelector('#companySealLoadStatus').hidden,text:document.querySelector('#simpleSealUploadedList').textContent})")
                    assert not result["sealFailure"]["loaded"] and not result["sealFailure"]["noticeHidden"]
                    assert "尚未建立印章" not in result["sealFailure"]["text"]
                    browser.evaluate("document.querySelector('#companySealLoadStatus').scrollIntoView({block:'center',behavior:'instant'});true")
                    browser.run("screenshot", str(OUT / f"{device}-seal-error.png"))
                    mode["seal_failure"] = False
                    browser.evaluate("location.hash='#dashboard';true")
                    browser.until("activeRouteTarget==='dashboard'&&window.__readAudit.pending===0")
                    result["dashboardScoped"] = browser.evaluate("({view:officialWorkflowPage.query.view,mine:homeOfficialCases.items.length,ownText:document.querySelector('#homeMyCasesList').textContent,hasMore:officialWorkflowPage.hasMore,count:document.querySelector('#dailyActionCount').textContent})")
                    assert result["dashboardScoped"]["view"] == "attention" and "Old own case" in result["dashboardScoped"]["ownText"]
                    assert "已載入" in result["dashboardScoped"]["count"] and result["dashboardScoped"]["hasMore"]
                    assert "50 件" in result["dashboardScoped"]["count"]
                    browser.click_visible("#dashboardOfficialPagination button")
                    browser.until("officialWorkflowItems.length===51&&!officialWorkflowPage.loading")
                    assert browser.evaluate("document.querySelector('#dailyActionCount').textContent.includes('51 件')")
                    browser.run("screenshot", str(OUT / f"{device}-dashboard-scoped.png"))
                    browser.evaluate("window.__readAudit.requests=[];location.hash='#seals';true")
                    browser.until("activeRouteTarget==='seals'&&companySealLoadState.status==='loaded'&&window.__readAudit.pending===0")
                    result["sealRecovered"] = browser.evaluate("window.__readAudit.requests.some(r=>r.path.endsWith('/seals')&&r.status===200)")
                    assert result["sealRecovered"]
                    browser.evaluate("document.querySelector('#companySealModule').scrollIntoView({block:'start',behavior:'instant'});true")
                    browser.run("screenshot", str(OUT / f"{device}-seal-recovered.png"))
                    result["layout"] = browser.evaluate(AUDIT_JS)
                    result["status"] = "passed"
                except Exception as error:
                    result.update(status="failed", error=str(error) if str(error).startswith("browser_") else type(error).__name__)
                    try:
                        result["diagnostic"] = browser.evaluate("({route:activeRouteTarget,requests:window.__readAudit.requests,errors:window.__fixtureErrors,seal:companySealLoadState,list:officialWorkflowPage,toast:document.querySelector('.toast')?.textContent})")
                    except Exception:
                        pass
                finally:
                    try:
                        browser.run("close")
                    except Exception:
                        pass
                    results.append(result)
                    print(json.dumps(result, ensure_ascii=False), flush=True)
        finally:
            fixture.tearDownClass()
    (OUT / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(row["status"] == "passed" for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
