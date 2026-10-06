from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import backend
from tests.test_inbound_mutation_contract import InboundMutationContractTests
from tests.test_inbound_lazy_loading import extract_function


ROOT = Path(__file__).resolve().parents[1]


class PersonnelAndInboundReadinessTests(InboundMutationContractTests):
    def registered(self):
        return backend.mutate_inbound_registration(
            self.conn, self.draft_payload("readiness-register-01"), self.session(self.ga, "official_documents.receive")
        )

    def test_inactive_handler_is_flagged_and_can_be_reassigned_without_rewriting_history(self):
        session = self.session(self.ga, "official_documents.receive", "official_documents.all_todo")
        created = self.registered()
        first = backend.mutate_inbound_assignment(self.conn, created["item"]["id"], {
            "idempotency_key": "readiness-assign-01", "expected_version": created["version"],
            "assignee_user_id": self.employee["id"], "due_at": "2099-10-06",
        }, session)
        self.conn.execute("UPDATE users SET status='停用' WHERE id=?", (self.employee["id"],))
        inactive = backend.inbound_document_detail(self.conn, first["item"]["id"], session)
        self.assertTrue(inactive["handover_required"])
        self.assertEqual(inactive["assignee_name"], "新進員工")
        second = backend.mutate_inbound_assignment(self.conn, first["item"]["id"], {
            "idempotency_key": "readiness-assign-02", "expected_version": first["version"],
            "assignee_user_id": self.ga["id"], "due_at": "2099-10-07", "note": "離職承辦交接測試",
        }, session)
        self.assertFalse(second["item"]["handover_required"])
        self.assertEqual(second["item"]["assignee_user_id"], self.ga["id"])
        history = self.conn.execute("SELECT detail FROM audit_logs WHERE target_id=? AND action='assign_inbound_document'", (first["item"]["id"],)).fetchall()
        self.assertEqual(len(history), 2)
        self.assertIn("新進員工", history[0]["detail"])

    def test_malformed_deadline_is_rejected_before_any_assignment(self):
        created = self.registered()
        session = self.session(self.ga, "official_documents.receive")
        for value in ("not-a-date", "2026-02-30", "2026-13-02", "2026-10-06<script>"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "case_due_at_invalid"):
                backend.mutate_inbound_assignment(self.conn, created["item"]["id"], {
                    "idempotency_key": "readiness-invalid-date", "expected_version": created["version"],
                    "assignee_user_id": self.employee["id"], "due_at": value,
                }, session)
        row = backend.inbound_document_detail(self.conn, created["item"]["id"], session)
        self.assertEqual(row["status"], "registered")

    def test_ga_assignment_directory_contains_staff_without_granting_delegation_control(self):
        session = self.session(self.ga, "official_documents.receive", "official_documents.all_todo")
        with self.assertRaisesRegex(PermissionError, "official_workflow_delegation_finance_actor_ineligible"):
            backend.official_workflow_delegation_candidates(self.conn, session)
        recipients = backend.internal_dispatch_recipient_directory(self.conn, session)
        self.assertIn(self.employee["id"], {row["id"] for row in recipients})


class HostedInboundPerformanceTests(unittest.TestCase):
    def test_list_batches_related_rows_and_preserves_company_acl(self):
        user = {"id": "GA", "status": "啟用", "account_source": "finance", "company_id": "CO-A", "finance_tenant_id": "TENANT-A", "unit": "總務"}
        session = {"user": user, "permissions": ["official_documents.receive"]}
        rows = [{"id": f"IN-{index}", "company_id": "CO-A", "finance_tenant_id": "TENANT-A", "status": "assigned", "assignee_user_id": "STAFF", "metadata_json": {}} for index in range(40)]
        rows.append({"id": "FOREIGN", "company_id": "CO-B", "finance_tenant_id": "TENANT-B"})
        calls = []
        def request(method, path, *args, **kwargs):
            from urllib.parse import parse_qs, urlsplit
            calls.append(path)
            table = urlsplit(path).path
            params = parse_qs(urlsplit(path).query)
            if table == "inbound_documents":
                self.assertEqual(params["company_id"], ["eq.CO-A"])
                return rows
            if table == "inbound_document_attachments":
                return [{"id": f"ATT-{index}", "inbound_document_id": f"IN-{index}"} for index in range(40)]
            if table == "users":
                return [{"id": "STAFF", "status": "啟用", "company_id": "CO-A", "finance_tenant_id": "TENANT-A"}]
            raise AssertionError(path)
        with mock.patch.object(backend, "supabase_official_session_user", return_value=user), mock.patch.object(backend, "supabase_request", side_effect=request):
            result = backend.supabase_list_inbound_documents({}, session)
        self.assertEqual(len(result), 40)
        self.assertLessEqual(len(calls), 4, "list must not issue 2 requests per document")
        self.assertTrue(all(len(item["attachments"]) == 1 for item in result))
        self.assertFalse(any(item["handover_required"] for item in result))
        self.assertFalse(any("FOREIGN" in path for path in calls))


class DeadlineAndHandoverValidationTests(unittest.TestCase):
    def test_reply_deadline_is_bounded_and_calendar_validated(self):
        for days in (0, -1, 366, True, None, 1.5, "3.0", "invalid"):
            with self.subTest(days=days), self.assertRaisesRegex(ValueError, "internal_dispatch_due_days_invalid"):
                backend.internal_dispatch_deadline({"reply_due_days": days}, True)
        for date in ("2026-02-30", "2026-10-06 25:00:00", "tomorrow"):
            with self.subTest(date=date), self.assertRaisesRegex(ValueError, "case_due_at_invalid"):
                backend.internal_dispatch_deadline({"due_at": date}, True)
        self.assertEqual(backend.internal_dispatch_deadline({"reply_due_days": 3, "due_at": "2099-01-01"}, True), (3, "2099-01-01"))
        self.assertEqual(backend.internal_dispatch_deadline({"reply_due_days": "invalid"}, False), (0, ""))

    def test_handover_flags_missing_disabled_and_out_of_scope_handlers_but_not_closed_history(self):
        document = {"assignee_user_id": "STAFF", "status": "assigned", "company_id": "CO", "finance_tenant_id": "TENANT"}
        active = {"id": "STAFF", "status": "啟用", "company_id": "CO", "finance_tenant_id": "TENANT"}
        self.assertFalse(backend.inbound_handover_required(document, active))
        for actor in (None, {**active, "status": "停用"}, {**active, "company_id": "OTHER"}, {**active, "finance_tenant_id": "OTHER"}):
            self.assertTrue(backend.inbound_handover_required(document, actor))
        for status in ("closed", "archived", "cancelled"):
            self.assertFalse(backend.inbound_handover_required({**document, "status": status}, None))


class FrontendReadinessTests(unittest.TestCase):
    def test_assignment_uses_independent_full_scoped_directory(self):
        source = (ROOT / "app.js").read_text()
        loader = extract_function(source, "loadInboundAssigneeCandidates")
        self.assertIn('/internal-dispatches/recipients', loader)
        self.assertNotIn('/workflow-delegations/candidates', loader)
        self.assertNotIn('workflowProxyCandidates =', loader)
        self.assertIn('frontendSessionScope()', loader)
        self.assertIn('if (throwOnError) throw error', loader)
        route = extract_function(source, 'loadRouteBackendData')
        self.assertIn('loadInboundAssigneeCandidates({ throwOnError: true })', route)
        self.assertIn('loadInternalDispatches(silent, { throwOnError: true })', route)

    def test_export_downloads_real_csv_and_dispatch_closes_obscuring_modal(self):
        source = (ROOT / "app.js").read_text()
        export = extract_function(source, "exportFilteredInboundCsv")
        self.assertIn('downloadTextFile(', export)
        self.assertIn('filteredInboundDocs()', export)
        self.assertIn('inboundCsvCell', export)
        actions = extract_function(source, "bindInboundDetailActions")
        self.assertIn('closeInboundModal()', actions)
        self.assertIn('exportFilteredInboundCsv()', actions)
        self.assertIn('prepareInternalDispatchForInbound(doc)', actions)
        prepare = extract_function(source, "prepareInternalDispatchForInbound")
        self.assertLess(prepare.index('await loadInternalDispatches'), prepare.index('internal-dispatch-recipient-check'))

    def test_csv_cells_are_quoted_and_spreadsheet_formula_safe(self):
        source = (ROOT / "app.js").read_text()
        script = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
const c={String};vm.createContext(c);vm.runInContext(JSON.parse(process.argv[1]),c);
for(const value of ['=HYPERLINK("bad")',' +CMD','@SUM(A1)','-1'])assert.ok(c.inboundCsvCell(value).startsWith('"\''));
assert.equal(c.inboundCsvCell('a,"b"'),'"a,""b"""');
assert.equal(c.inboundCsvCell('正常主旨'),'"正常主旨"');
'''
        result = subprocess.run(['node', '-e', script, json.dumps(extract_function(source, 'inboundCsvCell'))], cwd=ROOT, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_overdue_stats_require_real_deadline_and_include_reply_progress(self):
        source = (ROOT / "app.js").read_text()
        funcs = '\n'.join(extract_function(source, name) for name in ('caseDueTimestamp', 'caseIsOverdue', 'internalDispatchPendingRecipients', 'reportStats'))
        script = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
const c={Date,Number,Math,Set,Object,String,Array,
 inboundDocs:[{id:'IN1',status:'已收文',dueDate:'2000-01-01',owner:'員工',dept:'新單位',subject:'未結收文'}],
 dispatchDocs:[],archiveRecords:[],trackingCases:[{id:'T1',status:'未收確認',dueDate:'2099-01-01'}],
 workflowTasks:[{id:'W1',title:'沒有期限的待簽核',status:'待簽核',role:'主管'}],
 internalDispatchItems:[{id:'D1',status:'sent',reply_required:true,due_at:'2000-01-01',subject:'需回覆',recipients:[{recipient_name:'承辦',action_required:true,status:'pending'}]},
 {id:'D2',status:'sent',reply_required:true,due_at:'2000-01-01',recipients:[{action_required:true,status:'replied'}]}],
 userAccounts:[{unit:'新單位',status:'啟用'}]};
vm.createContext(c);vm.runInContext(JSON.parse(process.argv[1]),c);
const stats=c.reportStats();
assert.deepEqual(Array.from(stats.overdueItems.map(x=>x.id)).sort(),['D1','IN1']);
assert.equal(stats.replyPendingCount,1);assert.equal(stats.unitRows[0].unit,'新單位');
assert.equal(c.caseIsOverdue('invalid'),false);assert.equal(c.caseIsOverdue('2099-01-01'),false);
assert.equal(c.caseIsOverdue('2000-02-30'),false);
process.stdout.write('passed');
'''
        result = subprocess.run(['node', '-e', script, json.dumps(funcs)], cwd=ROOT, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
