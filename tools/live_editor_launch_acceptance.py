#!/usr/bin/env python3
"""Exercise a real private editor draft with verified existing Finance users.

Only synthetic A4 data is uploaded. No submission, stamp, notification, account
creation or direct database write is performed. Existing immutable draft/file
retention has no public delete API, so the report records the retained draft ID.
Secrets are supplied through the environment and never included in the report.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import random
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

try:
    from tools import live_five_account_sso_acceptance as sso
except ModuleNotFoundError:
    import live_five_account_sso_acceptance as sso


ORIGIN = sso.EDOC_ORIGIN
MAX_ACCOUNT_PROBES = 12
TIMEOUT_SECONDS = 60


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def raw_request(url: str, method: str = "GET", *, headers: dict | None = None,
                data: bytes | None = None) -> tuple[int, dict, bytes]:
    request = urllib.request.Request(url, method=method, data=data, headers={
        "User-Agent": "edoc-editor-live-acceptance/1", **(headers or {}),
    })
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=TIMEOUT_SECONDS) as response:
            return int(response.status), dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return int(error.code), dict(error.headers), error.read()
    except (urllib.error.URLError, TimeoutError):
        raise sso.AcceptanceError("editor_acceptance_network_unavailable") from None


def response_header(headers: dict, name: str) -> str:
    return next((str(value) for key, value in headers.items() if key.lower() == name.lower()), "")


def application_url(path: str) -> str:
    result = urllib.parse.urljoin(ORIGIN, path)
    parsed = urllib.parse.urlparse(result)
    if parsed.scheme != "https" or parsed.netloc != urllib.parse.urlparse(ORIGIN).netloc or not parsed.path.startswith("/api/official-documents/"):
        raise sso.AcceptanceError("editor_acceptance_download_url_invalid")
    return result


def api(token: str, method: str, path: str, expected: int, body: dict | None = None) -> dict:
    status, _headers, data = raw_request(application_url(path), method, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json",
        "Content-Type": "application/json", "Origin": ORIGIN,
    }, data=json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode() if body is not None else None)
    try:
        payload = json.loads(data) if data else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    if status != expected:
        code = str(payload.get("detail") or payload.get("error") or "") if isinstance(payload, dict) else ""
        safe_code = code if re.fullmatch(r"(?:editor|official|company|pdf)_[a-z0-9_]{1,80}", code) else "unexpected_status"
        raise sso.AcceptanceError(f"editor_acceptance_http_{status}_{safe_code}")
    if not isinstance(payload, dict):
        raise sso.AcceptanceError("editor_acceptance_json_invalid")
    return payload


def synthetic_a4_pdf() -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream, pagesize=A4, invariant=1, pageCompression=1)
    pdf.setTitle("Synthetic eDoc launch acceptance - not for submission")
    pdf.setAuthor("eDoc automated acceptance")
    for ordinal, size in enumerate((A4, landscape(A4)), start=1):
        pdf.setPageSize(size)
        pdf.setFont("Helvetica", 16)
        pdf.drawString(48, size[1] - 60, f"SYNTHETIC EDOC LAUNCH ACCEPTANCE PAGE {ordinal}")
        pdf.setFont("Helvetica", 11)
        pdf.drawString(48, size[1] - 88, "No personal data. Not a contract. Do not submit or stamp.")
        pdf.rect(48, 48, size[0] - 96, size[1] - 160)
        pdf.showPage()
    pdf.save()
    return stream.getvalue()


def public_upload_key(key: str) -> bool:
    if key.startswith("sb_publishable_"):
        return True
    if key.startswith(("sb_secret_", "service_role")):
        return False
    try:
        parts = key.split(".")
        return len(parts) == 3 and json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))).get("role") == "anon"
    except (ValueError, TypeError, UnicodeDecodeError):
        return False


def tus_upload(intent: dict, source: bytes) -> None:
    endpoint = str(intent.get("upload_url") or "")
    parsed = urllib.parse.urlparse(endpoint)
    key = str(intent.get("storage_publishable_key") or "")
    signature = str(intent.get("upload_token") or "")
    if intent.get("protocol") != "tus" or parsed.scheme != "https" or not (parsed.hostname or "").endswith(".storage.supabase.co") or parsed.path != "/storage/v1/upload/resumable/sign":
        raise sso.AcceptanceError("editor_acceptance_tus_endpoint_invalid")
    if not public_upload_key(key) or not signature:
        raise sso.AcceptanceError("editor_acceptance_tus_credentials_invalid")
    metadata = {
        "bucketName": str(intent.get("bucket") or ""), "objectName": str(intent.get("path") or ""),
        "contentType": "application/pdf", "cacheControl": "0",
    }
    if not all(metadata.values()):
        raise sso.AcceptanceError("editor_acceptance_tus_metadata_missing")
    headers = {"apikey": key, "x-signature": signature, "Tus-Resumable": "1.0.0"}
    status, response_headers, _data = raw_request(endpoint, "POST", headers={
        **headers, "Upload-Length": str(len(source)),
        "Upload-Metadata": ",".join(f"{key} {base64.b64encode(value.encode()).decode()}" for key, value in metadata.items()),
    }, data=b"")
    if status != 201:
        raise sso.AcceptanceError(f"editor_acceptance_tus_create_http_{status}")
    location = urllib.parse.urljoin(endpoint, response_header(response_headers, "Location"))
    target = urllib.parse.urlparse(location)
    if target.scheme != parsed.scheme or target.netloc != parsed.netloc or not target.path.startswith("/storage/v1/upload/resumable/sign/"):
        raise sso.AcceptanceError("editor_acceptance_tus_location_invalid")
    status, response_headers, _data = raw_request(location, "PATCH", headers={
        **headers, "Upload-Offset": "0", "Content-Type": "application/offset+octet-stream",
    }, data=source)
    if status != 204 or response_header(response_headers, "Upload-Offset") != str(len(source)):
        raise sso.AcceptanceError(f"editor_acceptance_tus_patch_http_{status}")
    status, response_headers, _data = raw_request(location, "HEAD", headers=headers)
    if status not in {200, 204} or response_header(response_headers, "Upload-Offset") != str(len(source)):
        raise sso.AcceptanceError(f"editor_acceptance_tus_head_http_{status}")


def text_edit_state(revision: dict) -> dict:
    state = copy.deepcopy(revision["state"])
    pages = state.get("pages") or []
    if len(pages) != 2:
        raise sso.AcceptanceError("editor_acceptance_page_count_invalid")
    for index, page in enumerate(pages):
        width, height = float(page["widthPt"]), float(page["heightPt"])
        if abs(min(width, height) - 595.2756) > 1 or abs(max(width, height) - 841.8898) > 1:
            raise sso.AcceptanceError("editor_acceptance_a4_geometry_invalid")
        if (width > height) != bool(index):
            raise sso.AcceptanceError("editor_acceptance_page_orientation_invalid")
    state["elements"] = [{
        "id": "TEXT-LAUNCH-ACCEPTANCE", "pageId": pages[0]["pageId"], "kind": "text",
        "x": 72, "y": 100, "width": 320, "height": 30,
        "rotation": 0, "opacity": 1, "zIndex": 1,
        "properties": {"text": "EDOC-LIVE-EDITOR-SAVED", "fontSize": 14, "fontFamily": "edukai", "color": "#202020"},
    }]
    return state


def download(token: str, path: str, expected: int = 200) -> bytes:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    status, _headers, body = raw_request(application_url(path), headers=headers)
    if status != expected:
        raise sso.AcceptanceError(f"editor_acceptance_download_http_{status}")
    return body


def run_editor_checks(token: str, user: dict, other_company_token: str, report: dict) -> None:
    marker = uuid.uuid4().hex[:12]
    title = f"上線驗收測試－PDF 編輯器－{marker}（不送簽）"
    draft = api(token, "POST", "/api/official-documents/editor-drafts", 201, {
        "company_id": user["company_id"], "title": title, "subject": title,
        "request_reason": "去識別化正式站功能驗收；不送簽、不寄送、不用印。",
        "document_category": "合作意向書", "dispatch_method": "no_dispatch_required",
    })
    document_id = str(draft.get("document_id") or "")
    if not re.fullmatch(r"OD-[A-Za-z0-9-]+", document_id):
        raise sso.AcceptanceError("editor_acceptance_draft_id_invalid")
    report["retainedDraftIds"].append(document_id)
    root = f"/api/official-documents/{document_id}"
    report["checks"]["privateDraftCreated"] = True
    source = synthetic_a4_pdf()
    digest = hashlib.sha256(source).hexdigest().upper()
    intent = api(token, "POST", root + "/editor-uploads", 201, {
        "asset_kind": "source_pdf", "file_name": f"launch-acceptance-{marker}.pdf",
        "mime_type": "application/pdf", "size_bytes": len(source), "sha256": digest,
    })
    tus_upload(intent, source)
    report["checks"]["directTusUploadAndOffsetVerified"] = True
    upload_id = str(intent["upload_id"])
    finalized = api(token, "POST", root + f"/editor-uploads/{upload_id}/finalize", 200, {"sha256": digest, "size_bytes": len(source)})
    asset = finalized.get("asset") or {}
    if asset.get("scanStatus") != "passed" or asset.get("preflightStatus") != "passed" or str(asset.get("sha256") or "").upper() != digest:
        raise sso.AcceptanceError("editor_acceptance_scan_or_hash_failed")
    report["checks"]["virusScanAndPdfPreflightPassed"] = True
    revision = finalized["editor_revision"]
    replay = api(token, "POST", root + f"/editor-uploads/{upload_id}/finalize", 200, {"sha256": digest})
    if replay["editor_revision"]["id"] != revision["id"]:
        raise sso.AcceptanceError("editor_acceptance_finalize_not_idempotent")
    report["checks"]["finalizeReplayIdempotent"] = True
    save_body = {"revisionNo": revision["revisionNo"], "baseManifestSha256": revision["manifestSha256"], "state": text_edit_state(revision)}
    saved = api(token, "PUT", root + "/editor-state", 200, save_body)
    api(token, "PUT", root + "/editor-state", 409, save_body)
    loaded = api(token, "GET", root + "/editor-state", 200)
    if loaded["id"] != saved["id"] or loaded["state"]["elements"][0]["properties"]["text"] != "EDOC-LIVE-EDITOR-SAVED":
        raise sso.AcceptanceError("editor_acceptance_saved_content_changed")
    report["checks"]["textEditSavedReloadedAndConflict409"] = True
    api(token, "POST", root + "/editor-preflight", 409, {"editorRevisionId": saved["id"], "manifestSha256": "0" * 64})
    report["checks"]["tamperedManifestRejected"] = True
    prepared = api(token, "POST", root + "/editor-preflight", 201, {"editorRevisionId": saved["id"], "manifestSha256": saved["manifestSha256"]})
    prepared_data = download(token, prepared["preparedUrl"])
    if hashlib.sha256(prepared_data).hexdigest().upper() != str(prepared["preparedSha256"]).upper():
        raise sso.AcceptanceError("editor_acceptance_prepared_hash_mismatch")
    from pypdf import PdfReader
    prepared_pdf = PdfReader(io.BytesIO(prepared_data))
    if len(prepared_pdf.pages) != 2 or "EDOC-LIVE-EDITOR-SAVED" not in prepared_pdf.pages[0].extract_text():
        raise sso.AcceptanceError("editor_acceptance_prepared_text_missing")
    report["checks"]["preparedPdfContainsSavedText"] = True
    source_path = root + f"/files/{asset['officialFileId']}/download"
    if hashlib.sha256(download(token, source_path)).hexdigest().upper() != digest:
        raise sso.AcceptanceError("editor_acceptance_original_changed")
    report["checks"]["originalSourceHashPreserved"] = True
    download("", prepared["preparedUrl"], 401)
    report["checks"]["anonymousDownloadDenied"] = True
    if other_company_token:
        api(other_company_token, "GET", root + "/editor-state", 403)
        download(other_company_token, prepared["preparedUrl"], 403)
        report["checks"]["crossCompanyReadAndDownloadDenied"] = True
    else:
        report["notExercised"].append("cross_company_no_second_eligible_company")
    summary = api(token, "GET", root + "/editor-change-summary", 200)
    if (summary.get("changes") or {}).get("total") != 1:
        raise sso.AcceptanceError("editor_acceptance_change_summary_invalid")
    report["checks"]["changeSummaryMatchesTextEdit"] = True
    detail = api(token, "GET", root, 200)
    if detail.get("current_status") != "draft" or detail.get("approval_steps"):
        raise sso.AcceptanceError("editor_acceptance_draft_unexpectedly_submitted")
    report["checks"]["remainsUnsubmittedDraft"] = True
    report["sourceSha256"] = digest
    report["preparedSha256"] = prepared["preparedSha256"]


def main() -> int:
    report = {"checks": {}, "failureCodes": [], "retainedDraftIds": [], "notExercised": [],
              "piiPrinted": False, "humanGoogleLoginExercised": False,
              "formalSubmissionPerformed": False, "sealOperationsPerformed": False,
              "draftCleanup": "retained_immutable_record_no_delete_api"}
    issued_tokens: list[str] = []
    try:
        secret = sso.required_environment("PORTAL_HANDOFF_SIGNING_SECRET")
        if len(secret.encode("utf-8")) < 32:
            raise sso.AcceptanceError("portal_handoff_secret_too_short")
        accounts = sso.portal_google_accounts()
        eligible = sorted(set(accounts) & sso.active_finance_emails())
        random.SystemRandom().shuffle(eligible)
        owner = None
        other = None
        sessions = []
        for ordinal, email in enumerate(eligible[:MAX_ACCOUNT_PROBES], start=1):
            sso._acceptance_for_account(email, accounts[email], secret, ordinal, issued_tokens)
            token = issued_tokens[-1]
            status, session = sso.request_json(f"{ORIGIN}/api/auth/me", headers={"Authorization": f"Bearer {token}"})
            if status != 200:
                raise sso.AcceptanceError("editor_acceptance_session_invalid")
            user = session.get("user") or {}
            sessions.append((token, user))
            permissions = set(session.get("permissions") or [])
            if owner is None and user.get("company_id") and permissions & {"official_documents.compose", "official_documents.all_todo"}:
                owner = (token, user)
            if owner:
                other = next((item for item in sessions if item[1].get("company_id") and item[1]["company_id"] != owner[1]["company_id"]), None)
                if other:
                    break
        if not owner:
            raise sso.AcceptanceError("editor_acceptance_no_eligible_applicant")
        run_editor_checks(owner[0], owner[1], other[0] if other else "", report)
    except sso.AcceptanceError as error:
        report["failureCodes"].append(str(error))
    except Exception:
        report["failureCodes"].append("editor_acceptance_unexpected_failure")
    finally:
        revoked = 0
        for token in issued_tokens:
            headers = {"Authorization": f"Bearer {token}"}
            status, payload = sso.request_json(f"{ORIGIN}/api/auth/logout", method="POST", data=b"", headers=headers)
            me_status, _ = sso.request_json(f"{ORIGIN}/api/auth/me", headers=headers)
            if status == 200 and payload.get("ok") and me_status == 401:
                revoked += 1
            else:
                report["failureCodes"].append("editor_acceptance_session_cleanup_failed")
        report["sessionsRevoked"] = revoked
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return 0 if not report["failureCodes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
