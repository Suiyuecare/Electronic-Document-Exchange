"""Local synthetic draft/navigation acceptance. No production login or writes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend
from tools.six_role_browser_acceptance import Browser, require_local_origin
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest


def run(output, widths=None):
    output.mkdir(parents=True, exist_ok=True)
    fixture = FiveAccountHttpAcceptanceTest
    fixture.setUpClass()
    require_local_origin(fixture.origin)
    config = Path(fixture.tmp.name) / "nav-browser.json"
    config.write_text(json.dumps({"headed": False}))
    browser = Browser(config, session="edoc-nav-20261014", namespace="edoc-nav-isolated")
    report = {"scope": "isolated_synthetic_not_real_SSO", "appSha256": hashlib.sha256((ROOT / "app.js").read_bytes()).hexdigest(), "checks": []}
    def check(name, value, **context):
        report["checks"].append({"name": name, "passed": bool(value), **context})
        if not value: raise AssertionError(name)
    def navigate(route, mobile):
        if mobile and not browser.evaluate("document.body.classList.contains('mobile-navigation-open')"):
            browser.run("click", "#mobileMenuButton")
            browser.until("Math.abs(document.querySelector('#primarySidebar').getBoundingClientRect().left)<0.5")
        browser.click_visible(f'.sidebar .nav-item[data-target="{route}"]')
        browser.until(f"activeRouteTarget==={json.dumps(route)}")
    try:
        for role in ("staff", "ceo"):
            auth = isolated_browser_session(fixture, role)
            with backend.connect() as conn:
                for i in range(31):
                    backend.save_compose_draft(conn, "OD-" + str(uuid.uuid4()), {"snapshot": {"userId": auth["user"]["id"], "companyId": auth["user"]["company_id"], "values": {"#subject": f"合成驗收草稿 {i:02d}", "#documentPurpose": "本機隔離驗收，不送簽"}}, "expected_revision": 0}, auth)
                conn.commit()
            for width, height in ((1440, 1000), (820, 1100), (390, 844)):
                if widths and width not in widths: continue
                context = {"role": role, "width": width}
                browser.run("set", "viewport", str(width), str(height))
                browser.run("open", fixture.origin + "/assets/favicon-32.png")
                browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                browser.run("open", fixture.origin + "/#dashboard")
                browser.until("hasAuthenticatedBackendSession()&&!document.querySelector('#appShell').inert&&!document.querySelector('#appShell').classList.contains('hidden')&&document.querySelector('#moduleEntryProgress').classList.contains('hidden')")
                mobile = width <= 760
                navigate("drafts", mobile)
                browser.until("!workspaceDraftState.loading&&workspaceDraftState.total===31")
                check("exact_full_badge", browser.evaluate("document.querySelector('#draftNavCount').textContent==='31'"), **context)
                check("first_page_25", browser.evaluate("document.querySelectorAll('[data-workspace-draft-open]').length===25"), **context)
                browser.click_visible("[data-drafts-more]")
                browser.until("workspaceDraftState.rows.length===31&&!workspaceDraftState.loading")
                check("second_page_no_duplicates", browser.evaluate("new Set(workspaceDraftState.rows.map(r=>r.key)).size===31"), **context)
                browser.run("fill", "#workspaceDraftSearch", "草稿 05")
                browser.until("!workspaceDraftState.loading&&workspaceDraftState.rows.length===1")
                check("search_preserves_global_badge", browser.evaluate("document.querySelector('#draftNavCount').textContent==='31'"), **context)
                browser.click_visible("[data-workspace-draft-open]")
                browser.until("activeRouteTarget==='compose'&&document.querySelector('#subject').value==='合成驗收草稿 05'")
                check("opens_selected_snapshot", True, **context)
                navigate("compose", mobile)
                browser.until("document.querySelector('#subject').value===''&&composeCloudDraftId===''")
                check("new_compose_blank_no_resume", browser.evaluate("!document.querySelector('#composeResumeDraft').getClientRects().length&&!document.querySelector('.compose-cloud-drafts').getClientRects().length"), **context)
                navigate("approvalLog", mobile)
                for tab in ("pending", "mine", "acted", "rejected"):
                    browser.click_visible(f'[data-approval-log-filter="{tab}"]')
                    browser.until(f"!officialWorkflowPage.loading&&officialWorkflowPage.dataQuery?.view==={json.dumps(tab)}")
                    check("approval_tab_" + tab, browser.evaluate(f"document.querySelector('[data-approval-log-filter={tab}]').getAttribute('aria-selected')==='true'"), **context)
                check("no_document_overflow", browser.evaluate("document.documentElement.scrollWidth<=innerWidth+1"), **context)
                browser.run("screenshot", str(output / f"{role}-{width}-approval.png"))
                navigate("drafts", mobile)
                browser.until("!workspaceDraftState.loading")
                browser.run("screenshot", str(output / f"{role}-{width}-drafts.png"))
                if width == 390:
                    navigate("compose", mobile)
                    browser.until("document.querySelector('#subject').value===''&&composeCloudDraftId===''")
                    attachment = Path(fixture.tmp.name) / "synthetic-local-attachment.pdf"
                    attachment.write_bytes(fixture._make_attachment_pdf(1))
                    browser.run("upload", "#attachments", str(attachment))
                    navigate("compose", mobile)
                    browser.until("!document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')")
                    check("unuploaded_attachment_requires_confirmation", browser.evaluate("document.querySelector('#workspaceTypedConfirmDescription').textContent.includes('尚未上傳的附件不會保存在文字草稿內')"), **context)
                    browser.click_visible("#workspaceTypedConfirmCancelBtn")
                    check("cancel_preserves_local_attachment", browser.evaluate("document.querySelector('#attachments').files.length===1"), **context)
                    navigate("compose", mobile)
                    browser.until("!document.querySelector('#workspaceTypedConfirmModal').classList.contains('hidden')")
                    browser.click_visible("#workspaceTypedConfirmSubmitBtn")
                    browser.until("document.querySelector('#attachments').files.length===0&&composeCloudDraftId===''")
                    check("explicit_confirmation_opens_blank_new_compose", True, **context)
    except Exception as error:
        report["error"] = str(error)
        try:
            report["diagnostic"] = browser.evaluate("(()=>{const e=document.querySelector('#mobileMenuButton'),r=e.getBoundingClientRect();return {width:innerWidth,route:activeRouteTarget,body:document.body.className,menu:e.outerHTML,rect:r.toJSON(),hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.outerHTML,ancestors:[e,e.parentElement,e.parentElement.parentElement,e.parentElement.parentElement.parentElement].map(x=>({tag:x.tagName,id:x.id,inert:x.inert,hidden:x.hidden,display:getComputedStyle(x).display,pointer:getComputedStyle(x).pointerEvents})),overlays:[...document.querySelectorAll('[role=dialog]:not(.hidden)')].map(x=>({id:x.id,text:x.textContent.slice(0,200)}))}})()")
            browser.run("screenshot", str(output / "failure.png"))
        except Exception: pass
        raise
    finally:
        try: browser.run("close")
        except Exception: pass
        fixture.tearDownClass()
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, action="append")
    args = parser.parse_args()
    result = run(args.output, args.width)
    print(json.dumps({"checks": len(result["checks"]), "passed": all(row["passed"] for row in result["checks"]), "report": str(args.output / "report.json")}))
