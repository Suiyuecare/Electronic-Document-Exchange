from __future__ import annotations

import copy
import json
import sqlite3
import unittest
from unittest import mock

import backend


class OverdueReminderTests(unittest.TestCase):
    """Deidentified RAM-only reminders; external providers are forbidden."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(backend.SCHEMA)
        self.addCleanup(self.conn.close)
        self.user = {"id": "TEST-ASSIGNEE", "name": "測試承辦人", "email": "assignee@example.invalid", "role": "員工", "unit": "TEST-UNIT", "company_id": "TEST-COMPANY", "finance_tenant_id": "TEST-TENANT", "account_source": "finance", "status": "啟用", "created_at": "2026-10-08"}
        self.other = {**self.user, "id": "TEST-OTHER", "email": "other@example.invalid", "name": "同職稱其他人"}
        self.company = {"id": "TEST-COMPANY", "name": "測試公司", "finance_tenant_id": "TEST-TENANT", "source_system": "finance", "status": "active", "created_at": "2026-10-08", "updated_at": "2026-10-08"}
        for user in (self.user, self.other):
            self.conn.execute("INSERT INTO users (id,name,email,role,unit,company_id,finance_tenant_id,account_source,status,created_at) VALUES (:id,:name,:email,:role,:unit,:company_id,:finance_tenant_id,:account_source,:status,:created_at)", user)
        self.conn.execute("INSERT INTO companies (id,name,finance_tenant_id,source_system,status,created_at,updated_at) VALUES (:id,:name,:finance_tenant_id,:source_system,:status,:created_at,:updated_at)", self.company)
        self.store = {"users": {user["id"]: copy.deepcopy(user) for user in (self.user, self.other)}, "companies": {self.company["id"]: copy.deepcopy(self.company)}, "documents": {}, "inbound_documents": {}, "notifications": {}, "notification_deliveries": {}, "system_inbox": {}, "audit_logs": {}}
        self.start(mock.patch.object(backend, "now", return_value="2026-10-08 12:00:00"))
        self.start(mock.patch.object(backend, "_urlopen_no_redirect", side_effect=AssertionError("live_network_forbidden")))
        self.email = self.start(mock.patch.object(backend, "send_email_notification", side_effect=AssertionError("external_email_forbidden")))
        self.line = self.start(mock.patch.object(backend, "send_line_notification", side_effect=AssertionError("external_line_forbidden")))
        self.start(mock.patch.object(backend, "notification_credential_status_for_channel", return_value={"status": "有效"}))
        self.start(mock.patch.object(backend, "supabase_notification_credential_status", return_value={"status": "有效"}))

    def start(self, patch):
        value = patch.start()
        self.addCleanup(patch.stop)
        return value

    def inbound(self, doc_id="INB-TEST", **changes):
        row = {"id": doc_id, "company_id": self.company["id"], "finance_tenant_id": "TEST-TENANT", "receive_no": "TEST-" + doc_id, "source_type": "manual", "sender_name": "測試單位", "subject": "去識別收文", "assignee_user_id": self.user["id"], "assignee_name": self.user["name"], "due_at": "2026-10-07", "status": "assigned", "created_by": self.other["id"], "created_at": "2026-10-01", "updated_at": "2026-10-01", **changes}
        keys = list(row)
        self.conn.execute(f"INSERT INTO inbound_documents ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})", tuple(row.values()))
        self.store["inbound_documents"][doc_id] = copy.deepcopy(row)
        return row

    def legacy(self, metadata=None, **changes):
        row = {"id": "LEGACY-TEST", "doc_no": "TEST-001", "direction": "收文", "agency_name": "測試單位", "subject": "去識別舊公文", "metadata_json": json.dumps(metadata or {}), "owner": self.user["name"], "department": self.user["unit"], "due_date": "2026-10-07", "status": "待辦", "created_at": "2026-10-01", "updated_at": "2026-10-01", **changes}
        keys = list(row)
        self.conn.execute(f"INSERT INTO documents ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})", tuple(row.values()))
        self.store["documents"][row["id"]] = copy.deepcopy(row)
        return row

    def supabase_fixture(self):
        def get(table, row_id):
            return copy.deepcopy(self.store.get(table, {}).get(row_id))
        def insert(table, payload):
            rows = self.store.setdefault(table, {})
            if payload["id"] in rows:
                raise RuntimeError("duplicate_id")
            rows[payload["id"]] = copy.deepcopy(payload)
            return copy.deepcopy(payload)
        def patch(table, row_id, payload):
            self.assertNotEqual(table, "notification_deliveries")
            self.store[table][row_id].update(payload)
            return copy.deepcopy(self.store[table][row_id])
        def rows(table, filters=None, **kwargs):
            return [copy.deepcopy(row) for row in self.store.get(table, {}).values() if all(row.get(key) == value for key, value in (filters or {}).items())]
        self.start(mock.patch.object(backend, "supabase_get", side_effect=get))
        self.start(mock.patch.object(backend, "supabase_insert", side_effect=insert))
        self.start(mock.patch.object(backend, "supabase_patch", side_effect=patch))
        self.start(mock.patch.object(backend, "supabase_filter_rows", side_effect=rows))
        self.start(mock.patch.object(backend, "supabase_list", side_effect=lambda table, *args: rows(table)))

    def run_job(self, remote=False):
        result = backend.supabase_execute_job_logic({"job_type": "overdueReminder"}) if remote else backend.execute_job_logic(self.conn, {"job_type": "overdueReminder"})
        self.email.assert_not_called()
        self.line.assert_not_called()
        self.assertEqual(result["payload"]["externalAttempted"], 0)
        return result

    def test_sqlite_reminder_is_exact_durable_and_daily_deduplicated(self):
        self.inbound()
        first = self.run_job()
        second = self.run_job()
        self.assertEqual(first["payload"]["created"], 1)
        self.assertEqual(first["payload"]["reminded"], 1)
        self.assertEqual(second["payload"]["created"], 0)
        self.assertEqual(second["payload"]["deduplicated"], 1)
        self.conn.commit()
        notice = dict(self.conn.execute("SELECT * FROM notifications").fetchone())
        inbox = dict(self.conn.execute("SELECT * FROM system_inbox").fetchone())
        self.assertEqual(notice["target_user_id"], self.user["id"])
        self.assertEqual(notice["target_company_id"], self.company["id"])
        self.assertEqual(inbox["target_user_id"], self.user["id"])
        self.assertNotIn("去識別收文", inbox["title"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM notification_deliveries").fetchone()[0], 2)
        with mock.patch.object(backend, "now", return_value="2026-10-09 12:00:00"):
            self.assertEqual(self.run_job()["payload"]["created"], 1)

    def test_supabase_reminder_persists_exact_private_inbox_and_deduplicates(self):
        self.inbound()
        self.supabase_fixture()
        self.assertEqual(self.run_job(True)["payload"]["created"], 1)
        self.assertEqual(self.run_job(True)["payload"]["deduplicated"], 1)
        self.assertEqual(len(self.store["notifications"]), 1)
        self.assertEqual(len(self.store["system_inbox"]), 1)
        self.assertEqual(next(iter(self.store["system_inbox"].values()))["target_user_id"], self.user["id"])

    def test_names_only_legacy_owner_is_blocked_without_fallback(self):
        self.legacy()
        for remote in (False, True):
            if remote:
                self.supabase_fixture()
            result = self.run_job(remote)
            self.assertEqual(result["status"], "待處理")
            self.assertEqual(result["payload"]["reminded"], 0)
            self.assertEqual(result["payload"]["errors"][0]["code"], "overdue_reminder_exact_assignee_required")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0], 0)
        self.assertFalse(self.store["notifications"])

    def test_legacy_unique_metadata_must_also_pass_current_document_acl(self):
        row = self.legacy({"assignee_user_id": self.user["id"], "company_id": self.company["id"]})
        self.assertEqual(self.run_job()["payload"]["reminded"], 1)
        self.conn.execute("UPDATE documents SET owner='無關人',department='無關單位' WHERE id=?", (row["id"],))
        self.assertEqual(self.run_job()["payload"]["errors"][0]["code"], "overdue_reminder_scope_forbidden")

    def test_supabase_legacy_scope_is_unverifiable_not_claimed_reminded(self):
        self.legacy({"assignee_user_id": self.user["id"], "company_id": self.company["id"]})
        self.supabase_fixture()
        result = self.run_job(True)
        self.assertEqual(result["payload"]["errors"][0]["code"], "overdue_reminder_legacy_scope_unverifiable")
        self.assertFalse(self.store["notifications"])

    def test_departed_company_changed_tenant_changed_or_unassigned_are_blocked(self):
        self.inbound()
        for field, value in (("status", "停用"), ("company_id", "OTHER-COMPANY"), ("finance_tenant_id", "OTHER-TENANT")):
            with self.subTest(field=field):
                self.conn.execute(f"UPDATE users SET {field}=? WHERE id=?", (value, self.user["id"]))
                result = self.run_job()
                self.assertEqual(result["payload"]["reminded"], 0)
                self.assertEqual(result["payload"]["blocked"], 1)
                self.conn.execute(f"UPDATE users SET {field}=? WHERE id=?", (self.user[field], self.user["id"]))
        self.conn.execute("UPDATE inbound_documents SET assignee_user_id=NULL")
        self.assertEqual(self.run_job()["payload"]["errors"][0]["code"], "overdue_reminder_exact_assignee_required")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0], 0)

    def test_remote_departure_and_company_tenant_invalid_are_blocked(self):
        self.inbound()
        self.supabase_fixture()
        for patch in ({"status": "停用"}, {"company_id": "OTHER"}, {"finance_tenant_id": "OTHER"}):
            self.store["users"][self.user["id"]] = {**self.user, **patch}
            self.assertEqual(self.run_job(True)["payload"]["reminded"], 0)
        self.store["users"][self.user["id"]] = dict(self.user)
        self.store["companies"][self.company["id"]]["status"] = "inactive"
        self.assertEqual(self.run_job(True)["payload"]["reminded"], 0)
        self.assertFalse(self.store["system_inbox"])

    def test_closed_future_today_and_invalid_deadlines_never_false_remind(self):
        for index, changes in enumerate(({"status": "closed"}, {"status": "已結案"}, {"closed_at": "2026-10-07"}, {"due_at": "2026-10-09"}, {"due_at": "2026-10-08"}, {"due_at": "2026-10-08 13:00:00"})):
            self.inbound(f"INB-SKIP-{index}", **changes)
        self.inbound("INB-INVALID", due_at="not-a-date")
        result = self.run_job()
        self.assertEqual(result["payload"]["reminded"], 0)
        self.assertEqual(result["payload"]["blocked"], 1)
        self.assertEqual(result["payload"]["errors"][0]["code"], "case_due_at_invalid")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0], 0)

    def test_same_day_datetime_deadline_reminds_after_expiry(self):
        self.inbound(due_at="2026-10-08 11:59:59")
        self.assertEqual(self.run_job()["payload"]["reminded"], 1)

    def test_queued_old_assignee_is_immutable_and_cannot_be_delivered_after_reassign(self):
        row = self.inbound()
        self.run_job()
        original = dict(self.conn.execute("SELECT * FROM notifications").fetchone())
        self.conn.execute("UPDATE inbound_documents SET assignee_user_id=? WHERE id=?", (self.other["id"], row["id"]))
        denied = backend.deliver_notification(self.conn, original["id"])
        self.assertEqual(denied["error"], "overdue_reminder_relationship_changed")
        self.assertEqual(self.conn.execute("SELECT target_user_id FROM notifications WHERE id=?", (original["id"],)).fetchone()[0], self.user["id"])
        self.assertEqual(self.run_job()["payload"]["created"], 1)
        self.assertEqual({row[0] for row in self.conn.execute("SELECT target_user_id FROM notifications")}, {self.user["id"], self.other["id"]})

    def test_reassignment_during_credential_lookup_cannot_reach_inbox(self):
        row = self.inbound()
        def credential(*args):
            self.conn.execute("UPDATE inbound_documents SET assignee_user_id=? WHERE id=?", (self.other["id"], row["id"]))
            return {"status": "有效"}
        with mock.patch.object(backend, "notification_credential_status_for_channel", side_effect=credential):
            result = self.run_job()
        self.assertEqual(result["payload"]["reminded"], 0)
        self.assertEqual(result["payload"]["errors"][0]["code"], "overdue_reminder_relationship_changed")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM system_inbox").fetchone()[0], 0)

    def test_closed_or_changed_deadline_blocks_old_pending_notice(self):
        row = self.inbound()
        self.run_job()
        notice = dict(self.conn.execute("SELECT * FROM notifications").fetchone())
        for statement in ("status='closed'", "status='assigned',due_at='2026-10-09'", "due_at='2026-10-06'"):
            self.conn.execute(f"UPDATE inbound_documents SET {statement} WHERE id=?", (row["id"],))
            self.assertEqual(backend.deliver_notification(self.conn, notice["id"])["error"], "overdue_reminder_case_no_longer_due")

    def test_persisted_notice_without_confirmed_inbox_is_not_counted_reminded(self):
        self.inbound()
        with mock.patch.object(backend, "push_system_notification", side_effect=RuntimeError("test-storage-failed")):
            result = self.run_job()
        self.assertEqual(result["payload"]["reminded"], 0)
        self.assertEqual(result["payload"]["blocked"], 1)
        self.assertIn("阻擋 1", result["message"])
        self.assertEqual(self.run_job()["payload"]["reminded"], 0)  # Unknown previous inbox attempt is not blindly retried.

    def test_remote_duplicate_insert_ack_loss_recovers_exact_binding_not_double_remind(self):
        self.inbound()
        self.supabase_fixture()
        original_insert = backend.supabase_insert
        def lost_ack(table, payload):
            result = original_insert(table, payload)
            if table == "notifications":
                raise RuntimeError("test-lost-ack")
            return result
        with mock.patch.object(backend, "supabase_insert", side_effect=lost_ack):
            self.assertEqual(self.run_job(True)["payload"]["reminded"], 1)
        self.assertEqual(self.run_job(True)["payload"]["deduplicated"], 1)
        self.assertEqual(len(self.store["notifications"]), 1)
        self.assertEqual(len(self.store["system_inbox"]), 1)

    def test_job_wrapper_preserves_blocked_business_status(self):
        self.legacy()
        self.conn.execute("INSERT INTO background_jobs (id,name,job_type,schedule_text,status,last_result,next_run_at,run_count,updated_at) VALUES ('TEST-JOB','test','overdueReminder','每小時','啟用','','2026-10-08',0,'2026-10-08')")
        result = backend.run_background_job(self.conn, "TEST-JOB")
        self.assertEqual(result["status"], "待處理")
        self.assertEqual(json.loads(self.conn.execute("SELECT payload_json FROM job_runs").fetchone()[0])["reminded"], 0)

    def test_remote_queued_relationship_or_deadline_changes_are_guarded(self):
        row = self.inbound()
        self.supabase_fixture()
        self.run_job(True)
        notice = next(iter(self.store["notifications"].values()))
        for changes, expected in (({"assignee_user_id": self.other["id"]}, "overdue_reminder_relationship_changed"), ({"status": "closed"}, "overdue_reminder_case_no_longer_due"), ({"due_at": "2026-10-09"}, "overdue_reminder_case_no_longer_due")):
            with self.subTest(changes=changes):
                self.store["inbound_documents"][row["id"]] = {**row, **changes}
                result = backend.supabase_deliver_notification(notice["id"])
                self.assertEqual(result["error"], expected)
        self.assertEqual(self.store["notifications"][notice["id"]]["target_user_id"], self.user["id"])
        self.assertEqual(len(self.store["system_inbox"]), 1)

    def test_existing_same_id_with_tampered_body_cannot_be_reused_as_reminded(self):
        self.inbound()
        self.supabase_fixture()
        self.run_job(True)
        notice = next(iter(self.store["notifications"].values()))
        self.store["notifications"][notice["id"]]["body"] = "different tampered body"
        result = self.run_job(True)
        self.assertEqual(result["payload"]["reminded"], 0)
        self.assertEqual(result["payload"]["errors"][0]["code"], "notification_identity_conflict")
        self.assertEqual(len(self.store["system_inbox"]), 1)

    def test_truncated_remote_scan_is_explicitly_blocked_not_false_complete(self):
        self.supabase_fixture()
        rows = [{"id": f"CLOSED-{index}", "status": "closed", "due_date": "2026-10-01"} for index in range(500)]
        with mock.patch.object(backend, "supabase_list", side_effect=lambda table, *args: rows if table == "documents" else []):
            result = self.run_job(True)
        self.assertEqual(result["status"], "待處理")
        self.assertEqual(result["payload"]["errors"][0]["code"], "overdue_reminder_scan_incomplete")

    def test_adapter_exception_cannot_echo_arbitrary_secret_as_a_machine_code(self):
        self.inbound()
        with mock.patch.object(backend, "overdue_reminder_identity", side_effect=RuntimeError("private_lowercase_secret")):
            result = self.run_job()
        self.assertEqual(result["payload"]["errors"][0]["code"], "overdue_reminder_processing_failed")
        self.assertNotIn("private_lowercase_secret", json.dumps(result))
        self.assertNotIn("private_lowercase_secret", self.conn.execute("SELECT detail FROM audit_logs").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
