"""Supervisor audit views use immutable decisions, complete scoped histories."""
import copy
import json
import time
import unittest
import urllib.parse
from unittest import mock

import backend
from tests import test_configurable_official_workflow as fixture


class OfficialDecisionDisplayTest(unittest.TestCase):
    def step(self, **values):
        return {"id": "STEP-1", "document_id": "DOC", "status": "approved", "approver_user_id": "PRINCIPAL", "approver_name": "原指派主管", "decision_actor_user_id": "DELEGATE", "decision_evidence_json": "{}", **values}

    def log(self, **values):
        return {"id": "LOG-1", "document_id": "DOC", "step_id": "STEP-1", "action": "approve", "actor_id": "DELEGATE", "actor_name": "實際代理人", "created_at": "2026-09-22 01:00:00", **values}

    def test_completed_delegate_uses_immutable_actor_name_not_assignment(self):
        steps, logs = [self.step()], [self.log()]
        before = copy.deepcopy((steps, logs))
        row = backend.official_step_decision_display(steps, logs)[0]
        self.assertEqual(row["decision_actor_name"], "實際代理人")
        self.assertEqual(row["decision_actor_id"], "DELEGATE")
        self.assertEqual(row["decision_log_id"], "LOG-1")
        self.assertEqual((steps, logs), before)

    def test_copied_approved_prefix_resolves_original_decision_across_generations(self):
        original = self.step()
        second = self.step(id="STEP-2", decision_evidence_json={"copied_from_step_id": "STEP-1"})
        third = self.step(id="STEP-3", decision_evidence_json={"copied_from_step_id": "STEP-2"})
        rows = backend.official_step_decision_display([original, second, third], [self.log()])
        self.assertEqual([row["decision_actor_name"] for row in rows], ["實際代理人"] * 3)
        added = self.step(id="ADDED-COPY", decision_evidence_json={"copied_from_step_id": "OLD-CURRENT"})
        row = backend.official_step_decision_display([added], [self.log(step_id="OLD-CURRENT", action="add_sign")])[0]
        self.assertEqual(row["decision_actor_name"], "實際代理人")

    def test_unknown_conflicting_foreign_and_pending_rows_never_impersonate_assignee(self):
        cases = (
            (self.step(), [], "DELEGATE"),
            (self.step(), [self.log(document_id="OTHER")], "DELEGATE"),
            (self.step(), [self.log(actor_id="OTHER")], "DELEGATE"),
            (self.step(status="pending"), [self.log()], ""),
            (self.step(status="skipped"), [self.log()], ""),
            (self.step(decision_actor_user_id=""), [self.log(), self.log(id="LOG-2", actor_id="OTHER")], ""),
        )
        for step, logs, actor_id in cases:
            with self.subTest(status=step["status"], logs=logs):
                row = backend.official_step_decision_display([step], logs)[0]
                self.assertEqual(row["decision_actor_name"], "")
                self.assertEqual(row["decision_actor_id"], actor_id)

    def test_legacy_receipt_uses_exact_confirm_audit_time_and_actor(self):
        step = self.step(step_key="applicant_confirm", decision_actor_user_id="", approved_at="2026-09-22 01:00:00")
        log = self.log(step_id=None, action="confirm", actor_id="PRINCIPAL", actor_name="實際收件人")
        self.assertEqual(backend.official_step_decision_display([step], [log])[0]["decision_actor_name"], "實際收件人")
        self.assertEqual(backend.official_step_decision_display([step], [{**log, "created_at": "2026-09-21 01:00:00"}])[0]["decision_actor_name"], "")

    def test_deep_history_is_iterative_and_indexed_without_losing_actor_conflicts(self):
        count = backend.OFFICIAL_HISTORY_MAX_ROWS
        steps = [self.step(id=f"STEP-{index}", decision_actor_user_id="", decision_evidence_json={"copied_from_step_id": f"STEP-{index - 1}"} if index else {}) for index in range(count)]
        logs = [self.log(id=f"LOG-{index}", step_id=f"UNRELATED-{index}") for index in range(count - 2)]
        logs += [self.log(id="ORIGIN", step_id="STEP-0"), self.log(id="CONFLICT", step_id=f"STEP-{count // 2}", actor_id="OTHER")]
        started = time.perf_counter()
        rows = backend.official_step_decision_display(list(reversed(steps)), logs)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 1.0, f"10,000-row deep history took {elapsed:.3f}s")
        self.assertEqual(rows[-1]["decision_actor_name"], "實際代理人")
        self.assertEqual(rows[count // 2]["decision_actor_name"], "實際代理人")
        self.assertTrue(all(row["decision_actor_name"] == "" for row in rows[:count // 2]))

    def test_cycle_uses_source_relative_nearest_witness_and_keeps_conflicts_unknown(self):
        steps = [self.step(id="A", decision_evidence_json={"copied_from_step_id": "B"}), self.step(id="B", decision_evidence_json={"copied_from_step_id": "A"})]
        logs = [self.log(id="LOG-A", step_id="A"), self.log(id="LOG-B", step_id="B")]
        rows = backend.official_step_decision_display(steps, logs)
        self.assertEqual([row["decision_log_id"] for row in rows], ["LOG-A", "LOG-B"])
        steps = [{**row, "decision_actor_user_id": ""} for row in steps]
        logs[1]["actor_id"] = "OTHER"
        self.assertTrue(all(row["decision_actor_name"] == "" for row in backend.official_step_decision_display(steps, logs)))


class OfficialHistoryPaginationTest(unittest.TestCase):
    def rows(self, count, *, logs=False):
        return [{"id": f"ROW-{index:05d}", "document_id": "DOC", "workflow_generation": index // 5 + 1, "step_order": index % 5 + 1, "created_at": "2026-09-22 01:00:00"} for index in range(count)]

    def run_paged(self, rows, *, logs=False, middle=None):
        calls = []
        def request(method, path):
            self.assertEqual(method, "GET")
            query = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
            calls.append(query)
            self.assertEqual(query["document_id"], ["eq.DOC"])
            self.assertNotIn("offset", query)
            self.assertIn("ROW-00199", query["and"][0])
            self.assertIn(rows[-1]["id"], query["and"][0])
            self.assertIn("id.asc", query["order"][0])
            return middle if middle is not None else rows[200:]
        with mock.patch.object(backend, "supabase_filter_rows", side_effect=[rows[:200], [rows[-1]]]), mock.patch.object(backend, "supabase_request", side_effect=request):
            result = backend.supabase_official_document_logs("DOC") if logs else backend.supabase_official_document_steps("DOC")
        return result, calls

    def test_more_than_200_steps_include_current_generation_without_duplicates(self):
        rows = self.rows(237)
        result, calls = self.run_paged(rows)
        self.assertEqual(result, rows)
        self.assertEqual(result[-1]["workflow_generation"], 48)
        self.assertEqual(len({row["id"] for row in result}), 237)
        self.assertEqual(len(calls), 1)

    def test_tied_timestamps_keep_all_older_decision_logs_with_stable_id_boundary(self):
        rows = self.rows(239, logs=True)
        result, _ = self.run_paged(rows, logs=True)
        self.assertEqual(result, list(reversed(rows)))

    def test_scope_duplicate_truncation_and_ceiling_violations_fail_closed(self):
        rows = self.rows(202)
        for suffix in ([{**rows[200], "document_id": "OTHER"}], [rows[199]], [], [rows[200]], [self.rows(203)[202]]):
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, "history_unavailable"):
                self.run_paged(rows, middle=suffix)
        with mock.patch.object(backend, "OFFICIAL_HISTORY_MAX_ROWS", 201):
            with self.assertRaisesRegex(ValueError, "too_large"):
                self.run_paged(rows)
        self.assertEqual(backend.api_value_error_status("official_workflow_history_unavailable:too_large"), 503)


class OfficialAuditIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.ConfigurableOfficialWorkflowTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.conn = self.fixture.conn

    def test_history_display_and_download_acl_survive_return_and_add_sign(self):
        helper = self.fixture
        detail = helper.fixture._submitted()[0]
        _, reviewer, payload = helper._review(detail)
        payload.update(operation_id="AUDIT-ADD-SIGN", target_user_id=helper.target_id)
        added = backend.mutate_official_workflow(self.conn, detail["id"], "add_sign", payload, reviewer)
        self.assertEqual(added["approval_steps"][0]["decision_actor_name"], reviewer["user"]["name"])
        target_reviewed = helper._approve(added)
        _, next_reviewer, payload = helper._review(target_reviewed)
        payload["operation_id"] = "AUDIT-RETURN-PREVIOUS"
        returned = backend.mutate_official_workflow(self.conn, detail["id"], "return_previous", payload, next_reviewer)
        raw_before = backend.official_document_steps(self.conn, detail["id"])
        actual_before = copy.deepcopy(raw_before)
        local = backend.official_document_detail(self.conn, detail["id"], helper.session)
        with helper.fixture._supabase_adapter(), mock.patch.object(backend, "supabase_official_document_actor_snapshots", return_value=backend.official_document_actor_snapshots(self.conn, detail["id"])):
            remote = backend.supabase_official_document_detail(detail["id"], helper.session)
        self.assertEqual(local["approval_step_history"], remote["approval_step_history"])
        self.assertEqual(backend.official_document_steps(self.conn, detail["id"]), actual_before)
        self.assertEqual({row["workflow_generation"] for row in returned["approval_step_history"]}, {1, 2, 3})
        first = returned["approval_steps"][0]
        self.assertEqual(first["decision_actor_name"], reviewer["user"]["name"])
        self.assertTrue(all(row["decision_actor_name"] == "" for row in returned["approval_steps"] if row["status"] == "pending"))
        final = helper.fixture.fixture._approve_and_stamp(returned)
        file_id = final["stamped_file_id"]
        for session in (helper.session, reviewer, helper.fixture.fixture._session_for_user_id(helper.target_id)):
            self.assertTrue(backend.official_document_download_file(self.conn, detail["id"], file_id, session)[2].startswith(b"%PDF"))
        stranger = helper.fixture.fixture._session_for_user_id(helper.fixture.fixture.applicant_ids[3])
        with self.assertRaisesRegex(PermissionError, "download_forbidden"):
            backend.official_document_download_file(self.conn, detail["id"], file_id, stranger)
        with helper.fixture._supabase_adapter(), mock.patch.object(backend, "supabase_official_document_actor_snapshots", return_value=backend.official_document_actor_snapshots(self.conn, detail["id"])), mock.patch.object(backend, "supabase_storage_create_signed_download_url") as sign:
            with self.assertRaisesRegex(PermissionError, "download_forbidden"):
                backend.supabase_official_document_download_file(detail["id"], file_id, stranger)
            sign.assert_not_called()


if __name__ == "__main__":
    unittest.main()
