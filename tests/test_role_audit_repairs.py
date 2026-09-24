"""Regression checks for release fixes identified in the five-role UX audit."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

import backend
from tests import test_general_document_seal_workflow as seal_fixture
from tests.test_compose_output_contract import function


ROOT = Path(__file__).resolve().parents[1]


class RoleAuditFrontendRepairTest(unittest.TestCase):
    def evaluate(self, name: str, setup: str, body: str):
        source = (ROOT / "app.js").read_text()
        script = setup + "\n" + function(source, name)
        script += "\n" + body
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_same_name_replacement_is_uploaded_but_identical_bytes_are_deduplicated(self):
        value = self.evaluate(
            "inboundAttachmentAlreadyUploaded",
            "",
            '''console.log(JSON.stringify([
              inboundAttachmentAlreadyUploaded([{file_name:"scan.pdf",file_hash:"A1"}],"A1"),
              inboundAttachmentAlreadyUploaded([{file_name:"scan.pdf",file_hash:"A1"}],"B2"),
              inboundAttachmentAlreadyUploaded([{file_name:"scan.pdf"}],"B2")
            ]));''',
        )
        self.assertEqual(value, [True, False, False])

    def test_transient_browser_network_errors_retry_without_reclassifying_auth_denial(self):
        value = self.evaluate(
            "isRetryableAuthError",
            "",
            '''console.log(JSON.stringify([
              isRetryableAuthError(new TypeError("Failed to fetch")),
              isRetryableAuthError(Object.assign(new Error("unavailable"),{status:503})),
              isRetryableAuthError(Object.assign(new Error("denied"),{status:401})),
              isRetryableAuthError(new TypeError("Cannot read properties of undefined"))
            ]));''',
        )
        self.assertEqual(value, [True, True, False, False])

    def test_peer_tab_signout_and_session_replacement_clear_stale_private_ui(self):
        value = self.evaluate(
            "handlePeerTabSignOut",
            '''const authStorageKey="edoc-session";let authState={token:"same",user:{id:"synthetic-user"}};const cleared=[];const notices=[];const hasAuthenticatedBackendSession=()=>Boolean(authState?.token);const clearAppSessionUi=session=>{cleared.push(session?.token||"");authState=null;};const isProductionEdocHost=()=>false;const showToast=message=>notices.push(message);''',
            '''handlePeerTabSignOut({key:authStorageKey,newValue:JSON.stringify({token:"same"})});const sameTokenNoop=cleared.length===0;authState={token:"same",user:{id:"synthetic-user"}};handlePeerTabSignOut({key:authStorageKey,newValue:JSON.stringify({token:"rotated"})});const replacedTokenCleared=cleared.length===1;authState={token:"rotated",user:{id:"synthetic-user"}};handlePeerTabSignOut({key:authStorageKey,newValue:null});console.log(JSON.stringify({sameTokenNoop,replacedTokenCleared,cleared,notices}));''',
        )
        self.assertEqual(value["sameTokenNoop"], True)
        self.assertEqual(value["replacedTokenCleared"], True)
        self.assertEqual(value["cleared"], ["same", "rotated"])
        self.assertIn("另一個分頁更新", value["notices"][0])
        self.assertIn("另一個分頁登出", value["notices"][1])

    def test_administrative_director_gets_only_the_delegation_route_with_permission(self):
        value = self.evaluate(
            "secondaryRoutesForRole",
            'const secondaryRoutesByIdentity={administrativeDirector:["notifications"]};let granted=false;const hasBackendPermission=key=>granted&&key==="workflow.delegations.manage";',
            '''const denied=secondaryRoutesForRole("行政部主任");granted=true;const allowed=secondaryRoutesForRole("行政部主任");console.log(JSON.stringify({denied,allowed}));''',
        )
        self.assertEqual(value["denied"], ["notifications"])
        self.assertEqual(value["allowed"], ["notifications", "workflow"])


class InactivePreviousApproverRegressionTest(unittest.TestCase):
    def setUp(self):
        self.fixture = seal_fixture.GeneralDocumentSealWorkflowTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.conn = self.fixture.conn
        self.session = self.fixture.session

    def _review(self, detail):
        step = next(row for row in detail["approval_steps"] if row["step_key"] == detail["current_step"] and row["status"] == "pending")
        session = self.fixture.fixture._session_for_user_id(step["approver_user_id"])
        for file in detail["files"]:
            if file["file_type"] in {"original_pdf", "prepared_pdf", "generated_pdf", "attachment"}:
                backend.official_document_download_file(self.conn, detail["id"], file["id"], session)
        payload = {
            "expected_step_id": step["id"],
            "comment": "Synthetic reviewed approval",
            "prepared_sha256": detail["stamp_request"]["prepared_sha256"],
            "manifest_sha256": detail["stamp_request"]["editor_manifest_sha256"],
            "review_acknowledgements": {"original_reviewed": True, "edited_version_reviewed": True, "attachments_reviewed": True},
        }
        return session, payload

    def test_return_previous_fails_closed_when_previous_reviewer_is_inactive(self):
        detail = self.fixture._submitted()[0]
        first_reviewer_id = detail["approval_steps"][0]["approver_user_id"]
        first_session, first_payload = self._review(detail)
        detail = backend.approve_official_document(self.conn, detail["id"], first_payload, first_session)
        self.conn.execute("UPDATE users SET status='停用' WHERE id=?", (first_reviewer_id,))
        current_session, return_payload = self._review(detail)
        return_payload["operation_id"] = "RETURN-INACTIVE-REVIEWER-001"
        with self.assertRaisesRegex(ValueError, "official_workflow_next_approver_inactive"):
            backend.mutate_official_workflow(self.conn, detail["id"], "return_previous", return_payload, current_session)
        self.assertEqual(backend.official_document_row(self.conn, detail["id"])["current_step"], detail["current_step"])


class OperationalReportRegressionTest(unittest.TestCase):
    def setUp(self):
        self.fixture = seal_fixture.GeneralDocumentSealWorkflowTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.conn = self.fixture.conn
        self.session = dict(self.fixture.session)
        self.session["permissions"] = [*self.session.get("permissions", []), "reports.operational_view"]

    def test_real_company_scoped_report_aggregates_statuses_and_filters(self):
        rows = [
            {"current_status": "pending_department_head", "applicant_department_name": "營運部", "recipient": "市府", "subject": "續約"},
            {"current_status": "closed", "applicant_department_name": "營運部", "recipient": "市府", "subject": "採購"},
            {"current_status": "rejected", "applicant_department_name": "人資部", "recipient": "區公所", "subject": "人事"},
            {"current_status": "cancelled", "applicant_department_name": "人資部", "recipient": "區公所", "subject": "取消"},
            {"current_status": "draft", "applicant_department_name": "營運部", "recipient": "市府", "subject": "草稿"},
            {"current_status": "pending_department_head", "applicant_department_name": "外公司", "recipient": "外部機關", "subject": "不得跨公司統計", "company_id": "CO-002"},
        ]
        for index, item in enumerate(rows):
            self.conn.execute(
                """INSERT INTO official_documents
                   (id, company_id, applicant_id, applicant_name, applicant_department_name, dispatch_unit,
                   document_type, source_type, title, subject, recipient, current_status, current_step,
                   content_revision, created_at, updated_at)
                   VALUES (?, ?, ?, '隔離測試', ?, ?, '一般', 'blank_editor', ?, ?, ?, ?, '', 0, ?, ?)""",
                (f"REPORT-CASE-{index}", item.get("company_id", "CO-001"), self.session["user"]["id"], item["applicant_department_name"], item["applicant_department_name"],
                 item["subject"], item["subject"], item["recipient"], item["current_status"], backend.now(), backend.now()),
            )
        self.conn.commit()
        report = backend.official_operational_report({"period": ["today"]}, self.session, conn=self.conn)
        self.assertEqual((report["total"], report["pending"], report["completed"], report["returned"], report["cancelled"], report["draft"]), (5, 1, 1, 1, 1, 1))
        self.assertEqual(next(row for row in report["unitRows"] if row["unit"] == "營運部")["draft"], 1)
        filtered = backend.official_operational_report({"period": ["today"], "unit": ["營運部"], "agency": ["續約"]}, self.session, conn=self.conn)
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["scope"], report["scope"])

    def test_operational_report_requires_explicit_permission_and_valid_period(self):
        session = dict(self.session)
        session["permissions"] = []
        with self.assertRaisesRegex(PermissionError, "operational_report_forbidden"):
            backend.official_operational_report({"period": ["7d"]}, session, conn=self.conn)
        with self.assertRaisesRegex(ValueError, "operational_report_period_invalid"):
            backend.official_operational_report({"period": ["forever"]}, self.session, conn=self.conn)

    def test_operational_report_day_uses_taipei_calendar_and_timezone_correct_storage_bounds(self):
        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                instant = datetime(2026, 9, 24, 16, 30, tzinfo=timezone.utc)
                return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

        with mock.patch.object(backend, "datetime", FixedDatetime):
            bounds = backend.official_operational_report_period("today")
        self.assertEqual(bounds["today"], "2026-09-25")
        self.assertEqual(bounds["periodStart"], "2026-09-25")
        self.assertEqual(bounds["supabaseStart"], "2026-09-24T16:00:00+00:00")
        self.assertEqual(bounds["supabaseEnd"], "2026-09-25T16:00:00+00:00")
        local_start = datetime(2026, 9, 24, 16, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        local_end = datetime(2026, 9, 25, 16, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        self.assertEqual(bounds["sqliteStart"], local_start.strftime("%Y-%m-%d %H:%M:%S"))
        self.assertEqual(bounds["sqliteEnd"], local_end.strftime("%Y-%m-%d %H:%M:%S"))

    def test_supabase_report_query_uses_company_scope_and_taipei_period_cutoffs(self):
        session = dict(self.session)
        fixed_bounds = {
            "today": "2026-09-25", "periodStart": "2026-09-25",
            "sqliteStart": "2026-09-25 00:00:00", "sqliteEnd": "2026-09-26 00:00:00",
            "supabaseStart": "2026-09-24T16:00:00+00:00", "supabaseEnd": "2026-09-25T16:00:00+00:00",
        }
        with mock.patch.object(backend, "supabase_official_session_user", return_value={"company_id": "CO-001"}), \
             mock.patch.object(backend, "official_operational_report_period", return_value=fixed_bounds), \
             mock.patch.object(backend, "supabase_request", return_value=[]) as request:
            report = backend.official_operational_report({"period": ["today"]}, session)
        query = parse_qs(urlparse(request.call_args.args[1]).query)
        self.assertEqual(query["company_id"], ["eq.CO-001"])
        self.assertEqual(query["created_at"], ["gte.2026-09-24T16:00:00+00:00"])
        self.assertEqual(query["and"], ["(created_at.lt.2026-09-25T16:00:00+00:00)"])
        self.assertEqual(report["total"], 0)


class ComposeMobileSimplificationContractTest(unittest.TestCase):
    def test_primary_text_fields_precede_collapsible_optional_sections(self):
        html = (ROOT / "index.html").read_text()
        form_start = html.index('id="composeForm"')
        form_end = html.index("</form>", form_start)
        form = html[form_start:form_end]
        self.assertLess(form.index('id="subject"'), form.index("compose-attachment-disclosure"))
        self.assertLess(form.index('id="bodyText"'), form.index("compose-ai-assist-disclosure"))
        self.assertIn('<summary>附件（選填）</summary>', form)
        self.assertIn('<summary>AI 協助起草（選填）</summary>', form)


if __name__ == "__main__":
    unittest.main()
