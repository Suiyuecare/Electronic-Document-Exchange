"""Deidentified SQLite and hosted adapter regression coverage for four P1 flows."""
import concurrent.futures
import copy
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import backend
from tests import test_inbound_mutation_contract as inbound_fixture


class InternalDispatchIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.f = inbound_fixture.InboundMutationContractTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.conn = self.f.conn
        self.ga = self.f.session(self.f.ga, "official_documents.internal_dispatch", "official_documents.receive", "official_documents.all_todo")
        self.employee = self.f.session(self.f.employee)
        self.new_user = self.f.add_user("FIN-NEW", "new@example.invalid", "去識別化接任人", "居家照顧部", "員工", "staff", "NEW-1")
        self.new_session = self.f.session(self.new_user)
        patch = mock.patch.object(backend, "create_and_deliver_notification", return_value={"id": "ISOLATED"})
        patch.start(); self.addCleanup(patch.stop)

    def payload(self, key="dispatch-request-001", **kw):
        return {"idempotency_key": key, "subject": "去識別化派文", "body": "測試用途", "reply_required": True, "reply_due_days": 3,
                "recipients": [{"user_id": self.f.employee["id"], "action_required": True}], **kw}

    def create(self, **kw):
        return backend.create_internal_dispatch(self.conn, self.payload(**kw), self.ga)

    def assign_fixture(self):
        item = backend.mutate_inbound_registration(self.conn, self.f.draft_payload("dispatch-register-001"), self.ga)
        return backend.mutate_inbound_assignment(self.conn, item["item"]["id"], {
            "idempotency_key": "dispatch-assign-001", "expected_version": item["version"], "assignee_user_id": self.f.employee["id"]}, self.ga)

    def test_response_loss_retry_single_case_notification_and_audit(self):
        first = self.create()
        second = self.create()
        self.assertEqual(first["id"], second["id"])
        for table in ("internal_dispatches", "internal_dispatch_recipients", "notifications", "internal_dispatch_logs", "internal_dispatch_mutations"):
            self.assertEqual(1, self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0], table)
        with self.assertRaisesRegex(ValueError, "internal_dispatch_idempotency_conflict"):
            self.create(body="不同內容")
        # A different user action, or an old client without key, must not be
        # merged merely because its content is identical.
        self.assertNotEqual(first["id"], self.create(key="dispatch-request-002")["id"])
        self.assertNotEqual(self.create(key="")["id"], self.create(key="")["id"])

    def test_concurrent_same_request_single_commit(self):
        self.conn.commit()
        with tempfile.TemporaryDirectory() as folder:
            target = str(Path(folder) / "isolated.sqlite3")
            disk = sqlite3.connect(target); self.conn.backup(disk); disk.close()
            ready = threading.Barrier(2)
            def submit(_):
                conn = sqlite3.connect(target, timeout=10)
                conn.row_factory = sqlite3.Row
                backend.register_sqlite_functions(conn)
                ready.wait(timeout=5)
                try:
                    return backend.create_internal_dispatch(conn, self.payload(), self.ga)["id"]
                finally:
                    conn.close()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                ids = list(pool.map(submit, range(2)))
            self.assertEqual(ids[0], ids[1])
            with sqlite3.connect(target) as check:
                self.assertEqual((1, 1, 1), tuple(check.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("internal_dispatches", "notifications", "internal_dispatch_mutations")))

    def test_failed_outbox_insert_rolls_back_all_and_retry_succeeds(self):
        with mock.patch.object(backend, "create_notification", side_effect=RuntimeError("isolated-outbox-failure")):
            with self.assertRaisesRegex(RuntimeError, "isolated-outbox-failure"):
                self.create()
        for table in ("internal_dispatches", "internal_dispatch_recipients", "internal_dispatch_logs", "internal_dispatch_mutations"):
            self.assertEqual(0, self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        self.assertEqual("sent", self.create()["status"])

    def test_pending_close_blocks_and_reply_then_close_idempotent(self):
        case = self.create()
        self.assertEqual(1, case["pending_reply_count"])
        with self.assertRaisesRegex(ValueError, "internal_dispatch_pending_replies"):
            backend.close_internal_dispatch(self.conn, case["id"], {}, self.ga)
        self.assertEqual("sent", backend.internal_dispatch_detail(self.conn, case["id"], self.ga)["status"])
        replied = backend.reply_internal_dispatch(self.conn, case["id"], {"reply_text": "已回覆"}, self.employee)
        self.assertEqual(0, replied["pending_reply_count"])
        one = backend.close_internal_dispatch(self.conn, case["id"], {}, self.ga)
        two = backend.close_internal_dispatch(self.conn, case["id"], {}, self.ga)
        self.assertEqual(one["closed_at"], two["closed_at"])
        self.assertEqual(1, sum(x["action"] == "close_internal_dispatch" for x in two["logs"]))

    def test_information_only_close_and_unrelated_actor_denied(self):
        case = self.create(reply_required=False, recipients=[{"user_id": self.f.employee["id"], "action_required": False}])
        with self.assertRaises(PermissionError):
            backend.close_internal_dispatch(self.conn, case["id"], {}, self.employee)
        self.assertEqual("closed", backend.close_internal_dispatch(self.conn, case["id"], {}, self.ga)["status"])

    def test_351_cases_paged_without_global_limit_status_scope_before_page(self):
        base = self.create()
        # 351 actor-visible cases are older than 400 unrelated cases.
        for i in range(750):
            row = {k: v for k, v in base.items() if k in {x[1] for x in self.conn.execute("PRAGMA table_info(internal_dispatches)")}}
            row.update(id=f"MANY-{i:04}", created_at="2020-01-01 00:00:00" if i < 350 else "2030-01-01 00:00:00")
            backend.insert_row(self.conn, "internal_dispatches", row)
            backend.insert_row(self.conn, "internal_dispatch_recipients", {"id": f"R-{i}", "dispatch_id": row["id"], "recipient_user_id": self.f.employee["id"] if i < 350 else self.new_user["id"], "action_required": 1, "status": "pending", "created_at": row["created_at"], "updated_at": row["created_at"]})
        found, cursor = [], None
        while True:
            query = {"paginated": ["1"], "page_size": ["50"], "needs_reply": ["1"]}
            if cursor: query["cursor"] = [cursor]
            page = backend.list_internal_dispatches(self.conn, query, self.employee)
            found.extend(x["id"] for x in page["items"])
            if not page["hasMore"]: break
            self.assertIsNotNone(page["nextCursor"])
            cursor = page["nextCursor"]
        self.assertEqual(351, len(found)); self.assertEqual(351, len(set(found)))
        self.assertIn("MANY-0000", found)
        with self.assertRaisesRegex(ValueError, "internal_dispatch_list_cursor_invalid"):
            backend.list_internal_dispatches(self.conn, {"paginated": ["1"], "cursor": [cursor]}, self.new_session)

    def test_reassignment_moves_only_pending_obligations_preserves_history(self):
        inbound = self.assign_fixture()
        waiting = self.create(inbound_document_id=inbound["item"]["id"])
        complete = self.create(key="dispatch-complete-001", inbound_document_id=inbound["item"]["id"])
        backend.reply_internal_dispatch(self.conn, complete["id"], {"reply_text": "原承辦回覆保留"}, self.employee)
        closed = self.create(key="dispatch-closed-001", inbound_document_id=inbound["item"]["id"], reply_required=False, recipients=[{"user_id": self.f.employee["id"], "action_required": False}])
        backend.close_internal_dispatch(self.conn, closed["id"], {}, self.ga)
        with self.assertRaises(PermissionError): backend.internal_dispatch_detail(self.conn, waiting["id"], self.new_session)
        result = backend.mutate_inbound_assignment(self.conn, inbound["item"]["id"], {"idempotency_key": "dispatch-reassign-001", "expected_version": inbound["version"], "assignee_user_id": self.new_user["id"]}, self.ga)
        self.assertEqual(self.new_user["id"], result["item"]["assignee_user_id"])
        detail = backend.internal_dispatch_detail(self.conn, waiting["id"], self.new_session)
        self.assertEqual(1, detail["pending_reply_count"])
        previous = next(r for r in detail["recipients"] if r["recipient_user_id"] == self.f.employee["id"])
        self.assertEqual("reassigned", previous["status"]); self.assertFalse(previous["action_required"])
        with self.assertRaisesRegex(PermissionError, "internal_dispatch_reply_forbidden"):
            backend.reply_internal_dispatch(self.conn, waiting["id"], {"reply_text": "舊承辦不能處理"}, self.employee)
        self.assertEqual("reply_completed", backend.reply_internal_dispatch(self.conn, waiting["id"], {"reply_text": "接任回覆"}, self.new_session)["status"])
        untouched = backend.internal_dispatch_detail(self.conn, complete["id"], self.ga)
        self.assertEqual(self.f.employee["id"], untouched["replies"][0]["replier_user_id"])
        self.assertEqual("原承辦回覆保留", untouched["replies"][0]["reply_text"])
        self.assertEqual(1, len(untouched["recipients"]))
        self.assertEqual(1, len(backend.internal_dispatch_detail(self.conn, closed["id"], self.ga)["recipients"]))
        log = next(x for x in detail["logs"] if x["action"] == "reassign_internal_dispatch")
        self.assertEqual(self.f.ga["id"], log["actor_id"])
        self.assertEqual(self.f.employee["id"], json.loads(log["detail"])["previous_user_id"])

    def test_reassignment_failure_rolls_back_inbound_and_dispatch(self):
        inbound = self.assign_fixture(); waiting = self.create(inbound_document_id=inbound["item"]["id"])
        with mock.patch.object(backend, "internal_dispatch_log", side_effect=RuntimeError("isolated-handoff-audit-failure")):
            with self.assertRaises(RuntimeError):
                backend.mutate_inbound_assignment(self.conn, inbound["item"]["id"], {"idempotency_key": "dispatch-failed-handoff", "expected_version": inbound["version"], "assignee_user_id": self.new_user["id"]}, self.ga)
        current = backend.inbound_document_detail(self.conn, inbound["item"]["id"], self.ga)
        self.assertEqual(inbound["version"], current["mutation_version"])
        self.assertEqual(self.f.employee["id"], current["assignee_user_id"])
        self.assertEqual(1, len(backend.internal_dispatch_detail(self.conn, waiting["id"], self.ga)["recipients"]))

    def test_previously_replied_successor_gets_new_pending_row_and_can_read_reply_close(self):
        inbound = self.assign_fixture()
        case = self.create(inbound_document_id=inbound["item"]["id"], recipients=[{"user_id": self.f.employee["id"], "action_required": True}, {"user_id": self.new_user["id"], "action_required": True}])
        backend.mark_internal_dispatch_read(self.conn, case["id"], {}, self.new_session)
        original = backend.reply_internal_dispatch(self.conn, case["id"], {"reply_text": "接任前已回覆"}, self.new_session)["replies"][0]
        backend.mutate_inbound_assignment(self.conn, inbound["item"]["id"], {"idempotency_key": "dispatch-replied-handoff", "expected_version": inbound["version"], "assignee_user_id": self.new_user["id"]}, self.ga)
        detail = backend.mark_internal_dispatch_read(self.conn, case["id"], {}, self.new_session)
        active = backend.internal_dispatch_workflow.actor_recipient(detail["recipients"], self.new_user["id"])
        self.assertNotEqual(original["recipient_id"], active["id"])
        self.assertEqual("pending", active["status"]); self.assertTrue(active["read_at"])
        detail = backend.reply_internal_dispatch(self.conn, case["id"], {"reply_text": "承接後回覆"}, self.new_session)
        self.assertEqual(0, detail["pending_reply_count"])
        self.assertEqual({original["recipient_id"], active["id"]}, {r["recipient_id"] for r in detail["replies"]})
        self.assertEqual("closed", backend.close_internal_dispatch(self.conn, case["id"], {}, self.ga)["status"])

    def test_handoff_back_to_original_recipient_keeps_history_and_new_obligation(self):
        inbound = self.assign_fixture(); case = self.create(inbound_document_id=inbound["item"]["id"])
        second = backend.mutate_inbound_assignment(self.conn, inbound["item"]["id"], {"idempotency_key": "dispatch-handoff-B", "expected_version": inbound["version"], "assignee_user_id": self.new_user["id"]}, self.ga)
        backend.mutate_inbound_assignment(self.conn, inbound["item"]["id"], {"idempotency_key": "dispatch-handoff-A", "expected_version": second["version"], "assignee_user_id": self.f.employee["id"]}, self.ga)
        detail = backend.internal_dispatch_detail(self.conn, case["id"], self.employee)
        self.assertEqual(1, detail["pending_reply_count"])
        self.assertEqual(2, sum(r["status"] == "reassigned" for r in detail["recipients"]))
        with self.assertRaises(PermissionError): backend.reply_internal_dispatch(self.conn, case["id"], {}, self.new_session)
        self.assertEqual("reply_completed", backend.reply_internal_dispatch(self.conn, case["id"], {"reply_text": "回任後完成"}, self.employee)["status"])

    def test_hosted_adapter_uses_one_scoped_rpc_not_301_http_reads(self):
        item = {"id": "IDISP-OLD", "created_at": "2020-01-01", "recipients": [], "pending_reply_count": 0}
        with mock.patch.object(backend, "supabase_request", return_value={"items": [item]}) as request, mock.patch.object(backend, "supabase_filter_rows") as per_row:
            result = backend.supabase_list_internal_dispatches({"paginated": ["1"], "needs_reply": ["1"]}, self.employee)
        self.assertEqual([item], result["items"]); per_row.assert_not_called(); request.assert_called_once()
        params = request.call_args.args[2]
        self.assertEqual(self.f.employee["id"], params["p_actor_user_id"])
        self.assertTrue(params["p_needs_reply"]); self.assertFalse(params["p_company_wide"])


if __name__ == "__main__": unittest.main()
