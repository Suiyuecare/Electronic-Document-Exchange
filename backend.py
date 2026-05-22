#!/usr/bin/env python3
"""Suiyuecare eDoc backend.

Zero-dependency HTTP + SQLite service for the electronic document exchange module.
It serves the existing static frontend and exposes REST APIs that persist core
documents, recipients, attachments, exchange tasks/events, audit logs, users,
jobs, settings, and backups.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
BACKUP_DIR = ROOT / "backups"
DB_PATH = DATA_DIR / "edoc.sqlite3"
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")
USE_SUPABASE = os.getenv("EDOC_DB_MODE", "").lower() == "supabase" or bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


TABLES = {
    "documents": "documents",
    "recipients": "recipients",
    "attachments": "attachments",
    "exchange_tasks": "exchange_tasks",
    "exchange_events": "exchange_events",
    "audit_logs": "audit_logs",
    "users": "users",
    "background_jobs": "background_jobs",
    "settings": "settings",
}


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  doc_no TEXT NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN ('收文','發文')),
  doc_type TEXT NOT NULL DEFAULT '函',
  priority TEXT NOT NULL DEFAULT '普通件',
  security_level TEXT NOT NULL DEFAULT '普通',
  agency_name TEXT NOT NULL,
  agency_code TEXT,
  subject TEXT NOT NULL,
  body TEXT,
  status TEXT NOT NULL,
  owner TEXT,
  department TEXT,
  due_date TEXT,
  received_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recipients (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  code TEXT NOT NULL UNIQUE,
  exchange_center TEXT NOT NULL,
  status TEXT NOT NULL,
  contact TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attachments (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  file_name TEXT NOT NULL,
  version TEXT NOT NULL DEFAULT 'v1',
  mime_type TEXT,
  size_bytes INTEGER NOT NULL DEFAULT 0,
  sha256 TEXT NOT NULL,
  scan_status TEXT NOT NULL DEFAULT '待掃描',
  storage_key TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS exchange_tasks (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  direction TEXT NOT NULL,
  target_agency TEXT NOT NULL,
  status TEXT NOT NULL,
  package_id TEXT,
  retry_count INTEGER NOT NULL DEFAULT 0,
  next_check_at TEXT,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS exchange_events (
  id TEXT PRIMARY KEY,
  task_id TEXT,
  document_id TEXT,
  event_type TEXT NOT NULL,
  message TEXT NOT NULL,
  payload_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(task_id) REFERENCES exchange_tasks(id) ON DELETE SET NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id TEXT PRIMARY KEY,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  ip TEXT,
  device TEXT,
  detail TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  unit TEXT,
  title TEXT,
  role TEXT NOT NULL,
  provider TEXT NOT NULL DEFAULT '本機帳號',
  mfa_status TEXT NOT NULL DEFAULT '待設定',
  status TEXT NOT NULL DEFAULT '啟用',
  last_login_at TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS background_jobs (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  job_type TEXT NOT NULL,
  schedule_text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '啟用',
  last_result TEXT NOT NULL DEFAULT '尚未執行',
  next_run_at TEXT,
  run_count INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_direction ON documents(direction);
CREATE INDEX IF NOT EXISTS idx_attachments_document ON attachments(document_id);
CREATE INDEX IF NOT EXISTS idx_exchange_tasks_document ON exchange_tasks(document_id);
CREATE INDEX IF NOT EXISTS idx_exchange_events_document ON exchange_events(document_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at);
"""


SEED_DOCUMENTS = [
    {
        "id": "DOC-IN-1140522-00018",
        "doc_no": "收1140522-00018",
        "direction": "收文",
        "doc_type": "函",
        "priority": "速件",
        "security_level": "普通",
        "agency_name": "衛生福利部",
        "agency_code": "A21000000I",
        "subject": "長照服務品質稽核資料補件通知",
        "body": "jAgent 已拉取，待登錄收文號與附件完整性。",
        "status": "待登錄",
        "owner": "總收發",
        "department": "總管理處",
        "due_date": "2026-05-29",
        "received_at": "2026-05-22 09:42",
    },
    {
        "id": "DOC-OUT-1140522-007",
        "doc_no": "歲悅字第1140522007號",
        "direction": "發文",
        "doc_type": "函",
        "priority": "速件",
        "security_level": "普通",
        "agency_name": "臺北市政府社會局",
        "agency_code": "A63000000J",
        "subject": "檢送本公司日間照顧中心設立許可補正資料，請查照。",
        "body": "依貴局通知辦理，檢附補正資料、附件清冊及相關證明文件。",
        "status": "待清稿",
        "owner": "總收發",
        "department": "總管理處",
        "due_date": "2026-05-29",
        "received_at": None,
    },
    {
        "id": "DOC-OUT-1140519-006",
        "doc_no": "歲悅字第1140519006號",
        "direction": "發文",
        "doc_type": "函",
        "priority": "速件",
        "security_level": "普通",
        "agency_name": "新北市政府衛生局",
        "agency_code": "A65000000I",
        "subject": "補送居家服務品質改善計畫。",
        "body": "補送改善計畫附件，請惠予備查。",
        "status": "交換失敗",
        "owner": "總收發",
        "department": "居家照顧課",
        "due_date": "2026-05-24",
        "received_at": None,
    },
]


SEED_RECIPIENTS = [
    ("REC-001", "臺北市政府社會局", "A63000000J", "G2B2C 統合交換中心", "可交換", "文書收發窗口"),
    ("REC-002", "臺北市政府衛生局", "A63000000I", "G2B2C 統合交換中心", "可交換", "衛生局收發"),
    ("REC-003", "新北市政府衛生局", "A65000000I", "北區交換中心", "可交換", "公文交換窗口"),
    ("REC-004", "衛生福利部", "A21000000I", "G2B2C 統合交換中心", "可交換", "部本部總收文"),
]


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    BACKUP_DIR.mkdir(exist_ok=True)


def connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def log_audit(conn: sqlite3.Connection, actor: str, action: str, target_type: str = "", target_id: str = "", detail: str = "") -> None:
    conn.execute(
        """
        INSERT INTO audit_logs (id, actor, action, target_type, target_id, ip, device, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (f"AUD-{int(time.time() * 1000)}", actor, action, target_type, target_id, "127.0.0.1", "backend", detail, now()),
    )


def migrate() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        seed(conn)
        conn.commit()


def seed(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"]
    if existing:
        return

    ts = now()
    for doc in SEED_DOCUMENTS:
        conn.execute(
            """
            INSERT INTO documents (
              id, doc_no, direction, doc_type, priority, security_level, agency_name, agency_code,
              subject, body, status, owner, department, due_date, received_at, created_at, updated_at
            ) VALUES (
              :id, :doc_no, :direction, :doc_type, :priority, :security_level, :agency_name, :agency_code,
              :subject, :body, :status, :owner, :department, :due_date, :received_at, :created_at, :updated_at
            )
            """,
            {**doc, "created_at": ts, "updated_at": ts},
        )

    for row in SEED_RECIPIENTS:
        conn.execute(
            """
            INSERT INTO recipients (id, name, code, exchange_center, status, contact, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (*row, ts),
        )

    attachments = [
        ("ATT-001", "DOC-IN-1140522-00018", "稽核補件通知.pdf", "v1", "application/pdf", 838860, "SHA256-C8202AF1", "待掃描", "inbound/1140522/稽核補件通知.pdf"),
        ("ATT-002", "DOC-IN-1140522-00018", "附件清冊.xml", "v1", "application/xml", 4096, "SHA256-AD997210", "待掃描", "inbound/1140522/附件清冊.xml"),
        ("ATT-003", "DOC-OUT-1140522-007", "設立許可補正資料.pdf", "v2", "application/pdf", 19496960, "SHA256-4D91FA33", "雜湊通過", "outbound/1140522/設立許可補正資料.pdf"),
        ("ATT-004", "DOC-OUT-1140519-006", "品質改善計畫.pdf", "v1", "application/pdf", 6041600, "SHA256-RETRY-006", "雜湊通過", "outbound/1140519/品質改善計畫.pdf"),
    ]
    for item in attachments:
        conn.execute(
            """
            INSERT INTO attachments (id, document_id, file_name, version, mime_type, size_bytes, sha256, scan_status, storage_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*item, ts),
        )

    tasks = [
        ("TASK-001", "DOC-OUT-1140522-007", "發文", "臺北市政府社會局", "待清稿", "", 0, "2026-05-23 09:00"),
        ("TASK-002", "DOC-OUT-1140519-006", "發文", "新北市政府衛生局", "交換失敗", "PKG-1140519-006", 1, "2026-05-23 09:00"),
    ]
    for item in tasks:
        conn.execute(
            """
            INSERT INTO exchange_tasks (id, document_id, direction, target_agency, status, package_id, retry_count, next_check_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*item, ts),
        )

    events = [
        ("EVT-001", "TASK-002", "DOC-OUT-1140519-006", "failed", "jAgent 回覆 failed：收文方機關代碼暫不可用。"),
        ("EVT-002", None, "DOC-IN-1140522-00018", "pulled", "jAgent 拉取來文成功。"),
    ]
    for item in events:
        conn.execute(
            """
            INSERT INTO exchange_events (id, task_id, document_id, event_type, message, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (*item, "{}", ts),
        )

    users = [
        ("USR-001", "林總收發", "edoc@suiyuecare.com", "總管理處", "總收發人員", "總收發人員", "Google Workspace", "已啟用", "啟用"),
        ("USR-002", "張文書", "records@suiyuecare.com", "總管理處", "文書主管", "文書主管", "Microsoft Entra", "已啟用", "啟用"),
        ("USR-003", "陳資訊", "it@suiyuecare.com", "資訊室", "資訊管理員", "資訊管理員", "本機帳號", "強制重設", "啟用"),
    ]
    for item in users:
        conn.execute(
            """
            INSERT INTO users (id, name, email, unit, title, role, provider, mfa_status, status, last_login_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*item, None, ts),
        )

    jobs = [
        ("JOB-001", "每日收文拉取", "pullInbound", "每日 08:30", "啟用", "尚未執行", "2026-05-23 08:30", 0),
        ("JOB-002", "發文翌日查核", "nextDayCheck", "每日 09:00", "啟用", "尚未執行", "2026-05-23 09:00", 0),
        ("JOB-003", "Token 到期檢查", "tokenCheck", "每 15 分鐘", "啟用", "尚未執行", "2026-05-22 11:15", 0),
    ]
    for item in jobs:
        conn.execute(
            """
            INSERT INTO background_jobs (id, name, job_type, schedule_text, status, last_result, next_run_at, run_count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*item, ts),
        )

    settings = {
        "agency": {"name": "歲悅長照股份有限公司", "code": "A00000000"},
        "jagent": {"apiUrl": "https://jagent.example.gov.tw/api", "mode": "測試環境", "center": "G2B2C 統合交換中心"},
        "security": {"requireCertificate": True, "tokenTtlMinutes": 480},
    }
    for key, value in settings.items():
        conn.execute(
            "INSERT INTO settings (key, value_json, version, updated_at) VALUES (?, ?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), 1, ts),
        )

    log_audit(conn, "系統", "資料庫初始化", "database", "seed", "已建立正式後端資料庫種子資料")


def list_rows(conn: sqlite3.Connection, table: str, query: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    where: List[str] = []
    params: List[Any] = []
    if "status" in query:
        where.append("status = ?")
        params.append(query["status"][0])
    if "direction" in query and table == "documents":
        where.append("direction = ?")
        params.append(query["direction"][0])
    sql = f"SELECT * FROM {table}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY rowid DESC LIMIT 500"
    return [row_to_dict(row) for row in conn.execute(sql, params).fetchall()]


def insert_row(conn: sqlite3.Connection, table: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if "id" not in payload or not payload["id"]:
        payload["id"] = f"{table.upper()}-{int(time.time() * 1000)}"
    if table in {"documents", "recipients", "exchange_tasks", "settings"}:
        payload.setdefault("updated_at", now())
    if table in {"documents", "attachments", "exchange_events", "audit_logs", "users"}:
        payload.setdefault("created_at", now())
    columns = list(payload.keys())
    placeholders = ", ".join(["?"] * len(columns))
    conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        [payload[column] for column in columns],
    )
    log_audit(conn, "API", "新增資料", table, str(payload.get("id")), json.dumps(payload, ensure_ascii=False))
    return payload


def patch_row(conn: sqlite3.Connection, table: str, row_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if table in {"documents", "recipients", "exchange_tasks", "settings", "background_jobs"}:
        payload["updated_at"] = now()
    if not payload:
        return {}
    assignments = ", ".join([f"{key} = ?" for key in payload.keys()])
    conn.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", [*payload.values(), row_id])
    log_audit(conn, "API", "更新資料", table, row_id, json.dumps(payload, ensure_ascii=False))
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return row_to_dict(row) if row else {}


def dashboard(conn: sqlite3.Connection) -> Dict[str, Any]:
    def scalar(sql: str, params: Tuple[Any, ...] = ()) -> int:
        return int(conn.execute(sql, params).fetchone()[0])

    total_tasks = scalar("SELECT COUNT(*) FROM exchange_tasks")
    failed_tasks = scalar("SELECT COUNT(*) FROM exchange_tasks WHERE status LIKE '%失敗%'")
    complete_tasks = scalar("SELECT COUNT(*) FROM exchange_tasks WHERE status LIKE '%完成%' OR status LIKE '%確認%'")
    return {
        "documents": scalar("SELECT COUNT(*) FROM documents"),
        "inboundPending": scalar("SELECT COUNT(*) FROM documents WHERE direction = '收文' AND status IN ('待登錄','待分派')"),
        "dispatchPending": scalar("SELECT COUNT(*) FROM documents WHERE direction = '發文' AND status IN ('草稿','待清稿','已清稿')"),
        "exchangeTasks": total_tasks,
        "exchangeFailed": failed_tasks,
        "successRate": round((complete_tasks / total_tasks) * 100, 1) if total_tasks else 100,
        "auditLogs": scalar("SELECT COUNT(*) FROM audit_logs"),
    }


def pull_inbound(conn: sqlite3.Connection) -> Dict[str, Any]:
    doc_id = f"DOC-IN-{datetime.now().strftime('%y%m%d%H%M%S')}"
    ts = now()
    conn.execute(
        """
        INSERT INTO documents (
          id, doc_no, direction, doc_type, priority, security_level, agency_name, agency_code,
          subject, body, status, owner, department, due_date, received_at, created_at, updated_at
        ) VALUES (?, ?, '收文', '函', '普通件', '普通', '臺北市政府衛生局', 'A63000000I', ?, ?, '待登錄', '總收發', '總管理處', ?, ?, ?, ?)
        """,
        (
            doc_id,
            f"收{datetime.now().strftime('%y%m%d%H%M%S')}",
            "長照機構感染管制作業檢核通知",
            "由後端 jAgent adapter 拉取的新來文。",
            (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
            ts,
            ts,
            ts,
        ),
    )
    log_audit(conn, "jAgent Worker", "每日收文拉取", "documents", doc_id, "後端已建立收文主檔")
    return {"created": doc_id}


def backup_database(conn: sqlite3.Connection) -> Dict[str, Any]:
    ensure_dirs()
    name = f"edoc-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
    target = BACKUP_DIR / name
    conn.commit()
    shutil.copy2(DB_PATH, target)
    log_audit(conn, "API", "資料備份", "backup", name, str(target))
    return {"backup": name, "path": str(target), "size": target.stat().st_size}


def supabase_headers(extra: Dict[str, str] | None = None) -> Dict[str, str]:
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


def supabase_request(method: str, path: str, body: Any = None, prefer: str = "return=representation") -> Any:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
      raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    url = f"{SUPABASE_URL}/rest/v1/{path.lstrip('/')}"
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = supabase_headers({"Prefer": prefer})
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else []
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        raise RuntimeError(f"Supabase {exc.code}: {detail}") from exc


def supabase_list(table: str, query: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    params = {"select": "*", "limit": "500"}
    if "status" in query:
        params["status"] = f"eq.{query['status'][0]}"
    if "direction" in query and table == "documents":
        params["direction"] = f"eq.{query['direction'][0]}"
    qs = urllib.parse.urlencode(params)
    return supabase_request("GET", f"{table}?{qs}")


def supabase_get(table: str, row_id: str) -> Dict[str, Any] | None:
    qs = urllib.parse.urlencode({"select": "*", "id": f"eq.{row_id}", "limit": "1"})
    rows = supabase_request("GET", f"{table}?{qs}")
    return rows[0] if rows else None


def supabase_insert(table: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if "id" not in payload or not payload["id"]:
        payload["id"] = f"{table.upper()}-{int(time.time() * 1000)}"
    timestamp = now()
    if table in {"documents", "recipients", "exchange_tasks", "settings"}:
        payload.setdefault("updated_at", timestamp)
    if table in {"documents", "attachments", "exchange_events", "audit_logs", "users"}:
        payload.setdefault("created_at", timestamp)
    rows = supabase_request("POST", table, payload)
    return rows[0] if rows else payload


def supabase_patch(table: str, row_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if table in {"documents", "recipients", "exchange_tasks", "settings", "background_jobs"}:
        payload["updated_at"] = now()
    qs = urllib.parse.urlencode({"id": f"eq.{row_id}"})
    rows = supabase_request("PATCH", f"{table}?{qs}", payload)
    return rows[0] if rows else {}


def supabase_dashboard() -> Dict[str, Any]:
    documents = supabase_list("documents", {})
    tasks = supabase_list("exchange_tasks", {})
    audits = supabase_list("audit_logs", {})
    complete = [item for item in tasks if "完成" in item.get("status", "") or "確認" in item.get("status", "")]
    return {
        "documents": len(documents),
        "inboundPending": len([item for item in documents if item.get("direction") == "收文" and item.get("status") in {"待登錄", "待分派"}]),
        "dispatchPending": len([item for item in documents if item.get("direction") == "發文" and item.get("status") in {"草稿", "待清稿", "已清稿"}]),
        "exchangeTasks": len(tasks),
        "exchangeFailed": len([item for item in tasks if "失敗" in item.get("status", "")]),
        "successRate": round((len(complete) / len(tasks)) * 100, 1) if tasks else 100,
        "auditLogs": len(audits),
    }


def supabase_pull_inbound() -> Dict[str, Any]:
    doc_id = f"DOC-IN-{datetime.now().strftime('%y%m%d%H%M%S')}"
    timestamp = now()
    supabase_insert("documents", {
        "id": doc_id,
        "doc_no": f"收{datetime.now().strftime('%y%m%d%H%M%S')}",
        "direction": "收文",
        "doc_type": "函",
        "priority": "普通件",
        "security_level": "普通",
        "agency_name": "臺北市政府衛生局",
        "agency_code": "A63000000I",
        "subject": "長照機構感染管制作業檢核通知",
        "body": "由 Supabase 後端 jAgent adapter 拉取的新來文。",
        "status": "待登錄",
        "owner": "總收發",
        "department": "總管理處",
        "due_date": (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
        "received_at": timestamp,
    })
    supabase_insert("audit_logs", {
        "id": f"AUD-{int(time.time() * 1000)}",
        "actor": "jAgent Worker",
        "action": "每日收文拉取",
        "target_type": "documents",
        "target_id": doc_id,
        "ip": "supabase",
        "device": "vercel",
        "detail": "Supabase 後端已建立收文主檔",
    })
    return {"created": doc_id}


class Handler(SimpleHTTPRequestHandler):
    server_version = "SuiyueEdocBackend/1.0"

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path)
        rel = unquote(parsed.path).lstrip("/") or "index.html"
        return str((ROOT / rel).resolve())

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api("GET", parsed.path, parse_qs(parsed.query))
            return
        super().do_GET()

    def do_POST(self) -> None:
        self.handle_api("POST", urlparse(self.path).path, {})

    def do_PATCH(self) -> None:
        self.handle_api("PATCH", urlparse(self.path).path, {})

    def read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_api(self, method: str, path: str, query: Dict[str, List[str]]) -> None:
        parts = [part for part in path.split("/") if part][1:]
        try:
            if USE_SUPABASE:
                if method == "GET" and parts == ["health"]:
                    self.send_json({"ok": True, "database": "supabase", "project": SUPABASE_URL, "time": now(), "tables": list(TABLES)})
                    return
                if method == "GET" and parts == ["dashboard"]:
                    self.send_json(supabase_dashboard())
                    return
                if method == "GET" and parts == ["schema"]:
                    self.send_json({"tables": TABLES})
                    return
                if method == "POST" and parts == ["actions", "pull-inbound"]:
                    self.send_json(supabase_pull_inbound(), 201)
                    return
                if method == "POST" and parts == ["actions", "backup"]:
                    payload = {
                        "id": f"AUD-{int(time.time() * 1000)}",
                        "actor": "API",
                        "action": "Supabase logical backup requested",
                        "target_type": "backup",
                        "target_id": "supabase",
                        "ip": "vercel",
                        "device": "serverless",
                        "detail": "Supabase 備份需由 Supabase PITR / dashboard / scheduled dump 執行；本次已留下 audit log。",
                    }
                    supabase_insert("audit_logs", payload)
                    self.send_json({"backup": "supabase-logical-backup-request", "detail": payload["detail"]}, 201)
                    return
                if parts and parts[0] in TABLES:
                    table = TABLES[parts[0]]
                    if method == "GET" and len(parts) == 1:
                        self.send_json(supabase_list(table, query))
                        return
                    if method == "GET" and len(parts) == 2:
                        row = supabase_get(table, parts[1])
                        self.send_json(row if row else {"error": "not_found"}, 200 if row else 404)
                        return
                    if method == "POST" and len(parts) == 1:
                        self.send_json(supabase_insert(table, self.read_json()), 201)
                        return
                    if method == "PATCH" and len(parts) == 2:
                        row = supabase_patch(table, parts[1], self.read_json())
                        self.send_json(row if row else {"error": "not_found"}, 200 if row else 404)
                        return
                self.send_json({"error": "not_found", "path": path}, 404)
                return

            with connect() as conn:
                if method == "GET" and parts == ["health"]:
                    self.send_json({"ok": True, "database": str(DB_PATH), "time": now(), "tables": list(TABLES)})
                    return
                if method == "GET" and parts == ["dashboard"]:
                    self.send_json(dashboard(conn))
                    return
                if method == "GET" and parts == ["schema"]:
                    self.send_json({"tables": TABLES})
                    return
                if method == "POST" and parts == ["actions", "pull-inbound"]:
                    result = pull_inbound(conn)
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "POST" and parts == ["actions", "backup"]:
                    result = backup_database(conn)
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if parts and parts[0] in TABLES:
                    table = TABLES[parts[0]]
                    if method == "GET" and len(parts) == 1:
                        self.send_json(list_rows(conn, table, query))
                        return
                    if method == "GET" and len(parts) == 2:
                        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (parts[1],)).fetchone()
                        self.send_json(row_to_dict(row) if row else {"error": "not_found"}, 200 if row else 404)
                        return
                    if method == "POST" and len(parts) == 1:
                        row = insert_row(conn, table, self.read_json())
                        conn.commit()
                        self.send_json(row, 201)
                        return
                    if method == "PATCH" and len(parts) == 2:
                        row = patch_row(conn, table, parts[1], self.read_json())
                        conn.commit()
                        self.send_json(row if row else {"error": "not_found"}, 200 if row else 404)
                        return
                self.send_json({"error": "not_found", "path": path}, 404)
        except Exception as exc:  # Keep API observable during prototype hardening.
            self.send_json({"error": "server_error", "detail": str(exc)}, 500)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Suiyuecare eDoc backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=5174, type=int)
    parser.add_argument("--init-only", action="store_true")
    args = parser.parse_args()
    migrate()
    if args.init_only:
        print(f"Initialized {DB_PATH}")
        return
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Suiyuecare eDoc backend running at http://{args.host}:{args.port}")
    print(f"SQLite database: {DB_PATH}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
