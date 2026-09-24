"""Complete authorized lists, stable cursors, and independent disclosure guards."""
import base64
import json
import sqlite3
import re
from pathlib import Path
import unittest
from unittest import mock

import backend
import official_listing


class OfficialListPaginationTest(unittest.TestCase):
    def setUp(self):
        self.session = {"user": {"id": "ACTOR", "company_id": "CO"}, "permissions": []}
        self.bundles = [{"document": {
            "id": f"DOC-{i:04d}", "company_id": "CO", "applicant_id": "ACTOR",
            "created_at": "2026-09-24 10:00:00", "current_status": "draft", "current_step": "",
            "title": f"Synthetic {i}", "metadata_json": "{}",
        }, "steps": [], "snapshots": []} for i in range(1001)]
        self.calls = 0

    def rpc(self, method, path, payload):
        self.assertEqual((method, path), ("POST", "rpc/edoc_list_official_document_candidates"))
        self.calls += 1
        request = payload["p_request"]
        rows = sorted(self.bundles, key=lambda b: (b["document"]["created_at"], b["document"]["id"]), reverse=True)
        if request["after_id"]:
            rows = [b for b in rows if (b["document"]["created_at"], b["document"]["id"]) < (request["after_created_at"], request["after_id"])]
        return {"items": rows[:request["limit"]]}

    def read(self, query=None):
        with mock.patch.object(backend, "supabase_request", side_effect=self.rpc):
            return backend.supabase_list_official_documents(query or {}, self.session)

    def test_all_pages_same_timestamp_no_duplicates_or_300_row_cutoff(self):
        query, ids = {"scope": ["mine"], "page_size": ["50"]}, []
        while True:
            page = self.read(query)
            self.assertLessEqual(len(page["items"]), 50)
            ids.extend(row["id"] for row in page["items"])
            if not page["has_more"]:
                self.assertIsNone(page["next_cursor"])
                break
            query["cursor"] = [page["next_cursor"]]
        self.assertEqual(ids, [f"DOC-{i:04d}" for i in reversed(range(1001))])
        self.assertEqual(21, self.calls)

    def test_legacy_array_also_complete(self):
        rows = self.read({"scope": ["mine"]})
        self.assertEqual(1001, len(rows))
        self.assertEqual(11, self.calls)

    def test_search_and_view_find_old_actionable_case_not_only_first_page(self):
        old = self.bundles[0]["document"]
        old.update(title="Old actionable target", current_status="rejected")
        result = self.read({"scope": ["all"], "page_size": ["50"], "search": ["actionable"], "view": ["my_pending"]})
        self.assertEqual(["DOC-0000"], [r["id"] for r in result["items"]])
        self.assertFalse(result["has_more"])

    def test_scope_and_company_are_rechecked_if_rpc_returns_excessive_candidates(self):
        for bundle in self.bundles[1:]:
            bundle["document"].update(applicant_id="OTHER", company_id="FOREIGN")
        result = self.read({"scope": ["all"], "page_size": ["50"]})
        self.assertEqual(["DOC-0000"], [r["id"] for r in result["items"]])
        self.assertFalse(result["has_more"])

    def test_localized_status_and_current_actor_search_remain_available(self):
        self.bundles[0]["document"].update(current_status="closed")
        result = self.read({"search": ["已結案"], "page_size": ["50"]})
        self.assertEqual(["DOC-0000"], [r["id"] for r in result["items"]])
        self.bundles[0]["document"].update(current_status="pending_applicant_manager", current_step="applicant_manager")
        self.bundles[0]["steps"] = [{"id": "STEP", "step_order": 1, "step_key": "applicant_manager", "status": "pending",
                                     "approver_user_id": "REVIEWER", "approver_name": "合成主管甲"}]
        result = self.read({"search": ["合成主管甲"], "page_size": ["50"]})
        self.assertEqual(["DOC-0000"], [r["id"] for r in result["items"]])
        source = (Path(__file__).resolve().parents[1] / "app.js").read_text()
        for js_name, expected in (("officialStatusLabels", official_listing.STATUS_LABELS), ("officialWorkflowStepLabels", official_listing.STEP_LABELS)):
            body = re.search(r"const " + js_name + r" = \{(.*?)\n\};", source, re.S).group(1)
            self.assertEqual(expected, dict(re.findall(r'(\w+): "([^"]+)"', body)))

    def test_dashboard_attention_and_persisted_correction_deadline(self):
        for bundle in self.bundles:
            bundle["document"]["current_status"] = "closed"
        self.bundles[0]["document"].update(current_status="rejected", correction_due_at="2020-01-01 00:00:00")
        self.bundles[1]["document"].update(current_status="draft")
        attention = self.read({"view": ["attention"], "page_size": ["50"]})
        self.assertEqual(["DOC-0001", "DOC-0000"], [r["id"] for r in attention["items"]])
        overdue = self.read({"view": ["overdue"], "page_size": ["50"]})
        self.assertEqual(["DOC-0000"], [r["id"] for r in overdue["items"]])

    def test_old_historical_participant_can_see_but_not_act_on_new_generation(self):
        self.bundles = [self.bundles[0]]
        self.bundles[0]["document"].update(applicant_id="OTHER", company_id="FOREIGN", current_step="general_affairs", current_status="pending_general_affairs")
        self.bundles[0]["steps"] = [
            {"id": "OLD", "workflow_generation": 1, "step_key": "general_affairs", "status": "approved", "approver_user_id": "ACTOR"},
            {"id": "NEW", "workflow_generation": 2, "step_key": "general_affairs", "status": "pending", "approver_user_id": "NEW-ACTOR"},
        ]
        item = self.read({"scope": ["all"]})[0]
        self.assertTrue(item["can_download"])
        self.assertFalse(item["can_act"])
        self.assertEqual(["NEW"], [s["id"] for s in item["approval_steps"]])

    def test_cursor_is_bound_to_actor_and_filters(self):
        cursor = self.read({"page_size": ["50"]})["next_cursor"]
        for change in ({"search": ["different"]}, {"view": ["processed"]}, {"scope": ["mine"]}):
            with self.assertRaisesRegex(ValueError, "cursor_invalid"):
                self.read({"page_size": ["50"], "cursor": [cursor], **change})
        self.session["user"]["id"] = "ANOTHER"
        with self.assertRaisesRegex(ValueError, "cursor_invalid"):
            self.read({"page_size": ["50"], "cursor": [cursor]})

    def test_failed_stamp_is_actionable_for_current_ga_without_pending_approval(self):
        self.bundles = [self.bundles[0]]
        bundle = self.bundles[0]
        bundle["document"].update(applicant_id="OTHER", current_step="general_affairs_review", current_status="stamping_failed")
        bundle["steps"] = [{"id": "GA", "workflow_generation": 2, "step_key": "general_affairs_review", "status": "approved", "approver_user_id": "ACTOR"}]
        bundle["stamp_request"] = {"id": "STAMP", "status": "failed", "stamped_file_id": None}
        result = self.read({"view": ["attention"], "page_size": ["50"]})
        self.assertEqual(1, len(result["items"]))
        self.assertTrue(result["items"][0]["can_retry_stamp"])
        self.assertFalse(result["items"][0]["can_act"])
        self.assertEqual(1, len(self.read({"view": ["my_pending"]})))

    def test_malformed_cursor_and_page_size_fail_without_storage_read(self):
        for value in ({}, [], None, ["x"], ["x", "date", "id"]):
            cursor = base64.urlsafe_b64encode(json.dumps(value).encode()).decode()
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "cursor_invalid"):
                self.read({"cursor": [cursor]})
        for size in ("0", "101", "-1", "abc"):
            with self.assertRaisesRegex(ValueError, "page_size_invalid"):
                self.read({"page_size": [size]})
        self.assertEqual(0, self.calls)

    def test_nonadvancing_adapter_fails_closed_instead_of_looping(self):
        with mock.patch.object(backend, "supabase_request", return_value={"items": [self.bundles[0], self.bundles[0]]}):
            with self.assertRaisesRegex(RuntimeError, "cursor_not_advancing"):
                backend.supabase_list_official_documents({}, self.session)

    def test_backend_only_tokens_never_leak_through_list_projection(self):
        self.bundles = [self.bundles[0]]
        self.bundles[0]["stamp_request"] = {"id": "STAMP", "claim_token": "PRIVATE", "claim_owner_id": "PRIVATE"}
        self.assertNotIn("PRIVATE", json.dumps(self.read()))
        self.assertIn("edoc_list_official_document_candidates", backend.EDOC_READINESS_REQUIRED_RPC_NAMES)

    def test_delegation_is_current_unexpired_and_requalified_without_n_plus_one(self):
        from tests.test_launch_permission_regressions import DelegatedReadGuardParityTest
        fixture = DelegatedReadGuardParityTest()
        fixture.setUp()
        self.session = fixture.session
        self.bundles = [{"document": {**fixture.document, "created_at": "2026-09-24 10:00:00"},
                         "steps": [fixture.step], "snapshots": [], "delegations": [fixture.delegation],
                         "delegation_users": [{**fixture.user, "id": "principal"}, fixture.user]}]
        page = self.read({"page_size": ["50"], "view": ["delegated"]})
        self.assertEqual(1, len(page["items"]))
        self.assertTrue(page["items"][0]["can_act"])
        self.assertTrue(page["items"][0]["can_download"])
        self.assertEqual("principal", page["items"][0]["acting_for_user_id"])
        self.assertEqual(1, self.calls)
        fixture.delegation["ends_at"] = "2020-01-01 00:00:00"
        self.assertEqual([], self.read({"scope": ["all"]}))
        fixture.delegation["ends_at"] = "2099-01-01 00:00:00"
        fixture.user["status"] = "停用"
        self.assertEqual([], self.read({"scope": ["all"]}))


class SQLiteOfficialListPaginationTest(unittest.TestCase):
    def test_real_sqlite_scope_and_old_case_pagination(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        backend.register_sqlite_functions(conn)
        conn.executescript(backend.SCHEMA)
        conn.execute("INSERT INTO companies(id,name,created_at,updated_at) VALUES ('CO','Synthetic','x','x')")
        rows = [(f"DOC-{i:04d}", "OTHER" if i > 500 else "ACTOR", "2026-09-24 10:00:00") for i in range(1001)]
        conn.executemany("INSERT INTO official_documents(id,company_id,source_type,title,applicant_id,current_status,created_at,updated_at) VALUES (?,'CO','uploaded_pdf','Synthetic',?,'draft',?,'x')", rows)
        session = {"user": {"id": "ACTOR", "company_id": "CO"}, "permissions": []}
        query, ids = {"scope": ["mine"], "page_size": ["50"]}, []
        while True:
            page = backend.list_official_documents(conn, query, session)
            ids.extend(row["id"] for row in page["items"])
            if not page["has_more"]:
                break
            query["cursor"] = [page["next_cursor"]]
        self.assertEqual([f"DOC-{i:04d}" for i in reversed(range(501))], ids)


if __name__ == "__main__":
    unittest.main()
