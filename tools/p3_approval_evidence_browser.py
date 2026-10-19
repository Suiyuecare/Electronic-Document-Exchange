"""P3 evidence wording through local HTTP and a real browser; no live services.

Run with --source-ref HEAD for a committed baseline without changing checkout
files. Synthetic actors, files and seals live only in a temporary fixture.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.six_role_browser_acceptance import Browser, require_local_origin
from tests.test_five_account_http_acceptance import (
    FiveAccountHttpAcceptanceTest as F,
    QuietAcceptanceHandler,
)


STATE = """(()=>{
 const evidence=document.querySelector('#officialDecisionEvidence');
 const form=document.querySelector('#officialDecisionForm');
 return {documentId:officialDecisionState.documentId,
  buttons:Object.fromEntries([...evidence.querySelectorAll('[data-decision-evidence]')].map(e=>[e.dataset.decisionEvidence,{text:e.textContent.trim(),title:e.title,disabled:e.disabled,complete:e.classList.contains('complete')}])),
  checks:Object.fromEntries(['Original','Attachments','Edited'].map(k=>{const e=document.querySelector('#officialReview'+k);return[k,{disabled:e.disabled,checked:e.checked}]})),
  submitDisabled:document.querySelector('#officialDecisionSubmitBtn').disabled,
  applicationReviewed:evidence.dataset.applicationReviewed,
  comment:document.querySelector('#officialApprovalComment').value,
  error:document.querySelector('#officialDecisionError').hidden?'':document.querySelector('#officialDecisionError').textContent,
  overflow:form.scrollWidth>form.clientWidth+1,
  widths:[...evidence.querySelectorAll('.decision-check span')].map(e=>e.getBoundingClientRect().width),
  downloads:window.__p3Downloads||[]};})()"""

RECORDER = """(()=>{
 window.__p3Downloads=[];window.__p3Errors=[];
 window.addEventListener('error',e=>window.__p3Errors.push(e.message));
 window.addEventListener('unhandledrejection',e=>window.__p3Errors.push(String(e.reason?.message||e.reason)));
 const original=window.fetch.bind(window);
 window.fetch=async(...args)=>{const response=await original(...args);
 const url=new URL(String(args[0]?.url||args[0]),location.href);
 if(url.origin===location.origin&&url.pathname.includes('/files/')&&url.pathname.endsWith('/download')){
   const bytes=await response.clone().arrayBuffer();
   const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
   window.__p3Downloads.push({path:url.pathname,status:response.status,bytes:bytes.byteLength,sha256:hash,type:response.headers.get('content-type')});
 }return response;};return true;})()"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("before", "after"), default="after")
    parser.add_argument("--source-ref", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = (subprocess.check_output(["git", "show", args.source_ref + ":app.js"], cwd=ROOT)
              if args.source_ref else (ROOT / "app.js").read_bytes())
    source_hashes = lambda: {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ("app.js", "styles.css", "index.html", "backend.py")}
    report = {"scope": "localhost_synthetic_not_production_or_real_sso", "mode": args.mode,
              "sourceSha256": hashlib.sha256(source).hexdigest(), "journeys": [],
              "actualApprovals": 0, "faults": [], "sourceHashesAtStart": source_hashes()}
    faults = {}
    original_head = QuietAcceptanceHandler.send_head
    original_get = QuietAcceptanceHandler.do_GET

    def serve_head(handler):
        if urlparse(handler.path).path == "/app.js":
            handler.send_response(200)
            handler.send_header("Content-Type", "application/javascript; charset=utf-8")
            handler.send_header("Content-Length", str(len(source)))
            handler.end_headers()
            return io.BytesIO(source)
        return original_head(handler)

    def serve_get(handler):
        path = urlparse(handler.path).path
        if faults.get(path, 0):
            faults[path] -= 1
            report["faults"].append({"path": path, "status": 503})
            handler.send_json({"error": "isolated_fixture_download_failure"}, 503)
            return
        original_get(handler)

    with mock.patch.object(QuietAcceptanceHandler, "send_head", serve_head), mock.patch.object(QuietAcceptanceHandler, "do_GET", serve_get):
        F.setUpClass()
        require_local_origin(F.origin)
        config = Path(F.tmp.name) / "p3-browser.json"
        config.write_text(json.dumps({"headed": False}))
        browser = Browser(config, session="p3-" + args.mode, namespace="p3-" + args.mode)
        original_api = F._expect_json.__func__
        captured = {}

        class SeedComplete(Exception):
            pass

        def capture(cls, method, path, expected, **kwargs):
            result = original_api(cls, method, path, expected, **kwargs)
            if method == "POST" and path.endswith("/files"):
                original_api(cls, method, path, expected, token=kwargs["token"], json_body={
                    "file_name": "isolated-second-attachment.pdf", "file_mime_type": "application/pdf",
                    "content_base64": base64.b64encode(F._make_attachment_pdf(902)).decode("ascii"),
                })
            if method == "POST" and path.endswith("/submit"):
                captured["detail"] = result
                raise SeedComplete()
            return result

        def approver(detail):
            step = next(row for row in detail["approval_steps"] if row["step_key"] == detail["current_step"])
            return F._token_for_user_id(step["approver_user_id"])

        def login(token, width):
            auth = {**F._expect_json("GET", "/api/auth/me", 200, token=token), "token": token}
            browser.run("open", F.origin + "/assets/favicon-32.png")
            browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
            browser.run("set", "viewport", str(width), "1000" if width > 600 else "844")
            browser.run("open", F.origin + "/#approvalLog")
            browser.until("typeof hasAuthenticatedBackendSession==='function'&&hasAuthenticatedBackendSession()&&!document.querySelector('#moduleEntryProgress')?.getClientRects().length")
            browser.evaluate(RECORDER)

        def open_case(document_id):
            report["stage"] = "open_case:" + document_id
            browser.evaluate("(async()=>{await openOfficialCaseFromNavigation(" + json.dumps(document_id) + ",{tab:'pending'});return true})()")
            browser.until("officialDocumentDetailReady.has(" + json.dumps(document_id) + ")&&!officialCaseNavigation.loading")
            # The application scrolls its detail panel into view asynchronously.
            # Wait for that ordinary animation before the harness centers the
            # decision button; competing scrolls can strand it below the viewport.
            browser.evaluate("window.__p3CaseLayout=null;true")
            browser.until("(()=>{const e=document.querySelector('#approvalLogDetail [data-progress-official-action=approve]');if(!e)return false;const r=e.getBoundingClientRect(),key=[r.x,r.y,r.width,r.height].join(','),now=performance.now();if(window.__p3CaseLayout?.key!==key)window.__p3CaseLayout={key,since:now};return now-window.__p3CaseLayout.since>=300})()")
            browser.click_visible('#approvalLogDetail [data-progress-official-action="approve"]')
            browser.until("document.querySelector('#officialDecisionModal').getClientRects().length>0")

        def action(kind):
            report["stage"] = "evidence:" + kind
            browser.click_visible('[data-decision-evidence="' + kind + '"]')
            browser.until("(()=>{const button=document.querySelector('[data-decision-evidence=" + kind + "]');return button.classList.contains('complete')||!button.disabled})()")
            return browser.evaluate(STATE)

        def snapshot(name):
            browser.evaluate("document.querySelector('#officialDecisionForm').scrollTop=0;true")
            browser.run("screenshot", str(args.output / (name + ".png")), "--full")

        def assert_reset(state, document_id):
            assert state["documentId"] == document_id, state
            assert all(not item["checked"] and item["disabled"] for item in state["checks"].values()), state
            assert all(not item["complete"] for item in state["buttons"].values()), state
            assert state["applicationReviewed"] == "false" and state["submitDisabled"], state

        def assert_not_acknowledged(state, kind, checkbox):
            assert state["buttons"][kind]["complete"], state
            assert state["checks"][checkbox] == {"checked": False, "disabled": False}, state
            assert state["submitDisabled"], state

        try:
            case = dict(next(row for row in F.case_definitions if row["role"] == "staff"))
            case.update(route="D", category="採購合約", orientations=("portrait",))
            applicant = F._portal_session(case["email"])
            # Create a normal no-attachment/no-edited-PDF official letter through
            # the real API; this is not a damaged locked editor document.
            empty = F._expect_json("POST", "/api/official-documents", 201, token=applicant, json_body={
                "id": "OD-P3-" + uuid.uuid4().hex, "source_type": "blank_editor",
                "document_type": "outgoing_official_document", "company_id": case["company_id"],
                "title": "隔離驗收：沒有附件與編輯版本", "subject": "隔離驗收公文，請查照。",
                "description": "一、本函為去識別化的介面驗收資料。", "recipient": "隔離驗收收文單位",
                "request_reason": "檢核無檔案的確認文字", "document_category": case["category"],
                "output_mode": "electronic", "dispatch_method": "email_by_general_affairs",
                "metadata": {"contact_email": "isolated@example.test"}, "submit": False,
            })
            empty = F._expect_json("POST", "/api/official-documents/" + empty["id"] + "/submit", 200, token=applicant, json_body={})
            F._expect_json = classmethod(capture)
            try:
                F._run_case(case, {case["ordinal"]: applicant})
            except SeedComplete:
                pass
            finally:
                F._expect_json = classmethod(original_api)
            full = captured["detail"]
            token = approver(full)
            assert token == approver(empty), "fixture_approvers_differ"
            attachments = [row for row in full["files"] if row["file_type"] == "attachment"]
            assert len(attachments) == 2, "fixture_requires_two_attachments"
            originals = [row for row in full["files"] if row["file_type"] == "original_pdf"]
            assert len(originals) == 1
            baseline = {item["id"]: {"status": item["current_status"], "contentRevision": item["content_revision"],
                        "request": item.get("stamp_request"), "editorRevision": item.get("editor_revision")}
                        for item in (empty, full)}
            for width in (1440, 390):
                login(token, width)
                row = {"viewport": width, "states": {}}
                open_case(empty["id"])
                state = browser.evaluate(STATE)
                assert_reset(state, empty["id"])
                if args.mode == "after":
                    assert state["buttons"]["attachments"]["text"] == "確認沒有附件", state
                    assert state["buttons"]["editor"]["text"] == "確認無編輯內容", state
                row["states"]["emptyInitial"] = state
                snapshot(f"empty-{width}-initial")
                browser.run("fill", "#officialApprovalComment", "隔離驗收意見應保留")
                action("application")
                action("source")
                for kind, checkbox, expected in (("attachments", "Attachments", "已確認無附件"), ("editor", "Edited", "已確認無編輯內容")):
                    before = len(browser.evaluate("window.__p3Downloads"))
                    state = action(kind)
                    assert_not_acknowledged(state, kind, checkbox)
                    assert state["buttons"][kind]["text"] == expected, state
                    assert "已下載" not in state["buttons"][kind]["title"], state
                    assert len(state["downloads"]) == before, "empty_confirmation_downloaded_a_file"
                assert state["buttons"]["source"]["text"].startswith("已下載｜"), state
                assert state["comment"] == "隔離驗收意見應保留", state
                assert not state["overflow"] and min(state["widths"]) > 150, state
                row["states"]["emptyConfirmed"] = state
                snapshot(f"empty-{width}-confirmed")
                for checkbox in ("Original", "Attachments", "Edited"):
                    selector = "#officialReview" + checkbox
                    browser.evaluate("document.querySelector(" + json.dumps(selector) + ").scrollIntoView({block:'center',behavior:'instant'});document.querySelector(" + json.dumps(selector) + ").focus();true")
                    browser.run("press", "Space")
                    browser.until("document.querySelector(" + json.dumps(selector) + ").checked")
                browser.until("!document.querySelector('#officialDecisionSubmitBtn').disabled")
                row["manualAcknowledgementsEnableGate"] = True
                browser.click_visible("#officialDecisionCancelBtn")
                open_case(full["id"])
                assert_reset(browser.evaluate(STATE), full["id"])
                row["newCaseReset"] = True
                browser.run("fill", "#officialApprovalComment", "隔離驗收意見應保留")
                source_path = f"/api/official-documents/{full['id']}/files/{originals[0]['id']}/download"
                faults[source_path] = 1
                state = action("source")
                assert not state["buttons"]["source"]["complete"] and not state["buttons"]["source"]["disabled"], state
                assert state["checks"]["Original"] == {"checked": False, "disabled": True}, state
                assert state["submitDisabled"] and state["error"] and state["comment"] == "隔離驗收意見應保留", state
                row["states"]["sourceFailed"] = state
                state = action("source")
                assert_not_acknowledged(state, "source", "Original")
                assert not state["error"] and state["buttons"]["source"]["text"].startswith("已下載｜"), state
                row["states"]["sourceRetried"] = state
                second_path = f"/api/official-documents/{full['id']}/files/{attachments[1]['id']}/download"
                faults[second_path] = 1
                start = len(state["downloads"])
                state = action("attachments")
                assert [request["status"] for request in state["downloads"][start:]] == [200, 503], state
                assert not state["buttons"]["attachments"]["complete"], state
                assert state["checks"]["Attachments"] == {"checked": False, "disabled": True}, state
                row["states"]["attachmentsPartiallyFailed"] = state
                snapshot(f"files-{width}-partial-failure")
                state = action("attachments")
                assert_not_acknowledged(state, "attachments", "Attachments")
                assert state["buttons"]["attachments"]["text"].startswith("已下載｜"), state
                assert not state["error"], state
                row["states"]["attachmentsRetried"] = state
                state = action("editor")
                assert_not_acknowledged(state, "editor", "Edited")
                assert state["buttons"]["editor"]["text"].startswith("已下載｜"), state
                assert not state["overflow"] and min(state["widths"]) > 150, state
                row["states"]["filesDownloaded"] = state
                snapshot(f"files-{width}-downloaded")
                expected_hashes = {f"/api/official-documents/{item['id']}/files/{file['id']}/download": file.get("file_hash") for item in (empty, full) for file in item["files"]}
                for download in state["downloads"]:
                    if download["status"] == 200:
                        assert download["bytes"] > 0 and download["type"].startswith("application/pdf"), download
                        assert download["sha256"] == str(expected_hashes[download["path"]] or "").lower(), download
                row["actualPdfResponsesMatchImmutableHashes"] = True
                browser.click_visible("#officialDecisionCancelBtn")
                open_case(empty["id"])
                assert_reset(browser.evaluate(STATE), empty["id"])
                row["returningCaseAlsoReset"] = True
                browser.click_visible("#officialDecisionCancelBtn")
                row["browserErrors"] = browser.evaluate("window.__p3Errors")
                assert not row["browserErrors"], row["browserErrors"]
                report["journeys"].append(row)
                print(json.dumps({"viewport": width, "passed": True}), flush=True)
            for item in (empty, full):
                fresh = F._expect_json("GET", "/api/official-documents/" + item["id"], 200, token=token)
                same = {"status": fresh["current_status"], "contentRevision": fresh["content_revision"], "request": fresh.get("stamp_request"), "editorRevision": fresh.get("editor_revision")}
                assert baseline[item["id"]] == same, "review_changed_case_data"
                assert not any(log.get("action") == "approve" for log in fresh["logs"]), "unexpected_approval"
            report.update(passed=True, caseDataUnchanged=True, noAutomaticAcknowledgements=True)
        except Exception as error:
            report.update(passed=False, error=str(error)[:12000])
            try:
                report["failureState"] = browser.evaluate(STATE)
            except Exception:
                pass
            try:
                snapshot("failure")
            except Exception:
                pass
        finally:
            F._expect_json = classmethod(original_api)
            report["sourceHashesAtEnd"] = source_hashes()
            report["sourceStableDuringRun"] = report["sourceHashesAtStart"] == report["sourceHashesAtEnd"]
            if not report["sourceStableDuringRun"]:
                report.update(passed=False, error="source_changed_during_acceptance")
            (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            try:
                browser.run("close")
            finally:
                F.tearDownClass()
    print(json.dumps({"passed": report.get("passed", False), "journeys": len(report["journeys"]), "report": str(args.output / "report.json")}))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
