from __future__ import annotations

import copy
import sqlite3
import unittest
from unittest import mock

import backend


class NotificationDeliverySafetyTests(unittest.TestCase):
    """No real recipients, provider requests or production database access."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(backend.SCHEMA)
        self.addCleanup(self.conn.close)
        self.user = {"id": "TEST-EMPLOYEE", "name": "測試員工", "email": "target@example.invalid", "role": "員工", "company_id": "TEST-COMPANY", "status": "啟用"}
        self.conn.execute("INSERT INTO users (id,name,email,role,company_id,status,created_at) VALUES (:id,:name,:email,:role,:company_id,:status,'2026-10-08')", self.user)
        self.notice = backend.create_notification(self.conn, {"id": "NTF-TEST-SAFE", "title": "去識別測試主旨", "body": "去識別測試內容", **backend.exact_notification_target_payload(self.user), "channel": "Email + 系統通知"})
        self.start(mock.patch.object(backend, "_urlopen_no_redirect", side_effect=AssertionError("live_provider_forbidden")))
        self.start(mock.patch.object(backend, "notification_credential_status_for_channel", return_value={"status": "有效"}))
        self.start(mock.patch.object(backend, "supabase_notification_credential_status", return_value={"status": "有效"}))
        self.start(mock.patch.object(backend, "log_audit"))
        self.email = self.start(mock.patch.object(backend, "send_email_notification", return_value={"status": "成功", "receipt": "test-provider-accepted", "error": ""}))
        self.line = self.start(mock.patch.object(backend, "send_line_notification", return_value={"status": "成功", "receipt": "test-line-accepted", "error": ""}))
        self.store = {"notifications": {self.notice["id"]: copy.deepcopy(self.notice)}, "users": {self.user["id"]: copy.deepcopy(self.user)}, "notification_deliveries": {}, "system_inbox": {}, "audit_logs": {}}

    def start(self, patch):
        value = patch.start()
        self.addCleanup(patch.stop)
        return value

    def supabase_fixture(self):
        def get(table, row_id):
            return copy.deepcopy(self.store.get(table, {}).get(row_id))
        def insert(table, payload):
            table_rows = self.store.setdefault(table, {})
            if payload["id"] in table_rows:
                raise RuntimeError("duplicate_id")
            table_rows[payload["id"]] = copy.deepcopy(payload)
            return payload
        def patch(table, row_id, payload):
            self.assertNotEqual(table, "notification_deliveries", "Ledger must be append-only")
            self.store[table][row_id].update(payload)
            return copy.deepcopy(self.store[table][row_id])
        def rows(table, filters=None, **kwargs):
            return [copy.deepcopy(row) for row in self.store.get(table, {}).values() if all(row.get(key) == value for key, value in (filters or {}).items())]
        self.start(mock.patch.object(backend, "supabase_get", side_effect=get))
        self.start(mock.patch.object(backend, "supabase_insert", side_effect=insert))
        self.start(mock.patch.object(backend, "supabase_patch", side_effect=patch))
        self.start(mock.patch.object(backend, "supabase_filter_rows", side_effect=rows))
        self.start(mock.patch.object(backend, "supabase_list", side_effect=lambda table, *args, **kwargs: rows(table)))

    def ledger(self, channel="Email", **changes):
        row = {"id": "TEST-LEGACY-DELIVERY", "notification_id": self.notice["id"], "channel": channel,
               "target": backend.notification_channel_target(self.notice, channel), "status": "失敗", "receipt": "", "error": "Resend HTTP 400", "attempt_count": 1, "created_at": "2026-10-08 00:00:00", **changes}
        self.conn.execute("INSERT INTO notification_deliveries (id,notification_id,channel,target,status,receipt,error,attempt_count,created_at) VALUES (:id,:notification_id,:channel,:target,:status,:receipt,:error,:attempt_count,:created_at)", row)
        self.store["notification_deliveries"][row["id"]] = copy.deepcopy(row)
        return row

    def test_unknown_adapter_missing_receipt_and_http_5xx_never_retry(self):
        for channel, errors in (("Email", ["Resend 未回傳寄送識別碼", "Resend HTTP 500", "Resend HTTP 503 [service_unavailable]", "future_adapter_error"]), ("Line 工作群組", ["HTTP 500", "HTTP 503"])):
            for error in errors:
                with self.subTest(channel=channel, error=error):
                    self.conn.execute("DELETE FROM notification_deliveries")
                    self.conn.execute("UPDATE notifications SET channel=?,delivery_receipt='',sent_at=NULL WHERE id=?", (channel, self.notice["id"]))
                    sender = self.email if channel == "Email" else self.line
                    sender.reset_mock()
                    sender.return_value = {"status": "失敗", "receipt": "", "error": error}
                    backend.deliver_notification(self.conn, self.notice["id"])
                    second = backend.deliver_notification(self.conn, self.notice["id"])
                    self.assertEqual(sender.call_count, 1)
                    self.assertEqual(second["results"][0]["error"], "notification_delivery_evidence_unknown")

    def test_malformed_success_receipt_leaves_unknown_claim_and_cannot_retry(self):
        for receipt in ({"id": "bad"}, ["bad"], "has whitespace", "x" * 257):
            with self.subTest(receipt=receipt):
                self.conn.execute("DELETE FROM notification_deliveries")
                self.conn.execute("UPDATE notifications SET channel='Email',delivery_receipt='',sent_at=NULL WHERE id=?", (self.notice["id"],))
                self.email.reset_mock()
                self.email.return_value = {"status": "成功", "receipt": receipt, "error": ""}
                first = backend.deliver_notification(self.conn, self.notice["id"])
                second = backend.deliver_notification(self.conn, self.notice["id"])
                self.assertEqual(self.email.call_count, 1)
                self.assertEqual(first["results"][0]["error"], "notification_delivery_outcome_unknown")
                self.assertEqual(second["results"][0]["error"], "notification_delivery_evidence_unknown")

    def test_sqlite_business_transaction_never_sends_or_commits_and_rollback_is_safe(self):
        self.conn.isolation_level = ""
        self.conn.execute("UPDATE notifications SET title='uncommitted-business-change' WHERE id=?", (self.notice["id"],))
        first = backend.deliver_notification(self.conn, self.notice["id"])
        self.assertTrue(self.conn.in_transaction)
        self.assertEqual(first["results"][0]["error"], "notification_postcommit_worker_required")
        self.email.assert_not_called()
        self.conn.rollback()
        self.assertEqual(self.conn.execute("SELECT title FROM notifications WHERE id=?", (self.notice["id"],)).fetchone()[0], self.notice["title"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM system_inbox").fetchone()[0], 0)
        backend.deliver_notification(self.conn, self.notice["id"])
        self.email.assert_not_called()  # A default connection still cannot durably reserve external work.
        self.conn.rollback()
        self.conn.isolation_level = None
        backend.deliver_notification(self.conn, self.notice["id"])
        backend.deliver_notification(self.conn, self.notice["id"])
        self.email.assert_called_once()  # Explicit post-commit autocommit worker owns the claim.

    def test_sqlite_autocommit_explicit_transaction_also_blocks_external_send(self):
        self.conn.execute("BEGIN")
        result = backend.deliver_notification(self.conn, self.notice["id"])
        self.assertEqual(result["results"][0]["error"], "notification_postcommit_worker_required")
        self.assertTrue(self.conn.in_transaction)
        self.email.assert_not_called()
        self.conn.rollback()

    def test_legacy_role_only_and_ambiguous_email_cannot_create_a_notification(self):
        with self.assertRaisesRegex(ValueError, "notification_exact_target_required"):
            backend.create_notification(self.conn, {"target_role": "員工"})
        created = backend.create_notification(self.conn, {"target_role": "wrong-role", "target_email": self.user["email"]})
        self.assertEqual(created["target_user_id"], self.user["id"])
        self.conn.execute("INSERT INTO users (id,name,email,role,company_id,status,created_at) VALUES ('DUPLICATE','不同人',?,'員工','OTHER','啟用','2026-10-08')", (self.user["email"].upper(),))
        with self.assertRaisesRegex(ValueError, "notification_exact_target_required"):
            backend.create_notification(self.conn, {"target_email": self.user["email"]})

    def test_supabase_explicit_invalid_id_never_falls_back_to_email(self):
        self.supabase_fixture()
        with mock.patch.object(backend, "supabase_notification_target_user_id") as resolve:
            with self.assertRaisesRegex(ValueError, "notification_exact_target_required"):
                backend.supabase_create_notification({"target_user_id": "GONE", "target_email": self.user["email"]})
            resolve.assert_not_called()

    def test_resend_2xx_requires_real_well_formed_provider_id_not_request_header(self):
        for body in (b"{}", b"[]", b"not-json", b'{"id":123}', b'{"id":{"value":"bad"}}', b'{"id":"has space"}'):
            with self.subTest(body=body), mock.patch.dict(backend.os.environ, {"RESEND_API_KEY": "test-only", "MAIL_FROM": "notify@example.invalid"}):
                response = mock.MagicMock()
                response.read.return_value = body
                response.headers = {"X-Request-Id": "not-email-provider-acceptance"}
                response.__enter__.return_value = response
                with mock.patch.object(backend, "_urlopen_no_redirect", return_value=response):
                    result = backend.send_resend_email_notification(self.user["email"], "test", "test", "TEST-ID")
                self.assertEqual(result["status"], "失敗")
                self.assertEqual(result["receipt"], "")
                self.assertFalse(backend.notification_failure_definitely_unsent("Email", result["status"], result["error"]))

    def test_existing_notification_id_is_immutable_not_retargeted_or_reused_for_new_body(self):
        payload = {**self.notice, "target_user_id": self.user["id"], "target_company_id": self.user["company_id"]}
        self.assertEqual(backend.create_notification(self.conn, payload)["id"], self.notice["id"])
        with self.assertRaisesRegex(ValueError, "notification_identity_conflict"):
            backend.create_notification(self.conn, {**payload, "body": "different content"})
        self.supabase_fixture()
        with self.assertRaisesRegex(ValueError, "notification_identity_conflict"):
            backend.supabase_create_notification({**payload, "body": "different content"})
        self.assertEqual(self.store["notifications"][self.notice["id"]]["body"], self.notice["body"])

    def test_fixed_initial_supabase_lost_outcome_never_resends(self):
        self.supabase_fixture()
        notice = {**self.notice, "id": "NTF-MONTEST-ISOLATED", "channel": "Email"}
        self.store["notifications"][notice["id"]] = notice
        with mock.patch.object(backend, "supabase_record_notification_delivery", side_effect=RuntimeError("test-lost-outcome")):
            first = backend.supabase_deliver_notification(notice["id"])
        second = backend.supabase_deliver_notification(notice["id"])
        self.email.assert_called_once()
        self.assertEqual(first["results"][0]["error"], "notification_delivery_outcome_unknown")
        self.assertFalse(second.get("attempted"))
        self.assertTrue(any(key.startswith("NDEL-MONINITIAL-") for key in self.store["notification_deliveries"]))
        self.assertEqual(backend.unresolved_notification_failure_count(list(self.store["notification_deliveries"].values())), 1)

    def test_fixed_initial_sqlite_lost_outcome_has_durable_guard(self):
        notice = backend.create_notification(self.conn, {**self.notice, "id": "NTF-MONTEST-ISOLATED", "channel": "Email"})
        with mock.patch.object(backend, "record_notification_delivery", side_effect=RuntimeError("test-lost-outcome")):
            backend.deliver_notification(self.conn, notice["id"])
        self.conn.rollback()
        backend.deliver_notification(self.conn, notice["id"])
        self.email.assert_called_once()
        self.assertFalse(self.conn.in_transaction)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM notification_deliveries WHERE id LIKE 'NDEL-MONINITIAL-%'").fetchone()[0], 1)
        self.assertEqual(backend.unresolved_notification_failure_count([dict(row) for row in self.conn.execute("SELECT * FROM notification_deliveries")]), 1)

    def test_fixed_initial_monitoring_guard_resolves_only_verified_exact_outcome(self):
        notice_id = "NTF-MONTEST-PENDING"
        guard = {"id": "NDEL-MONINITIAL-" + backend.stable_json_hash({"notificationId": notice_id, "channel": "Email"})[:40], "notification_id": notice_id, "channel": "Email 保留", "target": self.user["email"], "status": "已保留", "attempt_count": 0, "created_at": "2026-10-08 12:00:00"}
        accepted = {"id": "INITIAL-OUTCOME", "notification_id": notice_id, "channel": "Email", "target": self.user["email"], "status": "成功", "receipt": "provider-accepted", "error": "", "attempt_count": 1, "created_at": "2026-10-08 12:00:00"}
        self.assertEqual(backend.unresolved_notification_failure_count([guard]), 1)
        self.assertEqual(backend.unresolved_notification_failure_count([guard, accepted]), 0)
        rejected = {**accepted, "status": "失敗", "receipt": "", "error": "Resend HTTP 400"}
        self.assertEqual(backend.unresolved_notification_failure_count([guard, rejected]), 1)  # Existing failed Email, no double count.
        for patch in ({"target": "other@example.invalid"}, {"receipt": ""}, {"receipt": {"bad": True}}, {"created_at": "2026-10-08 11:59:59"}, {"notification_id": "OTHER"}):
            with self.subTest(patch=patch):
                self.assertEqual(backend.unresolved_notification_failure_count([guard, {**accepted, **patch}]), 1)
        unknown = {**accepted, "status": "失敗", "receipt": "", "error": "notification_delivery_outcome_unknown"}
        self.assertEqual(backend.unresolved_notification_failure_count([guard, unknown]), 1)

    def test_local_postcommit_worker_can_send_after_blocked_business_notice_commits(self):
        self.conn.isolation_level = ""
        first = backend.deliver_notification(self.conn, self.notice["id"])
        self.assertEqual(first["results"][0]["error"], "notification_postcommit_worker_required")
        self.email.assert_not_called()
        self.conn.commit()
        self.conn.isolation_level = None
        second = backend.deliver_notification(self.conn, self.notice["id"])
        self.email.assert_called_once()
        self.assertEqual(second["success"], 2)

    def test_supabase_email_lookup_requires_one_case_insensitive_exact_account(self):
        for rows, expected in (([{"id": self.user["id"], "email": self.user["email"].upper()}], self.user["id"]), ([{"id": "ONE", "email": self.user["email"]}, {"id": "TWO", "email": self.user["email"].upper()}], ""), ([{"id": "WRONG", "email": "someone@example.invalid"}], "")):
            with self.subTest(rows=rows), mock.patch.object(backend, "supabase_request", return_value=rows) as request:
                self.assertEqual(backend.supabase_notification_target_user_id("irrelevant-role", self.user["email"]), expected)
                self.assertIn("limit=2", request.call_args.args[1])

    def test_target_guard_rejects_departure_company_email_missing_or_legacy_role(self):
        for field, value, expected in (("status", "停用", "notification_target_inactive"), ("company_id", "OTHER-COMPANY", "notification_target_company_changed"), ("email", "changed@example.invalid", "notification_target_identity_changed")):
            with self.subTest(field=field):
                self.conn.execute(f"UPDATE users SET {field}=? WHERE id=?", (value, self.user["id"]))
                result = backend.deliver_notification(self.conn, self.notice["id"])
                self.assertEqual(result["error"], expected)
                self.conn.execute(f"UPDATE users SET {field}=? WHERE id=?", (self.user[field], self.user["id"]))
        self.conn.execute("DELETE FROM users WHERE id=?", (self.user["id"],))
        self.assertEqual(backend.deliver_notification(self.conn, self.notice["id"])["error"], "notification_target_inactive")
        self.assertEqual(backend.notification_delivery_target_error({**self.notice, "target_user_id": ""}, self.user), "notification_exact_target_required")
        self.email.assert_not_called()
        self.line.assert_not_called()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM system_inbox").fetchone()[0], 0)

    def test_supabase_rechecks_exact_identity_before_any_provider_or_inbox(self):
        self.supabase_fixture()
        for patch, expected in (({"status": "停用"}, "notification_target_inactive"), ({"company_id": "OTHER-COMPANY"}, "notification_target_company_changed"), ({"email": "changed@example.invalid"}, "notification_target_identity_changed")):
            with self.subTest(patch=patch):
                self.store["users"][self.user["id"]] = {**self.user, **patch}
                result = backend.supabase_deliver_notification(self.notice["id"])
                self.assertEqual(result["error"], expected)
        self.email.assert_not_called()
        self.assertFalse(self.store["system_inbox"])
        self.assertFalse(self.store["notification_deliveries"])

    def test_duplicate_local_call_reuses_accepted_channels_and_does_not_mark_human_receipt(self):
        first = backend.deliver_notification(self.conn, self.notice["id"])
        second = backend.deliver_notification(self.conn, self.notice["id"])
        self.email.assert_called_once()
        self.assertEqual(first["attempted"], 2)
        self.assertEqual(second["attempted"], 0)
        self.assertTrue(all(row["reused"] for row in second["results"]))
        self.assertEqual(second["status"], "已派送")
        self.assertFalse(second["humanReceiptConfirmed"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM system_inbox").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT SUM(attempt_count) FROM notification_deliveries").fetchone()[0], 2)

    def test_duplicate_supabase_call_does_not_repeat_email_or_inbox(self):
        self.supabase_fixture()
        first = backend.supabase_deliver_notification(self.notice["id"])
        second = backend.supabase_deliver_notification(self.notice["id"])
        self.email.assert_called_once()
        self.assertEqual(first["attempted"], 2)
        self.assertEqual(second["attempted"], 0)
        self.assertEqual(len(self.store["system_inbox"]), 1)
        self.assertEqual(len(self.store["notification_deliveries"]), 4)

    def test_partial_failure_retries_only_failed_channel(self):
        with mock.patch.object(backend, "push_system_notification", side_effect=[{"status": "憑證異常", "receipt": "", "error": "notification_credential_unavailable"}, {"status": "成功", "receipt": "test-inbox-recovered", "error": ""}]) as inbox:
            first = backend.deliver_notification(self.conn, self.notice["id"])
            retry = backend.retry_failed_notifications(self.conn)
        self.email.assert_called_once()
        self.assertEqual(inbox.call_count, 2)
        self.assertEqual(first["status"], "部分派送")
        self.assertEqual(retry["count"], 1)
        self.assertEqual(retry["results"][0]["attempted"], 1)
        self.assertEqual(retry["results"][0]["status"], "已派送")

    def test_repeated_known_failure_stops_after_three_total_channel_attempts(self):
        self.conn.execute("UPDATE notifications SET channel='Email' WHERE id=?", (self.notice["id"],))
        self.email.return_value = {"status": "失敗", "receipt": "", "error": "Resend HTTP 400"}
        for _ in range(3):
            backend.deliver_notification(self.conn, self.notice["id"])
        fourth = backend.deliver_notification(self.conn, self.notice["id"])
        retried = backend.retry_failed_notifications(self.conn)
        self.assertEqual(self.email.call_count, 3)
        self.assertEqual(fourth["results"][0]["error"], "notification_retry_limit_reached")
        self.assertEqual(retried["count"], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM notification_deliveries").fetchone()[0], 6)

    def test_legacy_success_with_receipt_is_not_sent_again(self):
        self.ledger(status="成功", receipt="legacy-provider-accepted", error="")
        result = backend.deliver_notification(self.conn, self.notice["id"])
        self.email.assert_not_called()
        self.assertEqual(result["results"][0]["receipt"], "legacy-provider-accepted")
        self.assertTrue(result["results"][0]["reused"])

    def test_unknown_legacy_receipts_status_and_identity_do_not_authorize_retry(self):
        changes = [{"status": "成功", "receipt": ""}, {"status": "sending"}, {"target": "other@example.invalid"}, {"status": "失敗", "receipt": "unexpected"}, {"attempt_count": -1}, {"error": "Resend 連線失敗"}]
        for patch in changes:
            with self.subTest(patch=patch):
                self.conn.execute("DELETE FROM notification_deliveries")
                self.ledger(**patch)
                result = backend.deliver_notification(self.conn, self.notice["id"], "Email")
                self.assertEqual(result["results"][0]["error"], "notification_delivery_evidence_unknown")
        self.email.assert_not_called()

    def test_summary_without_channel_ledger_is_unknown_not_permission_to_resend(self):
        self.conn.execute("UPDATE notifications SET delivery_receipt='legacy accepted',sent_at='2026-10-07 12:00:00' WHERE id=?", (self.notice["id"],))
        result = backend.deliver_notification(self.conn, self.notice["id"])
        self.assertEqual(result["attempted"], 0)
        self.email.assert_not_called()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM system_inbox").fetchone()[0], 0)

    def test_claimed_transport_exception_is_not_automatically_retried(self):
        self.email.side_effect = RuntimeError("test-lost-response-with-private-text")
        first = backend.deliver_notification(self.conn, self.notice["id"])
        second = backend.deliver_notification(self.conn, self.notice["id"])
        self.email.assert_called_once()
        self.assertEqual(first["results"][0]["error"], "notification_delivery_outcome_unknown")
        self.assertEqual(second["attempted"], 0)
        self.assertEqual(second["results"][0]["error"], "notification_delivery_evidence_unknown")
        self.assertNotIn("private-text", str(first))

    def test_stale_supabase_reads_and_duplicate_claim_cannot_double_send(self):
        self.supabase_fixture()
        self.store["notifications"][self.notice["id"]]["channel"] = "Email"
        original_filter = backend.supabase_filter_rows.side_effect
        with mock.patch.object(backend, "supabase_filter_rows", side_effect=lambda table, filters=None, **kwargs: [] if table == "notification_deliveries" else original_filter(table, filters, **kwargs)):
            first = backend.supabase_deliver_notification(self.notice["id"])
            # Simulate a stale notification summary and stale ledger snapshot.
            self.store["notifications"][self.notice["id"]].update(delivery_receipt="", sent_at=None)
            second = backend.supabase_deliver_notification(self.notice["id"])
        self.email.assert_called_once()
        self.assertEqual(first["attempted"], 1)
        self.assertEqual(second["results"][0]["error"], "notification_delivery_claim_unavailable")
        self.assertEqual(len(self.store["notification_deliveries"]), 2)

    def test_lost_claim_acknowledgement_does_not_send_and_leaves_pending_evidence(self):
        self.supabase_fixture()
        original_insert = backend.supabase_insert.side_effect
        def insert(table, payload):
            result = original_insert(table, payload)
            if table == "notification_deliveries" and payload["id"].startswith(backend.NOTIFICATION_CLAIM_PREFIX):
                raise RuntimeError("test-lost-claim-ack")
            return result
        with mock.patch.object(backend, "supabase_insert", side_effect=insert):
            first = backend.supabase_deliver_notification(self.notice["id"])
        second = backend.supabase_deliver_notification(self.notice["id"])
        self.email.assert_not_called()
        self.assertEqual(first["attempted"], 0)
        self.assertEqual(second["attempted"], 0)
        self.assertTrue(all(row["status"] == "重試中" for row in self.store["notification_deliveries"].values()))

    def test_lost_outcome_acknowledgement_is_read_back_without_resending(self):
        self.supabase_fixture()
        original_insert = backend.supabase_insert.side_effect
        def insert(table, payload):
            result = original_insert(table, payload)
            if table == "notification_deliveries" and payload["id"].startswith(backend.NOTIFICATION_RESULT_PREFIX):
                raise RuntimeError("test-lost-outcome-ack")
            return result
        with mock.patch.object(backend, "supabase_insert", side_effect=insert):
            first = backend.supabase_deliver_notification(self.notice["id"])
        second = backend.supabase_deliver_notification(self.notice["id"])
        self.email.assert_called_once()
        self.assertEqual(first["status"], "已派送")
        self.assertEqual(second["attempted"], 0)

    def test_missing_outcome_after_provider_acceptance_blocks_resend(self):
        self.supabase_fixture()
        original_insert = backend.supabase_insert.side_effect
        def insert(table, payload):
            if table == "notification_deliveries" and payload["id"].startswith(backend.NOTIFICATION_RESULT_PREFIX):
                raise RuntimeError("test-outcome-store-unavailable")
            return original_insert(table, payload)
        with mock.patch.object(backend, "supabase_insert", side_effect=insert):
            first = backend.supabase_deliver_notification(self.notice["id"])
        second = backend.supabase_deliver_notification(self.notice["id"])
        self.email.assert_called_once()
        self.assertEqual(first["results"][0]["error"], "notification_delivery_outcome_unknown")
        self.assertEqual(second["attempted"], 0)

    def test_same_timestamp_outcome_resolves_claim_for_monitoring(self):
        with mock.patch.object(backend, "now", return_value="2026-10-08 00:00:00"):
            backend.deliver_notification(self.conn, self.notice["id"])
        rows = [dict(row) for row in self.conn.execute("SELECT * FROM notification_deliveries")]
        self.assertEqual(backend.unresolved_notification_failure_count(rows), 0)
        self.assertEqual(backend.unresolved_notification_failure_count(list(reversed(rows))), 0)

    def test_same_second_later_retry_outcome_overrides_earlier_failure(self):
        self.conn.execute("UPDATE notifications SET channel='Email' WHERE id=?", (self.notice["id"],))
        self.email.side_effect = [{"status": "失敗", "receipt": "", "error": "Resend HTTP 400"}, {"status": "成功", "receipt": "test-retry-accepted", "error": ""}]
        with mock.patch.object(backend, "now", return_value="2026-10-08 00:00:00"):
            backend.deliver_notification(self.conn, self.notice["id"])
            backend.deliver_notification(self.conn, self.notice["id"])
        rows = [dict(row) for row in self.conn.execute("SELECT * FROM notification_deliveries")]
        for order in (rows, list(reversed(rows))):
            self.assertEqual(backend.unresolved_notification_failure_count(order), 0)
            self.assertEqual(backend.notification_runtime_readiness(order)["email_validation"], "provider_accepted")

    def test_legacy_failed_channels_count_towards_attempt_limit(self):
        self.conn.execute("UPDATE notifications SET channel='Email' WHERE id=?", (self.notice["id"],))
        for index in range(3):
            self.ledger(id=f"TEST-LEGACY-{index}")
        result = backend.deliver_notification(self.conn, self.notice["id"])
        self.assertEqual(result["results"][0]["error"], "notification_retry_limit_reached")
        self.email.assert_not_called()

    def test_supabase_partial_failure_only_retries_failed_channel_and_honors_cap(self):
        self.supabase_fixture()
        self.email.return_value = {"status": "失敗", "receipt": "", "error": "Resend HTTP 400"}
        backend.supabase_deliver_notification(self.notice["id"])
        for _ in range(4):
            backend.supabase_retry_failed_notifications()
        self.assertEqual(self.email.call_count, 3)
        self.assertEqual(len(self.store["system_inbox"]), 1)
        self.assertEqual(sum(row["attempt_count"] for row in self.store["notification_deliveries"].values()), 4)

    def test_conflicting_outcome_is_never_overwritten_or_authorization_to_send(self):
        self.supabase_fixture()
        claim = backend.notification_delivery_claim(self.notice, "Email", 1)
        backend.insert_notification_delivery_claim(claim)
        result = {"status": "成功", "receipt": "test-provider-accepted", "error": ""}
        row = backend.append_notification_delivery_outcome(claim, result)
        with self.assertRaisesRegex(RuntimeError, "^notification_delivery_outcome_unknown$"):
            backend.append_notification_delivery_outcome(claim, {**result, "receipt": "conflicting-provider-id"})
        self.assertEqual(self.store["notification_deliveries"][row["id"]]["receipt"], "test-provider-accepted")
        self.email.assert_not_called()

    def test_truncated_ledger_unknown_channel_and_invalid_claim_fail_closed(self):
        rows = [{"channel": "Other"}] * 1000
        self.assertEqual(backend.notification_channel_delivery_plan(self.notice, "Email", rows)["error"], "notification_delivery_evidence_unknown")
        self.assertEqual(backend.notification_channel_delivery_plan(self.notice, "Fax", [])["error"], "notification_channel_unsupported")
        claim = backend.notification_delivery_claim(self.notice, "Email", 1)
        for patch in ({"id": "not-a-claim"}, {"notification_id": "OTHER"}, {"status": "成功"}, {"attempt_count": 0}):
            with self.subTest(patch=patch), self.assertRaisesRegex(RuntimeError, "^notification_delivery_claim_invalid$"):
                backend.append_notification_delivery_outcome({**claim, **patch}, {"status": "成功", "receipt": "test-provider-id", "error": ""}, self.conn)

    def test_private_notice_text_is_not_broadcast_to_line_group(self):
        self.conn.execute("UPDATE notifications SET channel='Line 工作群組' WHERE id=?", (self.notice["id"],))
        backend.deliver_notification(self.conn, self.notice["id"])
        self.line.assert_called_once_with("公文系統有待處理通知，請登入系統依權限查看。")
        self.assertNotIn(self.notice["title"], self.line.call_args.args[0])
        self.assertNotIn(self.notice["body"], self.line.call_args.args[0])

    def test_departure_between_channel_calls_prevents_second_channel(self):
        def send(*args):
            self.conn.execute("UPDATE users SET status='停用' WHERE id=?", (self.user["id"],))
            return {"status": "成功", "receipt": "test-provider-accepted", "error": ""}
        self.email.side_effect = send
        result = backend.deliver_notification(self.conn, self.notice["id"])
        self.assertEqual(result["results"][1]["error"], "notification_target_inactive")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM system_inbox").fetchone()[0], 0)

    def test_inbox_receipt_for_a_different_identity_is_not_reused(self):
        self.conn.execute("INSERT INTO system_inbox (id,notification_id,target_role,target_user_id,title,body,status,created_at) VALUES ('TEST-INBOX',?,'員工','OTHER-USER','test','test','未讀','2026-10-08')", (self.notice["id"],))
        with self.assertRaisesRegex(RuntimeError, "^notification_inbox_target_mismatch$"):
            backend.push_system_notification(self.conn, self.notice)
        self.supabase_fixture()
        self.store["system_inbox"]["TEST-INBOX"] = {"id": "TEST-INBOX", "notification_id": self.notice["id"], "target_user_id": "OTHER-USER"}
        with self.assertRaisesRegex(RuntimeError, "^notification_inbox_target_mismatch$"):
            backend.supabase_push_system_notification(self.notice)
        self.assertEqual(len(self.store["system_inbox"]), 1)

    def test_channel_claims_and_outcomes_do_not_mutate_prior_ledger(self):
        self.conn.executescript("CREATE TRIGGER no_notification_delivery_update BEFORE UPDATE ON notification_deliveries BEGIN SELECT RAISE(ABORT,'immutable'); END; CREATE TRIGGER no_notification_delivery_delete BEFORE DELETE ON notification_deliveries BEGIN SELECT RAISE(ABORT,'immutable'); END;")
        first = backend.deliver_notification(self.conn, self.notice["id"])
        rows_before = [dict(row) for row in self.conn.execute("SELECT * FROM notification_deliveries ORDER BY id")]
        second = backend.deliver_notification(self.conn, self.notice["id"])
        self.assertEqual(first["status"], "已派送")
        self.assertEqual(second["attempted"], 0)
        self.assertEqual([dict(row) for row in self.conn.execute("SELECT * FROM notification_deliveries ORDER BY id")], rows_before)

    def test_departure_during_credential_lookup_is_checked_before_provider_call(self):
        def credential(conn, channel):
            self.conn.execute("UPDATE users SET status='停用' WHERE id=?", (self.user["id"],))
            return {"status": "有效"}
        with mock.patch.object(backend, "notification_credential_status_for_channel", side_effect=credential):
            result = backend.deliver_notification(self.conn, self.notice["id"])
        self.email.assert_not_called()
        self.assertEqual(result["results"][0]["error"], "notification_target_inactive")

    def test_summary_write_failure_does_not_lose_receipts_or_repeat_provider_calls(self):
        self.supabase_fixture()
        with mock.patch.object(backend, "supabase_patch", side_effect=RuntimeError("test-summary-write-unavailable")):
            with self.assertRaisesRegex(RuntimeError, "test-summary-write-unavailable"):
                backend.supabase_deliver_notification(self.notice["id"])
        second = backend.supabase_deliver_notification(self.notice["id"])
        self.email.assert_called_once()
        self.assertEqual(second["status"], "已派送")
        self.assertEqual(second["attempted"], 0)
        self.assertEqual(len(self.store["system_inbox"]), 1)


if __name__ == "__main__":
    unittest.main()
