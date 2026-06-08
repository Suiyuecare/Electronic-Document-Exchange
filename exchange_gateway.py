"""Protocol-neutral official document exchange gateway.

This module intentionally does not connect to Taiwan's production eDoc exchange
network. The first provider is a deterministic mock so the business workflow can
be wired and tested before the official jAgent/SOAP/file/SDK documents arrive.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


SENSITIVE_KEYWORDS = {
    "api_key",
    "apikey",
    "authorization",
    "certificate_password",
    "client_secret",
    "password",
    "passphrase",
    "pfx_password",
    "pin",
    "private_key",
    "secret",
    "token",
}

OUTBOX_PENDING = "待發文"
OUTBOX_SENT = "已送出"
OUTBOX_DELIVERED = "已送達"
OUTBOX_FAILED = "失敗"
OUTBOX_RETURNED = "退文"
OUTBOX_RETRY_LIMIT = "已達重送上限"
INBOX_PENDING_ACK = "待確認"
INBOX_FILED = "已入案"


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def make_id(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(keyword in key_text for keyword in SENSITIVE_KEYWORDS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


def redact_text(value: str) -> str:
    try:
        return json.dumps(redact_sensitive(json.loads(value)), ensure_ascii=False)
    except (TypeError, json.JSONDecodeError):
        text = value
        for keyword in SENSITIVE_KEYWORDS:
            text = text.replace(f"{keyword}=", f"{keyword}=[REDACTED]")
            text = text.replace(f"{keyword}:", f"{keyword}:[REDACTED]")
        return text


def safe_json(value: Any) -> str:
    return json.dumps(redact_sensitive(value or {}), ensure_ascii=False, sort_keys=True)


def parse_json(value: Optional[str]) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


class ExchangeProvider(ABC):
    """Provider adapter contract for jAgent, SOAP, file-drop, HTTP, or SDK."""

    name = "abstract"

    @abstractmethod
    def send_official_document(self, package: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def receive_official_documents(self, criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def query_delivery_status(self, tracking: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def acknowledge_received(self, inbound: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def retry_failed_delivery(self, package: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class ExchangeGateway(ABC):
    """Business-facing exchange interface.

    Keep these names camelCase because they mirror the requested integration API
    and make the boundary explicit for future frontend/API callers.
    """

    @abstractmethod
    def sendOfficialDocument(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def receiveOfficialDocuments(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def queryDeliveryStatus(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def acknowledgeReceived(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def retryFailedDelivery(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class MockExchangeProvider(ExchangeProvider):
    """Deterministic provider used until the formal exchange spec is available."""

    name = "mock"

    def __init__(self, default_scenario: Optional[str] = None) -> None:
        self.default_scenario = (default_scenario or os.getenv("EDOC_EXCHANGE_MOCK_SCENARIO") or "success").strip().lower()

    def _scenario(self, payload: Dict[str, Any]) -> str:
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        text = " ".join(str(payload.get(key, "")) for key in ("subject", "doc_no", "target_agency", "target_agency_code"))
        scenario = str(payload.get("mock_scenario") or metadata.get("mock_exchange") or self.default_scenario).strip().lower()
        if "[mock_fail]" in text.lower() or scenario in {"fail", "failed", "failure"}:
            return "failure"
        if "[mock_return]" in text.lower() or scenario in {"return", "returned"}:
            return "returned"
        return "success"

    def send_official_document(self, package: Dict[str, Any]) -> Dict[str, Any]:
        scenario = self._scenario(package)
        if scenario == "failure":
            return {
                "ok": False,
                "status": OUTBOX_FAILED,
                "provider_status": "MOCK_FAILED",
                "external_id": "",
                "message": "Mock provider 模擬發文失敗。",
                "error_code": "MOCK_SEND_FAILED",
                "retryable": True,
                "summary": {"scenario": scenario},
            }
        external_prefix = "MOCK-RETURN" if scenario == "returned" else "MOCK-SENT"
        return {
            "ok": True,
            "status": OUTBOX_SENT,
            "provider_status": "MOCK_ACCEPTED",
            "external_id": f"{external_prefix}-{secrets.token_hex(5).upper()}",
            "message": "Mock provider 模擬發文成功。",
            "error_code": "",
            "retryable": False,
            "summary": {"scenario": scenario},
        }

    def retry_failed_delivery(self, package: Dict[str, Any]) -> Dict[str, Any]:
        package = dict(package)
        if package.get("mock_retry_success", True):
            package["mock_scenario"] = "success"
        return self.send_official_document(package)

    def receive_official_documents(self, criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
        count = int(criteria.get("count") or os.getenv("EDOC_EXCHANGE_MOCK_INBOUND_COUNT", "1"))
        if count <= 0:
            return []
        received: List[Dict[str, Any]] = []
        for index in range(count):
            suffix = f"{datetime.now().strftime('%y%m%d%H%M%S')}-{index + 1}"
            external_id = criteria.get("external_id") or f"MOCK-IN-{suffix}"
            received.append({
                "external_id": external_id,
                "source_agency": criteria.get("source_agency") or "臺北市政府社會局",
                "source_agency_code": criteria.get("source_agency_code") or "A63000000J",
                "doc_no": criteria.get("doc_no") or f"北市社照字第{datetime.now().strftime('%Y%m%d%H%M%S')}號",
                "doc_type": criteria.get("doc_type") or "函",
                "priority": criteria.get("priority") or "普通件",
                "security_level": criteria.get("security_level") or "普通",
                "subject": criteria.get("subject") or "Mock 交換中心來文：長照服務資料補正通知",
                "body": criteria.get("body") or "此為 mock provider 產生的收文資料，供介接層與排程測試使用。",
                "attachments": criteria.get("attachments") or [{
                    "file_name": "mock-inbound-attachment.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 2048,
                    "sha256": "MOCK-SHA256-INBOUND",
                    "storage_key": f"mock/inbound/{external_id}.pdf",
                }],
                "summary": {"scenario": "inbound_mock"},
            })
        return received

    def query_delivery_status(self, tracking: Dict[str, Any]) -> Dict[str, Any]:
        external_id = str(tracking.get("external_id") or "")
        if external_id.startswith("MOCK-RETURN"):
            return {
                "ok": True,
                "status": OUTBOX_RETURNED,
                "provider_status": "MOCK_RETURNED",
                "message": "Mock provider 模擬退文：收文方退回補正。",
                "error_code": "MOCK_RETURNED_FOR_CORRECTION",
                "retryable": True,
                "summary": {"return_reason": "格式或附件需補正"},
            }
        if tracking.get("status") in {OUTBOX_FAILED, OUTBOX_RETRY_LIMIT}:
            return {
                "ok": False,
                "status": OUTBOX_FAILED,
                "provider_status": "MOCK_STILL_FAILED",
                "message": "Mock provider 模擬查詢：目前仍失敗。",
                "error_code": "MOCK_STILL_FAILED",
                "retryable": True,
                "summary": {},
            }
        return {
            "ok": True,
            "status": OUTBOX_DELIVERED,
            "provider_status": "MOCK_DELIVERED",
            "message": "Mock provider 模擬交換狀態查詢：收文方已確認。",
            "error_code": "",
            "retryable": False,
            "summary": {},
        }

    def acknowledge_received(self, inbound: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "ok": True,
            "status": INBOX_FILED,
            "provider_status": "MOCK_ACKNOWLEDGED",
            "message": "Mock provider 模擬收文確認成功。",
            "summary": {"external_id": inbound.get("external_id")},
        }


class SQLiteExchangeGateway(ExchangeGateway):
    def __init__(
        self,
        conn: sqlite3.Connection,
        provider: Optional[ExchangeProvider] = None,
        environment: Optional[str] = None,
        max_retries: Optional[int] = None,
    ) -> None:
        self.conn = conn
        self.provider = provider or MockExchangeProvider()
        self.environment = environment or os.getenv("EDOC_EXCHANGE_ENV", "sandbox")
        self.max_retries = int(max_retries if max_retries is not None else os.getenv("EDOC_EXCHANGE_MAX_RETRIES", "3"))

    def sendOfficialDocument(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        outbox = self._resolve_or_create_outbox(payload)
        package = self._build_outgoing_package(outbox, payload)
        result = self.provider.send_official_document(package)
        return self._apply_outbox_provider_result(outbox, result, "sendOfficialDocument", payload)

    def receiveOfficialDocuments(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        received = self.provider.receive_official_documents(payload)
        inbox_rows = []
        for item in received:
            existing = self.conn.execute("SELECT * FROM exchange_inbox WHERE external_id = ?", (item["external_id"],)).fetchone()
            if existing:
                inbox_rows.append(self._row(existing))
                continue
            doc_id = self._create_inbound_document(item)
            inbox_id = make_id("EXIN")
            ts = now()
            self.conn.execute(
                """
                INSERT INTO exchange_inbox (
                  id, document_id, external_id, source_agency, source_agency_code, doc_no, subject,
                  status, provider, environment, received_at, acknowledged_at, raw_summary_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?)
                """,
                (
                    inbox_id,
                    doc_id,
                    item["external_id"],
                    item.get("source_agency", ""),
                    item.get("source_agency_code", ""),
                    item.get("doc_no", ""),
                    item.get("subject", ""),
                    INBOX_PENDING_ACK,
                    self.provider.name,
                    self.environment,
                    ts,
                    safe_json(item.get("summary", {})),
                    ts,
                    ts,
                ),
            )
            self._insert_attachments("inbox", inbox_id, doc_id, item.get("attachments") or [])
            self._record_history("inbox", inbox_id, "", INBOX_PENDING_ACK, "Mock 收文已寫入待確認。", "MOCK_RECEIVED", item.get("summary", {}))
            self._insert_log("inbox", inbox_id, "receiveOfficialDocuments", "inbound", payload, item, "success")
            inbox_rows.append(self._get("exchange_inbox", inbox_id))
        return {"count": len(inbox_rows), "items": inbox_rows}

    def queryDeliveryStatus(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        outbox = self._load_outbox(payload)
        if not outbox:
            return {"ok": False, "error": "outbox_not_found"}
        result = self.provider.query_delivery_status(self._row(outbox))
        return self._apply_outbox_provider_result(outbox, result, "queryDeliveryStatus", payload)

    def acknowledgeReceived(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        inbox = self._load_inbox(payload)
        if not inbox:
            return {"ok": False, "error": "inbox_not_found"}
        result = self.provider.acknowledge_received(self._row(inbox))
        to_status = INBOX_FILED if result.get("ok") else self._row(inbox)["status"]
        ts = now()
        self.conn.execute(
            "UPDATE exchange_inbox SET status = ?, acknowledged_at = ?, updated_at = ? WHERE id = ?",
            (to_status, ts if result.get("ok") else "", ts, inbox["id"]),
        )
        if inbox["document_id"] and result.get("ok"):
            self.conn.execute("UPDATE documents SET status = ?, updated_at = ? WHERE id = ?", ("待分派", ts, inbox["document_id"]))
        self._record_history("inbox", inbox["id"], inbox["status"], to_status, result.get("message", ""), result.get("provider_status", ""), result.get("summary", {}))
        self._insert_log("inbox", inbox["id"], "acknowledgeReceived", "inbound", payload, result, "success" if result.get("ok") else "failed")
        return {"ok": bool(result.get("ok")), "item": self._get("exchange_inbox", inbox["id"]), "provider": result}

    def retryFailedDelivery(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        outbox = self._load_outbox(payload)
        if not outbox:
            return {"ok": False, "error": "outbox_not_found"}
        if outbox["status"] not in {OUTBOX_FAILED, OUTBOX_RETURNED, OUTBOX_RETRY_LIMIT}:
            return {"ok": True, "skipped": True, "reason": "status_not_retryable", "item": self._row(outbox)}
        if int(outbox["retry_count"] or 0) >= int(outbox["max_retries"] or self.max_retries):
            self._set_outbox_status(outbox, OUTBOX_RETRY_LIMIT, "重送上限已達。", "RETRY_LIMIT", {})
            return {"ok": False, "error": "retry_limit_reached", "item": self._get("exchange_outbox", outbox["id"])}
        retry_count = int(outbox["retry_count"] or 0) + 1
        self.conn.execute("UPDATE exchange_outbox SET retry_count = ?, updated_at = ? WHERE id = ?", (retry_count, now(), outbox["id"]))
        refreshed = self.conn.execute("SELECT * FROM exchange_outbox WHERE id = ?", (outbox["id"],)).fetchone()
        package = self._build_outgoing_package(refreshed, payload)
        result = self.provider.retry_failed_delivery(package)
        if not result.get("ok") and retry_count >= int(outbox["max_retries"] or self.max_retries):
            result = {**result, "status": OUTBOX_RETRY_LIMIT}
        return self._apply_outbox_provider_result(refreshed, result, "retryFailedDelivery", payload)

    def queueOfficialDocument(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._row(self._resolve_or_create_outbox({**payload, "queue_only": True}))

    def sendPendingOfficialDocuments(self, limit: int = 20) -> Dict[str, Any]:
        rows = self.conn.execute(
            "SELECT * FROM exchange_outbox WHERE status = ? ORDER BY created_at LIMIT ?",
            (OUTBOX_PENDING, limit),
        ).fetchall()
        results = [self.sendOfficialDocument({"outbox_id": row["id"]}) for row in rows]
        return {"count": len(results), "results": results}

    def queryPendingDeliveryStatuses(self, limit: int = 50) -> Dict[str, Any]:
        rows = self.conn.execute(
            "SELECT * FROM exchange_outbox WHERE status = ? ORDER BY updated_at LIMIT ?",
            (OUTBOX_SENT, limit),
        ).fetchall()
        results = [self.queryDeliveryStatus({"outbox_id": row["id"]}) for row in rows]
        return {"count": len(results), "results": results}

    def retryFailedDeliveries(self, limit: int = 20) -> Dict[str, Any]:
        rows = self.conn.execute(
            """
            SELECT * FROM exchange_outbox
            WHERE status IN (?, ?) AND retry_count < max_retries
              AND (next_retry_at IS NULL OR next_retry_at = '' OR next_retry_at <= ?)
            ORDER BY updated_at LIMIT ?
            """,
            (OUTBOX_FAILED, OUTBOX_RETURNED, now(), limit),
        ).fetchall()
        results = [self.retryFailedDelivery({"outbox_id": row["id"]}) for row in rows]
        return {"count": len(results), "results": results}

    def _resolve_or_create_outbox(self, payload: Dict[str, Any]) -> sqlite3.Row:
        existing = self._load_outbox(payload)
        if existing:
            return existing
        document_id = payload.get("document_id")
        if not document_id:
            raise ValueError("document_id is required")
        document = self.conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not document:
            raise ValueError(f"document_not_found:{document_id}")
        metadata = parse_json(document["metadata_json"])
        outbox_id = make_id("EXOUT")
        ts = now()
        max_retries = int(payload.get("max_retries") or metadata.get("exchange_max_retries") or self.max_retries)
        self.conn.execute(
            """
            INSERT INTO exchange_outbox (
              id, document_id, doc_no, target_agency, target_agency_code, status, provider, environment,
              package_id, external_id, idempotency_key, retry_count, max_retries, last_error_code,
              last_error_message, next_retry_at, sent_at, returned_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, 0, ?, '', '', '', '', '', ?, ?)
            """,
            (
                outbox_id,
                document_id,
                document["doc_no"],
                payload.get("target_agency") or document["agency_name"],
                payload.get("target_agency_code") or document["agency_code"] or "",
                OUTBOX_PENDING,
                self.provider.name,
                self.environment,
                payload.get("package_id") or f"PKG-{document['doc_no']}",
                payload.get("idempotency_key") or f"{document_id}:{document['doc_no']}",
                max_retries,
                ts,
                ts,
            ),
        )
        self._sync_legacy_exchange_task(outbox_id)
        self._record_history("outbox", outbox_id, "", OUTBOX_PENDING, "公文已加入交換待發佇列。", "QUEUED", {})
        return self.conn.execute("SELECT * FROM exchange_outbox WHERE id = ?", (outbox_id,)).fetchone()

    def _build_outgoing_package(self, outbox: sqlite3.Row, payload: Dict[str, Any]) -> Dict[str, Any]:
        document = self.conn.execute("SELECT * FROM documents WHERE id = ?", (outbox["document_id"],)).fetchone()
        if not document:
            raise ValueError(f"document_not_found:{outbox['document_id']}")
        attachments = [self._row(row) for row in self.conn.execute("SELECT * FROM attachments WHERE document_id = ?", (document["id"],)).fetchall()]
        metadata = parse_json(document["metadata_json"])
        return {
            "outbox_id": outbox["id"],
            "document_id": document["id"],
            "doc_no": document["doc_no"],
            "doc_type": document["doc_type"],
            "priority": document["priority"],
            "security_level": document["security_level"],
            "subject": document["subject"],
            "body": document["body"],
            "target_agency": outbox["target_agency"],
            "target_agency_code": outbox["target_agency_code"],
            "package_id": outbox["package_id"],
            "idempotency_key": outbox["idempotency_key"],
            "retry_count": outbox["retry_count"],
            "attachments": attachments,
            "metadata": metadata,
            "mock_scenario": payload.get("mock_scenario") or metadata.get("mock_exchange"),
            "mock_retry_success": payload.get("mock_retry_success", True),
        }

    def _apply_outbox_provider_result(self, outbox: sqlite3.Row, result: Dict[str, Any], operation: str, request_payload: Dict[str, Any]) -> Dict[str, Any]:
        from_status = outbox["status"]
        to_status = result.get("status") or (OUTBOX_SENT if result.get("ok") else OUTBOX_FAILED)
        if to_status == OUTBOX_FAILED and int(outbox["retry_count"] or 0) >= int(outbox["max_retries"] or self.max_retries):
            to_status = OUTBOX_RETRY_LIMIT
        ts = now()
        next_retry = ""
        if to_status in {OUTBOX_FAILED, OUTBOX_RETURNED} and int(outbox["retry_count"] or 0) < int(outbox["max_retries"] or self.max_retries):
            next_retry = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            """
            UPDATE exchange_outbox
            SET status = ?, external_id = COALESCE(NULLIF(?, ''), external_id), last_error_code = ?,
                last_error_message = ?, next_retry_at = ?, sent_at = CASE WHEN ? IN (?, ?) THEN COALESCE(NULLIF(sent_at, ''), ?) ELSE sent_at END,
                returned_at = CASE WHEN ? = ? THEN COALESCE(NULLIF(returned_at, ''), ?) ELSE returned_at END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                to_status,
                result.get("external_id", ""),
                result.get("error_code", ""),
                result.get("message", ""),
                next_retry,
                to_status,
                OUTBOX_SENT,
                OUTBOX_DELIVERED,
                ts,
                to_status,
                OUTBOX_RETURNED,
                ts,
                ts,
                outbox["id"],
            ),
        )
        self._record_history("outbox", outbox["id"], from_status, to_status, result.get("message", ""), result.get("provider_status", ""), result.get("summary", {}))
        self._insert_log("outbox", outbox["id"], operation, "outbound", request_payload, result, "success" if result.get("ok") else "failed")
        self._sync_legacy_exchange_task(outbox["id"])
        return {"ok": bool(result.get("ok")), "item": self._get("exchange_outbox", outbox["id"]), "provider": redact_sensitive(result)}

    def _create_inbound_document(self, item: Dict[str, Any]) -> str:
        doc_id = make_id("DOC-IN")
        ts = now()
        self.conn.execute(
            """
            INSERT INTO documents (
              id, doc_no, direction, doc_type, priority, security_level, agency_name, agency_code,
              subject, body, status, owner, department, due_date, received_at, created_at, updated_at
            ) VALUES (?, ?, '收文', ?, ?, ?, ?, ?, ?, ?, '待登錄', '總務', '總管理處', ?, ?, ?, ?)
            """,
            (
                doc_id,
                item.get("doc_no") or f"收{datetime.now().strftime('%y%m%d%H%M%S')}",
                item.get("doc_type") or "函",
                item.get("priority") or "普通件",
                item.get("security_level") or "普通",
                item.get("source_agency") or "",
                item.get("source_agency_code") or "",
                item.get("subject") or "未命名來文",
                item.get("body") or "",
                (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
                ts,
                ts,
                ts,
            ),
        )
        return doc_id

    def _insert_attachments(self, ref_type: str, ref_id: str, document_id: str, attachments: List[Dict[str, Any]]) -> None:
        for attachment in attachments:
            self.conn.execute(
                """
                INSERT INTO exchange_attachment (
                  id, exchange_ref_type, exchange_ref_id, document_id, file_name, mime_type,
                  size_bytes, sha256, storage_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    make_id("EXATT"),
                    ref_type,
                    ref_id,
                    document_id,
                    attachment.get("file_name", ""),
                    attachment.get("mime_type", ""),
                    int(attachment.get("size_bytes") or 0),
                    attachment.get("sha256", ""),
                    attachment.get("storage_key", ""),
                    now(),
                ),
            )

    def _load_outbox(self, payload: Dict[str, Any]) -> Optional[sqlite3.Row]:
        if payload.get("outbox_id"):
            return self.conn.execute("SELECT * FROM exchange_outbox WHERE id = ?", (payload["outbox_id"],)).fetchone()
        if payload.get("id"):
            return self.conn.execute("SELECT * FROM exchange_outbox WHERE id = ?", (payload["id"],)).fetchone()
        if payload.get("external_id"):
            return self.conn.execute("SELECT * FROM exchange_outbox WHERE external_id = ?", (payload["external_id"],)).fetchone()
        if payload.get("document_id"):
            return self.conn.execute(
                "SELECT * FROM exchange_outbox WHERE document_id = ? ORDER BY created_at DESC LIMIT 1",
                (payload["document_id"],),
            ).fetchone()
        return None

    def _load_inbox(self, payload: Dict[str, Any]) -> Optional[sqlite3.Row]:
        if payload.get("inbox_id"):
            return self.conn.execute("SELECT * FROM exchange_inbox WHERE id = ?", (payload["inbox_id"],)).fetchone()
        if payload.get("id"):
            return self.conn.execute("SELECT * FROM exchange_inbox WHERE id = ?", (payload["id"],)).fetchone()
        if payload.get("external_id"):
            return self.conn.execute("SELECT * FROM exchange_inbox WHERE external_id = ?", (payload["external_id"],)).fetchone()
        return None

    def _set_outbox_status(self, outbox: sqlite3.Row, status: str, message: str, provider_status: str, summary: Dict[str, Any]) -> None:
        self.conn.execute("UPDATE exchange_outbox SET status = ?, updated_at = ? WHERE id = ?", (status, now(), outbox["id"]))
        self._record_history("outbox", outbox["id"], outbox["status"], status, message, provider_status, summary)
        self._sync_legacy_exchange_task(outbox["id"])

    def _record_history(self, ref_type: str, ref_id: str, from_status: str, to_status: str, message: str, provider_status: str, payload: Dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO exchange_status_history (
              id, exchange_ref_type, exchange_ref_id, from_status, to_status, message,
              provider_status_code, payload_summary_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (make_id("EXHIS"), ref_type, ref_id, from_status or "", to_status or "", message or "", provider_status or "", safe_json(payload), now()),
        )

    def _insert_log(
        self,
        ref_type: str,
        ref_id: str,
        operation: str,
        direction: str,
        request_summary: Dict[str, Any],
        response_summary: Dict[str, Any],
        status: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO exchange_log (
              id, exchange_ref_type, exchange_ref_id, provider, environment, operation, direction,
              request_summary_json, response_summary_json, status, error_code, error_message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                make_id("EXLOG"),
                ref_type,
                ref_id,
                self.provider.name,
                self.environment,
                operation,
                direction,
                safe_json(request_summary),
                safe_json(response_summary),
                status,
                response_summary.get("error_code", "") if isinstance(response_summary, dict) else "",
                response_summary.get("message", "") if isinstance(response_summary, dict) else "",
                now(),
            ),
        )

    def _sync_legacy_exchange_task(self, outbox_id: str) -> None:
        outbox = self.conn.execute("SELECT * FROM exchange_outbox WHERE id = ?", (outbox_id,)).fetchone()
        if not outbox:
            return
        task_id = f"TASK-{outbox_id}"
        self.conn.execute(
            """
            INSERT INTO exchange_tasks (id, document_id, direction, target_agency, status, package_id, retry_count, next_check_at, updated_at)
            VALUES (?, ?, '發文', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              status = excluded.status,
              package_id = excluded.package_id,
              retry_count = excluded.retry_count,
              next_check_at = excluded.next_check_at,
              updated_at = excluded.updated_at
            """,
            (
                task_id,
                outbox["document_id"],
                outbox["target_agency"],
                outbox["status"],
                outbox["package_id"],
                outbox["retry_count"],
                outbox["next_retry_at"],
                now(),
            ),
        )
        self.conn.execute(
            """
            INSERT INTO exchange_events (id, task_id, document_id, event_type, message, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                make_id("EVT"),
                task_id,
                outbox["document_id"],
                "gateway_sync",
                f"交換介接層同步狀態：{outbox['status']}",
                safe_json({"outbox_id": outbox["id"], "external_id": outbox["external_id"]}),
                now(),
            ),
        )

    def _get(self, table: str, row_id: str) -> Dict[str, Any]:
        row = self.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
        return self._row(row) if row else {}

    def _row(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {key: row[key] for key in row.keys()}


def create_exchange_gateway(conn: sqlite3.Connection) -> SQLiteExchangeGateway:
    provider_name = os.getenv("EDOC_EXCHANGE_PROVIDER", "mock").strip().lower()
    if provider_name != "mock":
        raise RuntimeError(f"exchange_provider_not_implemented:{provider_name}")
    return SQLiteExchangeGateway(conn, MockExchangeProvider())
