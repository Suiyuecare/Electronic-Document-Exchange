"""Exercise bounded dispatch pages and older pending work in a local fixture."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend
from tools.readiness_inbound_browser import login
from tools.six_role_browser_acceptance import Browser, AUDIT_JS, require_local_origin
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest


def run(output):
    fixture = FiveAccountHttpAcceptanceTest
    fixture.setUpClass()
    require_local_origin(fixture.origin)
    output.mkdir(parents=True, exist_ok=True)
    config = Path(fixture.tmp.name) / "p1-paging-browser.json"
    config.write_text(json.dumps({"headed": False}))
    browser = Browser(config, session="p1-dispatch-pages", namespace="p1-dispatch-pages")
    report = {"scope": "isolated_synthetic_http", "realSSOVerified": False, "journeys": []}
    try:
        ga = isolated_browser_session(fixture, "ga_chief", entity_id="E1")
        employee = isolated_browser_session(fixture, "staff", entity_id="E1")
        old = fixture._expect_json("POST", "/api/internal-dispatches", 201, token=ga["token"], json_body={
            "title": "舊案待回覆驗收", "subject": "舊案待回覆驗收", "body": "去識別化分頁驗收",
            "reply_required": True, "reply_due_days": 3,
            "idempotency_key": "p1-paging-seed-once",
            "recipients": [{"user_id": employee["user"]["id"], "action_required": True}],
        })
        with backend.connect() as conn:
            conn.execute("UPDATE internal_dispatches SET created_at='2000-01-01 00:00:00' WHERE id=?", (old["id"],))
            dispatch = dict(conn.execute("SELECT * FROM internal_dispatches WHERE id=?", (old["id"],)).fetchone())
            recipient = dict(conn.execute("SELECT * FROM internal_dispatch_recipients WHERE dispatch_id=?", (old["id"],)).fetchone())
            for index in range(320):
                row = {**dispatch, "id": f"P1-DISP-{index:04}", "title": f"已回覆合成派發 {index}",
                       "subject": f"已回覆合成派發 {index}", "status": "reply_completed", "reply_status": "completed",
                       "created_at": (datetime(2020, 1, 1) + timedelta(seconds=index)).strftime("%Y-%m-%d %H:%M:%S")}
                conn.execute("INSERT INTO internal_dispatches(" + ",".join(row) + ") VALUES(" + ",".join("?" for _ in row) + ")", tuple(row.values()))
                rec = {**recipient, "id": f"P1-REC-{index:04}", "dispatch_id": row["id"], "status": "replied", "replied_at": row["created_at"]}
                conn.execute("INSERT INTO internal_dispatch_recipients(" + ",".join(rec) + ") VALUES(" + ",".join("?" for _ in rec) + ")", tuple(rec.values()))
            conn.commit()
        for device in ("desktop", "mobile"):
            login(browser, fixture, employee, device)
            browser.click_visible('[data-inbound-section="dispatch"]')
            browser.until("internalDispatchLoadStatus==='loaded'&&internalDispatchItems.length===50")
            browser.evaluate("""(()=>{const original=window.fetch;window.__p1FailedPage=false;window.fetch=async function(input,init){if(!window.__p1FailedPage&&String(input).includes('/internal-dispatches?')&&String(input).includes('cursor=')){window.__p1FailedPage=true;throw new TypeError('Synthetic page read failure')}return original.call(this,input,init)};return true})()""")
            first_ids = browser.evaluate("internalDispatchItems.map(x=>x.id)")
            browser.click_visible('[data-dispatch-page="next"]')
            browser.until("internalDispatchLoadStatus==='error'")
            if browser.evaluate("internalDispatchItems.map(x=>x.id)") != first_ids:
                raise AssertionError("failed_page_replaced_current_records")
            if not browser.evaluate("document.querySelector('#internalDispatchLoadNotice').textContent.includes('保留')"):
                raise AssertionError("failed_page_has_no_recovery_message")
            pages, seen = 1, set(first_ids)
            while browser.evaluate("internalDispatchPageState.hasMore"):
                browser.click_visible('[data-dispatch-page="next"]')
                browser.until("internalDispatchLoadStatus==='loaded'&&internalDispatchPageState.history.length===" + str(pages))
                ids = browser.evaluate("internalDispatchItems.map(x=>x.id)")
                if len(ids) > 50 or seen.intersection(ids):
                    raise AssertionError("paging_is_unbounded_or_duplicates_records")
                seen.update(ids)
                pages += 1
            if len(seen) != 321 or old["id"] not in seen:
                raise AssertionError("older_dispatch_missing")
            browser.click_visible('[data-internal-dispatch-id="' + old["id"] + '"]')
            browser.until("Boolean(document.querySelector('#internalDispatchReplyText'))")
            browser.evaluate("document.querySelector('#internalDispatchDetail').scrollIntoView({block:'center'});true")
            browser.run("screenshot", str(output / (device + "-older-case.png")), "--full")
            browser.run("select", "#internalDispatchScopeFilter", "needs_reply")
            browser.until("internalDispatchLoadStatus==='loaded'&&internalDispatchPageState.needsReply&&internalDispatchItems.length===1")
            if browser.evaluate("internalDispatchItems[0].id") != old["id"]:
                raise AssertionError("pending_reply_filter_did_not_precede_pagination")
            layout = browser.evaluate(AUDIT_JS)
            if layout["overflow"] or layout["errors"]:
                raise AssertionError("paging_layout_or_runtime_error")
            browser.evaluate("document.querySelector('#internalDispatchScopeFilter').closest('label').scrollIntoView({block:'center'});true")
            browser.run("screenshot", str(output / (device + "-pending-filter.png")), "--full")
            report["journeys"].append({"device": device, "passed": True, "records": len(seen), "pages": pages,
                "maxRowsPerPage": 50, "failedPagePreservesRecords": True, "olderCaseReplyAvailable": True,
                "pendingFilterFindsOldest": True, "overflow": False})
        return report
    finally:
        try:
            browser.run("close")
        finally:
            fixture.tearDownClass()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output.resolve())
    (args.output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))
