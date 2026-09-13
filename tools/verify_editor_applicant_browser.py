"""Production-shaped Finance applicant browser regression, fully isolated.

The real Finance directory formatter and production authoritative-unit guard
consume a deidentified in-memory organization mirror. HTTP records and PDF
bytes use temporary SQLite/local transport. No real account, hosted Storage,
Google login, seal operation, submission or exchange is contacted.
"""
from __future__ import annotations

import argparse
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import time
from types import FunctionType
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from tools.six_role_browser_acceptance import Browser, AUDIT_JS, TELEMETRY, require_local_origin
from tests.support.five_account_browser_fixture import BROWSER_ROLES, isolated_browser_session
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest, QuietAcceptanceHandler


class FinanceMirror:
    """Only transport is replaced; directory and authorization code stay real."""

    def __init__(self, fixture):
        with backend.connect() as conn:
            self.companies = [dict(row) for row in conn.execute("SELECT * FROM companies WHERE source_system='finance'")]
        self.states = []
        self.units = []
        for company in self.companies:
            tenant = company["finance_tenant_id"]
            entity = company["finance_entity_id"]
            code = "QA100" if entity == "E1" else "QA200"
            name = "隔離驗收部一" if entity == "E1" else "隔離驗收部二"
            self.states.append({"finance_tenant_id": tenant, "version_no": 1, "etag": "a" * 64, "last_synced_from_finance_at": "2026-09-13T00:00:00Z"})
            for order, unit_code, unit_name, unit_type in ((1, code, name, "department"), (2, "A1000", "隔離執行長室", "division")):
                self.units.append({"id": f"MIRROR-{entity}-{unit_code}", "finance_unit_id": f"SYNTHETIC-{entity}-{unit_code}", "finance_tenant_id": tenant, "code": unit_code, "name": unit_name, "unit_type": unit_type, "parent_finance_unit_id": None, "sort_order": order, "is_posting_unit": unit_type == "department", "entity_scope_mode": "explicit", "entity_codes": [entity], "status": "active"})

    def rows(self, table, filters=None, **kwargs):
        available = {"companies": self.companies, "finance_organization_projection_state": self.states, "finance_organization_units": self.units}
        if table not in available:
            raise AssertionError("unexpected_mirror_table")
        selected = [row for row in available[table] if all(row.get(key) == value for key, value in (filters or {}).items())]
        return copy.deepcopy(selected[:kwargs.get("limit", len(selected))])

    def get(self, table, row_id):
        if table != "companies":
            raise AssertionError("unexpected_mirror_get")
        return copy.deepcopy(next((row for row in self.companies if row["id"] == row_id), None))

    def production_function(self, function):
        scope = {**function.__globals__, "USE_SUPABASE": True, "is_production": lambda: True, "supabase_filter_rows": self.rows, "supabase_get": self.get}
        return FunctionType(function.__code__, scope, function.__name__, function.__defaults__, function.__closure__)


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = {}
    if args.baseline:
        source = {name: subprocess.check_output(["git", "show", "origin/main:" + name], cwd=ROOT) for name in ("index.html", "app.js", "styles.css")}
    original_head = QuietAcceptanceHandler.send_head
    original_json = QuietAcceptanceHandler.send_json
    requests = []

    def instrument(handler):
        path = urlparse(handler.path).path
        name = "index.html" if path in {"/", "/index.html"} else path.lstrip("/")
        if name == "index.html" or name in source:
            data = source.get(name) or (ROOT / name).read_bytes()
            if name == "index.html":
                data = data.replace(b"<head>", ("<head>" + TELEMETRY).encode(), 1)
            handler.send_response(200)
            handler.send_header("Content-Type", "application/javascript" if name.endswith(".js") else "text/css" if name.endswith(".css") else "text/html; charset=utf-8")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            return io.BytesIO(data)
        return original_head(handler)

    def trace_json(handler, data, status=200, extra_headers=None):
        if urlparse(handler.path).path == "/api/official-documents/editor-drafts":
            requests.append({"operation": "editor-draft-create", "status": status, "errorCode": data.get("detail", "") if isinstance(data, dict) and status >= 400 else ""})
        return original_json(handler, data, status, extra_headers)

    report = {"scope": "synthetic_production_finance_mirror_with_real_guards_local_pdf_transport", "realSsoVerified": False, "hostedTusVerified": False, "baseline": args.baseline, "journeys": [], "draftRequests": requests}
    fixture = FiveAccountHttpAcceptanceTest
    fixture.setUpClass()
    require_local_origin(fixture.origin)
    # The reported failure is a division-level CEO missing from department-only
    # directory options. Names and accounts here are synthetic, not copied users.
    for snapshot in fixture.snapshots_by_email.values():
        if snapshot["identity"]["role"] == "ceo":
            snapshot["identity"].update(departmentCode="A1000", departmentName="隔離執行長室")
    mirror = FinanceMirror(fixture)
    directory = mirror.production_function(backend.supabase_finance_directory)
    authority = mirror.production_function(backend.authoritative_finance_unit)
    authority.__kwdefaults__ = backend.authoritative_finance_unit.__kwdefaults__
    config = Path(fixture.tmp.name) / "browser.json"
    config.write_text(json.dumps({"allowedDomains": ["127.0.0.1", "fonts.googleapis.com", "fonts.gstatic.com"], "headed": False}))
    browser = Browser(config, session="editor-applicant-0913", namespace="editor-applicant-0913")
    try:
        with mock.patch.object(QuietAcceptanceHandler, "send_head", instrument), mock.patch.object(QuietAcceptanceHandler, "send_json", trace_json), mock.patch.object(backend, "local_finance_directory", side_effect=lambda conn, session: directory(session)), mock.patch.object(backend, "authoritative_finance_unit", side_effect=authority):
            roles = ("ceo",) if args.baseline else ("ceo", *[role for role in BROWSER_ROLES if role != "ceo"])
            for role in roles:
                auth = isolated_browser_session(fixture, role, entity_id="E1")
                devices = [("desktop", (1440, 1000))] if args.baseline or role != "ceo" else [("desktop", (1440, 1000)), ("mobile", (390, 844))]
                expected_code = "A1000" if role == "ceo" else "QA100"
                for device, dimensions in devices:
                    row = {"role": role, "device": device, "checks": {}}
                    report["journeys"].append(row)
                    browser.run("open", fixture.origin + "/assets/favicon-32.png")
                    browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
                    browser.run("set", "viewport", *map(str, dimensions))
                    browser.run("open", fixture.origin + f"/?applicant_fixture={time.monotonic_ns()}#electronicSeal")
                    browser.until("window.__fixtureTiming?.appInteractiveMs&&document.querySelector('#uploadedSealApprovalCategorySelect')?.options.length>1&&!uploadedSealEditorRuntime.directoryLoading")
                    browser.run("snapshot", "-i")
                    row["identity"] = browser.evaluate("(()=>{const c=document.querySelector('#uploadedSealCompany'),d=document.querySelector('#uploadedSealDepartment'),p=editorDraftPayload();return {company:c.value,companyLocked:c.disabled,department:d.value,departmentCode:d.selectedOptions[0]?.dataset.financeUnitCode,departmentLocked:d.disabled,payloadCompany:p.company_id,payloadDepartmentCode:p.applicant_department_id,source:financeDirectoryState.source,generalDirectoryIncludesA1000:departmentRegistry.some(e=>e.code==='A1000')}})()")
                    row["checks"]["realFinanceDirectoryShape"] = row["identity"]["source"] == "finance"
                    row["checks"]["divisionNotInjectedIntoGeneralDirectory"] = not row["identity"]["generalDirectoryIncludesA1000"]
                    row["checks"]["exactOwnUnitSelected"] = row["identity"].get("departmentCode") == expected_code
                    row["checks"]["companyAndUnitLocked"] = row["identity"]["companyLocked"] and row["identity"]["departmentLocked"]
                    row["checks"]["payloadUsesCanonicalCode"] = row["identity"].get("payloadDepartmentCode") == expected_code
                    row["checks"]["ownCompanyUsed"] = row["identity"]["company"] == auth["user"]["company_id"] == row["identity"]["payloadCompany"]
                    if role == "ceo":
                        category = browser.evaluate("[...document.querySelector('#uploadedSealApprovalCategorySelect').options].find(e=>e.textContent.includes('合作意向書')).value")
                        browser.run("select", "#uploadedSealApprovalCategorySelect", category)
                        browser.run("fill", "#uploadedSealTitle", "隔離驗收：執行長 PDF 文字編輯")
                        browser.run("fill", "#uploadedSealReason", "合成文件；不送簽、不用印、不寄發。")
                        pdf = Path(fixture.tmp.name) / f"synthetic-{device}.pdf"
                        writer = canvas.Canvas(str(pdf), pagesize=A4)
                        writer.drawString(50, 770, "SYNTHETIC A4 APPLICANT REGRESSION")
                        writer.showPage()
                        writer.save()
                        request_start = len(requests)
                        browser.run("upload", "#uploadedSealPdfInput", str(pdf))
                        browser.until("uploadedSealEditorState.pages.length===1&&!uploadedSealEditorRuntime.uploading||!document.querySelector('#uploadedEditorUploadError').hidden")
                        row["draftRequests"] = requests[request_start:]
                        row["checks"]["uploadAccepted"] = browser.evaluate("uploadedSealEditorState.pages.length===1")
                        if not args.baseline:
                            if not row["checks"]["uploadAccepted"]:
                                raise AssertionError("upload_regression_failed")
                            browser.click_visible('#uploadedPdfEditor [data-editor-tool="text"]')
                            browser.run("fill", "#uploadedSealTextInput", "隔離執行長編輯驗收")
                            browser.click_visible("#addUploadedTextBtn")
                            browser.until("uploadedSealEditorState.elements.some(e=>e.kind==='text')&&uploadedSealEditorRuntime.savedGeneration>=uploadedSealEditorRuntime.dirtyGeneration&&!uploadedSealEditorRuntime.saving")
                            document_id = browser.evaluate("uploadedSealEditorRuntime.documentId")
                            saved = fixture._expect_json("GET", f"/api/official-documents/{document_id}/editor-state", 200, token=auth["token"])
                            state = saved.get("state") or saved.get("editor_state")
                            row["checks"]["savedTextReadbackMatches"] = any(e.get("properties", {}).get("text") == "隔離執行長編輯驗收" for e in state.get("elements", []))
                            row["checks"]["noSealOrSubmission"] = not any(e.get("kind") == "seal" for e in state.get("elements", []))
                        else:
                            row["reproduced403"] = any(e["status"] == 403 and e["errorCode"] == "finance_unit_payload_mismatch" for e in row["draftRequests"])
                    row["layout"] = browser.evaluate(AUDIT_JS)
                    row["checks"]["noDocumentOverflow"] = not row["layout"]["overflow"]
                    row["checks"]["noUnhandledErrors"] = not row["layout"]["errors"]
                    browser.run("screenshot", str(output / f"{role}-{device}.png"), "--full")
                    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
                    print(json.dumps({"role": role, "device": device, "checks": row["checks"], "reproduced403": row.get("reproduced403")}), flush=True)
            return int(not all(row.get("reproduced403") for row in report["journeys"])) if args.baseline else int(any(not all(row["checks"].values()) for row in report["journeys"]))
    except Exception as error:
        report["errorCode"] = str(error) if str(error).startswith(("browser_", "upload_")) else type(error).__name__
        report["failure"] = browser.evaluate("({uploadError:document.querySelector('#uploadedEditorUploadErrorMessage')?.textContent,pages:uploadedSealEditorState?.pages?.length,errors:window.__fixtureErrors})")
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        browser.run("screenshot", str(output / "failure.png"), "--full")
        raise
    finally:
        try:
            browser.run("close")
        finally:
            fixture.tearDownClass()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", action="store_true")
    raise SystemExit(run(parser.parse_args()))
