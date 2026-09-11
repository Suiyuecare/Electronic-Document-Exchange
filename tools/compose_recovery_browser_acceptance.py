"""Real-browser, localhost-only compose recovery and contact disclosure regression."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import sys
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler
from tests.support.five_account_browser_fixture import isolated_browser_session
from tools.six_role_browser_acceptance import Browser, TELEMETRY, require_local_origin


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="tests/.artifacts/compose-recovery")
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    fixture = FiveAccountHttpAcceptanceTest
    original = QuietAcceptanceHandler.send_head

    def instrumented(handler):
        if urlparse(handler.path).path in {"/", "/index.html"}:
            data = (ROOT / "index.html").read_text().replace("<head>", "<head>" + TELEMETRY, 1).encode()
            handler.send_response(200)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            return io.BytesIO(data)
        return original(handler)

    report = {}
    with mock.patch.object(QuietAcceptanceHandler, "send_head", instrumented):
        fixture.setUpClass()
        require_local_origin(fixture.origin)
        (output / "browser-config.json").write_text(json.dumps({"allowedDomains": ["127.0.0.1", "localhost"], "headed": False}))
        browser = Browser(output / "browser-config.json", session="composefix0912b", namespace="composefix0912b")
        try:
            auth = isolated_browser_session(fixture, "staff")
            browser.run("set", "viewport", "1440", "1000")
            browser.run("open", fixture.origin + "/assets/favicon-32.png")
            browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
            browser.run("open", fixture.origin + "/?compose-recovery=acceptance#compose")
            browser.until("window.__fixtureTiming?.appInteractiveMs&&document.querySelector('.view.active')?.id==='compose'&&document.querySelector('#composeApprovalCategorySelect').options.length>1")
            browser.run("snapshot", "-i")
            browser.run("screenshot", str(output / "01-ready.png"))
            assert browser.evaluate("document.body.innerText.trim().length>0&&!document.querySelector('[data-nextjs-dialog],.vite-error-overlay')")
            browser.run("fill", "#documentPurpose", "隔離驗收第一版公文用途")
            browser.until("composeSaveState.title==='私人雲端草稿已保存'&&!composeCloudOperation")
            first = browser.evaluate("composeCloudDraftId")
            browser.run("fill", "#documentPurpose", "隔離驗收第二版公文用途")
            browser.until("composeSaveState.title==='私人雲端草稿已保存'&&!composeCloudOperation&&composeCloudRevisions.get(composeCloudDraftId)>=2")
            before = browser.evaluate("({id:composeCloudDraftId,revision:composeCloudRevisions.get(composeCloudDraftId),savedRevision:JSON.parse(localStorage.getItem(composeAutosaveStorageKey)).cloudRevision})")
            assert before["revision"] == before["savedRevision"] == 2, before
            # Upgrade compatibility: the previously deployed client kept the
            # content but omitted this local token. An exact cloud match is safe.
            browser.evaluate("{const saved=JSON.parse(localStorage.getItem(composeAutosaveStorageKey));delete saved.cloudRevision;localStorage.setItem(composeAutosaveStorageKey,JSON.stringify(saved));}true")
            browser.run("reload")
            browser.until("window.__fixtureTiming?.appInteractiveMs&&document.querySelector('.view.active')?.id==='compose'&&!document.querySelector('#composeResumeDraft').hidden&&composeCloudRows.length===1")
            browser.run("snapshot", "-i")
            browser.run("screenshot", str(output / "02-explicit-recovery.png"))
            assert browser.evaluate("document.querySelector('#documentPurpose').value===''"), "Must not silently restore"
            browser.click_visible("#composeResumeDraftBtn")
            browser.until("document.querySelector('#documentPurpose').value==='隔離驗收第二版公文用途'")
            resumed = browser.evaluate("({id:composeCloudDraftId,revision:composeCloudRevisions.get(composeCloudDraftId),promptHidden:document.querySelector('#composeResumeDraft').hidden})")
            assert resumed == {"id": first, "revision": 2, "promptHidden": True}, resumed
            browser.run("snapshot", "-i")
            browser.run("fill", "#documentPurpose", "隔離驗收第三版公文用途")
            browser.until("composeSaveState.title==='私人雲端草稿已保存'&&!composeCloudOperation&&composeCloudRevisions.get(composeCloudDraftId)===3")
            with backend.connect() as conn:
                rows = conn.execute("SELECT id,revision,snapshot_json FROM official_document_compose_drafts WHERE applicant_id=?", (auth["user"]["id"],)).fetchall()
            assert len(rows) == 1 and rows[0]["id"] == first and rows[0]["revision"] == 3
            assert json.loads(rows[0]["snapshot_json"])["values"]["#documentPurpose"] == "隔離驗收第三版公文用途"
            report["sameDraftResumedWithoutDuplicate"] = {"before": before, "after": resumed, "legacyMissingTokenRecoveredByExactSnapshot": True, "persistedRevision": 3, "rowCount": len(rows)}
            browser.run("screenshot", str(output / "03-recovered-saved.png"))
            browser.run("reload")
            browser.until("window.__fixtureTiming?.appInteractiveMs&&!document.querySelector('#composeResumeDraft').hidden")
            browser.run("snapshot", "-i")
            browser.click_visible("#composeStartFreshBtn")
            assert browser.evaluate("document.querySelector('#composeResumeDraft').hidden&&document.querySelector('#documentPurpose').value===''")
            browser.run("fill", "#documentPurpose", "隔離驗收明確新增另一份公文")
            browser.until("composeSaveState.title==='私人雲端草稿已保存'&&!composeCloudOperation")
            second = browser.evaluate("composeCloudDraftId")
            assert second != first
            with backend.connect() as conn:
                rows = conn.execute("SELECT id,revision FROM official_document_compose_drafts WHERE applicant_id=?", (auth["user"]["id"],)).fetchall()
            assert len(rows) == 2 and next(row for row in rows if row["id"] == first)["revision"] == 3
            report["explicitNewDraftPreservesPrior"] = {"rowCount": 2, "priorRevision": 3}
            browser.run("set", "viewport", "390", "844")
            browser.run("snapshot", "-i")
            browser.evaluate("document.querySelector('#contactAddress').value='隔離測試地址';document.querySelector('#contactEmail').value='fixture@example.invalid';renderComposeContactSummary();document.querySelector('#composeContactToggleBtn').setAttribute('aria-expanded','false');renderComposeContactSummary();true")
            contacts = browser.evaluate("({phoneVisible:document.querySelector('#contactPhone').getBoundingClientRect().height>=44,addressHidden:document.querySelector('#contactAddress').closest('label').hidden,expanded:document.querySelector('#composeContactToggleBtn').getAttribute('aria-expanded'),overflow:document.documentElement.scrollWidth>innerWidth})")
            assert contacts == {"phoneVisible": True, "addressHidden": True, "expanded": "false", "overflow": False}, contacts
            browser.click_visible("#composeContactToggleBtn")
            assert browser.evaluate("!document.querySelector('#contactAddress').closest('label').hidden")
            browser.run("snapshot", "-i")
            browser.click_visible("#composeContactToggleBtn")
            browser.evaluate("setComposeFieldValidity('#contactEmail',null,false,'測試錯誤');focusComposeValidationField('#contactEmail');true")
            assert browser.evaluate("!document.querySelector('#contactEmail').closest('label').hidden&&document.activeElement.id==='contactEmail'")
            report["mobileContactDisclosure"] = {**contacts, "errorAutoExpandsAndFocuses": True}
            browser.run("screenshot", str(output / "04-mobile-contact-error.png"))
            browser.evaluate("document.querySelector('#contactEmail').value='fixture@example.invalid';setComposeFieldValidity('#contactEmail',null,true,'');setView('dashboard');true")
            browser.until("document.querySelector('.view.active')?.id==='dashboard'")
            browser.run("snapshot", "-i")
            browser.evaluate("setView('compose');true")
            browser.until("document.querySelector('.view.active')?.id==='compose'")
            assert browser.evaluate("document.querySelector('#documentPurpose').value==='隔離驗收明確新增另一份公文'")
            errors = browser.evaluate("window.__fixtureErrors||[]")
            assert not errors, errors
            report["navigationPreservesInput"] = True
            report["javascriptErrors"] = errors
            report["status"] = "passed"
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            try:
                browser.run("close")
            finally:
                fixture.tearDownClass()


if __name__ == "__main__":
    main()
