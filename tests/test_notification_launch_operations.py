from __future__ import annotations

import json
import io
import os
from pathlib import Path
import sqlite3
import unittest
import urllib.error
from unittest import mock
from urllib.parse import parse_qs, urlparse

import backend


class NotificationLaunchOperationsTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(backend.SCHEMA)
        self.addCleanup(self.conn.close)
        self.env = mock.patch.dict(os.environ, {"RESEND_API_KEY": "test-only-key", "RESEND_FROM": "notify@example.test", "APP_SECRET": "test-only-signing"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def user(self, user_id="OPS-1", **overrides):
        return {"id": user_id, "name": "測試人員", "email": f"{user_id.lower()}@example.test", "role": "行政部主任", "company_id": "CO-1", "account_source": "finance", "logging_role_key": "admin_director", "status": "啟用", **overrides}

    def snapshot(self):
        return {"status": "critical", "alerts": [{"code": "CRON-STALLED", "message": "private employee text secret"}], "checkedAt": "2026-09-07", "deployment": {"secret": "do-not-send"}}

    def test_resend_alias_sender_and_old_smtp_expiry_do_not_block_delivery(self):
        credential = {"channel": "Email", "env_key_name": "SMTP_HOST,SMTP_FROM", "expires_at": "2000-01-01"}
        self.assertEqual(backend.notification_email_required_env(), ["RESEND_API_KEY", "RESEND_FROM"])
        result = backend.supabase_notification_credential_status("Email", [credential])
        self.assertEqual(result["status"], "有效")
        self.assertEqual(result["expires_at"], "")

    def test_current_provider_expiry_is_still_enforced(self):
        credential = {"channel": "Email", "env_key_name": "RESEND_API_KEY,MAIL_FROM", "expires_at": "2000-01-01"}
        self.assertEqual(backend.supabase_notification_credential_status("Email", [credential])["status"], "已到期")
        with mock.patch.dict(os.environ, {"RESEND_CREDENTIAL_EXPIRES_AT": "2000-01-01"}):
            self.assertEqual(backend.supabase_notification_credential_status("Email", [])["status"], "已到期")

    def test_local_and_supabase_runtime_credentials_agree_without_seed_rows(self):
        self.assertEqual(backend.notification_credential_status_for_channel(self.conn, "Email")["status"], "有效")
        self.assertEqual(backend.supabase_notification_credential_status("Email", [])["status"], "有效")

    def test_runtime_readiness_does_not_claim_human_delivery(self):
        readiness = backend.notification_runtime_readiness()
        self.assertEqual(readiness["external"]["email"], "configured")
        self.assertEqual(readiness["email_validation"], "pending_delivery_test")
        accepted = backend.notification_runtime_readiness([{"notification_id": "N-1", "channel": "Email", "status": "成功", "receipt": "provider-id", "created_at": "2026-09-07"}])
        self.assertEqual(accepted["email_validation"], "provider_accepted")
        self.assertFalse(accepted["human_receipt_confirmed"])
        self.assertNotIn("provider-id", json.dumps(accepted))

    def test_latest_failed_attempt_overrides_historical_success_without_losing_history(self):
        rows = [{"notification_id": "OLD", "channel": "Email", "status": "成功", "receipt": "accepted", "created_at": "2026-09-06"}, {"notification_id": "LATEST", "channel": "Email", "status": "失敗", "error": "Resend HTTP 400", "created_at": "2026-09-07"}]
        readiness = backend.notification_runtime_readiness(rows)
        self.assertEqual(readiness["email_validation"], "delivery_failed")
        self.assertEqual(readiness["last_accepted_notification_id"], "OLD")
        self.assertEqual(readiness["lastAttemptStatus"], "失敗")
        self.assertEqual(readiness["safeErrorCode"], "Resend HTTP 400")
        rows[-1]["error"] = "private recipient@example.test key-re-secret"
        self.assertEqual(backend.notification_runtime_readiness(rows)["safeErrorCode"], "email_delivery_failed")

    def test_sender_diagnostics_are_only_booleans_and_never_reveal_configuration(self):
        for value in ('"notify@example.test"', 'notify@example.test\\n', 'notify@example.test\nother@example.test', 'Name ＜notify@example.test＞', 'one@example.test,two@example.test'):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"MAIL_FROM": value}):
                result = backend.notification_email_format_diagnostics()
                self.assertFalse(result["senderFormatValid"])
                self.assertTrue(all(isinstance(item, bool) for item in result.values()))
                self.assertNotIn("@", json.dumps(result))
        with mock.patch.dict(os.environ, {"MAIL_FROM": "通知系統 <notify@example.test>", "RESEND_API_KEY": "re_" + "a" * 32}):
            result = backend.notification_email_format_diagnostics()
            self.assertTrue(result["senderFormatValid"])
            self.assertTrue(result["resendKeyFormatValid"])

    def test_resend_error_classifies_only_allowlisted_name_and_field(self):
        body = json.dumps({"name": "validation_error", "message": "Invalid `from` field: private@example.test re_secret"}).encode()
        error = urllib.error.HTTPError("https://example.test", 400, "Bad Request", {}, io.BytesIO(body))
        safe = backend.resend_safe_http_error(error)
        self.assertEqual(safe, "Resend HTTP 400 [validation_error:from]")
        self.assertNotIn("private", safe)
        self.assertNotIn("re_secret", safe)
        for body in (b'{"name":"recipient@example.test","message":"secret"}', b'not-json'):
            error = urllib.error.HTTPError("https://example.test", 400, "Bad", {}, io.BytesIO(body))
            self.assertEqual(backend.resend_safe_http_error(error), "Resend HTTP 400")

    def test_fixed_test_retry_only_sends_email_once_with_original_payload(self):
        user = self.user()
        self.conn.execute("INSERT INTO users (id,name,email,role,status,company_id,account_source,logging_role_key,created_at) VALUES (:id,:name,:email,:role,:status,:company_id,:account_source,:logging_role_key,'2026-09-07')", user)
        with mock.patch.object(backend, "send_email_notification", return_value={"status": "失敗", "receipt": "", "error": "Resend HTTP 400"}):
            first = backend.execute_monitoring_mode("deliveryTest", self.conn)
        notice_id = first["delivery"]["notificationIds"][0]
        notice = dict(self.conn.execute("SELECT * FROM notifications WHERE id=?", (notice_id,)).fetchone())
        self.conn.executescript("""
            CREATE TRIGGER reject_delivery_update BEFORE UPDATE ON notification_deliveries
            BEGIN SELECT RAISE(ABORT, 'append_only'); END;
            CREATE TRIGGER reject_delivery_delete BEFORE DELETE ON notification_deliveries
            BEGIN SELECT RAISE(ABORT, 'append_only'); END;
        """)
        with mock.patch.object(backend, "send_resend_email_notification", return_value={"status": "失敗", "receipt": "", "error": "Resend HTTP 400 [validation_error:from]"}) as send, mock.patch.object(backend, "push_system_notification") as inbox:
            retry = backend.execute_monitoring_mode("deliveryTestRetry", self.conn)
            third = backend.execute_monitoring_mode("deliveryTestRetry", self.conn)
        send.assert_called_once_with(notice["target_email"], notice["title"], notice["body"], notice_id)
        inbox.assert_not_called()
        self.assertEqual(retry["attempted"], 1)
        self.assertEqual(third["attempted"], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM system_inbox").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM notification_deliveries WHERE channel='Email'").fetchone()[0], 3)
        self.assertEqual(self.conn.execute("SELECT SUM(attempt_count) FROM notification_deliveries WHERE channel='Email'").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT status FROM notification_deliveries WHERE id LIKE 'NDEL-MONRETRY-%'").fetchone()[0], "重試中")
        self.assertEqual(self.conn.execute("SELECT status,attempt_count FROM notification_deliveries WHERE id LIKE 'NDEL-MONRESULT-%'").fetchone()[:], ("失敗", 0))
        with mock.patch.object(backend, "send_email_notification") as generic_send:
            self.assertEqual(backend.deliver_notification(self.conn, notice_id)["error"], "fixed_test_retry_only")
            self.assertEqual(backend.retry_failed_notifications(self.conn)["count"], 0)
        generic_send.assert_not_called()

    def test_retry_eligibility_rejects_other_dates_payloads_statuses_or_attempt_counts(self):
        expected = backend.monitoring_alert_notification_payload({"deliveryTest": True}, self.user())
        notice = {**expected, "created_at": backend.now()}
        attempts = [{"status": "失敗", "receipt": "", "error": "Resend HTTP 400", "attempt_count": 1, "target": expected["target_email"]}]
        self.assertTrue(backend.monitoring_test_retry_eligible(notice, attempts, expected))
        for patch in ({"id": "NTF-BUSINESS"}, {"created_at": "2000-01-01"}, {"target_email": "changed@example.test"}, {"title": "changed"}, {"type": "一般通知"}, {"body": "changed"}, {"target_user_id": "someone-else"}):
            self.assertFalse(backend.monitoring_test_retry_eligible({**notice, **patch}, attempts, expected))
        for patch in ({"status": "成功", "receipt": "accepted"}, {"receipt": "receipt"}, {"error": "Resend HTTP 403"}, {"status": "憑證異常"}, {"attempt_count": 2}, {"target": "different@example.test"}):
            self.assertFalse(backend.monitoring_test_retry_eligible(notice, [{**attempts[0], **patch}], expected))
        self.assertFalse(backend.monitoring_test_retry_eligible(None, attempts, expected))
        self.assertFalse(backend.monitoring_test_retry_eligible(notice, [], expected))
        self.assertFalse(backend.monitoring_test_retry_eligible(notice, attempts * 2, expected))

    def test_supabase_retry_atomic_claim_prevents_stale_count_double_send(self):
        user = self.user()
        expected = backend.monitoring_alert_notification_payload({"deliveryTest": True}, user)
        notice = {**expected, "created_at": backend.now()}
        attempts = [{"status": "失敗", "receipt": "", "error": "Resend HTTP 400", "attempt_count": 1, "target": user["email"]}]
        claims = set()
        def insert(table, payload):
            self.assertEqual(table, "notification_deliveries")
            if payload["id"] in claims:
                raise RuntimeError("unique_claim_conflict")
            claims.add(payload["id"])
            return payload
        def query(table, *args, **kwargs):
            return [user] if table == "users" else attempts
        def patch(table, row_id, payload):
            # Mirrors the deployed backend role: deliveries allow INSERT only.
            self.assertEqual(table, "notifications")
        with mock.patch.object(backend, "supabase_filter_rows", side_effect=query), mock.patch.object(backend, "supabase_get", return_value=notice), mock.patch.object(backend, "supabase_insert", side_effect=insert), mock.patch.object(backend, "supabase_patch", side_effect=patch), mock.patch.object(backend, "send_resend_email_notification", return_value={"status": "成功", "receipt": "accepted", "error": ""}) as send:
            first = backend.retry_monitoring_delivery_test()
            second = backend.retry_monitoring_delivery_test()
        send.assert_called_once()
        self.assertEqual(first["attempted"], 1)
        self.assertEqual(second["attempted"], 0)
        self.assertEqual(second["skipped"][0]["reason"], "retry_claim_unavailable")
        self.assertEqual(len(claims), 2)
        self.assertTrue(any(row_id.startswith("NDEL-MONRESULT-") for row_id in claims))

    def retry_claim(self):
        notice_id = backend.monitoring_alert_notification_payload({"deliveryTest": True}, self.user())["id"]
        return {
            "id": "NDEL-MONRETRY-" + backend.stable_json_hash({"notificationId": notice_id})[:32],
            "notification_id": notice_id, "channel": "Email", "target": self.user()["email"],
            "status": "重試中", "receipt": "", "error": "", "attempt_count": 1, "created_at": backend.now(),
        }

    def test_outcome_insert_lost_acknowledgement_and_matching_duplicate_are_safe(self):
        stored = {}
        def insert(table, row):
            self.assertEqual(table, "notification_deliveries")
            stored.setdefault(row["id"], dict(row))
            raise RuntimeError("database response lost")
        with mock.patch.object(backend, "supabase_insert", side_effect=insert), mock.patch.object(backend, "supabase_get", side_effect=lambda table, row_id: stored.get(row_id)), mock.patch.object(backend, "supabase_patch") as patch, mock.patch.object(backend, "send_resend_email_notification") as send:
            first = backend.append_monitoring_retry_outcome(self.retry_claim(), {"status": "成功", "receipt": "accepted", "error": ""})
            second = backend.append_monitoring_retry_outcome(self.retry_claim(), {"status": "成功", "receipt": "accepted", "error": ""})
        self.assertEqual(first, second)
        self.assertEqual(len(stored), 1)
        self.assertEqual(first["attempt_count"], 0)
        patch.assert_not_called()
        send.assert_not_called()

    def test_conflicting_or_unconfirmed_outcome_never_overwrites_existing_audit(self):
        claim = self.retry_claim()
        outcome = {"status": "成功", "receipt": "accepted", "error": ""}
        with mock.patch.object(backend, "supabase_insert"), mock.patch.object(backend, "supabase_patch") as patch:
            stored = backend.append_monitoring_retry_outcome(claim, outcome)
        for existing, message in (({**stored, "receipt": "different"}, "monitoring_retry_outcome_conflict"), (None, "monitoring_retry_outcome_unconfirmed")):
            with self.subTest(message=message), mock.patch.object(backend, "supabase_insert", side_effect=RuntimeError("private database error")), mock.patch.object(backend, "supabase_get", return_value=existing), mock.patch.object(backend, "supabase_patch") as patch, mock.patch.object(backend, "send_resend_email_notification") as send:
                with self.assertRaisesRegex(RuntimeError, "^" + message + "$"):
                    backend.append_monitoring_retry_outcome(claim, outcome)
                patch.assert_not_called()
                send.assert_not_called()
        with mock.patch.object(backend, "supabase_insert", side_effect=RuntimeError("private write")), mock.patch.object(backend, "supabase_get", side_effect=RuntimeError("private read")):
            with self.assertRaisesRegex(RuntimeError, "^monitoring_retry_outcome_unconfirmed$"):
                backend.append_monitoring_retry_outcome(claim, outcome)

    def test_invalid_outcome_keeps_claim_unresolved_without_recording_success(self):
        for outcome in ({"status": "成功", "receipt": ""}, {"status": "失敗", "receipt": "unexpected"}, {"status": "unknown", "receipt": ""}):
            with self.subTest(outcome=outcome), mock.patch.object(backend, "supabase_insert") as insert:
                with self.assertRaisesRegex(RuntimeError, "^monitoring_retry_outcome_invalid$"):
                    backend.append_monitoring_retry_outcome(self.retry_claim(), outcome)
                insert.assert_not_called()

    def test_claim_is_not_retried_after_delivery_exception(self):
        user = self.user()
        self.conn.execute("INSERT INTO users (id,name,email,role,status,company_id,account_source,logging_role_key,created_at) VALUES (:id,:name,:email,:role,:status,:company_id,:account_source,:logging_role_key,'2026-09-07')", user)
        with mock.patch.object(backend, "send_email_notification", return_value={"status": "失敗", "receipt": "", "error": "Resend HTTP 400"}):
            backend.execute_monitoring_mode("deliveryTest", self.conn)
        with mock.patch.object(backend, "send_resend_email_notification", side_effect=RuntimeError("private uncertain transport")) as send:
            with self.assertRaisesRegex(RuntimeError, "^monitoring_retry_delivery_unknown$"):
                backend.retry_monitoring_delivery_test(self.conn)
            second = backend.retry_monitoring_delivery_test(self.conn)
        send.assert_called_once()
        self.assertEqual(second["attempted"], 0)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM notification_deliveries WHERE id LIKE 'NDEL-MONRESULT-%'").fetchone()[0], 0)
        rows = [dict(row) for row in self.conn.execute("SELECT * FROM notification_deliveries")]
        self.assertEqual(backend.unresolved_notification_failure_count(rows), 1)

    def test_outcome_persists_when_notification_summary_update_fails(self):
        user = self.user()
        notice = {**backend.monitoring_alert_notification_payload({"deliveryTest": True}, user), "created_at": backend.now()}
        initial = {"id": "ORIGINAL", "notification_id": notice["id"], "channel": "Email", "target": user["email"], "status": "失敗", "receipt": "", "error": "Resend HTTP 400", "attempt_count": 1, "created_at": backend.now()}
        rows = {initial["id"]: initial}
        def query(table, *args, **kwargs):
            return [user] if table == "users" else list(rows.values())
        def insert(table, row):
            if row["id"] in rows:
                raise RuntimeError("duplicate")
            rows[row["id"]] = dict(row)
            return row
        def patch(table, *args):
            self.assertEqual(table, "notifications")
            raise RuntimeError("summary unavailable")
        with mock.patch.object(backend, "supabase_filter_rows", side_effect=query), mock.patch.object(backend, "supabase_get", return_value=notice), mock.patch.object(backend, "supabase_insert", side_effect=insert), mock.patch.object(backend, "supabase_patch", side_effect=patch), mock.patch.object(backend, "send_resend_email_notification", return_value={"status": "成功", "receipt": "accepted", "error": ""}) as send:
            with self.assertRaisesRegex(RuntimeError, "summary unavailable"):
                backend.retry_monitoring_delivery_test()
            second = backend.retry_monitoring_delivery_test()
        send.assert_called_once()
        self.assertEqual(second["attempted"], 0)
        self.assertEqual(len(rows), 3)
        self.assertEqual(backend.unresolved_notification_failure_count(list(rows.values())), 0)
        self.assertEqual(backend.notification_runtime_readiness(list(rows.values()))["email_validation"], "provider_accepted")

    def test_same_timestamp_outcome_resolves_claim_and_receipt_preview_in_any_order(self):
        claim = self.retry_claim()
        with mock.patch.object(backend, "supabase_insert"), mock.patch.object(backend, "now", return_value=claim["created_at"]):
            outcome = backend.append_monitoring_retry_outcome(claim, {"status": "成功", "receipt": "accepted", "error": ""})
        original = {**claim, "id": "ORIGINAL", "status": "失敗", "error": "Resend HTTP 400"}
        for rows in ([original, claim, outcome], [outcome, claim, original], [claim, outcome, original]):
            with self.subTest(order=[row["id"] for row in rows]):
                self.assertEqual(backend.unresolved_notification_failure_count(rows), 0)
                self.assertEqual(backend.notification_runtime_readiness(rows)["email_validation"], "provider_accepted")
                with mock.patch.object(backend, "deliver_supabase_monitoring_alerts", return_value={"notificationIds": [claim["notification_id"]]}), mock.patch.object(backend, "supabase_filter_rows", return_value=rows), mock.patch.object(backend, "send_resend_email_notification") as send:
                    result = backend.execute_monitoring_mode("deliveryTest")
                self.assertTrue(result["receipts"][0]["serviceAccepted"])
                self.assertEqual(result["receipts"][0]["receipt"], "accepted")
                send.assert_not_called()

    def test_supabase_generic_retry_cannot_bypass_fixed_test_limit(self):
        notice = {"id": "NTF-MONTEST-today", "status": "部分派送"}
        with mock.patch.object(backend, "supabase_list", return_value=[notice]), mock.patch.object(backend, "supabase_filter_rows", return_value=[{"channel": "Email"}]), mock.patch.object(backend, "send_email_notification") as send:
            self.assertEqual(backend.supabase_deliver_notification(notice["id"])["error"], "fixed_test_retry_only")
            self.assertEqual(backend.supabase_retry_failed_notifications()["count"], 0)
        send.assert_not_called()

    def test_unconfigured_line_is_not_an_internal_launch_requirement(self):
        with mock.patch.object(backend, "launch_scope", return_value="internal_official"):
            self.assertEqual(backend.monitored_notification_channels(), ["Email", "系統站內通知"])
            with mock.patch.dict(os.environ, {"LINE_CHANNEL_ACCESS_TOKEN": "partial-test-token"}):
                self.assertIn("Line 工作群組", backend.monitored_notification_channels())

    def test_successful_retry_clears_only_that_channel_failure(self):
        rows = [
            {"notification_id": "N-1", "channel": "Email", "status": "失敗", "created_at": "2026-09-01"},
            {"notification_id": "N-1", "channel": "Email", "status": "成功", "created_at": "2026-09-02"},
            {"notification_id": "N-1", "channel": "Line 工作群組", "status": "失敗", "created_at": "2026-09-01"},
        ]
        self.assertEqual(backend.unresolved_notification_failure_count(rows), 1)

    def test_interrupted_claim_stays_unresolved_in_monitoring(self):
        rows = [{"notification_id": "N-1", "channel": "Email", "status": "失敗", "created_at": "2026-09-06"}, {"notification_id": "N-1", "channel": "Email", "status": "重試中", "created_at": "2026-09-07"}]
        self.assertEqual(backend.unresolved_notification_failure_count(rows), 1)
        self.assertEqual(backend.notification_runtime_readiness(rows)["email_validation"], "delivery_failed")

    def test_dry_run_targets_only_exact_active_finance_operational_users(self):
        users = [self.user(), self.user("GA", logging_role_key="ga_chief", role="總務"), self.user("STOP", status="停用"), self.user("STAFF", logging_role_key="staff"), self.user("LEGACY", account_source="edoc"), self.user("BAD", email="not-an-email")]
        with mock.patch.object(backend, "send_email_notification") as send:
            preview = backend.monitoring_alert_delivery_preview(users)
        send.assert_not_called()
        self.assertEqual({row["userId"] for row in preview["recipients"]}, {"OPS-1", "GA"})
        self.assertTrue(preview["fallbackReady"])
        self.assertNotIn("@", json.dumps(preview))

    def test_monitoring_payload_is_hourly_stable_and_masks_details(self):
        with mock.patch.object(backend.time, "time", return_value=7201):
            first = backend.monitoring_alert_notification_payload(self.snapshot(), self.user())
        with mock.patch.object(backend.time, "time", return_value=7250):
            second = backend.monitoring_alert_notification_payload(self.snapshot(), self.user())
        self.assertEqual(first["id"], second["id"])
        self.assertNotIn("private employee", first["body"])
        self.assertNotIn("do-not-send", first["body"])
        self.assertIn("CRON-STALLED", first["body"])
        self.assertEqual(first["target_user_id"], "OPS-1")

    def test_local_monitoring_delivers_once_and_records_inbox_and_receipt(self):
        user = self.user()
        self.conn.execute("INSERT INTO users (id,name,email,role,status,company_id,account_source,logging_role_key,created_at) VALUES (:id,:name,:email,:role,:status,:company_id,:account_source,:logging_role_key,'2026-09-07')", user)
        with mock.patch.object(backend, "send_email_notification", return_value={"status": "成功", "receipt": "accepted-test-only", "error": ""}) as send:
            first = backend.deliver_local_monitoring_alerts(self.conn, self.snapshot())
            second = backend.deliver_local_monitoring_alerts(self.conn, self.snapshot())
        self.assertEqual(first["accepted"], 1)
        self.assertEqual(second["deduplicated"], 1)
        send.assert_called_once()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM system_inbox").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM notification_deliveries").fetchone()[0], 2)

    def test_supabase_monitoring_deduplicates_before_send(self):
        with mock.patch.object(backend, "supabase_filter_rows", return_value=[self.user()]), mock.patch.object(backend, "supabase_get", return_value={"id": "already-created"}), mock.patch.object(backend, "supabase_create_and_deliver_notification") as send:
            result = backend.deliver_supabase_monitoring_alerts(self.snapshot())
        send.assert_not_called()
        self.assertEqual(result["deduplicated"], 1)

    def test_monitoring_without_alerts_does_not_create_messages(self):
        with mock.patch.object(backend, "supabase_filter_rows", return_value=[self.user()]), mock.patch.object(backend, "supabase_create_and_deliver_notification") as send:
            result = backend.deliver_supabase_monitoring_alerts({"status": "healthy", "alerts": []})
        send.assert_not_called()
        self.assertEqual(result["attempted"], 0)

    def test_working_webhook_does_not_also_send_fallback_mail(self):
        with mock.patch.object(backend, "supabase_monitoring_snapshot", return_value=self.snapshot()), mock.patch.object(backend, "post_monitoring_webhook", return_value={"sent": True}), mock.patch.object(backend, "supabase_insert"), mock.patch.object(backend, "log_structured"), mock.patch.object(backend, "deliver_supabase_monitoring_alerts") as fallback:
            backend.run_supabase_monitoring_check()
        fallback.assert_not_called()

    def test_smtp_provider_errors_do_not_leak_recipient_or_response_text(self):
        with mock.patch.dict(os.environ, {"SMTP_HOST": "localhost", "SMTP_FROM": "notify@example.test"}), mock.patch.object(backend.smtplib, "SMTP", side_effect=backend.smtplib.SMTPResponseException(550, b"private recipient@example.test")):
            result = backend.send_smtp_email_notification("recipient@example.test", "test", "test")
        self.assertEqual(result["error"], "smtp_response_550")
        self.assertNotIn("@", result["error"])

    def test_dedicated_monitoring_token_cannot_run_other_crons_or_normal_apis(self):
        token = "monitoring-only-test-secret-" + "x" * 40
        for method, path, expected in (("GET", "/api/cron/monitoring", 201), ("POST", "/api/cron/monitoring", 401), ("GET", "/api/cron/run-due", 401), ("GET", "/api/cron/jobs", 401), ("GET", "/api/cron/monitoring/extra", 401), ("GET", "/api/notifications/gateway-status", 401)):
            with self.subTest(method=method, path=path):
                handler = object.__new__(backend.Handler)
                handler.headers = {"Authorization": f"Bearer {token}"}
                handler.bearer_token = lambda: token
                responses = []
                handler.send_json = lambda payload, status=200, *_args: responses.append((payload, status))
                with mock.patch.dict(os.environ, {"EDOC_MONITORING_CRON_SECRET": token}), mock.patch.object(backend, "USE_SUPABASE", True), mock.patch.object(backend, "run_supabase_monitoring_check", return_value={"ok": True}) as monitor, mock.patch.object(backend, "supabase_current_session", return_value=None):
                    handler.handle_api(method, path, {})
                self.assertEqual(responses[-1][1], expected)
                self.assertEqual(monitor.call_count, 1 if expected == 201 else 0)

    def test_monitoring_credential_requires_strength_and_constant_time_comparison(self):
        handler = object.__new__(backend.Handler)
        handler.headers = {"Authorization": "Bearer short"}
        with mock.patch.dict(os.environ, {"EDOC_MONITORING_CRON_SECRET": "short"}):
            self.assertFalse(handler.cron_authorized(monitoring_only=True))
        token = "x" * 48
        handler.headers = {"Authorization": f"Bearer {token}"}
        with mock.patch.dict(os.environ, {"EDOC_MONITORING_CRON_SECRET": token}), mock.patch.object(backend.hmac, "compare_digest", wraps=backend.hmac.compare_digest) as compare:
            self.assertTrue(handler.cron_authorized(monitoring_only=True))
            self.assertFalse(handler.cron_authorized())
        compare.assert_called_once()

    def test_monitoring_mode_rejects_unknown_empty_duplicate_or_combined_queries(self):
        invalid = ({"dryRun": [""]}, {"dryRun": ["0"]}, {"dryRun": ["1", "1"]}, {"deliveryTest": ["true"]}, {"dryRun": ["1"], "deliveryTest": ["1"]}, {"target": ["someone@example.test"]})
        for query in invalid:
            with self.subTest(query=query), self.assertRaisesRegex(ValueError, "monitoring_query_invalid"):
                backend.monitoring_request_mode(query)
        self.assertEqual(backend.monitoring_request_mode({"dryRun": ["1"]}), "dryRun")
        self.assertEqual(backend.monitoring_request_mode({"deliveryTest": ["1"]}), "deliveryTest")

    def test_dry_run_performs_no_database_writes_or_external_send(self):
        before = self.conn.total_changes
        ready = {"ready": True, "missing": [], "blockers": [], "warnings": []}
        service = {"ready": True, "productionBlocked": False, "missing": []}
        with mock.patch.object(backend, "is_production", return_value=False), mock.patch.object(backend, "launch_scope", return_value="internal_official"), mock.patch.object(backend, "internal_readiness", return_value=ready), mock.patch.object(backend, "production_readiness", return_value=ready), mock.patch.object(backend, "signing_service_status", return_value=service), mock.patch.object(backend, "storage_service_status", return_value=service), mock.patch.object(backend, "run_local_monitoring_check") as normal, mock.patch.object(backend, "deliver_local_monitoring_alerts") as delivery, mock.patch.object(backend, "log_audit") as audit:
            result = backend.execute_monitoring_mode("dryRun", self.conn)
        normal.assert_not_called()
        delivery.assert_not_called()
        audit.assert_not_called()
        self.assertEqual(self.conn.total_changes, before)
        self.assertFalse(result["writesPerformed"])

    def test_fixed_delivery_test_deduplicates_and_returns_service_acceptance_only(self):
        user = self.user()
        self.conn.execute("INSERT INTO users (id,name,email,role,status,company_id,account_source,logging_role_key,created_at) VALUES (:id,:name,:email,:role,:status,:company_id,:account_source,:logging_role_key,'2026-09-07')", user)
        with mock.patch.object(backend, "send_email_notification", return_value={"status": "成功", "receipt": "test-service-receipt", "error": ""}) as send:
            first = backend.execute_monitoring_mode("deliveryTest", self.conn)
            second = backend.execute_monitoring_mode("deliveryTest", self.conn)
        send.assert_called_once()
        self.assertIn("上線驗收測試", send.call_args.args[1])
        self.assertTrue(first["receipts"][0]["serviceAccepted"])
        self.assertEqual(second["receipts"], first["receipts"])
        self.assertEqual(second["delivery"]["deduplicated"], 1)
        self.assertFalse(first["humanReceiptConfirmed"])

    def test_long_term_advisory_never_triggers_outward_notification(self):
        snapshot = {"status": "warning", "alerts": [{"code": "READINESS-WARNING", "level": "warning", "message": "Sentry 尚未設定"}]}
        with mock.patch.object(backend, "supabase_monitoring_snapshot", return_value=snapshot), mock.patch.object(backend, "post_monitoring_webhook") as webhook, mock.patch.object(backend, "deliver_supabase_monitoring_alerts") as delivery, mock.patch.object(backend, "supabase_insert"), mock.patch.object(backend, "log_structured"):
            backend.run_supabase_monitoring_check()
        webhook.assert_not_called()
        delivery.assert_not_called()

    def test_warning_deduplicates_across_hours_but_critical_may_remind_hourly(self):
        warning = {"status": "warning", "alerts": [{"code": "NOTIFICATION-FAILED"}]}
        with mock.patch.object(backend.time, "time", return_value=7201):
            first = backend.monitoring_alert_notification_payload(warning, self.user())
            critical_first = backend.monitoring_alert_notification_payload(self.snapshot(), self.user())
        with mock.patch.object(backend.time, "time", return_value=10801):
            second = backend.monitoring_alert_notification_payload(warning, self.user())
            critical_second = backend.monitoring_alert_notification_payload(self.snapshot(), self.user())
        self.assertEqual(first["id"], second["id"])
        self.assertNotEqual(critical_first["id"], critical_second["id"])

    def test_blank_http_monitoring_flag_is_preserved_for_rejection(self):
        handler = object.__new__(backend.Handler)
        handler.path = "/api/cron/monitoring?dryRun"
        handler.handle_api = mock.Mock()
        handler.do_GET()
        handler.handle_api.assert_called_once_with("GET", "/api/cron/monitoring", {"dryRun": [""]})

    def test_invalid_monitoring_query_returns_400_without_execution(self):
        handler = object.__new__(backend.Handler)
        token = "x" * 48
        handler.headers = {"Authorization": f"Bearer {token}"}
        handler.bearer_token = lambda: token
        responses = []
        handler.send_json = lambda payload, status=200, *_args: responses.append((payload, status))
        with mock.patch.dict(os.environ, {"EDOC_MONITORING_CRON_SECRET": token}), mock.patch.object(backend, "USE_SUPABASE", True), mock.patch.object(backend, "execute_monitoring_mode") as execute:
            handler.handle_api("GET", "/api/cron/monitoring", {"dryRun": ["1"], "deliveryTest": ["1"]})
        execute.assert_not_called()
        self.assertEqual(responses[-1][1], 400)

    def test_supabase_monitoring_sends_real_ordered_queries_and_uses_latest_run(self):
        requested = []
        def request(method, path, *_args, **_kwargs):
            parsed = urlparse(path)
            query = parse_qs(parsed.query)
            requested.append((parsed.path, query))
            if parsed.path == "job_runs":
                return [{"id": "RUN-LATEST", "status": "成功", "finished_at": backend.now()}]
            if parsed.path == "notification_deliveries":
                return [{"notification_id": "N-1", "channel": "Email", "status": "成功", "receipt": "accepted", "created_at": "2026-09-07"}, {"notification_id": "N-1", "channel": "Email", "status": "失敗", "created_at": "2026-09-06"}]
            return []
        ready = {"ready": True, "missing": [], "blockers": [], "warnings": []}
        service = {"ready": True, "productionBlocked": False, "missing": []}
        with mock.patch.object(backend, "supabase_request", side_effect=request), mock.patch.object(backend, "supabase_list", return_value=[]), mock.patch.object(backend, "launch_scope", return_value="internal_official"), mock.patch.object(backend, "is_production", return_value=True), mock.patch.object(backend, "internal_readiness", return_value=ready), mock.patch.object(backend, "production_readiness", return_value=ready), mock.patch.object(backend, "signing_service_status", return_value=service), mock.patch.object(backend, "storage_service_status", return_value=service):
            snapshot = backend.supabase_monitoring_snapshot()
        queries = dict(requested)
        self.assertEqual(queries["job_runs"]["order"], ["finished_at.desc"])
        self.assertEqual(queries["job_runs"]["limit"], ["20"])
        self.assertEqual(queries["notification_deliveries"]["order"], ["created_at.desc"])
        self.assertEqual(queries["notification_deliveries"]["limit"], ["1000"])
        self.assertEqual(snapshot["checks"]["cron"]["lastRun"]["id"], "RUN-LATEST")
        self.assertEqual(snapshot["checks"]["cron"]["status"], "ok")
        self.assertEqual(snapshot["counts"]["notification_failed"], 0)

    def test_monitoring_scheduler_does_not_persist_bearer_in_network_queue(self):
        source = (Path(__file__).resolve().parents[1] / "supabase/migrations/20260907132959_edoc_monitor_secure_http_transport.sql").read_text()
        self.assertIn("security invoker", source)
        self.assertIn("from public, anon, authenticated, service_role", source)
        self.assertIn("select status into response_status", source)
        self.assertIn("command := 'select edoc_private.run_monitoring_http();'", source)
        self.assertNotIn("net.http_get(", source)
        self.assertNotIn("active := true", source)
        self.assertNotIn("active := false", source)
        self.assertIn("'CURLOPT_TIMEOUT_MS', '120000'", source)
        self.assertIn("raise exception 'edoc_monitor_request_failed'", source)


if __name__ == "__main__":
    unittest.main()
