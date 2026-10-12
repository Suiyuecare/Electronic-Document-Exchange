"""Synthetic SQLite inbound-to-dispatch lifecycle; no mail/provider calls."""
import unittest
from unittest import mock

import backend
from tests import test_inbound_mutation_contract as existing


class CompleteInboundDispatchFlowTest(unittest.TestCase):
    def setUp(self):
        self.fixture = existing.InboundMutationContractTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        # This test is for the document lifecycle; notifications cannot leave it.
        self.notices = []
        patch = mock.patch.object(backend, "create_and_deliver_notification",
            side_effect=lambda conn, payload: self.notices.append(payload) or {"id": "LOCAL-NOTICE"})
        patch.start(); self.addCleanup(patch.stop)

    def test_register_assign_dispatch_read_reply_close_history_and_denials(self):
        f, conn = self.fixture, self.fixture.conn
        ga = f.session(f.ga, "official_documents.receive", "official_documents.internal_dispatch", "official_documents.all_todo")
        employee = f.session(f.employee)
        registered = backend.mutate_inbound_registration(conn, f.draft_payload("complete-register-001"), ga)
        self.assertEqual(registered["item"]["status"], "registered")
        self.assertEqual(backend.mutate_inbound_registration(conn, f.draft_payload("complete-register-001"), ga)["item"]["id"], registered["item"]["id"])
        assigned = backend.mutate_inbound_assignment(conn, registered["item"]["id"], {
            "idempotency_key": "complete-assign-001", "expected_version": registered["version"],
            "assignee_user_id": f.employee["id"], "due_at": "2099-01-01 10:00:00"}, ga)
        self.assertEqual(assigned["item"]["status"], "assigned")
        detail = backend.create_internal_dispatch(conn, {
            "inbound_document_id": assigned["item"]["id"], "subject": "去識別化派文全流程",
            "recipients": [{"user_id": f.employee["id"], "action_required": True}],
            "reply_required": True, "reply_due_days": 3}, ga)
        dispatch_id = detail["id"]
        self.assertEqual(detail["status"], "sent")
        read = backend.mark_internal_dispatch_read(conn, dispatch_id, {}, employee)
        first_read = read["recipients"][0]["read_at"]
        self.assertTrue(first_read)
        read_again = backend.mark_internal_dispatch_read(conn, dispatch_id, {}, employee)
        self.assertEqual(first_read, read_again["recipients"][0]["read_at"])
        replied = backend.reply_internal_dispatch(conn, dispatch_id, {"reply_text": "已完成去識別化測試回覆"}, employee)
        self.assertEqual(replied["status"], "reply_completed")
        self.assertEqual(replied["reply_status"], "completed")
        self.assertEqual(replied["replies"][0]["replier_user_id"], f.employee["id"])
        with self.assertRaisesRegex(PermissionError, "internal_dispatch_close_forbidden"):
            backend.close_internal_dispatch(conn, dispatch_id, {}, employee)
        closed = backend.close_internal_dispatch(conn, dispatch_id, {"comment": "測試已結案"}, ga)
        self.assertEqual(closed["status"], "closed")
        self.assertTrue(closed["closed_at"])
        with self.assertRaisesRegex(ValueError, "internal_dispatch_closed"):
            backend.reply_internal_dispatch(conn, dispatch_id, {"reply_text": "不可重開"}, employee)
        detail = backend.internal_dispatch_detail(conn, dispatch_id, employee)
        self.assertEqual(detail["replies"], closed["replies"])
        self.assertEqual({"create_internal_dispatch", "read_internal_dispatch", "reply_internal_dispatch", "close_internal_dispatch"}, {row["action"] for row in detail["logs"]})
        self.assertEqual(1, sum(row["action"] == "read_internal_dispatch" for row in detail["logs"]))
        outsider = f.add_user("FIN-OUT", "outside@example.invalid", "同名新進員工", "居家照顧部", "員工", "staff", "OUT-1")
        with self.assertRaises(PermissionError):
            backend.internal_dispatch_detail(conn, dispatch_id, f.session(outsider))
        conn.execute("UPDATE users SET status = '停用' WHERE id = ?", (outsider["id"],))
        with self.assertRaises((PermissionError, ValueError)):
            backend.create_internal_dispatch(conn, {"subject": "不可派發", "recipients": [{"user_id": outsider["id"]}]}, ga)
        self.assertEqual(2, len(self.notices))


if __name__ == "__main__":
    unittest.main()
