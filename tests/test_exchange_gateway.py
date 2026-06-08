from __future__ import annotations

import json
import os
import sqlite3
import unittest

os.environ.setdefault("EDOC_EXCHANGE_PROVIDER", "mock")
os.environ.setdefault("EDOC_EXCHANGE_ENV", "sandbox")
os.environ.setdefault("EDOC_EXCHANGE_MAX_RETRIES", "2")

import backend
from exchange_gateway import (  # noqa: E402
    INBOX_FILED,
    INBOX_PENDING_ACK,
    OUTBOX_DELIVERED,
    OUTBOX_FAILED,
    OUTBOX_PENDING,
    OUTBOX_RETURNED,
    OUTBOX_SENT,
    SQLiteExchangeGateway,
)


class ExchangeGatewayTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(backend.SCHEMA)
        self._insert_document("DOC-OK", "歲悅字第1150527001號", "臺北市政府社會局", {})

    def tearDown(self) -> None:
        self.conn.close()

    def _insert_document(self, doc_id: str, doc_no: str, agency: str, metadata: dict) -> None:
        self.conn.execute(
            """
            INSERT INTO documents (
              id, doc_no, direction, company_name, doc_type, priority, security_level,
              agency_name, agency_code, subject, body, seal_plan_json, metadata_json,
              status, owner, department, created_at, updated_at
            ) VALUES (?, ?, '發文', '歲悅長照股份有限公司', '函', '普通件', '普通',
              ?, 'A63000000J', ?, '測試本文', '{}', ?, '待發文', '總務', '總管理處',
              '2026-05-27 09:00:00', '2026-05-27 09:00:00')
            """,
            (doc_id, doc_no, agency, f"測試公文 {doc_id}", json.dumps(metadata, ensure_ascii=False)),
        )

    def test_send_official_document_success_and_status_query(self) -> None:
        gateway = SQLiteExchangeGateway(self.conn, max_retries=2)

        sent = gateway.sendOfficialDocument({"document_id": "DOC-OK"})
        self.assertTrue(sent["ok"])
        self.assertEqual(sent["item"]["status"], OUTBOX_SENT)
        self.assertEqual(sent["item"]["provider"], "mock")

        status = gateway.queryDeliveryStatus({"outbox_id": sent["item"]["id"]})
        self.assertTrue(status["ok"])
        self.assertEqual(status["item"]["status"], OUTBOX_DELIVERED)

        history_count = self.conn.execute("SELECT COUNT(*) FROM exchange_status_history").fetchone()[0]
        log_count = self.conn.execute("SELECT COUNT(*) FROM exchange_log").fetchone()[0]
        self.assertGreaterEqual(history_count, 2)
        self.assertGreaterEqual(log_count, 2)

    def test_send_failure_then_retry_success(self) -> None:
        self._insert_document("DOC-FAIL", "歲悅字第1150527002號", "Mock 失敗機關", {"mock_exchange": "failure"})
        gateway = SQLiteExchangeGateway(self.conn, max_retries=2)

        failed = gateway.sendOfficialDocument({"document_id": "DOC-FAIL"})
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["item"]["status"], OUTBOX_FAILED)

        retried = gateway.retryFailedDelivery({"outbox_id": failed["item"]["id"]})
        self.assertTrue(retried["ok"])
        self.assertEqual(retried["item"]["status"], OUTBOX_SENT)
        self.assertEqual(retried["item"]["retry_count"], 1)

    def test_query_status_can_simulate_returned_document(self) -> None:
        self._insert_document("DOC-RETURN", "歲悅字第1150527003號", "Mock 退文機關", {"mock_exchange": "returned"})
        gateway = SQLiteExchangeGateway(self.conn, max_retries=2)

        sent = gateway.sendOfficialDocument({"document_id": "DOC-RETURN"})
        returned = gateway.queryDeliveryStatus({"outbox_id": sent["item"]["id"]})
        self.assertTrue(returned["ok"])
        self.assertEqual(returned["item"]["status"], OUTBOX_RETURNED)
        self.assertEqual(returned["item"]["last_error_code"], "MOCK_RETURNED_FOR_CORRECTION")

    def test_receive_and_acknowledge_inbound_document(self) -> None:
        gateway = SQLiteExchangeGateway(self.conn, max_retries=2)

        received = gateway.receiveOfficialDocuments({"external_id": "MOCK-IN-UNIT-001"})
        self.assertEqual(received["count"], 1)
        inbox = received["items"][0]
        self.assertEqual(inbox["status"], INBOX_PENDING_ACK)

        ack = gateway.acknowledgeReceived({"inbox_id": inbox["id"]})
        self.assertTrue(ack["ok"])
        self.assertEqual(ack["item"]["status"], INBOX_FILED)
        doc_status = self.conn.execute("SELECT status FROM documents WHERE id = ?", (inbox["document_id"],)).fetchone()[0]
        self.assertEqual(doc_status, "待分派")

    def test_scheduler_sends_pending_and_retries_failed(self) -> None:
        gateway = SQLiteExchangeGateway(self.conn, max_retries=2)
        queued = gateway.queueOfficialDocument({"document_id": "DOC-OK"})
        self.assertEqual(queued["status"], OUTBOX_PENDING)

        self.conn.execute(
            """
            INSERT INTO background_jobs (id, name, job_type, schedule_text, status, last_result, next_run_at, run_count, updated_at)
            VALUES ('JOB-SEND-TEST', '測試待發送出', 'exchangeSendPending', '每 5 分鐘', '啟用', '尚未執行', '2026-05-27 09:00:00', 0, '2026-05-27 09:00:00')
            """
        )
        run = backend.run_background_job(self.conn, "JOB-SEND-TEST")
        self.assertEqual(run["status"], "成功")
        self.assertEqual(run["payload"]["count"], 1)

        outbox_status = self.conn.execute("SELECT status FROM exchange_outbox WHERE id = ?", (queued["id"],)).fetchone()[0]
        self.assertEqual(outbox_status, OUTBOX_SENT)

        self._insert_document("DOC-JOB-FAIL", "歲悅字第1150527004號", "Mock 失敗機關", {"mock_exchange": "failure"})
        failed = gateway.sendOfficialDocument({"document_id": "DOC-JOB-FAIL"})
        self.assertEqual(failed["item"]["status"], OUTBOX_FAILED)
        self.conn.execute(
            """
            INSERT INTO background_jobs (id, name, job_type, schedule_text, status, last_result, next_run_at, run_count, updated_at)
            VALUES ('JOB-RETRY-TEST', '測試失敗重送', 'exchangeRetryFailed', '每 15 分鐘', '啟用', '尚未執行', '2026-05-27 09:00:00', 0, '2026-05-27 09:00:00')
            """
        )
        self.conn.execute("UPDATE exchange_outbox SET next_retry_at = '' WHERE id = ?", (failed["item"]["id"],))
        retry_run = backend.run_background_job(self.conn, "JOB-RETRY-TEST")
        self.assertEqual(retry_run["status"], "成功")
        self.assertEqual(retry_run["payload"]["count"], 1)

    def test_logs_redact_sensitive_payload(self) -> None:
        gateway = SQLiteExchangeGateway(self.conn, max_retries=2)
        sent = gateway.sendOfficialDocument({"document_id": "DOC-OK", "pin": "123456", "api_key": "secret-key"})
        self.assertTrue(sent["ok"])
        log = self.conn.execute("SELECT request_summary_json FROM exchange_log ORDER BY rowid DESC LIMIT 1").fetchone()[0]
        self.assertIn("[REDACTED]", log)
        self.assertNotIn("123456", log)
        self.assertNotIn("secret-key", log)


if __name__ == "__main__":
    unittest.main()
