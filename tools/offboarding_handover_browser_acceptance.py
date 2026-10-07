"""Loopback-only browser -> authenticated API -> SQLite handover acceptance.

Synthetic Finance sessions are test fixtures, never proof of human SSO.
No real employee is disabled. Only synthetic seals are rendered; no mail or
external document exchange is sent.
"""
import json
import io
import base64
import copy
from pathlib import Path
import sys
import tempfile
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend
from tests.support.five_account_browser_fixture import isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as Fixture, QuietAcceptanceHandler
from tools.six_role_browser_acceptance import Browser, VIEWPORTS, TELEMETRY, require_local_origin
from tools.fluid_experience_browser_acceptance import HIT_AREA_AUDIT_JS, navigate


def complete_linked_http_case(document_id, session, original_id, original):
    """Continue the actual browser-created case, never a replacement fixture.

    Synthetic seals/storage only. Each new reviewer must download the fresh
    package; copied approvals or a missing review may not complete this case.
    """
    require_local_origin(Fixture.origin)
    # The base fixture's reviewers deliberately have no applicant hierarchy.
    # Complete the synthetic successor's organization data for this new
    # applicant scenario; do not disable the production readiness guard.
    email = session["user"]["email"]
    snapshot = Fixture.snapshots_by_email[email]
    assert email.endswith("@example.test") and snapshot["identity"]["role"] == "department_head"
    source = next(item for item in Fixture.snapshots_by_email.values()
        if item["workflowReady"] and item["identity"]["entityId"] == snapshot["identity"]["entityId"])
    snapshot["actors"] = copy.deepcopy(source["actors"])
    snapshot["workflowReady"] = True
    # Browser fixtures seed a local session, while production-branch workflow
    # tests use the isolated Portal assertion boundary. Refresh this exact
    # synthetic identity, never substitute another actor or bypass Finance.
    token = Fixture._token_for_user_id(session["user"]["id"])
    path = f"/api/official-documents/{document_id}"
    case = {"ordinal": 90, "company_id": session["user"]["company_id"], "orientations": ["portrait"]}
    revision = Fixture._expect_json("GET", path+"/editor-state", 200, token=token)
    state = Fixture._editor_state(revision, case)
    saved = Fixture._expect_json("PUT", path+"/editor-state", 200, token=token, json_body={
        "revisionNo": revision["revisionNo"], "baseManifestSha256": revision["manifestSha256"], "state": state})
    Fixture._expect_json("POST", path+"/files", 201, token=token, json_body={
        "file_name": "synthetic-linked-attachment.pdf", "file_mime_type": "application/pdf",
        "content_base64": base64.b64encode(Fixture._make_attachment_pdf(90)).decode("ascii")})
    snapshot = Fixture._expect_json("GET", path, 200, token=token)
    prepared = Fixture._expect_json("POST", path+"/editor-preflight", 201, token=token, json_body={
        "editorRevisionId": saved["id"], "manifestSha256": saved["manifestSha256"]})
    detail = Fixture._expect_json("POST", path+"/submit", 200, token=token, json_body={
        "editorRevisionId": prepared["editorRevisionId"], "manifestSha256": prepared["manifestSha256"],
        "preparedFileId": prepared["preparedFileId"], "preparedSha256": prepared["preparedSha256"],
        "expected_content_revision": snapshot["content_revision"], "comment": "關聯新案隔離送簽"})
    expected = [step["key"] for step in backend.official_workflow_steps_for_finance_applicant("A", "department_head")]
    assert [step["step_key"] for step in detail["approval_steps"]] == expected
    reviews = 0
    while detail["current_status"] not in {"stamped", "stamping_failed"}:
        assert any(item["step_key"] == detail["current_step"] for item in detail["approval_steps"]), {
            "status": detail["current_status"], "step": detail["current_step"],
            "stampStatus": (detail.get("stamp_request") or {}).get("status"),
            "steps": [item["step_key"] for item in detail["approval_steps"]]}
        step = next(item for item in detail["approval_steps"] if item["step_key"] == detail["current_step"])
        reviewer = Fixture._token_for_user_id(step["approver_user_id"])
        payload = {"expected_step_id": step["id"], "comment": "關聯新案重新審閱",
            "prepared_sha256": detail["stamp_request"]["prepared_sha256"],
            "manifest_sha256": detail["stamp_request"]["editor_manifest_sha256"],
            "review_acknowledgements": {"original_reviewed": True, "edited_version_reviewed": True, "attachments_reviewed": True}}
        denied = Fixture._request("POST", path+"/approve", token=reviewer, json_body=payload)
        assert denied.status in {400, 409, 422}, f"new review guard returned unexpected status {denied.status}"
        assert str(denied.json().get("detail", "")).split(":", 1)[0] in {
            "official_document_review_session_not_started", "official_document_review_access_required"}, denied.json()
        for file in detail["files"]:
            if file["file_type"] not in {"original_pdf", "prepared_pdf", "attachment"}:
                continue
            downloaded = Fixture._request("GET", path+f"/files/{file['id']}/download", token=reviewer)
            assert downloaded.status == 200 and downloaded.body
        detail = Fixture._expect_json("POST", path+"/approve", 200, token=reviewer, json_body=payload)
        reviews += 1
    assert detail["current_status"] == "stamped"
    file = next(item for item in detail["files"] if item["file_type"] == "stamped_pdf")
    downloaded = Fixture._request("GET", path+f"/files/{file['id']}/download", token=token)
    assert downloaded.status == 200 and downloaded.body.startswith(b"%PDF")
    assert backend.sha256_bytes(downloaded.body) == file["file_hash"]
    detail = Fixture._expect_json("POST", path+"/confirm", 200, token=token, json_body={"comment": "關聯新案收件驗收"})
    assert detail["current_status"] == "closed"
    with backend.connect() as conn:
        assert backend.official_document_row(conn, original_id) == original
        assert not backend.official_document_steps(conn, original_id)
        metadata = backend.parse_json_any(backend.official_document_row(conn, document_id)["metadata_json"], {})
        assert metadata["linked_application"]["original_document_id"] == original_id
    return {"stage": "linked_full_http_approval", "reviewedNewSteps": reviews,
        "freshReviewRequired": True, "stampedPDFDownloaded": True, "closed": True, "originalUnchanged": True}


def main():
    output = ROOT / "tests/.artifacts/offboarding-handover-20261007"
    output.mkdir(parents=True, exist_ok=True)
    report = {"scope": "isolated_loopback_synthetic_finance_not_human_sso", "humanSSOVerified": False, "journeys": []}
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
    telemetry = mock.patch.object(QuietAcceptanceHandler, "send_head", instrumented_head)
    telemetry.start()
    Fixture.setUpClass()
    browser = None
    try:
        require_local_origin(Fixture.origin)
        sessions = {role: isolated_browser_session(Fixture, role, entity_id="E1") for role in ("ga_chief", "admin_director", "department_head", "staff")}
        with tempfile.TemporaryDirectory(prefix="edoc-handover-browser-") as temporary:
            config = output / "browser.json"
            config.write_text(json.dumps({"headed": False}))
            browser = Browser(config, session="edoc-handover-20261007", namespace="edoc-handover-isolated")

            def login(role, device):
                sessions[role] = isolated_browser_session(Fixture, role, entity_id="E1")
                Fixture._expect_json("GET", "/api/auth/me", 200, token=sessions[role]["token"])
                browser.run("set", "viewport", *map(str, VIEWPORTS[device]))
                browser.run("open", Fixture.origin + "/assets/favicon-32.png")
                browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(sessions[role])) + ");true")
                browser.run("open", Fixture.origin + "/#dashboard")
                browser.until("typeof hasAuthenticatedBackendSession==='function'&&hasAuthenticatedBackendSession()&&!document.querySelector('#appShell').inert&&!!officialHandoverController")
                browser.until("!!document.querySelector('.sidebar .nav-item[data-target=approvalLog]')&&getComputedStyle(document.querySelector('.sidebar .nav-item[data-target=approvalLog]')).display!=='none'&&!document.querySelector('#moduleEntryProgress')?.getClientRects().length")
                navigate(browser, "approvalLog", device)

            for device in VIEWPORTS:
                identity = "HANDOVER-BROWSER-" + device.upper()
                ga = sessions["ga_chief"]["user"]
                successor = sessions["department_head"]["user"]
                applicant = sessions["staff"]["user"]
                former = "FORMER-BROWSER-" + device.upper()
                with backend.connect() as conn:
                    row = dict(conn.execute("SELECT * FROM users WHERE id=?", (successor["id"],)).fetchone())
                    row.update(id=former, auth_user_id=None, logging_account_id=former,
                               finance_employee_id=former, email=former.lower()+"@example.invalid", name="離職驗收人員", status="停用")
                    backend.insert_row(conn, "users", row)
                    backend.insert_row(conn, "official_documents", {"id": identity, "source_type": "blank_editor", "company_id": ga["company_id"], "applicant_id": applicant["id"], "title": "隔離交接驗收", "subject": "離職待簽交接－" + device, "current_status": "pending_department_head", "current_step": "department_head", "content_revision": 1, "metadata_json": "{}", "created_at": backend.now(), "updated_at": backend.now()})
                    for order, key, person in ((1, "department_head", former), (2, "applicant_confirm", applicant["id"])):
                        backend.insert_row(conn, "official_document_approval_steps", {"id": identity + "-STEP-" + str(order), "document_id": identity, "workflow_generation": 1, "step_order": order, "step_key": key, "step_name": key, "approver_user_id": person, "approver_name": person, "approver_role": "主任" if order == 1 else "員工", "status": "pending", "decision_evidence_json": "{}", "created_at": backend.now(), "updated_at": backend.now()})
                    conn.commit()
                login("ga_chief", device)
                browser.click_visible("#officialHandoverOpenBtn")
                browser.until("!!document.querySelector('[data-handover-document=" + identity + "]')")
                browser.click_visible('[data-handover-document="' + identity + '"]')
                browser.until("!!document.querySelector('#officialHandoverSuccessor')")
                browser.run("select", "#officialHandoverSuccessor", successor["id"])
                browser.run("fill", "#officialHandoverReason", "隔離驗收：離職後由同職級人員接任")
                browser.click_visible("#officialHandoverProposalForm button[type=submit]")
                browser.until("!document.querySelector('#officialHandoverModal').classList.contains('hidden')")
                assert browser.evaluate("document.activeElement.id==='officialHandoverModalCancel'")
                browser.run("press", "Escape")
                assert browser.evaluate("document.querySelector('#officialHandoverReason').value.includes('隔離驗收')")
                browser.click_visible("#officialHandoverProposalForm button[type=submit]")
                browser.run("check", "#officialHandoverAcknowledgement")
                browser.click_visible("#officialHandoverModalSubmit")
                browser.until("document.querySelector('#officialHandoverModal').classList.contains('hidden')&&document.querySelector('#officialHandoverDetail').textContent.includes('待行政主任確認')")
                with backend.connect() as conn:
                    assert conn.execute("SELECT status FROM official_document_approval_steps WHERE id=?", (identity+"-STEP-1",)).fetchone()[0] == "pending"
                    operation = conn.execute("SELECT id FROM official_document_handovers WHERE document_id=?", (identity,)).fetchone()[0]
                report["journeys"].append({"device": device, "stage": "ga_proposal", **browser.evaluate(HIT_AREA_AUDIT_JS)})
                browser.run("screenshot", str(output / (device + "-proposal.png")), "--full")

                login("admin_director", device)
                browser.click_visible("#officialHandoverOpenBtn")
                browser.click_visible('[data-handover-view="pending"]')
                browser.until("!!document.querySelector('[data-handover-document=" + identity + "]')")
                browser.click_visible('[data-handover-document="' + identity + '"]')
                browser.until("!!document.querySelector(" + json.dumps('[data-handover-confirm="' + operation + '"]') + ")")
                browser.click_visible('[data-handover-confirm="' + operation + '"]')
                browser.run("check", "#officialHandoverAcknowledgement")
                browser.click_visible("#officialHandoverModalSubmit")
                browser.until("document.querySelector('#officialHandoverModal').classList.contains('hidden')&&document.querySelector('#officialHandoverDetail').textContent.includes('已確認交接')")
                with backend.connect() as conn:
                    steps = backend.current_official_document_steps(conn, identity)
                    assert steps[0]["approver_user_id"] == successor["id"]
                    assert steps[0]["status"] == "pending"
                    assert steps[0]["decision_actor_user_id"] is None
                    assert backend.official_document_row(conn, identity)["applicant_id"] == applicant["id"]
                    assert conn.execute("SELECT count(*) FROM notifications WHERE source=?", (identity,)).fetchone()[0] > 0
                report["journeys"].append({"device": device, "stage": "director_confirm", "actualDatabaseReassignment": True, "noDocumentApproval": True, **browser.evaluate(HIT_AREA_AUDIT_JS)})
                browser.run("screenshot", str(output / (device + "-confirmed.png")), "--full")

                # Separate synthetic departed applicant; never disable a
                # fixture's active Finance identity or impersonate a human.
                linked_origin = "LINKED-BROWSER-" + device.upper()
                departed = "APPLICANT-BROWSER-" + device.upper()
                with backend.connect() as conn:
                    row = dict(conn.execute("SELECT * FROM users WHERE id=?", (applicant["id"],)).fetchone())
                    row.update(id=departed, auth_user_id=None, logging_account_id=departed, finance_employee_id=departed,
                        email=departed.lower()+"@example.invalid", name="離職申請驗收人員", status="停用")
                    backend.insert_row(conn, "users", row)
                    backend.insert_row(conn, "official_documents", {"id": linked_origin, "source_type": "uploaded_pdf", "company_id": ga["company_id"],
                        "applicant_id": departed, "title": "關聯新案隔離驗收", "subject": "關聯新案－"+device, "current_status": "rejected",
                        "dispatch_method": backend.official_document_dispatch_method("uploaded_pdf"),
                        "metadata_json": "{}", "created_at": backend.now(), "updated_at": backend.now()})
                    before = backend.official_document_row(conn, linked_origin)
                    conn.commit()
                context = Fixture._expect_json("GET", f"/api/official-documents/{linked_origin}/handover-context", 200, token=sessions["ga_chief"]["token"])
                proposal = Fixture._expect_json("POST", f"/api/official-documents/{linked_origin}/handovers", 200, token=sessions["ga_chief"]["token"], json_body={
                    "operation_id": "LINKED-HANDOVER-"+device.upper(), "kind": "followup_owner", "former_user_id": departed,
                    "successor_user_id": successor["id"], "reason": "隔離驗收：離職申請保留原案另立新案", "expected_fingerprint": context["expected_fingerprint"]})
                Fixture._expect_json("POST", f"/api/official-handovers/{proposal['request']['id']}/confirm", 200, token=sessions["admin_director"]["token"], json_body={})
                login("department_head", device)
                browser.until("!!document.querySelector('[data-approval-log-select*=LINKED-BROWSER]')")
                browser.click_visible('[data-approval-log-select*="'+linked_origin+'"]')
                browser.until("!!document.querySelector('[data-linked-official-id="+linked_origin+"]')")
                browser.click_visible('[data-linked-official-id="'+linked_origin+'"]')
                browser.until("!document.querySelector('#officialHandoverModal').classList.contains('hidden')")
                assert browser.evaluate("document.querySelector('#officialHandoverModalTitle').textContent==='建立關聯新案'")
                browser.run("check", "#officialHandoverAcknowledgement")
                browser.click_visible("#officialHandoverModalSubmit")
                browser.until("document.querySelector('#officialHandoverModal').classList.contains('hidden')&&uploadedSealEditorRuntime.documentId.startsWith('ODLINK-')&&!uploadedSealApplicationRuntime.openPromise")
                new_id = browser.evaluate("uploadedSealEditorRuntime.documentId")
                with backend.connect() as conn:
                    new = backend.official_document_row(conn, new_id)
                    assert new["applicant_id"] == successor["id"] and new["current_status"] == "draft"
                    assert before == backend.official_document_row(conn, linked_origin)
                    # General PDF contracts use fresh case IDs, not an
                    # invented official dispatch number. Compose documents
                    # have separate server-owned numbering unit/PG gates.
                    assert new_id != linked_origin
                    assert new["dispatch_no"] is None and before["dispatch_no"] is None
                    assert not backend.official_document_files(conn, new_id) and not backend.official_document_steps(conn, new_id)
                report["journeys"].append({"device": device, "stage": "linked_draft", "originalPreserved": True, "freshCaseAndFiles": True, **browser.evaluate(HIT_AREA_AUDIT_JS)})
                browser.run("screenshot", str(output / (device + "-linked-draft.png")), "--full")
                browser.until("document.querySelector('#uploadedSealApprovalCategorySelect').options.length>1")
                category = browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(e=>e.textContent.includes('合作意向書')).value")
                browser.run("select", "#uploadedSealApprovalCategorySelect", category)
                browser.run("fill", "#uploadedSealTitle", "關聯新案：重新選擇去識別化文件")
                browser.run("fill", "#uploadedSealReason", "隔離測試：原案保留，不沿用舊檔案或簽核。")
                pdf = Path(temporary) / ("linked-fresh-"+device+".pdf")
                pdf.write_bytes(Fixture._make_a4_pdf({"ordinal": 90, "orientations": ["portrait"]}))
                browser.run("upload", "#uploadedSealPdfInput", str(pdf))
                browser.until("uploadedSealEditorState.pages.length===1&&!uploadedSealEditorRuntime.uploading")
                assert browser.evaluate("uploadedSealEditorRuntime.documentId") == new_id
                browser.add_pdf_text("關聯新案重新編輯驗收")
                browser.until("uploadedSealEditorState.elements.some(e=>e.kind==='text')&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration&&!uploadedSealEditorRuntime.saving")
                with backend.connect() as conn:
                    assert before == backend.official_document_row(conn, linked_origin)
                    revision = backend._editor_latest_revision_row(conn, new_id)
                    state = backend.parse_json_any(revision["editor_state_json"], {})
                    assert any(e.get("properties", {}).get("text") == "關聯新案重新編輯驗收" for e in state["elements"])
                    assert backend.official_document_row(conn, new_id)["current_status"] == "draft"
                    assert not backend.official_document_steps(conn, new_id)
                    metadata = backend.parse_json_any(backend.official_document_row(conn, new_id)["metadata_json"], {})
                    assert metadata["linked_application"]["original_document_id"] == linked_origin
                report["journeys"].append({"device": device, "stage": "linked_fresh_pdf_edit", "persistedText": True, "originalUnchanged": True, "notAutoSubmitted": True, **browser.evaluate(HIT_AREA_AUDIT_JS)})
                browser.run("screenshot", str(output / (device + "-linked-edited.png")), "--full")
                report["journeys"].append({"device": device,
                    **complete_linked_http_case(new_id, sessions["department_head"], linked_origin, before),
                    **browser.evaluate(HIT_AREA_AUDIT_JS)})
            login("staff", "mobile")
            assert browser.evaluate("document.querySelector('#officialHandoverOpenBtn').hidden")
            denial = Fixture._request("GET", "/api/official-handovers", token=sessions["staff"]["token"])
            assert denial.status == 403
            report["employeeReadDenied"] = True
            # Existing integrated report/header controls are outside this
            # feature; retain their findings, do not pretend they passed.
            for row in report["journeys"]:
                row["handoverShortTargets"] = [item for item in row["shortTargets"] if item.get("id", "").startswith("officialHandover")]
                row["handoverSmallInputs"] = [item for item in row["smallInputs"] if item.get("id", "").startswith("officialHandover")]
            report["passed"] = all(not row["overflow"] and not row["handoverShortTargets"] and not row["handoverSmallInputs"] and not row["errors"] for row in report["journeys"])
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps({"passed": report["passed"], "journeys": len(report["journeys"]), "report": str(output / "report.json")}), flush=True)
            return 0 if report["passed"] else 1
    except Exception:
        if browser:
            try:
                report["failure"] = browser.evaluate("({route:document.querySelector('.view.active')?.id,role:authState?.user?.role,permissions:authState?.permissions,appInert:document.querySelector('#appShell')?.inert,nav:[...document.querySelectorAll('.sidebar .nav-item')].map(e=>({target:e.dataset.target,hidden:e.hidden,width:e.getBoundingClientRect().width,display:getComputedStyle(e).display})),errors:window.__fixtureErrors||[]})")
                (output / "failure.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
                browser.run("screenshot", str(output / "failure.png"), "--full")
            except RuntimeError:
                pass
        raise
    finally:
        if browser:
            try:
                browser.run("close")
            except RuntimeError:
                pass
        Fixture.tearDownClass()
        telemetry.stop()


if __name__ == "__main__":
    raise SystemExit(main())
