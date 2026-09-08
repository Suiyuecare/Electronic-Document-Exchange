"""Real-browser form recovery checks using fresh, deidentified local fixtures.

No production login, provider, approval, or notification is exercised.
Before mode records defects; after mode requires their regression checks.
"""
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
from tools.six_role_browser_acceptance import Browser, TELEMETRY, AUDIT_JS, require_local_origin
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler


def run(output: Path, phase: str, roles: list[str], devices: list[str]) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    fixture = FiveAccountHttpAcceptanceTest
    original_head = QuietAcceptanceHandler.send_head

    def instrumented_head(handler):
        if urlparse(handler.path).path in {"/", "/index.html"}:
            data = (ROOT / "index.html").read_text().replace("<head>", "<head>" + TELEMETRY, 1).encode()
            handler.send_response(200)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            return io.BytesIO(data)
        return original_head(handler)

    report = {"phase": phase, "scope": "isolated_synthetic_local_no_submission", "rows": []}
    with mock.patch.object(QuietAcceptanceHandler, "send_head", instrumented_head):
        fixture.setUpClass()
        require_local_origin(fixture.origin)
        config = Path(fixture.tmp.name) / "compose-usability-browser.json"
        config.write_text(json.dumps({"allowedDomains": ["127.0.0.1", "fonts.googleapis.com", "fonts.gstatic.com"], "headed": False}))
        browser = Browser(config, session="cux-" + phase, namespace="cux09")
        try:
            for role in roles:
                auth = isolated_browser_session(fixture, role)
                for device in devices:
                    browser.run("set", "viewport", *("1440", "1000") if device == "desktop" else ("390", "844"))
                    browser.run("open", fixture.origin + "/assets/favicon-32.png")
                    browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                    browser.run("open", fixture.origin + f"/?usability={time.monotonic_ns()}#compose")
                    browser.until("window.__fixtureTiming?.appInteractiveMs&&document.querySelector('.view.active')?.id==='compose'&&document.querySelector('#composeApprovalCategorySelect').options.length>1")
                    browser.run("snapshot", "-i")
                    if not browser.evaluate("document.body.innerText.trim().length>0&&!document.querySelector('[data-nextjs-dialog],.vite-error-overlay')"):
                        raise AssertionError("browser_verification_failed")
                    row = {"role": role, "device": device}
                    prefix = f"{phase}-{role}-{device}"
                    browser.click_visible("#saveDispatchDraftBtn")
                    browser.until("!composeSaveInFlight")
                    row["incompleteSave"] = browser.evaluate("({tone:composeSaveState.tone,title:composeSaveState.title,focus:document.activeElement.id,categoryInvalid:document.querySelector('#composeApprovalCategorySelect').getAttribute('aria-invalid')})")
                    browser.run("screenshot", str(output / f"{prefix}-incomplete-save.png"))

                    category = browser.evaluate("[...document.querySelector('#composeApprovalCategorySelect').options].find(e=>e.textContent.includes('合作意向書')).value")
                    browser.run("select", "#composeApprovalCategorySelect", category)
                    for identity, value in {
                        "contactAddress": "測試市測試區測試路1號",
                        "contactOwner": "去識別化測試承辦人",
                        "contactPhone": "02-66045432 #123",
                        "contactEmail": "invalid-email",
                        "recipient": "去識別化測試受文單位",
                        "subject": "有關隔離測試資料更新一案，請查照。",
                        "bodyText": "一、本案僅供隔離驗收。\n二、不發送、不用印、不進行正式簽核。",
                    }.items():
                        browser.run("fill", "#" + identity, value)
                    browser.run("select", "#composeOutputMode", "electronic")
                    browser.click_visible("#composeNextBtn")
                    browser.until("!composeSaveInFlight")
                    row["invalidEmail"] = browser.evaluate("({step:activeComposeStep,focus:document.activeElement.id,emailInvalid:document.querySelector('#contactEmail').getAttribute('aria-invalid'),nativeInvalid:!document.querySelector('#contactEmail').validity.valid,documentId:currentComposeDraftId,toast:document.querySelector('#toast').textContent})")
                    browser.run("screenshot", str(output / f"{prefix}-invalid-email.png"))
                    if browser.evaluate("activeComposeStep==='confirm'"):
                        browser.click_visible("#composePrevBtn")
                    browser.run("fill", "#contactEmail", "fixture@example.test")
                    browser.click_visible("#composeNextBtn")
                    browser.until("activeComposeStep==='confirm'")
                    row["recovered"] = browser.evaluate("({step:activeComposeStep,number:document.querySelector('#dispatchNo').value,tone:composeSaveState.tone})")
                    row["confirmationBounds"] = browser.evaluate("Array.from(document.querySelectorAll('.compose-confirm-page,.compose-bottom-actions,#composePrevBtn')).filter(e=>e.getClientRects().length).map(e=>({id:e.id,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right,width:innerWidth}))")
                    browser.run("screenshot", str(output / f"{prefix}-confirm.png"))
                    browser.click_visible("#composePrevBtn")
                    browser.run("fill", "#contactOwner", "")
                    browser.run("fill", "#recipient", "")
                    browser.click_visible("#composeNextBtn")
                    row["validationOrder"] = browser.evaluate("({focus:document.activeElement.id,ownerInvalid:document.querySelector('#contactOwner').getAttribute('aria-invalid'),summary:document.querySelector('#composeValidationSummary')?.textContent||''})")
                    browser.run("screenshot", str(output / f"{prefix}-missing-fields.png"))
                    row["layout"] = browser.evaluate(AUDIT_JS)
                    row["checks"] = {
                        "incompleteSaveNotStuck": row["incompleteSave"]["tone"] != "saving",
                        "invalidEmailStopsBeforeConfirmation": row["invalidEmail"]["step"] == "fill",
                        "invalidEmailExplainedAtField": row["invalidEmail"]["emailInvalid"] == "true",
                        "correctionAllowsSaveAndConfirm": row["recovered"]["step"] == "confirm" and bool(row["recovered"]["number"]),
                        "firstErrorFollowsFormOrder": row["validationOrder"]["focus"] == "contactOwner",
                        "errorsAccessible": row["validationOrder"]["ownerInvalid"] == "true",
                        "noDocumentOverflow": not row["layout"]["overflow"],
                        "confirmationControlsFitViewport": all(rect["left"] >= -1 and rect["right"] <= rect["width"] + 1 for rect in row["confirmationBounds"]),
                        "noBrowserErrors": not row["layout"]["errors"],
                    }
                    report["rows"].append(row)
                    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
                    print(json.dumps({"role": role, "device": device, "checks": row["checks"]}), flush=True)
        except Exception:
            report["failure"] = browser.evaluate("({step:activeComposeStep,width:innerWidth,scrollWidth:document.documentElement.scrollWidth,errors:window.__fixtureErrors,rects:['#composeForm','.compose-confirm-page','#draftReviewPreview','#composePrevBtn','.compose-bottom-actions'].map(s=>({selector:s,rect:document.querySelector(s)?.getBoundingClientRect().toJSON()}))})")
            browser.run("screenshot", str(output / "failure.png"))
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            raise
        finally:
            try:
                browser.run("close")
            finally:
                fixture.tearDownClass()
    report["passed"] = all(all(row["checks"].values()) for row in report["rows"])
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("before", "after"), default="before")
    parser.add_argument("--roles", nargs="+", choices=("staff", "ceo"), default=["staff", "ceo"])
    parser.add_argument("--devices", nargs="+", choices=("desktop", "mobile"), default=["desktop", "mobile"])
    args = parser.parse_args()
    result = run(args.output, args.phase, args.roles, args.devices)
    raise SystemExit(int(args.phase == "after" and not result["passed"]))
