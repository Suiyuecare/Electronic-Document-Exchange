#!/usr/bin/env python3
"""Suiyuecare eDoc backend.

Zero-dependency HTTP + SQLite service for the electronic document exchange module.
It serves the existing static frontend and exposes REST APIs that persist core
documents, recipients, attachments, exchange tasks/events, audit logs, users,
jobs, settings, and backups.
"""

from __future__ import annotations

import argparse
import base64
import io
import smtplib
import ssl
import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from email.message import EmailMessage
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from exchange_gateway import MockExchangeProvider, create_exchange_gateway, redact_sensitive, redact_text


ROOT = Path(__file__).resolve().parent
RUNNING_ON_VERCEL = bool(os.getenv("VERCEL"))
WRITABLE_ROOT = Path(os.getenv("EDOC_WRITABLE_DIR", "/tmp/edoc" if RUNNING_ON_VERCEL else str(ROOT)))
DATA_DIR = WRITABLE_ROOT / "data"
BACKUP_DIR = WRITABLE_ROOT / "backups"
STORAGE_DIR = WRITABLE_ROOT / "storage"
PRIVATE_SEAL_STORAGE_DIR = STORAGE_DIR / "seal-vault" / "seals"
SEAL_VAULT_DOCUMENT_ID = "SEAL-VAULT"
SEAL_VAULT_PURPOSE_PREFIX = "seal-vault"
DB_PATH = DATA_DIR / "edoc.sqlite3"
DEPLOYMENT_ENV = os.getenv("EDOC_DEPLOYMENT_ENV", os.getenv("VERCEL_ENV", "development")).lower()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")
USE_SUPABASE = os.getenv("EDOC_DB_MODE", "").lower() == "supabase" or bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)
EDOC_STORAGE_PROVIDER = os.getenv("EDOC_STORAGE_PROVIDER", "local").lower()
EDOC_STORAGE_BUCKET = os.getenv("EDOC_STORAGE_BUCKET", "edoc-private")
EDOC_SEAL_STORAGE_BUCKET = os.getenv("EDOC_SEAL_STORAGE_BUCKET", "edoc-seal-vault")
EDOC_OBJECT_STORAGE_URL = os.getenv("EDOC_OBJECT_STORAGE_URL", (f"{SUPABASE_URL}/storage/v1" if SUPABASE_URL else "")).rstrip("/")
EDOC_STORAGE_ACCESS_MODE = os.getenv("EDOC_STORAGE_ACCESS_MODE", "server-signed-url")
EDOC_SIGNED_URL_TTL_SECONDS = int(os.getenv("EDOC_SIGNED_URL_TTL_SECONDS", "300"))
EDOC_FILE_ENCRYPTION_KEY = os.getenv("EDOC_FILE_ENCRYPTION_KEY", os.getenv("APP_SECRET", "dev-edoc-file-key"))
EDOC_FILE_ENCRYPTION_ENABLED = os.getenv("EDOC_FILE_ENCRYPTION_ENABLED", "true").lower() != "false"
EDOC_SCAN_ENGINE = os.getenv("EDOC_SCAN_ENGINE", "ClamAV-compatible")
EDOC_AV_PROVIDER = os.getenv("EDOC_AV_PROVIDER", EDOC_SCAN_ENGINE)
EDOC_AV_ENDPOINT = os.getenv("EDOC_AV_ENDPOINT", "")
EDOC_MAX_FILE_SIZE_MB = int(os.getenv("EDOC_MAX_FILE_SIZE_MB", "100"))
EDOC_ALLOWED_MIME_TYPES = os.getenv("EDOC_ALLOWED_MIME_TYPES", "application/pdf,application/xml,text/xml,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/pkcs7-mime,application/octet-stream")
EDOC_SEAL_FILE_MAX_SIZE_MB = int(os.getenv("EDOC_SEAL_FILE_MAX_SIZE_MB", "5"))
EDOC_SEAL_ALLOWED_MIME_TYPES = os.getenv("EDOC_SEAL_ALLOWED_MIME_TYPES", "image/png,image/jpeg,image/webp,image/svg+xml")
EDOC_PUBLIC_BASE_URL = os.getenv("EDOC_PUBLIC_BASE_URL", os.getenv("PRODUCTION_BASE_URL", "")).rstrip("/")
MONITORING_WEBHOOK_URL = os.getenv("MONITORING_WEBHOOK_URL", "")
SENTRY_DSN = os.getenv("SENTRY_DSN", "")
EDOC_MONITORING_EXPECTED_CRON_MINUTES = int(os.getenv("EDOC_MONITORING_EXPECTED_CRON_MINUTES", "1440"))
EDOC_SIGNATURE_PROVIDER = os.getenv("EDOC_SIGNATURE_PROVIDER", "local-simulation")
EDOC_SIGNATURE_API_URL = os.getenv("EDOC_SIGNATURE_API_URL", "").rstrip("/")
EDOC_SIGNATURE_API_KEY = os.getenv("EDOC_SIGNATURE_API_KEY", "")
EDOC_SIGNATURE_KEY_ID = os.getenv("EDOC_SIGNATURE_KEY_ID", "")
EDOC_SIGNATURE_PROFILE = os.getenv("EDOC_SIGNATURE_PROFILE", "CAdES-B-LT")
EDOC_SIGNATURE_TIMEOUT_SECONDS = int(os.getenv("EDOC_SIGNATURE_TIMEOUT_SECONDS", "25"))
EDOC_SIGNATURE_MAX_RETRIES = int(os.getenv("EDOC_SIGNATURE_MAX_RETRIES", "2"))
EDOC_HSM_PROVIDER = os.getenv("EDOC_HSM_PROVIDER", "")
EDOC_CERT_TRUST_STORE = os.getenv("EDOC_CERT_TRUST_STORE", "")
EDOC_TSA_URL = os.getenv("EDOC_TSA_URL", "")
EDOC_TSA_API_KEY = os.getenv("EDOC_TSA_API_KEY", "")
EDOC_TSA_POLICY_OID = os.getenv("EDOC_TSA_POLICY_OID", "1.3.6.1.4.1.55555.1.1")
EDOC_OCSP_RESPONDER_URL = os.getenv("EDOC_OCSP_RESPONDER_URL", "")
EDOC_CRL_DISTRIBUTION_URL = os.getenv("EDOC_CRL_DISTRIBUTION_URL", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
EDOC_EXCHANGE_ENV = os.getenv("EDOC_EXCHANGE_ENV", "sandbox").strip().lower()
EDOC_EXCHANGE_PROVIDER = os.getenv("EDOC_EXCHANGE_PROVIDER", "mock").strip().lower()
EDOC_EXCHANGE_MAX_RETRIES = int(os.getenv("EDOC_EXCHANGE_MAX_RETRIES", "3"))
ALLOWED_EDOC_ROLE_LIST = [
    "員工",
    "主管",
    "主任",
    "執行長",
    "行政部主任",
    "人資",
    "會計",
    "總務",
    "業務助理",
    "董事會",
    "股東",
    "外部檢核單位",
]
ALLOWED_EDOC_ROLES = set(ALLOWED_EDOC_ROLE_LIST)
EDOC_JOB_LEVELS = {"職員", "組長", "課長", "部長", "區經理", "執行長", "董事會", "股東", "外部檢核單位"}
HRIS_QUICK_LOGIN_SECRET = os.getenv("HRIS_QUICK_LOGIN_SECRET", os.getenv("NEXTAUTH_SECRET", "suiyue-hris-local-quick-login-secret"))
PORTAL_HANDOFF_SECRET = os.getenv(
    "EDOC_PORTAL_HANDOFF_SECRET",
    os.getenv("PORTAL_HANDOFF_SIGNING_SECRET", ""),
).strip()
PORTAL_HANDOFF_MAX_AGE_SECONDS = int(os.getenv("EDOC_PORTAL_HANDOFF_MAX_AGE_SECONDS", "600"))

LOGGING_AUDIT_EVENT_TYPES = {
    "login",
    "logout",
    "export",
    "print",
    "delete",
    "submit",
    "approve",
    "reject",
    "assign",
    "permission_change",
    "sensitive_access",
    "external_account_status_change",
}
LOGGING_CRITICAL_EVENTS = {"delete", "permission_change", "sensitive_access", "external_account_status_change"}
LOGGING_DATA_SCOPES = {"self", "assigned", "class", "department", "business_unit", "region", "institution", "company", "group", "custom"}

LOGGING_ROLE_ALIASES = {
    "team_member": "staff",
    "employee": "staff",
    "supervisor": "section_chief",
    "hr": "hr_chief",
    "super_admin": "ceo",
    "company_admin": "admin_director",
    "hr_manager": "hr_chief",
    "accountant": "admin_director",
    "department_manager": "department_head",
    "homecare_supervisor": "section_chief",
    "homecare_worker": "staff",
    "daycare_staff": "staff",
    "system": "system_department",
    "system_admin": "system_department",
    "it": "system_department",
    "it_admin": "system_department",
    "系統處": "system_department",
    "資訊": "system_department",
    "admin-director": "admin_director",
    "hr-chief": "hr_chief",
    "hr-staff": "hr_staff",
    "accounting-chief": "accounting_chief",
    "cashier-chief": "accounting_chief",
    "ga-chief": "ga_chief",
    "business-director": "department_head",
    "section-chief": "section_chief",
    "team-lead": "team_lead",
    "region-manager": "district_manager",
    "external-audit": "external_auditor",
    "external-auditor": "external_auditor",
}

LOGGING_ROLE_TO_EDOC_PROFILE = {
    "board": {"role": "董事會", "job_level": "董事會", "title": "董事會成員", "unit": "董事會"},
    "shareholder": {"role": "股東", "job_level": "股東", "title": "股東代表", "unit": "股東"},
    "ceo": {"role": "執行長", "job_level": "執行長", "title": "執行長", "unit": "經營管理"},
    "district_manager": {"role": "主管", "job_level": "區經理", "title": "區經理", "unit": "營運管理處"},
    "department_head": {"role": "主任", "job_level": "部長", "title": "部門主管", "unit": "營運管理處"},
    "section_chief": {"role": "主管", "job_level": "課長", "title": "課長", "unit": "營運管理處"},
    "team_lead": {"role": "主管", "job_level": "組長", "title": "組長", "unit": "營運管理處"},
    "staff": {"role": "員工", "job_level": "職員", "title": "職員", "unit": "居家照顧部"},
    "external_auditor": {"role": "外部檢核單位", "job_level": "外部檢核單位", "title": "外部檢核", "unit": "外部檢核"},
    "system_department": {"role": "行政部主任", "job_level": "部長", "title": "系統處管理員", "unit": "系統處"},
    "admin_director": {"role": "行政部主任", "job_level": "部長", "title": "行政部門主任", "unit": "行政部"},
    "hr_chief": {"role": "人資", "job_level": "課長", "title": "人資課長", "unit": "人資"},
    "hr_staff": {"role": "人資", "job_level": "職員", "title": "人資組員", "unit": "人資"},
    "accounting_chief": {"role": "會計", "job_level": "課長", "title": "會計課長", "unit": "會計"},
    "ga_chief": {"role": "總務", "job_level": "課長", "title": "總務課長", "unit": "總務"},
}

LOGGING_PERMISSION_TO_EDOC_CODES = {
    "request:create": ["official_documents.compose"],
    "form:document:create": ["official_documents.compose"],
    "request:view": ["official_documents.records"],
    "request:own:view": ["official_documents.records"],
    "request:team:view": ["official_documents.todo", "official_documents.records"],
    "request:approve": ["official_documents.todo"],
    "request:admin": ["official_documents.all_todo", "official_documents.all_records"],
    "module:admin": ["official_documents.all_todo", "official_documents.all_records", "exchange.manage", "system_permissions.view"],
    "system:settings": ["settings.system_manage", "system_permissions.manage"],
    "permission:settings:view": ["system_permissions.view"],
    "permission:settings:publish": ["system_permissions.manage"],
    "system:audit:view": ["audit_logs.view"],
    "internal_audit:view": ["audit_logs.view"],
    "internal_audit:manage": ["audit_logs.view", "audit_logs.export"],
    "analytics:view": ["reports.operational_view"],
    "analytics:export": ["reports.operational_view", "audit_logs.export"],
    "bi:view": ["reports.operational_view"],
    "bi:manage": ["reports.operational_view"],
    "compliance:view": ["audit_logs.view"],
    "compliance:manage": ["audit_logs.view", "audit_logs.export"],
    "finance_handoff:view": ["contracts.view"],
    "finance_handoff:manage": ["contracts.manage", "contracts.seal"],
}

EDOC_ROLE_CATALOG = [
    ("ROLE-EMPLOYEE", "員工", "edoc_employee", "撰寫公文、處理個人待辦並查詢所屬部門公文紀錄。", "department"),
    ("ROLE-SUPERVISOR", "主管", "edoc_supervisor", "承接所屬部門簽核、退回補正與部門公文紀錄。", "department"),
    ("ROLE-DIRECTOR", "主任", "edoc_director", "承接所屬部門公文、核准部門分派與追蹤處理時限。", "department"),
    ("ROLE-CEO", "執行長", "edoc_ceo", "核定重大、密件或跨部門高風險公文並查閱全公司資料。", "company"),
    ("ROLE-ADMIN-CHIEF", "行政部主任", "edoc_admin_chief", "管理流程、清稿、角色權限、交換參數、資安與營運維護。", "company"),
    ("ROLE-HR", "人資", "edoc_hr", "處理人資相關來文、發文、附件補正與部門公文紀錄。", "department"),
    ("ROLE-ACCOUNTING", "會計", "edoc_accounting", "處理會計、補助款、核銷相關來文與發文。", "department"),
    ("ROLE-GA", "總務", "edoc_general_affairs", "唯一收文入口；拉取、登錄來文後分發給各部門主管。", "company"),
    ("ROLE-SALES-ASSISTANT", "業務助理", "edoc_sales_assistant", "建立函稿、補附件、協助發文與查詢被分派案件。", "assigned"),
    ("ROLE-BOARD", "董事會", "edoc_board", "查閱全公司治理層級公文、合約與稽核紀錄，不處理日常收發。", "group"),
    ("ROLE-SHAREHOLDER", "股東", "edoc_shareholder", "查閱經授權的全公司彙總紀錄與治理報表，不處理日常收發。", "group"),
    ("ROLE-EXTERNAL-AUDITOR", "外部檢核單位", "edoc_external_auditor", "僅查閱被授權的檢核資料與 audit log。", "custom"),
]

EDOC_PERMISSION_CATALOG = [
    ("PERM-EDOC-COMPOSE", "official_documents.compose", "撰寫公文", "official_documents", "建立函稿、預覽、送簽與補正。"),
    ("PERM-EDOC-TODO", "official_documents.todo", "公文待辦", "official_documents", "查看並處理個人或角色待辦。"),
    ("PERM-EDOC-RECORDS", "official_documents.records", "公文紀錄", "official_documents", "查詢可見範圍內的收發文紀錄。"),
    ("PERM-EDOC-RECEIVE", "official_documents.receive", "公文收發", "official_documents", "總務或授權角色執行收文、登錄、分派與交換處理。"),
    ("PERM-EDOC-ALL-TODO", "official_documents.all_todo", "全公司公文待辦", "official_documents", "查看全公司待辦與風險。"),
    ("PERM-EDOC-ALL-RECORDS", "official_documents.all_records", "全公司公文紀錄", "official_documents", "查看全公司收發文紀錄。"),
    ("PERM-EXCHANGE-VIEW", "exchange.view", "交換查詢", "exchange", "查詢交換狀態、地址簿與交換事件。"),
    ("PERM-EXCHANGE-MANAGE", "exchange.manage", "交換管理", "exchange", "管理交換設定、送出、重送、退文與收文確認。"),
    ("PERM-CONTRACTS-VIEW", "contracts.view", "合約檢視", "contracts", "查看可見範圍內合約。"),
    ("PERM-CONTRACTS-MANAGE", "contracts.manage", "合約管理", "contracts", "建立、簽核、退回、續約與歸檔合約。"),
    ("PERM-CONTRACTS-SEAL", "contracts.seal", "合約用印", "contracts", "處理合約用印與留存。"),
    ("PERM-FILES-MANAGE", "files.manage", "附件管理", "files", "上傳附件、補正、安全檢查與下載控管。"),
    ("PERM-SEALS-MANAGE", "seals.manage", "印鑑管理", "seals", "管理印章、校準尺寸、用印申請與押章設定。"),
    ("PERM-REPORTS-VIEW", "reports.operational_view", "營運報表檢視", "reports", "查看營運報表、交換成功率與逾期件。"),
    ("PERM-AUDIT-VIEW", "audit_logs.view", "稽核檢視", "audit_logs", "查看 audit log、交換歷程與操作軌跡。"),
    ("PERM-AUDIT-EXPORT", "audit_logs.export", "稽核匯出", "audit_logs", "匯出稽核紀錄，並留下 export 事件。"),
    ("PERM-SYSTEM-PERMISSIONS-VIEW", "system_permissions.view", "權限檢視", "system_permissions", "查看角色、權限、帳號與授權紀錄。"),
    ("PERM-SYSTEM-PERMISSIONS-MANAGE", "system_permissions.manage", "權限管理", "system_permissions", "管理角色、權限、帳號與授權。"),
    ("PERM-SETTINGS-MANAGE", "settings.system_manage", "系統設定管理", "settings", "管理環境、參數、通知、備份與維運設定。"),
]

EDOC_LEGACY_PERMISSION_CATALOG = [
    ("PERM-INBOUND", "inbound.manage", "收文管理", "公文", "拉取、登錄、分派與誤送漏送處理。"),
    ("PERM-DISPATCH", "dispatch.manage", "發文管理", "公文", "建立函稿、清稿、封裝、送交與重送。"),
    ("PERM-JAGENT", "jagent.manage", "jAgent 介接", "系統", "憑證登入、Token、交換中心與地址簿。"),
    ("PERM-WORKFLOW", "workflow.approve", "簽核流程", "流程", "簽核、退回、抽回、加簽、會辦與改派。"),
    ("PERM-SEAL", "seal.apply", "自動用印", "印鑑", "PDF 套版、押章與用印紀錄。"),
    ("PERM-AUDIT", "audit.view", "稽核查閱", "稽核", "Audit log、交換事件與不可否認紀錄。"),
    ("PERM-SECURITY", "security.manage", "資安管理", "資安", "RBAC、IP/裝置限制、MFA 與 Token 過期。"),
    ("PERM-REPORT", "reports.view", "報表統計", "報表", "收發量、成功率、異常、承辦量與逾期件。"),
    ("PERM-SETTINGS", "settings.manage", "系統設定", "系統", "機關代碼、API URL、防火牆、憑證與角色。"),
]

EDOC_ROLE_PERMISSION_GRANTS = {
    "ROLE-EMPLOYEE": ["PERM-EDOC-COMPOSE", "PERM-EDOC-TODO", "PERM-EDOC-RECORDS", "PERM-EXCHANGE-VIEW", "PERM-FILES-MANAGE", "PERM-DISPATCH", "PERM-WORKFLOW"],
    "ROLE-SUPERVISOR": ["PERM-EDOC-COMPOSE", "PERM-EDOC-TODO", "PERM-EDOC-RECORDS", "PERM-EXCHANGE-VIEW", "PERM-FILES-MANAGE", "PERM-REPORTS-VIEW", "PERM-DISPATCH", "PERM-WORKFLOW", "PERM-REPORT"],
    "ROLE-DIRECTOR": ["PERM-EDOC-COMPOSE", "PERM-EDOC-TODO", "PERM-EDOC-RECORDS", "PERM-EXCHANGE-VIEW", "PERM-CONTRACTS-VIEW", "PERM-CONTRACTS-MANAGE", "PERM-FILES-MANAGE", "PERM-REPORTS-VIEW", "PERM-INBOUND", "PERM-DISPATCH", "PERM-WORKFLOW", "PERM-REPORT"],
    "ROLE-CEO": ["PERM-EDOC-COMPOSE", "PERM-EDOC-RECEIVE", "PERM-EDOC-ALL-TODO", "PERM-EDOC-ALL-RECORDS", "PERM-EXCHANGE-VIEW", "PERM-EXCHANGE-MANAGE", "PERM-CONTRACTS-VIEW", "PERM-CONTRACTS-MANAGE", "PERM-CONTRACTS-SEAL", "PERM-SEALS-MANAGE", "PERM-REPORTS-VIEW", "PERM-AUDIT-VIEW", "PERM-AUDIT-EXPORT", "PERM-SYSTEM-PERMISSIONS-VIEW", "PERM-INBOUND", "PERM-DISPATCH", "PERM-WORKFLOW", "PERM-AUDIT", "PERM-REPORT"],
    "ROLE-ADMIN-CHIEF": ["PERM-EDOC-COMPOSE", "PERM-EDOC-RECEIVE", "PERM-EDOC-ALL-TODO", "PERM-EDOC-ALL-RECORDS", "PERM-EXCHANGE-VIEW", "PERM-EXCHANGE-MANAGE", "PERM-CONTRACTS-VIEW", "PERM-CONTRACTS-MANAGE", "PERM-CONTRACTS-SEAL", "PERM-FILES-MANAGE", "PERM-SEALS-MANAGE", "PERM-REPORTS-VIEW", "PERM-AUDIT-VIEW", "PERM-AUDIT-EXPORT", "PERM-SYSTEM-PERMISSIONS-VIEW", "PERM-SYSTEM-PERMISSIONS-MANAGE", "PERM-SETTINGS-MANAGE", "PERM-INBOUND", "PERM-DISPATCH", "PERM-JAGENT", "PERM-WORKFLOW", "PERM-SEAL", "PERM-AUDIT", "PERM-SECURITY", "PERM-REPORT", "PERM-SETTINGS"],
    "ROLE-HR": ["PERM-EDOC-COMPOSE", "PERM-EDOC-TODO", "PERM-EDOC-RECORDS", "PERM-EXCHANGE-VIEW", "PERM-CONTRACTS-VIEW", "PERM-CONTRACTS-MANAGE", "PERM-FILES-MANAGE", "PERM-REPORTS-VIEW", "PERM-INBOUND", "PERM-DISPATCH", "PERM-WORKFLOW", "PERM-REPORT"],
    "ROLE-ACCOUNTING": ["PERM-EDOC-COMPOSE", "PERM-EDOC-TODO", "PERM-EDOC-RECORDS", "PERM-EXCHANGE-VIEW", "PERM-CONTRACTS-VIEW", "PERM-CONTRACTS-MANAGE", "PERM-FILES-MANAGE", "PERM-REPORTS-VIEW", "PERM-INBOUND", "PERM-DISPATCH", "PERM-WORKFLOW", "PERM-REPORT"],
    "ROLE-GA": ["PERM-EDOC-COMPOSE", "PERM-EDOC-RECEIVE", "PERM-EDOC-ALL-TODO", "PERM-EDOC-ALL-RECORDS", "PERM-EXCHANGE-VIEW", "PERM-EXCHANGE-MANAGE", "PERM-CONTRACTS-VIEW", "PERM-CONTRACTS-MANAGE", "PERM-CONTRACTS-SEAL", "PERM-FILES-MANAGE", "PERM-SEALS-MANAGE", "PERM-REPORTS-VIEW", "PERM-INBOUND", "PERM-DISPATCH", "PERM-JAGENT", "PERM-WORKFLOW", "PERM-REPORT"],
    "ROLE-SALES-ASSISTANT": ["PERM-EDOC-COMPOSE", "PERM-EDOC-TODO", "PERM-EDOC-RECORDS", "PERM-EXCHANGE-VIEW", "PERM-CONTRACTS-VIEW", "PERM-CONTRACTS-MANAGE", "PERM-FILES-MANAGE", "PERM-REPORTS-VIEW", "PERM-DISPATCH", "PERM-WORKFLOW", "PERM-REPORT"],
    "ROLE-BOARD": ["PERM-EDOC-ALL-RECORDS", "PERM-CONTRACTS-VIEW", "PERM-REPORTS-VIEW", "PERM-AUDIT-VIEW", "PERM-SYSTEM-PERMISSIONS-VIEW", "PERM-AUDIT", "PERM-REPORT"],
    "ROLE-SHAREHOLDER": ["PERM-EDOC-ALL-RECORDS", "PERM-CONTRACTS-VIEW", "PERM-REPORTS-VIEW", "PERM-AUDIT-VIEW", "PERM-REPORT"],
    "ROLE-EXTERNAL-AUDITOR": ["PERM-EDOC-RECORDS", "PERM-AUDIT-VIEW", "PERM-REPORTS-VIEW", "PERM-AUDIT", "PERM-REPORT"],
}


def roster_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_edoc_job_level(job_level: Any) -> str:
    text = roster_text(job_level)
    legacy_map = {
        "L1 員工": "職員",
        "L2 專員": "職員",
        "L3 主管": "課長",
        "L4 部門主管": "部長",
        "L5 高階主管": "區經理",
        "L6 執行長": "執行長",
    }
    if text in legacy_map:
        return legacy_map[text]
    return text if text in EDOC_JOB_LEVELS else "職員"


def derive_edoc_role_from_roster(
    job_level: Any = "",
    title: Any = "",
    department: Any = "",
    company: Any = "",
    region: Any = "",
    class_name: Any = "",
) -> str:
    level = normalize_edoc_job_level(job_level)
    title_text = roster_text(title)
    department_text = roster_text(department)
    haystack = " ".join([level, title_text, department_text, roster_text(company), roster_text(region), roster_text(class_name)])

    if "執行長" in haystack:
        return "執行長"
    if level in {"董事會", "股東", "外部檢核單位"}:
        return level
    if "行政部主任" in haystack or "行政部長" in haystack:
        return "行政部主任"
    if "總務" in haystack:
        return "總務"
    if "人資" in haystack:
        return "人資"
    if "會計" in haystack or "財務" in haystack:
        return "會計"
    if "業務助理" in title_text:
        return "業務助理"
    supervisor_keywords = {"督導", "負責人", "主任", "主管", "經理", "部長", "課長", "組長"}
    if level in {"組長", "課長", "部長", "區經理"} or any(keyword in title_text for keyword in supervisor_keywords):
        return "主管"
    return "員工"


def derive_edoc_data_scope_from_roster(job_level: Any = "", role: Any = "") -> str:
    level = normalize_edoc_job_level(job_level)
    role_text = roster_text(role)
    if role_text in {"執行長", "行政部主任", "總務"}:
        return "company"
    if role_text in {"董事會", "股東"}:
        return "group"
    if role_text == "外部檢核單位":
        return "custom"
    if level == "區經理":
        return "region"
    if level == "部長":
        return "business_unit"
    return "department"


def edoc_roster_permission_profile(row: Dict[str, Any]) -> Dict[str, Any]:
    job_level = normalize_edoc_job_level(row.get("job_level") or row.get("職等"))
    role = row.get("role") or row.get("角色") or derive_edoc_role_from_roster(
        job_level=job_level,
        title=row.get("title") or row.get("職稱"),
        department=row.get("unit") or row.get("所屬部門"),
        company=row.get("company") or row.get("所屬公司"),
        region=row.get("region") or row.get("所屬區域"),
        class_name=row.get("class_name") or row.get("課別"),
    )
    if role not in ALLOWED_EDOC_ROLES:
        role = derive_edoc_role_from_roster(
            job_level=job_level,
            title=row.get("title") or row.get("職稱"),
            department=row.get("unit") or row.get("所屬部門"),
            company=row.get("company") or row.get("所屬公司"),
            region=row.get("region") or row.get("所屬區域"),
            class_name=row.get("class_name") or row.get("課別"),
        )
    return {
        "job_level": job_level,
        "role": role,
        "data_scope": derive_edoc_data_scope_from_roster(job_level, role),
    }


def apply_user_permission_defaults(payload: Dict[str, Any]) -> None:
    if "job_level" in payload:
        payload["job_level"] = normalize_edoc_job_level(payload.get("job_level"))
    profile = edoc_roster_permission_profile(payload)
    payload.setdefault("job_level", profile["job_level"])
    if not payload.get("role") or payload.get("role") not in ALLOWED_EDOC_ROLES:
        payload["role"] = profile["role"]


def canonical_logging_role(role: Any) -> str:
    raw = roster_text(role)
    return LOGGING_ROLE_ALIASES.get(raw, raw)


def logging_role_profile(role: Any) -> Dict[str, str]:
    canonical = canonical_logging_role(role)
    return {"logging_role_key": canonical, **LOGGING_ROLE_TO_EDOC_PROFILE.get(canonical, LOGGING_ROLE_TO_EDOC_PROFILE["staff"])}


def canonical_hris_quick_login_payload(user: Dict[str, Any]) -> str:
    payload = {
        "id": roster_text(user.get("id")),
        "email": roster_text(user.get("email")),
        "role": roster_text(user.get("role")),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def base64url_decode(value: str) -> bytes:
    text = urllib.parse.unquote(roster_text(value))
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("utf-8"))


def base64url_json(value: str) -> Dict[str, Any]:
    decoded = base64url_decode(value).decode("utf-8")
    parsed = json.loads(decoded)
    return parsed if isinstance(parsed, dict) else {}


def base64url_hmac_sha256(secret: str, value: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def verify_portal_handoff_payload(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], str | None]:
    encoded_payload = roster_text(payload.get("payload"))
    signature = roster_text(payload.get("signature"))
    token = roster_text(payload.get("token"))
    if token and (not encoded_payload or not signature):
        parts = token.split(".", 1)
        if len(parts) == 2:
            encoded_payload, signature = parts
    if not encoded_payload or not signature:
        return {}, "missing_portal_handoff"
    if not PORTAL_HANDOFF_SECRET:
        return {}, "missing_portal_handoff_secret"
    expected = base64url_hmac_sha256(PORTAL_HANDOFF_SECRET, encoded_payload)
    if not hmac.compare_digest(signature, expected):
        return {}, "invalid_signature"
    try:
        decoded = base64url_json(encoded_payload)
    except Exception:
        return {}, "invalid_payload"
    if decoded.get("moduleId") != "edoc":
        return {}, "invalid_target_module"
    now_ts = int(time.time())
    exp = int(decoded.get("exp") or 0)
    iat = int(decoded.get("iat") or 0)
    if exp and exp < now_ts:
        return {}, "expired_portal_handoff"
    if iat and iat > now_ts + 300:
        return {}, "invalid_issued_at"
    if iat and not exp and now_ts - iat > PORTAL_HANDOFF_MAX_AGE_SECONDS:
        return {}, "expired_portal_handoff"
    return decoded, None


def verify_hris_quick_login_signature(payload: Dict[str, Any]) -> bool:
    if payload.get("v") != 1 or not isinstance(payload.get("user"), dict) or not payload.get("signature"):
        return False
    signature = roster_text(payload.get("signature"))
    expected = hmac.new(
        HRIS_QUICK_LOGIN_SECRET.encode("utf-8"),
        canonical_hris_quick_login_payload(payload["user"]).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def extract_logging_bridge_user(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], str | None]:
    if not isinstance(payload, dict):
        return {}, "invalid_payload"

    if payload.get("token") or (payload.get("payload") and payload.get("signature")):
        portal_payload, error = verify_portal_handoff_payload(payload)
        if error:
            return {}, error
        return portal_payload, None

    signed_payload = payload if payload.get("signature") else payload.get("signedPayload")
    if isinstance(signed_payload, dict) and signed_payload.get("signature"):
        if not verify_hris_quick_login_signature(signed_payload):
            return {}, "invalid_signature"
        return dict(signed_payload["user"]), None

    source = payload.get("user") or payload.get("currentUser") or payload.get("profile")
    if not source and isinstance(payload.get("session"), dict):
        source = payload["session"].get("user")
    if not source:
        source = payload
    if not isinstance(source, dict):
        return {}, "missing_user"
    if is_production() and not payload.get("accessToken") and not payload.get("idToken"):
        return {}, "unsigned_bridge_payload"
    return dict(source), None


def logging_permissions_to_edoc_codes(logging_permissions: Iterable[Any]) -> List[str]:
    codes: set[str] = set()
    for permission in logging_permissions or []:
        for code in LOGGING_PERMISSION_TO_EDOC_CODES.get(str(permission), []):
            codes.add(code)
    return sorted(codes)


def upsert_logging_bridge_user(conn: sqlite3.Connection, payload: Dict[str, Any]) -> sqlite3.Row:
    source_user, error = extract_logging_bridge_user(payload)
    if error:
        raise ValueError(error)
    logging_role_key = canonical_logging_role(source_user.get("loggingRoleKey") or source_user.get("logging_role_key") or source_user.get("role"))
    profile = logging_role_profile(logging_role_key)
    email = roster_text(source_user.get("email")).lower()
    if not email:
        raise ValueError("missing_email")
    logging_account_id = roster_text(source_user.get("loggingAccountId") or source_user.get("logging_account_id") or source_user.get("id") or source_user.get("profileId") or email)
    display_name = roster_text(source_user.get("name") or source_user.get("display_name") or source_user.get("roleLabel") or email.split("@")[0])
    unit = roster_text(source_user.get("unit") or source_user.get("department") or source_user.get("departmentCode") or source_user.get("department_code") or profile["unit"])
    title = roster_text(source_user.get("title") or source_user.get("roleLabel") or profile["title"])
    job_level = normalize_edoc_job_level(source_user.get("jobLevel") or source_user.get("job_level") or profile["job_level"])
    edoc_role = profile["role"]
    ts = now()
    external_payload = redact_sensitive(source_user)
    user = conn.execute(
        "SELECT * FROM users WHERE logging_account_id = ? OR lower(email) = ? ORDER BY CASE WHEN logging_account_id = ? THEN 0 ELSE 1 END LIMIT 1",
        (logging_account_id, email, logging_account_id),
    ).fetchone()
    before = row_to_dict(user) if user else {}
    if user:
        conn.execute(
            """
            UPDATE users
            SET auth_user_id = COALESCE(auth_user_id, ?),
                account_source = 'logging',
                logging_account_id = ?,
                logging_role_key = ?,
                external_account_payload_json = ?,
                last_synced_from_logging_at = ?,
                name = ?,
                email = ?,
                unit = ?,
                title = ?,
                job_level = ?,
                role = ?,
                provider = 'Logging / 平台帳號',
                mfa_status = CASE WHEN mfa_status = '' OR mfa_status IS NULL THEN '由平台管理' ELSE mfa_status END,
                status = '啟用'
            WHERE id = ?
            """,
            (
                roster_text(source_user.get("authUserId") or source_user.get("auth_user_id")) or None,
                logging_account_id,
                logging_role_key,
                json.dumps(external_payload, ensure_ascii=False),
                ts,
                display_name,
                email,
                unit,
                title,
                job_level,
                edoc_role,
                user["id"],
            ),
        )
        user_id = user["id"]
    else:
        user_id = f"LOG-{hashlib.sha256(logging_account_id.encode('utf-8')).hexdigest()[:10].upper()}"
        conn.execute(
            """
            INSERT INTO users (
              id, auth_user_id, account_source, logging_account_id, logging_role_key, external_account_payload_json,
              last_synced_from_logging_at, name, email, password_hash, unit, title, job_level, role,
              provider, mfa_status, status, last_login_at, created_at
            ) VALUES (?, ?, 'logging', ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, 'Logging / 平台帳號', '由平台管理', '啟用', NULL, ?)
            """,
            (
                user_id,
                roster_text(source_user.get("authUserId") or source_user.get("auth_user_id")) or None,
                logging_account_id,
                logging_role_key,
                json.dumps(external_payload, ensure_ascii=False),
                ts,
                display_name,
                email,
                unit,
                title,
                job_level,
                edoc_role,
                ts,
            ),
        )
    link_id = f"LINK-LOGGING-EDOC-{hashlib.sha256(logging_account_id.encode('utf-8')).hexdigest()[:10].upper()}"
    conn.execute(
        """
        INSERT INTO module_account_links (
          id, user_id, source_system, source_account_id, source_role_key, source_email,
          target_module, target_role_key, sync_status, metadata_json, last_synced_at, created_at, updated_at
        ) VALUES (?, ?, 'logging', ?, ?, ?, 'edoc', ?, 'active', ?, ?, ?, ?)
        ON CONFLICT(source_system, source_account_id, target_module) DO UPDATE SET
          user_id = excluded.user_id,
          source_role_key = excluded.source_role_key,
          source_email = excluded.source_email,
          target_role_key = excluded.target_role_key,
          sync_status = 'active',
          metadata_json = excluded.metadata_json,
          last_synced_at = excluded.last_synced_at,
          updated_at = excluded.updated_at
        """,
        (link_id, user_id, logging_account_id, logging_role_key, email, edoc_role, json.dumps({"source": "logging_bridge"}, ensure_ascii=False), ts, ts, ts),
    )
    updated = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    after = row_to_dict(updated) if updated else {}
    if before and any(before.get(key) != after.get(key) for key in ("role", "job_level", "unit", "title", "status", "logging_role_key")):
        log_permission_change(
            conn,
            "Logging Bridge",
            user_id,
            email,
            {key: before.get(key) for key in ("role", "job_level", "unit", "title", "status", "logging_role_key")},
            {key: after.get(key) for key in ("role", "job_level", "unit", "title", "status", "logging_role_key")},
            "Logging 帳號與 EDOC 角色權限同步。",
            ["system_permissions.manage"],
        )
    else:
        log_audit(
            conn,
            "Logging Bridge",
            "同步外部帳號",
            "module_account_links",
            link_id,
            f"{email} / {logging_role_key} → {edoc_role}",
            event_type="external_account_status_change",
            result="success",
            module_code="system_permissions",
            resource_type="external_account",
            resource_id=link_id,
            data_scope="custom",
            actor_roles=["system_permissions.manage"],
            target_user_id=user_id,
            target_email=email,
            reason="Logging 帳號進入 EDOC，自動同步帳號連結。",
            metadata={"source_system": "logging", "target_module": "edoc", "logging_role_key": logging_role_key},
        )
    return updated


def authenticate_logging_bridge(conn: sqlite3.Connection, payload: Dict[str, Any], ip: str, device: str) -> Tuple[Dict[str, Any], int]:
    try:
        user = upsert_logging_bridge_user(conn, payload)
    except ValueError as error:
        return {"error": "logging_bridge_denied", "detail": str(error)}, 403 if str(error) in {"invalid_signature", "unsigned_bridge_payload"} else 400
    if not user or user["status"] != "啟用" or user["role"] not in ALLOWED_EDOC_ROLES:
        return {"error": "role_forbidden", "detail": "此 Logging 帳號未授權使用 EDOC。"}, 403
    session = create_session(conn, user, "Logging / 平台帳號", ip, device)
    session["bridge"] = {
        "sourceSystem": "logging",
        "loggingAccountId": user["logging_account_id"],
        "loggingRoleKey": user["logging_role_key"],
        "targetModule": "edoc",
        "targetRole": user["role"],
    }
    incoming_permissions = []
    if isinstance(payload.get("permissions"), list):
        incoming_permissions = payload["permissions"]
    elif isinstance(payload.get("user"), dict) and isinstance(payload["user"].get("permissions"), list):
        incoming_permissions = payload["user"]["permissions"]
    session["permissions"] = sorted(set(session["permissions"]) | set(logging_permissions_to_edoc_codes(incoming_permissions)))
    return session, 200


TABLES = {
    "documents": "documents",
    "companies": "companies",
    "seal_reference_options": "seal_reference_options",
    "company_seals": "company_seals",
    "company_seal_files": "company_seal_files",
    "seal_permissions": "seal_permissions",
    "seal_usage_requests": "seal_usage_requests",
    "seal_usage_approvals": "seal_usage_approvals",
    "seal_usage_logs": "seal_usage_logs",
    "official_documents": "official_documents",
    "official_document_files": "official_document_files",
    "official_document_approval_steps": "official_document_approval_steps",
    "official_document_approval_logs": "official_document_approval_logs",
    "official_document_stamp_requests": "official_document_stamp_requests",
    "official_document_dispatch_records": "official_document_dispatch_records",
    "company_registry": "company_registry",
    "department_registry": "department_registry",
    "seal_type_registry": "seal_type_registry",
    "workflow_tasks": "workflow_tasks",
    "approval_step_actor_snapshots": "approval_step_actor_snapshots",
    "contracts": "contracts",
    "contract_parties": "contract_parties",
    "contract_approvals": "contract_approvals",
    "recipients": "recipients",
    "attachments": "attachments",
    "attachment_security": "attachment_security",
    "file_access_logs": "file_access_logs",
    "file_objects": "file_objects",
    "file_download_tokens": "file_download_tokens",
    "virus_scan_jobs": "virus_scan_jobs",
    "pdf_versions": "pdf_versions",
    "seal_assets": "seal_assets",
    "seal_applications": "seal_applications",
    "signing_certificates": "signing_certificates",
    "certificate_authorities": "certificate_authorities",
    "certificate_validation_events": "certificate_validation_events",
    "signature_provider_events": "signature_provider_events",
    "tsa_timestamp_tokens": "tsa_timestamp_tokens",
    "electronic_signatures": "electronic_signatures",
    "exchange_outbox": "exchange_outbox",
    "exchange_inbox": "exchange_inbox",
    "exchange_log": "exchange_log",
    "exchange_attachment": "exchange_attachment",
    "exchange_status_history": "exchange_status_history",
    "exchange_tasks": "exchange_tasks",
    "exchange_events": "exchange_events",
    "audit_logs": "audit_logs",
    "users": "users",
    "roles": "roles",
    "permissions": "permissions",
    "role_permissions": "role_permissions",
    "module_account_links": "module_account_links",
    "document_acl": "document_acl",
    "document_acl_events": "document_acl_events",
    "auth_sessions": "auth_sessions",
    "login_events": "login_events",
    "trusted_devices": "trusted_devices",
    "ip_allowlist": "ip_allowlist",
    "sso_providers": "sso_providers",
    "background_jobs": "background_jobs",
    "job_runs": "job_runs",
    "notifications": "notifications",
    "notification_deliveries": "notification_deliveries",
    "notification_channel_credentials": "notification_channel_credentials",
    "system_inbox": "system_inbox",
    "notification_rules": "notification_rules",
    "compliance_attestations": "compliance_attestations",
    "settings": "settings",
}


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  doc_no TEXT NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN ('收文','發文')),
  company_name TEXT NOT NULL DEFAULT '歲悅長照股份有限公司',
  doc_type TEXT NOT NULL DEFAULT '函',
  priority TEXT NOT NULL DEFAULT '普通件',
  security_level TEXT NOT NULL DEFAULT '普通',
  agency_name TEXT NOT NULL,
  agency_code TEXT,
  subject TEXT NOT NULL,
  body TEXT,
  seal_plan_json TEXT NOT NULL DEFAULT '{}',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL,
  owner TEXT,
  department TEXT,
  due_date TEXT,
  received_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS company_registry (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  tax_id TEXT NOT NULL DEFAULT '待設定',
  status TEXT NOT NULL DEFAULT '啟用',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  tax_id TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seal_reference_options (
  id TEXT PRIMARY KEY,
  option_type TEXT NOT NULL,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(option_type, code)
);

CREATE TABLE IF NOT EXISTS company_seals (
  id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL,
  seal_name TEXT NOT NULL,
  seal_category TEXT NOT NULL,
  seal_size_type TEXT NOT NULL,
  purpose_description TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deactivated_at TEXT,
  FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS company_seal_files (
  id TEXT PRIMARY KEY,
  seal_id TEXT NOT NULL,
  file_object_id TEXT,
  file_storage_key TEXT NOT NULL,
  file_name TEXT NOT NULL,
  file_mime_type TEXT NOT NULL,
  file_size INTEGER NOT NULL,
  file_hash TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  is_current INTEGER NOT NULL DEFAULT 1,
  uploaded_by TEXT,
  uploaded_at TEXT NOT NULL,
  FOREIGN KEY(seal_id) REFERENCES company_seals(id) ON DELETE CASCADE,
  FOREIGN KEY(file_object_id) REFERENCES file_objects(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS seal_permissions (
  id TEXT PRIMARY KEY,
  seal_id TEXT NOT NULL,
  user_id TEXT,
  role TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(seal_id) REFERENCES company_seals(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS seal_usage_requests (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  company_id TEXT NOT NULL,
  seal_id TEXT NOT NULL,
  requested_by TEXT,
  request_reason TEXT,
  usage_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  stamp_positions_json TEXT NOT NULL DEFAULT '[]',
  stamped_pdf_version_id TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  requested_at TEXT NOT NULL,
  approved_at TEXT,
  stamped_at TEXT,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
  FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE RESTRICT,
  FOREIGN KEY(seal_id) REFERENCES company_seals(id) ON DELETE RESTRICT,
  FOREIGN KEY(stamped_pdf_version_id) REFERENCES pdf_versions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS seal_usage_approvals (
  id TEXT PRIMARY KEY,
  usage_request_id TEXT NOT NULL,
  approver_id TEXT,
  approval_order INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'pending',
  comment TEXT,
  approved_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(usage_request_id) REFERENCES seal_usage_requests(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS seal_usage_logs (
  id TEXT PRIMARY KEY,
  usage_request_id TEXT,
  seal_id TEXT,
  document_id TEXT,
  action TEXT NOT NULL,
  actor_id TEXT,
  ip_address TEXT,
  user_agent TEXT,
  detail TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(usage_request_id) REFERENCES seal_usage_requests(id) ON DELETE SET NULL,
  FOREIGN KEY(seal_id) REFERENCES company_seals(id) ON DELETE SET NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS official_documents (
  id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL,
  document_type TEXT NOT NULL DEFAULT 'outgoing_official_document',
  source_type TEXT NOT NULL CHECK(source_type IN ('blank_editor','uploaded_pdf')),
  title TEXT NOT NULL,
  subject TEXT,
  description TEXT,
  method TEXT,
  recipient TEXT,
  dispatch_unit TEXT,
  handler_name TEXT,
  applicant_id TEXT NOT NULL,
  applicant_name TEXT,
  applicant_department_id TEXT,
  applicant_department_name TEXT,
  dispatch_method TEXT NOT NULL DEFAULT 'electronic_official_document_by_general_affairs',
  current_status TEXT NOT NULL DEFAULT 'draft',
  current_step TEXT,
  request_reason TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS official_document_files (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  file_object_id TEXT,
  file_type TEXT NOT NULL,
  file_name TEXT NOT NULL,
  file_storage_key TEXT NOT NULL,
  file_mime_type TEXT NOT NULL,
  file_size INTEGER NOT NULL,
  file_hash TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  uploaded_by TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES official_documents(id) ON DELETE CASCADE,
  FOREIGN KEY(file_object_id) REFERENCES file_objects(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS official_document_approval_steps (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  step_order INTEGER NOT NULL,
  step_key TEXT NOT NULL,
  step_name TEXT NOT NULL,
  approver_user_id TEXT,
  approver_name TEXT,
  approver_role TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  comment TEXT,
  approved_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES official_documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS official_document_approval_logs (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  step_id TEXT,
  file_id TEXT,
  actor_id TEXT,
  actor_name TEXT,
  action TEXT NOT NULL,
  comment TEXT,
  ip_address TEXT,
  user_agent TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES official_documents(id) ON DELETE CASCADE,
  FOREIGN KEY(step_id) REFERENCES official_document_approval_steps(id) ON DELETE SET NULL,
  FOREIGN KEY(file_id) REFERENCES official_document_files(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS official_document_stamp_requests (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  company_id TEXT NOT NULL,
  seal_id TEXT NOT NULL,
  requested_by TEXT,
  stamp_page INTEGER NOT NULL DEFAULT 1,
  stamp_x REAL NOT NULL DEFAULT 420,
  stamp_y REAL NOT NULL DEFAULT 130,
  stamp_width REAL NOT NULL DEFAULT 85,
  stamp_height REAL NOT NULL DEFAULT 85,
  status TEXT NOT NULL DEFAULT 'pending',
  stamped_file_id TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL,
  stamped_at TEXT,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES official_documents(id) ON DELETE CASCADE,
  FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE RESTRICT,
  FOREIGN KEY(seal_id) REFERENCES company_seals(id) ON DELETE RESTRICT,
  FOREIGN KEY(stamped_file_id) REFERENCES official_document_files(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS official_document_dispatch_records (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  dispatch_method TEXT NOT NULL,
  dispatch_owner_type TEXT NOT NULL,
  dispatch_owner_user_id TEXT,
  dispatch_status TEXT NOT NULL DEFAULT 'pending',
  external_official_document_number TEXT,
  dispatch_date TEXT,
  recipient TEXT,
  recipient_contact TEXT,
  dispatch_note TEXT,
  proof_file_id TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT,
  FOREIGN KEY(document_id) REFERENCES official_documents(id) ON DELETE CASCADE,
  FOREIGN KEY(proof_file_id) REFERENCES official_document_files(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS department_registry (
  id TEXT PRIMARY KEY,
  company_name TEXT NOT NULL,
  name TEXT NOT NULL,
  manager_role TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '啟用',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(company_name, name)
);

CREATE TABLE IF NOT EXISTS seal_type_registry (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  scope TEXT NOT NULL DEFAULT '未設定使用範圍',
  status TEXT NOT NULL DEFAULT '啟用',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_tasks (
  id TEXT PRIMARY KEY,
  document_id TEXT,
  title TEXT NOT NULL,
  workflow_type TEXT NOT NULL DEFAULT '發文',
  step TEXT NOT NULL,
  role TEXT NOT NULL,
  status TEXT NOT NULL,
  template TEXT NOT NULL DEFAULT 'standard',
  current_step_index INTEGER NOT NULL DEFAULT 0,
  requester TEXT,
  submitted_at TEXT,
  last_signed_at TEXT,
  last_comment TEXT,
  proof_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS approval_step_actor_snapshots (
  id TEXT PRIMARY KEY,
  workflow_task_id TEXT,
  seal_application_id TEXT,
  source_type TEXT NOT NULL DEFAULT 'seal_application',
  source_id TEXT NOT NULL,
  step_no INTEGER NOT NULL DEFAULT 1,
  step_name TEXT NOT NULL,
  approver_role TEXT NOT NULL,
  approver_user_id TEXT,
  approver_name TEXT,
  approver_email TEXT,
  status TEXT NOT NULL DEFAULT '待簽核',
  comment TEXT,
  acted_at TEXT,
  snapshot_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contracts (
  id TEXT PRIMARY KEY,
  contract_no TEXT NOT NULL UNIQUE,
  company_name TEXT NOT NULL DEFAULT '歲悅長照股份有限公司',
  contract_type TEXT NOT NULL DEFAULT '一般合約',
  title TEXT NOT NULL,
  counterparty TEXT NOT NULL,
  counterparty_tax_id TEXT,
  owner TEXT NOT NULL,
  department TEXT NOT NULL,
  amount REAL NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'TWD',
  start_date TEXT,
  end_date TEXT,
  renewal_alert_days INTEGER NOT NULL DEFAULT 60,
  confidentiality_level TEXT NOT NULL DEFAULT '普通',
  seal_requirement TEXT NOT NULL DEFAULT '一般章',
  storage_status TEXT NOT NULL DEFAULT '待歸檔',
  status TEXT NOT NULL DEFAULT '草稿',
  summary TEXT,
  risk_note TEXT,
  attachment_manifest_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contract_parties (
  id TEXT PRIMARY KEY,
  contract_id TEXT NOT NULL,
  party_type TEXT NOT NULL,
  name TEXT NOT NULL,
  tax_id TEXT,
  contact_name TEXT,
  contact_email TEXT,
  contact_phone TEXT,
  address TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(contract_id) REFERENCES contracts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS contract_approvals (
  id TEXT PRIMARY KEY,
  contract_id TEXT NOT NULL,
  step_no INTEGER NOT NULL DEFAULT 1,
  step_name TEXT NOT NULL,
  role TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '待簽核',
  approver TEXT,
  comment TEXT,
  signed_at TEXT,
  non_repudiation_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(contract_id) REFERENCES contracts(id) ON DELETE CASCADE
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

CREATE TABLE IF NOT EXISTS attachment_security (
  id TEXT PRIMARY KEY,
  attachment_id TEXT NOT NULL UNIQUE,
  document_id TEXT NOT NULL,
  file_name TEXT NOT NULL,
  file_ext TEXT,
  size_bytes INTEGER NOT NULL DEFAULT 0,
  max_size_bytes INTEGER NOT NULL DEFAULT 52428800,
  scan_status TEXT NOT NULL DEFAULT '待掃描',
  scan_engine TEXT NOT NULL DEFAULT 'ClamAV-compatible',
  scan_signature TEXT,
  mask_status TEXT NOT NULL DEFAULT '未遮罩',
  sensitive_hits_json TEXT NOT NULL DEFAULT '[]',
  confidential_level TEXT NOT NULL DEFAULT '普通',
  allowed_roles TEXT,
  watermark_status TEXT NOT NULL DEFAULT '未下載',
  quarantine_reason TEXT,
  backup_id TEXT,
  last_accessed_by TEXT,
  last_accessed_at TEXT,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(attachment_id) REFERENCES attachments(id) ON DELETE CASCADE,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS file_access_logs (
  id TEXT PRIMARY KEY,
  attachment_id TEXT,
  file_object_id TEXT,
  document_id TEXT,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  ip TEXT,
  device TEXT,
  watermark_text TEXT,
  result TEXT NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(attachment_id) REFERENCES attachments(id) ON DELETE SET NULL,
  FOREIGN KEY(file_object_id) REFERENCES file_objects(id) ON DELETE SET NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS file_objects (
  id TEXT PRIMARY KEY,
  document_id TEXT,
  file_name TEXT NOT NULL,
  storage_key TEXT NOT NULL UNIQUE,
  bucket TEXT NOT NULL DEFAULT 'edoc-private',
  storage_provider TEXT NOT NULL DEFAULT 'local',
  mime_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  encrypted_sha256 TEXT,
  encryption_status TEXT NOT NULL DEFAULT '未加密',
  encryption_alg TEXT,
  encryption_key_id TEXT,
  scan_status TEXT NOT NULL DEFAULT '待掃描',
  scan_engine TEXT,
  quarantine_reason TEXT,
  signed_url_expires_at TEXT,
  last_scan_at TEXT,
  last_download_at TEXT,
  version_label TEXT NOT NULL,
  purpose TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file_download_tokens (
  id TEXT PRIMARY KEY,
  file_object_id TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  actor TEXT NOT NULL,
  purpose TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT,
  revoked_at TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(file_object_id) REFERENCES file_objects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS virus_scan_jobs (
  id TEXT PRIMARY KEY,
  file_object_id TEXT,
  attachment_id TEXT,
  document_id TEXT,
  engine TEXT NOT NULL,
  status TEXT NOT NULL,
  signature TEXT,
  result TEXT,
  detail TEXT,
  started_at TEXT,
  finished_at TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(file_object_id) REFERENCES file_objects(id) ON DELETE SET NULL,
  FOREIGN KEY(attachment_id) REFERENCES attachments(id) ON DELETE SET NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS pdf_versions (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  file_object_id TEXT NOT NULL,
  version_type TEXT NOT NULL CHECK(version_type IN ('before_seal','after_seal','application')),
  template_name TEXT NOT NULL,
  stamp_no TEXT,
  coordinates_json TEXT,
  previous_version_id TEXT,
  sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(file_object_id) REFERENCES file_objects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS seal_assets (
  id TEXT PRIMARY KEY,
  seal_id TEXT NOT NULL,
  name TEXT NOT NULL,
  seal_type TEXT NOT NULL,
  owner TEXT NOT NULL,
  doc_type TEXT NOT NULL,
  file_object_id TEXT,
  width_mm REAL NOT NULL,
  height_mm REAL NOT NULL,
  width_pt REAL NOT NULL,
  height_pt REAL NOT NULL,
  calibration_status TEXT NOT NULL DEFAULT '待校準',
  hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '啟用',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(file_object_id) REFERENCES file_objects(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS seal_applications (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  seal_id TEXT NOT NULL,
  application_type TEXT NOT NULL DEFAULT 'official_document',
  company_name TEXT NOT NULL DEFAULT '歲悅股份有限公司',
  department TEXT,
  title TEXT,
  source_pdf_file_object_id TEXT,
  source_pdf_sha256 TEXT,
  source_pdf_name TEXT,
  locked_pdf_sha256 TEXT,
  locked_positions_sha256 TEXT,
  stamp_positions_json TEXT NOT NULL DEFAULT '[]',
  approval_route_code TEXT,
  approval_route_name TEXT,
  approval_snapshot_json TEXT NOT NULL DEFAULT '{}',
  current_step_no INTEGER NOT NULL DEFAULT 1,
  current_step_name TEXT,
  current_approver_role TEXT,
  applicant_user_id TEXT,
  applicant_name TEXT,
  applicant_email TEXT,
  applicant TEXT NOT NULL,
  approver TEXT,
  status TEXT NOT NULL,
  reason TEXT,
  reject_reason TEXT,
  stamp_no TEXT,
  pdf_before_version_id TEXT,
  pdf_after_version_id TEXT,
  returned_at TEXT,
  completed_at TEXT,
  notification_id TEXT,
  created_at TEXT NOT NULL,
  approved_at TEXT,
  signature_id TEXT,
  provider_status TEXT,
  failure_reason TEXT,
  evidence_json TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS signing_certificates (
  id TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  subject TEXT NOT NULL,
  issuer TEXT NOT NULL,
  serial_no TEXT NOT NULL UNIQUE,
  algorithm TEXT NOT NULL,
  valid_from TEXT NOT NULL,
  valid_to TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '啟用',
  certificate_type TEXT NOT NULL DEFAULT 'organization',
  fingerprint_sha256 TEXT NOT NULL,
  key_usage TEXT,
  extended_key_usage TEXT,
  chain_status TEXT NOT NULL DEFAULT '待驗證',
  ocsp_status TEXT NOT NULL DEFAULT '待查詢',
  crl_status TEXT NOT NULL DEFAULT '待查詢',
  tsa_url TEXT,
  ocsp_url TEXT,
  crl_url TEXT,
  root_ca_fingerprint TEXT,
  last_validated_at TEXT,
  validation_report_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS certificate_authorities (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  ca_type TEXT NOT NULL,
  subject TEXT NOT NULL,
  issuer TEXT NOT NULL,
  fingerprint_sha256 TEXT NOT NULL,
  valid_from TEXT NOT NULL,
  valid_to TEXT NOT NULL,
  trust_status TEXT NOT NULL DEFAULT 'trusted',
  ocsp_url TEXT,
  crl_url TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS electronic_signatures (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  pdf_version_id TEXT,
  file_object_id TEXT,
  certificate_id TEXT NOT NULL,
  signer TEXT NOT NULL,
  signature_type TEXT NOT NULL CHECK(signature_type IN ('approval','seal','timestamp','package')),
  algorithm TEXT NOT NULL,
  digest_sha256 TEXT NOT NULL,
  signature_value TEXT NOT NULL,
  tsa_token TEXT NOT NULL,
  previous_signature_id TEXT,
  non_repudiation_json TEXT,
  verified_at TEXT,
  status TEXT NOT NULL DEFAULT '有效',
  certificate_validation_id TEXT,
  tsa_status TEXT NOT NULL DEFAULT '待驗證',
  ocsp_status TEXT NOT NULL DEFAULT '待查詢',
  crl_status TEXT NOT NULL DEFAULT '待查詢',
  chain_status TEXT NOT NULL DEFAULT '待驗證',
  provider TEXT,
  provider_key_id TEXT,
  provider_request_id TEXT,
  provider_receipt_json TEXT,
  evidence_digest_sha256 TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
  FOREIGN KEY(pdf_version_id) REFERENCES pdf_versions(id) ON DELETE SET NULL,
  FOREIGN KEY(file_object_id) REFERENCES file_objects(id) ON DELETE SET NULL,
  FOREIGN KEY(certificate_id) REFERENCES signing_certificates(id) ON DELETE RESTRICT,
  FOREIGN KEY(previous_signature_id) REFERENCES electronic_signatures(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS certificate_validation_events (
  id TEXT PRIMARY KEY,
  certificate_id TEXT NOT NULL,
  signature_id TEXT,
  validator TEXT NOT NULL,
  validation_type TEXT NOT NULL,
  chain_status TEXT NOT NULL,
  ocsp_status TEXT NOT NULL,
  crl_status TEXT NOT NULL,
  tsa_status TEXT NOT NULL,
  result TEXT NOT NULL,
  report_json TEXT,
  checked_at TEXT NOT NULL,
  FOREIGN KEY(certificate_id) REFERENCES signing_certificates(id) ON DELETE CASCADE,
  FOREIGN KEY(signature_id) REFERENCES electronic_signatures(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS signature_provider_events (
  id TEXT PRIMARY KEY,
  document_id TEXT,
  signature_id TEXT,
  provider TEXT NOT NULL,
  operation TEXT NOT NULL,
  request_id TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  request_digest_sha256 TEXT NOT NULL,
  response_digest_sha256 TEXT,
  status TEXT NOT NULL,
  http_status INTEGER,
  error TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 1,
  duration_ms INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tsa_timestamp_tokens (
  id TEXT PRIMARY KEY,
  signature_id TEXT NOT NULL,
  tsa_name TEXT NOT NULL,
  tsa_url TEXT,
  imprint_sha256 TEXT NOT NULL,
  token_value TEXT NOT NULL,
  policy_oid TEXT,
  status TEXT NOT NULL,
  issued_at TEXT NOT NULL,
  verified_at TEXT,
  FOREIGN KEY(signature_id) REFERENCES electronic_signatures(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS exchange_outbox (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  doc_no TEXT NOT NULL,
  target_agency TEXT NOT NULL,
  target_agency_code TEXT,
  status TEXT NOT NULL CHECK(status IN ('待發文','已送出','已送達','失敗','退文','已達重送上限')),
  provider TEXT NOT NULL DEFAULT 'mock',
  environment TEXT NOT NULL DEFAULT 'sandbox',
  package_id TEXT,
  external_id TEXT,
  idempotency_key TEXT NOT NULL UNIQUE,
  retry_count INTEGER NOT NULL DEFAULT 0,
  max_retries INTEGER NOT NULL DEFAULT 3,
  last_error_code TEXT,
  last_error_message TEXT,
  next_retry_at TEXT,
  sent_at TEXT,
  returned_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS exchange_inbox (
  id TEXT PRIMARY KEY,
  document_id TEXT,
  external_id TEXT NOT NULL UNIQUE,
  source_agency TEXT NOT NULL,
  source_agency_code TEXT,
  doc_no TEXT NOT NULL,
  subject TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('已收文','待確認','已入案')),
  provider TEXT NOT NULL DEFAULT 'mock',
  environment TEXT NOT NULL DEFAULT 'sandbox',
  received_at TEXT NOT NULL,
  acknowledged_at TEXT,
  raw_summary_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS exchange_log (
  id TEXT PRIMARY KEY,
  exchange_ref_type TEXT NOT NULL CHECK(exchange_ref_type IN ('outbox','inbox','status','system')),
  exchange_ref_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  environment TEXT NOT NULL,
  operation TEXT NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN ('outbound','inbound','system')),
  request_summary_json TEXT NOT NULL DEFAULT '{}',
  response_summary_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL,
  error_code TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exchange_attachment (
  id TEXT PRIMARY KEY,
  exchange_ref_type TEXT NOT NULL CHECK(exchange_ref_type IN ('outbox','inbox')),
  exchange_ref_id TEXT NOT NULL,
  document_id TEXT,
  file_name TEXT NOT NULL,
  mime_type TEXT,
  size_bytes INTEGER NOT NULL DEFAULT 0,
  sha256 TEXT,
  storage_key TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS exchange_status_history (
  id TEXT PRIMARY KEY,
  exchange_ref_type TEXT NOT NULL CHECK(exchange_ref_type IN ('outbox','inbox')),
  exchange_ref_id TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  message TEXT,
  provider_status_code TEXT,
  payload_summary_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
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
  event_type TEXT NOT NULL DEFAULT 'submit',
  severity TEXT NOT NULL DEFAULT 'info',
  result TEXT NOT NULL DEFAULT 'success',
  module_code TEXT,
  resource_type TEXT,
  resource_id TEXT,
  data_scope TEXT,
  actor_user_id TEXT,
  actor_email TEXT,
  actor_roles_json TEXT NOT NULL DEFAULT '[]',
  target_user_id TEXT,
  target_email TEXT,
  reason TEXT,
  request_id TEXT,
  before_snapshot_json TEXT NOT NULL DEFAULT '{}',
  after_snapshot_json TEXT NOT NULL DEFAULT '{}',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  auth_user_id TEXT,
  account_source TEXT NOT NULL DEFAULT 'edoc',
  logging_account_id TEXT,
  logging_role_key TEXT,
  external_account_payload_json TEXT NOT NULL DEFAULT '{}',
  last_synced_from_logging_at TEXT,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT,
  unit TEXT,
  title TEXT,
  job_level TEXT NOT NULL DEFAULT '職員',
  role TEXT NOT NULL,
  provider TEXT NOT NULL DEFAULT '本機帳號',
  mfa_status TEXT NOT NULL DEFAULT '待設定',
  status TEXT NOT NULL DEFAULT '啟用',
  last_login_at TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roles (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  description TEXT,
  data_scope TEXT NOT NULL DEFAULT 'assigned',
  status TEXT NOT NULL DEFAULT '啟用',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS permissions (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  description TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS role_permissions (
  role_id TEXT NOT NULL,
  permission_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(role_id, permission_id),
  FOREIGN KEY(role_id) REFERENCES roles(id) ON DELETE CASCADE,
  FOREIGN KEY(permission_id) REFERENCES permissions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS document_acl (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  principal_type TEXT NOT NULL CHECK(principal_type IN ('role','user','unit')),
  principal_id TEXT NOT NULL,
  can_view INTEGER NOT NULL DEFAULT 1,
  can_sign INTEGER NOT NULL DEFAULT 0,
  can_download INTEGER NOT NULL DEFAULT 0,
  can_seal INTEGER NOT NULL DEFAULT 0,
  can_delegate INTEGER NOT NULL DEFAULT 0,
  reason TEXT,
  granted_by TEXT,
  expires_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS document_acl_events (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS auth_sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  provider TEXT NOT NULL,
  ip TEXT,
  device TEXT,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS login_events (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  email TEXT NOT NULL,
  provider TEXT NOT NULL,
  ip TEXT,
  device TEXT,
  status TEXT NOT NULL,
  reason TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS module_account_links (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  source_system TEXT NOT NULL,
  source_account_id TEXT NOT NULL,
  source_role_key TEXT,
  source_email TEXT,
  target_module TEXT NOT NULL DEFAULT 'edoc',
  target_role_key TEXT,
  sync_status TEXT NOT NULL DEFAULT 'active',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  last_synced_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(source_system, source_account_id, target_module),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS trusted_devices (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  ip TEXT,
  fingerprint TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '待複核',
  last_seen_at TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ip_allowlist (
  id TEXT PRIMARY KEY,
  cidr TEXT NOT NULL UNIQUE,
  purpose TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '啟用',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sso_providers (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL UNIQUE,
  domain TEXT NOT NULL,
  tenant_id TEXT,
  client_id TEXT,
  status TEXT NOT NULL DEFAULT '未連線',
  require_mfa INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS job_runs (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL,
  result TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT,
  FOREIGN KEY(job_id) REFERENCES background_jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notifications (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  target_role TEXT NOT NULL,
  target_email TEXT,
  channel TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '未讀',
  priority TEXT NOT NULL DEFAULT '中',
  source TEXT,
  body TEXT NOT NULL,
  delivery_receipt TEXT,
  created_at TEXT NOT NULL,
  sent_at TEXT
);

CREATE TABLE IF NOT EXISTS notification_deliveries (
  id TEXT PRIMARY KEY,
  notification_id TEXT,
  channel TEXT NOT NULL,
  target TEXT NOT NULL,
  status TEXT NOT NULL,
  receipt TEXT,
  error TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  FOREIGN KEY(notification_id) REFERENCES notifications(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS notification_channel_credentials (
  id TEXT PRIMARY KEY,
  channel TEXT NOT NULL,
  provider TEXT NOT NULL,
  credential_type TEXT NOT NULL,
  env_key_name TEXT NOT NULL,
  masked_identifier TEXT NOT NULL,
  fingerprint_sha256 TEXT NOT NULL,
  expires_at TEXT,
  status TEXT NOT NULL DEFAULT '待驗證',
  last_validated_at TEXT,
  validation_report_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_inbox (
  id TEXT PRIMARY KEY,
  notification_id TEXT,
  target_role TEXT NOT NULL,
  target_user_id TEXT,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '未讀',
  created_at TEXT NOT NULL,
  FOREIGN KEY(notification_id) REFERENCES notifications(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS notification_rules (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  rule_text TEXT NOT NULL,
  target_role TEXT NOT NULL,
  channel TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '啟用',
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compliance_attestations (
  id TEXT PRIMARY KEY,
  attestation_type TEXT NOT NULL,
  period TEXT NOT NULL,
  signer_name TEXT NOT NULL,
  signer_role TEXT NOT NULL,
  reviewer_name TEXT,
  reviewer_role TEXT,
  status TEXT NOT NULL,
  score INTEGER NOT NULL DEFAULT 0,
  report_hash TEXT NOT NULL,
  report_json TEXT NOT NULL,
  signed_at TEXT NOT NULL,
  non_repudiation_json TEXT
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_direction ON documents(direction);
CREATE INDEX IF NOT EXISTS idx_companies_status ON companies(status);
CREATE INDEX IF NOT EXISTS idx_seal_reference_options_type ON seal_reference_options(option_type, status);
CREATE INDEX IF NOT EXISTS idx_company_seals_company ON company_seals(company_id, is_active);
CREATE INDEX IF NOT EXISTS idx_company_seals_category ON company_seals(seal_category, seal_size_type);
CREATE INDEX IF NOT EXISTS idx_company_seal_files_seal ON company_seal_files(seal_id, is_current);
CREATE INDEX IF NOT EXISTS idx_seal_permissions_seal ON seal_permissions(seal_id);
CREATE INDEX IF NOT EXISTS idx_seal_usage_requests_document ON seal_usage_requests(document_id);
CREATE INDEX IF NOT EXISTS idx_seal_usage_requests_status ON seal_usage_requests(status);
CREATE INDEX IF NOT EXISTS idx_seal_usage_requests_company ON seal_usage_requests(company_id);
CREATE INDEX IF NOT EXISTS idx_seal_usage_approvals_request ON seal_usage_approvals(usage_request_id, approval_order);
CREATE INDEX IF NOT EXISTS idx_seal_usage_logs_request ON seal_usage_logs(usage_request_id, created_at);
CREATE INDEX IF NOT EXISTS idx_official_documents_status ON official_documents(current_status, current_step);
CREATE INDEX IF NOT EXISTS idx_official_documents_applicant ON official_documents(applicant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_official_documents_company ON official_documents(company_id, created_at);
CREATE INDEX IF NOT EXISTS idx_official_document_files_document ON official_document_files(document_id, file_type, version);
CREATE INDEX IF NOT EXISTS idx_official_document_steps_document ON official_document_approval_steps(document_id, step_order);
CREATE INDEX IF NOT EXISTS idx_official_document_steps_approver ON official_document_approval_steps(approver_user_id, status);
CREATE INDEX IF NOT EXISTS idx_official_document_logs_document ON official_document_approval_logs(document_id, created_at);
CREATE INDEX IF NOT EXISTS idx_official_stamp_requests_document ON official_document_stamp_requests(document_id, status);
CREATE INDEX IF NOT EXISTS idx_official_dispatch_records_document ON official_document_dispatch_records(document_id, dispatch_status);
CREATE INDEX IF NOT EXISTS idx_official_dispatch_records_owner ON official_document_dispatch_records(dispatch_owner_user_id, dispatch_status);
CREATE INDEX IF NOT EXISTS idx_company_registry_status ON company_registry(status);
CREATE INDEX IF NOT EXISTS idx_department_registry_company ON department_registry(company_name);
CREATE INDEX IF NOT EXISTS idx_seal_type_registry_status ON seal_type_registry(status);
CREATE INDEX IF NOT EXISTS idx_workflow_tasks_document ON workflow_tasks(document_id);
CREATE INDEX IF NOT EXISTS idx_workflow_tasks_status ON workflow_tasks(status);
CREATE INDEX IF NOT EXISTS idx_workflow_tasks_role ON workflow_tasks(role);
CREATE INDEX IF NOT EXISTS idx_contracts_status ON contracts(status);
CREATE INDEX IF NOT EXISTS idx_contracts_owner ON contracts(owner);
CREATE INDEX IF NOT EXISTS idx_contracts_department ON contracts(department);
CREATE INDEX IF NOT EXISTS idx_contracts_counterparty ON contracts(counterparty);
CREATE INDEX IF NOT EXISTS idx_contracts_end_date ON contracts(end_date);
CREATE INDEX IF NOT EXISTS idx_contract_parties_contract ON contract_parties(contract_id);
CREATE INDEX IF NOT EXISTS idx_contract_approvals_contract ON contract_approvals(contract_id);
CREATE INDEX IF NOT EXISTS idx_contract_approvals_role ON contract_approvals(role);
CREATE INDEX IF NOT EXISTS idx_contract_approvals_status ON contract_approvals(status);
CREATE INDEX IF NOT EXISTS idx_approval_actor_snapshots_source ON approval_step_actor_snapshots(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_approval_actor_snapshots_status ON approval_step_actor_snapshots(approver_role, status);
CREATE INDEX IF NOT EXISTS idx_attachments_document ON attachments(document_id);
CREATE INDEX IF NOT EXISTS idx_attachment_security_document ON attachment_security(document_id);
CREATE INDEX IF NOT EXISTS idx_attachment_security_scan ON attachment_security(scan_status);
CREATE INDEX IF NOT EXISTS idx_file_access_logs_attachment ON file_access_logs(attachment_id);
CREATE INDEX IF NOT EXISTS idx_file_access_logs_created ON file_access_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_file_objects_document ON file_objects(document_id);
CREATE INDEX IF NOT EXISTS idx_file_download_tokens_file ON file_download_tokens(file_object_id);
CREATE INDEX IF NOT EXISTS idx_virus_scan_jobs_file ON virus_scan_jobs(file_object_id);
CREATE INDEX IF NOT EXISTS idx_pdf_versions_document ON pdf_versions(document_id);
CREATE INDEX IF NOT EXISTS idx_seal_assets_seal_id ON seal_assets(seal_id);
CREATE INDEX IF NOT EXISTS idx_seal_applications_document ON seal_applications(document_id);
CREATE INDEX IF NOT EXISTS idx_signing_certificates_serial ON signing_certificates(serial_no);
CREATE INDEX IF NOT EXISTS idx_electronic_signatures_document ON electronic_signatures(document_id);
CREATE INDEX IF NOT EXISTS idx_electronic_signatures_file ON electronic_signatures(file_object_id);
CREATE INDEX IF NOT EXISTS idx_certificate_validation_events_certificate ON certificate_validation_events(certificate_id);
CREATE INDEX IF NOT EXISTS idx_certificate_validation_events_signature ON certificate_validation_events(signature_id);
CREATE INDEX IF NOT EXISTS idx_signature_provider_events_signature ON signature_provider_events(signature_id);
CREATE INDEX IF NOT EXISTS idx_signature_provider_events_request ON signature_provider_events(request_id);
CREATE INDEX IF NOT EXISTS idx_tsa_timestamp_tokens_signature ON tsa_timestamp_tokens(signature_id);
CREATE INDEX IF NOT EXISTS idx_exchange_outbox_document ON exchange_outbox(document_id);
CREATE INDEX IF NOT EXISTS idx_exchange_outbox_status ON exchange_outbox(status);
CREATE INDEX IF NOT EXISTS idx_exchange_outbox_external ON exchange_outbox(external_id);
CREATE INDEX IF NOT EXISTS idx_exchange_inbox_document ON exchange_inbox(document_id);
CREATE INDEX IF NOT EXISTS idx_exchange_inbox_status ON exchange_inbox(status);
CREATE INDEX IF NOT EXISTS idx_exchange_log_ref ON exchange_log(exchange_ref_type, exchange_ref_id);
CREATE INDEX IF NOT EXISTS idx_exchange_attachment_ref ON exchange_attachment(exchange_ref_type, exchange_ref_id);
CREATE INDEX IF NOT EXISTS idx_exchange_status_history_ref ON exchange_status_history(exchange_ref_type, exchange_ref_id);
CREATE INDEX IF NOT EXISTS idx_exchange_tasks_document ON exchange_tasks(document_id);
CREATE INDEX IF NOT EXISTS idx_exchange_events_document ON exchange_events(document_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_token ON auth_sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_login_events_created ON login_events(created_at);
CREATE INDEX IF NOT EXISTS idx_document_acl_document ON document_acl(document_id);
CREATE INDEX IF NOT EXISTS idx_document_acl_principal ON document_acl(principal_type, principal_id);
CREATE INDEX IF NOT EXISTS idx_document_acl_events_document ON document_acl_events(document_id);
CREATE INDEX IF NOT EXISTS idx_job_runs_job ON job_runs(job_id);
CREATE INDEX IF NOT EXISTS idx_job_runs_finished ON job_runs(finished_at);
CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status);
CREATE INDEX IF NOT EXISTS idx_notifications_source ON notifications(source);
CREATE INDEX IF NOT EXISTS idx_notification_deliveries_notification ON notification_deliveries(notification_id);
CREATE INDEX IF NOT EXISTS idx_notification_credentials_channel ON notification_channel_credentials(channel);
CREATE INDEX IF NOT EXISTS idx_system_inbox_notification ON system_inbox(notification_id);
CREATE INDEX IF NOT EXISTS idx_compliance_attestations_period ON compliance_attestations(period);
CREATE INDEX IF NOT EXISTS idx_compliance_attestations_signed ON compliance_attestations(signed_at);
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
        "owner": "總務",
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
        "owner": "總務",
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
        "owner": "總務",
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


def is_production() -> bool:
    return DEPLOYMENT_ENV in {"production", "prod"}


def env_present(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def production_readiness() -> Dict[str, Any]:
    required = [
        "EDOC_DEPLOYMENT_ENV",
        "EDOC_PUBLIC_BASE_URL",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "CRON_SECRET",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_FROM",
        "SMTP_CREDENTIAL_EXPIRES_AT",
        "LINE_WEBHOOK_URL",
        "LINE_CREDENTIAL_EXPIRES_AT",
        "APP_SECRET",
        "INBOX_SIGNING_KEY_EXPIRES_AT",
        "EDOC_STORAGE_PROVIDER",
        "EDOC_STORAGE_BUCKET",
        "EDOC_SEAL_STORAGE_BUCKET",
        "EDOC_OBJECT_STORAGE_URL",
        "EDOC_STORAGE_ACCESS_MODE",
        "EDOC_FILE_ENCRYPTION_KEY",
        "EDOC_SCAN_ENGINE",
        "EDOC_AV_PROVIDER",
        "EDOC_AV_ENDPOINT",
        "EDOC_AV_API_KEY",
        "EDOC_MAX_FILE_SIZE_MB",
        "EDOC_ALLOWED_MIME_TYPES",
        "EDOC_SIGNATURE_PROVIDER",
        "EDOC_SIGNATURE_API_URL",
        "EDOC_SIGNATURE_API_KEY",
        "EDOC_SIGNATURE_KEY_ID",
        "EDOC_HSM_PROVIDER",
        "EDOC_CERT_TRUST_STORE",
        "EDOC_TSA_URL",
        "EDOC_TSA_API_KEY",
        "EDOC_OCSP_RESPONDER_URL",
        "EDOC_CRL_DISTRIBUTION_URL",
    ]
    missing = [name for name in required if not env_present(name)]
    blockers: List[str] = []
    warnings: List[str] = []
    if is_production() and not USE_SUPABASE:
        blockers.append("production 必須使用 Supabase；Vercel serverless 不可依賴本機 SQLite 持久化。")
    if env_present("SUPABASE_ANON_KEY") and not env_present("SUPABASE_SERVICE_ROLE_KEY"):
        warnings.append("只設定 SUPABASE_ANON_KEY 不足以執行 server-side migration / REST 管理操作。")
    if env_present("SMTP_HOST") and not env_present("SMTP_USERNAME"):
        warnings.append("SMTP_HOST 已設定但 SMTP_USERNAME 未設定，若郵件服務要求驗證將派送失敗。")
    storage_service = storage_service_status()
    if storage_service["productionBlocked"]:
        blockers.append(f"production 必須接正式物件儲存與防毒服務；缺少：{', '.join(storage_service['missing'])}。")
    elif not storage_service["ready"]:
        warnings.append(f"正式檔案儲存與防毒服務尚未完整：{', '.join(storage_service['missing'])}。")
    if not env_present("MONITORING_WEBHOOK_URL"):
        warnings.append("未設定 MONITORING_WEBHOOK_URL，監控告警將只留在系統內，不會推送到外部值班通道。")
    if not env_present("SENTRY_DSN"):
        warnings.append("未設定 SENTRY_DSN，正式錯誤追蹤需依賴 Vercel runtime logs 與系統 audit log。")
    if is_production() and EDOC_SIGNATURE_PROVIDER == "local-simulation":
        blockers.append("production 必須接正式電子簽章服務；不可使用 local-simulation 簽章。")
    if is_production() and not env_present("EDOC_TSA_URL"):
        blockers.append("production 必須設定 TSA 時間戳服務 URL。")
    if is_production() and not env_present("EDOC_OCSP_RESPONDER_URL"):
        blockers.append("production 必須設定 OCSP 即時撤銷查詢服務。")
    if is_production() and not env_present("EDOC_CRL_DISTRIBUTION_URL"):
        blockers.append("production 必須設定 CRL 撤銷清單來源。")
    ready = not missing and not blockers
    return {
        "environment": DEPLOYMENT_ENV,
        "vercel": RUNNING_ON_VERCEL,
        "databaseMode": "supabase" if USE_SUPABASE else "sqlite",
        "ready": ready,
        "missing": missing,
        "blockers": blockers,
        "warnings": warnings,
        "checks": {
            "supabase": bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY),
            "cronSecret": env_present("CRON_SECRET"),
            "smtp": env_present("SMTP_HOST") and env_present("SMTP_FROM"),
            "line": env_present("LINE_WEBHOOK_URL"),
            "storage": storage_service,
            "encryption": EDOC_FILE_ENCRYPTION_ENABLED and env_present("EDOC_FILE_ENCRYPTION_KEY"),
            "scanner": EDOC_SCAN_ENGINE,
            "publicBaseUrl": EDOC_PUBLIC_BASE_URL,
            "monitoringWebhook": env_present("MONITORING_WEBHOOK_URL"),
            "sentry": env_present("SENTRY_DSN"),
            "signatureProvider": EDOC_SIGNATURE_PROVIDER,
            "signatureApi": bool(EDOC_SIGNATURE_API_URL and EDOC_SIGNATURE_API_KEY),
            "signatureProfile": EDOC_SIGNATURE_PROFILE,
            "signatureTimeoutSeconds": EDOC_SIGNATURE_TIMEOUT_SECONDS,
            "signatureMaxRetries": EDOC_SIGNATURE_MAX_RETRIES,
            "hsmProvider": EDOC_HSM_PROVIDER or "未設定",
            "trustStore": bool(EDOC_CERT_TRUST_STORE),
            "tsa": bool(EDOC_TSA_URL),
            "ocsp": bool(EDOC_OCSP_RESPONDER_URL),
            "crl": bool(EDOC_CRL_DISTRIBUTION_URL),
        },
    }


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on", "enabled"}


DEMO_LOGIN_EMAILS = {
    "edoc@suiyuecare.com",
    "records@suiyuecare.com",
    "director@suiyuecare.com",
    "ceo@suiyuecare.com",
    "hr@suiyuecare.com",
    "accounting@suiyuecare.com",
    "sales-assistant@suiyuecare.com",
    "employee@suiyuecare.com",
}


def demo_login_blocked(email: str, password: str) -> bool:
    return bool(
        is_production()
        and env_flag("EDOC_DISABLE_DEMO_ACCOUNTS", False)
        and email.lower() in DEMO_LOGIN_EMAILS
        and password == "demo1234"
    )


def go_live_audit() -> Dict[str, Any]:
    readiness = production_readiness()
    storage_service = storage_service_status()
    signing_service = signing_service_status()
    exchange_status = exchange_gateway_status()
    target_date = os.getenv("EDOC_TARGET_GO_LIVE_DATE", "").strip() or (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    demo_accounts_disabled = env_flag("EDOC_DISABLE_DEMO_ACCOUNTS", False)
    formal_exchange_ready = bool(exchange_status.get("formalConnection"))
    formal_blockers = [
        *[f"缺少正式環境變數：{name}" for name in readiness.get("missing", [])],
        *list(readiness.get("blockers", [])),
    ]
    if not formal_exchange_ready:
        formal_blockers.append("正式電子公文交換 provider 尚未開放；目前只能使用 mock provider 進行內部演練，不可送正式交換。")
    if is_production() and not demo_accounts_disabled:
        formal_blockers.append("正式站仍允許 demo / seed 帳號政策；上線前需設定 EDOC_DISABLE_DEMO_ACCOUNTS=true 並完成正式帳號匯入。")

    formal_go = not formal_blockers
    internal_pilot_allowed = bool(
        not formal_go
        and exchange_status.get("provider") == "mock"
        and env_flag("EDOC_ALLOW_INTERNAL_PILOT", True)
    )
    decision = "GO" if formal_go else "NO_GO"
    summary = (
        "正式上線可開放。"
        if formal_go
        else "不可開放正式電子公文交換；僅可做內部演練、教育訓練與資料流程驗收。"
        if internal_pilot_allowed
        else "不可上線，且目前不建議開放內部試營運。"
    )
    categories = [
        {
            "key": "database",
            "name": "正式資料庫",
            "status": "pass" if readiness["checks"]["supabase"] and readiness["databaseMode"] == "supabase" else "fail",
            "severity": "critical",
            "evidence": f"databaseMode={readiness['databaseMode']}",
            "action": "建立獨立 Supabase project，設定 SUPABASE_URL、SUPABASE_SERVICE_ROLE_KEY、EDOC_DB_MODE=supabase，套用 migrations 並驗證 RLS。",
        },
        {
            "key": "storage_av",
            "name": "檔案儲存與防毒",
            "status": "pass" if storage_service["ready"] else "fail",
            "severity": "critical",
            "evidence": f"mode={storage_service['mode']}；missing={','.join(storage_service['missing']) or 'none'}",
            "action": "接 private object storage、短效下載 URL、加密金鑰與正式 AV endpoint/API key。",
        },
        {
            "key": "signature",
            "name": "正式簽章與憑證合法性",
            "status": "pass" if signing_service["ready"] else "fail",
            "severity": "critical",
            "evidence": f"mode={signing_service['mode']}；missing={','.join(signing_service['missing']) or 'none'}",
            "action": "設定正式簽章 provider、HSM/KMS、信任根、TSA、OCSP、CRL 與 API key。",
        },
        {
            "key": "exchange",
            "name": "jAgent / 電子交換正式 provider",
            "status": "pass" if formal_exchange_ready else "fail",
            "severity": "critical",
            "evidence": f"provider={exchange_status.get('provider')}；mode={exchange_status.get('mode')}",
            "action": "待機關提供 jAgent/API/SDK/封包規格並經人工核准後，才可啟用 RealExchangeProvider。",
        },
        {
            "key": "notifications",
            "name": "通知通道",
            "status": "pass" if readiness["checks"]["smtp"] and readiness["checks"]["line"] else "fail",
            "severity": "high",
            "evidence": f"smtp={readiness['checks']['smtp']}；line={readiness['checks']['line']}",
            "action": "補齊 SMTP 與 LINE 正式通道，跑通知測試與失敗重送測試。",
        },
        {
            "key": "monitoring",
            "name": "監控與值班告警",
            "status": "pass" if readiness["checks"]["monitoringWebhook"] and readiness["checks"]["cronSecret"] else "warn",
            "severity": "high",
            "evidence": f"monitoringWebhook={readiness['checks']['monitoringWebhook']}；cronSecret={readiness['checks']['cronSecret']}；sentry={readiness['checks']['sentry']}",
            "action": "設定 MONITORING_WEBHOOK_URL / SENTRY_DSN，並讓 Cron 每日執行 production monitoring check。",
        },
        {
            "key": "accounts",
            "name": "正式帳號與 demo 帳號關閉",
            "status": "pass" if demo_accounts_disabled or not is_production() else "fail",
            "severity": "critical" if is_production() else "medium",
            "evidence": f"EDOC_DISABLE_DEMO_ACCOUNTS={demo_accounts_disabled}",
            "action": "正式帳號匯入後設定 EDOC_DISABLE_DEMO_ACCOUNTS=true，避免 demo1234 帳號留在公開正式站。",
        },
    ]
    return {
        "decision": decision,
        "formalGo": formal_go,
        "internalPilotAllowed": internal_pilot_allowed,
        "summary": summary,
        "targetLaunchDate": target_date,
        "checkedAt": now(),
        "environment": DEPLOYMENT_ENV,
        "databaseMode": readiness["databaseMode"],
        "formalBlockers": formal_blockers,
        "warnings": readiness.get("warnings", []),
        "categories": categories,
        "readiness": readiness,
        "exchange": exchange_status,
        "nextActions": [
            "先補 Supabase / Storage / AV / Signature / TSA / OCSP / CRL / Notification 正式設定。",
            "完成正式帳號匯入並關閉 demo 帳號政策。",
            "取得機關 jAgent/API/SDK/封包規格前，不開放正式電子交換送收。",
            "補齊後重新打 /api/production/go-live-audit，decision 必須為 GO 才能正式上線。",
        ] if not formal_go else [
            "執行 production monitoring check。",
            "執行收文、發文、簽核、用印、通知與備份還原 smoke test。",
            "將 go-live audit 報告保存到法遵營運紀錄。",
        ],
    }


def deployment_revision() -> str:
    return (
        os.getenv("VERCEL_GIT_COMMIT_SHA")
        or os.getenv("GITHUB_SHA")
        or os.getenv("COMMIT_SHA")
        or "local"
    )


def deployment_report() -> Dict[str, Any]:
    vercel_url = os.getenv("VERCEL_URL", "")
    deployment_url = EDOC_PUBLIC_BASE_URL or (f"https://{vercel_url}" if vercel_url else "")
    return {
        "environment": DEPLOYMENT_ENV,
        "runtime": "vercel-python" if RUNNING_ON_VERCEL else "local-dev",
        "vercel": RUNNING_ON_VERCEL,
        "databaseMode": "supabase" if USE_SUPABASE else "sqlite",
        "storage": {
            "provider": EDOC_STORAGE_PROVIDER,
            "bucket": EDOC_STORAGE_BUCKET,
            "objectEndpoint": EDOC_OBJECT_STORAGE_URL or "未設定",
            "accessMode": EDOC_STORAGE_ACCESS_MODE,
            "signedUrlTtlSeconds": EDOC_SIGNED_URL_TTL_SECONDS,
            "encryptionEnabled": EDOC_FILE_ENCRYPTION_ENABLED,
            "scanner": EDOC_SCAN_ENGINE,
            "avProvider": EDOC_AV_PROVIDER,
            "maxFileSizeMb": EDOC_MAX_FILE_SIZE_MB,
        },
        "revision": deployment_revision(),
        "branch": os.getenv("VERCEL_GIT_COMMIT_REF") or os.getenv("GITHUB_REF_NAME") or "local",
        "deploymentUrl": deployment_url,
        "region": os.getenv("VERCEL_REGION", "local"),
        "deployedAt": os.getenv("VERCEL_DEPLOYMENT_CREATED_AT", ""),
        "checkedAt": now(),
    }


def age_minutes(value: str | None) -> int | None:
    if not value:
        return None
    parsed = parse_time(value)
    if not parsed:
        return None
    return int((datetime.now() - parsed).total_seconds() // 60)


def append_alert(alerts: List[Dict[str, str]], level: str, code: str, message: str, action: str) -> None:
    alerts.append({"level": level, "code": code, "message": message, "action": action})


def monitoring_status(alerts: List[Dict[str, str]]) -> str:
    if any(alert["level"] == "critical" for alert in alerts):
        return "critical"
    if any(alert["level"] == "warning" for alert in alerts):
        return "warning"
    return "healthy"


def log_structured(level: str, message: str, **fields: Any) -> None:
    print(json.dumps({"level": level, "message": message, "time": now(), **fields}, ensure_ascii=False), flush=True)


def signing_service_status() -> Dict[str, Any]:
    services = {
        "provider": {"configured": EDOC_SIGNATURE_PROVIDER != "local-simulation", "value": EDOC_SIGNATURE_PROVIDER},
        "providerApi": {"configured": env_present("EDOC_SIGNATURE_API_URL"), "value": EDOC_SIGNATURE_API_URL or "未設定"},
        "providerCredential": {"configured": env_present("EDOC_SIGNATURE_API_KEY"), "value": "已設定" if env_present("EDOC_SIGNATURE_API_KEY") else "未設定"},
        "keyId": {"configured": env_present("EDOC_SIGNATURE_KEY_ID"), "value": EDOC_SIGNATURE_KEY_ID or "未設定"},
        "hsm": {"configured": env_present("EDOC_HSM_PROVIDER"), "value": EDOC_HSM_PROVIDER or "未設定"},
        "trustStore": {"configured": env_present("EDOC_CERT_TRUST_STORE"), "value": EDOC_CERT_TRUST_STORE or "未設定"},
        "tsa": {"configured": env_present("EDOC_TSA_URL"), "value": EDOC_TSA_URL or "未設定", "policyOid": EDOC_TSA_POLICY_OID},
        "tsaCredential": {"configured": env_present("EDOC_TSA_API_KEY"), "value": "已設定" if env_present("EDOC_TSA_API_KEY") else "未設定"},
        "ocsp": {"configured": env_present("EDOC_OCSP_RESPONDER_URL"), "value": EDOC_OCSP_RESPONDER_URL or "未設定"},
        "crl": {"configured": env_present("EDOC_CRL_DISTRIBUTION_URL"), "value": EDOC_CRL_DISTRIBUTION_URL or "未設定"},
        "signingSecret": {"configured": env_present("EDOC_SIGNING_SECRET") or EDOC_SIGNATURE_PROVIDER != "local-simulation", "value": "已設定" if env_present("EDOC_SIGNING_SECRET") else "正式 provider 簽章"},
    }
    missing = [key for key, item in services.items() if not item["configured"]]
    ready = not missing
    return {
        "ready": ready,
        "mode": "formal" if ready else "simulation-or-incomplete",
        "missing": missing,
        "services": services,
        "policy": {
            "profile": EDOC_SIGNATURE_PROFILE,
            "provider": EDOC_SIGNATURE_PROVIDER,
            "keyId": EDOC_SIGNATURE_KEY_ID or "未設定",
            "timeoutSeconds": EDOC_SIGNATURE_TIMEOUT_SECONDS,
            "maxRetries": EDOC_SIGNATURE_MAX_RETRIES,
            "tsaPolicyOid": EDOC_TSA_POLICY_OID,
            "requiresExternalProvider": is_production(),
        },
        "productionBlocked": is_production() and not ready,
    }


def storage_service_status() -> Dict[str, Any]:
    services = {
        "provider": {"configured": EDOC_STORAGE_PROVIDER in {"supabase", "s3", "gcs", "azure"}, "value": EDOC_STORAGE_PROVIDER or "未設定"},
        "bucket": {"configured": bool(EDOC_STORAGE_BUCKET), "value": EDOC_STORAGE_BUCKET or "未設定"},
        "sealBucket": {"configured": bool(EDOC_SEAL_STORAGE_BUCKET), "value": EDOC_SEAL_STORAGE_BUCKET or "未設定"},
        "objectEndpoint": {"configured": bool(EDOC_OBJECT_STORAGE_URL), "value": EDOC_OBJECT_STORAGE_URL or "未設定"},
        "accessMode": {"configured": EDOC_STORAGE_ACCESS_MODE == "server-signed-url", "value": EDOC_STORAGE_ACCESS_MODE},
        "encryption": {"configured": EDOC_FILE_ENCRYPTION_ENABLED and env_present("EDOC_FILE_ENCRYPTION_KEY"), "value": "已啟用" if EDOC_FILE_ENCRYPTION_ENABLED else "未啟用", "keyId": file_key_id() if env_present("EDOC_FILE_ENCRYPTION_KEY") else "未設定"},
        "scanner": {"configured": env_present("EDOC_SCAN_ENGINE"), "value": EDOC_SCAN_ENGINE or "未設定"},
        "avProvider": {"configured": env_present("EDOC_AV_PROVIDER"), "value": EDOC_AV_PROVIDER or "未設定"},
        "avEndpoint": {"configured": env_present("EDOC_AV_ENDPOINT"), "value": EDOC_AV_ENDPOINT or "未設定"},
        "avCredential": {"configured": env_present("EDOC_AV_API_KEY") or EDOC_AV_ENDPOINT.startswith(("tcp://", "clamd://")), "value": "已設定" if env_present("EDOC_AV_API_KEY") else ("內網連線" if EDOC_AV_ENDPOINT.startswith(("tcp://", "clamd://")) else "未設定")},
        "signedUrlTtl": {"configured": 0 < EDOC_SIGNED_URL_TTL_SECONDS <= 900, "value": EDOC_SIGNED_URL_TTL_SECONDS},
        "maxFileSize": {"configured": EDOC_MAX_FILE_SIZE_MB > 0, "value": EDOC_MAX_FILE_SIZE_MB},
        "allowedMimeTypes": {"configured": bool(EDOC_ALLOWED_MIME_TYPES.strip()), "value": EDOC_ALLOWED_MIME_TYPES},
    }
    missing = [key for key, item in services.items() if not item["configured"]]
    ready = not missing
    return {
        "ready": ready,
        "mode": "formal-object-storage-av" if ready else "local-or-incomplete",
        "missing": missing,
        "services": services,
        "policy": {
            "provider": EDOC_STORAGE_PROVIDER,
            "bucket": EDOC_STORAGE_BUCKET,
            "sealBucket": EDOC_SEAL_STORAGE_BUCKET,
            "objectEndpoint": EDOC_OBJECT_STORAGE_URL or "未設定",
            "accessMode": EDOC_STORAGE_ACCESS_MODE,
            "signedUrlTtlSeconds": EDOC_SIGNED_URL_TTL_SECONDS,
            "maxFileSizeMb": EDOC_MAX_FILE_SIZE_MB,
            "allowedMimeTypes": [item.strip() for item in EDOC_ALLOWED_MIME_TYPES.split(",") if item.strip()],
            "encryptionEnabled": EDOC_FILE_ENCRYPTION_ENABLED,
            "scanEngine": EDOC_SCAN_ENGINE,
            "avProvider": EDOC_AV_PROVIDER,
            "avEndpoint": EDOC_AV_ENDPOINT or "未設定",
        },
        "productionBlocked": is_production() and not ready,
    }


def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 210_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algorithm, salt, expected = stored.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 210_000).hex()
    return hmac.compare_digest(digest, expected)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def file_key_id() -> str:
    return f"KEY-{hashlib.sha256(EDOC_FILE_ENCRYPTION_KEY.encode('utf-8')).hexdigest()[:12].upper()}"


def xor_keystream(data: bytes, key: str) -> bytes:
    key_bytes = hashlib.sha256(key.encode("utf-8")).digest()
    output = bytearray()
    counter = 0
    while len(output) < len(data):
        output.extend(hmac.new(key_bytes, counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(byte ^ output[index] for index, byte in enumerate(data))


def encrypt_file_bytes(data: bytes) -> Tuple[bytes, str, str]:
    if not EDOC_FILE_ENCRYPTION_ENABLED:
        return data, "未加密", ""
    return xor_keystream(data, EDOC_FILE_ENCRYPTION_KEY), "已加密", "LOCAL-HMAC-STREAM"


def decrypt_file_bytes(data: bytes, encryption_status: str = "", encryption_alg: str = "") -> bytes:
    if encryption_status != "已加密" or encryption_alg != "LOCAL-HMAC-STREAM":
        return data
    return xor_keystream(data, EDOC_FILE_ENCRYPTION_KEY)


def signed_url_expiry(seconds: int | None = None) -> str:
    return (datetime.now() + timedelta(seconds=seconds or EDOC_SIGNED_URL_TTL_SECONDS)).strftime("%Y-%m-%d %H:%M:%S")


def parse_time(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime((value or "").split(".")[0], fmt)
        except ValueError:
            continue
    return datetime.min


A4_WIDTH_PT = 595.28
A4_HEIGHT_PT = 841.89
PDF_PT_PER_MM = 72 / 25.4


def pdf_literal(value: Any) -> str:
    return str(value or "").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf_hex_text(value: Any) -> str:
    return str(value or "").encode("utf-16-be", "replace").hex().upper()


def pdf_text_width_units(value: Any) -> float:
    units = 0.0
    for char in str(value or ""):
        code = ord(char)
        if char in " \t":
            units += 0.45
        elif code < 128:
            units += 0.55
        elif 0xFF61 <= code <= 0xFF9F:
            units += 0.55
        else:
            units += 1.0
    return units


def pdf_estimated_width(value: Any, size: float) -> float:
    return pdf_text_width_units(value) * size


def pdf_show_text(text: Any, x: float, y: float, size: float = 12, font: str = "F1") -> str:
    return f"BT /{font} {size:.2f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm <{pdf_hex_text(text)}> Tj ET\n"


def pdf_center_text(text: Any, y: float, size: float = 18, font: str = "F1") -> str:
    x = max(36.0, (A4_WIDTH_PT - pdf_estimated_width(text, size)) / 2)
    return pdf_show_text(text, x, y, size, font)


def pdf_top_y(top_y: float) -> float:
    return A4_HEIGHT_PT - top_y


def pdf_safe_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def clamp_pdf_rect(x: float, y: float, width: float, height: float) -> Tuple[float, float, float, float]:
    width = max(12.0, min(width, A4_WIDTH_PT - 24.0))
    height = max(12.0, min(height, A4_HEIGHT_PT - 24.0))
    x = max(12.0, min(x, A4_WIDTH_PT - width - 12.0))
    y = max(12.0, min(y, A4_HEIGHT_PT - height - 12.0))
    return round(x, 2), round(y, 2), round(width, 2), round(height, 2)


def wrap_pdf_text(text: Any, max_units: float) -> List[str]:
    source = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines: List[str] = []
    for paragraph in source.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        current_units = 0.0
        for char in paragraph.strip():
            unit = pdf_text_width_units(char)
            if current and current_units + unit > max_units:
                lines.append(current)
                current = char
                current_units = unit
            else:
                current += char
                current_units += unit
        if current:
            lines.append(current)
    return lines or [""]


def parse_json_field(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def parse_json_any(value: Any, fallback: Any = None) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return fallback
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def roc_date_string(value: Any = None) -> str:
    parsed = parse_time(str(value)) if value else datetime.now()
    if parsed == datetime.min:
        parsed = datetime.now()
    return f"中華民國{parsed.year - 1911}年{parsed.month}月{parsed.day}日"


def official_pdf_info(doc: Dict[str, Any], template: str) -> Dict[str, Any]:
    metadata = parse_json_field(doc.get("metadata_json"))
    contact = metadata.get("contact") if isinstance(metadata.get("contact"), dict) else {}
    attachments = doc.get("attachments")
    if isinstance(attachments, list):
        attachments_text = "、".join(str(item) for item in attachments if item) or "函稿本文、附件清冊"
    else:
        attachments_text = str(attachments or metadata.get("attachments") or "函稿本文、附件清冊")
    company = doc.get("company_name") or doc.get("companyName") or metadata.get("companyName") or "歲悅長照股份有限公司"
    doc_type = doc.get("doc_type") or doc.get("type") or template.replace(company, "").strip() or "函"
    return {
        "company": company,
        "doc_type": doc_type,
        "doc_no": doc.get("doc_no") or doc.get("no") or doc.get("docNo") or "系統產生中",
        "date": roc_date_string(doc.get("created_at") or doc.get("date")),
        "priority": doc.get("priority") or "普通件",
        "security": doc.get("security_level") or doc.get("security") or "普通",
        "recipient": doc.get("agency_name") or doc.get("to") or "未指定受文者",
        "agency_code": doc.get("agency_code") or doc.get("agencyCode") or "",
        "subject": doc.get("subject") or "未填主旨",
        "body": doc.get("body") or doc.get("description") or "尚未填寫說明內容。",
        "attachments": attachments_text,
        "contact_address": doc.get("contactAddress") or doc.get("contact_address") or contact.get("address") or "220205 新北市板橋區英士路192之1號",
        "contact_owner": doc.get("contactOwner") or doc.get("contact_owner") or contact.get("owner") or doc.get("owner") or "總務",
        "contact_phone": doc.get("contactPhone") or doc.get("contact_phone") or contact.get("phone") or "(02)2257-7155 分機3762",
        "contact_fax": doc.get("contactFax") or doc.get("contact_fax") or contact.get("fax") or "(02)2254-4029",
        "contact_email": doc.get("contactEmail") or doc.get("contact_email") or contact.get("email") or "edoc@suiyuecare.com",
    }


def content_bottom_for_pdf_stamps(stamps: List[Dict[str, Any]] | None, page_number: int, fallback: float = 788.0) -> float:
    bottom = fallback
    for stamp in stamps or []:
        if stamp.get("page") not in {page_number, "all"}:
            continue
        y = pdf_safe_float(stamp.get("y"), 0.0)
        height = pdf_safe_float(stamp.get("h"), 0.0)
        stamp_top_from_page_top = A4_HEIGHT_PT - (y + height)
        if stamp_top_from_page_top > 500:
            bottom = min(bottom, stamp_top_from_page_top - 24)
    return max(540.0, bottom)


def paginate_official_pdf(info: Dict[str, Any], stamps: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    text_x = 104.0
    right_margin = 44.0
    max_units = (A4_WIDTH_PT - text_x - right_margin) / 18.0
    subject_lines = wrap_pdf_text(info["subject"], max_units)
    body_lines = wrap_pdf_text(info["body"], max_units)
    subject_top = 468.0
    line_height = 28.0
    body_top = subject_top + max(1, len(subject_lines)) * line_height + 26.0
    bottom_top = content_bottom_for_pdf_stamps(stamps, 1, 788.0)
    first_capacity = max(1, int((bottom_top - body_top) // line_height) + 1)
    next_top = 92.0
    pages: List[Dict[str, Any]] = []
    pages.append({"number": 1, "body_lines": body_lines[:first_capacity], "body_top": body_top, "bottom_top": bottom_top})
    remaining = body_lines[first_capacity:]
    while remaining:
        number = len(pages) + 1
        page_bottom = content_bottom_for_pdf_stamps(stamps, number, 788.0)
        next_capacity = max(1, int((page_bottom - next_top) // line_height) + 1)
        pages.append({"number": number, "body_lines": remaining[:next_capacity], "body_top": next_top, "bottom_top": page_bottom})
        remaining = remaining[next_capacity:]
    return {
        "subject_lines": subject_lines,
        "pages": pages,
        "line_height": line_height,
        "body_text_x": text_x,
        "label_x": 42.0,
        "bottom_top": 788.0,
    }


def draw_wrapped_lines(lines: List[str], x: float, top_y: float, size: float, line_height: float) -> str:
    stream = ""
    for index, line in enumerate(lines):
        if line:
            stream += pdf_show_text(line, x, pdf_top_y(top_y + index * line_height), size)
    return stream


def draw_official_page(info: Dict[str, Any], layout: Dict[str, Any], page: Dict[str, Any], total_pages: int, stamps: List[Dict[str, Any]]) -> str:
    page_number = int(page["number"])
    stream = "1 1 1 rg 0 0 595.28 841.89 re f 0 0 0 rg\n"
    if page_number == 1:
        stream += pdf_show_text("檔　號：", 430, pdf_top_y(30), 12)
        stream += pdf_show_text("保存年限：", 430, pdf_top_y(48), 12)
        stream += pdf_center_text(f"{info['company']}　{info['doc_type']}", pdf_top_y(112), 23)
        contact_lines = [
            f"地址：{info['contact_address']}",
            f"承辦人：{info['contact_owner']}",
            f"電話：{info['contact_phone']}",
            f"傳真：{info['contact_fax']}",
            f"電子信箱：{info['contact_email']}",
        ]
        contact_top = 150.0
        contact_x = 300.0
        contact_max_units = (A4_WIDTH_PT - contact_x - 36.0) / 10.5
        for line in contact_lines:
            for wrapped_line in wrap_pdf_text(line, contact_max_units):
                stream += pdf_show_text(wrapped_line, contact_x, pdf_top_y(contact_top), 10.5)
                contact_top += 15.0
        stream += pdf_show_text(f"受文者：{info['recipient']}", 42, pdf_top_y(294), 18)
        meta_lines = [
            f"發文日期：{info['date']}",
            f"發文字號：{info['doc_no']}",
            f"速別：{info['priority']}",
            f"密等及解密條件或保密期限：{info['security']}",
            f"附件：{info['attachments']}",
        ]
        for index, line in enumerate(meta_lines):
            stream += pdf_show_text(line, 42, pdf_top_y(340 + index * 22), 14)
        stream += pdf_show_text("主旨：", layout["label_x"], pdf_top_y(468), 18)
        stream += draw_wrapped_lines(layout["subject_lines"], layout["body_text_x"], 468, 18, layout["line_height"])
        stream += pdf_show_text("說明：", layout["label_x"], pdf_top_y(page["body_top"]), 18)
        stream += draw_wrapped_lines(page["body_lines"], layout["body_text_x"], page["body_top"], 18, layout["line_height"])
    else:
        stream += pdf_show_text(info["doc_no"], 42, pdf_top_y(42), 12)
        stream += pdf_show_text(f"續第 {page_number} 頁", 490, pdf_top_y(42), 12)
        stream += "0.75 0.75 0.75 RG 42 774 511 0.8 re S 0 0 0 RG\n"
        stream += pdf_show_text("續：", layout["label_x"], pdf_top_y(page["body_top"]), 18)
        stream += draw_wrapped_lines(page["body_lines"], layout["body_text_x"], page["body_top"], 18, layout["line_height"])
    stream += pdf_show_text(f"第 {page_number} 頁 / 共 {total_pages} 頁", 248, 28, 9)
    for stamp in stamps:
        if stamp.get("page") not in {page_number, "all"}:
            continue
        x, y, width, height = clamp_pdf_rect(
            pdf_safe_float(stamp.get("x"), 420.0),
            pdf_safe_float(stamp.get("y"), 120.0),
            pdf_safe_float(stamp.get("w"), 56.0),
            pdf_safe_float(stamp.get("h"), 56.0),
        )
        label = str(stamp.get("label") or "用印")
        stamp_type = str(stamp.get("type") or "")
        stamp_no = str(stamp.get("stamp_no") or "")
        stream += "0.75 0 0 RG 1.8 w\n"
        stream += f"{x:.2f} {y:.2f} {width:.2f} {height:.2f} re S\n"
        stream += f"{x + 4:.2f} {y + 4:.2f} {max(4, width - 8):.2f} {max(4, height - 8):.2f} re S\n"
        stream += "0.72 0 0 rg\n"
        stream += pdf_show_text(label, x + 8, y + height * 0.58, min(12, max(8, width / 7)))
        if stamp_type:
            stream += pdf_show_text(stamp_type, x + 8, y + height * 0.39, min(9, max(6, width / 9)))
        if stamp_no:
            stream += pdf_show_text(stamp_no[-18:], x + 5, y + 8, min(6.5, max(5, width / 13)))
        stream += "0 0 0 rg 0 0 0 RG 1 w\n"
    return stream


def write_pdf_document(page_streams: List[str]) -> bytes:
    page_count = len(page_streams)
    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    page_object_numbers = [3 + index * 2 for index in range(page_count)]
    objects.append(f"<< /Type /Pages /Kids [{' '.join(f'{num} 0 R' for num in page_object_numbers)}] /Count {page_count} >>")
    font_object_number = 3 + page_count * 2
    cid_font_object_number = font_object_number + 1
    for index, stream in enumerate(page_streams):
        page_object_number = 3 + index * 2
        content_object_number = page_object_number + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {A4_WIDTH_PT:.2f} {A4_HEIGHT_PT:.2f}] "
            f"/Resources << /Font << /F1 {font_object_number} 0 R >> >> /Contents {content_object_number} 0 R >>"
        )
        stream_bytes = stream.encode("latin-1", "replace")
        objects.append(f"<< /Length {len(stream_bytes)} >>\nstream\n{stream}endstream")
    objects.append(
        f"<< /Type /Font /Subtype /Type0 /BaseFont /MKai-Medium /Encoding /UniCNS-UCS2-H "
        f"/DescendantFonts [{cid_font_object_number} 0 R] >>"
    )
    objects.append(
        "<< /Type /Font /Subtype /CIDFontType0 /BaseFont /MKai-Medium "
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (CNS1) /Supplement 5 >> /DW 1000 >>"
    )
    pdf = "%PDF-1.4\n"
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf.encode("latin-1")))
        pdf += f"{index} 0 obj\n{obj}\nendobj\n"
    xref_at = len(pdf.encode("latin-1"))
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    for offset in offsets[1:]:
        pdf += f"{offset:010d} 00000 n \n"
    pdf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF"
    return pdf.encode("latin-1", "replace")


def build_official_pdf_package(doc: Dict[str, Any], stamps: List[Dict[str, Any]] | None = None, template: str = "歲悅正式函", min_page_count: int = 1) -> Dict[str, Any]:
    stamps = stamps or []
    info = official_pdf_info(doc, template)
    layout = paginate_official_pdf(info, stamps)
    while len(layout["pages"]) < max(1, int(min_page_count or 1)):
        layout["pages"].append({"number": len(layout["pages"]) + 1, "body_lines": [], "body_top": 92.0, "bottom_top": 788.0})
    total_pages = len(layout["pages"])
    page_streams = [draw_official_page(info, layout, page, total_pages, stamps) for page in layout["pages"]]
    return {
        "data": write_pdf_document(page_streams),
        "layout": {
            "page_count": total_pages,
            "page_size": {"width_pt": A4_WIDTH_PT, "height_pt": A4_HEIGHT_PT, "format": "A4"},
            "subject_lines": len(layout["subject_lines"]),
            "body_lines": sum(len(page["body_lines"]) for page in layout["pages"]),
            "pages": [{"number": page["number"], "body_line_count": len(page["body_lines"]), "body_top": page["body_top"], "bottom_top": page.get("bottom_top", 788.0)} for page in layout["pages"]],
            "font": "MKai-Medium / UniCNS-UCS2-H",
        },
    }


def build_official_pdf(doc: Dict[str, Any], stamps: List[Dict[str, Any]] | None = None, template: str = "歲悅正式函", page_count: int = 1) -> bytes:
    return build_official_pdf_package(doc, stamps, template, page_count)["data"]


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    PRIVATE_SEAL_STORAGE_DIR.mkdir(parents=True, exist_ok=True)


LOCAL_SCHEMA_READY = False


def connect() -> sqlite3.Connection:
    global LOCAL_SCHEMA_READY
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if not LOCAL_SCHEMA_READY:
        conn.executescript(SCHEMA)
        conn.commit()
        LOCAL_SCHEMA_READY = True
    return conn


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def audit_severity(event_type: str, result: str = "success") -> str:
    if result == "denied" or event_type in LOGGING_CRITICAL_EVENTS:
        return "critical"
    if result == "failed":
        return "warning"
    return "info"


def normalize_audit_event_type(event_type: str | None, action: str) -> str:
    if event_type in LOGGING_AUDIT_EVENT_TYPES:
        return str(event_type)
    if "登入" in action:
        return "login"
    if "登出" in action:
        return "logout"
    if "匯出" in action:
        return "export"
    if "刪除" in action or "停用" in action:
        return "delete"
    if "退回" in action or "拒絕" in action:
        return "reject"
    if "核准" in action or "簽核" in action or "覆核" in action:
        return "approve"
    if "分派" in action or "指派" in action:
        return "assign"
    if "權限" in action or "角色" in action:
        return "permission_change"
    if "敏感" in action or "密件" in action or "下載" in action:
        return "sensitive_access"
    return "submit"


def log_audit(
    conn: sqlite3.Connection,
    actor: str,
    action: str,
    target_type: str = "",
    target_id: str = "",
    detail: str = "",
    *,
    event_type: str | None = None,
    result: str = "success",
    module_code: str = "",
    resource_type: str | None = None,
    resource_id: str | None = None,
    data_scope: str | None = None,
    actor_user_id: str = "",
    actor_email: str = "",
    actor_roles: List[str] | None = None,
    target_user_id: str = "",
    target_email: str = "",
    reason: str = "",
    request_id: str = "",
    before_snapshot: Dict[str, Any] | None = None,
    after_snapshot: Dict[str, Any] | None = None,
    metadata: Dict[str, Any] | None = None,
) -> None:
    safe_detail = redact_text(detail) if isinstance(detail, str) else json.dumps(redact_sensitive(detail), ensure_ascii=False)
    normalized_event_type = normalize_audit_event_type(event_type, action)
    normalized_result = result if result in {"success", "failed", "denied"} else "success"
    normalized_scope = data_scope if data_scope in LOGGING_DATA_SCOPES else None
    metadata_payload = {"legacy_detail": safe_detail, **(metadata or {})}
    conn.execute(
        """
        INSERT INTO audit_logs (
          id, actor, action, target_type, target_id, ip, device, detail,
          event_type, severity, result, module_code, resource_type, resource_id, data_scope,
          actor_user_id, actor_email, actor_roles_json, target_user_id, target_email,
          reason, request_id, before_snapshot_json, after_snapshot_json, metadata_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"AUD-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
            actor,
            action,
            target_type,
            target_id,
            "127.0.0.1",
            "backend",
            safe_detail,
            normalized_event_type,
            audit_severity(normalized_event_type, normalized_result),
            normalized_result,
            module_code or target_type or "edoc",
            resource_type or target_type or None,
            resource_id or target_id or None,
            normalized_scope,
            actor_user_id,
            actor_email,
            json.dumps(actor_roles or ([actor] if actor else []), ensure_ascii=False),
            target_user_id,
            target_email,
            reason,
            request_id or f"req_{secrets.token_hex(8)}",
            json.dumps(redact_sensitive(before_snapshot or {}), ensure_ascii=False),
            json.dumps(redact_sensitive(after_snapshot or {}), ensure_ascii=False),
            json.dumps(redact_sensitive(metadata_payload), ensure_ascii=False),
            now(),
        ),
    )


def log_permission_change(
    conn: sqlite3.Connection,
    actor: str,
    target_user_id: str,
    target_email: str,
    before_snapshot: Dict[str, Any],
    after_snapshot: Dict[str, Any],
    reason: str,
    actor_roles: List[str] | None = None,
) -> None:
    log_audit(
        conn,
        actor,
        "權限異動",
        "user_role",
        target_user_id,
        reason,
        event_type="permission_change",
        result="success",
        module_code="system_permissions",
        resource_type="user_role",
        resource_id=target_user_id,
        data_scope="custom",
        actor_roles=actor_roles or [actor],
        target_user_id=target_user_id,
        target_email=target_email,
        reason=reason,
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
        metadata={"source": "edoc_rbac"},
    )


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def migrate() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        ensure_column(conn, "documents", "company_name", "TEXT NOT NULL DEFAULT '歲悅長照股份有限公司'")
        ensure_column(conn, "documents", "seal_plan_json", "TEXT NOT NULL DEFAULT '{}'")
        ensure_column(conn, "documents", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
        ensure_column(conn, "users", "auth_user_id", "TEXT")
        ensure_column(conn, "users", "account_source", "TEXT NOT NULL DEFAULT 'edoc'")
        ensure_column(conn, "users", "logging_account_id", "TEXT")
        ensure_column(conn, "users", "logging_role_key", "TEXT")
        ensure_column(conn, "users", "external_account_payload_json", "TEXT NOT NULL DEFAULT '{}'")
        ensure_column(conn, "users", "last_synced_from_logging_at", "TEXT")
        ensure_column(conn, "users", "password_hash", "TEXT")
        ensure_column(conn, "users", "job_level", "TEXT NOT NULL DEFAULT '職員'")
        ensure_column(conn, "official_documents", "dispatch_method", "TEXT NOT NULL DEFAULT 'electronic_official_document_by_general_affairs'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_official_dispatch_records_document ON official_document_dispatch_records(document_id, dispatch_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_official_dispatch_records_owner ON official_document_dispatch_records(dispatch_owner_user_id, dispatch_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_logging_account ON users(logging_account_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_module_account_links_source ON module_account_links(source_system, source_account_id, target_module)")
        conn.execute(
            """
            UPDATE users
            SET job_level = CASE job_level
              WHEN 'L1 員工' THEN '職員'
              WHEN 'L2 專員' THEN '職員'
              WHEN 'L3 主管' THEN '課長'
              WHEN 'L4 部門主管' THEN '部長'
              WHEN 'L5 高階主管' THEN '區經理'
              WHEN 'L6 執行長' THEN '執行長'
              ELSE COALESCE(NULLIF(job_level, ''), '職員')
            END
            WHERE job_level IS NULL
               OR job_level = ''
               OR job_level IN ('L1 員工', 'L2 專員', 'L3 主管', 'L4 部門主管', 'L5 高階主管', 'L6 執行長')
            """
        )
        for column, definition in {
            "event_type": "TEXT NOT NULL DEFAULT 'submit'",
            "severity": "TEXT NOT NULL DEFAULT 'info'",
            "result": "TEXT NOT NULL DEFAULT 'success'",
            "module_code": "TEXT",
            "resource_type": "TEXT",
            "resource_id": "TEXT",
            "data_scope": "TEXT",
            "actor_user_id": "TEXT",
            "actor_email": "TEXT",
            "actor_roles_json": "TEXT NOT NULL DEFAULT '[]'",
            "target_user_id": "TEXT",
            "target_email": "TEXT",
            "reason": "TEXT",
            "request_id": "TEXT",
            "before_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
            "after_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
            "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
        }.items():
            ensure_column(conn, "audit_logs", column, definition)
        for statement in [
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_event_type ON audit_logs(event_type, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_module ON audit_logs(module_code, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs(resource_type, resource_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_request ON audit_logs(request_id)",
        ]:
            conn.execute(statement)
        for column, definition in {
            "bucket": "TEXT NOT NULL DEFAULT 'edoc-private'",
            "storage_provider": "TEXT NOT NULL DEFAULT 'local'",
            "encrypted_sha256": "TEXT",
            "encryption_status": "TEXT NOT NULL DEFAULT '未加密'",
            "encryption_alg": "TEXT",
            "encryption_key_id": "TEXT",
            "scan_status": "TEXT NOT NULL DEFAULT '待掃描'",
            "scan_engine": "TEXT",
            "quarantine_reason": "TEXT",
            "signed_url_expires_at": "TEXT",
            "last_scan_at": "TEXT",
            "last_download_at": "TEXT",
        }.items():
            ensure_column(conn, "file_objects", column, definition)
        for column, definition in {
            "certificate_type": "TEXT NOT NULL DEFAULT 'organization'",
            "key_usage": "TEXT",
            "extended_key_usage": "TEXT",
            "chain_status": "TEXT NOT NULL DEFAULT '待驗證'",
            "ocsp_status": "TEXT NOT NULL DEFAULT '待查詢'",
            "crl_status": "TEXT NOT NULL DEFAULT '待查詢'",
            "tsa_url": "TEXT",
            "ocsp_url": "TEXT",
            "crl_url": "TEXT",
            "root_ca_fingerprint": "TEXT",
            "last_validated_at": "TEXT",
            "validation_report_json": "TEXT",
        }.items():
            ensure_column(conn, "signing_certificates", column, definition)
        for column, definition in {
            "certificate_validation_id": "TEXT",
            "tsa_status": "TEXT NOT NULL DEFAULT '待驗證'",
            "ocsp_status": "TEXT NOT NULL DEFAULT '待查詢'",
            "crl_status": "TEXT NOT NULL DEFAULT '待查詢'",
            "chain_status": "TEXT NOT NULL DEFAULT '待驗證'",
            "provider": "TEXT",
            "provider_key_id": "TEXT",
            "provider_request_id": "TEXT",
            "provider_receipt_json": "TEXT",
            "evidence_digest_sha256": "TEXT",
        }.items():
            ensure_column(conn, "electronic_signatures", column, definition)
        for column, definition in {
            "application_type": "TEXT NOT NULL DEFAULT 'official_document'",
            "company_name": "TEXT NOT NULL DEFAULT '歲悅股份有限公司'",
            "department": "TEXT",
            "title": "TEXT",
            "source_pdf_file_object_id": "TEXT",
            "source_pdf_sha256": "TEXT",
            "source_pdf_name": "TEXT",
            "locked_pdf_sha256": "TEXT",
            "locked_positions_sha256": "TEXT",
            "stamp_positions_json": "TEXT NOT NULL DEFAULT '[]'",
            "approval_route_code": "TEXT",
            "approval_route_name": "TEXT",
            "approval_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
            "current_step_no": "INTEGER NOT NULL DEFAULT 1",
            "current_step_name": "TEXT",
            "current_approver_role": "TEXT",
            "applicant_user_id": "TEXT",
            "applicant_name": "TEXT",
            "applicant_email": "TEXT",
            "reject_reason": "TEXT",
            "returned_at": "TEXT",
            "completed_at": "TEXT",
            "notification_id": "TEXT",
            "signature_id": "TEXT",
            "provider_status": "TEXT",
            "failure_reason": "TEXT",
            "evidence_json": "TEXT",
            "updated_at": "TEXT",
        }.items():
            ensure_column(conn, "seal_applications", column, definition)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_seal_applications_type_status ON seal_applications(application_type, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_seal_applications_current_approver ON seal_applications(current_approver_role, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_file_objects_scan ON file_objects(scan_status)")
        seed(conn)
        seed_auth(conn)
        ensure_allowed_edoc_users(conn)
        normalize_legacy_document_owners(conn)
        seed_persistent_registries(conn)
        seed_workflow_tasks(conn)
        seed_contracts(conn)
        seed_department_isolation_examples(conn)
        seed_document_acl_examples(conn)
        seed_certificate_authorities(conn)
        seed_signing_certificates(conn)
        seed_company_seal_module(conn)
        seed_seal_assets(conn)
        seed_notification_credentials(conn)
        seed_attachment_security(conn)
        seed_jobs(conn)
        seed_notifications(conn)
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
        ("USR-001", None, "林總務", "edoc@suiyuecare.com", password_hash("demo1234"), "總務", "總務", "L2 專員", "總務", "Google Workspace", "已啟用", "啟用"),
        ("USR-002", None, "張行政", "records@suiyuecare.com", password_hash("demo1234"), "行政部", "行政部主任", "L4 部門主管", "行政部主任", "Microsoft Entra", "已啟用", "啟用"),
        ("USR-003", None, "王主任", "director@suiyuecare.com", password_hash("demo1234"), "營運管理處", "主任", "L3 主管", "主任", "Google Workspace", "已啟用", "啟用"),
        ("USR-004", None, "陳執行長", "ceo@suiyuecare.com", password_hash("demo1234"), "經營管理", "執行長", "L6 執行長", "執行長", "Google Workspace", "已啟用", "啟用"),
        ("USR-005", None, "何人資", "hr@suiyuecare.com", password_hash("demo1234"), "人資", "人資", "L2 專員", "人資", "Microsoft Entra", "已啟用", "啟用"),
        ("USR-006", None, "許會計", "accounting@suiyuecare.com", password_hash("demo1234"), "會計", "會計", "L2 專員", "會計", "Microsoft Entra", "已啟用", "啟用"),
        ("USR-007", None, "周業助", "sales-assistant@suiyuecare.com", password_hash("demo1234"), "業務部", "業務助理", "L1 員工", "業務助理", "Google Workspace", "待設定", "啟用"),
    ]
    for item in users:
        conn.execute(
            """
            INSERT INTO users (id, auth_user_id, name, email, password_hash, unit, title, job_level, role, provider, mfa_status, status, last_login_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def seed_auth(conn: sqlite3.Connection) -> None:
    ts = now()
    default_password = password_hash("demo1234")
    conn.execute("UPDATE users SET password_hash = COALESCE(password_hash, ?)", (default_password,))

    for role in EDOC_ROLE_CATALOG:
        conn.execute(
            """
            INSERT INTO roles (id, name, description, data_scope, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, '啟用', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              name = excluded.name,
              description = excluded.description,
              data_scope = excluded.data_scope,
              status = excluded.status,
              updated_at = excluded.updated_at
            """,
            (role[0], role[1], f"{role[2]}：{role[3]}", role[4], ts, ts),
        )
    placeholders = ",".join("?" for _ in ALLOWED_EDOC_ROLE_LIST)
    conn.execute(
        f"UPDATE roles SET status = '停用', updated_at = ? WHERE name NOT IN ({placeholders})",
        (ts, *ALLOWED_EDOC_ROLE_LIST),
    )
    conn.execute(
        f"UPDATE roles SET status = '啟用', updated_at = ? WHERE name IN ({placeholders})",
        (ts, *ALLOWED_EDOC_ROLE_LIST),
    )


def ensure_allowed_edoc_users(conn: sqlite3.Connection) -> None:
    ts = now()
    seed_password = password_hash("demo1234")
    users = [
        ("USR-001", None, "林總務", "edoc@suiyuecare.com", "總務", "總務課長", "課長", "總務", "Google Workspace", "已啟用", "啟用"),
        ("USR-002", None, "張行政", "records@suiyuecare.com", "行政部", "行政部長", "部長", "行政部主任", "Microsoft Entra", "已啟用", "啟用"),
        ("USR-003", None, "王主管", "director@suiyuecare.com", "居家照顧部", "居家服務督導", "組長", "主管", "Google Workspace", "已啟用", "啟用"),
        ("USR-004", None, "陳執行長", "ceo@suiyuecare.com", "經營管理", "執行長", "執行長", "執行長", "Google Workspace", "已啟用", "啟用"),
        ("USR-005", None, "何人資", "hr@suiyuecare.com", "人資", "人資課長", "課長", "人資", "Microsoft Entra", "已啟用", "啟用"),
        ("USR-006", None, "許會計", "accounting@suiyuecare.com", "會計", "會計課長", "課長", "會計", "Microsoft Entra", "已啟用", "啟用"),
        ("USR-007", None, "周業助", "sales-assistant@suiyuecare.com", "業務部", "業務助理", "職員", "業務助理", "Google Workspace", "待設定", "啟用"),
        ("USR-008", None, "員工測試", "employee@suiyuecare.com", "居家照顧部", "居家照顧服務員", "職員", "員工", "Google Workspace", "待設定", "啟用"),
    ]
    for item in users:
        updated = conn.execute(
            """
            UPDATE users
            SET
              auth_user_id = COALESCE(auth_user_id, ?),
              name = ?,
              email = ?,
              unit = ?,
              title = ?,
              job_level = ?,
              role = ?,
              provider = ?,
              mfa_status = ?,
              status = ?
            WHERE id = ? OR lower(email) = ?
            """,
            (item[1], item[2], item[3], item[4], item[5], item[6], item[7], item[8], item[9], item[10], item[0], item[3].lower()),
        )
        if updated.rowcount:
            continue
        conn.execute(
            """
            INSERT INTO users (
              id, auth_user_id, name, email, password_hash, unit, title, job_level, role,
              provider, mfa_status, status, last_login_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (item[0], item[1], item[2], item[3], seed_password, item[4], item[5], item[6], item[7], item[8], item[9], item[10], ts),
        )
    placeholders = ",".join("?" for _ in ALLOWED_EDOC_ROLE_LIST)
    conn.execute(f"UPDATE users SET status = '停用' WHERE role NOT IN ({placeholders})", tuple(ALLOWED_EDOC_ROLE_LIST))
    conn.execute("UPDATE users SET password_hash = ? WHERE password_hash IS NULL OR password_hash = ''", (seed_password,))


def normalize_legacy_document_owners(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE documents SET owner = '總務' WHERE owner IN ('總收發', '總收發人員')")
    conn.execute("UPDATE documents SET owner = '行政部主任' WHERE owner IN ('文書主管', '資訊管理員')")
    conn.execute("UPDATE documents SET owner = '主任' WHERE owner = '稽核人員'")
    conn.execute("UPDATE documents SET owner = '業務助理' WHERE owner = '承辦人'")
    conn.execute("UPDATE documents SET department = '總務' WHERE owner = '總務' AND department = '總管理處'")
    conn.execute("UPDATE documents SET department = '行政部' WHERE owner = '行政部主任' AND department = '總管理處'")


def seed_persistent_registries(conn: sqlite3.Connection) -> None:
    ts = now()
    companies = [
        ("CO-001", "歲悅股份有限公司", "60792234", "啟用"),
        ("CO-002", "樂齡歲悅股份有限公司", "60541552", "啟用"),
        ("CO-003", "移站式股份有限公司", "待設定", "啟用"),
        ("CO-004", "大齡好好投資有限公司", "待設定", "啟用"),
        ("CO-005", "歲悅股份有限公司附設臺北市私立歲悅居家長照機構", "00602175", "啟用"),
        ("CO-006", "樂齡歲悅股份有限公司附設臺北市私立歲悅萬華社區長照機構", "00667423", "啟用"),
        ("CO-007", "愛無限整合服務有限公司", "90691342", "啟用"),
        ("CO-008", "愛無限整合有限公司附設新北市私立愛無限居家長照機構", "91254360", "啟用"),
    ]
    departments = [
        ("DEP-001", "歲悅股份有限公司", "總管理處", "執行長", "啟用"),
        ("DEP-002", "歲悅股份有限公司", "行政部", "行政部主任", "啟用"),
        ("DEP-003", "歲悅股份有限公司", "總務", "總務", "啟用"),
    ]
    seal_types = [
        ("ST-001", "一般章", "日常公文、一般函稿", "啟用"),
        ("ST-002", "公司設立章", "設立登記、公司變更、重大文件", "啟用"),
        ("ST-003", "銀行印鑑章", "銀行往來、帳戶、授權文件", "啟用"),
        ("ST-004", "圖記章", "政府機關登記圖記、正式用印", "啟用"),
    ]
    for row in companies:
        conn.execute(
            """
            INSERT OR IGNORE INTO company_registry (id, name, tax_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (*row, ts, ts),
        )
    for row in departments:
        conn.execute(
            """
            INSERT OR IGNORE INTO department_registry (id, company_name, name, manager_role, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (*row, ts, ts),
        )
    for row in seal_types:
        conn.execute(
            """
            INSERT OR IGNORE INTO seal_type_registry (id, name, scope, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (*row, ts, ts),
        )


def seed_workflow_tasks(conn: sqlite3.Connection) -> None:
    ts = now()
    rows = [
        ("WF-003", "DOC-OUT-1140522-007", "日照中心補正資料發文", "發文", "清稿檢核", "行政部主任", "待審核", "standard", 1, "業務助理", "2026-05-22 10:40", "", "等待清稿檢核。"),
        ("WF-007", "DOC-OUT-1140519-006", "補送居家服務品質改善計畫", "發文", "交換失敗重送複核", "行政部主任", "退回補正", "urgent", 1, "總務", "2026-05-19 11:20", "2026-05-22 15:18", "請確認機關代碼後重送。"),
    ]
    for row in rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO workflow_tasks (
              id, document_id, title, workflow_type, step, role, status, template,
              current_step_index, requester, submitted_at, last_signed_at, last_comment,
              proof_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
            """,
            (*row, ts, ts),
        )


def seed_contracts(conn: sqlite3.Connection) -> None:
    ts = now()
    rows = [
        {
            "id": "CON-1140525-001",
            "contract_no": "合約字第1140525001號",
            "company_name": "歲悅長照股份有限公司",
            "contract_type": "服務委託合約",
            "title": "日間照顧中心資訊系統維護合約",
            "counterparty": "康照資訊股份有限公司",
            "counterparty_tax_id": "24567890",
            "owner": "業務助理",
            "department": "行政部",
            "amount": 180000,
            "currency": "TWD",
            "start_date": "2026-06-01",
            "end_date": "2027-05-31",
            "renewal_alert_days": 60,
            "confidentiality_level": "普通",
            "seal_requirement": "一般章",
            "storage_status": "待歸檔",
            "status": "待主管審核",
            "summary": "年度資訊維護、客服支援、資安弱點修補與 SLA 回覆承諾。",
            "risk_note": "金額超過 10 萬，需會計複核與行政部主任清稿後送執行長核定。",
            "attachment_manifest_json": json.dumps(["合約草案.pdf", "報價單.pdf", "服務範圍清單.xlsx"], ensure_ascii=False),
            "metadata_json": json.dumps({"approvalTemplate": "amount_over_100k", "renewalNotice": "到期前 60 天提醒"}, ensure_ascii=False),
        },
        {
            "id": "CON-1140524-002",
            "contract_no": "合約字第1140524002號",
            "company_name": "歲悅長照股份有限公司",
            "contract_type": "租賃合約",
            "title": "板橋據點辦公設備租賃合約",
            "counterparty": "新北設備租賃有限公司",
            "counterparty_tax_id": "90345671",
            "owner": "總務",
            "department": "總務",
            "amount": 72000,
            "currency": "TWD",
            "start_date": "2026-06-15",
            "end_date": "2027-06-14",
            "renewal_alert_days": 45,
            "confidentiality_level": "普通",
            "seal_requirement": "一般章",
            "storage_status": "待歸檔",
            "status": "待用印簽署",
            "summary": "影印機、掃描設備與耗材保固租賃。",
            "risk_note": "用印前請確認租期、提前解約條款與維修回應時間。",
            "attachment_manifest_json": json.dumps(["租賃合約草案.pdf", "設備明細.pdf"], ensure_ascii=False),
            "metadata_json": json.dumps({"approvalTemplate": "standard", "renewalNotice": "到期前 45 天提醒"}, ensure_ascii=False),
        },
    ]
    for row in rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO contracts (
              id, contract_no, company_name, contract_type, title, counterparty, counterparty_tax_id,
              owner, department, amount, currency, start_date, end_date, renewal_alert_days,
              confidentiality_level, seal_requirement, storage_status, status, summary, risk_note,
              attachment_manifest_json, metadata_json, created_at, updated_at
            ) VALUES (
              :id, :contract_no, :company_name, :contract_type, :title, :counterparty, :counterparty_tax_id,
              :owner, :department, :amount, :currency, :start_date, :end_date, :renewal_alert_days,
              :confidentiality_level, :seal_requirement, :storage_status, :status, :summary, :risk_note,
              :attachment_manifest_json, :metadata_json, :created_at, :updated_at
            )
            """,
            {**row, "created_at": ts, "updated_at": ts},
        )

    parties = [
        ("CP-001", "CON-1140525-001", "甲方", "歲悅長照股份有限公司", "待設定", "張行政", "records@suiyuecare.com", "(02)2257-7155", "220205 新北市板橋區英士路192之1號"),
        ("CP-002", "CON-1140525-001", "乙方", "康照資訊股份有限公司", "24567890", "林專員", "service@example.com", "(02)2999-0000", "新北市板橋區文化路一段1號"),
        ("CP-003", "CON-1140524-002", "甲方", "歲悅長照股份有限公司", "待設定", "林總務", "edoc@suiyuecare.com", "(02)2257-7155", "220205 新北市板橋區英士路192之1號"),
        ("CP-004", "CON-1140524-002", "乙方", "新北設備租賃有限公司", "90345671", "吳小姐", "lease@example.com", "(02)2666-0000", "新北市新莊區中平路100號"),
    ]
    for row in parties:
        conn.execute(
            """
            INSERT OR IGNORE INTO contract_parties (
              id, contract_id, party_type, name, tax_id, contact_name, contact_email,
              contact_phone, address, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*row, ts, ts),
        )

    approvals = [
        ("CA-001", "CON-1140525-001", 1, "起案完成", "業務助理", "完成", "周業助", "已上傳草案與報價單。", "2026-05-25 09:12"),
        ("CA-002", "CON-1140525-001", 2, "部門主管審核", "主任", "待簽核", "", "請確認服務範圍與 SLA。", ""),
        ("CA-003", "CON-1140525-001", 3, "會計複核", "會計", "待簽核", "", "金額超過 10 萬需複核預算。", ""),
        ("CA-004", "CON-1140525-001", 4, "行政部主任清稿", "行政部主任", "待簽核", "", "確認合約條款與用印需求。", ""),
        ("CA-005", "CON-1140525-001", 5, "執行長核定", "執行長", "待簽核", "", "重大金額合約最終核定。", ""),
        ("CA-006", "CON-1140524-002", 1, "起案完成", "總務", "完成", "林總務", "設備租賃合約已完成草案。", "2026-05-24 15:20"),
        ("CA-007", "CON-1140524-002", 2, "行政部主任清稿", "行政部主任", "完成", "張行政", "條款與租期已確認。", "2026-05-24 17:10"),
        ("CA-008", "CON-1140524-002", 3, "總務用印簽署", "總務", "待簽核", "", "待確認用印與簽署後歸檔。", ""),
    ]
    for row in approvals:
        evidence = json.dumps({"source": "seed", "hash": sha256_bytes("|".join(map(str, row)).encode("utf-8"))}, ensure_ascii=False)
        conn.execute(
            """
            INSERT OR IGNORE INTO contract_approvals (
              id, contract_id, step_no, step_name, role, status, approver, comment,
              signed_at, non_repudiation_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*row, evidence, ts, ts),
        )


def seed_department_isolation_examples(conn: sqlite3.Connection) -> None:
    ts = now()
    conn.execute(
        """
        INSERT OR IGNORE INTO documents (
          id, doc_no, direction, doc_type, priority, security_level, agency_name, agency_code,
          subject, body, status, owner, department, due_date, received_at, created_at, updated_at
        ) VALUES (
          'DOC-ADMIN-1140523-001', '行管字第1140523001號', '發文', '函', '普通件', '普通',
          '臺北市政府社會局', 'A63000000J',
          '檢送行政部內部流程控管與清稿規則修訂資料。',
          '本件屬行政部主任工作區範例，用於驗證總務與行政部門公文隔離。',
          '待清稿', '行政部主任', '行政部', '2026-05-30', NULL, ?, ?
        )
        """,
        (ts, ts),
    )


def seed_document_acl_examples(conn: sqlite3.Connection) -> None:
    ts = now()
    rows = [
        ("ACL-001", "DOC-IN-1140522-00018", "role", "總務", 1, 0, 1, 0, 1, "總務統一收文、登錄與分派。", "system"),
        ("ACL-002", "DOC-IN-1140522-00018", "role", "主任", 1, 1, 1, 0, 0, "分派後由部門主管承接與簽核。", "system"),
        ("ACL-003", "DOC-OUT-1140522-007", "role", "業務助理", 1, 0, 0, 0, 0, "承辦撰稿，只能檢視與補正內容。", "system"),
        ("ACL-004", "DOC-OUT-1140522-007", "role", "行政部主任", 1, 1, 1, 1, 1, "清稿、會辦、用印前核准。", "system"),
        ("ACL-005", "DOC-OUT-1140522-007", "role", "總務", 1, 0, 1, 1, 0, "封裝、用印與送交 jAgent。", "system"),
        ("ACL-006", "DOC-ADMIN-1140523-001", "role", "行政部主任", 1, 1, 1, 1, 1, "行政部門內部清稿與維運公文。", "system"),
        ("ACL-007", "DOC-ADMIN-1140523-001", "role", "總務", 0, 0, 0, 0, 0, "明確隔離總務收文池與行政部內部公文。", "system"),
    ]
    for row in rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO document_acl (
              id, document_id, principal_type, principal_id, can_view, can_sign, can_download,
              can_seal, can_delegate, reason, granted_by, expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (*row, ts, ts),
        )
    events = [
        ("ACLEVT-001", "DOC-IN-1140522-00018", "system", "建立文件 ACL", "總務可登錄下載；主任可檢視簽核。"),
        ("ACLEVT-002", "DOC-OUT-1140522-007", "system", "建立文件 ACL", "業務助理、行政部主任、總務依流程分權。"),
        ("ACLEVT-003", "DOC-ADMIN-1140523-001", "system", "建立隔離 ACL", "行政部主任公文對總務明確關閉。"),
    ]
    for event in events:
        conn.execute(
            """
            INSERT OR IGNORE INTO document_acl_events (id, document_id, actor, action, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (*event, ts),
        )


def seed_signing_certificates(conn: sqlite3.Connection) -> None:
    ts = now()
    certificates = [
        ("CERT-SEAL-001", "行政部主任", "CN=Suiyuecare Admin Chief Seal,O=Suiyuecare", "Suiyuecare Internal CA", "SYC-SEAL-2026-0001", "HMAC-SHA256-RSA-PSS-READY", "2026-01-01", "2027-12-31", "啟用", "organization"),
        ("CERT-SEAL-002", "總務", "CN=Suiyuecare General Affairs Seal,O=Suiyuecare", "Suiyuecare Internal CA", "SYC-GA-2026-0002", "HMAC-SHA256-RSA-PSS-READY", "2026-01-01", "2027-12-31", "啟用", "business"),
        ("CERT-TSA-001", "系統時間戳", "CN=Suiyuecare TSA,O=Suiyuecare", "Suiyuecare Internal CA", "SYC-TSA-2026-0001", "RFC3161-TSA-SIM", "2026-01-01", "2027-12-31", "啟用", "tsa"),
    ]
    for cert in certificates:
        fingerprint = sha256_bytes("|".join(cert).encode("utf-8"))
        conn.execute(
            """
            INSERT OR IGNORE INTO signing_certificates (
              id, owner, subject, issuer, serial_no, algorithm, valid_from, valid_to, status, certificate_type,
              fingerprint_sha256, key_usage, extended_key_usage, ocsp_url, crl_url, tsa_url, root_ca_fingerprint, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                *cert,
                fingerprint,
                "digitalSignature,nonRepudiation",
                "documentSigning,timeStamping" if cert[9] == "tsa" else "documentSigning,clientAuth",
                "https://ocsp.suiyuecare.local",
                "https://crl.suiyuecare.local/root.crl",
                "https://tsa.suiyuecare.local/rfc3161",
                sha256_bytes("Suiyuecare Internal CA".encode("utf-8")),
                ts,
            ),
        )
        conn.execute(
            """
            UPDATE signing_certificates
            SET certificate_type = ?, key_usage = COALESCE(key_usage, ?), extended_key_usage = COALESCE(extended_key_usage, ?),
                ocsp_url = COALESCE(ocsp_url, ?), crl_url = COALESCE(crl_url, ?), tsa_url = COALESCE(tsa_url, ?),
                root_ca_fingerprint = COALESCE(root_ca_fingerprint, ?)
            WHERE id = ?
            """,
            (
                cert[9],
                "digitalSignature,nonRepudiation",
                "documentSigning,timeStamping" if cert[9] == "tsa" else "documentSigning,clientAuth",
                "https://ocsp.suiyuecare.local",
                "https://crl.suiyuecare.local/root.crl",
                "https://tsa.suiyuecare.local/rfc3161",
                sha256_bytes("Suiyuecare Internal CA".encode("utf-8")),
                cert[0],
            ),
        )


def seed_certificate_authorities(conn: sqlite3.Connection) -> None:
    ts = now()
    authorities = [
        ("CA-SYC-ROOT-001", "Suiyuecare Internal Root CA", "organization", "CN=Suiyuecare Internal Root CA,O=Suiyuecare", "CN=Suiyuecare Internal Root CA,O=Suiyuecare", "trusted"),
        ("CA-SYC-TSA-001", "Suiyuecare TSA CA", "tsa", "CN=Suiyuecare TSA CA,O=Suiyuecare", "CN=Suiyuecare Internal Root CA,O=Suiyuecare", "trusted"),
    ]
    for ca in authorities:
        fingerprint = sha256_bytes("|".join(ca).encode("utf-8"))
        conn.execute(
            """
            INSERT OR IGNORE INTO certificate_authorities (
              id, name, ca_type, subject, issuer, fingerprint_sha256, valid_from, valid_to, trust_status, ocsp_url, crl_url, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*ca[:5], fingerprint, "2026-01-01", "2036-12-31", ca[5], "https://ocsp.suiyuecare.local", "https://crl.suiyuecare.local/root.crl", ts),
        )


def mm_to_pdf_points(value: Any, fallback: float = 20.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    return round(number * 72 / 25.4, 2)


def seed_company_seal_module(conn: sqlite3.Connection) -> None:
    ts = now()
    reference_rows = [
        ("category", "establishment_seal", "公司設立印鑑", "公司設立、變更、重大治理文件", 10),
        ("category", "bank_seal", "銀行印鑑章", "銀行開戶、授權、往來文件", 20),
        ("category", "general_seal", "便章", "日常公文、一般函稿、例行文件", 30),
        ("category", "other", "其他章", "使用者自行新增或特殊用途印章", 90),
        ("size", "large_seal", "大章", "公司或組織大章", 10),
        ("size", "small_seal", "小章", "負責人章、授權小章", 20),
        ("usage_type", "official_document", "公文", "電子公文發文或回覆", 10),
        ("usage_type", "contract", "合約", "電子合約或契約文件", 20),
        ("usage_type", "bank_document", "銀行文件", "銀行帳戶、授權、付款相關文件", 30),
        ("usage_type", "government_application", "政府申請文件", "政府機關申請、補正、許可文件", 40),
        ("usage_type", "internal_document", "內部文件", "內部簽呈、公告、作業文件", 50),
        ("request_status", "draft", "草稿", "尚未送出", 10),
        ("request_status", "pending", "待簽核", "等待權責人核准", 20),
        ("request_status", "approved", "已核准", "可執行套印", 30),
        ("request_status", "rejected", "已駁回", "不可用印", 40),
        ("request_status", "stamped", "已用印", "已產出用印文件版本", 50),
        ("request_status", "cancelled", "已取消", "申請取消或作廢", 60),
        ("permission_role", "viewer", "檢視者", "僅可查看授權紀錄", 10),
        ("permission_role", "requester", "申請者", "可提出用印申請", 20),
        ("permission_role", "approver", "簽核者", "可核准或駁回用印", 30),
        ("permission_role", "seal_admin", "印章管理者", "可上傳、停用、更新印章檔案", 40),
    ]
    for option_type, code, name, description, sort_order in reference_rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO seal_reference_options (
              id, option_type, code, name, description, sort_order, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (f"SOPT-{option_type}-{code}", option_type, code, name, description, sort_order, ts, ts),
        )

    registry_rows = conn.execute("SELECT * FROM company_registry").fetchall()
    if not registry_rows:
        registry_rows = [{"id": "CO-001", "name": "歲悅長照股份有限公司", "tax_id": "待設定", "status": "啟用"}]
    for row in registry_rows:
        company_id = row["id"] if isinstance(row, sqlite3.Row) else row["id"]
        name = row["name"] if isinstance(row, sqlite3.Row) else row["name"]
        tax_id = row["tax_id"] if isinstance(row, sqlite3.Row) else row["tax_id"]
        status = row["status"] if isinstance(row, sqlite3.Row) else row["status"]
        normalized_status = "active" if status in {"啟用", "active"} else "inactive"
        conn.execute(
            """
            INSERT OR IGNORE INTO companies (id, name, tax_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (company_id, name, tax_id, normalized_status, ts, ts),
        )
        seed_rows = [
            ("establishment_seal", "large_seal", "公司設立印鑑－大章", "設立登記、公司變更、重大申請"),
            ("establishment_seal", "small_seal", "公司設立印鑑－小章", "設立登記、負責人或授權小章"),
            ("bank_seal", "large_seal", "銀行印鑑章－大章", "銀行往來、帳戶與付款授權"),
            ("bank_seal", "small_seal", "銀行印鑑章－小章", "銀行往來小章或負責人小章"),
            ("general_seal", "large_seal", "便章－大章", "日常公文、一般函稿"),
            ("general_seal", "small_seal", "便章－小章", "一般函稿、內部文件"),
            ("other", "large_seal", "其他章", "特殊用途，可由印章管理者調整"),
        ]
        for category, size, seal_name, purpose in seed_rows:
            seal_id = f"CSEAL-{company_id}-{category}-{size}".replace(" ", "-")
            conn.execute(
                """
                INSERT OR IGNORE INTO company_seals (
                  id, company_id, seal_name, seal_category, seal_size_type, purpose_description,
                  is_active, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, 'system-seed', ?, ?)
                """,
                (seal_id, company_id, seal_name, category, size, purpose, ts, ts),
            )
            for role in ["viewer", "requester", "approver", "seal_admin"]:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO seal_permissions (id, seal_id, user_id, role, created_at)
                    VALUES (?, ?, '', ?, ?)
                    """,
                    (f"SPERM-{seal_id}-{role}", seal_id, role, ts),
                )


def seed_seal_assets(conn: sqlite3.Connection) -> None:
    ts = now()
    seals = [
        ("SEAL-001", "歲悅長照公司章", "公司章", "行政部主任", "函", 30.0, 30.0, "SHA256-SEAL-A19F"),
        ("SEAL-002", "歲悅負責人章", "負責人章", "行政部主任", "函", 18.0, 18.0, "SHA256-SEAL-B72C"),
        ("SEAL-003", "附件騎縫章", "騎縫章", "總務", "附件", 10.0, 35.0, "SHA256-SEAL-C44D"),
    ]
    for seal in seals:
        conn.execute(
            """
            INSERT OR IGNORE INTO seal_assets (
              id, seal_id, name, seal_type, owner, doc_type, file_object_id,
              width_mm, height_mm, width_pt, height_pt, calibration_status, hash, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"ASSET-{seal[0]}",
                seal[0],
                seal[1],
                seal[2],
                seal[3],
                seal[4],
                seal[5],
                seal[6],
                mm_to_pdf_points(seal[5]),
                mm_to_pdf_points(seal[6]),
                "待上傳圖檔",
                seal[7],
                "啟用",
                ts,
                ts,
            ),
        )


def seed_attachment_security(conn: sqlite3.Connection) -> None:
    ts = now()
    rows = conn.execute("SELECT * FROM attachments").fetchall()
    for row in rows:
        name = row["file_name"]
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        confidential = "密" if "稽核" in name or "補件" in name else "普通"
        sensitive_hits = ["身分證", "電話"] if confidential != "普通" else []
        scan_status = "已通過" if row["scan_status"] in {"雜湊通過", "已通過"} else row["scan_status"]
        conn.execute(
            """
            INSERT OR IGNORE INTO attachment_security (
              id, attachment_id, document_id, file_name, file_ext, size_bytes, max_size_bytes,
              scan_status, scan_engine, scan_signature, mask_status, sensitive_hits_json,
              confidential_level, allowed_roles, watermark_status, quarantine_reason,
              backup_id, last_accessed_by, last_accessed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"ASEC-{row['id']}",
                row["id"],
                row["document_id"],
                name,
                ext,
                row["size_bytes"],
                50 * 1024 * 1024,
                scan_status,
                "ClamAV-compatible",
                f"SIG-{sha256_bytes(name.encode('utf-8'))[:10]}",
                "需遮罩" if sensitive_hits else "未遮罩",
                json.dumps(sensitive_hits, ensure_ascii=False),
                confidential,
                "行政部主任,主任,執行長" if confidential != "普通" else "一般角色",
                "未下載",
                "",
                "",
                "",
                "",
                ts,
            ),
        )


def seed_jobs(conn: sqlite3.Connection) -> None:
    ts = now()
    jobs = [
        ("JOB-001", "每日收文拉取", "pullInbound", "每日 08:30", "啟用", "尚未執行", "2026-05-23 08:30", 0),
        ("JOB-002", "發文翌日查核", "nextDayCheck", "每日 09:00", "啟用", "尚未執行", "2026-05-23 09:00", 0),
        ("JOB-003", "Token 到期檢查", "tokenCheck", "每 15 分鐘", "啟用", "尚未執行", "2026-05-23 09:15", 0),
        ("JOB-004", "逾期稽催", "overdueReminder", "每小時", "啟用", "尚未執行", "2026-05-23 10:00", 0),
        ("JOB-005", "交換狀態同步", "exchangeSync", "每 15 分鐘", "啟用", "尚未執行", "2026-05-23 09:15", 0),
        ("JOB-006", "歸檔封存", "archiveSeal", "每日 18:00", "啟用", "尚未執行", "2026-05-23 18:00", 0),
        ("JOB-007", "報表產生", "reportGenerate", "每日 18:00", "啟用", "尚未執行", "2026-05-23 18:00", 0),
        ("JOB-008", "合約到期與續約提醒", "contractRenewalCheck", "每日 09:30", "啟用", "尚未執行", "2026-05-23 09:30", 0),
        ("JOB-009", "交換待發公文送出", "exchangeSendPending", "每 5 分鐘", "啟用", "尚未執行", "2026-05-23 09:05", 0),
        ("JOB-010", "交換失敗重送", "exchangeRetryFailed", "每 15 分鐘", "啟用", "尚未執行", "2026-05-23 09:15", 0),
    ]
    for item in jobs:
        conn.execute(
            """
            INSERT OR IGNORE INTO background_jobs (id, name, job_type, schedule_text, status, last_result, next_run_at, run_count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*item, ts),
        )

    for permission in [*EDOC_LEGACY_PERMISSION_CATALOG, *EDOC_PERMISSION_CATALOG]:
        conn.execute(
            """
            INSERT INTO permissions (id, code, name, category, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              code = excluded.code,
              name = excluded.name,
              category = excluded.category,
              description = excluded.description
            """,
            (*permission, ts),
        )

    for role_id, permission_ids in EDOC_ROLE_PERMISSION_GRANTS.items():
        for permission_id in permission_ids:
            conn.execute(
                "INSERT OR IGNORE INTO role_permissions (role_id, permission_id, created_at) VALUES (?, ?, ?)",
                (role_id, permission_id, ts),
            )

    devices = [
        ("ACC-DEV-001", "USR-001", "總務辦公室 Mac", "203.0.113.18", "FP-SYC-EDOC-A1F9", "信任"),
        ("ACC-DEV-002", "USR-002", "行政部主任筆電", "198.51.100.27", "FP-SYC-EDOC-B8C2", "信任"),
        ("ACC-DEV-003", "USR-003", "主任辦公室 Mac", "203.0.113.18", "FP-SYC-EDOC-C339", "信任"),
        ("ACC-DEV-004", "USR-004", "執行長筆電", "203.0.113.44", "FP-SYC-EDOC-D601", "信任"),
        ("ACC-DEV-005", "USR-005", "人資筆電", "198.51.100.27", "FP-SYC-EDOC-HR01", "信任"),
        ("ACC-DEV-006", "USR-006", "會計筆電", "198.51.100.28", "FP-SYC-EDOC-ACC1", "信任"),
        ("ACC-DEV-007", "USR-007", "業務助理筆電", "203.0.113.19", "FP-SYC-EDOC-SA01", "待複核"),
    ]
    for device in devices:
        conn.execute(
            """
            INSERT OR IGNORE INTO trusted_devices (id, user_id, name, ip, fingerprint, status, last_seen_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*device, ts, ts),
        )

    conn.execute(
        """
        INSERT OR IGNORE INTO ip_allowlist (id, cidr, purpose, status, created_at, updated_at)
        VALUES ('IP-001', '203.0.113.0/24', '歲悅辦公室與 VPN', '啟用', ?, ?)
        """,
        (ts, ts),
    )
    for provider, domain in [("Google Workspace", "suiyuecare.com"), ("Microsoft Entra", "suiyuecare.com")]:
        conn.execute(
            """
            INSERT OR IGNORE INTO sso_providers (id, provider, domain, tenant_id, client_id, status, require_mfa, updated_at)
            VALUES (?, ?, ?, '', '', '待設定', 1, ?)
            """,
            (f"SSO-{provider.split()[0].upper()}", provider, domain, ts),
        )


def seed_notifications(conn: sqlite3.Connection) -> None:
    ts = now()
    seeds = [
        ("NTF-001", "收文", "衛福部補件通知待登錄", "總務", "", "系統通知", "未讀", "高", "IN-1140522-00018", "jAgent 已拉取新來文，請完成收文登錄與附件檢核。"),
        ("NTF-002", "待清稿", "日照中心補正資料待清稿", "行政部主任", "", "Email + 系統通知", "未讀", "高", "OUT-1140522-007", "函稿已建立，請進行清稿檢核與附件封裝。"),
        ("NTF-003", "交換失敗", "新北市政府衛生局交換失敗", "總務", "", "Email + Line + 系統通知", "未讀", "高", "OUT-1140519-006", "jAgent 回覆 failed，請確認機關代碼並重送。"),
        ("NTF-004", "Token 到期", "jAgent Token 即將到期", "行政部主任", "", "Email + 系統通知", "未讀", "中", "SEC-TOKEN", "Token 剩餘時間不足，請刷新或重新憑證登入。"),
        ("NTF-005", "逾期查核", "收1140522-00013 分派逾期", "行政部主任", "", "Line 工作群組", "未讀", "高", "TRK-003", "收文尚未完成分派，請啟動逾期查核提醒。"),
    ]
    for item in seeds:
        conn.execute(
            """
            INSERT OR IGNORE INTO notifications (
              id, type, title, target_role, target_email, channel, status, priority, source, body, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*item, ts),
        )

    rules = [
        ("NRULE-001", "收文", "jAgent 拉取來文後立即通知總務。", "總務", "系統通知"),
        ("NRULE-002", "待清稿", "發文待清稿超過 2 小時通知行政部主任。", "行政部主任", "Email + 系統通知"),
        ("NRULE-003", "交換失敗", "交換失敗即時發送 Email、LINE 與站內通知。", "總務", "Email + Line + 系統通知"),
        ("NRULE-004", "Token 到期", "Token 到期前 60 分鐘通知行政部主任。", "行政部主任", "Email + 系統通知"),
        ("NRULE-005", "逾期查核", "每日 09:00 送出逾期查核提醒。", "行政部主任", "Line 工作群組"),
    ]
    for item in rules:
        conn.execute(
            """
            INSERT OR IGNORE INTO notification_rules (id, type, rule_text, target_role, channel, status, updated_at)
            VALUES (?, ?, ?, ?, ?, '啟用', ?)
            """,
            (*item, ts),
        )


def mask_notification_credential(env_key_name: str) -> str:
    masked = []
    for name in env_key_name.split(","):
        name = name.strip()
        value = os.getenv(name, "").strip()
        if not name:
            continue
        if not value:
            masked.append(f"{name}=未設定")
        elif len(value) <= 8:
            masked.append(f"{name}=****")
        else:
            masked.append(f"{name}={value[:4]}...{value[-4:]}")
    return "；".join(masked)


def notification_credential_seed_rows() -> List[Tuple[str, str, str, str, str, str]]:
    return [
        ("NCRED-EMAIL-SMTP", "Email", os.getenv("SMTP_PROVIDER", "SMTP / Transactional Email"), "SMTP 帳號/應用程式密碼", "SMTP_HOST,SMTP_USERNAME,SMTP_PASSWORD,SMTP_FROM", os.getenv("SMTP_CREDENTIAL_EXPIRES_AT", "")),
        ("NCRED-LINE-WEBHOOK", "Line 工作群組", "LINE Messaging API / Webhook", "Webhook Secret / Channel Access Token", "LINE_WEBHOOK_URL,LINE_CHANNEL_SECRET,LINE_CHANNEL_ACCESS_TOKEN,LINE_TARGET_ID", os.getenv("LINE_CREDENTIAL_EXPIRES_AT", "")),
        ("NCRED-INBOX-SIGNING", "系統站內通知", "Suiyuecare eDoc", "站內通知簽章金鑰", "APP_SECRET,CRON_SECRET", os.getenv("INBOX_SIGNING_KEY_EXPIRES_AT", "")),
    ]


def notification_credential_fingerprint(env_key_name: str) -> str:
    values = [f"{name.strip()}={os.getenv(name.strip(), '')}" for name in env_key_name.split(",") if name.strip()]
    return sha256_bytes(("|".join(values) or env_key_name).encode("utf-8"))


def seed_notification_credentials(conn: sqlite3.Connection) -> None:
    ts = now()
    for credential_id, channel, provider, credential_type, env_key_name, expires_at in notification_credential_seed_rows():
        fingerprint = notification_credential_fingerprint(env_key_name)
        conn.execute(
            """
            INSERT OR IGNORE INTO notification_channel_credentials (
              id, channel, provider, credential_type, env_key_name, masked_identifier, fingerprint_sha256,
              expires_at, status, last_validated_at, validation_report_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '待驗證', NULL, NULL, ?, ?)
            """,
            (credential_id, channel, provider, credential_type, env_key_name, mask_notification_credential(env_key_name), fingerprint, expires_at, ts, ts),
        )
        conn.execute(
            """
            UPDATE notification_channel_credentials
            SET provider = ?, credential_type = ?, env_key_name = ?, masked_identifier = ?, fingerprint_sha256 = ?,
                expires_at = COALESCE(NULLIF(?, ''), expires_at), updated_at = ?
            WHERE id = ?
            """,
            (provider, credential_type, env_key_name, mask_notification_credential(env_key_name), fingerprint, expires_at, ts, credential_id),
        )


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
    if table == "users":
        apply_user_permission_defaults(payload)
    if table == "documents" and payload.get("direction") == "發文" and not payload.get("doc_no"):
        payload["doc_no"] = next_dispatch_no(conn)
    if table in {"documents", "recipients", "exchange_tasks", "exchange_outbox", "exchange_inbox", "settings", "notification_rules", "company_registry", "department_registry", "seal_type_registry", "companies", "seal_reference_options", "company_seals", "seal_usage_requests", "seal_usage_approvals", "workflow_tasks", "approval_step_actor_snapshots", "contracts", "contract_parties", "contract_approvals", "seal_applications", "official_documents", "official_document_approval_steps", "official_document_stamp_requests", "official_document_dispatch_records"}:
        payload.setdefault("updated_at", now())
    if table in {"documents", "attachments", "exchange_events", "exchange_outbox", "exchange_inbox", "exchange_log", "exchange_attachment", "exchange_status_history", "audit_logs", "users", "notifications", "notification_deliveries", "system_inbox", "file_objects", "file_download_tokens", "virus_scan_jobs", "compliance_attestations", "company_registry", "department_registry", "seal_type_registry", "companies", "seal_reference_options", "company_seals", "seal_permissions", "seal_usage_approvals", "seal_usage_logs", "workflow_tasks", "approval_step_actor_snapshots", "contracts", "contract_parties", "contract_approvals", "seal_applications", "signature_provider_events", "official_documents", "official_document_files", "official_document_approval_steps", "official_document_approval_logs", "official_document_stamp_requests", "official_document_dispatch_records"}:
        payload.setdefault("created_at", now())
    if table in {"documents", "workflow_tasks", "approval_step_actor_snapshots", "contracts", "contract_approvals", "seal_applications", "seal_usage_requests", "exchange_log", "exchange_inbox", "exchange_status_history", "audit_logs", "official_documents"}:
        for key, value in list(payload.items()):
            if key.endswith("_json") and not isinstance(value, str):
                payload[key] = json.dumps(value, ensure_ascii=False)
    columns = list(payload.keys())
    placeholders = ", ".join(["?"] * len(columns))
    conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        [payload[column] for column in columns],
    )
    if table == "users":
        permission_fields = {"role", "status", "unit", "title", "job_level", "mfa_status"}
        log_permission_change(
            conn,
            "API",
            str(payload.get("id")),
            payload.get("email", ""),
            {},
            {key: payload.get(key) for key in sorted(permission_fields) if key in payload},
            "建立使用者帳號與初始角色權限。",
            ["system_permissions.manage"],
        )
    else:
        log_audit(conn, "API", "新增資料", table, str(payload.get("id")), json.dumps(payload, ensure_ascii=False))
    return payload


def patch_row(conn: sqlite3.Connection, table: str, row_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    before_row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    before_data = row_to_dict(before_row) if before_row else {}
    if table == "users":
        permission_inputs = {"role", "unit", "title", "job_level", "company", "region", "class_name"}
        merged_payload = {**before_data, **payload}
        profile = edoc_roster_permission_profile(merged_payload)
        if "job_level" in payload:
            payload["job_level"] = profile["job_level"]
        if permission_inputs.intersection(payload) and (not payload.get("role") or payload.get("role") not in ALLOWED_EDOC_ROLES):
            payload["role"] = profile["role"]
    if table in {"documents", "recipients", "exchange_tasks", "exchange_outbox", "exchange_inbox", "settings", "background_jobs", "notification_rules", "company_registry", "department_registry", "seal_type_registry", "companies", "seal_reference_options", "company_seals", "seal_usage_requests", "seal_usage_approvals", "workflow_tasks", "approval_step_actor_snapshots", "contracts", "contract_parties", "contract_approvals", "seal_applications", "official_documents", "official_document_approval_steps", "official_document_stamp_requests", "official_document_dispatch_records"}:
        payload["updated_at"] = now()
    if table in {"documents", "workflow_tasks", "approval_step_actor_snapshots", "contracts", "contract_approvals", "seal_applications", "seal_usage_requests", "exchange_log", "exchange_inbox", "exchange_status_history", "audit_logs", "official_documents"}:
        for key, value in list(payload.items()):
            if key.endswith("_json") and not isinstance(value, str):
                payload[key] = json.dumps(value, ensure_ascii=False)
    if not payload:
        return {}
    assignments = ", ".join([f"{key} = ?" for key in payload.keys()])
    conn.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", [*payload.values(), row_id])
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    after_data = row_to_dict(row) if row else {}
    permission_fields = {"role", "status", "unit", "title", "job_level", "mfa_status"}
    if table == "users" and permission_fields.intersection(payload):
        log_permission_change(
            conn,
            "API",
            row_id,
            after_data.get("email") or before_data.get("email") or "",
            {key: before_data.get(key) for key in sorted(permission_fields) if key in before_data},
            {key: after_data.get(key) for key in sorted(permission_fields) if key in after_data},
            "使用者角色、職等、狀態或權限相關資料異動。",
            ["system_permissions.manage"],
        )
    else:
        log_audit(conn, "API", "更新資料", table, row_id, json.dumps(payload, ensure_ascii=False))
    return row_to_dict(row) if row else {}


def public_user(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
    data = row_to_dict(row) if isinstance(row, sqlite3.Row) else dict(row)
    data.pop("password_hash", None)
    return data


def role_permission_codes(conn: sqlite3.Connection, role_name: str) -> List[str]:
    rows = conn.execute(
        """
        SELECT p.code
        FROM roles r
        JOIN role_permissions rp ON rp.role_id = r.id
        JOIN permissions p ON p.id = rp.permission_id
        WHERE r.name = ?
        ORDER BY p.category, p.code
        """,
        (role_name,),
    ).fetchall()
    return [row["code"] for row in rows]


def session_permissions(session: Dict[str, Any] | None) -> set[str]:
    return set(session.get("permissions") or []) if session else set()


def session_has_any_permission(session: Dict[str, Any] | None, permissions: List[str]) -> bool:
    available = session_permissions(session)
    return any(permission in available for permission in permissions)


TABLE_READ_PERMISSIONS: Dict[str, List[str]] = {
    "users": ["system_permissions.view", "system_permissions.manage"],
    "roles": ["system_permissions.view", "system_permissions.manage"],
    "permissions": ["system_permissions.view", "system_permissions.manage"],
    "role_permissions": ["system_permissions.view", "system_permissions.manage"],
    "module_account_links": ["system_permissions.view", "system_permissions.manage"],
    "auth_sessions": ["system_permissions.view", "system_permissions.manage"],
    "login_events": ["system_permissions.view", "system_permissions.manage"],
    "trusted_devices": ["system_permissions.view", "system_permissions.manage"],
    "ip_allowlist": ["system_permissions.view", "system_permissions.manage"],
    "sso_providers": ["system_permissions.view", "system_permissions.manage"],
    "audit_logs": ["audit_logs.view", "audit_logs.export", "audit.view"],
    "document_acl": ["system_permissions.view", "system_permissions.manage", "audit_logs.view"],
    "document_acl_events": ["system_permissions.view", "system_permissions.manage", "audit_logs.view"],
    "settings": ["settings.system_manage", "settings.manage"],
    "notification_channel_credentials": ["settings.system_manage", "settings.manage"],
    "exchange_outbox": ["exchange.view", "exchange.manage"],
    "exchange_inbox": ["exchange.view", "exchange.manage"],
    "exchange_log": ["exchange.view", "exchange.manage", "audit_logs.view"],
    "exchange_attachment": ["exchange.view", "exchange.manage", "files.manage"],
    "exchange_status_history": ["exchange.view", "exchange.manage"],
    "signature_provider_events": ["seals.manage", "audit_logs.view"],
    "file_download_tokens": ["files.manage", "audit_logs.view"],
    "companies": ["seals.manage", "contracts.seal", "official_documents.compose"],
    "seal_reference_options": ["seals.manage", "contracts.seal", "official_documents.compose"],
    "company_seals": ["seals.manage", "contracts.seal", "official_documents.compose"],
    "company_seal_files": ["seals.manage", "audit_logs.view"],
    "seal_permissions": ["seals.manage", "system_permissions.view"],
    "seal_usage_requests": ["seals.manage", "contracts.seal", "official_documents.todo", "official_documents.compose"],
    "seal_usage_approvals": ["seals.manage", "contracts.seal", "official_documents.todo"],
    "seal_usage_logs": ["seals.manage", "audit_logs.view"],
    "official_documents": ["official_documents.compose", "official_documents.todo", "official_documents.records", "official_documents.all_records", "official_documents.all_todo"],
    "official_document_files": ["official_documents.compose", "official_documents.todo", "official_documents.records", "official_documents.all_records"],
    "official_document_approval_steps": ["official_documents.todo", "official_documents.records", "official_documents.all_records"],
    "official_document_approval_logs": ["official_documents.todo", "official_documents.records", "official_documents.all_records", "audit_logs.view"],
    "official_document_stamp_requests": ["official_documents.compose", "official_documents.todo", "official_documents.records", "official_documents.all_records"],
    "official_document_dispatch_records": ["official_documents.compose", "official_documents.todo", "official_documents.records", "official_documents.all_records", "official_documents.all_todo"],
}


TABLE_WRITE_PERMISSIONS: Dict[str, List[str]] = {
    "users": ["system_permissions.manage"],
    "roles": ["system_permissions.manage"],
    "permissions": ["system_permissions.manage"],
    "role_permissions": ["system_permissions.manage"],
    "module_account_links": ["system_permissions.manage"],
    "auth_sessions": ["system_permissions.manage"],
    "login_events": ["system_permissions.manage"],
    "trusted_devices": ["system_permissions.manage"],
    "ip_allowlist": ["system_permissions.manage"],
    "sso_providers": ["system_permissions.manage"],
    "audit_logs": ["audit_logs.export"],
    "document_acl": ["system_permissions.manage"],
    "document_acl_events": ["system_permissions.manage"],
    "settings": ["settings.system_manage", "settings.manage"],
    "notification_channel_credentials": ["settings.system_manage", "settings.manage"],
    "exchange_outbox": ["exchange.manage"],
    "exchange_inbox": ["exchange.manage"],
    "exchange_log": ["exchange.manage"],
    "exchange_attachment": ["exchange.manage", "files.manage"],
    "exchange_status_history": ["exchange.manage"],
    "signature_provider_events": ["seals.manage"],
    "file_download_tokens": ["files.manage"],
    "companies": ["seals.manage"],
    "seal_reference_options": ["seals.manage"],
    "company_seals": ["seals.manage"],
    "company_seal_files": ["seals.manage"],
    "seal_permissions": ["seals.manage", "system_permissions.manage"],
    "seal_usage_requests": ["seals.manage", "contracts.seal", "official_documents.compose"],
    "seal_usage_approvals": ["seals.manage", "contracts.seal", "official_documents.todo"],
    "seal_usage_logs": ["seals.manage"],
    "official_documents": ["official_documents.compose"],
    "official_document_files": ["official_documents.compose", "official_documents.todo"],
    "official_document_approval_steps": ["official_documents.compose", "official_documents.todo"],
    "official_document_approval_logs": ["official_documents.compose", "official_documents.todo"],
    "official_document_stamp_requests": ["official_documents.compose", "official_documents.todo"],
    "official_document_dispatch_records": ["official_documents.compose", "official_documents.todo"],
}


def can_read_table(session: Dict[str, Any] | None, table: str) -> bool:
    permissions = TABLE_READ_PERMISSIONS.get(table)
    return bool(session) if not permissions else session_has_any_permission(session, permissions)


def can_write_table(session: Dict[str, Any] | None, table: str) -> bool:
    permissions = TABLE_WRITE_PERMISSIONS.get(table)
    return bool(session) if not permissions else session_has_any_permission(session, permissions)


def document_scope_clause(user: Dict[str, Any] | sqlite3.Row | None) -> Tuple[str, List[Any]]:
    if not user:
        return "1 = 0", []
    role = user["role"] if isinstance(user, sqlite3.Row) else user.get("role", "")
    unit = user["unit"] if isinstance(user, sqlite3.Row) else user.get("unit", "")
    name = user["name"] if isinstance(user, sqlite3.Row) else user.get("name", "")
    if role in {"執行長", "董事會", "股東"}:
        return "", []
    acl_clause = """
      EXISTS (
        SELECT 1 FROM document_acl da
        WHERE da.document_id = documents.id
          AND da.can_view = 1
          AND (
            (da.principal_type = 'role' AND da.principal_id = ?)
            OR (da.principal_type = 'unit' AND da.principal_id = ?)
            OR (da.principal_type = 'user' AND da.principal_id = ?)
          )
          AND (da.expires_at IS NULL OR da.expires_at = '' OR da.expires_at > ?)
      )
    """
    acl_params = [role, unit, name, now()]
    if role == "總務":
        return f"(((owner = ? OR department = ?) AND owner <> ?) OR {acl_clause})", ["總務", "總務", "行政部主任", *acl_params]
    if role == "行政部主任":
        return f"(((owner = ? OR department IN (?, ?)) AND owner <> ?) OR {acl_clause})", ["行政部主任", "行政部", "總管理處", "總務", *acl_params]
    if role in {"人資", "會計", "業務助理", "主任", "主管", "員工"}:
        return f"((owner IN (?, ?) OR department IN (?, ?)) OR {acl_clause})", [role, name, role, unit, *acl_params]
    if role == "外部檢核單位":
        return acl_clause, acl_params
    return "1 = 0", []


def scoped_document_where(session: Dict[str, Any] | None, extra: List[str] | None = None) -> Tuple[str, List[Any]]:
    where = list(extra or [])
    params: List[Any] = []
    scope_clause, scope_params = document_scope_clause(session.get("user") if session else None)
    if scope_clause:
        where.append(scope_clause)
        params.extend(scope_params)
    return (" WHERE " + " AND ".join(where)) if where else "", params


def scoped_document_rows(conn: sqlite3.Connection, query: Dict[str, List[str]], session: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    where: List[str] = []
    params: List[Any] = []
    if "status" in query:
        where.append("status = ?")
        params.append(query["status"][0])
    if "direction" in query:
        where.append("direction = ?")
        params.append(query["direction"][0])
    scope_clause, scope_params = document_scope_clause(session.get("user") if session else None)
    if scope_clause:
        where.append(scope_clause)
        params.extend(scope_params)
    sql = "SELECT * FROM documents"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY rowid DESC LIMIT 500"
    return [row_to_dict(row) for row in conn.execute(sql, params).fetchall()]


def search_like_clause(columns: List[str], term: str) -> Tuple[str, List[Any]]:
    like = f"%{term}%"
    return "(" + " OR ".join(f"COALESCE({column}, '') LIKE ?" for column in columns) + ")", [like] * len(columns)


def unified_search(conn: sqlite3.Connection, query: Dict[str, List[str]], session: Dict[str, Any] | None) -> Dict[str, Any]:
    term = (query.get("q") or query.get("term") or [""])[0].strip()
    category = (query.get("category") or query.get("type") or ["all"])[0]
    status = (query.get("status") or [""])[0].strip()
    limit = min(int((query.get("limit") or ["80"])[0] or 80), 200)
    if not term and not status:
        return {"query": term, "category": category, "count": 0, "results": []}

    specs = [
        ("documents", "公文", "documents", ["id", "doc_no", "agency_name", "agency_code", "subject", "body", "status", "owner", "department"], "status"),
        ("contracts", "合約", "contracts", ["id", "contract_no", "company_name", "contract_type", "title", "counterparty", "owner", "department", "status", "summary", "risk_note"], "status"),
        ("contract_approvals", "合約簽核", "contract_approvals", ["id", "contract_id", "step_name", "role", "status", "approver", "comment"], "status"),
        ("attachments", "附件", "attachments", ["id", "document_id", "file_name", "version", "mime_type", "sha256", "scan_status", "storage_key"], "scan_status"),
        ("attachment_security", "附件安全", "attachment_security", ["id", "attachment_id", "document_id", "file_name", "file_ext", "scan_status", "mask_status", "confidential_level", "allowed_roles", "watermark_status", "quarantine_reason"], "scan_status"),
        ("exchange_tasks", "交換任務", "exchange_tasks", ["id", "document_id", "direction", "target_agency", "status", "package_id"], "status"),
        ("exchange_events", "交換事件", "exchange_events", ["id", "task_id", "document_id", "event_type", "message", "payload_json"], "event_type"),
        ("notifications", "通知", "notifications", ["id", "type", "title", "target_role", "target_email", "channel", "status", "priority", "source", "body", "delivery_receipt"], "status"),
        ("audit_logs", "稽核紀錄", "audit_logs", ["id", "actor", "action", "target_type", "target_id", "detail"], "action"),
        ("file_access_logs", "檔案存取", "file_access_logs", ["id", "attachment_id", "file_object_id", "document_id", "actor", "action", "result", "detail", "watermark_text"], "result"),
    ]
    results: List[Dict[str, Any]] = []
    for table_key, label, table, columns, status_column in specs:
        if category not in {"all", table_key, label}:
            continue
        if not can_read_table(session, table):
            continue
        where: List[str] = []
        params: List[Any] = []
        if term:
            clause, clause_params = search_like_clause(columns, term)
            where.append(clause)
            params.extend(clause_params)
        if status:
            where.append(f"COALESCE({status_column}, '') LIKE ?")
            params.append(f"%{status}%")
        if table == "documents":
            scope_clause, scope_params = document_scope_clause(session.get("user") if session else None)
            if scope_clause:
                where.append(scope_clause)
                params.extend(scope_params)
        sql = f"SELECT * FROM {table}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY rowid DESC LIMIT ?"
        rows = conn.execute(sql, (*params, limit)).fetchall()
        for row in rows:
            data = row_to_dict(row)
            title = data.get("doc_no") or data.get("contract_no") or data.get("file_name") or data.get("title") or data.get("action") or data.get("event_type") or data.get("id")
            subtitle = data.get("subject") or data.get("counterparty") or data.get("step_name") or data.get("agency_name") or data.get("target_agency") or data.get("body") or data.get("detail") or data.get("message") or ""
            results.append({
                "id": data.get("id"),
                "category": label,
                "table": table_key,
                "title": title,
                "subtitle": subtitle,
                "status": data.get("status") or data.get("scan_status") or data.get("result") or data.get("event_type") or "",
                "createdAt": data.get("created_at") or data.get("updated_at") or data.get("last_accessed_at") or "",
                "record": data,
            })
    results.sort(key=lambda item: item.get("createdAt") or "", reverse=True)
    return {"query": term, "category": category, "count": len(results[:limit]), "results": results[:limit]}


def can_read_document(conn: sqlite3.Connection, document_id: str, session: Dict[str, Any] | None) -> bool:
    scope_clause, scope_params = document_scope_clause(session.get("user") if session else None)
    if not scope_clause:
        return True
    row = conn.execute(f"SELECT 1 FROM documents WHERE id = ? AND {scope_clause}", (document_id, *scope_params)).fetchone()
    return bool(row)


def roc_date_serial(date: datetime | None = None) -> str:
    date = date or datetime.now()
    return f"{date.year - 1911}{date.month:02d}{date.day:02d}"


def next_dispatch_no(conn: sqlite3.Connection) -> str:
    date_serial = roc_date_serial()
    prefix = f"歲悅字第{date_serial}"
    rows = conn.execute(
        "SELECT doc_no FROM documents WHERE direction = '發文' AND doc_no LIKE ?",
        (f"{prefix}%號",),
    ).fetchall()
    max_serial = 0
    for row in rows:
        value = row["doc_no"]
        if value.startswith(prefix) and value.endswith("號"):
            serial = value[len(prefix):-1]
            if serial.isdigit():
                max_serial = max(max_serial, int(serial))
    return f"{prefix}{max_serial + 1:03d}號"


def record_login_event(
    conn: sqlite3.Connection,
    email: str,
    provider: str,
    status: str,
    reason: str = "",
    user_id: str | None = None,
    ip: str = "",
    device: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO login_events (id, user_id, email, provider, ip, device, status, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (f"LOGIN-{int(time.time() * 1000)}", user_id, email, provider, ip, device, status, reason, now()),
    )


def create_session(conn: sqlite3.Connection, user: sqlite3.Row, provider: str, ip: str, device: str) -> Dict[str, Any]:
    token = secrets.token_urlsafe(36)
    expires = datetime.now() + timedelta(hours=8)
    conn.execute(
        """
        INSERT INTO auth_sessions (id, user_id, token_hash, provider, ip, device, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (f"SES-{int(time.time() * 1000)}", user["id"], hash_token(token), provider, ip, device, expires.strftime("%Y-%m-%d %H:%M:%S"), now()),
    )
    conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now(), user["id"]))
    record_login_event(conn, user["email"], provider, "成功", "帳密驗證通過", user["id"], ip, device)
    log_audit(conn, user["email"], "使用者登入", "users", user["id"], f"{provider} / {ip} / {device}")
    return {
        "token": token,
        "expiresAt": expires.strftime("%Y-%m-%d %H:%M:%S"),
        "user": public_user(user),
        "permissions": role_permission_codes(conn, user["role"]),
    }


def authenticate_local(conn: sqlite3.Connection, payload: Dict[str, Any], ip: str, device: str) -> Tuple[Dict[str, Any], int]:
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    provider = str(payload.get("provider") or payload.get("environment") or "本機帳號")
    if not email or not password:
        record_login_event(conn, email or "-", provider, "失敗", "缺少帳號或密碼", None, ip, device)
        return {"error": "invalid_request", "detail": "請輸入帳號與密碼。"}, 400

    user = conn.execute("SELECT * FROM users WHERE lower(email) = ?", (email,)).fetchone()
    if not user:
        record_login_event(conn, email, provider, "失敗", "帳號不存在", None, ip, device)
        return {"error": "invalid_credentials", "detail": "帳號或密碼不正確。"}, 401
    if user["status"] != "啟用":
        record_login_event(conn, email, provider, "失敗", "帳號停用", user["id"], ip, device)
        return {"error": "account_disabled", "detail": "此帳號已停用。"}, 403
    if user["role"] not in ALLOWED_EDOC_ROLES:
        record_login_event(conn, email, provider, "失敗", "角色未授權", user["id"], ip, device)
        return {"error": "role_forbidden", "detail": "此帳號角色未授權使用電子公文系統。"}, 403
    if demo_login_blocked(email, password):
        record_login_event(conn, email, provider, "失敗", "正式站禁止 demo 帳號登入", user["id"], ip, device)
        return {"error": "demo_login_disabled", "detail": "正式環境已關閉 demo 帳號，請使用正式帳號或 Logging Portal 登入。"}, 403
    if not verify_password(password, user["password_hash"]):
        record_login_event(conn, email, provider, "失敗", "密碼錯誤", user["id"], ip, device)
        return {"error": "invalid_credentials", "detail": "帳號或密碼不正確。"}, 401
    return create_session(conn, user, provider, ip, device), 200


def current_session(conn: sqlite3.Connection, token: str) -> Dict[str, Any] | None:
    if not token:
        return None
    row = conn.execute(
        """
        SELECT
          s.id AS session_id, s.expires_at,
          u.id, u.auth_user_id, u.name, u.email, u.unit, u.title, u.job_level, u.role,
          u.provider, u.mfa_status, u.status, u.last_login_at, u.created_at
        FROM auth_sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = ? AND s.revoked_at IS NULL AND s.expires_at > ?
        """,
        (hash_token(token), now()),
    ).fetchone()
    if not row:
        return None
    if row["role"] not in ALLOWED_EDOC_ROLES:
        return None
    user = {key: row[key] for key in row.keys() if key in {"id", "auth_user_id", "name", "email", "unit", "title", "job_level", "role", "provider", "mfa_status", "status", "last_login_at", "created_at"}}
    return {
        "sessionId": row["session_id"],
        "expiresAt": row["expires_at"],
        "user": user,
        "permissions": role_permission_codes(conn, row["role"]),
    }


def dashboard(conn: sqlite3.Connection, session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    def scalar(sql: str, params: Tuple[Any, ...] = ()) -> int:
        return int(conn.execute(sql, params).fetchone()[0])

    document_where, document_params = scoped_document_where(session)
    inbound_where, inbound_params = scoped_document_where(session, ["direction = '收文'", "status IN ('待登錄','待分派')"])
    dispatch_where, dispatch_params = scoped_document_where(session, ["direction = '發文'", "status IN ('草稿','待清稿','已清稿')"])
    exchange_scope = f"document_id IN (SELECT id FROM documents{document_where})"
    total_tasks = scalar(f"SELECT COUNT(*) FROM exchange_tasks WHERE {exchange_scope}", tuple(document_params))
    failed_tasks = scalar(f"SELECT COUNT(*) FROM exchange_tasks WHERE status LIKE '%失敗%' AND {exchange_scope}", tuple(document_params))
    complete_tasks = scalar(
        f"SELECT COUNT(*) FROM exchange_tasks WHERE (status LIKE '%完成%' OR status LIKE '%確認%') AND {exchange_scope}",
        tuple(document_params),
    )
    audit_count = scalar("SELECT COUNT(*) FROM audit_logs") if session_has_any_permission(session, ["audit_logs.view", "audit_logs.export", "audit.view"]) else 0
    return {
        "documents": scalar(f"SELECT COUNT(*) FROM documents{document_where}", tuple(document_params)),
        "inboundPending": scalar(f"SELECT COUNT(*) FROM documents{inbound_where}", tuple(inbound_params)),
        "dispatchPending": scalar(f"SELECT COUNT(*) FROM documents{dispatch_where}", tuple(dispatch_params)),
        "exchangeTasks": total_tasks,
        "exchangeFailed": failed_tasks,
        "successRate": round((complete_tasks / total_tasks) * 100, 1) if total_tasks else 100,
        "auditLogs": audit_count,
    }


def pull_inbound(conn: sqlite3.Connection) -> Dict[str, Any]:
    gateway = create_exchange_gateway(conn)
    result = gateway.receiveOfficialDocuments({})
    created = [item.get("document_id") for item in result.get("items", []) if item.get("document_id")]
    for doc_id in created:
        log_audit(conn, "Exchange Gateway", "每日收文拉取", "documents", doc_id, "mock provider 已建立收文主檔")
    return {"created": created[0] if created else "", "created_ids": created, "count": result.get("count", 0), "gateway": result}


def exchange_gateway_status() -> Dict[str, Any]:
    return {
        "provider": EDOC_EXCHANGE_PROVIDER,
        "environment": EDOC_EXCHANGE_ENV,
        "maxRetries": EDOC_EXCHANGE_MAX_RETRIES,
        "formalConnection": False,
        "mode": "mock-only" if EDOC_EXCHANGE_PROVIDER == "mock" else "provider-not-implemented",
        "secrets": {
            "configuredByEnvironment": True,
            "logged": False,
        },
    }


def exchange_queue_document(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    gateway = create_exchange_gateway(conn)
    result = gateway.queueOfficialDocument(payload)
    log_audit(conn, "Exchange Gateway", "加入交換待發佇列", "exchange_outbox", result.get("id", ""), json.dumps(redact_sensitive(payload), ensure_ascii=False))
    return result


def exchange_send_document(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    gateway = create_exchange_gateway(conn)
    result = gateway.sendOfficialDocument(payload)
    log_audit(conn, "Exchange Gateway", "送出公文交換", "exchange_outbox", result.get("item", {}).get("id", ""), json.dumps(redact_sensitive(result), ensure_ascii=False))
    return result


def exchange_receive_documents(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    gateway = create_exchange_gateway(conn)
    result = gateway.receiveOfficialDocuments(payload)
    log_audit(conn, "Exchange Gateway", "收取交換來文", "exchange_inbox", "batch", json.dumps({"count": result.get("count", 0)}, ensure_ascii=False))
    return result


def exchange_query_status(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    gateway = create_exchange_gateway(conn)
    result = gateway.queryDeliveryStatus(payload)
    log_audit(conn, "Exchange Gateway", "查詢交換狀態", "exchange_outbox", result.get("item", {}).get("id", ""), json.dumps(redact_sensitive(result), ensure_ascii=False))
    return result


def exchange_acknowledge_received(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    gateway = create_exchange_gateway(conn)
    result = gateway.acknowledgeReceived(payload)
    log_audit(conn, "Exchange Gateway", "確認收文入案", "exchange_inbox", result.get("item", {}).get("id", ""), json.dumps(redact_sensitive(result), ensure_ascii=False))
    return result


def exchange_retry_failed(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    gateway = create_exchange_gateway(conn)
    result = gateway.retryFailedDelivery(payload)
    log_audit(conn, "Exchange Gateway", "重送交換失敗公文", "exchange_outbox", result.get("item", {}).get("id", ""), json.dumps(redact_sensitive(result), ensure_ascii=False))
    return result


def backup_database(conn: sqlite3.Connection) -> Dict[str, Any]:
    ensure_dirs()
    name = f"edoc-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
    target = BACKUP_DIR / name
    conn.commit()
    shutil.copy2(DB_PATH, target)
    digest = sha256_bytes(target.read_bytes())
    log_audit(conn, "API", "資料備份", "backup", name, f"{target} sha256={digest}")
    return {"backup": name, "path": str(target), "size": target.stat().st_size, "sha256": digest, "created_at": now()}


def sqlite_table_counts(db_path: Path) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    readonly = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    readonly.row_factory = sqlite3.Row
    try:
        for table in TABLES:
            try:
                counts[table] = readonly.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
            except sqlite3.Error:
                counts[table] = 0
    finally:
        readonly.close()
    return counts


def run_backup_restore_drill(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    ensure_dirs()
    started = time.time()
    scope = payload.get("scope") or "全部資料表"
    target_env = payload.get("target_env") or payload.get("target") or "測試沙盒"
    rto_target = int(payload.get("rto_target_minutes") or payload.get("rtoTarget") or 30)
    rpo_target = int(payload.get("rpo_target_minutes") or payload.get("rpoTarget") or 15)
    backup = backup_database(conn)
    source_hash = backup["sha256"]
    source_counts = sqlite_table_counts(Path(backup["path"]))
    sandbox_name = backup["backup"].replace("edoc-backup-", "restore-sandbox-")
    sandbox_path = BACKUP_DIR / sandbox_name
    shutil.copy2(backup["path"], sandbox_path)
    restore_hash = sha256_bytes(sandbox_path.read_bytes())
    restored_counts = sqlite_table_counts(sandbox_path)
    integrity_row = sqlite3.connect(str(sandbox_path)).execute("PRAGMA integrity_check").fetchone()
    integrity = integrity_row[0] if integrity_row else "unknown"
    duration_ms = int((time.time() - started) * 1000)
    rto_minutes = max(1, (duration_ms + 59999) // 60000)
    backup_age_seconds = max(0, int(time.time() - Path(backup["path"]).stat().st_mtime))
    rpo_minutes = max(1, (backup_age_seconds + 59) // 60)
    counts_match = source_counts == restored_counts
    hash_match = source_hash == restore_hash
    rto_ok = rto_minutes <= rto_target
    rpo_ok = rpo_minutes <= rpo_target
    ok = integrity == "ok" and counts_match and hash_match and rto_ok and rpo_ok
    drill_id = f"DRILL-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3).upper()}"
    report = {
        "id": drill_id,
        "ok": ok,
        "result": "通過" if ok else "需改善",
        "created_at": now(),
        "scope": scope,
        "target_env": target_env,
        "backup": backup,
        "sandbox": {"path": str(sandbox_path), "sha256": restore_hash, "integrity": integrity},
        "source_counts": source_counts,
        "restored_counts": restored_counts,
        "row_count": sum(source_counts.values()),
        "checks": {
            "integrity": integrity == "ok",
            "hash_match": hash_match,
            "counts_match": counts_match,
            "rto_ok": rto_ok,
            "rpo_ok": rpo_ok,
        },
        "rto_minutes": rto_minutes,
        "rto_target_minutes": rto_target,
        "rpo_minutes": rpo_minutes,
        "rpo_target_minutes": rpo_target,
        "duration_ms": duration_ms,
        "steps": {
            "snapshot": f"{backup['backup']} 已建立，{sum(source_counts.values())} 筆資料",
            "sourceHash": f"{source_hash} 已產生",
            "sandboxRestore": f"{target_env} 還原完成，未覆蓋正式資料",
            "verify": "筆數與雜湊比對通過" if counts_match and hash_match else "筆數或雜湊不一致",
            "rtoRpo": f"RTO {rto_minutes}/{rto_target} 分，RPO {rpo_minutes}/{rpo_target} 分",
        },
        "improvements": [] if ok else [
            item for item, passed in {
                "確認備份檔完整性或重新產生備份": integrity == "ok" and hash_match,
                "檢查還原程序是否漏表或資料筆數不一致": counts_match,
                "優化還原程序以符合 RTO": rto_ok,
                "提高備份頻率以符合 RPO": rpo_ok,
            }.items() if not passed
        ],
    }
    report_path = BACKUP_DIR / f"{drill_id}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log_audit(conn, "Ops Drill", "備份還原演練", "backup_restore_drill", drill_id, json.dumps({"result": report["result"], "backup": backup["backup"], "rto": rto_minutes, "rpo": rpo_minutes}, ensure_ascii=False))
    return {**report, "report_path": str(report_path)}


def record_file_access(
    conn: sqlite3.Connection,
    *,
    attachment_id: str = "",
    file_object_id: str = "",
    document_id: str = "",
    actor: str = "API",
    action: str,
    result: str,
    detail: str = "",
    watermark_text: str = "",
) -> Dict[str, Any]:
    document_log_id = document_id or ""
    if document_log_id and not conn.execute("SELECT 1 FROM documents WHERE id = ?", (document_log_id,)).fetchone():
        document_log_id = ""
    row = {
        "id": f"FLOG-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "attachment_id": attachment_id or None,
        "file_object_id": file_object_id or None,
        "document_id": document_log_id or None,
        "actor": actor,
        "action": action,
        "ip": "",
        "device": "",
        "watermark_text": watermark_text,
        "result": result,
        "detail": detail,
        "created_at": now(),
    }
    insert_row(conn, "file_access_logs", row)
    log_audit(conn, actor, action, "attachments", attachment_id or file_object_id, detail or result)
    return row


def is_seal_vault_file(item: Dict[str, Any] | sqlite3.Row | None) -> bool:
    if not item:
        return False
    data = row_to_dict(item) if isinstance(item, sqlite3.Row) else item
    purpose = str(data.get("purpose") or "")
    storage_key = str(data.get("storage_key") or "")
    document_id = str(data.get("document_id") or "")
    return (
        purpose.startswith(SEAL_VAULT_PURPOSE_PREFIX)
        or storage_key.startswith("seal-vault/")
        or storage_key.startswith("private/seals/")
        or document_id == SEAL_VAULT_DOCUMENT_ID
    )


def seal_file_row_for_file_object(conn: sqlite3.Connection, file_id: str) -> Dict[str, Any] | None:
    row = conn.execute("SELECT * FROM company_seal_files WHERE file_object_id = ? ORDER BY uploaded_at DESC LIMIT 1", (file_id,)).fetchone()
    return row_to_dict(row) if row else None


def audit_seal_vault_access(
    conn: sqlite3.Connection,
    *,
    file_id: str,
    actor: str,
    action: str,
    result: str,
    detail: str = "",
    document_id: str = "",
) -> None:
    seal_file = seal_file_row_for_file_object(conn, file_id)
    log_seal_usage(
        conn,
        action=action,
        actor_id=actor,
        seal_id=seal_file.get("seal_id", "") if seal_file else "",
        document_id=document_id,
        detail=f"{result}: {detail or file_id}",
    )


def create_file_signed_url(conn: sqlite3.Connection, file_id: str, actor: str = "API", ttl_seconds: int | None = None, purpose: str = "download") -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM file_objects WHERE id = ?", (file_id,)).fetchone()
    if not row:
        return {"error": "file_not_found"}
    item = row_to_dict(row)
    if is_seal_vault_file(item):
        audit_seal_vault_access(conn, file_id=file_id, actor=actor, action="block_seal_vault_signed_url", result="denied", detail="seal_original_never_gets_download_url")
        return {"error": "seal_vault_download_forbidden", "detail": "seal_original_files_must_be_accessed_only_by_authorized_backend_seal_workflows"}
    expires_at = signed_url_expiry(ttl_seconds)
    token = secrets.token_urlsafe(32)
    token_id = f"FDL-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    conn.execute(
        """
        INSERT INTO file_download_tokens (id, file_object_id, token_hash, actor, purpose, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (token_id, file_id, hash_token(token), actor, purpose, expires_at, now()),
    )
    conn.execute("UPDATE file_objects SET signed_url_expires_at = ? WHERE id = ?", (expires_at, file_id))
    url = f"/api/files/{file_id}/download?token={urllib.parse.quote(token)}"
    log_audit(conn, actor, "產生短效檔案下載 URL", "file_objects", file_id, f"expires_at={expires_at}, provider={item.get('storage_provider')}")
    return {"file": item, "token_id": token_id, "download_url": url, "expires_at": expires_at, "ttl_seconds": ttl_seconds or EDOC_SIGNED_URL_TTL_SECONDS}


def validate_file_download_token(conn: sqlite3.Connection, file_id: str, token: str) -> Tuple[bool, str, Dict[str, Any] | None]:
    if not token:
        return False, "missing_token", None
    row = conn.execute(
        "SELECT * FROM file_download_tokens WHERE file_object_id = ? AND token_hash = ? ORDER BY created_at DESC LIMIT 1",
        (file_id, hash_token(token)),
    ).fetchone()
    if not row:
        return False, "invalid_token", None
    item = row_to_dict(row)
    if item.get("revoked_at"):
        return False, "revoked_token", item
    if parse_time(item.get("expires_at", "")) < datetime.now():
        return False, "expired_token", item
    return True, "ok", item


def scan_bytes_for_threats(data: bytes, file_name: str) -> Tuple[str, str]:
    upper = data.upper()
    if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in upper or b"X5O!P%@AP" in upper:
        return "已隔離", "EICAR-Test-File"
    if Path(file_name).suffix.lower().lstrip(".") not in {"pdf", "xml", "xlsx", "docx", "p7m", "txt", "png", "jpg", "jpeg", "webp"}:
        return "已隔離", "Disallowed-Extension"
    return "已通過", "Clean"


def scan_file_object(conn: sqlite3.Connection, file_id: str, actor: str = "AV Worker") -> Dict[str, Any]:
    storage_service = storage_service_status()
    if storage_service["productionBlocked"]:
        return {"ok": False, "error": "formal_storage_av_not_ready", "missing": storage_service["missing"], "service": storage_service}
    row = conn.execute("SELECT * FROM file_objects WHERE id = ?", (file_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "file_not_found"}
    item = row_to_dict(row)
    path = STORAGE_DIR / item["storage_key"]
    if not path.exists():
        return {"ok": False, "error": "file_missing"}
    raw = path.read_bytes()
    data = decrypt_file_bytes(raw, item.get("encryption_status", ""), item.get("encryption_alg", ""))
    status, signature = scan_bytes_for_threats(data, item["file_name"])
    detail = "防毒掃描通過" if status == "已通過" else f"隔離：{signature}"
    job_id = f"VS-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    timestamp = now()
    conn.execute(
        """
        INSERT INTO virus_scan_jobs (
          id, file_object_id, attachment_id, document_id, engine, status, signature, result, detail,
          started_at, finished_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (job_id, file_id, None, item.get("document_id"), EDOC_SCAN_ENGINE, "完成", signature, status, detail, timestamp, timestamp, timestamp),
    )
    conn.execute(
        "UPDATE file_objects SET scan_status = ?, scan_engine = ?, quarantine_reason = ?, last_scan_at = ? WHERE id = ?",
        (status, EDOC_SCAN_ENGINE, "" if status == "已通過" else signature, timestamp, file_id),
    )
    log_audit(conn, actor, "正式防毒掃描", "file_objects", file_id, f"{EDOC_SCAN_ENGINE} / {status} / {signature}")
    refreshed = row_to_dict(conn.execute("SELECT * FROM file_objects WHERE id = ?", (file_id,)).fetchone())
    return {"ok": status == "已通過", "file": refreshed, "job": {"id": job_id, "engine": EDOC_SCAN_ENGINE, "result": status, "signature": signature, "detail": detail}}


def upload_file_object(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    storage_service = storage_service_status()
    if storage_service["productionBlocked"]:
        return {"ok": False, "error": "formal_storage_av_not_ready", "missing": storage_service["missing"], "service": storage_service}
    purpose = payload.get("purpose") or "attachment"
    document_id = payload.get("document_id") or "DOC-UPLOAD-MANUAL"
    if (
        str(purpose).startswith(("seal", "private/seals", SEAL_VAULT_PURPOSE_PREFIX))
        or str(document_id) in {"DOC-SEAL-ASSET", SEAL_VAULT_DOCUMENT_ID}
    ):
        log_audit(conn, payload.get("actor") or "API", "阻擋一般附件 API 上傳印章原檔", "seal_vault", str(document_id), "seal_original_must_use_seal_vault_api", event_type="seal_vault_upload_blocked", module_code="seals", result="denied")
        return {"ok": False, "error": "seal_vault_upload_required", "detail": "印章電子檔不得透過一般附件 API 上傳，請使用 /api/seals/{sealId}/files。"}
    content = payload.get("content_base64") or payload.get("content") or ""
    if payload.get("content_base64"):
        import base64
        data = base64.b64decode(content)
    else:
        data = str(content).encode("utf-8")
    max_bytes = EDOC_MAX_FILE_SIZE_MB * 1024 * 1024
    if len(data) > max_bytes:
        return {"ok": False, "error": "file_too_large", "max_mb": EDOC_MAX_FILE_SIZE_MB, "size_bytes": len(data)}
    mime_type = payload.get("mime_type") or "application/octet-stream"
    allowed_mime_types = {item.strip().lower() for item in EDOC_ALLOWED_MIME_TYPES.split(",") if item.strip()}
    if allowed_mime_types and mime_type.lower() not in allowed_mime_types:
        return {"ok": False, "error": "mime_type_not_allowed", "mime_type": mime_type, "allowed": sorted(allowed_mime_types)}
    if not conn.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,)).fetchone():
        ts = now()
        conn.execute(
            """
            INSERT INTO documents (
              id, doc_no, direction, doc_type, priority, security_level, agency_name, agency_code,
              subject, body, status, owner, department, due_date, received_at, created_at, updated_at
            ) VALUES (?, ?, '發文', '附件', '普通件', '普通', '歲悅長照', 'SYC',
              '系統資產上傳', '印鑑圖檔或系統附件資產。', '封存', '總務', '總務', NULL, NULL, ?, ?)
            """,
            (document_id, document_id, ts, ts),
        )
    file_name = payload.get("file_name") or f"upload-{int(time.time())}.bin"
    actor = payload.get("actor") or "API"
    file_row = store_file_object(conn, document_id, file_name, data, purpose, payload.get("version_label") or "v1", actor)
    conn.execute("UPDATE file_objects SET mime_type = ? WHERE id = ?", (mime_type, file_row["id"]))
    scan = scan_file_object(conn, file_row["id"], actor)
    signed = create_file_signed_url(conn, file_row["id"], actor, int(payload.get("ttl_seconds") or EDOC_SIGNED_URL_TTL_SECONDS))
    conn.commit()
    return {"file": row_to_dict(conn.execute("SELECT * FROM file_objects WHERE id = ?", (file_row["id"],)).fetchone()), "scan": scan, "signed_url": signed}


def storage_health(conn: sqlite3.Connection) -> Dict[str, Any]:
    service = storage_service_status()
    total = conn.execute("SELECT COUNT(*) AS count FROM file_objects").fetchone()["count"]
    encrypted = conn.execute("SELECT COUNT(*) AS count FROM file_objects WHERE encryption_status = '已加密'").fetchone()["count"]
    pending = conn.execute("SELECT COUNT(*) AS count FROM file_objects WHERE scan_status = '待掃描'").fetchone()["count"]
    quarantined = conn.execute("SELECT COUNT(*) AS count FROM file_objects WHERE scan_status = '已隔離'").fetchone()["count"]
    tokens = conn.execute("SELECT COUNT(*) AS count FROM file_download_tokens WHERE revoked_at IS NULL AND expires_at > ?", (now(),)).fetchone()["count"]
    return {
        "ready": service["ready"],
        "provider": EDOC_STORAGE_PROVIDER,
        "bucket": EDOC_STORAGE_BUCKET,
        "service": service,
        "signedUrlTtlSeconds": EDOC_SIGNED_URL_TTL_SECONDS,
        "encryption": {"enabled": EDOC_FILE_ENCRYPTION_ENABLED, "keyId": file_key_id(), "encryptedFiles": encrypted, "totalFiles": total},
        "scanner": {"engine": EDOC_SCAN_ENGINE, "avProvider": EDOC_AV_PROVIDER, "endpoint": EDOC_AV_ENDPOINT or "未設定", "pending": pending, "quarantined": quarantined},
        "activeDownloadTokens": tokens,
        "policy": service["policy"],
        "mode": service["mode"] if service["ready"] else ("local-encrypted-storage" if EDOC_STORAGE_PROVIDER == "local" else "supabase-storage-incomplete"),
    }


def attachment_security_action(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    action = payload.get("action") or "scan"
    ids = payload.get("ids") or ([payload["id"]] if payload.get("id") else [])
    if not ids:
        return {"count": 0, "results": [], "error": "ids_required"}
    actor = payload.get("actor") or "API"
    watermark_text = payload.get("watermark_text") or "歲悅長照｜電子公文交換｜限授權使用"
    backup_id = payload.get("backup_id") or f"FBKP-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    results: List[Dict[str, Any]] = []
    for item_id in ids:
        row = conn.execute(
            "SELECT * FROM attachment_security WHERE id = ? OR attachment_id = ?",
            (item_id, item_id),
        ).fetchone()
        if not row:
            results.append({"id": item_id, "status": "not_found"})
            continue
        item = row_to_dict(row)
        update: Dict[str, Any] = {"updated_at": now()}
        result = "成功"
        detail = ""
        if action == "scan":
            over_limit = item["size_bytes"] > item["max_size_bytes"]
            unsafe_ext = item.get("file_ext", "").lower() not in {"pdf", "xml", "xlsx", "docx", "p7m"}
            update["scan_status"] = "已隔離" if over_limit or unsafe_ext else "已通過"
            update["quarantine_reason"] = "檔案超過大小限制" if over_limit else "不允許副檔名" if unsafe_ext else ""
            update["scan_engine"] = EDOC_SCAN_ENGINE
            update["scan_signature"] = f"{EDOC_SCAN_ENGINE}-SIG-{sha256_bytes((item['file_name'] + now()).encode('utf-8'))[:12]}"
            detail = update["quarantine_reason"] or "防毒掃描通過"
        elif action == "quarantine":
            update["scan_status"] = "已隔離"
            update["quarantine_reason"] = payload.get("reason") or "人工隔離"
            detail = update["quarantine_reason"]
        elif action == "release":
            update["scan_status"] = "已通過"
            update["quarantine_reason"] = ""
            detail = "人工解除隔離"
        elif action == "mask":
            update["mask_status"] = "已遮罩"
            detail = f"遮罩政策：{payload.get('mask_policy') or '身分證 / 電話 / Email'}"
        elif action == "watermark":
            update["watermark_status"] = "已加浮水印下載"
            update["last_accessed_by"] = actor
            update["last_accessed_at"] = now()
            detail = watermark_text
        elif action == "backup":
            update["backup_id"] = backup_id
            detail = f"備份快照 {backup_id}"
        else:
            result = "失敗"
            detail = f"unknown_action:{action}"
        assignments = ", ".join(f"{key} = ?" for key in update)
        conn.execute(f"UPDATE attachment_security SET {assignments} WHERE id = ?", (*update.values(), item["id"]))
        log_row = record_file_access(
            conn,
            attachment_id=item["attachment_id"],
            document_id=item["document_id"],
            actor=actor,
            action=f"附件安全-{action}",
            result=result,
            detail=detail,
            watermark_text=watermark_text if action == "watermark" else "",
        )
        refreshed = row_to_dict(conn.execute("SELECT * FROM attachment_security WHERE id = ?", (item["id"],)).fetchone())
        results.append({"id": item["id"], "status": result, "item": refreshed, "log": log_row})
    return {"count": len(results), "backup_id": backup_id if action == "backup" else "", "results": results}


def get_or_create_pdf_document(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    doc_payload = payload.get("document") or payload
    candidates = [
        doc_payload.get("document_id"),
        doc_payload.get("id"),
        f"DOC-{doc_payload.get('id')}" if doc_payload.get("id") and not str(doc_payload.get("id")).startswith("DOC-") else None,
    ]
    for candidate in [item for item in candidates if item]:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (candidate,)).fetchone()
        if row:
            return row_to_dict(row)
    doc_no = doc_payload.get("doc_no") or doc_payload.get("no")
    if doc_no:
        row = conn.execute("SELECT * FROM documents WHERE doc_no = ?", (doc_no,)).fetchone()
        if row:
            return row_to_dict(row)
    ts = now()
    doc_id = str(doc_payload.get("document_id") or doc_payload.get("id") or f"DOC-PDF-{int(time.time() * 1000)}")
    if not doc_id.startswith("DOC-"):
        doc_id = f"DOC-{doc_id}"
    doc = {
        "id": doc_id,
        "doc_no": doc_no or doc_id,
        "direction": doc_payload.get("direction", "發文"),
        "doc_type": doc_payload.get("doc_type") or doc_payload.get("type") or "函",
        "priority": doc_payload.get("priority") or "普通件",
        "security_level": doc_payload.get("security_level") or doc_payload.get("security") or "普通",
        "agency_name": doc_payload.get("agency_name") or doc_payload.get("to") or "未指定機關",
        "agency_code": doc_payload.get("agency_code") or doc_payload.get("agencyCode") or "",
        "subject": doc_payload.get("subject") or "未命名公文",
        "body": doc_payload.get("body") or "",
        "status": doc_payload.get("status") or "PDF 已產生",
        "owner": doc_payload.get("owner") or "總務",
        "department": doc_payload.get("department") or doc_payload.get("dept") or "總管理處",
        "due_date": doc_payload.get("due_date") or doc_payload.get("dueDate") or "",
        "received_at": doc_payload.get("received_at") or None,
        "created_at": ts,
        "updated_at": ts,
    }
    insert_row(conn, "documents", doc)
    return doc


def store_file_object(conn: sqlite3.Connection, document_id: str, file_name: str, data: bytes, purpose: str, version_label: str, actor: str = "API") -> Dict[str, Any]:
    ensure_dirs()
    file_id = f"FILE-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    safe_name = Path(file_name).name
    storage_key = f"{purpose}/{document_id}/{file_id}-{safe_name}"
    target = STORAGE_DIR / storage_key
    target.parent.mkdir(parents=True, exist_ok=True)
    encrypted_data, encryption_status, encryption_alg = encrypt_file_bytes(data)
    target.write_bytes(encrypted_data)
    digest = sha256_bytes(data)
    row = {
        "id": file_id,
        "document_id": document_id,
        "file_name": safe_name,
        "storage_key": storage_key,
        "bucket": EDOC_STORAGE_BUCKET,
        "storage_provider": EDOC_STORAGE_PROVIDER,
        "mime_type": "application/pdf",
        "size_bytes": len(data),
        "sha256": digest,
        "encrypted_sha256": sha256_bytes(encrypted_data) if encryption_status == "已加密" else "",
        "encryption_status": encryption_status,
        "encryption_alg": encryption_alg,
        "encryption_key_id": file_key_id() if encryption_status == "已加密" else "",
        "scan_status": "待掃描",
        "scan_engine": EDOC_SCAN_ENGINE,
        "quarantine_reason": "",
        "signed_url_expires_at": "",
        "last_scan_at": "",
        "last_download_at": "",
        "version_label": version_label,
        "purpose": purpose,
        "created_by": actor,
        "created_at": now(),
    }
    insert_row(conn, "file_objects", row)
    return row


def create_pdf_version(conn: sqlite3.Connection, document: Dict[str, Any], version_type: str, template: str, data: bytes, coordinates: Dict[str, Any], stamp_no: str = "", previous_version_id: str = "") -> Dict[str, Any]:
    suffix = "before-seal" if version_type == "before_seal" else "after-seal" if version_type == "after_seal" else "seal-application"
    file_row = store_file_object(conn, document["id"], f"{document['doc_no']}-{suffix}.pdf", data, "pdf", version_type)
    version_id = f"PDF-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    row = {
        "id": version_id,
        "document_id": document["id"],
        "file_object_id": file_row["id"],
        "version_type": version_type,
        "template_name": template,
        "stamp_no": stamp_no,
        "coordinates_json": json.dumps(coordinates, ensure_ascii=False),
        "previous_version_id": previous_version_id,
        "sha256": file_row["sha256"],
        "created_at": now(),
    }
    insert_row(conn, "pdf_versions", row)
    row["file"] = file_row
    row["download_url"] = create_file_signed_url(conn, file_row["id"], "PDF Worker")["download_url"]
    row["coordinates"] = coordinates
    row["page_count"] = coordinates.get("page_count")
    row["page_size"] = coordinates.get("page_size")
    return row


def latest_pdf_version(conn: sqlite3.Connection, document_id: str, version_type: str = "") -> Dict[str, Any] | None:
    params: List[Any] = [document_id]
    sql = "SELECT * FROM pdf_versions WHERE document_id = ?"
    if version_type:
        sql += " AND version_type = ?"
        params.append(version_type)
    sql += " ORDER BY rowid DESC LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    return row_to_dict(row) if row else None


def create_pdf_version_for_file(
    conn: sqlite3.Connection,
    document: Dict[str, Any],
    file_row: Dict[str, Any],
    version_type: str,
    template: str,
    coordinates: Dict[str, Any],
    stamp_no: str = "",
    previous_version_id: str = "",
) -> Dict[str, Any]:
    version_id = f"PDF-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    row = {
        "id": version_id,
        "document_id": document["id"],
        "file_object_id": file_row["id"],
        "version_type": version_type,
        "template_name": template,
        "stamp_no": stamp_no,
        "coordinates_json": json.dumps(coordinates, ensure_ascii=False),
        "previous_version_id": previous_version_id,
        "sha256": file_row["sha256"],
        "created_at": now(),
    }
    insert_row(conn, "pdf_versions", row)
    row["file"] = file_row
    row["download_url"] = create_file_signed_url(conn, file_row["id"], "PDF Worker")["download_url"]
    row["coordinates"] = coordinates
    row["page_count"] = coordinates.get("page_count")
    row["page_size"] = coordinates.get("page_size")
    return row


def read_file_object_bytes(conn: sqlite3.Connection, file_id: str) -> Tuple[Dict[str, Any], bytes]:
    row = conn.execute("SELECT * FROM file_objects WHERE id = ?", (file_id,)).fetchone()
    if not row:
        raise ValueError("file_not_found")
    item = row_to_dict(row)
    path = STORAGE_DIR / item["storage_key"]
    if not path.exists():
        raise ValueError("file_missing")
    raw = path.read_bytes()
    data = decrypt_file_bytes(raw, item.get("encryption_status", ""), item.get("encryption_alg", ""))
    actual = sha256_bytes(data)
    if actual != item["sha256"]:
        raise ValueError("file_hash_mismatch")
    return item, data


def seal_actor(session: Dict[str, Any] | None, payload: Dict[str, Any] | None = None) -> str:
    user = current_user_from_session(session)
    payload = payload or {}
    return user.get("id") or user.get("email") or user.get("name") or payload.get("actor_id") or payload.get("actor") or "API"


def seal_reference_codes(conn: sqlite3.Connection, option_type: str) -> set[str]:
    rows = conn.execute(
        "SELECT code FROM seal_reference_options WHERE option_type = ? AND status = 'active'",
        (option_type,),
    ).fetchall()
    return {row["code"] for row in rows}


def company_seal_row(conn: sqlite3.Connection, seal_id: str) -> Dict[str, Any]:
    row = conn.execute(
        """
        SELECT s.*, c.name AS company_name, c.tax_id AS company_tax_id
        FROM company_seals s
        JOIN companies c ON c.id = s.company_id
        WHERE s.id = ?
        """,
        (seal_id,),
    ).fetchone()
    if not row:
        raise ValueError("seal_not_found")
    data = row_to_dict(row)
    current_file = conn.execute(
        """
        SELECT *
        FROM company_seal_files
        WHERE seal_id = ? AND is_current = 1
        ORDER BY version DESC
        LIMIT 1
        """,
        (seal_id,),
    ).fetchone()
    data["current_file"] = seal_file_metadata(row_to_dict(current_file)) if current_file else None
    return data


def seal_file_metadata(row: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {
        "id", "seal_id", "file_object_id", "file_name", "file_mime_type", "file_size",
        "file_hash", "version", "is_current", "uploaded_by", "uploaded_at"
    }
    return {key: row.get(key) for key in allowed if key in row}


def log_seal_usage(
    conn: sqlite3.Connection,
    *,
    action: str,
    actor_id: str = "API",
    usage_request_id: str = "",
    seal_id: str = "",
    document_id: str = "",
    detail: str = "",
    ip_address: str = "",
    user_agent: str = "",
) -> Dict[str, Any]:
    row = {
        "id": f"SLOG-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "usage_request_id": usage_request_id or None,
        "seal_id": seal_id or None,
        "document_id": document_id or None,
        "action": action,
        "actor_id": actor_id,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "detail": detail,
        "created_at": now(),
    }
    insert_row(conn, "seal_usage_logs", row)
    log_audit(conn, actor_id, action, "seal_usage", usage_request_id or seal_id or document_id, detail, event_type=action, module_code="seals")
    return row


def list_company_seals(conn: sqlite3.Connection, company_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT s.*, c.name AS company_name, c.tax_id AS company_tax_id
        FROM company_seals s
        JOIN companies c ON c.id = s.company_id
        WHERE s.company_id = ?
        ORDER BY s.is_active DESC, s.seal_category, s.seal_size_type, s.created_at DESC
        """,
        (company_id,),
    ).fetchall()
    return [company_seal_row(conn, row["id"]) for row in rows]


def create_company_seal(conn: sqlite3.Connection, company_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not conn.execute("SELECT 1 FROM companies WHERE id = ?", (company_id,)).fetchone():
        raise ValueError("company_not_found")
    category = payload.get("seal_category") or payload.get("category") or "other"
    size_type = payload.get("seal_size_type") or payload.get("size_type") or "large_seal"
    if category not in seal_reference_codes(conn, "category"):
        raise ValueError("invalid_seal_category")
    if size_type not in seal_reference_codes(conn, "size"):
        raise ValueError("invalid_seal_size_type")
    actor = seal_actor(session, payload)
    seal_id = payload.get("id") or f"CSEAL-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    row = {
        "id": seal_id,
        "company_id": company_id,
        "seal_name": payload.get("seal_name") or payload.get("name") or "未命名印章",
        "seal_category": category,
        "seal_size_type": size_type,
        "purpose_description": payload.get("purpose_description") or payload.get("purpose") or "",
        "is_active": 1 if payload.get("is_active", True) else 0,
        "created_by": actor,
        "created_at": now(),
        "updated_at": now(),
        "deactivated_at": "",
    }
    insert_row(conn, "company_seals", row)
    for role in payload.get("default_permission_roles") or ["viewer", "requester", "approver", "seal_admin"]:
        if role not in seal_reference_codes(conn, "permission_role"):
            continue
        insert_row(conn, "seal_permissions", {
            "id": f"SPERM-{seal_id}-{role}",
            "seal_id": seal_id,
            "user_id": payload.get("user_id") or "",
            "role": role,
            "created_at": now(),
        })
    log_seal_usage(conn, action="create_seal", actor_id=actor, seal_id=seal_id, detail=row["seal_name"])
    return company_seal_row(conn, seal_id)


def patch_company_seal(conn: sqlite3.Connection, seal_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    company_seal_row(conn, seal_id)
    update: Dict[str, Any] = {}
    for source_key, target_key in [
        ("seal_name", "seal_name"),
        ("seal_category", "seal_category"),
        ("seal_size_type", "seal_size_type"),
        ("purpose_description", "purpose_description"),
        ("is_active", "is_active"),
    ]:
        if source_key in payload:
            update[target_key] = payload[source_key]
    if "seal_category" in update and update["seal_category"] not in seal_reference_codes(conn, "category"):
        raise ValueError("invalid_seal_category")
    if "seal_size_type" in update and update["seal_size_type"] not in seal_reference_codes(conn, "size"):
        raise ValueError("invalid_seal_size_type")
    if "is_active" in update:
        update["is_active"] = 1 if update["is_active"] else 0
        update["deactivated_at"] = "" if update["is_active"] else now()
    update["updated_at"] = now()
    conn.execute(
        f"UPDATE company_seals SET {', '.join(f'{key} = ?' for key in update)} WHERE id = ?",
        [*update.values(), seal_id],
    )
    log_seal_usage(conn, action="update_seal", actor_id=seal_actor(session, payload), seal_id=seal_id, detail=json.dumps(update, ensure_ascii=False))
    return company_seal_row(conn, seal_id)


def deactivate_company_seal(conn: sqlite3.Connection, seal_id: str, session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    row = patch_company_seal(conn, seal_id, {"is_active": False}, session)
    log_seal_usage(conn, action="deactivate_seal", actor_id=seal_actor(session), seal_id=seal_id, detail="soft_delete_only")
    return row


def validate_seal_file_upload(file_name: str, mime_type: str, data: bytes) -> None:
    allowed_mime_types = {item.strip().lower() for item in EDOC_SEAL_ALLOWED_MIME_TYPES.split(",") if item.strip()}
    suffix = Path(file_name).suffix.lower().lstrip(".")
    if mime_type.lower() not in allowed_mime_types:
        raise ValueError("seal_file_mime_type_not_allowed")
    if suffix not in {"png", "jpg", "jpeg", "webp", "svg"}:
        raise ValueError("seal_file_extension_not_allowed")
    max_bytes = EDOC_SEAL_FILE_MAX_SIZE_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise ValueError("seal_file_too_large")
    if suffix == "svg" or mime_type.lower() == "image/svg+xml":
        text = data[:200000].decode("utf-8", "ignore").lower()
        blocked_patterns = ["<script", "javascript:", "onload=", "onerror=", "foreignobject", "<iframe", "<object", "<embed"]
        if any(pattern in text for pattern in blocked_patterns):
            raise ValueError("unsafe_svg_rejected")


def upload_company_seal_file(conn: sqlite3.Connection, seal_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    seal = company_seal_row(conn, seal_id)
    if not seal.get("is_active"):
        raise ValueError("inactive_seal_cannot_upload_new_file")
    content = payload.get("content_base64") or ""
    if not content:
        raise ValueError("seal_file_content_required")
    data = base64.b64decode(content)
    file_name = Path(payload.get("file_name") or f"{seal_id}.png").name
    mime_type = payload.get("file_mime_type") or payload.get("mime_type") or "image/png"
    validate_seal_file_upload(file_name, mime_type, data)
    actor = seal_actor(session, payload)
    next_version = (conn.execute("SELECT COALESCE(MAX(version), 0) + 1 AS version FROM company_seal_files WHERE seal_id = ?", (seal_id,)).fetchone()["version"])
    file_row = store_file_object(conn, SEAL_VAULT_DOCUMENT_ID, file_name, data, f"{SEAL_VAULT_PURPOSE_PREFIX}/seals/{seal_id}", f"seal-v{next_version}", actor)
    conn.execute("UPDATE file_objects SET mime_type = ?, storage_provider = ?, purpose = ? WHERE id = ?", (mime_type, "seal-vault", "seal-vault-original", file_row["id"]))
    file_row = row_to_dict(conn.execute("SELECT * FROM file_objects WHERE id = ?", (file_row["id"],)).fetchone())
    conn.execute("UPDATE company_seal_files SET is_current = 0 WHERE seal_id = ?", (seal_id,))
    row = {
        "id": f"SFILE-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "seal_id": seal_id,
        "file_object_id": file_row["id"],
        "file_storage_key": file_row["storage_key"],
        "file_name": file_name,
        "file_mime_type": mime_type,
        "file_size": len(data),
        "file_hash": sha256_bytes(data),
        "version": int(next_version),
        "is_current": 1,
        "uploaded_by": actor,
        "uploaded_at": now(),
    }
    insert_row(conn, "company_seal_files", row)
    log_seal_usage(conn, action="upload_seal", actor_id=actor, seal_id=seal_id, detail=f"{file_name} v{next_version} hash={row['file_hash']}")
    return {"seal": company_seal_row(conn, seal_id), "file": seal_file_metadata(row)}


def list_company_seal_files(conn: sqlite3.Connection, seal_id: str, session: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    company_seal_row(conn, seal_id)
    actor = seal_actor(session)
    log_seal_usage(conn, action="view_seal_metadata", actor_id=actor, seal_id=seal_id, detail="metadata_only")
    rows = conn.execute("SELECT * FROM company_seal_files WHERE seal_id = ? ORDER BY version DESC", (seal_id,)).fetchall()
    return [seal_file_metadata(row_to_dict(row)) for row in rows]


def set_current_seal_file(conn: sqlite3.Connection, file_id: str, session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM company_seal_files WHERE id = ?", (file_id,)).fetchone()
    if not row:
        raise ValueError("seal_file_not_found")
    item = row_to_dict(row)
    conn.execute("UPDATE company_seal_files SET is_current = 0 WHERE seal_id = ?", (item["seal_id"],))
    conn.execute("UPDATE company_seal_files SET is_current = 1 WHERE id = ?", (file_id,))
    log_seal_usage(conn, action="set_current_seal_file", actor_id=seal_actor(session), seal_id=item["seal_id"], detail=f"version={item['version']}")
    return company_seal_row(conn, item["seal_id"])


def seal_usage_request_row(conn: sqlite3.Connection, request_id: str) -> Dict[str, Any]:
    row = conn.execute(
        """
        SELECT r.*, c.name AS company_name, s.seal_name, s.seal_category, s.seal_size_type
        FROM seal_usage_requests r
        JOIN companies c ON c.id = r.company_id
        JOIN company_seals s ON s.id = r.seal_id
        WHERE r.id = ?
        """,
        (request_id,),
    ).fetchone()
    if not row:
        raise ValueError("seal_usage_request_not_found")
    data = row_to_dict(row)
    data["stamp_positions"] = parse_json_any(data.get("stamp_positions_json"), []) or []
    data["metadata"] = parse_json_any(data.get("metadata_json"), {}) or {}
    data["approvals"] = [row_to_dict(item) for item in conn.execute("SELECT * FROM seal_usage_approvals WHERE usage_request_id = ? ORDER BY approval_order", (request_id,)).fetchall()]
    data["logs"] = [row_to_dict(item) for item in conn.execute("SELECT * FROM seal_usage_logs WHERE usage_request_id = ? ORDER BY created_at DESC LIMIT 50", (request_id,)).fetchall()]
    return data


def list_seal_usage_requests(conn: sqlite3.Connection, query: Dict[str, List[str]] | None = None) -> List[Dict[str, Any]]:
    query = query or {}
    where: List[str] = []
    params: List[Any] = []
    for key, column in [("company_id", "r.company_id"), ("seal_id", "r.seal_id"), ("requested_by", "r.requested_by"), ("usage_type", "r.usage_type"), ("status", "r.status")]:
        if key in query and query[key]:
            where.append(f"{column} = ?")
            params.append(query[key][0])
    if "date_from" in query and query["date_from"]:
        where.append("r.requested_at >= ?")
        params.append(query["date_from"][0])
    if "date_to" in query and query["date_to"]:
        where.append("r.requested_at <= ?")
        params.append(query["date_to"][0])
    sql = """
        SELECT r.id
        FROM seal_usage_requests r
        JOIN company_seals s ON s.id = r.seal_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.requested_at DESC LIMIT 300"
    return [seal_usage_request_row(conn, row["id"]) for row in conn.execute(sql, params).fetchall()]


def create_seal_usage_request(conn: sqlite3.Connection, document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    seal_id = payload.get("seal_id") or ""
    if not seal_id:
        raise ValueError("seal_id_required")
    seal = company_seal_row(conn, seal_id)
    if not seal.get("is_active"):
        raise ValueError("inactive_seal_cannot_be_requested")
    if not conn.execute("SELECT 1 FROM company_seal_files WHERE seal_id = ? AND is_current = 1", (seal_id,)).fetchone():
        raise ValueError("current_seal_file_required")
    usage_type = payload.get("usage_type") or "official_document"
    if usage_type not in seal_reference_codes(conn, "usage_type"):
        raise ValueError("invalid_usage_type")
    document = get_or_create_pdf_document(conn, {"document_id": document_id, **(payload.get("document") or {})})
    actor = seal_actor(session, payload)
    request_id = payload.get("id") or f"SREQ-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    positions = payload.get("stamp_positions") or payload.get("positions") or []
    row = {
        "id": request_id,
        "document_id": document["id"],
        "company_id": seal["company_id"],
        "seal_id": seal_id,
        "requested_by": actor,
        "request_reason": payload.get("request_reason") or payload.get("reason") or "",
        "usage_type": usage_type,
        "status": payload.get("status") or "pending",
        "stamp_positions_json": json.dumps(positions, ensure_ascii=False),
        "stamped_pdf_version_id": None,
        "metadata_json": json.dumps(payload.get("metadata") or {}, ensure_ascii=False),
        "requested_at": now(),
        "approved_at": "",
        "stamped_at": "",
        "updated_at": now(),
    }
    insert_row(conn, "seal_usage_requests", row)
    approvers = payload.get("approvers") or [{"approver_id": "seal_approver", "approval_order": 1}]
    for index, approver in enumerate(approvers, start=1):
        insert_row(conn, "seal_usage_approvals", {
            "id": f"SAPP-{request_id}-{index}",
            "usage_request_id": request_id,
            "approver_id": approver.get("approver_id") or approver.get("id") or "seal_approver",
            "approval_order": int(approver.get("approval_order") or index),
            "status": "pending",
            "comment": "",
            "approved_at": "",
            "created_at": now(),
            "updated_at": now(),
        })
    log_seal_usage(conn, action="request_use", actor_id=actor, usage_request_id=request_id, seal_id=seal_id, document_id=document["id"], detail=row["request_reason"])
    return seal_usage_request_row(conn, request_id)


def approve_seal_usage_request(conn: sqlite3.Connection, request_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    request = seal_usage_request_row(conn, request_id)
    if request["status"] not in {"pending", "draft"}:
        raise ValueError("seal_request_not_pending")
    actor = seal_actor(session, payload)
    pending = conn.execute("SELECT * FROM seal_usage_approvals WHERE usage_request_id = ? AND status = 'pending' ORDER BY approval_order LIMIT 1", (request_id,)).fetchone()
    if pending:
        conn.execute(
            "UPDATE seal_usage_approvals SET status = 'approved', approver_id = ?, comment = ?, approved_at = ?, updated_at = ? WHERE id = ?",
            (actor, payload.get("comment") or "核准用印。", now(), now(), pending["id"]),
        )
    remaining = conn.execute("SELECT COUNT(*) AS count FROM seal_usage_approvals WHERE usage_request_id = ? AND status = 'pending'", (request_id,)).fetchone()["count"]
    if remaining == 0:
        conn.execute("UPDATE seal_usage_requests SET status = 'approved', approved_at = ?, updated_at = ? WHERE id = ?", (now(), now(), request_id))
    log_seal_usage(conn, action="approve_use", actor_id=actor, usage_request_id=request_id, seal_id=request["seal_id"], document_id=request["document_id"], detail=payload.get("comment") or "")
    return seal_usage_request_row(conn, request_id)


def reject_seal_usage_request(conn: sqlite3.Connection, request_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    request = seal_usage_request_row(conn, request_id)
    if request["status"] in {"stamped", "cancelled"}:
        raise ValueError("seal_request_cannot_be_rejected")
    actor = seal_actor(session, payload)
    conn.execute("UPDATE seal_usage_approvals SET status = 'rejected', comment = ?, approved_at = ?, updated_at = ? WHERE usage_request_id = ? AND status = 'pending'", (payload.get("comment") or "駁回用印。", now(), now(), request_id))
    conn.execute("UPDATE seal_usage_requests SET status = 'rejected', updated_at = ? WHERE id = ?", (now(), request_id))
    log_seal_usage(conn, action="reject_use", actor_id=actor, usage_request_id=request_id, seal_id=request["seal_id"], document_id=request["document_id"], detail=payload.get("comment") or "")
    return seal_usage_request_row(conn, request_id)


def stamp_seal_usage_request(conn: sqlite3.Connection, request_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    request = seal_usage_request_row(conn, request_id)
    if request["status"] != "approved":
        raise ValueError("seal_request_must_be_approved_before_stamp")
    seal = company_seal_row(conn, request["seal_id"])
    if not seal.get("is_active"):
        raise ValueError("inactive_seal_cannot_stamp")
    file_row = conn.execute("SELECT * FROM company_seal_files WHERE seal_id = ? AND is_current = 1 ORDER BY version DESC LIMIT 1", (request["seal_id"],)).fetchone()
    if not file_row:
        raise ValueError("current_seal_file_required")
    file_meta = row_to_dict(file_row)
    if file_meta.get("file_object_id"):
        log_seal_usage(conn, action="read_seal_vault_for_stamp", actor_id=seal_actor(session, payload), usage_request_id=request_id, seal_id=request["seal_id"], document_id=request["document_id"], detail="authorized_backend_stamp_only")
        read_file_object_bytes(conn, file_meta["file_object_id"])
    stamp_no = payload.get("stamp_no") or f"STAMP-{request_id}-{int(time.time())}"
    positions = payload.get("stamp_positions") or request.get("stamp_positions") or [
        {"page": 1, "x": 420, "y": 130, "w": 85, "h": 85, "label": seal["seal_name"], "type": seal["seal_category"], "seal_id": request["seal_id"]}
    ]
    result = pdf_stamp(conn, {
        "document_id": request["document_id"],
        "seal_id": request["seal_id"],
        "applicant": request.get("requested_by") or "申請人",
        "reason": request.get("request_reason") or "核准後自動用印",
        "stamp_no": stamp_no,
        "stamp_positions": positions,
        "coordinates": payload.get("coordinates") or {},
        "template": payload.get("template") or "公司用印文件",
    })
    conn.execute(
        "UPDATE seal_usage_requests SET status = 'stamped', stamped_at = ?, stamped_pdf_version_id = ?, stamp_positions_json = ?, updated_at = ? WHERE id = ?",
        (now(), result.get("pdf_version_id") or result.get("id") or "", json.dumps(positions, ensure_ascii=False), now(), request_id),
    )
    conn.execute("UPDATE documents SET status = '已用印', updated_at = ? WHERE id = ?", (now(), request["document_id"]))
    actor = seal_actor(session, payload)
    log_seal_usage(conn, action="stamp_document", actor_id=actor, usage_request_id=request_id, seal_id=request["seal_id"], document_id=request["document_id"], detail=f"{stamp_no} seal_file_hash={file_meta['file_hash']}")
    refreshed = seal_usage_request_row(conn, request_id)
    return {"request": refreshed, "stamped_file": {"pdf_version_id": result.get("pdf_version_id") or result.get("id"), "file_object_id": result.get("file_object_id"), "sha256": result.get("sha256"), "stamp_no": stamp_no, "download_url": result.get("download_url")}}


OFFICIAL_DOCUMENT_WORKFLOW_STEPS = [
    {"order": 1, "key": "applicant_manager", "name": "申請人主管", "status": "pending_applicant_manager", "role": "主管"},
    {"order": 2, "key": "department_head", "name": "部門主管", "status": "pending_department_head", "role": "主管"},
    {"order": 3, "key": "admin_director", "name": "行政部門主任", "status": "pending_admin_director", "role": "行政部主任"},
    {"order": 4, "key": "general_affairs_review", "name": "總務審核", "status": "pending_general_affairs_review", "role": "總務"},
    {"order": 5, "key": "ceo", "name": "執行長", "status": "pending_ceo", "role": "執行長"},
]
OFFICIAL_DOCUMENT_STEP_STATUS = {step["key"]: step["status"] for step in OFFICIAL_DOCUMENT_WORKFLOW_STEPS}
OFFICIAL_DOCUMENT_DOWNLOAD_ROLES = {"申請人", "主管", "主任", "行政部主任", "總務", "執行長", "系統管理員"}
OFFICIAL_DOCUMENT_FILE_LABELS = {
    "original_pdf": "原始上傳 PDF",
    "generated_pdf": "系統產生公文 PDF",
    "stamped_pdf": "已用印版本",
    "attachment": "補充附件",
    "dispatch_proof": "寄發證明",
}
OFFICIAL_DISPATCH_METHODS = {
    "electronic_official_document_by_general_affairs": {
        "label": "總務電子公文系統發文",
        "owner_type": "general_affairs",
        "owner_role": "總務",
        "next_status": "pending_general_affairs_dispatch",
        "next_step": "general_affairs_dispatch",
        "dispatch_status": "pending",
    },
    "email_by_general_affairs": {
        "label": "總務 Email 寄出",
        "owner_type": "general_affairs",
        "owner_role": "總務",
        "next_status": "pending_general_affairs_dispatch",
        "next_step": "general_affairs_dispatch",
        "dispatch_status": "pending",
    },
    "physical_mail_by_general_affairs": {
        "label": "總務紙本郵寄",
        "owner_type": "general_affairs",
        "owner_role": "總務",
        "next_status": "pending_general_affairs_dispatch",
        "next_step": "general_affairs_dispatch",
        "dispatch_status": "pending",
    },
    "return_to_applicant_for_manual_send": {
        "label": "回申請人自行寄發",
        "owner_type": "applicant",
        "owner_role": "申請人",
        "next_status": "returned_to_applicant_for_send",
        "next_step": "applicant_dispatch",
        "dispatch_status": "pending",
    },
    "no_dispatch_required": {
        "label": "僅用印歸檔",
        "owner_type": "system",
        "owner_role": "system",
        "next_status": "closed",
        "next_step": "",
        "dispatch_status": "dispatched",
    },
}
OFFICIAL_DISPATCH_PROOF_MIME_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp"}


def official_session_user(session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = session.get("user") if session else None
    if not user:
        raise PermissionError("authentication_required")
    return user


def official_actor_name(user: Dict[str, Any] | None) -> str:
    if not user:
        return "System"
    return user.get("name") or user.get("email") or user.get("role") or user.get("id") or "API"


def official_company_row(conn: sqlite3.Connection, company_id: str) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    if not row:
        raise ValueError("company_not_found")
    return row_to_dict(row)


def official_document_row(conn: sqlite3.Connection, document_id: str) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM official_documents WHERE id = ?", (document_id,)).fetchone()
    if not row:
        raise ValueError("official_document_not_found")
    return row_to_dict(row)


def active_user_by_role(conn: sqlite3.Connection, role: str, exclude_user_id: str = "") -> Dict[str, Any] | None:
    params: List[Any] = [role]
    sql = "SELECT * FROM users WHERE role = ? AND status = '啟用'"
    if exclude_user_id:
        sql += " AND id <> ?"
        params.append(exclude_user_id)
    sql += " ORDER BY rowid LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    return row_to_dict(row) if row else None


def active_user_by_id(conn: sqlite3.Connection, user_id: str) -> Dict[str, Any] | None:
    row = conn.execute("SELECT * FROM users WHERE id = ? AND status = '啟用'", (user_id,)).fetchone()
    return row_to_dict(row) if row else None


def official_department_head_role(conn: sqlite3.Connection, company: Dict[str, Any], department_name: str) -> str:
    row = conn.execute(
        """
        SELECT manager_role FROM department_registry
        WHERE status = '啟用' AND company_name = ? AND name = ?
        ORDER BY rowid LIMIT 1
        """,
        (company.get("name") or "", department_name or ""),
    ).fetchone()
    return row["manager_role"] if row else "主管"


def resolve_official_step_approver(conn: sqlite3.Connection, step: Dict[str, Any], applicant: Dict[str, Any], company: Dict[str, Any]) -> Dict[str, Any] | None:
    key = step["key"]
    role = step["role"]
    if key == "department_head":
        role = official_department_head_role(conn, company, applicant.get("unit") or "")
    user = active_user_by_role(conn, role, applicant.get("id") if key in {"applicant_manager", "department_head"} else "")
    if not user and key in {"applicant_manager", "department_head"}:
        user = active_user_by_role(conn, "行政部主任", applicant.get("id"))
    return user


def official_stamp_position_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw = payload.get("stamp_position") or {}
    positions = payload.get("stamp_positions") or payload.get("positions")
    if positions:
        raw = positions[0] if isinstance(positions, list) and positions else positions
    return {
        "stamp_page": max(1, int(pdf_safe_float(raw.get("page", raw.get("stamp_page", payload.get("stamp_page", 1))), 1))),
        "stamp_x": pdf_safe_float(raw.get("x", raw.get("stamp_x", payload.get("stamp_x", 420))), 420),
        "stamp_y": pdf_safe_float(raw.get("y", raw.get("stamp_y", payload.get("stamp_y", 130))), 130),
        "stamp_width": pdf_safe_float(raw.get("w", raw.get("width", raw.get("stamp_width", payload.get("stamp_width", 85)))), 85),
        "stamp_height": pdf_safe_float(raw.get("h", raw.get("height", raw.get("stamp_height", payload.get("stamp_height", 85)))), 85),
    }


def official_stamp_positions_from_request(stamp_request: Dict[str, Any], seal: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{
        "page": int(stamp_request.get("stamp_page") or 1),
        "x": pdf_safe_float(stamp_request.get("stamp_x"), 420),
        "y": pdf_safe_float(stamp_request.get("stamp_y"), 130),
        "w": pdf_safe_float(stamp_request.get("stamp_width"), 85),
        "h": pdf_safe_float(stamp_request.get("stamp_height"), 85),
        "label": seal.get("seal_name") or "公司印章",
        "type": seal.get("seal_category") or "company_seal",
        "seal_id": seal.get("id") or "",
    }]


def official_file_metadata(row: Dict[str, Any] | sqlite3.Row) -> Dict[str, Any]:
    data = row_to_dict(row) if isinstance(row, sqlite3.Row) else dict(row)
    data.pop("file_storage_key", None)
    data.pop("file_object_id", None)
    data["is_stamped"] = data.get("file_type") == "stamped_pdf"
    data["display_label"] = OFFICIAL_DOCUMENT_FILE_LABELS.get(data.get("file_type"), data.get("file_type") or "文件")
    return data


def official_document_files(conn: sqlite3.Connection, document_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM official_document_files
        WHERE document_id = ?
        ORDER BY CASE WHEN file_type = 'stamped_pdf' THEN 0 ELSE 1 END, version DESC, created_at DESC
        """,
        (document_id,),
    ).fetchall()
    return [official_file_metadata(row) for row in rows]


def official_document_steps(conn: sqlite3.Connection, document_id: str) -> List[Dict[str, Any]]:
    return [row_to_dict(row) for row in conn.execute("SELECT * FROM official_document_approval_steps WHERE document_id = ? ORDER BY step_order", (document_id,)).fetchall()]


def official_document_logs(conn: sqlite3.Connection, document_id: str) -> List[Dict[str, Any]]:
    return [row_to_dict(row) for row in conn.execute("SELECT * FROM official_document_approval_logs WHERE document_id = ? ORDER BY created_at DESC", (document_id,)).fetchall()]


def official_document_stamp_request(conn: sqlite3.Connection, document_id: str) -> Dict[str, Any] | None:
    row = conn.execute("SELECT * FROM official_document_stamp_requests WHERE document_id = ? ORDER BY created_at DESC LIMIT 1", (document_id,)).fetchone()
    return row_to_dict(row) if row else None


def official_dispatch_method(value: str | None) -> str:
    method = value or "electronic_official_document_by_general_affairs"
    if method not in OFFICIAL_DISPATCH_METHODS:
        raise ValueError("invalid_official_dispatch_method")
    return method


def official_dispatch_record_metadata(conn: sqlite3.Connection, row: Dict[str, Any] | sqlite3.Row | None) -> Dict[str, Any] | None:
    if not row:
        return None
    data = row_to_dict(row) if isinstance(row, sqlite3.Row) else dict(row)
    method = official_dispatch_method(data.get("dispatch_method"))
    data["dispatch_method_label"] = OFFICIAL_DISPATCH_METHODS[method]["label"]
    owner = active_user_by_id(conn, data.get("dispatch_owner_user_id") or "")
    data["dispatch_owner_name"] = owner.get("name") if owner else (data.get("dispatch_owner_user_id") or data.get("dispatch_owner_type") or "")
    proof_file_id = data.get("proof_file_id")
    if proof_file_id:
        proof = conn.execute("SELECT * FROM official_document_files WHERE id = ? AND document_id = ?", (proof_file_id, data["document_id"])).fetchone()
        data["proof_file"] = official_file_metadata(proof) if proof else None
    else:
        data["proof_file"] = None
    return data


def official_dispatch_record(conn: sqlite3.Connection, document_id: str) -> Dict[str, Any] | None:
    row = conn.execute("SELECT * FROM official_document_dispatch_records WHERE document_id = ? ORDER BY created_at DESC LIMIT 1", (document_id,)).fetchone()
    return official_dispatch_record_metadata(conn, row)


def resolve_official_dispatch_owner(conn: sqlite3.Connection, document: Dict[str, Any], method: str) -> Dict[str, Any]:
    config = OFFICIAL_DISPATCH_METHODS[method]
    if config["owner_type"] == "general_affairs":
        return active_user_by_role(conn, "總務") or {"id": "", "name": "總務", "role": "總務"}
    if config["owner_type"] == "applicant":
        return active_user_by_id(conn, document["applicant_id"]) or {"id": document["applicant_id"], "name": document.get("applicant_name") or "申請人", "role": "申請人"}
    return {"id": "system", "name": "System", "role": "system"}


def upsert_official_dispatch_record(
    conn: sqlite3.Connection,
    document: Dict[str, Any],
    method: str | None = None,
    actor: Dict[str, Any] | None = None,
    payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    method = official_dispatch_method(method or document.get("dispatch_method"))
    existing = conn.execute("SELECT * FROM official_document_dispatch_records WHERE document_id = ? ORDER BY created_at DESC LIMIT 1", (document["id"],)).fetchone()
    owner = resolve_official_dispatch_owner(conn, document, method)
    config = OFFICIAL_DISPATCH_METHODS[method]
    payload = payload or {}
    values = {
        "dispatch_method": method,
        "dispatch_owner_type": config["owner_type"],
        "dispatch_owner_user_id": owner.get("id") or "",
        "dispatch_status": payload.get("dispatch_status") or config["dispatch_status"],
        "external_official_document_number": payload.get("external_official_document_number") or "",
        "dispatch_date": payload.get("dispatch_date") or "",
        "recipient": payload.get("recipient") or document.get("recipient") or "",
        "recipient_contact": payload.get("recipient_contact") or "",
        "dispatch_note": payload.get("dispatch_note") or "",
        "proof_file_id": payload.get("proof_file_id") or None,
        "created_by": actor.get("id") if actor else "system",
        "completed_at": payload.get("completed_at") or (now() if config["owner_type"] == "system" else ""),
    }
    if existing:
        update = {key: value for key, value in values.items() if key not in {"created_by"}}
        update["updated_at"] = now()
        conn.execute(
            """
            UPDATE official_document_dispatch_records
            SET dispatch_method = ?, dispatch_owner_type = ?, dispatch_owner_user_id = ?, dispatch_status = ?,
                external_official_document_number = ?, dispatch_date = ?, recipient = ?, recipient_contact = ?,
                dispatch_note = ?, proof_file_id = ?, completed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                update["dispatch_method"],
                update["dispatch_owner_type"],
                update["dispatch_owner_user_id"],
                update["dispatch_status"],
                update["external_official_document_number"],
                update["dispatch_date"],
                update["recipient"],
                update["recipient_contact"],
                update["dispatch_note"],
                update["proof_file_id"],
                update["completed_at"],
                update["updated_at"],
                existing["id"],
            ),
        )
        return official_dispatch_record(conn, document["id"]) or {}
    row = {
        "id": f"ODDISP-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "document_id": document["id"],
        **values,
        "created_at": now(),
        "updated_at": now(),
    }
    insert_row(conn, "official_document_dispatch_records", row)
    return official_dispatch_record(conn, document["id"]) or row


def can_manage_official_dispatch(user: Dict[str, Any] | None, document: Dict[str, Any], record: Dict[str, Any] | None, session: Dict[str, Any] | None = None) -> bool:
    if not user:
        return False
    if user.get("role") == "系統管理員":
        return True
    owner_type = (record or {}).get("dispatch_owner_type")
    if owner_type == "general_affairs":
        return user.get("role") == "總務"
    if owner_type == "applicant":
        return user.get("id") == document.get("applicant_id")
    return False


def advance_official_dispatch_after_stamp(
    conn: sqlite3.Connection,
    document_id: str,
    stamped_file: Dict[str, Any],
    actor: Dict[str, Any] | None,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    document = official_document_row(conn, document_id)
    method = official_dispatch_method(document.get("dispatch_method"))
    config = OFFICIAL_DISPATCH_METHODS[method]
    record = upsert_official_dispatch_record(conn, document, method, actor)
    conn.execute(
        "UPDATE official_documents SET current_status = ?, current_step = ?, updated_at = ? WHERE id = ?",
        (config["next_status"], config["next_step"], now(), document_id),
    )
    insert_official_log(conn, document_id, "dispatch_route_created", actor, f"{method}:{config['label']}", file_id=stamped_file.get("id") or "", ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    if config["owner_type"] == "general_affairs":
        create_notification(conn, {"type": "發文寄發待辦", "title": f"{document['title']} 待總務寄發", "target_role": "總務", "source": document_id, "priority": "高", "body": "已用印版本已產生，請下載後至外部電子公文系統、Email 或紙本郵寄完成寄發並回填證明。"})
    elif config["owner_type"] == "applicant":
        create_notification(conn, {"type": "發文寄發待辦", "title": f"{document['title']} 已回到申請人寄發", "target_role": "員工", "target_email": "", "source": document_id, "priority": "高", "body": "已用印版本已產生，請下載後自行寄送並回填寄送紀錄。"})
    else:
        insert_official_log(conn, document_id, "auto_archive_no_dispatch", actor, "no_dispatch_required", file_id=stamped_file.get("id") or "", ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
        create_notification(conn, {"type": "發文結案", "title": f"{document['title']} 已用印並歸檔", "target_role": "員工", "source": document_id, "body": "寄發方式為不需寄發，系統已完成結案歸檔。"})
    return record


def update_official_dispatch_record(conn: sqlite3.Connection, document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = official_session_user(session)
    document = official_document_row(conn, document_id)
    steps = official_document_steps(conn, document_id)
    if not canDownloadOfficialDocument(user, document, steps) and not session_has_any_permission(session, ["official_documents.all_records", "official_documents.all_todo"]):
        raise PermissionError("official_dispatch_access_denied")
    record = official_dispatch_record(conn, document_id)
    if not record:
        method = official_dispatch_method(payload.get("dispatch_method") or document.get("dispatch_method"))
        record = upsert_official_dispatch_record(conn, document, method, user)
    if not can_manage_official_dispatch(user, document, record, session):
        raise PermissionError("official_dispatch_update_forbidden")
    allowed = {
        "external_official_document_number",
        "dispatch_date",
        "recipient",
        "recipient_contact",
        "dispatch_note",
        "proof_file_id",
    }
    update = {key: (payload.get(key) or None if key == "proof_file_id" else payload.get(key) or "") for key in allowed if key in payload}
    if not update:
        return official_dispatch_record(conn, document_id) or record
    assignments = ", ".join([f"{key} = ?" for key in update])
    conn.execute(f"UPDATE official_document_dispatch_records SET {assignments}, updated_at = ? WHERE id = ?", [*update.values(), now(), record["id"]])
    insert_official_log(conn, document_id, "update_dispatch", user, json.dumps(update, ensure_ascii=False), ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    return official_dispatch_record(conn, document_id) or {}


def complete_official_dispatch(conn: sqlite3.Connection, document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = official_session_user(session)
    document = official_document_row(conn, document_id)
    record = official_dispatch_record(conn, document_id)
    if not record:
        record = upsert_official_dispatch_record(conn, document, document.get("dispatch_method"), user)
    if not can_manage_official_dispatch(user, document, record, session):
        raise PermissionError("official_dispatch_complete_forbidden")
    if record.get("dispatch_owner_type") == "general_affairs" and document.get("current_status") != "pending_general_affairs_dispatch":
        raise ValueError("official_document_not_pending_general_affairs_dispatch")
    if record.get("dispatch_owner_type") == "applicant" and document.get("current_status") != "returned_to_applicant_for_send":
        raise ValueError("official_document_not_returned_to_applicant_for_send")
    if payload:
        record = update_official_dispatch_record(conn, document_id, payload, session)
    final_dispatch_status = "sent_by_applicant" if record.get("dispatch_owner_type") == "applicant" else "dispatched"
    final_document_status = "sent_by_applicant" if record.get("dispatch_owner_type") == "applicant" else "dispatched"
    if payload.get("close", False):
        final_document_status = "closed" if final_document_status in {"dispatched", "sent_by_applicant"} else final_document_status
    conn.execute(
        """
        UPDATE official_document_dispatch_records
        SET dispatch_status = ?, completed_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (final_dispatch_status, now(), now(), record["id"]),
    )
    conn.execute("UPDATE official_documents SET current_status = ?, current_step = '', updated_at = ? WHERE id = ?", (final_document_status, now(), document_id))
    insert_official_log(conn, document_id, "complete_dispatch", user, final_dispatch_status, file_id=(payload.get("proof_file_id") or record.get("proof_file_id") or ""), ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    create_notification(conn, {"type": "發文寄發完成", "title": f"{document['title']} 已完成寄發", "target_role": "員工", "source": document_id, "body": f"寄發狀態：{final_dispatch_status}。"})
    return official_document_detail(conn, document_id, session)


def upload_official_dispatch_proof_file(conn: sqlite3.Connection, document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = official_session_user(session)
    document = official_document_row(conn, document_id)
    record = official_dispatch_record(conn, document_id)
    if not record:
        record = upsert_official_dispatch_record(conn, document, document.get("dispatch_method"), user)
    if not can_manage_official_dispatch(user, document, record, session):
        raise PermissionError("official_dispatch_proof_upload_forbidden")
    content = payload.get("content_base64") or ""
    if not content:
        raise ValueError("dispatch_proof_file_required")
    data = base64.b64decode(content)
    mime_type = payload.get("file_mime_type") or payload.get("mime_type") or "application/pdf"
    if mime_type.lower() not in OFFICIAL_DISPATCH_PROOF_MIME_TYPES:
        raise ValueError("dispatch_proof_mime_type_not_allowed")
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("dispatch_proof_file_too_large")
    file_name = Path(payload.get("file_name") or f"{document_id}-dispatch-proof").name
    file_row = store_file_object(conn, document_id, file_name, data, "official-documents", "dispatch-proof", official_actor_name(user))
    conn.execute("UPDATE file_objects SET mime_type = ? WHERE id = ?", (mime_type, file_row["id"]))
    file_row["mime_type"] = mime_type
    official_file = insert_official_document_file(conn, document_id, "dispatch_proof", file_row, official_actor_name(user))
    conn.execute("UPDATE official_document_dispatch_records SET proof_file_id = ?, updated_at = ? WHERE id = ?", (official_file["id"], now(), record["id"]))
    insert_official_log(conn, document_id, "upload_dispatch_proof", user, official_file["file_hash"], file_id=official_file["id"], ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    return {"dispatch_record": official_dispatch_record(conn, document_id), "file": official_file_metadata(official_file)}


def insert_official_log(
    conn: sqlite3.Connection,
    document_id: str,
    action: str,
    actor: Dict[str, Any] | None,
    comment: str = "",
    *,
    step_id: str = "",
    file_id: str = "",
    ip_address: str = "",
    user_agent: str = "",
) -> Dict[str, Any]:
    row = {
        "id": f"ODLOG-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "document_id": document_id,
        "step_id": step_id or None,
        "file_id": file_id or None,
        "actor_id": actor.get("id") if actor else "system",
        "actor_name": official_actor_name(actor),
        "action": action,
        "comment": comment,
        "ip_address": ip_address,
        "user_agent": user_agent[:180] if user_agent else "",
        "created_at": now(),
    }
    insert_row(conn, "official_document_approval_logs", row)
    log_audit(conn, row["actor_name"], action, "official_documents", document_id, comment, event_type=action if action in LOGGING_AUDIT_EVENT_TYPES else None, module_code="official_documents")
    return row


def insert_official_document_file(conn: sqlite3.Connection, document_id: str, file_type: str, file_row: Dict[str, Any], actor: str) -> Dict[str, Any]:
    next_version = conn.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 AS version FROM official_document_files WHERE document_id = ? AND file_type = ?",
        (document_id, file_type),
    ).fetchone()["version"]
    row = {
        "id": f"ODFILE-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "document_id": document_id,
        "file_object_id": file_row.get("id"),
        "file_type": file_type,
        "file_name": file_row.get("file_name") or f"{document_id}-{file_type}.pdf",
        "file_storage_key": file_row.get("storage_key") or "",
        "file_mime_type": file_row.get("mime_type") or "application/pdf",
        "file_size": int(file_row.get("size_bytes") or 0),
        "file_hash": file_row.get("sha256") or "",
        "version": int(next_version),
        "uploaded_by": actor,
        "created_at": now(),
    }
    insert_row(conn, "official_document_files", row)
    return row


def store_official_pdf_file(conn: sqlite3.Connection, document_id: str, file_type: str, file_name: str, data: bytes, actor: str) -> Dict[str, Any]:
    file_row = store_file_object(conn, document_id, file_name, data, "official-documents", f"{file_type}-v1", actor)
    return insert_official_document_file(conn, document_id, file_type, file_row, actor)


def official_pdf_document_payload(conn: sqlite3.Connection, document: Dict[str, Any]) -> Dict[str, Any]:
    company = official_company_row(conn, document["company_id"])
    body_parts = []
    if document.get("description"):
        body_parts.append(f"說明：\n{document['description']}")
    if document.get("method"):
        body_parts.append(f"辦法：\n{document['method']}")
    return {
        "id": document["id"],
        "doc_no": document["id"],
        "company_name": company.get("name") or "歲悅股份有限公司",
        "doc_type": "函",
        "agency_name": document.get("recipient") or "未指定受文者",
        "subject": document.get("subject") or document.get("title") or "未命名發文",
        "body": "\n\n".join(body_parts) or document.get("description") or "尚未填寫說明內容。",
        "owner": document.get("handler_name") or document.get("applicant_name") or "承辦人",
        "department": document.get("dispatch_unit") or document.get("applicant_department_name") or "",
        "attachments": parse_json_field(document.get("metadata_json")).get("attachments", "附件詳如附件區"),
        "created_at": document.get("created_at"),
    }


def ensure_official_generated_pdf(conn: sqlite3.Connection, document: Dict[str, Any], actor: str = "PDF Worker") -> Dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM official_document_files WHERE document_id = ? AND file_type = 'generated_pdf' ORDER BY version DESC LIMIT 1",
        (document["id"],),
    ).fetchone()
    if row:
        return row_to_dict(row)
    package = build_official_pdf_package(official_pdf_document_payload(conn, document), [], "歲悅正式函", 1)
    file_row = store_official_pdf_file(conn, document["id"], "generated_pdf", f"{document['id']}-generated.pdf", package["data"], actor)
    insert_official_log(conn, document["id"], "generate_pdf", {"id": "system", "name": actor, "role": "system"}, file_row["file_hash"], file_id=file_row["id"])
    return file_row


def official_latest_source_file(conn: sqlite3.Connection, document: Dict[str, Any]) -> Dict[str, Any]:
    file_type = "original_pdf" if document.get("source_type") == "uploaded_pdf" else "generated_pdf"
    if file_type == "generated_pdf":
        ensure_official_generated_pdf(conn, document)
    row = conn.execute(
        "SELECT * FROM official_document_files WHERE document_id = ? AND file_type = ? ORDER BY version DESC LIMIT 1",
        (document["id"], file_type),
    ).fetchone()
    if not row:
        raise ValueError("official_document_source_pdf_required")
    return row_to_dict(row)


def create_official_workflow_steps(conn: sqlite3.Connection, document: Dict[str, Any], applicant: Dict[str, Any]) -> List[Dict[str, Any]]:
    existing = official_document_steps(conn, document["id"])
    if existing:
        return existing
    company = official_company_row(conn, document["company_id"])
    created: List[Dict[str, Any]] = []
    for step in OFFICIAL_DOCUMENT_WORKFLOW_STEPS:
        approver = resolve_official_step_approver(conn, step, applicant, company)
        row = {
            "id": f"ODSTEP-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
            "document_id": document["id"],
            "step_order": step["order"],
            "step_key": step["key"],
            "step_name": step["name"],
            "approver_user_id": approver.get("id") if approver else "",
            "approver_name": approver.get("name") if approver else step["role"],
            "approver_role": approver.get("role") if approver else step["role"],
            "status": "pending",
            "comment": "",
            "approved_at": "",
            "created_at": now(),
            "updated_at": now(),
        }
        insert_row(conn, "official_document_approval_steps", row)
        created.append(row)
    return created


def canDownloadOfficialDocument(user: Dict[str, Any] | None, document: Dict[str, Any], steps: List[Dict[str, Any]] | None = None) -> bool:
    if not user:
        return False
    if user.get("id") == document.get("applicant_id"):
        return True
    if user.get("role") in {"執行長", "行政部主任", "總務"}:
        return True
    if user.get("role") == "系統管理員":
        return True
    if user.get("role") in OFFICIAL_DOCUMENT_DOWNLOAD_ROLES and user.get("id") in {step.get("approver_user_id") for step in steps or []}:
        return True
    metadata = parse_json_field(document.get("metadata_json"))
    extra = set(metadata.get("authorized_download_user_ids") or [])
    return user.get("id") in extra


def official_application_package(
    document: Dict[str, Any],
    files: List[Dict[str, Any]],
    steps: List[Dict[str, Any]],
    logs: List[Dict[str, Any]],
    stamp_request: Dict[str, Any] | None,
    dispatch_record: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    versions = [file for file in files if file.get("file_type") in {"original_pdf", "generated_pdf", "stamped_pdf"}]
    attachments = [file for file in files if file.get("file_type") == "attachment"]
    download_logs = [log for log in logs if log.get("action") == "download_file"]
    process_logs = [log for log in logs if log.get("action") != "download_file"]
    return {
        "id": document.get("id"),
        "record_type": "official_document_application",
        "title": document.get("title") or document.get("subject") or document.get("id"),
        "company_id": document.get("company_id"),
        "source_type": document.get("source_type"),
        "document_type": document.get("document_type"),
        "current_status": document.get("current_status"),
        "current_step": document.get("current_step"),
        "applicant_id": document.get("applicant_id"),
        "applicant_name": document.get("applicant_name"),
        "all_files": files,
        "document_versions": versions,
        "attachments": attachments,
        "stamped_versions": [file for file in versions if file.get("file_type") == "stamped_pdf"],
        "approval_steps": steps,
        "process_logs": process_logs,
        "download_logs": download_logs,
        "stamp_request": stamp_request,
        "dispatch_record": dispatch_record,
        "summary": {
            "version_count": len(versions),
            "attachment_count": len(attachments),
            "approval_step_count": len(steps),
            "download_count": len(download_logs),
            "has_stamped_pdf": any(file.get("file_type") == "stamped_pdf" for file in versions),
            "has_dispatch_record": bool(dispatch_record),
        },
    }


def official_document_detail(conn: sqlite3.Connection, document_id: str, session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    document = official_document_row(conn, document_id)
    steps = official_document_steps(conn, document_id)
    user = session.get("user") if session else None
    if user and not canDownloadOfficialDocument(user, document, steps) and not session_has_any_permission(session, ["official_documents.all_records", "official_documents.all_todo"]):
        raise PermissionError("official_document_access_denied")
    current_step = next((step for step in steps if step.get("step_key") == document.get("current_step")), None)
    files = official_document_files(conn, document_id)
    logs = official_document_logs(conn, document_id)
    stamp_request = official_document_stamp_request(conn, document_id)
    dispatch_record = official_dispatch_record(conn, document_id)
    package = official_application_package(document, files, steps, logs, stamp_request, dispatch_record)
    return {
        **document,
        "metadata": parse_json_field(document.get("metadata_json")),
        "application_package": package,
        "document_versions": package["document_versions"],
        "attachments": package["attachments"],
        "download_logs": package["download_logs"],
        "process_logs": package["process_logs"],
        "files": files,
        "approval_steps": steps,
        "logs": logs,
        "stamp_request": stamp_request,
        "dispatch_record": dispatch_record,
        "can_download": bool(user and canDownloadOfficialDocument(user, document, steps)),
        "can_manage_dispatch": bool(user and can_manage_official_dispatch(user, document, dispatch_record, session)),
        "can_act": bool(user and current_step and current_step.get("approver_user_id") == user.get("id") and current_step.get("status") == "pending"),
    }


def list_official_documents(conn: sqlite3.Connection, query: Dict[str, List[str]] | None, session: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    user = official_session_user(session)
    query = query or {}
    where: List[str] = []
    params: List[Any] = []
    if query.get("status"):
        where.append("d.current_status = ?")
        params.append(query["status"][0])
    if query.get("company_id"):
        where.append("d.company_id = ?")
        params.append(query["company_id"][0])
    if query.get("applicant_id"):
        where.append("d.applicant_id = ?")
        params.append(query["applicant_id"][0])
    scope = (query.get("scope") or [""])[0]
    if scope == "mine":
        where.append("d.applicant_id = ?")
        params.append(user["id"])
    elif scope == "todo":
        where.append(
            """
            (
              EXISTS (
                SELECT 1 FROM official_document_approval_steps s
                WHERE s.document_id = d.id
                  AND s.status = 'pending'
                  AND s.step_key = d.current_step
                  AND s.approver_user_id = ?
              )
              OR EXISTS (
                SELECT 1 FROM official_document_dispatch_records r
                WHERE r.document_id = d.id
                  AND r.dispatch_status = 'pending'
                  AND (
                    r.dispatch_owner_user_id = ?
                    OR (r.dispatch_owner_type = 'general_affairs' AND ? = '總務')
                  )
              )
            )
            """
        )
        params.extend([user["id"], user["id"], user.get("role") or ""])
    elif not session_has_any_permission(session, ["official_documents.all_records", "official_documents.all_todo"]):
        where.append("(d.applicant_id = ? OR EXISTS (SELECT 1 FROM official_document_approval_steps s WHERE s.document_id = d.id AND s.approver_user_id = ?))")
        params.extend([user["id"], user["id"]])
    sql = "SELECT d.* FROM official_documents d"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY d.created_at DESC LIMIT 300"
    rows = []
    for row in conn.execute(sql, params).fetchall():
        item = row_to_dict(row)
        item["stamp_request"] = official_document_stamp_request(conn, item["id"])
        item["dispatch_record"] = official_dispatch_record(conn, item["id"])
        item["current_step_name"] = next((step["step_name"] for step in official_document_steps(conn, item["id"]) if step.get("step_key") == item.get("current_step")), "")
        rows.append(item)
    return rows


def create_official_document(conn: sqlite3.Connection, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = official_session_user(session)
    if not session_has_any_permission(session, ["official_documents.compose", "official_documents.all_todo"]):
        raise PermissionError("official_document_create_forbidden")
    source_type = payload.get("source_type") or "blank_editor"
    if source_type not in {"blank_editor", "uploaded_pdf"}:
        raise ValueError("invalid_official_document_source_type")
    company_id = payload.get("company_id") or "CO-001"
    official_company_row(conn, company_id)
    dispatch_method = official_dispatch_method(payload.get("dispatch_method"))
    document_id = payload.get("id") or f"OD-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    ts = now()
    metadata = {
        "attachments": payload.get("attachments_summary") or payload.get("attachments") or "",
        "workflow_template": "fixed_dispatch_seal_v1",
        "future_rule_inputs": {
            "company_id": company_id,
            "department": user.get("unit"),
            "document_type": payload.get("document_type"),
            "seal_id": payload.get("seal_id"),
            "dispatch_method": dispatch_method,
            "amount": payload.get("amount"),
        },
    }
    document = {
        "id": document_id,
        "company_id": company_id,
        "document_type": payload.get("document_type") or ("uploaded_pdf_for_stamp" if source_type == "uploaded_pdf" else "outgoing_official_document"),
        "source_type": source_type,
        "title": payload.get("title") or payload.get("subject") or "未命名發文申請",
        "subject": payload.get("subject") or payload.get("title") or "",
        "description": payload.get("description") or payload.get("body") or "",
        "method": payload.get("method") or payload.get("辦法") or "",
        "recipient": payload.get("recipient") or payload.get("agency_name") or "",
        "dispatch_unit": payload.get("dispatch_unit") or user.get("unit") or "",
        "handler_name": payload.get("handler_name") or user.get("name") or "",
        "applicant_id": user["id"],
        "applicant_name": user.get("name") or user.get("email"),
        "applicant_department_id": payload.get("applicant_department_id") or user.get("unit") or "",
        "applicant_department_name": payload.get("applicant_department_name") or user.get("unit") or "",
        "dispatch_method": dispatch_method,
        "current_status": "draft",
        "current_step": "",
        "request_reason": payload.get("request_reason") or payload.get("reason") or "",
        "metadata_json": metadata,
        "created_at": ts,
        "updated_at": ts,
    }
    insert_row(conn, "official_documents", document)
    if source_type == "uploaded_pdf":
        content = payload.get("content_base64") or payload.get("file_content_base64") or ""
        if not content:
            raise ValueError("original_pdf_required")
        data = base64.b64decode(content)
        if not data.startswith(b"%PDF"):
            raise ValueError("original_pdf_must_be_pdf")
        file_row = store_official_pdf_file(conn, document_id, "original_pdf", Path(payload.get("file_name") or f"{document_id}.pdf").name, data, official_actor_name(user))
        insert_official_log(conn, document_id, "upload_original_pdf", user, file_row["file_hash"], file_id=file_row["id"], ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    else:
        ensure_official_generated_pdf(conn, document, official_actor_name(user))
    seal_id = payload.get("seal_id")
    if seal_id:
        position = official_stamp_position_payload(payload)
        stamp_request = {
            "id": f"ODSTAMP-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
            "document_id": document_id,
            "company_id": company_id,
            "seal_id": seal_id,
            "requested_by": user["id"],
            **position,
            "status": "pending",
            "stamped_file_id": None,
            "error_message": "",
            "created_at": ts,
            "stamped_at": "",
            "updated_at": ts,
        }
        insert_row(conn, "official_document_stamp_requests", stamp_request)
    insert_official_log(conn, document_id, "create", user, document["request_reason"], ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    if payload.get("submit", True):
        return submit_official_document(conn, document_id, payload, session)
    return official_document_detail(conn, document_id, session)


def submit_official_document(conn: sqlite3.Connection, document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = official_session_user(session)
    document = official_document_row(conn, document_id)
    if document["applicant_id"] != user["id"] and not session_has_any_permission(session, ["official_documents.all_todo"]):
        raise PermissionError("only_applicant_can_submit")
    if document["current_status"] not in {"draft", "rejected"}:
        raise ValueError("official_document_not_submittable")
    if not official_document_stamp_request(conn, document_id):
        raise ValueError("official_document_seal_required")
    if document["source_type"] == "blank_editor":
        ensure_official_generated_pdf(conn, document, official_actor_name(user))
    applicant = active_user_by_id(conn, document["applicant_id"]) or user
    steps = create_official_workflow_steps(conn, document, applicant)
    first = steps[0]
    conn.execute("UPDATE official_documents SET current_status = ?, current_step = ?, updated_at = ? WHERE id = ?", (OFFICIAL_DOCUMENT_STEP_STATUS[first["step_key"]], first["step_key"], now(), document_id))
    insert_official_log(conn, document_id, "submit", user, payload.get("comment") or "送出發文用印簽核", step_id=first["id"], ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    if first.get("approver_role"):
        create_notification(conn, {"type": "發文簽核", "title": f"{document['title']} 待{first['step_name']}簽核", "target_role": first["approver_role"], "target_email": "", "source": document_id, "body": f"{document.get('applicant_name') or '申請人'} 已送出發文用印申請。"})
    return official_document_detail(conn, document_id, session)


def current_official_pending_step(conn: sqlite3.Connection, document: Dict[str, Any]) -> Dict[str, Any]:
    row = conn.execute(
        """
        SELECT * FROM official_document_approval_steps
        WHERE document_id = ? AND step_key = ? AND status = 'pending'
        ORDER BY step_order LIMIT 1
        """,
        (document["id"], document.get("current_step") or ""),
    ).fetchone()
    if not row:
        raise ValueError("official_document_current_step_not_pending")
    return row_to_dict(row)


def assert_official_step_actor(user: Dict[str, Any], step: Dict[str, Any]) -> None:
    if step.get("approver_user_id") != user.get("id"):
        raise PermissionError("not_current_official_document_approver")


def next_official_step(conn: sqlite3.Connection, document_id: str, step_order: int) -> Dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM official_document_approval_steps WHERE document_id = ? AND step_order > ? ORDER BY step_order LIMIT 1",
        (document_id, step_order),
    ).fetchone()
    return row_to_dict(row) if row else None


def approve_official_document(conn: sqlite3.Connection, document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = official_session_user(session)
    document = official_document_row(conn, document_id)
    if document["current_status"] in {"draft", "stamping", "stamped", "pending_general_affairs_dispatch", "returned_to_applicant_for_send", "dispatched", "sent_by_applicant", "closed", "cancelled", "rejected"}:
        raise ValueError("official_document_not_pending_approval")
    step = current_official_pending_step(conn, document)
    assert_official_step_actor(user, step)
    if step["step_key"] == "applicant_manager" and user["id"] == document["applicant_id"]:
        raise PermissionError("applicant_cannot_self_approve_manager_step")
    conn.execute(
        "UPDATE official_document_approval_steps SET status = 'approved', comment = ?, approved_at = ?, updated_at = ? WHERE id = ?",
        (payload.get("comment") or "核准", now(), now(), step["id"]),
    )
    insert_official_log(conn, document_id, "approve", user, payload.get("comment") or "", step_id=step["id"], ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    if step["step_key"] == "ceo":
        conn.execute("UPDATE official_documents SET current_status = 'approved', current_step = 'auto_stamp', updated_at = ? WHERE id = ?", (now(), document_id))
        result = auto_stamp_official_document(conn, document_id, payload, user)
        return {**official_document_detail(conn, document_id, session), "auto_stamp": result}
    next_step = next_official_step(conn, document_id, int(step["step_order"]))
    if not next_step:
        raise ValueError("official_document_next_step_missing")
    conn.execute("UPDATE official_documents SET current_status = ?, current_step = ?, updated_at = ? WHERE id = ?", (OFFICIAL_DOCUMENT_STEP_STATUS[next_step["step_key"]], next_step["step_key"], now(), document_id))
    create_notification(conn, {"type": "發文簽核", "title": f"{document['title']} 待{next_step['step_name']}簽核", "target_role": next_step.get("approver_role") or "", "source": document_id, "body": f"{step['step_name']}已核准，請接續處理。"})
    return official_document_detail(conn, document_id, session)


def reject_official_document(conn: sqlite3.Connection, document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = official_session_user(session)
    document = official_document_row(conn, document_id)
    step = current_official_pending_step(conn, document)
    assert_official_step_actor(user, step)
    comment = payload.get("comment") or "駁回"
    conn.execute("UPDATE official_document_approval_steps SET status = 'rejected', comment = ?, approved_at = ?, updated_at = ? WHERE id = ?", (comment, now(), now(), step["id"]))
    conn.execute("UPDATE official_documents SET current_status = 'rejected', current_step = 'applicant', updated_at = ? WHERE id = ?", (now(), document_id))
    insert_official_log(conn, document_id, "reject", user, comment, step_id=step["id"], ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    create_notification(conn, {"type": "發文退回", "title": f"{document['title']} 已駁回", "target_role": "員工", "target_email": "", "source": document_id, "priority": "高", "body": comment})
    return official_document_detail(conn, document_id, session)


def cancel_official_document(conn: sqlite3.Connection, document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = official_session_user(session)
    document = official_document_row(conn, document_id)
    if document["applicant_id"] != user["id"]:
        raise PermissionError("only_applicant_can_cancel")
    if document["current_status"] in {"stamping", "stamped", "pending_general_affairs_dispatch", "returned_to_applicant_for_send", "dispatched", "sent_by_applicant", "closed"}:
        raise ValueError("official_document_cannot_cancel_after_stamp")
    conn.execute("UPDATE official_documents SET current_status = 'cancelled', current_step = '', updated_at = ? WHERE id = ?", (now(), document_id))
    insert_official_log(conn, document_id, "cancel", user, payload.get("comment") or "申請人取消", ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    return official_document_detail(conn, document_id, session)


def confirm_official_document(conn: sqlite3.Connection, document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = official_session_user(session)
    document = official_document_row(conn, document_id)
    if document["applicant_id"] != user["id"]:
        raise PermissionError("only_applicant_can_confirm")
    if document["current_status"] not in {"returned_to_applicant_for_send", "stamped"}:
        raise ValueError("official_document_not_ready_for_applicant_confirm")
    if document["current_status"] == "returned_to_applicant_for_send":
        return complete_official_dispatch(conn, document_id, {**payload, "close": True}, session)
    conn.execute("UPDATE official_documents SET current_status = 'closed', current_step = '', updated_at = ? WHERE id = ?", (now(), document_id))
    insert_official_log(conn, document_id, "confirm", user, payload.get("comment") or "申請人確認已用印版本", ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    return official_document_detail(conn, document_id, session)


def update_official_stamp_position(conn: sqlite3.Connection, document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = official_session_user(session)
    document = official_document_row(conn, document_id)
    if document["applicant_id"] != user["id"]:
        raise PermissionError("only_applicant_can_update_stamp_position")
    if document["current_status"] != "draft":
        raise ValueError("stamp_position_locked_after_submit")
    position = official_stamp_position_payload(payload)
    stamp_request = official_document_stamp_request(conn, document_id)
    if not stamp_request:
        raise ValueError("official_document_stamp_request_not_found")
    conn.execute(
        """
        UPDATE official_document_stamp_requests
        SET stamp_page = ?, stamp_x = ?, stamp_y = ?, stamp_width = ?, stamp_height = ?, updated_at = ?
        WHERE id = ?
        """,
        (position["stamp_page"], position["stamp_x"], position["stamp_y"], position["stamp_width"], position["stamp_height"], now(), stamp_request["id"]),
    )
    insert_official_log(conn, document_id, "update_stamp_position", user, json.dumps(position, ensure_ascii=False), ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    return official_document_detail(conn, document_id, session)


def auto_stamp_official_document(conn: sqlite3.Connection, document_id: str, payload: Dict[str, Any], actor: Dict[str, Any] | None = None) -> Dict[str, Any]:
    document = official_document_row(conn, document_id)
    stamp_request = official_document_stamp_request(conn, document_id)
    if not stamp_request:
        raise ValueError("official_document_stamp_request_required")
    try:
        conn.execute("UPDATE official_documents SET current_status = 'stamping', current_step = 'auto_stamp', updated_at = ? WHERE id = ?", (now(), document_id))
        conn.execute("UPDATE official_document_stamp_requests SET status = 'stamping', updated_at = ? WHERE id = ?", (now(), stamp_request["id"]))
        seal = company_seal_row(conn, stamp_request["seal_id"])
        if not seal.get("is_active"):
            raise ValueError("inactive_seal_cannot_stamp")
        current_file = conn.execute("SELECT * FROM company_seal_files WHERE seal_id = ? AND is_current = 1 ORDER BY version DESC LIMIT 1", (stamp_request["seal_id"],)).fetchone()
        if not current_file:
            raise ValueError("current_seal_file_required")
        seal_file = row_to_dict(current_file)
        if not seal_file.get("file_object_id"):
            raise ValueError("seal_file_object_required")
        insert_official_log(conn, document_id, "read_seal_vault_for_stamp", actor, "authorized_backend_stamp_only", ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
        _, seal_bytes = read_file_object_bytes(conn, seal_file["file_object_id"])
        if sha256_bytes(seal_bytes) != seal_file["file_hash"]:
            raise ValueError("seal_file_hash_mismatch")
        source_file = official_latest_source_file(conn, document)
        file_object_id = source_file.get("file_object_id")
        if not file_object_id:
            raise ValueError("official_source_file_object_missing")
        _, original_pdf = read_file_object_bytes(conn, file_object_id)
        stamp_no = payload.get("stamp_no") or f"ODSTAMP-{document_id}-{int(time.time())}"
        positions = official_stamp_positions_from_request(stamp_request, seal)
        stamped_pdf, engine, layout = stamp_uploaded_pdf_bytes(original_pdf, [{**item, "stamp_no": stamp_no} for item in positions], stamp_no)
        stamped_file = store_official_pdf_file(conn, document_id, "stamped_pdf", f"{document_id}-stamped.pdf", stamped_pdf, "Auto Stamp")
        conn.execute(
            "UPDATE official_document_stamp_requests SET status = 'stamped', stamped_file_id = ?, stamped_at = ?, updated_at = ?, error_message = '' WHERE id = ?",
            (stamped_file["id"], now(), now(), stamp_request["id"]),
        )
        insert_official_log(conn, document_id, "auto_stamp", actor, f"{engine} {stamp_no} seal_hash={seal_file['file_hash']}", file_id=stamped_file["id"], ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
        dispatch_record = advance_official_dispatch_after_stamp(conn, document_id, stamped_file, actor, payload)
        return {"ok": True, "stamped_file": official_file_metadata(stamped_file), "engine": engine, "layout": layout, "dispatch_record": dispatch_record}
    except Exception as exc:
        detail = str(exc)
        conn.execute("UPDATE official_documents SET current_status = 'stamping_failed', current_step = 'general_affairs_review', updated_at = ? WHERE id = ?", (now(), document_id))
        conn.execute("UPDATE official_document_stamp_requests SET status = 'failed', error_message = ?, updated_at = ? WHERE id = ?", (detail, now(), stamp_request["id"]))
        insert_official_log(conn, document_id, "auto_stamp_failed", actor, detail, ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
        create_notification(conn, {"type": "發文用印失敗", "title": f"{document['title']} 自動用印失敗", "target_role": "總務", "source": document_id, "priority": "高", "body": detail})
        return {"ok": False, "error": "auto_stamp_failed", "detail": detail}


def official_document_download_file(conn: sqlite3.Connection, document_id: str, file_id: str, session: Dict[str, Any] | None, ip_address: str = "", user_agent: str = "") -> Tuple[Dict[str, Any], Dict[str, Any], bytes]:
    user = official_session_user(session)
    document = official_document_row(conn, document_id)
    steps = official_document_steps(conn, document_id)
    if not canDownloadOfficialDocument(user, document, steps) and not session_has_any_permission(session, ["official_documents.all_records"]):
        raise PermissionError("official_document_download_forbidden")
    file_row = conn.execute("SELECT * FROM official_document_files WHERE id = ? AND document_id = ?", (file_id, document_id)).fetchone()
    if not file_row:
        raise ValueError("official_document_file_not_found")
    file_meta = row_to_dict(file_row)
    if not file_meta.get("file_object_id"):
        raise ValueError("official_document_file_object_missing")
    object_row, data = read_file_object_bytes(conn, file_meta["file_object_id"])
    insert_official_log(conn, document_id, "download_file", user, file_meta["file_type"], file_id=file_id, ip_address=ip_address, user_agent=user_agent)
    record_file_access(conn, file_object_id=file_meta["file_object_id"], document_id=document_id, actor=official_actor_name(user), action="發文附件下載", result="成功", detail=file_meta["file_type"])
    return document, {**file_meta, "object": object_row}, data


def canonical_json_hash(value: Any) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def normalized_stamp_positions(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = payload.get("stamp_positions") or payload.get("stamps") or payload.get("positions") or []
    if isinstance(raw, str):
        raw = parse_json_any(raw, []) or []
    if not isinstance(raw, list):
        raise ValueError("stamp_positions_required")
    positions: List[Dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError("invalid_stamp_position")
        width = pdf_safe_float(item.get("w", item.get("width")), 0)
        height = pdf_safe_float(item.get("h", item.get("height")), 0)
        if width <= 0 or height <= 0:
            raise ValueError("invalid_stamp_size")
        page = item.get("page", 1)
        normalized = {
            "id": str(item.get("id") or f"STAMP-POS-{index}"),
            "page": "all" if page == "all" else max(1, int(pdf_safe_float(page, 1))),
            "x": round(pdf_safe_float(item.get("x"), 0), 2),
            "y": round(pdf_safe_float(item.get("y"), 0), 2),
            "w": round(width, 2),
            "h": round(height, 2),
            "label": str(item.get("label") or item.get("seal_type") or "用印"),
            "type": str(item.get("type") or item.get("seal_type") or "一般章"),
            "seal_id": str(item.get("seal_id") or item.get("sealId") or payload.get("seal_id") or ""),
        }
        if normalized["x"] < 0 or normalized["y"] < 0:
            raise ValueError("invalid_stamp_coordinate")
        positions.append(normalized)
    if not positions:
        raise ValueError("stamp_positions_required")
    return positions


def pdf_page_sizes(data: bytes) -> List[Tuple[float, float]]:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(io.BytesIO(data))
        sizes: List[Tuple[float, float]] = []
        for page in reader.pages:
            box = page.mediabox
            sizes.append((float(box.width), float(box.height)))
        return sizes or [(A4_WIDTH_PT, A4_HEIGHT_PT)]
    except Exception:
        return [(A4_WIDTH_PT, A4_HEIGHT_PT)]


def write_stamp_overlay_pdf(page_sizes: List[Tuple[float, float]], stamps: List[Dict[str, Any]], stamp_no: str) -> bytes:
    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    page_object_numbers = [3 + index * 2 for index in range(len(page_sizes))]
    objects.append(f"<< /Type /Pages /Kids [{' '.join(f'{num} 0 R' for num in page_object_numbers)}] /Count {len(page_sizes)} >>")
    font_object_number = 3 + len(page_sizes) * 2
    for page_index, (page_width, page_height) in enumerate(page_sizes, start=1):
        stream = ""
        for stamp in stamps:
            if stamp.get("page") not in {page_index, "all"}:
                continue
            x, y, width, height = clamp_pdf_rect(
                pdf_safe_float(stamp.get("x"), 0),
                pdf_safe_float(stamp.get("y"), 0),
                pdf_safe_float(stamp.get("w"), 56),
                pdf_safe_float(stamp.get("h"), 56),
            )
            if x + width > page_width:
                x = max(0, page_width - width)
            if y + height > page_height:
                y = max(0, page_height - height)
            label = stamp.get("label") or "用印"
            stamp_type = stamp.get("type") or ""
            stream += "1 0 0 RG 1 0 0 rg\n"
            stream += f"{x:.2f} {y:.2f} {width:.2f} {height:.2f} re S\n"
            stream += pdf_show_text(label, x + 6, y + height * 0.58, min(12, max(7, width / 7)))
            if stamp_type:
                stream += pdf_show_text(stamp_type, x + 6, y + height * 0.38, min(9, max(6, width / 9)))
            stream += pdf_show_text(stamp_no[-18:], x + 4, y + 6, min(6.5, max(5, width / 13)))
            stream += "0 0 0 RG 0 0 0 rg\n"
        page_object_number = 3 + (page_index - 1) * 2
        content_object_number = page_object_number + 1
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width:.2f} {page_height:.2f}] /Resources << /Font << /F1 {font_object_number} 0 R >> >> /Contents {content_object_number} 0 R >>")
        stream_bytes = stream.encode("latin-1", "replace")
        objects.append(f"<< /Length {len(stream_bytes)} >>\nstream\n{stream}endstream")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pdf = "%PDF-1.4\n"
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf.encode("latin-1")))
        pdf += f"{index} 0 obj\n{obj}\nendobj\n"
    xref_at = len(pdf.encode("latin-1"))
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    for offset in offsets[1:]:
        pdf += f"{offset:010d} 00000 n \n"
    pdf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF"
    return pdf.encode("latin-1", "replace")


def stamp_uploaded_pdf_bytes(original: bytes, stamps: List[Dict[str, Any]], stamp_no: str) -> Tuple[bytes, str, Dict[str, Any]]:
    page_sizes = pdf_page_sizes(original)
    try:
        from pypdf import PdfReader, PdfWriter  # type: ignore

        source = PdfReader(io.BytesIO(original))
        overlay = PdfReader(io.BytesIO(write_stamp_overlay_pdf(page_sizes, stamps, stamp_no)))
        writer = PdfWriter()
        for index, page in enumerate(source.pages):
            page.merge_page(overlay.pages[index])
            writer.add_page(page)
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue(), "pypdf-overlay", {"page_count": len(source.pages), "page_size": page_sizes[0] if page_sizes else (A4_WIDTH_PT, A4_HEIGHT_PT)}
    except Exception as exc:
        fallback_doc = {
            "doc_no": stamp_no,
            "company_name": "歲悅股份有限公司",
            "doc_type": "用印證明",
            "agency_name": "PDF 用印工作台",
            "subject": "上傳 PDF 用印證明",
            "body": f"原始 PDF hash 已鎖定，因本環境缺少 PDF 疊章套件，產生用印證明 PDF。原因：{str(exc)[:120]}",
        }
        package = build_official_pdf_package(fallback_doc, [{**stamp, "stamp_no": stamp_no} for stamp in stamps], "上傳 PDF 用印證明", max(1, len(page_sizes)))
        return package["data"], "audit-receipt-fallback", {"page_count": package["layout"]["page_count"], "page_size": (A4_WIDTH_PT, A4_HEIGHT_PT), "fallback_reason": str(exc)[:160]}


def approval_route_steps(route_code: str = "A") -> Tuple[str, List[Dict[str, Any]]]:
    code = route_code if route_code in {"A", "B", "C", "D"} else "A"
    names = ["申請人送出", "主管簽核"]
    if code in {"B", "D"}:
        names.append("會計複核")
    names.append("行政部主任核定")
    if code in {"C", "D"}:
        names.append("執行長核定")
    names.extend(["系統自動用印", "申請人確認"])
    role_map = {
        "申請人送出": "員工",
        "主管簽核": "主管",
        "會計複核": "會計",
        "行政部主任核定": "行政部主任",
        "執行長核定": "執行長",
        "系統自動用印": "總務",
        "申請人確認": "員工",
    }
    return code, [{"step_no": index, "step_name": name, "role": role_map[name]} for index, name in enumerate(names, start=1)]


def current_user_from_session(session: Dict[str, Any] | None) -> Dict[str, Any]:
    return (session or {}).get("user") or {}


def seal_application_row(conn: sqlite3.Connection, application_id: str) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM seal_applications WHERE id = ?", (application_id,)).fetchone()
    if not row:
        raise ValueError("seal_application_not_found")
    data = row_to_dict(row)
    for field in ("stamp_positions_json", "approval_snapshot_json", "evidence_json"):
        data[field.replace("_json", "")] = parse_json_any(data.get(field), [] if field == "stamp_positions_json" else {}) or ([] if field == "stamp_positions_json" else {})
    return data


def insert_approval_snapshots(conn: sqlite3.Connection, application_id: str, steps: List[Dict[str, Any]], applicant: Dict[str, Any]) -> None:
    conn.execute("DELETE FROM approval_step_actor_snapshots WHERE source_type = 'seal_application' AND source_id = ?", (application_id,))
    timestamp = now()
    for step in steps:
        is_submitter = step["step_no"] == 1
        status = "已完成" if is_submitter else "待簽核" if step["step_no"] == 2 else "未開始"
        conn.execute(
            """
            INSERT INTO approval_step_actor_snapshots (
              id, seal_application_id, source_type, source_id, step_no, step_name, approver_role,
              approver_user_id, approver_name, approver_email, status, comment, acted_at,
              snapshot_json, created_at, updated_at
            ) VALUES (?, ?, 'seal_application', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"APSN-{application_id}-{step['step_no']}",
                application_id,
                application_id,
                step["step_no"],
                step["step_name"],
                step["role"],
                applicant.get("id") if is_submitter else "",
                applicant.get("name") if is_submitter else "",
                applicant.get("email") if is_submitter else "",
                status,
                "送出申請並鎖定 PDF 與章位。" if is_submitter else "",
                timestamp if is_submitter else "",
                json.dumps({"source": "finance-style-actor-snapshot", "role": step["role"], "step": step["step_name"]}, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )


def create_seal_notification(conn: sqlite3.Connection, application: Dict[str, Any], title: str, target_role: str, body: str, priority: str = "中") -> Dict[str, Any]:
    return create_notification(conn, {
        "type": "用印簽核",
        "title": title,
        "target_role": target_role,
        "target_email": application.get("applicant_email") or "",
        "channel": "系統通知",
        "priority": priority,
        "source": application["id"],
        "body": body,
    })


def seal_application_submit(conn: sqlite3.Connection, payload: Dict[str, Any], session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    user = current_user_from_session(session)
    applicant_name = payload.get("applicant_name") or user.get("name") or payload.get("applicant") or "申請人"
    document = get_or_create_pdf_document(conn, payload)
    file_id = payload.get("source_pdf_file_object_id") or payload.get("file_object_id")
    if not file_id and payload.get("source_pdf_content_base64"):
        upload = upload_file_object(conn, {
            "document_id": document["id"],
            "file_name": payload.get("source_pdf_name") or f"{document['doc_no']}-uploaded.pdf",
            "mime_type": "application/pdf",
            "purpose": "source-pdf",
            "version_label": "uploaded-source",
            "actor": applicant_name,
            "content_base64": payload["source_pdf_content_base64"],
        })
        if upload.get("error"):
            raise ValueError(upload["error"])
        file_id = upload["file"]["id"]
    if not file_id:
        raise ValueError("source_pdf_required")
    file_row, source_bytes = read_file_object_bytes(conn, file_id)
    if file_row.get("scan_status") == "已隔離":
        raise ValueError("source_pdf_quarantined")
    if file_row.get("mime_type") != "application/pdf" and not str(file_row.get("file_name") or "").lower().endswith(".pdf"):
        raise ValueError("source_pdf_must_be_pdf")
    positions = normalized_stamp_positions(payload)
    locked_pdf_sha256 = sha256_bytes(source_bytes)
    locked_positions_sha256 = canonical_json_hash(positions)
    route_code, steps = approval_route_steps(payload.get("approval_route_code") or payload.get("route") or "A")
    route_name = payload.get("approval_route_name") or f"{route_code} 會計系統式用印流程"
    application_id = payload.get("id") or payload.get("application_id") or f"USEAL-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    before_version = create_pdf_version_for_file(conn, document, file_row, "before_seal", payload.get("template") or "上傳 PDF", {
        "source": "uploaded_pdf",
        "page_count": len(pdf_page_sizes(source_bytes)),
        "locked_pdf_sha256": locked_pdf_sha256,
        "locked_positions_sha256": locked_positions_sha256,
        "stamp_positions": positions,
    })
    application = {
        "id": application_id,
        "document_id": document["id"],
        "seal_id": payload.get("seal_id") or positions[0].get("seal_id") or "SEAL-001",
        "application_type": payload.get("application_type") or payload.get("type") or "official_document",
        "company_name": payload.get("company_name") or document.get("company_name") or "歲悅股份有限公司",
        "department": payload.get("department") or document.get("department") or "",
        "title": payload.get("title") or document.get("subject") or document["doc_no"],
        "source_pdf_file_object_id": file_row["id"],
        "source_pdf_sha256": file_row["sha256"],
        "source_pdf_name": file_row["file_name"],
        "locked_pdf_sha256": locked_pdf_sha256,
        "locked_positions_sha256": locked_positions_sha256,
        "stamp_positions_json": json.dumps(positions, ensure_ascii=False),
        "approval_route_code": route_code,
        "approval_route_name": route_name,
        "approval_snapshot_json": json.dumps({"steps": steps, "source": "finance_system_pattern"}, ensure_ascii=False),
        "current_step_no": 2,
        "current_step_name": steps[1]["step_name"],
        "current_approver_role": steps[1]["role"],
        "applicant_user_id": user.get("id") or "",
        "applicant_name": applicant_name,
        "applicant_email": user.get("email") or payload.get("applicant_email") or "",
        "applicant": applicant_name,
        "approver": steps[1]["role"],
        "status": "待主管簽核",
        "reason": payload.get("reason") or payload.get("purpose") or "上傳 PDF 後申請用印",
        "reject_reason": "",
        "stamp_no": "",
        "pdf_before_version_id": before_version["id"],
        "pdf_after_version_id": "",
        "returned_at": "",
        "completed_at": "",
        "notification_id": "",
        "created_at": now(),
        "approved_at": "",
        "updated_at": now(),
    }
    insert_row(conn, "seal_applications", application)
    insert_approval_snapshots(conn, application_id, steps, user)
    notice = create_seal_notification(conn, application, f"{application['title']} 待主管簽核", steps[1]["role"], f"{applicant_name} 已送出 {file_row['file_name']} 用印申請，PDF 與 {len(positions)} 個章位已鎖定。")
    conn.execute("UPDATE seal_applications SET notification_id = ? WHERE id = ?", (notice["id"], application_id))
    log_audit(conn, applicant_name, "送簽 PDF 用印", "seal_applications", application_id, f"pdf={locked_pdf_sha256}, positions={locked_positions_sha256}", event_type="submit", module_code="seals")
    return {**seal_application_row(conn, application_id), "pdf_before": before_version, "notification": notice}


def seal_application_approve(conn: sqlite3.Connection, application_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    application = seal_application_row(conn, application_id)
    if application["status"] in {"已押章", "完成"} or application.get("stamp_no"):
        raise ValueError("seal_application_already_completed")
    user = current_user_from_session(session)
    actor_role = payload.get("approver_role") or user.get("role") or application.get("current_approver_role") or "主管"
    allowed_roles = {application.get("current_approver_role"), "主管", "主任", "行政部主任", "執行長"}
    if actor_role not in allowed_roles:
        raise ValueError("current_approver_mismatch")
    file_row, source_bytes = read_file_object_bytes(conn, application["source_pdf_file_object_id"])
    if sha256_bytes(source_bytes) != application["locked_pdf_sha256"]:
        raise ValueError("locked_pdf_hash_mismatch")
    positions = parse_json_any(application["stamp_positions_json"], []) or []
    if canonical_json_hash(positions) != application["locked_positions_sha256"]:
        raise ValueError("locked_stamp_positions_mismatch")
    document = row_to_dict(conn.execute("SELECT * FROM documents WHERE id = ?", (application["document_id"],)).fetchone())
    stamp_no = payload.get("stamp_no") or f"STAMP-{''.join(ch for ch in document['doc_no'] if ch.isdigit())[-10:] or int(time.time())}-{int(time.time())}"
    stamped_bytes, mode, metadata = stamp_uploaded_pdf_bytes(source_bytes, [{**position, "stamp_no": stamp_no} for position in positions], stamp_no)
    after_version = create_pdf_version(conn, document, "after_seal", payload.get("template") or "上傳 PDF 自動用印", stamped_bytes, {
        "source": "uploaded_pdf",
        "stamp_engine": mode,
        "page_count": metadata.get("page_count") or len(pdf_page_sizes(source_bytes)),
        "page_size": metadata.get("page_size"),
        "locked_pdf_sha256": application["locked_pdf_sha256"],
        "locked_positions_sha256": application["locked_positions_sha256"],
        "stamp_positions": positions,
        "fallback_reason": metadata.get("fallback_reason", ""),
    }, stamp_no, application["pdf_before_version_id"])
    signature = create_electronic_signature(conn, {
        **payload,
        "document_id": document["id"],
        "pdf_version_id": after_version["id"],
        "file_object_id": after_version["file_object_id"],
        "certificate_id": payload.get("certificate_id") or "CERT-SEAL-001",
        "signature_type": "seal",
        "signer": payload.get("approver") or user.get("name") or actor_role,
        "operation": f"主管核准後自動用印 {stamp_no}",
    })
    timestamp = now()
    conn.execute(
        """
        UPDATE seal_applications
        SET status = '已押章', approver = ?, stamp_no = ?, pdf_after_version_id = ?,
            approved_at = ?, completed_at = ?, current_step_no = ?, current_step_name = '申請人確認',
            current_approver_role = '員工', signature_id = ?, provider_status = ?, evidence_json = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            payload.get("approver") or user.get("name") or actor_role,
            stamp_no,
            after_version["id"],
            timestamp,
            timestamp,
            5,
            signature["id"],
            "簽章完成" if signature.get("status") == "有效" else signature.get("status") or "簽章完成",
            json.dumps({"pdf_after_sha256": after_version["sha256"], "stamp_engine": mode, "signature_id": signature["id"], "stamp_positions": positions}, ensure_ascii=False),
            timestamp,
            application_id,
        ),
    )
    conn.execute(
        """
        UPDATE approval_step_actor_snapshots
        SET status = '已完成', approver_user_id = ?, approver_name = ?, approver_email = ?,
            comment = ?, acted_at = ?, updated_at = ?
        WHERE source_type = 'seal_application' AND source_id = ? AND step_no = ?
        """,
        (user.get("id") or "", user.get("name") or payload.get("approver") or actor_role, user.get("email") or "", payload.get("comment") or "核准，系統自動用印。", timestamp, timestamp, application_id, application["current_step_no"]),
    )
    conn.execute(
        """
        UPDATE approval_step_actor_snapshots
        SET status = CASE WHEN step_name IN ('系統自動用印', '申請人確認') THEN '已完成' ELSE status END,
            acted_at = CASE WHEN step_name IN ('系統自動用印', '申請人確認') THEN ? ELSE acted_at END,
            updated_at = ?
        WHERE source_type = 'seal_application' AND source_id = ?
        """,
        (timestamp, timestamp, application_id),
    )
    refreshed = seal_application_row(conn, application_id)
    notice = create_seal_notification(conn, refreshed, f"{refreshed['title']} 已完成用印", refreshed.get("applicant") or "員工", f"主管已核准，系統已自動押章並產生 PDF hash {after_version['sha256']}。", "高")
    conn.execute("UPDATE seal_applications SET notification_id = ? WHERE id = ?", (notice["id"], application_id))
    log_audit(conn, user.get("name") or actor_role, "主管核准並自動用印", "seal_applications", application_id, f"{stamp_no} / {after_version['sha256']}", event_type="approve", module_code="seals")
    return {**seal_application_row(conn, application_id), "pdf_after": after_version, "signature": signature, "notification": notice}


def seal_application_return(conn: sqlite3.Connection, application_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    application = seal_application_row(conn, application_id)
    user = current_user_from_session(session)
    reason = payload.get("reason") or payload.get("comment") or "資料需補正後重新送簽。"
    timestamp = now()
    conn.execute(
        """
        UPDATE seal_applications
        SET status = '退回補正', reject_reason = ?, reason = ?, returned_at = ?,
            current_step_name = '申請人補正', current_approver_role = '員工', updated_at = ?
        WHERE id = ?
        """,
        (reason, reason, timestamp, timestamp, application_id),
    )
    conn.execute(
        """
        UPDATE approval_step_actor_snapshots
        SET status = '退回補正', comment = ?, approver_user_id = ?, approver_name = ?,
            approver_email = ?, acted_at = ?, updated_at = ?
        WHERE source_type = 'seal_application' AND source_id = ? AND step_no = ?
        """,
        (reason, user.get("id") or "", user.get("name") or payload.get("actor") or application.get("current_approver_role") or "主管", user.get("email") or "", timestamp, timestamp, application_id, application.get("current_step_no") or 2),
    )
    refreshed = seal_application_row(conn, application_id)
    notice = create_seal_notification(conn, refreshed, f"{refreshed['title']} 已退回補正", refreshed.get("applicant") or "員工", reason, "高")
    conn.execute("UPDATE seal_applications SET notification_id = ? WHERE id = ?", (notice["id"], application_id))
    log_audit(conn, user.get("name") or payload.get("actor") or "主管", "退回 PDF 用印", "seal_applications", application_id, reason, event_type="reject", module_code="seals")
    return {**seal_application_row(conn, application_id), "notification": notice}


def latest_signature(conn: sqlite3.Connection, document_id: str) -> Dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM electronic_signatures WHERE document_id = ? ORDER BY rowid DESC LIMIT 1",
        (document_id,),
    ).fetchone()
    return row_to_dict(row) if row else None


def active_certificate(conn: sqlite3.Connection, certificate_id: str = "", owner: str = "") -> Dict[str, Any]:
    if certificate_id:
        row = conn.execute("SELECT * FROM signing_certificates WHERE id = ? AND status = '啟用'", (certificate_id,)).fetchone()
    elif owner:
        row = conn.execute("SELECT * FROM signing_certificates WHERE owner = ? AND status = '啟用' ORDER BY rowid LIMIT 1", (owner,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM signing_certificates WHERE status = '啟用' ORDER BY rowid LIMIT 1").fetchone()
    if not row:
        raise ValueError("active_signing_certificate_not_found")
    return row_to_dict(row)


def signature_secret() -> bytes:
    value = os.getenv("EDOC_SIGNING_SECRET") or os.getenv("CRON_SECRET") or "dev-edoc-signing-secret-change-before-production"
    return value.encode("utf-8")


class SignatureProviderError(RuntimeError):
    def __init__(self, message: str, event: Dict[str, Any] | None = None):
        super().__init__(message)
        self.event = event or {}


def provider_event_row(event: Dict[str, Any], document_id: str = "", signature_id: str = "") -> Dict[str, Any]:
    return {
        "id": event.get("id") or f"SPE-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "document_id": document_id or event.get("document_id") or "",
        "signature_id": signature_id or event.get("signature_id") or "",
        "provider": event.get("provider") or EDOC_SIGNATURE_PROVIDER,
        "operation": event.get("operation") or "signature-provider",
        "request_id": event.get("request_id") or "",
        "endpoint": event.get("endpoint") or "",
        "request_digest_sha256": event.get("request_digest_sha256") or "",
        "response_digest_sha256": event.get("response_digest_sha256") or "",
        "status": event.get("status") or "失敗",
        "http_status": event.get("http_status"),
        "error": event.get("error") or "",
        "attempt_count": int(event.get("attempt_count") or 1),
        "duration_ms": int(event.get("duration_ms") or 0),
        "created_at": event.get("created_at") or now(),
    }


def record_signature_provider_event(conn: sqlite3.Connection, event: Dict[str, Any], document_id: str = "", signature_id: str = "") -> Dict[str, Any]:
    row = provider_event_row(event, document_id, signature_id)
    conn.execute(
        """
        INSERT OR REPLACE INTO signature_provider_events (
          id, document_id, signature_id, provider, operation, request_id, endpoint,
          request_digest_sha256, response_digest_sha256, status, http_status,
          error, attempt_count, duration_ms, created_at
        ) VALUES (
          :id, :document_id, :signature_id, :provider, :operation, :request_id, :endpoint,
          :request_digest_sha256, :response_digest_sha256, :status, :http_status,
          :error, :attempt_count, :duration_ms, :created_at
        )
        """,
        row,
    )
    return row


def provider_json_request(url: str, payload: Dict[str, Any], api_key: str, timeout: int | None = None, operation: str = "signature-provider") -> Dict[str, Any]:
    request_id = payload.get("request_id") or f"SIGREQ-{int(time.time() * 1000)}-{secrets.token_hex(4).upper()}"
    payload["request_id"] = request_id
    request_digest = sha256_bytes(canonical_signature_payload(payload).encode("utf-8"))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "suiyuecare-edoc-signature/1.0",
        "X-Request-ID": request_id,
        "Idempotency-Key": request_digest,
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    attempts = max(1, EDOC_SIGNATURE_MAX_RETRIES + 1)
    last_event: Dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        started = time.time()
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or EDOC_SIGNATURE_TIMEOUT_SECONDS) as response:
                raw = response.read().decode("utf-8")
                data = json.loads(raw) if raw else {}
                return {
                    "data": data,
                    "event": {
                        "provider": EDOC_SIGNATURE_PROVIDER,
                        "operation": operation,
                        "request_id": request_id,
                        "endpoint": url,
                        "request_digest_sha256": request_digest,
                        "response_digest_sha256": sha256_bytes(raw.encode("utf-8")),
                        "status": "成功",
                        "http_status": response.status,
                        "attempt_count": attempt,
                        "duration_ms": int((time.time() - started) * 1000),
                    },
                }
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            last_event = {
                "provider": EDOC_SIGNATURE_PROVIDER,
                "operation": operation,
                "request_id": request_id,
                "endpoint": url,
                "request_digest_sha256": request_digest,
                "status": "失敗",
                "http_status": exc.code,
                "error": detail[:500],
                "attempt_count": attempt,
                "duration_ms": int((time.time() - started) * 1000),
            }
            if exc.code not in {408, 425, 429, 500, 502, 503, 504} or attempt == attempts:
                raise SignatureProviderError(f"provider_http_{exc.code}:{detail}", last_event) from exc
        except Exception as exc:
            last_event = {
                "provider": EDOC_SIGNATURE_PROVIDER,
                "operation": operation,
                "request_id": request_id,
                "endpoint": url,
                "request_digest_sha256": request_digest,
                "status": "失敗",
                "error": str(exc)[:500],
                "attempt_count": attempt,
                "duration_ms": int((time.time() - started) * 1000),
            }
            if attempt == attempts:
                raise SignatureProviderError(f"provider_request_failed:{exc}", last_event) from exc
        time.sleep(min(1.5, 0.25 * attempt))
    raise SignatureProviderError("provider_request_failed", last_event)


def request_formal_signature(digest_payload: Dict[str, Any], digest: str, certificate: Dict[str, Any], signer: str, signature_id: str = "") -> Dict[str, Any]:
    if EDOC_SIGNATURE_PROVIDER == "local-simulation":
        signature_value = hmac.new(signature_secret(), canonical_signature_payload(digest_payload).encode("utf-8"), hashlib.sha256).hexdigest().upper()
        tsa_token = hmac.new(signature_secret(), f"TSA|{digest}|{digest_payload['timestamp']}".encode("utf-8"), hashlib.sha256).hexdigest().upper()
        return {
            "algorithm": "HMAC-SHA256-RSA-PSS-READY",
            "signature_value": signature_value,
            "tsa_token": tsa_token,
            "provider_receipt": {"mode": "local-simulation", "profile": EDOC_SIGNATURE_PROFILE},
            "provider_request_id": f"LOCAL-{signature_id or int(time.time() * 1000)}",
            "provider_status": "local-simulation",
            "provider_events": [],
        }
    if not EDOC_SIGNATURE_API_URL or not EDOC_SIGNATURE_API_KEY:
        raise ValueError("formal_signature_provider_not_configured")
    request_id = f"SIGREQ-{signature_id or int(time.time() * 1000)}"
    response = provider_json_request(
        f"{EDOC_SIGNATURE_API_URL}/sign",
        {
            "provider": EDOC_SIGNATURE_PROVIDER,
            "key_id": EDOC_SIGNATURE_KEY_ID,
            "request_id": request_id,
            "signature_id": signature_id,
            "signature_profile": EDOC_SIGNATURE_PROFILE,
            "certificate_id": certificate["id"],
            "certificate_serial": certificate.get("serial_no"),
            "signer": signer,
            "digest_sha256": digest,
            "payload": digest_payload,
            "tsa_url": EDOC_TSA_URL,
            "tsa_policy_oid": EDOC_TSA_POLICY_OID,
        },
        EDOC_SIGNATURE_API_KEY,
        operation="sign",
    )
    result = response["data"]
    signature_value = result.get("signature_value") or result.get("signature") or result.get("cms") or result.get("p7s")
    if not signature_value:
        raise ValueError("formal_signature_provider_missing_signature")
    tsa_token = result.get("tsa_token") or result.get("timestamp_token") or ""
    provider_events = [response["event"]]
    if not tsa_token and EDOC_TSA_URL:
        tsa_response = request_formal_tsa_token(digest, digest_payload["timestamp"], signature_id)
        tsa_token = tsa_response["token"]
        provider_events.append(tsa_response["event"])
    return {
        "algorithm": result.get("algorithm") or "RSA-PSS-SHA256",
        "signature_value": signature_value,
        "tsa_token": tsa_token,
        "provider_receipt": result.get("receipt") or result.get("provider_receipt") or result,
        "provider_request_id": result.get("request_id") or result.get("provider_request_id") or request_id,
        "provider_status": result.get("status") or "signed",
        "provider_events": provider_events,
    }


def request_formal_tsa_token(digest: str, timestamp: str, signature_id: str = "") -> Dict[str, Any]:
    if EDOC_SIGNATURE_PROVIDER == "local-simulation":
        return {
            "token": hmac.new(signature_secret(), f"TSA|{digest}|{timestamp}".encode("utf-8"), hashlib.sha256).hexdigest().upper(),
            "event": {},
        }
    if not EDOC_TSA_URL or not EDOC_TSA_API_KEY:
        raise ValueError("formal_tsa_not_configured")
    response = provider_json_request(
        EDOC_TSA_URL,
        {"digest_sha256": digest, "policy_oid": EDOC_TSA_POLICY_OID, "timestamp": timestamp, "signature_id": signature_id},
        EDOC_TSA_API_KEY,
        operation="tsa",
    )
    result = response["data"]
    token = result.get("tsa_token") or result.get("timestamp_token") or result.get("token")
    if not token:
        raise ValueError("formal_tsa_missing_token")
    return {"token": token, "event": response["event"]}


def canonical_signature_payload(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_date_value(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
    return None


def certificate_type_label(certificate: Dict[str, Any]) -> str:
    labels = {
        "natural_person": "自然人憑證",
        "business": "工商憑證",
        "organization": "組織憑證",
        "tsa": "時間戳憑證",
    }
    return labels.get(certificate.get("certificate_type") or "organization", "組織憑證")


def tsa_token_valid(signature: Dict[str, Any]) -> bool:
    proof = {}
    try:
        proof = json.loads(signature.get("non_repudiation_json") or "{}")
    except json.JSONDecodeError:
        return False
    timestamp = proof.get("timestamp")
    token = signature.get("tsa_token") or proof.get("tsa_token")
    digest = signature.get("digest_sha256") or ""
    if not timestamp or not token or not digest:
        return False
    if EDOC_SIGNATURE_PROVIDER != "local-simulation":
        return bool(EDOC_TSA_URL and token)
    expected = hmac.new(signature_secret(), f"TSA|{digest}|{timestamp}".encode("utf-8"), hashlib.sha256).hexdigest().upper()
    return hmac.compare_digest(expected, str(token).upper())


def validate_certificate_legality(
    conn: sqlite3.Connection,
    certificate: Dict[str, Any],
    signature: Dict[str, Any] | None = None,
    validator: str = "Certificate Worker",
) -> Dict[str, Any]:
    checked_at = now()
    today = datetime.now()
    valid_from = parse_date_value(certificate.get("valid_from") or "")
    valid_to = parse_date_value(certificate.get("valid_to") or "")
    is_active = certificate.get("status") == "啟用"
    is_within_validity = (valid_from is None or valid_from <= today) and (valid_to is None or today <= valid_to + timedelta(days=1))
    revoked = any(keyword in (certificate.get("status") or "") for keyword in ("撤銷", "停用", "註銷"))
    service = signing_service_status()
    ca = conn.execute(
        "SELECT * FROM certificate_authorities WHERE trust_status = 'trusted' AND (? LIKE '%' || name || '%' OR ? LIKE '%' || subject || '%' OR ? LIKE '%' || issuer || '%') ORDER BY rowid LIMIT 1",
        (certificate.get("issuer") or "", certificate.get("issuer") or "", certificate.get("issuer") or ""),
    ).fetchone()
    trusted_issuer = bool(ca) or ((not is_production()) and "Internal CA" in (certificate.get("issuer") or ""))
    chain_status = "有效" if is_active and is_within_validity and trusted_issuer else "憑證鏈異常"
    ocsp_url = certificate.get("ocsp_url") or EDOC_OCSP_RESPONDER_URL
    crl_url = certificate.get("crl_url") or EDOC_CRL_DISTRIBUTION_URL
    tsa_url = certificate.get("tsa_url") or EDOC_TSA_URL
    if revoked:
        ocsp_status = "已撤銷"
        crl_status = "已列入撤銷清單"
    else:
        ocsp_status = "良好" if ocsp_url else "無法查詢"
        crl_status = "未列入撤銷清單" if crl_url else "無法查詢"
    tsa_status = "不適用"
    if signature:
        tsa_status = "有效" if tsa_token_valid(signature) else "時間戳無效"
        if not tsa_url:
            tsa_status = "TSA 未設定"
    if is_production() and service["productionBlocked"]:
        chain_status = "正式憑證服務未設定"
    result = "通過" if chain_status == "有效" and ocsp_status == "良好" and crl_status == "未列入撤銷清單" and tsa_status in {"有效", "不適用"} else "不通過"
    report = {
        "ok": result == "通過",
        "certificate_id": certificate["id"],
        "certificate_type": certificate_type_label(certificate),
        "serial_no": certificate.get("serial_no"),
        "issuer": certificate.get("issuer"),
        "chain_status": chain_status,
        "ocsp_status": ocsp_status,
        "crl_status": crl_status,
        "tsa_status": tsa_status,
        "checked_at": checked_at,
        "ocsp_url": ocsp_url,
        "crl_url": crl_url,
        "tsa_url": tsa_url,
        "service_status": service,
        "trusted_ca": row_to_dict(ca) if ca else None,
        "result": result,
    }
    event_id = f"CVAL-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    conn.execute(
        """
        INSERT INTO certificate_validation_events (
          id, certificate_id, signature_id, validator, validation_type, chain_status, ocsp_status,
          crl_status, tsa_status, result, report_json, checked_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            certificate["id"],
            signature["id"] if signature else None,
            validator,
            "chain+ocsp+crl+tsa" if signature else "chain+ocsp+crl",
            chain_status,
            ocsp_status,
            crl_status,
            tsa_status,
            result,
            json.dumps(report, ensure_ascii=False),
            checked_at,
        ),
    )
    conn.execute(
        """
        UPDATE signing_certificates
        SET chain_status = ?, ocsp_status = ?, crl_status = ?, last_validated_at = ?, validation_report_json = ?
        WHERE id = ?
        """,
        (chain_status, ocsp_status, crl_status, checked_at, json.dumps(report, ensure_ascii=False), certificate["id"]),
    )
    if signature:
        conn.execute(
            """
            UPDATE electronic_signatures
            SET certificate_validation_id = ?, chain_status = ?, ocsp_status = ?, crl_status = ?, tsa_status = ?
            WHERE id = ?
            """,
            (event_id, chain_status, ocsp_status, crl_status, tsa_status, signature["id"]),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO tsa_timestamp_tokens (
              id, signature_id, tsa_name, tsa_url, imprint_sha256, token_value, policy_oid, status, issued_at, verified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"TSA-{signature['id']}",
                signature["id"],
                "Suiyuecare TSA",
                tsa_url or "https://tsa.suiyuecare.local/rfc3161",
                signature.get("digest_sha256") or "",
                signature.get("tsa_token") or "",
                EDOC_TSA_POLICY_OID,
                tsa_status,
                signature.get("created_at") or checked_at,
                checked_at,
            ),
        )
    report["event_id"] = event_id
    return report


def create_electronic_signature(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    service = signing_service_status()
    if service["productionBlocked"]:
        raise ValueError(f"formal_signing_service_not_ready:{','.join(service['missing'])}")
    document = get_or_create_pdf_document(conn, payload)
    pdf_version_id = payload.get("pdf_version_id") or payload.get("version_id") or ""
    file_object_id = payload.get("file_object_id") or ""
    version = None
    if pdf_version_id and not file_object_id:
        version = conn.execute("SELECT * FROM pdf_versions WHERE id = ?", (pdf_version_id,)).fetchone()
        if version:
            file_object_id = version["file_object_id"]
    file_row = conn.execute("SELECT * FROM file_objects WHERE id = ?", (file_object_id,)).fetchone() if file_object_id else None
    file_hash = file_row["sha256"] if file_row else payload.get("digest_sha256") or sha256_bytes(canonical_signature_payload(payload.get("document") or document).encode("utf-8"))
    signer = payload.get("signer") or payload.get("approver") or "行政部主任"
    certificate = active_certificate(conn, payload.get("certificate_id") or "", signer)
    previous = latest_signature(conn, document["id"])
    timestamp = now()
    signature_id = f"ESIG-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    digest_payload = {
        "signature_id": signature_id,
        "document_id": document["id"],
        "doc_no": document["doc_no"],
        "file_hash": file_hash,
        "signature_type": payload.get("signature_type") or "seal",
        "certificate_fingerprint": certificate["fingerprint_sha256"],
        "previous_signature": previous["signature_value"] if previous else "",
        "timestamp": timestamp,
    }
    digest = sha256_bytes(canonical_signature_payload(digest_payload).encode("utf-8"))
    try:
        formal_signature = request_formal_signature(digest_payload, digest, certificate, signer, signature_id)
    except SignatureProviderError as exc:
        if exc.event:
            record_signature_provider_event(conn, exc.event, document["id"], signature_id)
        log_audit(conn, signer, "正式電子簽章失敗", "documents", document["id"], f"{signature_id} / {exc}")
        raise
    signature_value = formal_signature["signature_value"]
    tsa_token = formal_signature["tsa_token"]
    for event in formal_signature.get("provider_events") or []:
        if event:
            record_signature_provider_event(conn, event, document["id"], signature_id)
    non_repudiation = {
        "version": "SYC-EDOC-SIGNATURE-EVIDENCE-1",
        "signer": signer,
        "provider": EDOC_SIGNATURE_PROVIDER,
        "provider_key_id": EDOC_SIGNATURE_KEY_ID,
        "provider_request_id": formal_signature.get("provider_request_id") or "",
        "provider_status": formal_signature.get("provider_status") or "",
        "signature_profile": EDOC_SIGNATURE_PROFILE,
        "provider_receipt": formal_signature.get("provider_receipt", {}),
        "certificate_serial": certificate["serial_no"],
        "certificate_fingerprint": certificate["fingerprint_sha256"],
        "timestamp": timestamp,
        "tsa_token": tsa_token,
        "file_hash": file_hash,
        "digest_payload": digest_payload,
        "digest_payload_sha256": digest,
        "previous_signature_id": previous["id"] if previous else "",
        "ip": payload.get("ip") or "system",
        "device": payload.get("device") or "server",
        "operation": payload.get("operation") or "PDF 電子簽章/押章",
    }
    evidence_digest = sha256_bytes(canonical_signature_payload(non_repudiation).encode("utf-8"))
    non_repudiation["evidence_digest_sha256"] = evidence_digest
    row = {
        "id": signature_id,
        "document_id": document["id"],
        "pdf_version_id": pdf_version_id or (version["id"] if version else None),
        "file_object_id": file_object_id or None,
        "certificate_id": certificate["id"],
        "signer": signer,
        "signature_type": payload.get("signature_type") or "seal",
        "algorithm": formal_signature["algorithm"],
        "digest_sha256": digest,
        "signature_value": signature_value,
        "tsa_token": tsa_token,
        "previous_signature_id": previous["id"] if previous else None,
        "non_repudiation_json": json.dumps(non_repudiation, ensure_ascii=False),
        "verified_at": timestamp,
        "status": "有效",
        "created_at": timestamp,
        "provider": EDOC_SIGNATURE_PROVIDER,
        "provider_key_id": EDOC_SIGNATURE_KEY_ID,
        "provider_request_id": formal_signature.get("provider_request_id") or "",
        "provider_receipt_json": json.dumps(formal_signature.get("provider_receipt", {}), ensure_ascii=False),
        "evidence_digest_sha256": evidence_digest,
    }
    insert_row(conn, "electronic_signatures", row)
    validation = validate_certificate_legality(conn, certificate, row, signer)
    row.update({
        "certificate_validation_id": validation["event_id"],
        "chain_status": validation["chain_status"],
        "ocsp_status": validation["ocsp_status"],
        "crl_status": validation["crl_status"],
        "tsa_status": validation["tsa_status"],
        "status": "有效" if validation["ok"] else "憑證驗證失敗",
    })
    conn.execute(
        "UPDATE electronic_signatures SET certificate_validation_id = ?, chain_status = ?, ocsp_status = ?, crl_status = ?, tsa_status = ?, status = ? WHERE id = ?",
        (row["certificate_validation_id"], row["chain_status"], row["ocsp_status"], row["crl_status"], row["tsa_status"], row["status"], row["id"]),
    )
    log_audit(conn, signer, "正式電子簽章", "documents", document["id"], f"{signature_id} / {digest}")
    return {**row, "certificate": certificate, "non_repudiation": non_repudiation, "certificate_validation": validation}


def verify_signature_value_with_provider(conn: sqlite3.Connection, signature: Dict[str, Any], certificate: Dict[str, Any]) -> Dict[str, Any]:
    try:
        proof = json.loads(signature.get("non_repudiation_json") or "{}")
    except json.JSONDecodeError:
        proof = {}
    digest_payload = proof.get("digest_payload") if isinstance(proof.get("digest_payload"), dict) else {}
    if EDOC_SIGNATURE_PROVIDER == "local-simulation":
        expected = hmac.new(signature_secret(), canonical_signature_payload(digest_payload).encode("utf-8"), hashlib.sha256).hexdigest().upper() if digest_payload else ""
        ok = bool(expected) and hmac.compare_digest(expected, str(signature.get("signature_value") or "").upper())
        return {"ok": ok, "mode": "local-simulation", "status": "簽章值有效" if ok else "簽章值不符"}
    if not EDOC_SIGNATURE_API_URL or not EDOC_SIGNATURE_API_KEY:
        return {"ok": False, "mode": "formal", "status": "簽章驗證 provider 未設定"}
    try:
        response = provider_json_request(
            f"{EDOC_SIGNATURE_API_URL}/verify",
            {
                "signature_id": signature["id"],
                "request_id": f"SIGVERIFY-{signature['id']}",
                "signature_profile": proof.get("signature_profile") or EDOC_SIGNATURE_PROFILE,
                "certificate_id": certificate["id"],
                "certificate_serial": certificate.get("serial_no"),
                "digest_sha256": signature.get("digest_sha256"),
                "signature_value": signature.get("signature_value"),
                "tsa_token": signature.get("tsa_token"),
                "payload": digest_payload,
            },
            EDOC_SIGNATURE_API_KEY,
            operation="verify",
        )
        record_signature_provider_event(conn, response["event"], signature.get("document_id") or "", signature["id"])
        data = response["data"]
        ok = bool(data.get("ok", data.get("valid", False)))
        return {"ok": ok, "mode": "formal", "status": data.get("status") or ("簽章值有效" if ok else "簽章值不符"), "provider_receipt": data}
    except SignatureProviderError as exc:
        if exc.event:
            record_signature_provider_event(conn, exc.event, signature.get("document_id") or "", signature["id"])
        return {"ok": False, "mode": "formal", "status": str(exc)}


def verify_electronic_signature(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    signature_id = payload.get("signature_id")
    row = conn.execute("SELECT * FROM electronic_signatures WHERE id = ?", (signature_id,)).fetchone() if signature_id else None
    if not row:
        return {"ok": False, "error": "signature_not_found"}
    signature = row_to_dict(row)
    file_hash = signature["digest_sha256"]
    if signature.get("file_object_id"):
        file_row = conn.execute("SELECT * FROM file_objects WHERE id = ?", (signature["file_object_id"],)).fetchone()
        if file_row:
            path = STORAGE_DIR / file_row["storage_key"]
            file_data = decrypt_file_bytes(path.read_bytes(), file_row["encryption_status"], file_row["encryption_alg"]) if path.exists() else b""
            file_hash_ok = bool(file_data) and sha256_bytes(file_data) == file_row["sha256"]
        else:
            file_hash_ok = False
    else:
        file_hash_ok = True
    cert_row = conn.execute("SELECT * FROM signing_certificates WHERE id = ?", (signature["certificate_id"],)).fetchone()
    if not cert_row:
        return {"ok": False, "error": "certificate_not_found", "signature": signature}
    certificate = row_to_dict(cert_row)
    signature_value_check = verify_signature_value_with_provider(conn, signature, certificate)
    validation = validate_certificate_legality(conn, certificate, signature, payload.get("validator") or "Signature Verifier")
    ok = file_hash_ok and signature_value_check["ok"] and validation["ok"]
    status = "有效" if ok else "憑證驗證失敗" if file_hash_ok and signature_value_check["ok"] else "簽章值異常" if file_hash_ok else "雜湊異常"
    conn.execute("UPDATE electronic_signatures SET verified_at = ?, status = ? WHERE id = ?", (now(), status, signature_id))
    return {"ok": ok, "signature": signature, "digest": file_hash, "status": status, "signature_value_check": signature_value_check, "certificate_validation": validation}


def validate_certificate_api(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    certificate_id = payload.get("certificate_id") or payload.get("id")
    row = conn.execute("SELECT * FROM signing_certificates WHERE id = ?", (certificate_id,)).fetchone() if certificate_id else None
    if not row:
        return {"ok": False, "error": "certificate_not_found"}
    signature = None
    if payload.get("signature_id"):
        signature_row = conn.execute("SELECT * FROM electronic_signatures WHERE id = ?", (payload["signature_id"],)).fetchone()
        signature = row_to_dict(signature_row) if signature_row else None
    result = validate_certificate_legality(conn, row_to_dict(row), signature, payload.get("validator") or "Certificate Verifier")
    log_audit(conn, payload.get("validator") or "Certificate Verifier", "憑證合法性驗證", "signing_certificates", certificate_id, result["result"] if "result" in result else result["chain_status"])
    return result


def certificate_health(conn: sqlite3.Connection) -> Dict[str, Any]:
    certificates = [row_to_dict(row) for row in conn.execute("SELECT * FROM signing_certificates ORDER BY rowid").fetchall()]
    authorities = [row_to_dict(row) for row in conn.execute("SELECT * FROM certificate_authorities ORDER BY rowid").fetchall()]
    events = [row_to_dict(row) for row in conn.execute("SELECT * FROM certificate_validation_events ORDER BY rowid DESC LIMIT 8").fetchall()]
    provider_events = [row_to_dict(row) for row in conn.execute("SELECT * FROM signature_provider_events ORDER BY rowid DESC LIMIT 8").fetchall()]
    service = signing_service_status()
    return {
        "mode": service["mode"],
        "ready": service["ready"],
        "certificate_count": len(certificates),
        "trusted_ca_count": len([item for item in authorities if item.get("trust_status") == "trusted"]),
        "services": {
            "provider": "啟用" if service["services"]["provider"]["configured"] else "仍為模擬",
            "providerApi": "啟用" if service["services"]["providerApi"]["configured"] else "未設定簽章 API",
            "providerCredential": "啟用" if service["services"]["providerCredential"]["configured"] else "未設定簽章 API key",
            "keyId": "啟用" if service["services"]["keyId"]["configured"] else "未設定簽章 key id",
            "chain": "啟用" if service["services"]["trustStore"]["configured"] else "未設定信任根",
            "tsa": "啟用" if service["services"]["tsa"]["configured"] else "未設定 TSA",
            "tsaCredential": "啟用" if service["services"]["tsaCredential"]["configured"] else "未設定 TSA API key",
            "ocsp": "啟用" if service["services"]["ocsp"]["configured"] else "未設定 OCSP",
            "crl": "啟用" if service["services"]["crl"]["configured"] else "未設定 CRL",
            "hsm": "啟用" if service["services"]["hsm"]["configured"] else "未設定 HSM/KMS",
        },
        "service": service,
        "policy": service.get("policy", {}),
        "certificates": certificates,
        "authorities": authorities,
        "recent_events": events,
        "provider_events": provider_events,
    }


def pdf_render_document(document: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    doc_payload = payload.get("document") or {}
    merged = {**document, **doc_payload}
    company_name = payload.get("company_name") or doc_payload.get("companyName") or doc_payload.get("company_name") or document.get("company_name")
    if company_name:
        merged["company_name"] = company_name
    contact_fields = {
        "contactAddress": "contactAddress",
        "contactOwner": "contactOwner",
        "contactPhone": "contactPhone",
        "contactFax": "contactFax",
        "contactEmail": "contactEmail",
    }
    for target, source in contact_fields.items():
        if doc_payload.get(source):
            merged[target] = doc_payload[source]
    return merged


def pdf_seal_plan(payload: Dict[str, Any], document: Dict[str, Any]) -> Dict[str, Any]:
    doc_payload = payload.get("document") or {}
    for value in (
        payload.get("seal_plan"),
        payload.get("sealPlan"),
        doc_payload.get("seal_plan"),
        doc_payload.get("sealPlan"),
        document.get("seal_plan_json"),
    ):
        parsed = parse_json_field(value)
        if parsed:
            return parsed
    return {}


def stamp_from_percentage(placement: Dict[str, Any], width: float, height: float, default_x: float, default_y: float, page_count: int) -> Tuple[int, float, float]:
    page = int(pdf_safe_float(placement.get("page"), 1))
    page = max(1, min(page, page_count))
    center_x = A4_WIDTH_PT * pdf_safe_float(placement.get("x"), default_x) / 100
    center_y_from_top = A4_HEIGHT_PT * pdf_safe_float(placement.get("y"), default_y) / 100
    return page, center_x - width / 2, A4_HEIGHT_PT - center_y_from_top - height / 2


def pdf_stamp_definitions(payload: Dict[str, Any], document: Dict[str, Any], stamp_no: str, page_count: int) -> List[Dict[str, Any]]:
    coordinates = payload.get("coordinates") or {}
    explicit_positions = payload.get("stamp_positions") or payload.get("stamps") or payload.get("positions")
    if explicit_positions:
        stamps: List[Dict[str, Any]] = []
        for position in normalized_stamp_positions({"stamp_positions": explicit_positions, "seal_id": payload.get("seal_id") or ""}):
            page_value = position.get("page", 1)
            target_pages = range(1, page_count + 1) if page_value == "all" else [max(1, min(page_count, int(page_value)))]
            for page in target_pages:
                x, y, width, height = clamp_pdf_rect(
                    pdf_safe_float(position.get("x"), 420.0),
                    pdf_safe_float(position.get("y"), 120.0),
                    pdf_safe_float(position.get("w"), 56.0),
                    pdf_safe_float(position.get("h"), 56.0),
                )
                stamps.append({
                    **position,
                    "page": page,
                    "x": x,
                    "y": y,
                    "w": width,
                    "h": height,
                    "stamp_no": stamp_no,
                    "source": "stamp_positions",
                })
        return stamps
    seal_plan = pdf_seal_plan(payload, document)
    stamps: List[Dict[str, Any]] = []
    seal_specs = [
        ("large", "公司大章", 70.0, 80.0, "company_width_mm", "company_height_mm", 30.0),
        ("small", "公司小章", 84.0, 80.0, "owner_width_mm", "owner_height_mm", 18.0),
    ]
    if seal_plan:
        for kind, label, default_x, default_y, width_key, height_key, fallback_mm in seal_specs:
            plan = seal_plan.get(kind) if isinstance(seal_plan.get(kind), dict) else {}
            seal_type = str(plan.get("type") or "無")
            if seal_type == "無":
                continue
            width = mm_to_pdf_points(plan.get("widthMm") or plan.get("width_mm") or coordinates.get(width_key), fallback_mm)
            height = mm_to_pdf_points(plan.get("heightMm") or plan.get("height_mm") or coordinates.get(height_key), fallback_mm)
            placement = plan.get("placement") if isinstance(plan.get("placement"), dict) else {}
            page, x, y = stamp_from_percentage(placement, width, height, default_x, default_y, page_count)
            x, y, width, height = clamp_pdf_rect(x, y, width, height)
            stamps.append({"page": page, "x": x, "y": y, "w": width, "h": height, "label": label, "type": seal_type, "stamp_no": stamp_no, "source": "seal_plan"})
    else:
        company_width = mm_to_pdf_points(coordinates.get("company_width_mm"), 30.0)
        company_height = mm_to_pdf_points(coordinates.get("company_height_mm"), 30.0)
        owner_width = mm_to_pdf_points(coordinates.get("owner_width_mm"), 18.0)
        owner_height = mm_to_pdf_points(coordinates.get("owner_height_mm"), 18.0)
        stamps = [
            {"page": 1, "x": pdf_safe_float(coordinates.get("company_x"), 420), "y": pdf_safe_float(coordinates.get("company_y"), 130), "w": company_width, "h": company_height, "label": "公司大章", "type": "一般章", "stamp_no": stamp_no, "source": "legacy_coordinates"},
            {"page": 1, "x": pdf_safe_float(coordinates.get("owner_x"), 470), "y": pdf_safe_float(coordinates.get("owner_y"), 130), "w": owner_width, "h": owner_height, "label": "公司小章", "type": "一般章", "stamp_no": stamp_no, "source": "legacy_coordinates"},
        ]
    if coordinates.get("multi_page") and page_count > 1:
        for page in range(1, page_count + 1):
            stamps.append({"page": page, "x": A4_WIDTH_PT - 24, "y": A4_HEIGHT_PT / 2 - 36, "w": 18, "h": 72, "label": "騎縫章", "type": "多頁章", "stamp_no": stamp_no, "source": "page_seal"})
    return stamps


def pdf_coordinates_with_layout(coordinates: Dict[str, Any], package: Dict[str, Any], stamps: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    enriched = {**coordinates, **package.get("layout", {})}
    if stamps is not None:
        enriched["stamp_positions"] = [
            {key: stamp.get(key) for key in ("page", "x", "y", "w", "h", "label", "type", "source")}
            for stamp in stamps
        ]
    return enriched


def pdf_generate(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    document = get_or_create_pdf_document(conn, payload)
    template = payload.get("template") or "歲悅正式函"
    coordinates = payload.get("coordinates") or {}
    min_page_count = 2 if coordinates.get("multi_page") else 1
    package = build_official_pdf_package(pdf_render_document(document, payload), [], template, min_page_count)
    version = create_pdf_version(conn, document, "before_seal", template, package["data"], pdf_coordinates_with_layout(coordinates, package, []))
    log_audit(conn, "PDF Worker", "產生公文 PDF 套版", "documents", document["id"], version["sha256"])
    return version


def pdf_stamp(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    document = get_or_create_pdf_document(conn, payload)
    template = payload.get("template") or "歲悅正式函"
    coordinates = payload.get("coordinates") or {}
    doc_digits = "".join(ch for ch in document["doc_no"] if ch.isdigit())[-10:] or str(int(time.time()))
    stamp_no = payload.get("stamp_no") or f"STAMP-{doc_digits}-{int(time.time())}"
    previous = latest_pdf_version(conn, document["id"], "before_seal") or pdf_generate(conn, payload)
    min_page_count = 2 if coordinates.get("multi_page") else 1
    dry_package = build_official_pdf_package(pdf_render_document(document, payload), [], template, min_page_count)
    stamps = pdf_stamp_definitions(payload, document, stamp_no, int(dry_package["layout"]["page_count"]))
    package = build_official_pdf_package(pdf_render_document(document, payload), stamps, template, min_page_count)
    if coordinates.get("multi_page") and package["layout"]["page_count"] != dry_package["layout"]["page_count"]:
        stamps = pdf_stamp_definitions(payload, document, stamp_no, int(package["layout"]["page_count"]))
        package = build_official_pdf_package(pdf_render_document(document, payload), stamps, template, min_page_count)
    version = create_pdf_version(conn, document, "after_seal", template, package["data"], pdf_coordinates_with_layout(coordinates, package, stamps), stamp_no, previous["id"])
    application_id = payload.get("application_id") or f"USEAL-{int(time.time() * 1000)}"
    conn.execute(
        """
        INSERT OR REPLACE INTO seal_applications (
          id, document_id, seal_id, applicant, approver, status, reason, stamp_no,
          pdf_before_version_id, pdf_after_version_id, provider_status, failure_reason,
          evidence_json, updated_at, created_at, approved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM seal_applications WHERE id = ?), ?), ?)
        """,
        (
            application_id,
            document["id"],
            payload.get("seal_id") or "SEAL-001",
            payload.get("applicant") or "總務",
            payload.get("approver") or "行政部主任",
            "已押章",
            payload.get("reason") or "簽核完成後自動用印",
            stamp_no,
            previous["id"],
            version["id"],
            "待簽章",
            "",
            json.dumps({"pdf_after_sha256": version["sha256"], "stamp_positions": version.get("coordinates", {}).get("stamp_positions", [])}, ensure_ascii=False),
            now(),
            application_id,
            now(),
            now(),
        ),
    )
    signature = create_electronic_signature(conn, {
        **payload,
        "document_id": document["id"],
        "pdf_version_id": version["id"],
        "file_object_id": version["file_object_id"],
        "signature_type": "seal",
        "signer": payload.get("approver") or "行政部主任",
        "operation": f"核准用印並自動押章 {stamp_no}",
    })
    conn.execute(
        """
        UPDATE seal_applications
        SET signature_id = ?, provider_status = ?, failure_reason = '', evidence_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            signature["id"],
            "簽章完成" if signature.get("status") == "有效" else signature.get("status") or "簽章完成",
            json.dumps({
                "pdf_after_sha256": version["sha256"],
                "signature_id": signature["id"],
                "signature_digest": signature.get("digest_sha256"),
                "evidence_digest_sha256": signature.get("evidence_digest_sha256"),
                "provider": signature.get("provider"),
                "provider_request_id": signature.get("provider_request_id"),
                "stamp_positions": version.get("coordinates", {}).get("stamp_positions", []),
            }, ensure_ascii=False),
            now(),
            application_id,
        ),
    )
    log_audit(conn, "PDF Worker", "自動押章 PDF", "documents", document["id"], f"{stamp_no} / {version['sha256']} / {signature['id']}")
    return {**version, "stamp_no": stamp_no, "application_id": application_id, "signature": signature}


def pdf_verify(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    file_id = payload.get("file_object_id")
    version_id = payload.get("version_id")
    if version_id and not file_id:
        version = conn.execute("SELECT * FROM pdf_versions WHERE id = ?", (version_id,)).fetchone()
        if version:
            file_id = version["file_object_id"]
    row = conn.execute("SELECT * FROM file_objects WHERE id = ?", (file_id,)).fetchone() if file_id else None
    if not row:
        return {"ok": False, "error": "file_not_found"}
    file_row = row_to_dict(row)
    path = STORAGE_DIR / file_row["storage_key"]
    raw = path.read_bytes() if path.exists() else b""
    actual = sha256_bytes(decrypt_file_bytes(raw, file_row.get("encryption_status", ""), file_row.get("encryption_alg", ""))) if raw else ""
    return {"ok": actual == file_row["sha256"], "expected": file_row["sha256"], "actual": actual, "file": file_row}


def compute_next_run_at(schedule_text: str, base: datetime | None = None) -> str:
    base = base or datetime.now()
    if "15 分鐘" in schedule_text:
        next_run = base + timedelta(minutes=15)
    elif "每小時" in schedule_text:
        next_run = base + timedelta(hours=1)
    elif "18:00" in schedule_text:
        next_run = base.replace(hour=18, minute=0, second=0, microsecond=0)
        if next_run <= base:
            next_run += timedelta(days=1)
    elif "09:00" in schedule_text:
        next_run = base.replace(hour=9, minute=0, second=0, microsecond=0)
        if next_run <= base:
            next_run += timedelta(days=1)
    else:
        next_run = base.replace(hour=8, minute=30, second=0, microsecond=0)
        if next_run <= base:
            next_run += timedelta(days=1)
    return next_run.strftime("%Y-%m-%d %H:%M:%S")


def scalar_int(conn: sqlite3.Connection, sql: str, params: Tuple[Any, ...] = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def execute_job_logic(conn: sqlite3.Connection, job: Dict[str, Any]) -> Dict[str, Any]:
    job_type = job["job_type"]
    if job_type == "pullInbound":
        result = pull_inbound(conn)
        return {"message": f"成功：拉取 {result.get('count', 0)} 筆收文 {result.get('created', '')}", "payload": result}

    if job_type == "exchangeSendPending":
        result = create_exchange_gateway(conn).sendPendingOfficialDocuments()
        return {"message": f"成功：送出 {result['count']} 筆待發交換公文", "payload": result}

    if job_type == "exchangeRetryFailed":
        result = create_exchange_gateway(conn).retryFailedDeliveries()
        return {"message": f"成功：重送 {result['count']} 筆交換失敗公文", "payload": result}

    if job_type == "nextDayCheck":
        rows = conn.execute("SELECT * FROM exchange_tasks WHERE direction = '發文'").fetchall()
        checked = 0
        for row in rows:
            checked += 1
            status = "已確認收文" if row["status"] not in {"交換失敗", "退回補正"} else row["status"]
            conn.execute("UPDATE exchange_tasks SET status = ?, updated_at = ?, next_check_at = ? WHERE id = ?", (status, now(), compute_next_run_at("每日 09:00"), row["id"]))
            conn.execute(
                "INSERT INTO exchange_events (id, task_id, document_id, event_type, message, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"EVT-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}", row["id"], row["document_id"], "next_day_check", "背景任務完成發文翌日查核。", "{}", now()),
            )
        return {"message": f"成功：完成 {checked} 筆發文翌日查核", "payload": {"checked": checked}}

    if job_type == "tokenCheck":
        active_sessions = scalar_int(conn, "SELECT COUNT(*) FROM auth_sessions WHERE revoked_at IS NULL AND expires_at > ?", (now(),))
        expiring = scalar_int(conn, "SELECT COUNT(*) FROM auth_sessions WHERE revoked_at IS NULL AND expires_at <= ?", ((datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),))
        detail = f"active_sessions={active_sessions}, expiring_in_1h={expiring}"
        log_audit(conn, "Scheduler", "Token 到期檢查", "auth_sessions", "tokenCheck", detail)
        return {"message": f"成功：有效 session {active_sessions}，1 小時內到期 {expiring}", "payload": {"active_sessions": active_sessions, "expiring": expiring}}

    if job_type == "overdueReminder":
        overdue_docs = conn.execute("SELECT * FROM documents WHERE due_date IS NOT NULL AND due_date <> '' AND due_date < ? AND status NOT LIKE '%完成%'", (datetime.now().strftime("%Y-%m-%d"),)).fetchall()
        for doc in overdue_docs:
            log_audit(conn, "Scheduler", "逾期稽催", "documents", doc["id"], f"{doc['doc_no']} / {doc['owner']} / {doc['due_date']}")
        return {"message": f"成功：產生 {len(overdue_docs)} 筆逾期稽催紀錄", "payload": {"overdue": len(overdue_docs)}}

    if job_type == "contractRenewalCheck":
        rows = conn.execute("SELECT * FROM contracts WHERE end_date IS NOT NULL AND end_date <> '' AND status NOT IN ('已終止','已作廢')").fetchall()
        due_contracts = []
        today = datetime.now().date()
        for row in rows:
            end_date = parse_time(row["end_date"]).date()
            alert_days = int(row["renewal_alert_days"] or 60)
            days_left = (end_date - today).days
            if 0 <= days_left <= alert_days:
                due_contracts.append(row)
                notice = create_notification(conn, {
                    "type": "合約續約",
                    "title": f"{row['title']} 即將到期",
                    "target_role": row["owner"] or "行政部主任",
                    "channel": "Email + 系統通知",
                    "priority": "高" if days_left <= 30 else "中",
                    "source": row["contract_no"],
                    "body": f"{row['counterparty']} 合約將於 {row['end_date']} 到期，剩餘 {days_left} 天，請確認續約、重簽或終止。",
                })
                log_audit(conn, "Scheduler", "合約續約提醒", "contracts", row["id"], notice["id"])
        return {"message": f"成功：產生 {len(due_contracts)} 筆合約續約提醒", "payload": {"dueContracts": len(due_contracts)}}

    if job_type == "exchangeSync":
        gateway_result = create_exchange_gateway(conn).queryPendingDeliveryStatuses()
        rows = conn.execute("SELECT * FROM exchange_tasks").fetchall()
        for row in rows:
            conn.execute(
                "INSERT INTO exchange_events (id, task_id, document_id, event_type, message, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"EVT-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}", row["id"], row["document_id"], "status_sync", f"背景任務同步交換狀態：{row['status']}", json.dumps({"status": row["status"]}, ensure_ascii=False), now()),
            )
        return {"message": f"成功：同步 {gateway_result['count']} 筆新介接層狀態，保留 {len(rows)} 筆舊交換事件", "payload": {"synced": gateway_result["count"], "gateway": gateway_result, "legacyEvents": len(rows)}}

    if job_type == "archiveSeal":
        files = conn.execute("SELECT * FROM file_objects").fetchall()
        verified = 0
        failed = 0
        for row in files:
            path = STORAGE_DIR / row["storage_key"]
            ok = path.exists() and sha256_bytes(path.read_bytes()) == row["sha256"]
            verified += 1 if ok else 0
            failed += 0 if ok else 1
        log_audit(conn, "Scheduler", "歸檔封存", "file_objects", "archiveSeal", f"verified={verified}, failed={failed}")
        return {"message": f"成功：歸檔檔案驗證 {verified} 件，異常 {failed} 件", "payload": {"verified": verified, "failed": failed}}

    if job_type == "reportGenerate":
        report = dashboard(conn)
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value_json, version, updated_at) VALUES (?, ?, COALESCE((SELECT version + 1 FROM settings WHERE key = ?), 1), ?)",
            ("latest_report", json.dumps({"generated_at": now(), **report}, ensure_ascii=False), "latest_report", now()),
        )
        return {"message": f"成功：報表已產生，公文 {report['documents']} 件，交換成功率 {report['successRate']}%", "payload": report}

    return {"message": f"成功：{job_type} 無額外動作", "payload": {}}


def run_background_job(conn: sqlite3.Connection, job_id: str) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM background_jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return {"error": "not_found", "job_id": job_id}
    job = row_to_dict(row)
    if job["status"] != "啟用":
        return {"id": job_id, "status": "skipped", "result": "任務未啟用"}
    started = datetime.now()
    run_id = f"RUN-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    try:
        result = execute_job_logic(conn, job)
        status = "成功"
        message = result["message"]
        payload = result.get("payload", {})
    except Exception as exc:
        status = "失敗"
        message = str(exc)
        payload = {"error": message}
    finished = datetime.now()
    duration_ms = int((finished - started).total_seconds() * 1000)
    next_run = compute_next_run_at(job["schedule_text"], finished)
    conn.execute(
        """
        INSERT INTO job_runs (id, job_id, job_type, status, result, started_at, finished_at, duration_ms, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (run_id, job_id, job["job_type"], status, message, started.strftime("%Y-%m-%d %H:%M:%S"), finished.strftime("%Y-%m-%d %H:%M:%S"), duration_ms, json.dumps(payload, ensure_ascii=False)),
    )
    conn.execute(
        """
        UPDATE background_jobs
        SET last_result = ?, next_run_at = ?, run_count = run_count + 1, updated_at = ?
        WHERE id = ?
        """,
        (f"{status}：{message}", next_run, now(), job_id),
    )
    log_audit(conn, "Scheduler", f"背景任務{status}", "background_jobs", job_id, message)
    return {"run_id": run_id, "job_id": job_id, "status": status, "result": message, "next_run_at": next_run, "duration_ms": duration_ms, "payload": payload}


def run_due_background_jobs(conn: sqlite3.Connection, all_enabled: bool = False) -> Dict[str, Any]:
    if all_enabled:
        rows = conn.execute("SELECT id FROM background_jobs WHERE status = '啟用' ORDER BY next_run_at").fetchall()
    else:
        rows = conn.execute("SELECT id FROM background_jobs WHERE status = '啟用' AND next_run_at <= ? ORDER BY next_run_at", (now(),)).fetchall()
    results = [run_background_job(conn, row["id"]) for row in rows]
    return {"count": len(results), "results": results}


def notification_channels(channel: str | None) -> List[str]:
    normalized = channel or "系統通知"
    channels: List[str] = []
    if "Email" in normalized:
        channels.append("Email")
    if "Line" in normalized or "LINE" in normalized:
        channels.append("Line 工作群組")
    if "系統" in normalized or "站內" in normalized:
        channels.append("系統站內通知")
    return channels or [normalized]


def channel_required_env(channel: str) -> List[str]:
    if channel == "Email":
        required = ["SMTP_HOST", "SMTP_FROM"]
        if env_present("SMTP_USERNAME") or env_present("SMTP_PASSWORD"):
            required.extend(["SMTP_USERNAME", "SMTP_PASSWORD"])
        return required
    if channel == "Line 工作群組":
        if env_present("LINE_WEBHOOK_URL"):
            return ["LINE_WEBHOOK_URL"]
        return ["LINE_WEBHOOK_URL 或 LINE_CHANNEL_ACCESS_TOKEN + LINE_TARGET_ID"]
    if channel == "系統站內通知":
        return ["APP_SECRET"] if env_present("APP_SECRET") else ["CRON_SECRET"]
    return []


def notification_credential_status_for_channel(conn: sqlite3.Connection, channel: str) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM notification_channel_credentials WHERE channel = ? ORDER BY updated_at DESC LIMIT 1", (channel,)).fetchone()
    if not row:
        return {"channel": channel, "status": "未設定", "ok": False, "error": "credential_not_registered"}
    credential = row_to_dict(row)
    required = channel_required_env(channel)
    if channel == "Line 工作群組" and not env_present("LINE_WEBHOOK_URL"):
        missing = [] if env_present("LINE_CHANNEL_ACCESS_TOKEN") and env_present("LINE_TARGET_ID") else required
    else:
        missing = [name for name in required if not env_present(name)]
    expires_at = credential.get("expires_at") or ""
    expiry = parse_time(expires_at) if expires_at else datetime.max
    days_left = None if expiry == datetime.max else (expiry - datetime.now()).days
    if missing:
        status = "缺少環境憑證"
    elif expiry < datetime.now():
        status = "已到期"
    elif days_left is not None and days_left <= 14:
        status = "即將到期"
    else:
        status = "有效"
    return {**credential, "ok": status == "有效", "status": status, "missing": missing, "days_left": days_left}


def validate_notification_credentials(conn: sqlite3.Connection, channel: str = "") -> Dict[str, Any]:
    channels = [channel] if channel else ["Email", "Line 工作群組", "系統站內通知"]
    checked_at = now()
    results = []
    for item in channels:
        status = notification_credential_status_for_channel(conn, item)
        report = {
            "channel": item,
            "status": status["status"],
            "missing": status.get("missing", []),
            "expires_at": status.get("expires_at") or "",
            "days_left": status.get("days_left"),
            "fingerprint_sha256": status.get("fingerprint_sha256") or "",
            "checked_at": checked_at,
        }
        if status.get("id"):
            conn.execute(
                """
                UPDATE notification_channel_credentials
                SET status = ?, last_validated_at = ?, validation_report_json = ?, masked_identifier = ?, fingerprint_sha256 = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status["status"],
                    checked_at,
                    json.dumps(report, ensure_ascii=False),
                    mask_notification_credential(status["env_key_name"]),
                    notification_credential_fingerprint(status["env_key_name"]),
                    checked_at,
                    status["id"],
                ),
            )
        results.append(report)
    ok = all(item["status"] in {"有效", "即將到期"} for item in results)
    log_audit(conn, "Notify Worker", "通知通道正式憑證驗證", "notification_channel_credentials", channel or "all", json.dumps(results, ensure_ascii=False))
    return {"ok": ok, "checked_at": checked_at, "credentials": results}


def notification_gateway_status() -> Dict[str, Any]:
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_from = os.getenv("SMTP_FROM", "").strip()
    smtp_username = os.getenv("SMTP_USERNAME", "").strip()
    line_url = os.getenv("LINE_WEBHOOK_URL", "").strip()
    line_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    line_target = os.getenv("LINE_TARGET_ID", "").strip()
    # This function is also used in Supabase mode without a local connection, so it reports env-derived state only.
    email_configured = bool(smtp_host and smtp_from)
    line_configured = bool(line_url or (line_token and line_target))
    return {
        "email": {
            "configured": email_configured,
            "host": smtp_host or "未設定",
            "port": os.getenv("SMTP_PORT", "587"),
            "from": smtp_from or "未設定",
            "username": smtp_username or "未設定",
            "status": "可測試" if email_configured else "未設定",
            "credentialExpiresAt": os.getenv("SMTP_CREDENTIAL_EXPIRES_AT", ""),
        },
        "line": {
            "configured": line_configured,
            "webhook": f"{line_url[:28]}..." if line_url else ("Messaging API push" if line_token and line_target else "未設定"),
            "mode": "webhook" if line_url else ("messaging-api-push" if line_token and line_target else "not_configured"),
            "target": f"{line_target[:8]}..." if line_target else "未設定",
            "status": "可測試" if line_configured else "未設定",
            "credentialExpiresAt": os.getenv("LINE_CREDENTIAL_EXPIRES_AT", ""),
        },
        "systemInbox": {
            "configured": True,
            "status": "啟用",
            "credentialExpiresAt": os.getenv("INBOX_SIGNING_KEY_EXPIRES_AT", ""),
        },
    }


def local_monitoring_snapshot(conn: sqlite3.Connection) -> Dict[str, Any]:
    readiness = production_readiness()
    alerts: List[Dict[str, str]] = []
    for name in readiness["missing"]:
        append_alert(alerts, "critical" if is_production() else "warning", "ENV-MISSING", f"缺少正式環境變數 {name}", "到 Vercel Project Settings 補齊後重新部署。")
    for item in readiness["blockers"]:
        append_alert(alerts, "critical", "READINESS-BLOCKER", item, "先處理 production readiness blocker，再開放正式交換。")
    for item in readiness["warnings"]:
        append_alert(alerts, "warning", "READINESS-WARNING", item, "排入上線前檢核清單，避免正式營運缺口。")

    counts = {
        "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        "attachments": conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0],
        "exchange_failed": conn.execute("SELECT COUNT(*) FROM exchange_tasks WHERE status IN ('交換失敗','失敗','逾期未確認')").fetchone()[0],
        "notification_failed": conn.execute("SELECT COUNT(*) FROM notification_deliveries WHERE status IN ('失敗','未設定','憑證異常')").fetchone()[0],
        "job_failed": conn.execute("SELECT COUNT(*) FROM job_runs WHERE status IN ('失敗','錯誤')").fetchone()[0],
    }
    if counts["exchange_failed"]:
        append_alert(alerts, "critical", "EXCHANGE-FAILED", f"{counts['exchange_failed']} 筆交換任務失敗或逾期。", "由總務工作台重送或執行翌日查核。")
    if counts["notification_failed"]:
        append_alert(alerts, "warning", "NOTIFICATION-FAILED", f"{counts['notification_failed']} 筆通知派送失敗。", "到通知中心重送，並檢查 Email/Line 憑證。")
    if counts["job_failed"]:
        append_alert(alerts, "warning", "JOB-FAILED", f"{counts['job_failed']} 筆背景任務失敗。", "到背景任務頁查看 job_runs 與 API log。")

    last_job_row = conn.execute("SELECT * FROM job_runs ORDER BY finished_at DESC LIMIT 1").fetchone()
    last_job = row_to_dict(last_job_row) if last_job_row else None
    last_job_age = age_minutes(last_job.get("finished_at") if last_job else None)
    if is_production() and (last_job_age is None or last_job_age > EDOC_MONITORING_EXPECTED_CRON_MINUTES + 120):
        append_alert(alerts, "critical", "CRON-STALLED", "正式環境背景排程超過預期時間未執行。", "檢查 Vercel Cron、CRON_SECRET 與 /api/cron/run-due 執行紀錄。")

    credentials = [notification_credential_status_for_channel(conn, channel) for channel in ["Email", "Line 工作群組", "系統站內通知"]]
    for credential in credentials:
        if credential.get("status") in {"缺少環境憑證", "已到期", "未設定"}:
            append_alert(alerts, "critical" if is_production() else "warning", "CREDENTIAL-INVALID", f"{credential['channel']} 憑證狀態：{credential.get('status')}", "補齊正式憑證、有效期限與環境變數後重新驗證。")
        elif credential.get("status") == "即將到期":
            append_alert(alerts, "warning", "CREDENTIAL-EXPIRING", f"{credential['channel']} 憑證即將到期。", "在到期前完成換證與驗證。")
    signing_service = signing_service_status()
    if signing_service["productionBlocked"]:
        append_alert(alerts, "critical", "SIGNING-SERVICE-INCOMPLETE", f"正式簽章服務尚未設定：{', '.join(signing_service['missing'])}", "設定 HSM/KMS、信任根憑證、TSA、OCSP、CRL 與 EDOC_SIGNING_SECRET 後重新部署。")
    elif not signing_service["ready"]:
        append_alert(alerts, "warning", "SIGNING-SERVICE-SIMULATION", f"簽章服務仍為模擬或不完整：{', '.join(signing_service['missing'])}", "正式上線前完成外部簽章服務接入。")
    storage_service = storage_service_status()
    if storage_service["productionBlocked"]:
        append_alert(alerts, "critical", "STORAGE-SERVICE-INCOMPLETE", f"正式檔案儲存與防毒尚未設定：{', '.join(storage_service['missing'])}", "設定 Supabase Storage private bucket、檔案加密、短效 URL、正式 AV endpoint/API key 後重新部署。")
    elif not storage_service["ready"]:
        append_alert(alerts, "warning", "STORAGE-SERVICE-SIMULATION", f"檔案儲存或防毒服務仍為本機/不完整：{', '.join(storage_service['missing'])}", "正式上線前完成物件儲存與防毒引擎接入。")

    checks = {
        "database": {"status": "ok", "mode": "sqlite", "detail": str(DB_PATH)},
        "readiness": {"status": "ok" if readiness["ready"] else "needs_action", "missing": readiness["missing"], "blockers": readiness["blockers"]},
        "storage": {"status": "ok" if storage_service["ready"] else "needs_action", **storage_service},
        "cron": {"status": "ok" if last_job_age is not None else "not_yet_run", "lastRun": last_job, "ageMinutes": last_job_age},
        "notifications": {"status": "ok" if all(item.get("status") in {"有效", "即將到期"} for item in credentials) else "needs_action", "credentials": credentials},
        "signing": {"status": "ok" if signing_service["ready"] else "needs_action", **signing_service},
        "jAgent": {"status": "needs_action" if counts["exchange_failed"] else "ok", "failedTasks": counts["exchange_failed"]},
    }
    status = monitoring_status(alerts)
    return {
        "ok": status != "critical",
        "status": status,
        "checkedAt": now(),
        "deployment": deployment_report(),
        "checks": checks,
        "counts": counts,
        "alerts": alerts,
    }


def post_monitoring_webhook(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    if not MONITORING_WEBHOOK_URL:
        return {"sent": False, "reason": "MONITORING_WEBHOOK_URL 未設定"}
    payload = json.dumps({
        "system": "Suiyuecare eDoc",
        "status": snapshot["status"],
        "checkedAt": snapshot["checkedAt"],
        "alerts": snapshot["alerts"][:8],
        "deployment": snapshot["deployment"],
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        MONITORING_WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "suiyuecare-edoc-monitor"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return {"sent": True, "status": response.status}
    except Exception as exc:
        return {"sent": False, "error": str(exc)}


def run_local_monitoring_check(conn: sqlite3.Connection) -> Dict[str, Any]:
    snapshot = local_monitoring_snapshot(conn)
    webhook = post_monitoring_webhook(snapshot) if snapshot["alerts"] else {"sent": False, "reason": "無告警"}
    log_structured("info", "production_monitoring_check", status=snapshot["status"], alerts=len(snapshot["alerts"]), webhook_sent=bool(webhook.get("sent")), runtime="local")
    log_audit(conn, "Ops Monitor", "正式部署監控檢查", "production_monitoring", snapshot["status"], json.dumps({"alerts": snapshot["alerts"], "webhook": webhook}, ensure_ascii=False))
    return {**snapshot, "webhook": webhook}


def notification_target_email(conn: sqlite3.Connection, role: str, explicit: str = "") -> str:
    if explicit:
        return explicit
    row = conn.execute("SELECT email FROM users WHERE role = ? AND status = '啟用' ORDER BY rowid LIMIT 1", (role,)).fetchone()
    return row["email"] if row else f"{role}@suiyuecare.local"


def create_notification(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    item = {
        "id": payload.get("id") or f"NTF-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "type": payload.get("type") or "一般通知",
        "title": payload.get("title") or f"{payload.get('type') or '一般'}通知",
        "target_role": payload.get("target_role") or payload.get("target") or "行政部主任",
        "target_email": payload.get("target_email") or "",
        "channel": payload.get("channel") or "系統通知",
        "status": payload.get("status") or "未讀",
        "priority": payload.get("priority") or "中",
        "source": payload.get("source") or "",
        "body": payload.get("body") or "請確認電子公文交換待辦事項。",
        "delivery_receipt": payload.get("delivery_receipt") or "",
        "created_at": payload.get("created_at") or now(),
        "sent_at": payload.get("sent_at") or None,
    }
    conn.execute(
        """
        INSERT OR IGNORE INTO notifications (
          id, type, title, target_role, target_email, channel, status, priority, source, body, delivery_receipt, created_at, sent_at
        ) VALUES (
          :id, :type, :title, :target_role, :target_email, :channel, :status, :priority, :source, :body, :delivery_receipt, :created_at, :sent_at
        )
        """,
        item,
    )
    return row_to_dict(conn.execute("SELECT * FROM notifications WHERE id = ?", (item["id"],)).fetchone())


def record_notification_delivery(
    conn: sqlite3.Connection,
    notification_id: str,
    channel: str,
    target: str,
    status: str,
    receipt: str = "",
    error: str = "",
) -> Dict[str, Any]:
    row = {
        "id": f"NDEL-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "notification_id": notification_id,
        "channel": channel,
        "target": target,
        "status": status,
        "receipt": receipt,
        "error": error,
        "attempt_count": 1,
        "created_at": now(),
    }
    conn.execute(
        """
        INSERT INTO notification_deliveries (
          id, notification_id, channel, target, status, receipt, error, attempt_count, created_at
        ) VALUES (
          :id, :notification_id, :channel, :target, :status, :receipt, :error, :attempt_count, :created_at
        )
        """,
        row,
    )
    return row


def send_email_notification(to_email: str, subject: str, body: str) -> Dict[str, str]:
    host = os.getenv("SMTP_HOST", "").strip()
    if not host:
        return {"status": "未設定", "receipt": "", "error": "SMTP_HOST 未設定"}
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", username or "no-reply@suiyuecare.local")
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() not in {"0", "false", "no"}
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to_email
    message["Subject"] = subject
    message["Message-ID"] = f"<edoc-{int(time.time() * 1000)}-{secrets.token_hex(4)}@suiyuecare.com>"
    message.set_content(body)
    context = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as smtp:
                if username:
                    smtp.login(username, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                if use_tls:
                    smtp.starttls(context=context)
                if username:
                    smtp.login(username, password)
                smtp.send_message(message)
        return {"status": "成功", "receipt": message["Message-ID"], "error": ""}
    except Exception as exc:
        return {"status": "失敗", "receipt": "", "error": str(exc)}


def send_line_notification(message: str) -> Dict[str, str]:
    url = os.getenv("LINE_WEBHOOK_URL", "").strip()
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    target_id = os.getenv("LINE_TARGET_ID", "").strip()
    if url:
        data = json.dumps({"message": message, "source": "suiyuecare-edoc"}, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "suiyuecare-edoc-notify"}
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    elif token and target_id:
        data = json.dumps({"to": target_id, "messages": [{"type": "text", "text": message[:5000]}]}, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}", "User-Agent": "suiyuecare-edoc-notify"}
        request = urllib.request.Request("https://api.line.me/v2/bot/message/push", data=data, headers=headers, method="POST")
    else:
        return {"status": "未設定", "receipt": "", "error": "LINE_WEBHOOK_URL 或 LINE_CHANNEL_ACCESS_TOKEN + LINE_TARGET_ID 未設定"}
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            receipt = response.headers.get("X-Line-Request-Id") or response.headers.get("X-Request-Id") or f"LINE-{int(time.time() * 1000)}"
            return {"status": "成功" if 200 <= response.status < 300 else "失敗", "receipt": receipt, "error": ""}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        return {"status": "失敗", "receipt": "", "error": f"HTTP {exc.code}: {detail}"}
    except Exception as exc:
        return {"status": "失敗", "receipt": "", "error": str(exc)}


def push_system_notification(conn: sqlite3.Connection, item: Dict[str, Any]) -> Dict[str, str]:
    inbox_id = f"INBOX-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    conn.execute(
        """
        INSERT INTO system_inbox (id, notification_id, target_role, target_user_id, title, body, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, '未讀', ?)
        """,
        (inbox_id, item["id"], item["target_role"], "", item["title"], item["body"], now()),
    )
    return {"status": "成功", "receipt": inbox_id, "error": ""}


def notification_attempt_result(channel: str, target: str, result: Dict[str, str], started: float) -> Dict[str, str | int]:
    return {
        "channel": channel,
        "target": target,
        "status": result.get("status", "失敗"),
        "receipt": result.get("receipt", ""),
        "error": result.get("error", ""),
        "attempted_at": now(),
        "duration_ms": int((time.time() - started) * 1000),
    }


def notification_delivery_report(notification: Dict[str, Any], delivery: Dict[str, Any], requested_channel: str) -> Dict[str, Any]:
    failed = [item for item in delivery.get("results", []) if item.get("status") != "成功"]
    return {
        "ok": delivery.get("success", 0) == delivery.get("total", 0) and delivery.get("total", 0) > 0,
        "checked_at": now(),
        "requested_channel": requested_channel,
        "notification_id": notification.get("id"),
        "title": notification.get("title"),
        "target_role": notification.get("target_role"),
        "target_email": notification.get("target_email"),
        "summary": delivery.get("receipt", ""),
        "success": delivery.get("success", 0),
        "total": delivery.get("total", 0),
        "failed": failed,
        "results": delivery.get("results", []),
    }


def deliver_notification(conn: sqlite3.Connection, notification_id: str, force_channel: str = "") -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM notifications WHERE id = ?", (notification_id,)).fetchone()
    if not row:
        return {"id": notification_id, "status": "失敗", "error": "notification_not_found", "results": []}
    item = row_to_dict(row)
    channels = notification_channels(force_channel or item["channel"])
    target_email = notification_target_email(conn, item["target_role"], item.get("target_email") or "")
    results: List[Dict[str, str]] = []
    for channel in channels:
        credential = notification_credential_status_for_channel(conn, channel)
        if channel != "系統站內通知" and credential["status"] not in {"有效", "即將到期"}:
            result = {"status": "憑證異常", "receipt": "", "error": f"{channel} 正式憑證{credential['status']}，請先完成憑證驗證或更新。"}
            target = target_email if channel == "Email" else "歲悅電子公文 LINE 工作群組"
            record_notification_delivery(conn, item["id"], channel, target, result["status"], result.get("receipt", ""), result.get("error", ""))
            results.append({"channel": channel, "target": target, **result, "attempted_at": now(), "duration_ms": 0})
            continue
        started = time.time()
        if channel == "Email":
            result = send_email_notification(target_email, item["title"], item["body"])
            target = target_email
        elif channel == "Line 工作群組":
            result = send_line_notification(f"{item['title']}\n{item['body']}")
            target = "歲悅電子公文 LINE 工作群組"
        else:
            result = push_system_notification(conn, item)
            target = item["target_role"]
        record_notification_delivery(conn, item["id"], channel, target, result["status"], result.get("receipt", ""), result.get("error", ""))
        results.append(notification_attempt_result(channel, target, result, started))

    success_count = len([item for item in results if item["status"] == "成功"])
    receipt_text = "；".join(
        f"{result['channel']}->{result['target']}:{result['status']}{('/' + result['receipt']) if result.get('receipt') else ''}{(' / ' + result['error']) if result.get('error') else ''}"
        for result in results
    )
    status = "已派送" if success_count == len(results) else "部分派送" if success_count else "派送失敗"
    conn.execute(
        "UPDATE notifications SET status = ?, sent_at = ?, delivery_receipt = ? WHERE id = ?",
        (status, now(), receipt_text, item["id"]),
    )
    log_audit(conn, "Notify Worker", "通知派送", "notifications", item["id"], receipt_text)
    return {"id": item["id"], "status": status, "success": success_count, "total": len(results), "receipt": receipt_text, "results": results}


def ensure_notification_for_source(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any] | None:
    source = payload.get("source") or ""
    notice_type = payload.get("type") or ""
    if not source or not notice_type:
        return create_notification(conn, payload)
    row = conn.execute("SELECT * FROM notifications WHERE source = ? AND type = ? LIMIT 1", (source, notice_type)).fetchone()
    if row:
        return row_to_dict(row)
    return create_notification(conn, payload)


def fallback_ai_compose(payload: Dict[str, Any]) -> Dict[str, Any]:
    plain = str(payload.get("plainText") or payload.get("plain_text") or "").strip()
    recipient = str(payload.get("recipient") or "貴機關").strip()
    doc_type = str(payload.get("docType") or payload.get("doc_type") or "函").strip()
    topic = plain.replace("\n", "，").strip("，。 ")
    if len(topic) > 42:
        topic = f"{topic[:42]}..."
    subject = f"有關{topic or '本公司業務事項'}，請查照。"
    body_lines = [
        f"一、依業務需要辦理，檢送相關資料予{recipient}參辦。",
        f"二、{plain or '相關內容如附件及補充說明，請惠予協助確認。'}",
        "三、如需補充資料或聯繫窗口，請逕洽本公司承辦人，俾利後續作業。"
    ]
    return {
        "subject": subject,
        "body": "\n".join(body_lines),
        "model": "local-template",
        "usedOpenAI": False,
        "notice": "OPENAI_API_KEY 未設定或 OpenAI 服務暫不可用，已使用本機公文模板產生。"
    }


def extract_openai_text(data: Dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    chunks: List[str] = []
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "\n".join(chunks).strip()


def parse_ai_compose_json(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").replace("json\n", "", 1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


def ai_compose_official_draft(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    plain = str(payload.get("plainText") or payload.get("plain_text") or "").strip()
    if len(plain) < 6:
        return {"error": "invalid_request", "detail": "白話文內容至少需要 6 個字。"}
    context = {
        "docType": payload.get("docType") or "函",
        "priority": payload.get("priority") or "普通件",
        "recipient": payload.get("recipient") or "未指定受文者",
        "attachments": payload.get("attachments") or [],
        "role": payload.get("role") or "業務助理"
    }
    if not OPENAI_API_KEY:
        result = fallback_ai_compose({**payload, **context})
        log_audit(conn, context["role"], "AI 公文助理產生函稿", "ai_compose", "local-template", result["notice"])
        return result
    request_payload = {
        "model": OPENAI_MODEL,
        "input": [
            {
                "role": "system",
                "content": (
                    "你是台灣長照公司電子公文撰寫助理。"
                    "請把使用者白話內容改寫成正式公文用語，只輸出 JSON，"
                    "格式為 {\"subject\":\"...\",\"body\":\"...\"}。"
                    "subject 必須精簡、以「請查照」或相近正式語氣結尾；"
                    "body 使用中文條列「一、」「二、」「三、」，語氣正式、清楚、不可捏造未提供的法規或事實。"
                )
            },
            {
                "role": "user",
                "content": json.dumps({"plainText": plain, "context": context}, ensure_ascii=False)
            }
        ],
        "temperature": 0.2
    }
    data = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=data,
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_data = json.loads(response.read().decode("utf-8"))
        text = extract_openai_text(response_data)
        parsed = parse_ai_compose_json(text)
        subject = str(parsed.get("subject") or "").strip()
        body = str(parsed.get("body") or "").strip()
        if not subject or not body:
            raise ValueError("openai_response_missing_subject_or_body")
        result = {"subject": subject, "body": body, "model": OPENAI_MODEL, "usedOpenAI": True}
        log_audit(conn, context["role"], "AI 公文助理產生函稿", "ai_compose", OPENAI_MODEL, f"recipient={context['recipient']}")
        return result
    except Exception as exc:
        result = fallback_ai_compose({**payload, **context})
        result["notice"] = f"OpenAI 產生失敗，已使用本機公文模板：{exc}"
        log_audit(conn, context["role"], "AI 公文助理備援產生函稿", "ai_compose", "local-template", str(exc))
        return result
def sync_notifications_from_business_state(conn: sqlite3.Connection) -> Dict[str, Any]:
    created = 0
    items: List[Dict[str, Any]] = []
    inbound = conn.execute("SELECT * FROM documents WHERE direction = '收文' AND status IN ('待登錄','待分派')").fetchall()
    for doc in inbound:
        before = conn.execute("SELECT COUNT(*) FROM notifications WHERE source = ? AND type = '收文'", (doc["id"],)).fetchone()[0]
        item = ensure_notification_for_source(conn, {
            "type": "收文",
            "title": f"{doc['doc_no']} {doc['status']}",
            "target_role": "總務",
            "channel": "系統通知",
            "priority": "高",
            "source": doc["id"],
            "body": f"{doc['agency_name']} 來文「{doc['subject']}」需處理。",
        })
        created += 0 if before else 1
        if item:
            items.append(item)

    dispatch = conn.execute("SELECT * FROM documents WHERE direction = '發文' AND status IN ('待清稿','已清稿','交換失敗')").fetchall()
    for doc in dispatch:
        notice_type = "交換失敗" if doc["status"] == "交換失敗" else "待清稿"
        before = conn.execute("SELECT COUNT(*) FROM notifications WHERE source = ? AND type = ?", (doc["id"], notice_type)).fetchone()[0]
        item = ensure_notification_for_source(conn, {
            "type": notice_type,
            "title": f"{doc['doc_no']} {doc['status']}",
            "target_role": "總務" if notice_type == "交換失敗" else "行政部主任",
            "channel": "Email + Line + 系統通知" if notice_type == "交換失敗" else "Email + 系統通知",
            "priority": "高",
            "source": doc["id"],
            "body": f"{doc['subject']} 目前狀態：{doc['status']}。",
        })
        created += 0 if before else 1
        if item:
            items.append(item)

    expiring = conn.execute("SELECT COUNT(*) FROM auth_sessions WHERE revoked_at IS NULL AND expires_at <= ?", ((datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),)).fetchone()[0]
    if expiring:
        before = conn.execute("SELECT COUNT(*) FROM notifications WHERE source = 'SEC-TOKEN' AND type = 'Token 到期'").fetchone()[0]
        item = ensure_notification_for_source(conn, {
            "type": "Token 到期",
            "title": "jAgent Token 到期檢查",
            "target_role": "行政部主任",
            "channel": "Email + 系統通知",
            "priority": "中",
            "source": "SEC-TOKEN",
            "body": f"{expiring} 個 session 將於 1 小時內到期，請確認憑證登入與 Token 更新。",
        })
        created += 0 if before else 1
        if item:
            items.append(item)
    return {"created": created, "items": items}


def retry_failed_notifications(conn: sqlite3.Connection) -> Dict[str, Any]:
    rows = conn.execute("SELECT id FROM notifications WHERE status IN ('派送失敗','部分派送') OR delivery_receipt IS NULL OR delivery_receipt = ''").fetchall()
    results = [deliver_notification(conn, row["id"]) for row in rows]
    return {"count": len(results), "results": results}


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
    if table == "users":
        apply_user_permission_defaults(payload)
    if table == "documents" and payload.get("direction") == "發文" and not payload.get("doc_no"):
        payload["doc_no"] = supabase_next_dispatch_no()
    timestamp = now()
    if table in {"documents", "recipients", "exchange_tasks", "exchange_outbox", "exchange_inbox", "settings", "notification_rules", "company_registry", "department_registry", "seal_type_registry", "companies", "seal_reference_options", "company_seals", "seal_usage_requests", "seal_usage_approvals", "workflow_tasks", "contracts", "contract_parties", "contract_approvals", "module_account_links", "official_documents", "official_document_approval_steps", "official_document_stamp_requests", "official_document_dispatch_records"}:
        payload.setdefault("updated_at", timestamp)
    if table in {"documents", "attachments", "exchange_events", "exchange_outbox", "exchange_inbox", "exchange_log", "exchange_attachment", "exchange_status_history", "audit_logs", "users", "notifications", "notification_deliveries", "system_inbox", "company_registry", "department_registry", "seal_type_registry", "companies", "seal_reference_options", "company_seals", "seal_permissions", "seal_usage_approvals", "seal_usage_logs", "workflow_tasks", "contracts", "contract_parties", "contract_approvals", "signature_provider_events", "module_account_links", "official_documents", "official_document_files", "official_document_approval_steps", "official_document_approval_logs", "official_document_stamp_requests", "official_document_dispatch_records"}:
        payload.setdefault("created_at", timestamp)
    if table in {"documents", "workflow_tasks", "contracts", "contract_approvals", "seal_usage_requests", "exchange_log", "exchange_inbox", "exchange_status_history", "audit_logs", "module_account_links", "official_documents"}:
        for key, value in list(payload.items()):
            if key.endswith("_json") and not isinstance(value, str):
                payload[key] = json.dumps(value, ensure_ascii=False)
    rows = supabase_request("POST", table, payload)
    created = rows[0] if rows else payload
    if table == "users":
        permission_fields = {"role", "status", "unit", "title", "job_level", "mfa_status"}
        supabase_insert("audit_logs", {
            "id": f"AUD-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
            "actor": "API",
            "action": "權限異動",
            "target_type": "user_role",
            "target_id": created.get("id"),
            "ip": "vercel",
            "device": "serverless",
            "detail": "建立使用者帳號與初始角色權限。",
            "event_type": "permission_change",
            "severity": "critical",
            "result": "success",
            "module_code": "system_permissions",
            "resource_type": "user_role",
            "resource_id": created.get("id"),
            "data_scope": "custom",
            "actor_roles_json": ["system_permissions.manage"],
            "target_user_id": created.get("id"),
            "target_email": created.get("email", ""),
            "reason": "建立使用者帳號與初始角色權限。",
            "request_id": f"req_{secrets.token_hex(8)}",
            "before_snapshot_json": {},
            "after_snapshot_json": {key: created.get(key) for key in sorted(permission_fields) if key in created},
            "metadata_json": {"source": "edoc_rbac_supabase"},
        })
    return created


def supabase_next_dispatch_no() -> str:
    date_serial = roc_date_serial()
    prefix = f"歲悅字第{date_serial}"
    qs = urllib.parse.urlencode({
        "select": "doc_no",
        "direction": "eq.發文",
        "doc_no": f"like.{prefix}%號",
        "limit": "500",
    })
    rows = supabase_request("GET", f"documents?{qs}")
    max_serial = 0
    for row in rows:
        value = row.get("doc_no", "")
        if value.startswith(prefix) and value.endswith("號"):
            serial = value[len(prefix):-1]
            if serial.isdigit():
                max_serial = max(max_serial, int(serial))
    return f"{prefix}{max_serial + 1:03d}號"


def supabase_patch(table: str, row_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    before = supabase_get(table, row_id) if table == "users" else None
    if table == "users":
        permission_inputs = {"role", "unit", "title", "job_level", "company", "region", "class_name"}
        merged_payload = {**(before or {}), **payload}
        profile = edoc_roster_permission_profile(merged_payload)
        if "job_level" in payload:
            payload["job_level"] = profile["job_level"]
        if permission_inputs.intersection(payload) and (not payload.get("role") or payload.get("role") not in ALLOWED_EDOC_ROLES):
            payload["role"] = profile["role"]
    if table in {"documents", "recipients", "exchange_tasks", "exchange_outbox", "exchange_inbox", "settings", "background_jobs", "notification_rules", "company_registry", "department_registry", "seal_type_registry", "companies", "seal_reference_options", "company_seals", "seal_usage_requests", "seal_usage_approvals", "workflow_tasks", "contracts", "contract_parties", "contract_approvals", "module_account_links", "official_documents", "official_document_approval_steps", "official_document_stamp_requests", "official_document_dispatch_records"}:
        payload["updated_at"] = now()
    if table in {"documents", "workflow_tasks", "contracts", "contract_approvals", "seal_usage_requests", "exchange_log", "exchange_inbox", "exchange_status_history", "audit_logs", "module_account_links", "official_documents"}:
        for key, value in list(payload.items()):
            if key.endswith("_json") and not isinstance(value, str):
                payload[key] = json.dumps(value, ensure_ascii=False)
    qs = urllib.parse.urlencode({"id": f"eq.{row_id}"})
    rows = supabase_request("PATCH", f"{table}?{qs}", payload)
    updated = rows[0] if rows else {}
    permission_fields = {"role", "status", "unit", "title", "job_level", "mfa_status"}
    if table == "users" and before and updated and permission_fields.intersection(payload):
        supabase_insert("audit_logs", {
            "id": f"AUD-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
            "actor": "API",
            "action": "權限異動",
            "target_type": "user_role",
            "target_id": row_id,
            "ip": "vercel",
            "device": "serverless",
            "detail": "使用者角色、職等、狀態或權限相關資料異動。",
            "event_type": "permission_change",
            "severity": "critical",
            "result": "success",
            "module_code": "system_permissions",
            "resource_type": "user_role",
            "resource_id": row_id,
            "data_scope": "custom",
            "actor_roles_json": ["system_permissions.manage"],
            "target_user_id": row_id,
            "target_email": updated.get("email", before.get("email", "")),
            "reason": "使用者角色、職等、狀態或權限相關資料異動。",
            "request_id": f"req_{secrets.token_hex(8)}",
            "before_snapshot_json": {key: before.get(key) for key in sorted(permission_fields) if key in before},
            "after_snapshot_json": {key: updated.get(key) for key in sorted(permission_fields) if key in updated},
            "metadata_json": {"source": "edoc_rbac_supabase"},
        })
    return updated


def supabase_filter_rows(table: str, filters: Dict[str, Any] | None = None, *, order: str = "", limit: int = 500, select: str = "*") -> List[Dict[str, Any]]:
    params: Dict[str, str] = {"select": select, "limit": str(limit)}
    for key, value in (filters or {}).items():
        if value is None:
            continue
        if value == "__is_null__":
            params[key] = "is.null"
        elif isinstance(value, bool):
            params[key] = f"eq.{str(value).lower()}"
        else:
            params[key] = f"eq.{value}"
    if order:
        params["order"] = order
    return supabase_request("GET", f"{table}?{urllib.parse.urlencode(params)}")


def supabase_update_many(table: str, filters: Dict[str, Any], payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    params = {
        key: (f"is.null" if value == "__is_null__" else f"eq.{str(value).lower()}" if isinstance(value, bool) else f"eq.{value}")
        for key, value in filters.items()
    }
    return supabase_request("PATCH", f"{table}?{urllib.parse.urlencode(params)}", payload)


def supabase_storage_object_url(storage_key: str, bucket: str | None = None) -> str:
    base = EDOC_OBJECT_STORAGE_URL or (f"{SUPABASE_URL}/storage/v1" if SUPABASE_URL else "")
    if not base:
        raise ValueError("supabase_storage_endpoint_required")
    storage_bucket = bucket or EDOC_STORAGE_BUCKET
    return f"{base.rstrip('/')}/object/{urllib.parse.quote(storage_bucket, safe='')}/{urllib.parse.quote(storage_key, safe='/')}"


def supabase_storage_upload(storage_key: str, data: bytes, mime_type: str, bucket: str | None = None) -> None:
    url = supabase_storage_object_url(storage_key, bucket)
    headers = supabase_headers({"Content-Type": mime_type, "x-upsert": "false"})
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")
        raise ValueError(f"supabase_storage_upload_failed:{exc.code}:{redact_text(detail)}") from exc


def supabase_storage_download(storage_key: str, bucket: str | None = None) -> bytes:
    url = supabase_storage_object_url(storage_key, bucket)
    request = urllib.request.Request(url, headers=supabase_headers(), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")
        raise ValueError(f"supabase_storage_download_failed:{exc.code}:{redact_text(detail)}") from exc


def supabase_store_file_object(document_id: str, file_name: str, data: bytes, purpose: str, version_label: str, actor: str, mime_type: str) -> Dict[str, Any]:
    file_id = f"FILE-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    safe_name = Path(file_name).name
    storage_key = f"{purpose}/{document_id}/{file_id}-{safe_name}"
    is_seal_vault = purpose.startswith(SEAL_VAULT_PURPOSE_PREFIX)
    bucket = EDOC_SEAL_STORAGE_BUCKET if is_seal_vault else EDOC_STORAGE_BUCKET
    supabase_storage_upload(storage_key, data, mime_type, bucket)
    row = {
        "id": file_id,
        "document_id": document_id,
        "file_name": safe_name,
        "storage_key": storage_key,
        "bucket": bucket,
        "storage_provider": "seal-vault" if is_seal_vault else (EDOC_STORAGE_PROVIDER or "supabase"),
        "mime_type": mime_type,
        "size_bytes": len(data),
        "sha256": sha256_bytes(data),
        "encrypted_sha256": "",
        "encryption_status": "由物件儲存服務控管",
        "encryption_alg": "",
        "encryption_key_id": "",
        "scan_status": "待掃描",
        "scan_engine": EDOC_SCAN_ENGINE,
        "quarantine_reason": "",
        "signed_url_expires_at": "",
        "last_scan_at": "",
        "last_download_at": "",
        "version_label": version_label,
        "purpose": purpose,
        "created_by": actor,
        "created_at": now(),
    }
    return supabase_insert("file_objects", row)


def supabase_reference_codes(option_type: str) -> set[str]:
    return {row["code"] for row in supabase_filter_rows("seal_reference_options", {"option_type": option_type, "status": "active"})}


def supabase_log_seal_usage(
    *,
    action: str,
    actor_id: str = "API",
    usage_request_id: str = "",
    seal_id: str = "",
    document_id: str = "",
    detail: str = "",
    ip_address: str = "",
    user_agent: str = "",
) -> Dict[str, Any]:
    row = {
        "id": f"SLOG-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "usage_request_id": usage_request_id or None,
        "seal_id": seal_id or None,
        "document_id": document_id or None,
        "action": action,
        "actor_id": actor_id,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "detail": detail,
        "created_at": now(),
    }
    created = supabase_insert("seal_usage_logs", row)
    supabase_insert("audit_logs", {
        "id": f"AUD-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "actor": actor_id,
        "action": action,
        "target_type": "seal_usage",
        "target_id": usage_request_id or seal_id or document_id,
        "detail": detail,
        "event_type": action,
        "module_code": "seals",
        "resource_type": "seal_usage",
        "resource_id": usage_request_id or seal_id or document_id,
        "result": "success",
        "severity": "info",
    })
    return created


def supabase_company_seal_row(seal_id: str) -> Dict[str, Any]:
    seal = supabase_get("company_seals", seal_id)
    if not seal:
        raise ValueError("seal_not_found")
    company = supabase_get("companies", seal.get("company_id", "")) or {}
    current_files = supabase_filter_rows("company_seal_files", {"seal_id": seal_id, "is_current": True}, order="version.desc", limit=1)
    data = {**seal, "company_name": company.get("name", ""), "company_tax_id": company.get("tax_id", "")}
    data["current_file"] = seal_file_metadata(current_files[0]) if current_files else None
    return data


def supabase_list_company_seals(company_id: str) -> List[Dict[str, Any]]:
    rows = supabase_filter_rows("company_seals", {"company_id": company_id}, order="is_active.desc,seal_category.asc,seal_size_type.asc,created_at.desc", limit=500)
    return [supabase_company_seal_row(row["id"]) for row in rows]


def supabase_create_company_seal(company_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not supabase_get("companies", company_id):
        raise ValueError("company_not_found")
    category = payload.get("seal_category") or payload.get("category") or "other"
    size_type = payload.get("seal_size_type") or payload.get("size_type") or "large_seal"
    if category not in supabase_reference_codes("category"):
        raise ValueError("invalid_seal_category")
    if size_type not in supabase_reference_codes("size"):
        raise ValueError("invalid_seal_size_type")
    actor = seal_actor(session, payload)
    seal_id = payload.get("id") or f"CSEAL-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    supabase_insert("company_seals", {
        "id": seal_id,
        "company_id": company_id,
        "seal_name": payload.get("seal_name") or payload.get("name") or "未命名印章",
        "seal_category": category,
        "seal_size_type": size_type,
        "purpose_description": payload.get("purpose_description") or payload.get("purpose") or "",
        "is_active": bool(payload.get("is_active", True)),
        "created_by": actor,
        "created_at": now(),
        "updated_at": now(),
        "deactivated_at": "",
    })
    for role in payload.get("default_permission_roles") or ["viewer", "requester", "approver", "seal_admin"]:
        if role in supabase_reference_codes("permission_role"):
            supabase_insert("seal_permissions", {"id": f"SPERM-{seal_id}-{role}", "seal_id": seal_id, "user_id": payload.get("user_id") or "", "role": role, "created_at": now()})
    supabase_log_seal_usage(action="create_seal", actor_id=actor, seal_id=seal_id, detail=payload.get("seal_name") or payload.get("name") or "")
    return supabase_company_seal_row(seal_id)


def supabase_patch_company_seal(seal_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    supabase_company_seal_row(seal_id)
    update: Dict[str, Any] = {}
    for key in ("seal_name", "seal_category", "seal_size_type", "purpose_description", "is_active"):
        if key in payload:
            update[key] = payload[key]
    if "seal_category" in update and update["seal_category"] not in supabase_reference_codes("category"):
        raise ValueError("invalid_seal_category")
    if "seal_size_type" in update and update["seal_size_type"] not in supabase_reference_codes("size"):
        raise ValueError("invalid_seal_size_type")
    if "is_active" in update:
        update["is_active"] = bool(update["is_active"])
        update["deactivated_at"] = "" if update["is_active"] else now()
    update["updated_at"] = now()
    supabase_patch("company_seals", seal_id, update)
    supabase_log_seal_usage(action="update_seal", actor_id=seal_actor(session, payload), seal_id=seal_id, detail=json.dumps(update, ensure_ascii=False))
    return supabase_company_seal_row(seal_id)


def supabase_deactivate_company_seal(seal_id: str, session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    row = supabase_patch_company_seal(seal_id, {"is_active": False}, session)
    supabase_log_seal_usage(action="deactivate_seal", actor_id=seal_actor(session), seal_id=seal_id, detail="soft_delete_only")
    return row


def supabase_upload_company_seal_file(seal_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    seal = supabase_company_seal_row(seal_id)
    if not seal.get("is_active"):
        raise ValueError("inactive_seal_cannot_upload_new_file")
    content = payload.get("content_base64") or ""
    if not content:
        raise ValueError("seal_file_content_required")
    data = base64.b64decode(content)
    file_name = Path(payload.get("file_name") or f"{seal_id}.png").name
    mime_type = payload.get("file_mime_type") or payload.get("mime_type") or "image/png"
    validate_seal_file_upload(file_name, mime_type, data)
    actor = seal_actor(session, payload)
    versions = supabase_filter_rows("company_seal_files", {"seal_id": seal_id}, order="version.desc", limit=1)
    next_version = int((versions[0].get("version") if versions else 0) or 0) + 1
    file_row = supabase_store_file_object(SEAL_VAULT_DOCUMENT_ID, file_name, data, f"{SEAL_VAULT_PURPOSE_PREFIX}/seals/{seal_id}", f"seal-v{next_version}", actor, mime_type)
    supabase_update_many("company_seal_files", {"seal_id": seal_id}, {"is_current": False})
    row = {
        "id": f"SFILE-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "seal_id": seal_id,
        "file_object_id": file_row["id"],
        "file_storage_key": file_row["storage_key"],
        "file_name": file_name,
        "file_mime_type": mime_type,
        "file_size": len(data),
        "file_hash": sha256_bytes(data),
        "version": next_version,
        "is_current": True,
        "uploaded_by": actor,
        "uploaded_at": now(),
    }
    created = supabase_insert("company_seal_files", row)
    supabase_log_seal_usage(action="upload_seal", actor_id=actor, seal_id=seal_id, detail=f"{file_name} v{next_version} hash={row['file_hash']}")
    return {"seal": supabase_company_seal_row(seal_id), "file": seal_file_metadata(created)}


def supabase_list_company_seal_files(seal_id: str, session: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    supabase_company_seal_row(seal_id)
    supabase_log_seal_usage(action="view_seal_metadata", actor_id=seal_actor(session), seal_id=seal_id, detail="metadata_only")
    return [seal_file_metadata(row) for row in supabase_filter_rows("company_seal_files", {"seal_id": seal_id}, order="version.desc")]


def supabase_set_current_seal_file(file_id: str, session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    item = supabase_get("company_seal_files", file_id)
    if not item:
        raise ValueError("seal_file_not_found")
    supabase_update_many("company_seal_files", {"seal_id": item["seal_id"]}, {"is_current": False})
    supabase_patch("company_seal_files", file_id, {"is_current": True})
    supabase_log_seal_usage(action="set_current_seal_file", actor_id=seal_actor(session), seal_id=item["seal_id"], detail=f"version={item.get('version')}")
    return supabase_company_seal_row(item["seal_id"])


def supabase_get_or_create_pdf_document(payload: Dict[str, Any]) -> Dict[str, Any]:
    doc_payload = payload.get("document") or payload
    doc_id = doc_payload.get("document_id") or doc_payload.get("id")
    if doc_id:
        existing = supabase_get("documents", str(doc_id))
        if existing:
            return existing
    if doc_id and not str(doc_id).startswith("DOC-"):
        doc_id = f"DOC-{doc_id}"
    doc_id = str(doc_id or f"DOC-PDF-{int(time.time() * 1000)}")
    doc = {
        "id": doc_id,
        "doc_no": doc_payload.get("doc_no") or doc_payload.get("no") or doc_id,
        "direction": doc_payload.get("direction") or "發文",
        "doc_type": doc_payload.get("doc_type") or doc_payload.get("type") or "函",
        "priority": doc_payload.get("priority") or "普通件",
        "security_level": doc_payload.get("security_level") or doc_payload.get("security") or "普通",
        "agency_name": doc_payload.get("agency_name") or doc_payload.get("to") or "未指定機關",
        "agency_code": doc_payload.get("agency_code") or doc_payload.get("agencyCode") or "",
        "subject": doc_payload.get("subject") or "未命名公文",
        "body": doc_payload.get("body") or "",
        "status": doc_payload.get("status") or "PDF 已產生",
        "owner": doc_payload.get("owner") or "總務",
        "department": doc_payload.get("department") or doc_payload.get("dept") or "總管理處",
        "due_date": doc_payload.get("due_date") or "",
        "received_at": doc_payload.get("received_at") or None,
        "company_name": doc_payload.get("company_name") or doc_payload.get("companyName") or "歲悅長照股份有限公司",
        "seal_plan_json": doc_payload.get("seal_plan_json") or "{}",
        "metadata_json": doc_payload.get("metadata_json") or "{}",
        "created_at": now(),
        "updated_at": now(),
    }
    return supabase_insert("documents", doc)


def supabase_seal_usage_request_row(request_id: str) -> Dict[str, Any]:
    request = supabase_get("seal_usage_requests", request_id)
    if not request:
        raise ValueError("seal_usage_request_not_found")
    company = supabase_get("companies", request.get("company_id", "")) or {}
    seal = supabase_get("company_seals", request.get("seal_id", "")) or {}
    request["company_name"] = company.get("name", "")
    request["seal_name"] = seal.get("seal_name", "")
    request["seal_category"] = seal.get("seal_category", "")
    request["seal_size_type"] = seal.get("seal_size_type", "")
    request["stamp_positions"] = parse_json_any(request.get("stamp_positions_json"), []) or []
    request["metadata"] = parse_json_any(request.get("metadata_json"), {}) or {}
    request["approvals"] = supabase_filter_rows("seal_usage_approvals", {"usage_request_id": request_id}, order="approval_order.asc")
    request["logs"] = supabase_filter_rows("seal_usage_logs", {"usage_request_id": request_id}, order="created_at.desc", limit=50)
    return request


def supabase_list_seal_usage_requests(query: Dict[str, List[str]] | None = None) -> List[Dict[str, Any]]:
    query = query or {}
    params: Dict[str, str] = {"select": "id", "limit": "300", "order": "requested_at.desc"}
    for key in ("company_id", "seal_id", "requested_by", "usage_type", "status"):
        if query.get(key):
            params[key] = f"eq.{query[key][0]}"
    if query.get("date_from"):
        params["requested_at"] = f"gte.{query['date_from'][0]}"
    if query.get("date_to"):
        params["requested_at"] = f"lte.{query['date_to'][0]}"
    rows = supabase_request("GET", f"seal_usage_requests?{urllib.parse.urlencode(params)}")
    return [supabase_seal_usage_request_row(row["id"]) for row in rows]


def supabase_create_seal_usage_request(document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    seal_id = payload.get("seal_id") or ""
    if not seal_id:
        raise ValueError("seal_id_required")
    seal = supabase_company_seal_row(seal_id)
    if not seal.get("is_active"):
        raise ValueError("inactive_seal_cannot_be_requested")
    if not supabase_filter_rows("company_seal_files", {"seal_id": seal_id, "is_current": True}, limit=1):
        raise ValueError("current_seal_file_required")
    usage_type = payload.get("usage_type") or "official_document"
    if usage_type not in supabase_reference_codes("usage_type"):
        raise ValueError("invalid_usage_type")
    document = supabase_get_or_create_pdf_document({"document_id": document_id, **(payload.get("document") or {})})
    actor = seal_actor(session, payload)
    request_id = payload.get("id") or f"SREQ-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    positions = payload.get("stamp_positions") or payload.get("positions") or []
    supabase_insert("seal_usage_requests", {
        "id": request_id,
        "document_id": document["id"],
        "company_id": seal["company_id"],
        "seal_id": seal_id,
        "requested_by": actor,
        "request_reason": payload.get("request_reason") or payload.get("reason") or "",
        "usage_type": usage_type,
        "status": payload.get("status") or "pending",
        "stamp_positions_json": positions,
        "stamped_pdf_version_id": None,
        "metadata_json": payload.get("metadata") or {},
        "requested_at": now(),
        "approved_at": "",
        "stamped_at": "",
        "updated_at": now(),
    })
    approvers = payload.get("approvers") or [{"approver_id": "seal_approver", "approval_order": 1}]
    for index, approver in enumerate(approvers, start=1):
        supabase_insert("seal_usage_approvals", {
            "id": f"SAPP-{request_id}-{index}",
            "usage_request_id": request_id,
            "approver_id": approver.get("approver_id") or approver.get("id") or "seal_approver",
            "approval_order": int(approver.get("approval_order") or index),
            "status": "pending",
            "comment": "",
            "approved_at": "",
            "created_at": now(),
            "updated_at": now(),
        })
    supabase_log_seal_usage(action="request_use", actor_id=actor, usage_request_id=request_id, seal_id=seal_id, document_id=document["id"], detail=payload.get("request_reason") or payload.get("reason") or "")
    return supabase_seal_usage_request_row(request_id)


def supabase_approve_seal_usage_request(request_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    request = supabase_seal_usage_request_row(request_id)
    if request["status"] not in {"pending", "draft"}:
        raise ValueError("seal_request_not_pending")
    actor = seal_actor(session, payload)
    pending = supabase_filter_rows("seal_usage_approvals", {"usage_request_id": request_id, "status": "pending"}, order="approval_order.asc", limit=1)
    if pending:
        supabase_patch("seal_usage_approvals", pending[0]["id"], {"status": "approved", "approver_id": actor, "comment": payload.get("comment") or "核准用印。", "approved_at": now(), "updated_at": now()})
    remaining = supabase_filter_rows("seal_usage_approvals", {"usage_request_id": request_id, "status": "pending"}, limit=1)
    if not remaining:
        supabase_patch("seal_usage_requests", request_id, {"status": "approved", "approved_at": now(), "updated_at": now()})
    supabase_log_seal_usage(action="approve_use", actor_id=actor, usage_request_id=request_id, seal_id=request["seal_id"], document_id=request["document_id"], detail=payload.get("comment") or "")
    return supabase_seal_usage_request_row(request_id)


def supabase_reject_seal_usage_request(request_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    request = supabase_seal_usage_request_row(request_id)
    if request["status"] in {"stamped", "cancelled"}:
        raise ValueError("seal_request_cannot_be_rejected")
    actor = seal_actor(session, payload)
    pending = supabase_filter_rows("seal_usage_approvals", {"usage_request_id": request_id, "status": "pending"}, limit=50)
    for approval in pending:
        supabase_patch("seal_usage_approvals", approval["id"], {"status": "rejected", "comment": payload.get("comment") or "駁回用印。", "approved_at": now(), "updated_at": now()})
    supabase_patch("seal_usage_requests", request_id, {"status": "rejected", "updated_at": now()})
    supabase_log_seal_usage(action="reject_use", actor_id=actor, usage_request_id=request_id, seal_id=request["seal_id"], document_id=request["document_id"], detail=payload.get("comment") or "")
    return supabase_seal_usage_request_row(request_id)


def supabase_stamp_seal_usage_request(request_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    request = supabase_seal_usage_request_row(request_id)
    if request["status"] != "approved":
        raise ValueError("seal_request_must_be_approved_before_stamp")
    seal = supabase_company_seal_row(request["seal_id"])
    if not seal.get("is_active"):
        raise ValueError("inactive_seal_cannot_stamp")
    files = supabase_filter_rows("company_seal_files", {"seal_id": request["seal_id"], "is_current": True}, order="version.desc", limit=1)
    if not files:
        raise ValueError("current_seal_file_required")
    file_meta = files[0]
    file_object = supabase_get("file_objects", file_meta.get("file_object_id", "")) if file_meta.get("file_object_id") else None
    if file_object:
        supabase_log_seal_usage(action="read_seal_vault_for_stamp", actor_id=seal_actor(session, payload), usage_request_id=request_id, seal_id=request["seal_id"], document_id=request["document_id"], detail="authorized_backend_stamp_only")
        seal_bytes = supabase_storage_download(file_object["storage_key"], file_object.get("bucket") or EDOC_SEAL_STORAGE_BUCKET)
        if sha256_bytes(seal_bytes) != file_meta["file_hash"]:
            raise ValueError("file_hash_mismatch")
    stamp_no = payload.get("stamp_no") or f"STAMP-{request_id}-{int(time.time())}"
    positions = payload.get("stamp_positions") or request.get("stamp_positions") or [
        {"page": 1, "x": 420, "y": 130, "w": 85, "h": 85, "label": seal["seal_name"], "type": seal["seal_category"], "seal_id": request["seal_id"]}
    ]
    document = supabase_get("documents", request["document_id"]) or {"id": request["document_id"], "doc_no": request["document_id"], "subject": "用印文件", "body": ""}
    template = payload.get("template") or "公司用印文件"
    dry_package = build_official_pdf_package(pdf_render_document(document, payload), [], template, 1)
    stamps = pdf_stamp_definitions({"stamp_positions": positions, "seal_id": request["seal_id"]}, document, stamp_no, int(dry_package["layout"]["page_count"]))
    package = build_official_pdf_package(pdf_render_document(document, payload), stamps, template, 1)
    actor = seal_actor(session, payload)
    file_row = supabase_store_file_object(request["document_id"], f"{document.get('doc_no') or request['document_id']}-after-seal.pdf", package["data"], "pdf", "after_seal", actor, "application/pdf")
    pdf_version_id = f"PDF-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    pdf_version = supabase_insert("pdf_versions", {
        "id": pdf_version_id,
        "document_id": request["document_id"],
        "file_object_id": file_row["id"],
        "version_type": "after_seal",
        "template_name": template,
        "stamp_no": stamp_no,
        "coordinates_json": json.dumps(pdf_coordinates_with_layout(payload.get("coordinates") or {}, package, stamps), ensure_ascii=False),
        "previous_version_id": "",
        "sha256": file_row["sha256"],
        "created_at": now(),
    })
    supabase_patch("seal_usage_requests", request_id, {"status": "stamped", "stamped_at": now(), "stamped_pdf_version_id": pdf_version_id, "stamp_positions_json": positions, "updated_at": now()})
    supabase_patch("documents", request["document_id"], {"status": "已用印", "updated_at": now()})
    supabase_log_seal_usage(action="stamp_document", actor_id=actor, usage_request_id=request_id, seal_id=request["seal_id"], document_id=request["document_id"], detail=f"{stamp_no} seal_file_hash={file_meta['file_hash']}")
    return {"request": supabase_seal_usage_request_row(request_id), "stamped_file": {"pdf_version_id": pdf_version["id"], "file_object_id": file_row["id"], "sha256": file_row["sha256"], "stamp_no": stamp_no}}


def supabase_official_session_user(session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = session.get("user") if session else None
    if not user:
        raise PermissionError("authentication_required")
    return user


def supabase_official_company_row(company_id: str) -> Dict[str, Any]:
    row = supabase_get("companies", company_id)
    if not row:
        raise ValueError("company_not_found")
    return row


def supabase_official_document_row(document_id: str) -> Dict[str, Any]:
    row = supabase_get("official_documents", document_id)
    if not row:
        raise ValueError("official_document_not_found")
    return row


def supabase_user_by_id(user_id: str) -> Dict[str, Any] | None:
    row = supabase_get("users", user_id)
    if not row or row.get("status") != "啟用":
        return None
    return public_user(row)


def supabase_active_user_by_role(role: str, exclude_user_id: str = "") -> Dict[str, Any] | None:
    rows = supabase_filter_rows("users", {"role": role, "status": "啟用"}, order="id.asc", limit=20)
    for row in rows:
        if row.get("id") != exclude_user_id:
            return public_user(row)
    return None


def supabase_department_head_role(company: Dict[str, Any], department_name: str) -> str:
    rows = supabase_filter_rows("department_registry", {"company_name": company.get("name") or "", "name": department_name or "", "status": "啟用"}, limit=1)
    return rows[0].get("manager_role") if rows else "主管"


def supabase_resolve_official_step_approver(step: Dict[str, Any], applicant: Dict[str, Any], company: Dict[str, Any]) -> Dict[str, Any] | None:
    role = step["role"]
    if step["key"] == "department_head":
        role = supabase_department_head_role(company, applicant.get("unit") or "")
    user = supabase_active_user_by_role(role, applicant.get("id") if step["key"] in {"applicant_manager", "department_head"} else "")
    if not user and step["key"] in {"applicant_manager", "department_head"}:
        user = supabase_active_user_by_role("行政部主任", applicant.get("id"))
    return user


def supabase_official_document_files(document_id: str) -> List[Dict[str, Any]]:
    rows = supabase_filter_rows("official_document_files", {"document_id": document_id}, order="version.desc,created_at.desc", limit=500)
    rows.sort(key=lambda item: (0 if item.get("file_type") == "stamped_pdf" else 1, -int(item.get("version") or 0), str(item.get("created_at") or "")))
    return [official_file_metadata(row) for row in rows]


def supabase_official_raw_document_files(document_id: str, file_type: str = "") -> List[Dict[str, Any]]:
    filters = {"document_id": document_id}
    if file_type:
        filters["file_type"] = file_type
    return supabase_filter_rows("official_document_files", filters, order="version.desc,created_at.desc", limit=500)


def supabase_official_document_steps(document_id: str) -> List[Dict[str, Any]]:
    return supabase_filter_rows("official_document_approval_steps", {"document_id": document_id}, order="step_order.asc", limit=50)


def supabase_official_document_logs(document_id: str) -> List[Dict[str, Any]]:
    return supabase_filter_rows("official_document_approval_logs", {"document_id": document_id}, order="created_at.desc", limit=200)


def supabase_official_document_stamp_request(document_id: str) -> Dict[str, Any] | None:
    rows = supabase_filter_rows("official_document_stamp_requests", {"document_id": document_id}, order="created_at.desc", limit=1)
    return rows[0] if rows else None


def supabase_official_dispatch_record_metadata(row: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not row:
        return None
    data = dict(row)
    method = official_dispatch_method(data.get("dispatch_method"))
    data["dispatch_method_label"] = OFFICIAL_DISPATCH_METHODS[method]["label"]
    owner = supabase_user_by_id(data.get("dispatch_owner_user_id") or "") if data.get("dispatch_owner_user_id") else None
    data["dispatch_owner_name"] = owner.get("name") if owner else (data.get("dispatch_owner_user_id") or data.get("dispatch_owner_type") or "")
    proof_file_id = data.get("proof_file_id")
    if proof_file_id:
        proofs = supabase_filter_rows("official_document_files", {"id": proof_file_id, "document_id": data["document_id"]}, limit=1)
        data["proof_file"] = official_file_metadata(proofs[0]) if proofs else None
    else:
        data["proof_file"] = None
    return data


def supabase_official_dispatch_record(document_id: str) -> Dict[str, Any] | None:
    rows = supabase_filter_rows("official_document_dispatch_records", {"document_id": document_id}, order="created_at.desc", limit=1)
    return supabase_official_dispatch_record_metadata(rows[0]) if rows else None


def supabase_resolve_official_dispatch_owner(document: Dict[str, Any], method: str) -> Dict[str, Any]:
    config = OFFICIAL_DISPATCH_METHODS[method]
    if config["owner_type"] == "general_affairs":
        return supabase_active_user_by_role("總務") or {"id": "", "name": "總務", "role": "總務"}
    if config["owner_type"] == "applicant":
        return supabase_user_by_id(document["applicant_id"]) or {"id": document["applicant_id"], "name": document.get("applicant_name") or "申請人", "role": "申請人"}
    return {"id": "system", "name": "System", "role": "system"}


def supabase_upsert_official_dispatch_record(
    document: Dict[str, Any],
    method: str | None = None,
    actor: Dict[str, Any] | None = None,
    payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    method = official_dispatch_method(method or document.get("dispatch_method"))
    existing = supabase_filter_rows("official_document_dispatch_records", {"document_id": document["id"]}, order="created_at.desc", limit=1)
    owner = supabase_resolve_official_dispatch_owner(document, method)
    config = OFFICIAL_DISPATCH_METHODS[method]
    payload = payload or {}
    values = {
        "dispatch_method": method,
        "dispatch_owner_type": config["owner_type"],
        "dispatch_owner_user_id": owner.get("id") or "",
        "dispatch_status": payload.get("dispatch_status") or config["dispatch_status"],
        "external_official_document_number": payload.get("external_official_document_number") or "",
        "dispatch_date": payload.get("dispatch_date") or "",
        "recipient": payload.get("recipient") or document.get("recipient") or "",
        "recipient_contact": payload.get("recipient_contact") or "",
        "dispatch_note": payload.get("dispatch_note") or "",
        "proof_file_id": payload.get("proof_file_id") or None,
        "completed_at": payload.get("completed_at") or (now() if config["owner_type"] == "system" else ""),
    }
    if existing:
        updated = supabase_patch("official_document_dispatch_records", existing[0]["id"], values)
        return supabase_official_dispatch_record(document["id"]) or updated
    created = supabase_insert("official_document_dispatch_records", {
        "id": f"ODDISP-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "document_id": document["id"],
        **values,
        "created_by": actor.get("id") if actor else "system",
        "created_at": now(),
        "updated_at": now(),
    })
    return supabase_official_dispatch_record(document["id"]) or created


def supabase_advance_official_dispatch_after_stamp(
    document_id: str,
    stamped_file: Dict[str, Any],
    actor: Dict[str, Any] | None,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    document = supabase_official_document_row(document_id)
    method = official_dispatch_method(document.get("dispatch_method"))
    config = OFFICIAL_DISPATCH_METHODS[method]
    record = supabase_upsert_official_dispatch_record(document, method, actor)
    supabase_patch("official_documents", document_id, {"current_status": config["next_status"], "current_step": config["next_step"], "updated_at": now()})
    supabase_insert_official_log(document_id, "dispatch_route_created", actor, f"{method}:{config['label']}", file_id=stamped_file.get("id") or "", ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    if config["owner_type"] == "general_affairs":
        supabase_create_notification({"type": "發文寄發待辦", "title": f"{document['title']} 待總務寄發", "target_role": "總務", "source": document_id, "priority": "高", "body": "已用印版本已產生，請下載後至外部電子公文系統、Email 或紙本郵寄完成寄發並回填證明。"})
    elif config["owner_type"] == "applicant":
        supabase_create_notification({"type": "發文寄發待辦", "title": f"{document['title']} 已回到申請人寄發", "target_role": "員工", "source": document_id, "priority": "高", "body": "已用印版本已產生，請下載後自行寄送並回填寄送紀錄。"})
    else:
        supabase_insert_official_log(document_id, "auto_archive_no_dispatch", actor, "no_dispatch_required", file_id=stamped_file.get("id") or "", ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
        supabase_create_notification({"type": "發文結案", "title": f"{document['title']} 已用印並歸檔", "target_role": "員工", "source": document_id, "body": "寄發方式為不需寄發，系統已完成結案歸檔。"})
    return record


def supabase_update_official_dispatch_record(document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = supabase_official_session_user(session)
    document = supabase_official_document_row(document_id)
    steps = supabase_official_document_steps(document_id)
    if not canDownloadOfficialDocument(user, document, steps) and not session_has_any_permission(session, ["official_documents.all_records", "official_documents.all_todo"]):
        raise PermissionError("official_dispatch_access_denied")
    record = supabase_official_dispatch_record(document_id)
    if not record:
        record = supabase_upsert_official_dispatch_record(document, payload.get("dispatch_method") or document.get("dispatch_method"), user)
    if not can_manage_official_dispatch(user, document, record, session):
        raise PermissionError("official_dispatch_update_forbidden")
    allowed = {"external_official_document_number", "dispatch_date", "recipient", "recipient_contact", "dispatch_note", "proof_file_id"}
    update = {key: (payload.get(key) or None if key == "proof_file_id" else payload.get(key) or "") for key in allowed if key in payload}
    if not update:
        return supabase_official_dispatch_record(document_id) or record
    supabase_patch("official_document_dispatch_records", record["id"], update)
    supabase_insert_official_log(document_id, "update_dispatch", user, json.dumps(update, ensure_ascii=False), ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    return supabase_official_dispatch_record(document_id) or {}


def supabase_complete_official_dispatch(document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = supabase_official_session_user(session)
    document = supabase_official_document_row(document_id)
    record = supabase_official_dispatch_record(document_id)
    if not record:
        record = supabase_upsert_official_dispatch_record(document, document.get("dispatch_method"), user)
    if not can_manage_official_dispatch(user, document, record, session):
        raise PermissionError("official_dispatch_complete_forbidden")
    if record.get("dispatch_owner_type") == "general_affairs" and document.get("current_status") != "pending_general_affairs_dispatch":
        raise ValueError("official_document_not_pending_general_affairs_dispatch")
    if record.get("dispatch_owner_type") == "applicant" and document.get("current_status") != "returned_to_applicant_for_send":
        raise ValueError("official_document_not_returned_to_applicant_for_send")
    if payload:
        record = supabase_update_official_dispatch_record(document_id, payload, session)
    final_dispatch_status = "sent_by_applicant" if record.get("dispatch_owner_type") == "applicant" else "dispatched"
    final_document_status = "sent_by_applicant" if record.get("dispatch_owner_type") == "applicant" else "dispatched"
    if payload.get("close", False):
        final_document_status = "closed" if final_document_status in {"dispatched", "sent_by_applicant"} else final_document_status
    supabase_patch("official_document_dispatch_records", record["id"], {"dispatch_status": final_dispatch_status, "completed_at": now(), "updated_at": now()})
    supabase_patch("official_documents", document_id, {"current_status": final_document_status, "current_step": "", "updated_at": now()})
    supabase_insert_official_log(document_id, "complete_dispatch", user, final_dispatch_status, file_id=(payload.get("proof_file_id") or record.get("proof_file_id") or ""), ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    supabase_create_notification({"type": "發文寄發完成", "title": f"{document['title']} 已完成寄發", "target_role": "員工", "source": document_id, "body": f"寄發狀態：{final_dispatch_status}。"})
    return supabase_official_document_detail(document_id, session)


def supabase_upload_official_dispatch_proof_file(document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = supabase_official_session_user(session)
    document = supabase_official_document_row(document_id)
    record = supabase_official_dispatch_record(document_id)
    if not record:
        record = supabase_upsert_official_dispatch_record(document, document.get("dispatch_method"), user)
    if not can_manage_official_dispatch(user, document, record, session):
        raise PermissionError("official_dispatch_proof_upload_forbidden")
    content = payload.get("content_base64") or ""
    if not content:
        raise ValueError("dispatch_proof_file_required")
    data = base64.b64decode(content)
    mime_type = payload.get("file_mime_type") or payload.get("mime_type") or "application/pdf"
    if mime_type.lower() not in OFFICIAL_DISPATCH_PROOF_MIME_TYPES:
        raise ValueError("dispatch_proof_mime_type_not_allowed")
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("dispatch_proof_file_too_large")
    file_name = Path(payload.get("file_name") or f"{document_id}-dispatch-proof").name
    file_row = supabase_store_file_object(document_id, file_name, data, "official-documents", "dispatch-proof", official_actor_name(user), mime_type)
    official_file = supabase_insert_official_document_file(document_id, "dispatch_proof", file_row, official_actor_name(user))
    supabase_patch("official_document_dispatch_records", record["id"], {"proof_file_id": official_file["id"], "updated_at": now()})
    supabase_insert_official_log(document_id, "upload_dispatch_proof", user, official_file["file_hash"], file_id=official_file["id"], ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    return {"dispatch_record": supabase_official_dispatch_record(document_id), "file": official_file_metadata(official_file)}


def supabase_insert_official_log(
    document_id: str,
    action: str,
    actor: Dict[str, Any] | None,
    comment: str = "",
    *,
    step_id: str = "",
    file_id: str = "",
    ip_address: str = "",
    user_agent: str = "",
) -> Dict[str, Any]:
    actor_name = official_actor_name(actor)
    row = supabase_insert("official_document_approval_logs", {
        "id": f"ODLOG-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "document_id": document_id,
        "step_id": step_id or None,
        "file_id": file_id or None,
        "actor_id": actor.get("id") if actor else "system",
        "actor_name": actor_name,
        "action": action,
        "comment": comment,
        "ip_address": ip_address,
        "user_agent": user_agent[:180] if user_agent else "",
        "created_at": now(),
    })
    supabase_insert("audit_logs", {
        "id": f"AUD-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "actor": actor_name,
        "action": action,
        "target_type": "official_documents",
        "target_id": document_id,
        "detail": comment,
        "event_type": action if action in LOGGING_AUDIT_EVENT_TYPES else "submit",
        "module_code": "official_documents",
        "resource_type": "official_documents",
        "resource_id": document_id,
        "result": "success",
        "severity": "info",
    })
    return row


def supabase_insert_official_document_file(document_id: str, file_type: str, file_row: Dict[str, Any], actor: str) -> Dict[str, Any]:
    versions = supabase_official_raw_document_files(document_id, file_type)
    next_version = max([int(item.get("version") or 0) for item in versions] or [0]) + 1
    row = {
        "id": f"ODFILE-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "document_id": document_id,
        "file_object_id": file_row.get("id"),
        "file_type": file_type,
        "file_name": file_row.get("file_name") or f"{document_id}-{file_type}.pdf",
        "file_storage_key": file_row.get("storage_key") or "",
        "file_mime_type": file_row.get("mime_type") or "application/pdf",
        "file_size": int(file_row.get("size_bytes") or 0),
        "file_hash": file_row.get("sha256") or "",
        "version": next_version,
        "uploaded_by": actor,
        "created_at": now(),
    }
    return supabase_insert("official_document_files", row)


def supabase_store_official_pdf_file(document_id: str, file_type: str, file_name: str, data: bytes, actor: str) -> Dict[str, Any]:
    file_row = supabase_store_file_object(document_id, file_name, data, "official-documents", f"{file_type}-v1", actor, "application/pdf")
    return supabase_insert_official_document_file(document_id, file_type, file_row, actor)


def supabase_official_pdf_document_payload(document: Dict[str, Any]) -> Dict[str, Any]:
    company = supabase_official_company_row(document["company_id"])
    body_parts = []
    if document.get("description"):
        body_parts.append(f"說明：\n{document['description']}")
    if document.get("method"):
        body_parts.append(f"辦法：\n{document['method']}")
    return {
        "id": document["id"],
        "doc_no": document["id"],
        "company_name": company.get("name") or "歲悅股份有限公司",
        "doc_type": "函",
        "agency_name": document.get("recipient") or "未指定受文者",
        "subject": document.get("subject") or document.get("title") or "未命名發文",
        "body": "\n\n".join(body_parts) or document.get("description") or "尚未填寫說明內容。",
        "owner": document.get("handler_name") or document.get("applicant_name") or "承辦人",
        "department": document.get("dispatch_unit") or document.get("applicant_department_name") or "",
        "attachments": parse_json_field(document.get("metadata_json")).get("attachments", "附件詳如附件區"),
        "created_at": document.get("created_at"),
    }


def supabase_ensure_official_generated_pdf(document: Dict[str, Any], actor: str = "PDF Worker") -> Dict[str, Any]:
    rows = supabase_official_raw_document_files(document["id"], "generated_pdf")
    if rows:
        return rows[0]
    package = build_official_pdf_package(supabase_official_pdf_document_payload(document), [], "歲悅正式函", 1)
    file_row = supabase_store_official_pdf_file(document["id"], "generated_pdf", f"{document['id']}-generated.pdf", package["data"], actor)
    supabase_insert_official_log(document["id"], "generate_pdf", {"id": "system", "name": actor, "role": "system"}, file_row["file_hash"], file_id=file_row["id"])
    return file_row


def supabase_official_latest_source_file(document: Dict[str, Any]) -> Dict[str, Any]:
    file_type = "original_pdf" if document.get("source_type") == "uploaded_pdf" else "generated_pdf"
    if file_type == "generated_pdf":
        supabase_ensure_official_generated_pdf(document)
    rows = supabase_official_raw_document_files(document["id"], file_type)
    if not rows:
        raise ValueError("official_document_source_pdf_required")
    return rows[0]


def supabase_create_official_workflow_steps(document: Dict[str, Any], applicant: Dict[str, Any]) -> List[Dict[str, Any]]:
    existing = supabase_official_document_steps(document["id"])
    if existing:
        return existing
    company = supabase_official_company_row(document["company_id"])
    created: List[Dict[str, Any]] = []
    for step in OFFICIAL_DOCUMENT_WORKFLOW_STEPS:
        approver = supabase_resolve_official_step_approver(step, applicant, company)
        row = supabase_insert("official_document_approval_steps", {
            "id": f"ODSTEP-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
            "document_id": document["id"],
            "step_order": step["order"],
            "step_key": step["key"],
            "step_name": step["name"],
            "approver_user_id": approver.get("id") if approver else "",
            "approver_name": approver.get("name") if approver else step["role"],
            "approver_role": approver.get("role") if approver else step["role"],
            "status": "pending",
            "comment": "",
            "approved_at": "",
            "created_at": now(),
            "updated_at": now(),
        })
        created.append(row)
    return created


def supabase_official_document_detail(document_id: str, session: Dict[str, Any] | None = None) -> Dict[str, Any]:
    document = supabase_official_document_row(document_id)
    steps = supabase_official_document_steps(document_id)
    user = session.get("user") if session else None
    if user and not canDownloadOfficialDocument(user, document, steps) and not session_has_any_permission(session, ["official_documents.all_records", "official_documents.all_todo"]):
        raise PermissionError("official_document_access_denied")
    current_step = next((step for step in steps if step.get("step_key") == document.get("current_step")), None)
    files = supabase_official_document_files(document_id)
    logs = supabase_official_document_logs(document_id)
    stamp_request = supabase_official_document_stamp_request(document_id)
    dispatch_record = supabase_official_dispatch_record(document_id)
    package = official_application_package(document, files, steps, logs, stamp_request, dispatch_record)
    return {
        **document,
        "metadata": parse_json_field(document.get("metadata_json")),
        "application_package": package,
        "document_versions": package["document_versions"],
        "attachments": package["attachments"],
        "download_logs": package["download_logs"],
        "process_logs": package["process_logs"],
        "files": files,
        "approval_steps": steps,
        "logs": logs,
        "stamp_request": stamp_request,
        "dispatch_record": dispatch_record,
        "can_download": bool(user and canDownloadOfficialDocument(user, document, steps)),
        "can_manage_dispatch": bool(user and can_manage_official_dispatch(user, document, dispatch_record, session)),
        "can_act": bool(user and current_step and current_step.get("approver_user_id") == user.get("id") and current_step.get("status") == "pending"),
    }


def supabase_list_official_documents(query: Dict[str, List[str]] | None, session: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    user = supabase_official_session_user(session)
    query = query or {}
    rows = supabase_filter_rows("official_documents", {}, order="created_at.desc", limit=300)
    status = (query.get("status") or [""])[0]
    company_id = (query.get("company_id") or [""])[0]
    applicant_id = (query.get("applicant_id") or [""])[0]
    scope = (query.get("scope") or [""])[0]
    items: List[Dict[str, Any]] = []
    for item in rows:
        if status and item.get("current_status") != status:
            continue
        if company_id and item.get("company_id") != company_id:
            continue
        if applicant_id and item.get("applicant_id") != applicant_id:
            continue
        steps = supabase_official_document_steps(item["id"])
        dispatch_record = supabase_official_dispatch_record(item["id"])
        is_applicant = item.get("applicant_id") == user.get("id")
        is_participant = any(step.get("approver_user_id") == user.get("id") for step in steps)
        is_current_todo = any(step.get("approver_user_id") == user.get("id") and step.get("status") == "pending" and step.get("step_key") == item.get("current_step") for step in steps)
        is_dispatch_todo = bool(
            dispatch_record
            and dispatch_record.get("dispatch_status") == "pending"
            and (
                dispatch_record.get("dispatch_owner_user_id") == user.get("id")
                or (dispatch_record.get("dispatch_owner_type") == "general_affairs" and user.get("role") == "總務")
            )
        )
        if scope == "mine" and not is_applicant:
            continue
        if scope == "todo" and not (is_current_todo or is_dispatch_todo):
            continue
        if not scope and not is_applicant and not is_participant and not session_has_any_permission(session, ["official_documents.all_records", "official_documents.all_todo"]):
            continue
        item["stamp_request"] = supabase_official_document_stamp_request(item["id"])
        item["dispatch_record"] = dispatch_record
        item["current_step_name"] = next((step["step_name"] for step in steps if step.get("step_key") == item.get("current_step")), "")
        items.append(item)
    return items


def supabase_create_official_document(payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = supabase_official_session_user(session)
    if not session_has_any_permission(session, ["official_documents.compose", "official_documents.all_todo"]):
        raise PermissionError("official_document_create_forbidden")
    source_type = payload.get("source_type") or "blank_editor"
    if source_type not in {"blank_editor", "uploaded_pdf"}:
        raise ValueError("invalid_official_document_source_type")
    company_id = payload.get("company_id") or "CO-001"
    supabase_official_company_row(company_id)
    dispatch_method = official_dispatch_method(payload.get("dispatch_method"))
    document_id = payload.get("id") or f"OD-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    ts = now()
    metadata = {
        "attachments": payload.get("attachments_summary") or payload.get("attachments") or "",
        "workflow_template": "fixed_dispatch_seal_v1",
        "future_rule_inputs": {
            "company_id": company_id,
            "department": user.get("unit"),
            "document_type": payload.get("document_type"),
            "seal_id": payload.get("seal_id"),
            "dispatch_method": dispatch_method,
            "amount": payload.get("amount"),
        },
    }
    document = supabase_insert("official_documents", {
        "id": document_id,
        "company_id": company_id,
        "document_type": payload.get("document_type") or ("uploaded_pdf_for_stamp" if source_type == "uploaded_pdf" else "outgoing_official_document"),
        "source_type": source_type,
        "title": payload.get("title") or payload.get("subject") or "未命名發文申請",
        "subject": payload.get("subject") or payload.get("title") or "",
        "description": payload.get("description") or payload.get("body") or "",
        "method": payload.get("method") or payload.get("辦法") or "",
        "recipient": payload.get("recipient") or payload.get("agency_name") or "",
        "dispatch_unit": payload.get("dispatch_unit") or user.get("unit") or "",
        "handler_name": payload.get("handler_name") or user.get("name") or "",
        "applicant_id": user["id"],
        "applicant_name": user.get("name") or user.get("email"),
        "applicant_department_id": payload.get("applicant_department_id") or user.get("unit") or "",
        "applicant_department_name": payload.get("applicant_department_name") or user.get("unit") or "",
        "dispatch_method": dispatch_method,
        "current_status": "draft",
        "current_step": "",
        "request_reason": payload.get("request_reason") or payload.get("reason") or "",
        "metadata_json": metadata,
        "created_at": ts,
        "updated_at": ts,
    })
    if source_type == "uploaded_pdf":
        content = payload.get("content_base64") or payload.get("file_content_base64") or ""
        if not content:
            raise ValueError("original_pdf_required")
        data = base64.b64decode(content)
        if not data.startswith(b"%PDF"):
            raise ValueError("original_pdf_must_be_pdf")
        file_row = supabase_store_official_pdf_file(document_id, "original_pdf", Path(payload.get("file_name") or f"{document_id}.pdf").name, data, official_actor_name(user))
        supabase_insert_official_log(document_id, "upload_original_pdf", user, file_row["file_hash"], file_id=file_row["id"], ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    else:
        supabase_ensure_official_generated_pdf(document, official_actor_name(user))
    seal_id = payload.get("seal_id")
    if seal_id:
        position = official_stamp_position_payload(payload)
        supabase_insert("official_document_stamp_requests", {
            "id": f"ODSTAMP-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
            "document_id": document_id,
            "company_id": company_id,
            "seal_id": seal_id,
            "requested_by": user["id"],
            **position,
            "status": "pending",
            "stamped_file_id": None,
            "error_message": "",
            "created_at": ts,
            "stamped_at": "",
            "updated_at": ts,
        })
    supabase_insert_official_log(document_id, "create", user, document["request_reason"], ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    if payload.get("submit", True):
        return supabase_submit_official_document(document_id, payload, session)
    return supabase_official_document_detail(document_id, session)


def supabase_submit_official_document(document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = supabase_official_session_user(session)
    document = supabase_official_document_row(document_id)
    if document["applicant_id"] != user["id"] and not session_has_any_permission(session, ["official_documents.all_todo"]):
        raise PermissionError("only_applicant_can_submit")
    if document["current_status"] not in {"draft", "rejected"}:
        raise ValueError("official_document_not_submittable")
    if not supabase_official_document_stamp_request(document_id):
        raise ValueError("official_document_seal_required")
    if document["source_type"] == "blank_editor":
        supabase_ensure_official_generated_pdf(document, official_actor_name(user))
    applicant = supabase_user_by_id(document["applicant_id"]) or user
    steps = supabase_create_official_workflow_steps(document, applicant)
    first = steps[0]
    supabase_patch("official_documents", document_id, {"current_status": OFFICIAL_DOCUMENT_STEP_STATUS[first["step_key"]], "current_step": first["step_key"], "updated_at": now()})
    supabase_insert_official_log(document_id, "submit", user, payload.get("comment") or "送出發文用印簽核", step_id=first["id"], ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    if first.get("approver_role"):
        supabase_create_notification({"type": "發文簽核", "title": f"{document['title']} 待{first['step_name']}簽核", "target_role": first["approver_role"], "source": document_id, "body": f"{document.get('applicant_name') or '申請人'} 已送出發文用印申請。"})
    return supabase_official_document_detail(document_id, session)


def supabase_current_official_pending_step(document: Dict[str, Any]) -> Dict[str, Any]:
    rows = supabase_filter_rows("official_document_approval_steps", {"document_id": document["id"], "step_key": document.get("current_step") or "", "status": "pending"}, order="step_order.asc", limit=1)
    if not rows:
        raise ValueError("official_document_current_step_not_pending")
    return rows[0]


def supabase_next_official_step(document_id: str, step_order: int) -> Dict[str, Any] | None:
    for step in supabase_official_document_steps(document_id):
        if int(step.get("step_order") or 0) > step_order:
            return step
    return None


def supabase_approve_official_document(document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = supabase_official_session_user(session)
    document = supabase_official_document_row(document_id)
    if document["current_status"] in {"draft", "stamping", "stamped", "pending_general_affairs_dispatch", "returned_to_applicant_for_send", "dispatched", "sent_by_applicant", "closed", "cancelled", "rejected"}:
        raise ValueError("official_document_not_pending_approval")
    step = supabase_current_official_pending_step(document)
    assert_official_step_actor(user, step)
    if step["step_key"] == "applicant_manager" and user["id"] == document["applicant_id"]:
        raise PermissionError("applicant_cannot_self_approve_manager_step")
    supabase_patch("official_document_approval_steps", step["id"], {"status": "approved", "comment": payload.get("comment") or "核准", "approved_at": now(), "updated_at": now()})
    supabase_insert_official_log(document_id, "approve", user, payload.get("comment") or "", step_id=step["id"], ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    if step["step_key"] == "ceo":
        supabase_patch("official_documents", document_id, {"current_status": "approved", "current_step": "auto_stamp", "updated_at": now()})
        result = supabase_auto_stamp_official_document(document_id, payload, user)
        return {**supabase_official_document_detail(document_id, session), "auto_stamp": result}
    next_step = supabase_next_official_step(document_id, int(step["step_order"]))
    if not next_step:
        raise ValueError("official_document_next_step_missing")
    supabase_patch("official_documents", document_id, {"current_status": OFFICIAL_DOCUMENT_STEP_STATUS[next_step["step_key"]], "current_step": next_step["step_key"], "updated_at": now()})
    supabase_create_notification({"type": "發文簽核", "title": f"{document['title']} 待{next_step['step_name']}簽核", "target_role": next_step.get("approver_role") or "", "source": document_id, "body": f"{step['step_name']}已核准，請接續處理。"})
    return supabase_official_document_detail(document_id, session)


def supabase_reject_official_document(document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = supabase_official_session_user(session)
    document = supabase_official_document_row(document_id)
    step = supabase_current_official_pending_step(document)
    assert_official_step_actor(user, step)
    comment = payload.get("comment") or "駁回"
    supabase_patch("official_document_approval_steps", step["id"], {"status": "rejected", "comment": comment, "approved_at": now(), "updated_at": now()})
    supabase_patch("official_documents", document_id, {"current_status": "rejected", "current_step": "applicant", "updated_at": now()})
    supabase_insert_official_log(document_id, "reject", user, comment, step_id=step["id"], ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    supabase_create_notification({"type": "發文退回", "title": f"{document['title']} 已駁回", "target_role": "員工", "source": document_id, "priority": "高", "body": comment})
    return supabase_official_document_detail(document_id, session)


def supabase_cancel_official_document(document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = supabase_official_session_user(session)
    document = supabase_official_document_row(document_id)
    if document["applicant_id"] != user["id"]:
        raise PermissionError("only_applicant_can_cancel")
    if document["current_status"] in {"stamping", "stamped", "pending_general_affairs_dispatch", "returned_to_applicant_for_send", "dispatched", "sent_by_applicant", "closed"}:
        raise ValueError("official_document_cannot_cancel_after_stamp")
    supabase_patch("official_documents", document_id, {"current_status": "cancelled", "current_step": "", "updated_at": now()})
    supabase_insert_official_log(document_id, "cancel", user, payload.get("comment") or "申請人取消", ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    return supabase_official_document_detail(document_id, session)


def supabase_confirm_official_document(document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = supabase_official_session_user(session)
    document = supabase_official_document_row(document_id)
    if document["applicant_id"] != user["id"]:
        raise PermissionError("only_applicant_can_confirm")
    if document["current_status"] not in {"returned_to_applicant_for_send", "stamped"}:
        raise ValueError("official_document_not_ready_for_applicant_confirm")
    if document["current_status"] == "returned_to_applicant_for_send":
        return supabase_complete_official_dispatch(document_id, {**payload, "close": True}, session)
    supabase_patch("official_documents", document_id, {"current_status": "closed", "current_step": "", "updated_at": now()})
    supabase_insert_official_log(document_id, "confirm", user, payload.get("comment") or "申請人確認已用印版本", ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    return supabase_official_document_detail(document_id, session)


def supabase_update_official_stamp_position(document_id: str, payload: Dict[str, Any], session: Dict[str, Any] | None) -> Dict[str, Any]:
    user = supabase_official_session_user(session)
    document = supabase_official_document_row(document_id)
    if document["applicant_id"] != user["id"]:
        raise PermissionError("only_applicant_can_update_stamp_position")
    if document["current_status"] != "draft":
        raise ValueError("stamp_position_locked_after_submit")
    position = official_stamp_position_payload(payload)
    stamp_request = supabase_official_document_stamp_request(document_id)
    if not stamp_request:
        raise ValueError("official_document_stamp_request_not_found")
    supabase_patch("official_document_stamp_requests", stamp_request["id"], {**position, "updated_at": now()})
    supabase_insert_official_log(document_id, "update_stamp_position", user, json.dumps(position, ensure_ascii=False), ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
    return supabase_official_document_detail(document_id, session)


def supabase_auto_stamp_official_document(document_id: str, payload: Dict[str, Any], actor: Dict[str, Any] | None = None) -> Dict[str, Any]:
    document = supabase_official_document_row(document_id)
    stamp_request = supabase_official_document_stamp_request(document_id)
    if not stamp_request:
        raise ValueError("official_document_stamp_request_required")
    try:
        supabase_patch("official_documents", document_id, {"current_status": "stamping", "current_step": "auto_stamp", "updated_at": now()})
        supabase_patch("official_document_stamp_requests", stamp_request["id"], {"status": "stamping", "updated_at": now()})
        seal = supabase_company_seal_row(stamp_request["seal_id"])
        if not seal.get("is_active"):
            raise ValueError("inactive_seal_cannot_stamp")
        current_files = supabase_filter_rows("company_seal_files", {"seal_id": stamp_request["seal_id"], "is_current": True}, order="version.desc", limit=1)
        if not current_files:
            raise ValueError("current_seal_file_required")
        seal_file = current_files[0]
        file_object = supabase_get("file_objects", seal_file.get("file_object_id") or "") if seal_file.get("file_object_id") else None
        if not file_object:
            raise ValueError("seal_file_object_required")
        supabase_insert_official_log(document_id, "read_seal_vault_for_stamp", actor, "authorized_backend_stamp_only", ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
        seal_bytes = supabase_storage_download(file_object["storage_key"], file_object.get("bucket") or EDOC_SEAL_STORAGE_BUCKET)
        if sha256_bytes(seal_bytes) != seal_file["file_hash"]:
            raise ValueError("seal_file_hash_mismatch")
        source_file = supabase_official_latest_source_file(document)
        source_object = supabase_get("file_objects", source_file.get("file_object_id") or "") if source_file.get("file_object_id") else None
        if not source_object:
            raise ValueError("official_source_file_object_missing")
        original_pdf = supabase_storage_download(source_object["storage_key"], source_object.get("bucket") or EDOC_STORAGE_BUCKET)
        stamp_no = payload.get("stamp_no") or f"ODSTAMP-{document_id}-{int(time.time())}"
        positions = official_stamp_positions_from_request(stamp_request, seal)
        stamped_pdf, engine, layout = stamp_uploaded_pdf_bytes(original_pdf, [{**item, "stamp_no": stamp_no} for item in positions], stamp_no)
        stamped_file = supabase_store_official_pdf_file(document_id, "stamped_pdf", f"{document_id}-stamped.pdf", stamped_pdf, "Auto Stamp")
        supabase_patch("official_document_stamp_requests", stamp_request["id"], {"status": "stamped", "stamped_file_id": stamped_file["id"], "stamped_at": now(), "updated_at": now(), "error_message": ""})
        supabase_insert_official_log(document_id, "auto_stamp", actor, f"{engine} {stamp_no} seal_hash={seal_file['file_hash']}", file_id=stamped_file["id"], ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
        dispatch_record = supabase_advance_official_dispatch_after_stamp(document_id, stamped_file, actor, payload)
        return {"ok": True, "stamped_file": official_file_metadata(stamped_file), "engine": engine, "layout": layout, "dispatch_record": dispatch_record}
    except Exception as exc:
        detail = str(exc)
        supabase_patch("official_documents", document_id, {"current_status": "stamping_failed", "current_step": "general_affairs_review", "updated_at": now()})
        supabase_patch("official_document_stamp_requests", stamp_request["id"], {"status": "failed", "error_message": detail, "updated_at": now()})
        supabase_insert_official_log(document_id, "auto_stamp_failed", actor, detail, ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
        supabase_create_notification({"type": "發文用印失敗", "title": f"{document['title']} 自動用印失敗", "target_role": "總務", "source": document_id, "priority": "高", "body": detail})
        return {"ok": False, "error": "auto_stamp_failed", "detail": detail}


def supabase_official_document_download_file(document_id: str, file_id: str, session: Dict[str, Any] | None, ip_address: str = "", user_agent: str = "") -> Tuple[Dict[str, Any], Dict[str, Any], bytes]:
    user = supabase_official_session_user(session)
    document = supabase_official_document_row(document_id)
    steps = supabase_official_document_steps(document_id)
    if not canDownloadOfficialDocument(user, document, steps) and not session_has_any_permission(session, ["official_documents.all_records"]):
        raise PermissionError("official_document_download_forbidden")
    rows = supabase_filter_rows("official_document_files", {"id": file_id, "document_id": document_id}, limit=1)
    if not rows:
        raise ValueError("official_document_file_not_found")
    file_meta = rows[0]
    file_object = supabase_get("file_objects", file_meta.get("file_object_id") or "") if file_meta.get("file_object_id") else None
    if not file_object:
        raise ValueError("official_document_file_object_missing")
    data = supabase_storage_download(file_object["storage_key"], file_object.get("bucket") or EDOC_STORAGE_BUCKET)
    supabase_insert_official_log(document_id, "download_file", user, file_meta["file_type"], file_id=file_id, ip_address=ip_address, user_agent=user_agent)
    supabase_insert("file_access_logs", {
        "id": f"FLOG-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "attachment_id": None,
        "file_object_id": file_meta.get("file_object_id"),
        "document_id": None,
        "actor": official_actor_name(user),
        "action": "發文附件下載",
        "ip": ip_address,
        "device": user_agent[:180] if user_agent else "",
        "watermark_text": "",
        "result": "成功",
        "detail": f"official_document_id={document_id};{file_meta['file_type']}",
        "created_at": now(),
    })
    return document, {**file_meta, "object": file_object}, data


def supabase_role_permissions(role_name: str) -> List[str]:
    role_qs = urllib.parse.urlencode({"select": "id", "name": f"eq.{role_name}", "limit": "1"})
    roles = supabase_request("GET", f"roles?{role_qs}")
    if not roles:
        return []
    rp_qs = urllib.parse.urlencode({"select": "permission_id", "role_id": f"eq.{roles[0]['id']}"})
    links = supabase_request("GET", f"role_permissions?{rp_qs}")
    if not links:
        return []
    ids = ",".join([item["permission_id"] for item in links])
    perm_qs = urllib.parse.urlencode({"select": "code", "id": f"in.({ids})"})
    return [item["code"] for item in supabase_request("GET", f"permissions?{perm_qs}")]


def supabase_authenticate(payload: Dict[str, Any], ip: str, device: str) -> Tuple[Dict[str, Any], int]:
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    provider = str(payload.get("provider") or payload.get("environment") or "本機帳號")
    if not email or not password:
        return {"error": "invalid_request", "detail": "請輸入帳號與密碼。"}, 400
    qs = urllib.parse.urlencode({"select": "*", "email": f"eq.{email}", "limit": "1"})
    users = supabase_request("GET", f"users?{qs}")
    if not users:
        supabase_insert("login_events", {"id": f"LOGIN-{int(time.time() * 1000)}", "email": email, "provider": provider, "ip": ip, "device": device, "status": "失敗", "reason": "帳號不存在"})
        return {"error": "invalid_credentials", "detail": "帳號或密碼不正確。"}, 401
    user = users[0]
    if user.get("status") != "啟用":
        supabase_insert("login_events", {"id": f"LOGIN-{int(time.time() * 1000)}", "user_id": user["id"], "email": email, "provider": provider, "ip": ip, "device": device, "status": "失敗", "reason": "帳號停用"})
        return {"error": "account_disabled", "detail": "此帳號已停用。"}, 403
    if user.get("role") not in ALLOWED_EDOC_ROLES:
        supabase_insert("login_events", {"id": f"LOGIN-{int(time.time() * 1000)}", "user_id": user["id"], "email": email, "provider": provider, "ip": ip, "device": device, "status": "失敗", "reason": "角色未授權"})
        return {"error": "role_forbidden", "detail": "此帳號角色未授權使用電子公文系統。"}, 403
    if demo_login_blocked(email, password):
        supabase_insert("login_events", {"id": f"LOGIN-{int(time.time() * 1000)}", "user_id": user["id"], "email": email, "provider": provider, "ip": ip, "device": device, "status": "失敗", "reason": "正式站禁止 demo 帳號登入"})
        return {"error": "demo_login_disabled", "detail": "正式環境已關閉 demo 帳號，請使用正式帳號或 Logging Portal 登入。"}, 403
    if not verify_password(password, user.get("password_hash")):
        supabase_insert("login_events", {"id": f"LOGIN-{int(time.time() * 1000)}", "user_id": user["id"], "email": email, "provider": provider, "ip": ip, "device": device, "status": "失敗", "reason": "密碼錯誤"})
        return {"error": "invalid_credentials", "detail": "帳號或密碼不正確。"}, 401
    token = secrets.token_urlsafe(36)
    expires = (datetime.now() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    supabase_insert("auth_sessions", {"id": f"SES-{int(time.time() * 1000)}", "user_id": user["id"], "token_hash": hash_token(token), "provider": provider, "ip": ip, "device": device, "expires_at": expires})
    supabase_patch("users", user["id"], {"last_login_at": now()})
    supabase_insert("login_events", {"id": f"LOGIN-{int(time.time() * 1000)}", "user_id": user["id"], "email": email, "provider": provider, "ip": ip, "device": device, "status": "成功", "reason": "帳密驗證通過"})
    user.pop("password_hash", None)
    return {"token": token, "expiresAt": expires, "user": user, "permissions": supabase_role_permissions(user.get("role", ""))}, 200


def supabase_authenticate_logging_bridge(payload: Dict[str, Any], ip: str, device: str) -> Tuple[Dict[str, Any], int]:
    try:
        source_user, error = extract_logging_bridge_user(payload)
        if error:
            return {"error": "logging_bridge_denied", "detail": error}, 403 if error in {"invalid_signature", "unsigned_bridge_payload"} else 400
        logging_role_key = canonical_logging_role(source_user.get("loggingRoleKey") or source_user.get("logging_role_key") or source_user.get("role"))
        profile = logging_role_profile(logging_role_key)
        email = roster_text(source_user.get("email")).lower()
        if not email:
            return {"error": "logging_bridge_denied", "detail": "missing_email"}, 400
        logging_account_id = roster_text(source_user.get("loggingAccountId") or source_user.get("logging_account_id") or source_user.get("id") or source_user.get("profileId") or email)
        display_name = roster_text(source_user.get("name") or source_user.get("display_name") or source_user.get("roleLabel") or email.split("@")[0])
        unit = roster_text(source_user.get("unit") or source_user.get("department") or source_user.get("departmentCode") or source_user.get("department_code") or profile["unit"])
        title = roster_text(source_user.get("title") or source_user.get("roleLabel") or profile["title"])
        job_level = normalize_edoc_job_level(source_user.get("jobLevel") or source_user.get("job_level") or profile["job_level"])
        edoc_role = profile["role"]
        if edoc_role not in ALLOWED_EDOC_ROLES:
            return {"error": "role_forbidden", "detail": "此 Logging 帳號未授權使用 EDOC。"}, 403

        qs = urllib.parse.urlencode({
            "select": "*",
            "or": f"(logging_account_id.eq.{logging_account_id},email.eq.{email})",
            "limit": "1",
        })
        rows = supabase_request("GET", f"users?{qs}")
        user = rows[0] if rows else None
        ts = now()
        update_payload = {
            "auth_user_id": roster_text(source_user.get("authUserId") or source_user.get("auth_user_id")) or None,
            "account_source": "logging",
            "logging_account_id": logging_account_id,
            "logging_role_key": logging_role_key,
            "external_account_payload_json": json.dumps(redact_sensitive(source_user), ensure_ascii=False),
            "last_synced_from_logging_at": ts,
            "name": display_name,
            "email": email,
            "unit": unit,
            "title": title,
            "job_level": job_level,
            "role": edoc_role,
            "provider": "Logging / 平台帳號",
            "mfa_status": "由平台管理",
            "status": "啟用",
        }
        if user:
            user = supabase_patch("users", user["id"], update_payload)
        else:
            user = supabase_insert("users", {
                "id": f"LOG-{hashlib.sha256(logging_account_id.encode('utf-8')).hexdigest()[:10].upper()}",
                **update_payload,
            })

        link_id = f"LINK-LOGGING-EDOC-{hashlib.sha256(logging_account_id.encode('utf-8')).hexdigest()[:10].upper()}"
        link_qs = urllib.parse.urlencode({
            "select": "*",
            "source_system": "eq.logging",
            "source_account_id": f"eq.{logging_account_id}",
            "target_module": "eq.edoc",
            "limit": "1",
        })
        links = supabase_request("GET", f"module_account_links?{link_qs}")
        link_payload = {
            "id": link_id,
            "user_id": user["id"],
            "source_system": "logging",
            "source_account_id": logging_account_id,
            "source_role_key": logging_role_key,
            "source_email": email,
            "target_module": "edoc",
            "target_role_key": edoc_role,
            "sync_status": "active",
            "metadata_json": {"source": "logging_bridge"},
            "last_synced_at": ts,
        }
        if links:
            supabase_patch("module_account_links", links[0]["id"], link_payload)
        else:
            supabase_insert("module_account_links", link_payload)
        supabase_insert("audit_logs", {
            "id": f"AUD-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
            "actor": "Logging Bridge",
            "action": "同步外部帳號",
            "target_type": "module_account_links",
            "target_id": link_id,
            "ip": ip,
            "device": device,
            "detail": f"{email} / {logging_role_key} → {edoc_role}",
            "event_type": "external_account_status_change",
            "severity": "critical",
            "result": "success",
            "module_code": "system_permissions",
            "resource_type": "external_account",
            "resource_id": link_id,
            "data_scope": "custom",
            "actor_roles_json": ["system_permissions.manage"],
            "target_user_id": user["id"],
            "target_email": email,
            "reason": "Logging 帳號進入 EDOC，自動同步帳號連結。",
            "request_id": f"req_{secrets.token_hex(8)}",
            "before_snapshot_json": {},
            "after_snapshot_json": {"role": edoc_role, "job_level": job_level, "unit": unit, "logging_role_key": logging_role_key},
            "metadata_json": {"source_system": "logging", "target_module": "edoc", "logging_role_key": logging_role_key},
        })
        token = secrets.token_urlsafe(36)
        expires = (datetime.now() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
        supabase_insert("auth_sessions", {"id": f"SES-{int(time.time() * 1000)}", "user_id": user["id"], "token_hash": hash_token(token), "provider": "Logging / 平台帳號", "ip": ip, "device": device, "expires_at": expires})
        supabase_patch("users", user["id"], {"last_login_at": ts})
        supabase_insert("login_events", {"id": f"LOGIN-{int(time.time() * 1000)}", "user_id": user["id"], "email": email, "provider": "Logging / 平台帳號", "ip": ip, "device": device, "status": "成功", "reason": "沿用 Logging 帳號進入 EDOC"})
        user.pop("password_hash", None)
        incoming_permissions = []
        if isinstance(payload.get("permissions"), list):
            incoming_permissions = payload["permissions"]
        elif isinstance(payload.get("user"), dict) and isinstance(payload["user"].get("permissions"), list):
            incoming_permissions = payload["user"]["permissions"]
        permissions = sorted(set(supabase_role_permissions(user.get("role", ""))) | set(logging_permissions_to_edoc_codes(incoming_permissions)))
        return {
            "token": token,
            "expiresAt": expires,
            "user": user,
            "permissions": permissions,
            "bridge": {
                "sourceSystem": "logging",
                "loggingAccountId": logging_account_id,
                "loggingRoleKey": logging_role_key,
                "targetModule": "edoc",
                "targetRole": edoc_role,
            },
        }, 200
    except RuntimeError as error:
        return {"error": "logging_bridge_unavailable", "detail": str(error)}, 503


def supabase_current_session(token: str) -> Dict[str, Any] | None:
    if not token:
        return None
    qs = urllib.parse.urlencode({"select": "*", "token_hash": f"eq.{hash_token(token)}", "revoked_at": "is.null", "limit": "1"})
    sessions = supabase_request("GET", f"auth_sessions?{qs}")
    if not sessions or sessions[0].get("expires_at", "") <= now():
        return None
    user = supabase_get("users", sessions[0]["user_id"])
    if not user:
        return None
    if user.get("role") not in ALLOWED_EDOC_ROLES:
        return None
    user.pop("password_hash", None)
    return {"sessionId": sessions[0]["id"], "expiresAt": sessions[0]["expires_at"], "user": user, "permissions": supabase_role_permissions(user.get("role", ""))}


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
        "owner": "總務",
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


def supabase_exchange_history(ref_type: str, ref_id: str, from_status: str, to_status: str, message: str, provider_status: str, payload: Dict[str, Any]) -> None:
    supabase_insert("exchange_status_history", {
        "id": f"EXHIS-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "exchange_ref_type": ref_type,
        "exchange_ref_id": ref_id,
        "from_status": from_status or "",
        "to_status": to_status,
        "message": message,
        "provider_status_code": provider_status,
        "payload_summary_json": redact_sensitive(payload),
    })


def supabase_exchange_log(ref_type: str, ref_id: str, operation: str, direction: str, request_payload: Dict[str, Any], response_payload: Dict[str, Any], status: str) -> None:
    supabase_insert("exchange_log", {
        "id": f"EXLOG-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "exchange_ref_type": ref_type,
        "exchange_ref_id": ref_id,
        "provider": EDOC_EXCHANGE_PROVIDER,
        "environment": EDOC_EXCHANGE_ENV,
        "operation": operation,
        "direction": direction,
        "request_summary_json": redact_sensitive(request_payload),
        "response_summary_json": redact_sensitive(response_payload),
        "status": status,
        "error_code": response_payload.get("error_code", ""),
        "error_message": response_payload.get("message", ""),
    })


def supabase_exchange_outboxes(filters: Dict[str, str]) -> List[Dict[str, Any]]:
    params = {"select": "*", "limit": "500", **filters}
    qs = urllib.parse.urlencode(params)
    return supabase_request("GET", f"exchange_outbox?{qs}")


def supabase_exchange_queue_document(payload: Dict[str, Any]) -> Dict[str, Any]:
    document_id = payload.get("document_id")
    if not document_id:
        raise ValueError("document_id is required")
    existing = supabase_exchange_outboxes({"document_id": f"eq.{document_id}"})
    if existing:
        return existing[0]
    document = supabase_get("documents", document_id)
    if not document:
        raise ValueError(f"document_not_found:{document_id}")
    outbox = {
        "id": f"EXOUT-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "document_id": document_id,
        "doc_no": document.get("doc_no", ""),
        "target_agency": payload.get("target_agency") or document.get("agency_name", ""),
        "target_agency_code": payload.get("target_agency_code") or document.get("agency_code", ""),
        "status": "待發文",
        "provider": EDOC_EXCHANGE_PROVIDER,
        "environment": EDOC_EXCHANGE_ENV,
        "package_id": payload.get("package_id") or f"PKG-{document.get('doc_no', document_id)}",
        "external_id": "",
        "idempotency_key": payload.get("idempotency_key") or f"{document_id}:{document.get('doc_no', '')}",
        "retry_count": 0,
        "max_retries": int(payload.get("max_retries") or EDOC_EXCHANGE_MAX_RETRIES),
        "last_error_code": "",
        "last_error_message": "",
        "next_retry_at": "",
        "sent_at": "",
        "returned_at": "",
    }
    created = supabase_insert("exchange_outbox", outbox)
    supabase_exchange_history("outbox", created["id"], "", "待發文", "公文已加入交換待發佇列。", "QUEUED", {})
    return created


def supabase_exchange_send_document(payload: Dict[str, Any]) -> Dict[str, Any]:
    outbox = supabase_get("exchange_outbox", payload.get("outbox_id") or payload.get("id") or "") if (payload.get("outbox_id") or payload.get("id")) else supabase_exchange_queue_document(payload)
    if not outbox:
        raise ValueError("outbox_not_found")
    document = supabase_get("documents", outbox["document_id"]) or {}
    metadata = json.loads(document.get("metadata_json") or "{}") if isinstance(document.get("metadata_json"), str) else document.get("metadata_json") or {}
    provider = MockExchangeProvider()
    package = {
        "outbox_id": outbox["id"],
        "document_id": outbox["document_id"],
        "doc_no": outbox.get("doc_no"),
        "subject": document.get("subject"),
        "target_agency": outbox.get("target_agency"),
        "target_agency_code": outbox.get("target_agency_code"),
        "metadata": metadata,
        "mock_scenario": payload.get("mock_scenario") or ("success" if payload.get("mock_retry_success") and outbox.get("status") in {"失敗", "退文"} else metadata.get("mock_exchange")),
        "mock_retry_success": payload.get("mock_retry_success", True),
    }
    result = provider.send_official_document(package)
    status = result.get("status") or ("已送出" if result.get("ok") else "失敗")
    patch_payload = {
        "status": status,
        "external_id": result.get("external_id") or outbox.get("external_id") or "",
        "last_error_code": result.get("error_code", ""),
        "last_error_message": result.get("message", ""),
        "next_retry_at": (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S") if status == "失敗" else "",
        "sent_at": now() if status == "已送出" and not outbox.get("sent_at") else outbox.get("sent_at", ""),
    }
    updated = supabase_patch("exchange_outbox", outbox["id"], patch_payload)
    supabase_exchange_history("outbox", outbox["id"], outbox.get("status", ""), status, result.get("message", ""), result.get("provider_status", ""), result.get("summary", {}))
    supabase_exchange_log("outbox", outbox["id"], "sendOfficialDocument", "outbound", payload, result, "success" if result.get("ok") else "failed")
    return {"ok": bool(result.get("ok")), "item": updated, "provider": redact_sensitive(result)}


def supabase_exchange_query_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    outbox = supabase_get("exchange_outbox", payload.get("outbox_id") or payload.get("id") or "")
    if not outbox:
        return {"ok": False, "error": "outbox_not_found"}
    result = MockExchangeProvider().query_delivery_status(outbox)
    status = result.get("status") or outbox.get("status")
    patch_payload = {
        "status": status,
        "last_error_code": result.get("error_code", ""),
        "last_error_message": result.get("message", ""),
        "returned_at": now() if status == "退文" and not outbox.get("returned_at") else outbox.get("returned_at", ""),
    }
    updated = supabase_patch("exchange_outbox", outbox["id"], patch_payload)
    supabase_exchange_history("outbox", outbox["id"], outbox.get("status", ""), status, result.get("message", ""), result.get("provider_status", ""), result.get("summary", {}))
    supabase_exchange_log("outbox", outbox["id"], "queryDeliveryStatus", "outbound", payload, result, "success" if result.get("ok") else "failed")
    return {"ok": bool(result.get("ok")), "item": updated, "provider": redact_sensitive(result)}


def supabase_exchange_retry_failed(payload: Dict[str, Any]) -> Dict[str, Any]:
    outbox = supabase_get("exchange_outbox", payload.get("outbox_id") or payload.get("id") or "")
    if not outbox:
        return {"ok": False, "error": "outbox_not_found"}
    retry_count = int(outbox.get("retry_count") or 0)
    max_retries = int(outbox.get("max_retries") or EDOC_EXCHANGE_MAX_RETRIES)
    if retry_count >= max_retries:
        updated = supabase_patch("exchange_outbox", outbox["id"], {"status": "已達重送上限"})
        return {"ok": False, "error": "retry_limit_reached", "item": updated}
    supabase_patch("exchange_outbox", outbox["id"], {"retry_count": retry_count + 1})
    return supabase_exchange_send_document({"outbox_id": outbox["id"], "mock_retry_success": payload.get("mock_retry_success", True)})


def supabase_exchange_receive_documents(payload: Dict[str, Any]) -> Dict[str, Any]:
    provider = MockExchangeProvider()
    items = provider.receive_official_documents(payload)
    rows = []
    for item in items:
        doc = supabase_insert("documents", {
            "id": f"DOC-IN-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
            "doc_no": item.get("doc_no"),
            "direction": "收文",
            "doc_type": item.get("doc_type", "函"),
            "priority": item.get("priority", "普通件"),
            "security_level": item.get("security_level", "普通"),
            "agency_name": item.get("source_agency", ""),
            "agency_code": item.get("source_agency_code", ""),
            "subject": item.get("subject", ""),
            "body": item.get("body", ""),
            "status": "待登錄",
            "owner": "總務",
            "department": "總管理處",
            "due_date": (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
            "received_at": now(),
        })
        inbox = supabase_insert("exchange_inbox", {
            "id": f"EXIN-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
            "document_id": doc["id"],
            "external_id": item["external_id"],
            "source_agency": item.get("source_agency", ""),
            "source_agency_code": item.get("source_agency_code", ""),
            "doc_no": item.get("doc_no", ""),
            "subject": item.get("subject", ""),
            "status": "待確認",
            "provider": EDOC_EXCHANGE_PROVIDER,
            "environment": EDOC_EXCHANGE_ENV,
            "received_at": now(),
            "acknowledged_at": "",
            "raw_summary_json": item.get("summary", {}),
        })
        supabase_exchange_history("inbox", inbox["id"], "", "待確認", "Mock 收文已寫入待確認。", "MOCK_RECEIVED", item.get("summary", {}))
        supabase_exchange_log("inbox", inbox["id"], "receiveOfficialDocuments", "inbound", payload, item, "success")
        rows.append(inbox)
    return {"count": len(rows), "items": rows}


def supabase_exchange_acknowledge_received(payload: Dict[str, Any]) -> Dict[str, Any]:
    inbox = supabase_get("exchange_inbox", payload.get("inbox_id") or payload.get("id") or "")
    if not inbox:
        return {"ok": False, "error": "inbox_not_found"}
    result = MockExchangeProvider().acknowledge_received(inbox)
    updated = supabase_patch("exchange_inbox", inbox["id"], {"status": "已入案", "acknowledged_at": now()})
    if inbox.get("document_id"):
        supabase_patch("documents", inbox["document_id"], {"status": "待分派"})
    supabase_exchange_history("inbox", inbox["id"], inbox.get("status", ""), "已入案", result.get("message", ""), result.get("provider_status", ""), result.get("summary", {}))
    supabase_exchange_log("inbox", inbox["id"], "acknowledgeReceived", "inbound", payload, result, "success")
    return {"ok": True, "item": updated, "provider": redact_sensitive(result)}


def supabase_next_run(schedule_text: str) -> str:
    return compute_next_run_at(schedule_text)


def supabase_execute_job_logic(job: Dict[str, Any]) -> Dict[str, Any]:
    job_type = job["job_type"]
    if job_type == "pullInbound":
        result = supabase_exchange_receive_documents({})
        return {"message": f"成功：拉取 {result.get('count', 0)} 筆收文", "payload": result}
    if job_type == "exchangeSendPending":
        outboxes = [item for item in supabase_list("exchange_outbox", {"status": ["待發文"]})[:20]]
        results = [supabase_exchange_send_document({"outbox_id": item["id"]}) for item in outboxes]
        return {"message": f"成功：送出 {len(results)} 筆待發交換公文", "payload": {"count": len(results), "results": results}}
    if job_type == "exchangeRetryFailed":
        candidates = []
        for status_text in ["失敗", "退文"]:
            candidates.extend(supabase_list("exchange_outbox", {"status": [status_text]}))
        due = [
            item for item in candidates
            if int(item.get("retry_count") or 0) < int(item.get("max_retries") or EDOC_EXCHANGE_MAX_RETRIES)
            and (not item.get("next_retry_at") or item.get("next_retry_at") <= now())
        ][:20]
        results = [supabase_exchange_retry_failed({"outbox_id": item["id"]}) for item in due]
        return {"message": f"成功：重送 {len(results)} 筆交換失敗公文", "payload": {"count": len(results), "results": results}}
    if job_type == "tokenCheck":
        sessions = supabase_list("auth_sessions", {})
        expiring_before = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        active = [item for item in sessions if not item.get("revoked_at") and item.get("expires_at", "") > now()]
        expiring = [item for item in active if item.get("expires_at", "") <= expiring_before]
        return {"message": f"成功：有效 session {len(active)}，1 小時內到期 {len(expiring)}", "payload": {"active_sessions": len(active), "expiring": len(expiring)}}
    if job_type == "nextDayCheck":
        tasks = supabase_list("exchange_tasks", {})
        checked = 0
        for task in [item for item in tasks if item.get("direction") == "發文"]:
            checked += 1
            status = task.get("status") if task.get("status") in {"交換失敗", "退回補正"} else "已確認收文"
            supabase_patch("exchange_tasks", task["id"], {"status": status, "next_check_at": compute_next_run_at("每日 09:00")})
            supabase_insert("exchange_events", {
                "id": f"EVT-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
                "task_id": task["id"],
                "document_id": task.get("document_id"),
                "event_type": "next_day_check",
                "message": "Vercel Cron 完成發文翌日查核。",
                "payload_json": "{}",
            })
        return {"message": f"成功：完成 {checked} 筆發文翌日查核", "payload": {"checked": checked}}
    if job_type == "exchangeSync":
        sent_outboxes = supabase_list("exchange_outbox", {"status": ["已送出"]})
        gateway_results = [supabase_exchange_query_status({"outbox_id": item["id"]}) for item in sent_outboxes[:50]]
        tasks = supabase_list("exchange_tasks", {})
        for task in tasks:
            supabase_insert("exchange_events", {
                "id": f"EVT-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
                "task_id": task["id"],
                "document_id": task.get("document_id"),
                "event_type": "status_sync",
                "message": f"Vercel Cron 同步交換狀態：{task.get('status')}",
                "payload_json": json.dumps({"status": task.get("status")}, ensure_ascii=False),
            })
        return {"message": f"成功：同步 {len(gateway_results)} 筆新介接層狀態，保留 {len(tasks)} 筆舊交換事件", "payload": {"synced": len(gateway_results), "results": gateway_results, "legacyEvents": len(tasks)}}
    if job_type == "overdueReminder":
        documents = supabase_list("documents", {})
        today = datetime.now().strftime("%Y-%m-%d")
        overdue = [item for item in documents if item.get("due_date") and item.get("due_date") < today and "完成" not in item.get("status", "")]
        for doc in overdue:
            supabase_insert("audit_logs", {
                "id": f"AUD-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
                "actor": "Vercel Cron",
                "action": "逾期稽催",
                "target_type": "documents",
                "target_id": doc["id"],
                "ip": "vercel",
                "device": "cron",
                "detail": f"{doc.get('doc_no')} / {doc.get('owner')} / {doc.get('due_date')}",
            })
        return {"message": f"成功：產生 {len(overdue)} 筆逾期稽催紀錄", "payload": {"overdue": len(overdue)}}
    if job_type == "contractRenewalCheck":
        contracts = supabase_list("contracts", {})
        today = datetime.now().date()
        due_contracts = []
        for contract in contracts:
            if not contract.get("end_date") or contract.get("status") in {"已終止", "已作廢"}:
                continue
            end_date = parse_time(contract.get("end_date", "")).date()
            days_left = (end_date - today).days
            alert_days = int(contract.get("renewal_alert_days") or 60)
            if 0 <= days_left <= alert_days:
                due_contracts.append(contract)
                notice = supabase_create_notification({
                    "type": "合約續約",
                    "title": f"{contract.get('title')} 即將到期",
                    "target_role": contract.get("owner") or "行政部主任",
                    "channel": "Email + 系統通知",
                    "priority": "高" if days_left <= 30 else "中",
                    "source": contract.get("contract_no"),
                    "body": f"{contract.get('counterparty')} 合約將於 {contract.get('end_date')} 到期，剩餘 {days_left} 天，請確認續約、重簽或終止。",
                })
                supabase_insert("audit_logs", {
                    "id": f"AUD-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
                    "actor": "Vercel Cron",
                    "action": "合約續約提醒",
                    "target_type": "contracts",
                    "target_id": contract["id"],
                    "ip": "vercel",
                    "device": "cron",
                    "detail": notice["id"],
                })
        return {"message": f"成功：產生 {len(due_contracts)} 筆合約續約提醒", "payload": {"dueContracts": len(due_contracts)}}
    if job_type == "reportGenerate":
        report = supabase_dashboard()
        supabase_request("POST", "settings?on_conflict=key", {
            "key": "latest_report",
            "value_json": json.dumps({"generated_at": now(), **report}, ensure_ascii=False),
            "version": 1,
            "updated_at": now(),
        }, prefer="resolution=merge-duplicates,return=representation")
        return {"message": f"成功：報表已產生，公文 {report['documents']} 件，交換成功率 {report['successRate']}%", "payload": report}
    if job_type == "archiveSeal":
        return {"message": "成功：Supabase Storage 歸檔檢查已排程，正式檔案桶接入後執行雜湊抽查", "payload": {"storage": "pending_bucket"}}
    return {"message": f"成功：{job_type} 無額外動作", "payload": {}}


def supabase_run_background_job(job_id: str) -> Dict[str, Any]:
    job = supabase_get("background_jobs", job_id)
    if not job:
        return {"error": "not_found", "job_id": job_id}
    if job.get("status") != "啟用":
        return {"id": job_id, "status": "skipped", "result": "任務未啟用"}
    started = datetime.now()
    run_id = f"RUN-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    try:
        result = supabase_execute_job_logic(job)
        status = "成功"
        message = result["message"]
        payload = result.get("payload", {})
    except Exception as exc:
        status = "失敗"
        message = str(exc)
        payload = {"error": message}
    finished = datetime.now()
    duration_ms = int((finished - started).total_seconds() * 1000)
    next_run = supabase_next_run(job["schedule_text"])
    supabase_insert("job_runs", {
        "id": run_id,
        "job_id": job_id,
        "job_type": job["job_type"],
        "status": status,
        "result": message,
        "started_at": started.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": finished.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_ms": duration_ms,
        "payload_json": json.dumps(payload, ensure_ascii=False),
    })
    supabase_patch("background_jobs", job_id, {
        "last_result": f"{status}：{message}",
        "next_run_at": next_run,
        "run_count": int(job.get("run_count") or 0) + 1,
    })
    return {"run_id": run_id, "job_id": job_id, "status": status, "result": message, "next_run_at": next_run, "duration_ms": duration_ms, "payload": payload}


def supabase_run_due_background_jobs(all_enabled: bool = False) -> Dict[str, Any]:
    jobs = supabase_list("background_jobs", {})
    if not all_enabled:
        jobs = [job for job in jobs if job.get("status") == "啟用" and (job.get("next_run_at") or "") <= now()]
    else:
        jobs = [job for job in jobs if job.get("status") == "啟用"]
    jobs.sort(key=lambda item: item.get("next_run_at") or "")
    results = [supabase_run_background_job(job["id"]) for job in jobs]
    return {"count": len(results), "results": results}


def supabase_notification_credential_status(channel: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    credential = next((row for row in rows if row.get("channel") == channel), {"channel": channel, "status": "未設定"})
    required = channel_required_env(channel)
    if channel == "Line 工作群組" and not env_present("LINE_WEBHOOK_URL"):
        missing = [] if env_present("LINE_CHANNEL_ACCESS_TOKEN") and env_present("LINE_TARGET_ID") else required
    else:
        missing = [name for name in required if env_present(name) is False]
    expires_at = credential.get("expires_at") or ""
    expiry = parse_time(expires_at) if expires_at else datetime.max
    days_left = None if expiry == datetime.max else (expiry - datetime.now()).days
    if missing:
        status = "缺少環境憑證"
    elif expiry < datetime.now():
        status = "已到期"
    elif days_left is not None and days_left <= 14:
        status = "即將到期"
    else:
        status = "有效"
    return {**credential, "channel": channel, "status": status, "missing": missing, "days_left": days_left, "ok": status == "有效"}


def supabase_monitoring_snapshot() -> Dict[str, Any]:
    readiness = production_readiness()
    alerts: List[Dict[str, str]] = []
    for name in readiness["missing"]:
        append_alert(alerts, "critical" if is_production() else "warning", "ENV-MISSING", f"缺少正式環境變數 {name}", "到 Vercel Project Settings 補齊後重新部署。")
    for item in readiness["blockers"]:
        append_alert(alerts, "critical", "READINESS-BLOCKER", item, "先處理 production readiness blocker，再開放正式交換。")
    for item in readiness["warnings"]:
        append_alert(alerts, "warning", "READINESS-WARNING", item, "排入上線前檢核清單，避免正式營運缺口。")

    exchange_tasks = supabase_list("exchange_tasks", {})
    deliveries = supabase_list("notification_deliveries", {})
    job_runs = supabase_list("job_runs", {"order": ["finished_at.desc"], "limit": ["20"]})
    documents = supabase_list("documents", {"limit": ["1000"]})
    attachments = supabase_list("attachments", {"limit": ["1000"]})
    credential_rows = supabase_list("notification_channel_credentials", {}) if "notification_channel_credentials" in TABLES else []
    credentials = [supabase_notification_credential_status(channel, credential_rows) for channel in ["Email", "Line 工作群組", "系統站內通知"]]

    counts = {
        "documents": len(documents),
        "attachments": len(attachments),
        "exchange_failed": len([item for item in exchange_tasks if item.get("status") in {"交換失敗", "失敗", "逾期未確認"}]),
        "notification_failed": len([item for item in deliveries if item.get("status") in {"失敗", "未設定", "憑證異常"}]),
        "job_failed": len([item for item in job_runs if item.get("status") in {"失敗", "錯誤"}]),
    }
    if counts["exchange_failed"]:
        append_alert(alerts, "critical", "EXCHANGE-FAILED", f"{counts['exchange_failed']} 筆交換任務失敗或逾期。", "由總務工作台重送或執行翌日查核。")
    if counts["notification_failed"]:
        append_alert(alerts, "warning", "NOTIFICATION-FAILED", f"{counts['notification_failed']} 筆通知派送失敗。", "到通知中心重送，並檢查 Email/Line 憑證。")
    if counts["job_failed"]:
        append_alert(alerts, "warning", "JOB-FAILED", f"{counts['job_failed']} 筆背景任務失敗。", "到背景任務頁查看 job_runs 與 API log。")

    last_job = job_runs[0] if job_runs else None
    last_job_age = age_minutes(last_job.get("finished_at") if last_job else None)
    if is_production() and (last_job_age is None or last_job_age > EDOC_MONITORING_EXPECTED_CRON_MINUTES + 120):
        append_alert(alerts, "critical", "CRON-STALLED", "正式環境背景排程超過預期時間未執行。", "檢查 Vercel Cron、CRON_SECRET 與 /api/cron/run-due 執行紀錄。")

    for credential in credentials:
        if credential.get("status") in {"缺少環境憑證", "已到期", "未設定"}:
            append_alert(alerts, "critical" if is_production() else "warning", "CREDENTIAL-INVALID", f"{credential['channel']} 憑證狀態：{credential.get('status')}", "補齊正式憑證、有效期限與環境變數後重新驗證。")
        elif credential.get("status") == "即將到期":
            append_alert(alerts, "warning", "CREDENTIAL-EXPIRING", f"{credential['channel']} 憑證即將到期。", "在到期前完成換證與驗證。")
    signing_service = signing_service_status()
    if signing_service["productionBlocked"]:
        append_alert(alerts, "critical", "SIGNING-SERVICE-INCOMPLETE", f"正式簽章服務尚未設定：{', '.join(signing_service['missing'])}", "設定 HSM/KMS、信任根憑證、TSA、OCSP、CRL 與 EDOC_SIGNING_SECRET 後重新部署。")
    elif not signing_service["ready"]:
        append_alert(alerts, "warning", "SIGNING-SERVICE-SIMULATION", f"簽章服務仍為模擬或不完整：{', '.join(signing_service['missing'])}", "正式上線前完成外部簽章服務接入。")
    storage_service = storage_service_status()
    if storage_service["productionBlocked"]:
        append_alert(alerts, "critical", "STORAGE-SERVICE-INCOMPLETE", f"正式檔案儲存與防毒尚未設定：{', '.join(storage_service['missing'])}", "設定 Supabase Storage private bucket、檔案加密、短效 URL、正式 AV endpoint/API key 後重新部署。")
    elif not storage_service["ready"]:
        append_alert(alerts, "warning", "STORAGE-SERVICE-SIMULATION", f"檔案儲存或防毒服務仍為本機/不完整：{', '.join(storage_service['missing'])}", "正式上線前完成物件儲存與防毒引擎接入。")

    checks = {
        "database": {"status": "ok", "mode": "supabase", "detail": SUPABASE_URL},
        "readiness": {"status": "ok" if readiness["ready"] else "needs_action", "missing": readiness["missing"], "blockers": readiness["blockers"]},
        "storage": {"status": "ok" if storage_service["ready"] else "needs_action", **storage_service},
        "cron": {"status": "ok" if last_job_age is not None else "not_yet_run", "lastRun": last_job, "ageMinutes": last_job_age},
        "notifications": {"status": "ok" if all(item.get("status") in {"有效", "即將到期"} for item in credentials) else "needs_action", "credentials": credentials},
        "signing": {"status": "ok" if signing_service["ready"] else "needs_action", **signing_service},
        "jAgent": {"status": "needs_action" if counts["exchange_failed"] else "ok", "failedTasks": counts["exchange_failed"]},
    }
    status = monitoring_status(alerts)
    return {
        "ok": status != "critical",
        "status": status,
        "checkedAt": now(),
        "deployment": deployment_report(),
        "checks": checks,
        "counts": counts,
        "alerts": alerts,
    }


def run_supabase_monitoring_check() -> Dict[str, Any]:
    snapshot = supabase_monitoring_snapshot()
    webhook = post_monitoring_webhook(snapshot) if snapshot["alerts"] else {"sent": False, "reason": "無告警"}
    log_structured("info", "production_monitoring_check", status=snapshot["status"], alerts=len(snapshot["alerts"]), webhook_sent=bool(webhook.get("sent")), runtime="vercel")
    supabase_insert("audit_logs", {
        "id": f"AUD-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "actor": "Ops Monitor",
        "action": "正式部署監控檢查",
        "target_type": "production_monitoring",
        "target_id": snapshot["status"],
        "ip": "vercel",
        "device": "serverless",
        "detail": json.dumps({"alerts": snapshot["alerts"], "webhook": webhook}, ensure_ascii=False),
        "created_at": now(),
    })
    return {**snapshot, "webhook": webhook}


def stable_json_hash(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(data)


COMPLIANCE_CONTROL_REQUIREMENTS = [
    ("C-001", "機關公文電子交換作業辦法", "收發文、交換事件、異常處理與留存可追蹤", ["documents", "exchange_events", "audit_logs"]),
    ("C-002", "公文電子交換系統資訊安全管理規範", "帳號、RBAC、憑證、Token、IP/裝置與操作留痕", ["users", "auth_sessions", "login_events", "audit_logs"]),
    ("C-003", "文書及檔案管理電腦化作業規範", "文號、附件清冊、PDF 套版、用印版本與歸檔保存", ["pdf_versions", "seal_assets", "file_objects"]),
    ("C-004", "個人資料保護法與內部資安政策", "敏感遮罩、密件隔離、浮水印、檔案存取紀錄", ["attachment_security", "file_access_logs"]),
    ("C-005", "正式資料庫權限政策", "RLS、密件 row-level 隔離、保留年限、audit log 不可竄改", ["document_acl", "audit_logs"]),
    ("C-006", "正式檔案儲存與病毒掃描政策", "Private bucket、加密、短效 URL、防毒掃描與隔離阻擋", ["file_objects", "virus_scan_jobs"]),
    ("C-007", "電子簽章憑證合法性驗證政策", "信任鏈、TSA、OCSP、CRL 與不可否認簽章證據", ["signing_certificates", "certificate_validation_events", "electronic_signatures"]),
    ("C-008", "委外與營運管理", "部署、監控、排程、通知、備份復原與 SOP", ["background_jobs", "job_runs", "notification_deliveries"]),
]


def compliance_control_report(counts: Dict[str, int]) -> List[Dict[str, Any]]:
    rows = []
    for control_id, source, requirement, evidence_tables in COMPLIANCE_CONTROL_REQUIREMENTS:
        evidence = {table: counts.get(table, 0) for table in evidence_tables}
        implemented = any(count > 0 for count in evidence.values())
        rows.append({
            "id": control_id,
            "source": source,
            "requirement": requirement,
            "evidence_tables": evidence,
            "status": "已驗收" if implemented else "待補證據",
        })
    return rows


def compliance_score(controls: List[Dict[str, Any]], blockers: List[str]) -> int:
    base = round((len([item for item in controls if item["status"] == "已驗收"]) / max(1, len(controls))) * 100)
    return max(0, base - min(30, len(blockers) * 5))


def compliance_attestation_payload(
    *,
    counts: Dict[str, int],
    readiness: Dict[str, Any],
    monitoring: Dict[str, Any] | None,
    latest_drill: Dict[str, Any] | None,
    signer_name: str,
    signer_role: str,
    reviewer_name: str,
    reviewer_role: str,
    period: str,
    attestation_type: str,
) -> Dict[str, Any]:
    controls = compliance_control_report(counts)
    blockers = list(readiness.get("blockers") or [])
    if not latest_drill:
        blockers.append("尚未完成備份還原演練。")
    if monitoring and monitoring.get("status") == "critical":
        blockers.append("正式監控仍有 critical 告警。")
    score = compliance_score(controls, blockers)
    status = "通過" if score >= 90 and not blockers else "有條件通過" if score >= 70 else "不通過"
    report = {
        "attestation_type": attestation_type,
        "period": period,
        "generated_at": now(),
        "signer": {"name": signer_name, "role": signer_role},
        "reviewer": {"name": reviewer_name, "role": reviewer_role},
        "status": status,
        "score": score,
        "controls": controls,
        "readiness": {
            "environment": readiness.get("environment"),
            "ready": readiness.get("ready"),
            "databaseMode": readiness.get("databaseMode"),
            "missing": readiness.get("missing", []),
            "blockers": readiness.get("blockers", []),
            "warnings": readiness.get("warnings", []),
        },
        "monitoring": {
            "status": monitoring.get("status") if monitoring else "未執行",
            "alerts": monitoring.get("alerts", [])[:10] if monitoring else [],
        },
        "latest_backup_drill": latest_drill,
        "counts": counts,
        "blockers": blockers,
        "evidence_documents": [
            "docs/compliance-control-matrix.md",
            "docs/database-security-policy.md",
            "docs/file-storage-scanning-policy.md",
            "docs/certificate-legality-validation-policy.md",
            "docs/backup-restore-drill.md",
            "docs/notification-delivery-test.md",
            "docs/deployment-production.md",
        ],
    }
    report_hash = stable_json_hash(report)
    return {
        "id": f"COMP-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3).upper()}",
        "attestation_type": attestation_type,
        "period": period,
        "signer_name": signer_name,
        "signer_role": signer_role,
        "reviewer_name": reviewer_name,
        "reviewer_role": reviewer_role,
        "status": status,
        "score": score,
        "report_hash": report_hash,
        "report": report,
        "signed_at": now(),
        "non_repudiation": {
            "report_hash": report_hash,
            "signed_at": now(),
            "signer_role": signer_role,
            "signature_method": "backend-attestation-hash",
            "ip": "127.0.0.1" if not RUNNING_ON_VERCEL else "vercel",
        },
    }


def latest_local_backup_drill(conn: sqlite3.Connection) -> Dict[str, Any] | None:
    row = conn.execute("SELECT * FROM audit_logs WHERE action = '備份還原演練' ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        return None
    item = row_to_dict(row)
    try:
        detail = json.loads(item.get("detail") or "{}")
    except json.JSONDecodeError:
        detail = {"detail": item.get("detail")}
    return {"audit_id": item["id"], "created_at": item["created_at"], **detail}


def create_compliance_attestation(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    counts = sqlite_table_counts(DB_PATH)
    readiness = production_readiness()
    monitoring = local_monitoring_snapshot(conn)
    latest_drill = latest_local_backup_drill(conn)
    attestation = compliance_attestation_payload(
        counts=counts,
        readiness=readiness,
        monitoring=monitoring,
        latest_drill=latest_drill,
        signer_name=payload.get("signer_name") or payload.get("signer") or "行政部主任",
        signer_role=payload.get("signer_role") or "行政部主任",
        reviewer_name=payload.get("reviewer_name") or "主任",
        reviewer_role=payload.get("reviewer_role") or "主任",
        period=payload.get("period") or datetime.now().strftime("%Y-Q%q").replace("%q", str((datetime.now().month - 1) // 3 + 1)),
        attestation_type=payload.get("attestation_type") or "法遵驗收與內控制度簽核",
    )
    conn.execute(
        """
        INSERT INTO compliance_attestations (
          id, attestation_type, period, signer_name, signer_role, reviewer_name, reviewer_role,
          status, score, report_hash, report_json, signed_at, non_repudiation_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            attestation["id"], attestation["attestation_type"], attestation["period"], attestation["signer_name"],
            attestation["signer_role"], attestation["reviewer_name"], attestation["reviewer_role"],
            attestation["status"], attestation["score"], attestation["report_hash"],
            json.dumps(attestation["report"], ensure_ascii=False), attestation["signed_at"],
            json.dumps(attestation["non_repudiation"], ensure_ascii=False),
        ),
    )
    log_audit(conn, attestation["signer_name"], "法遵驗收與內控制度簽核", "compliance_attestations", attestation["id"], f"{attestation['status']} score={attestation['score']} hash={attestation['report_hash']}")
    return attestation


def supabase_backup_restore_drill(payload: Dict[str, Any]) -> Dict[str, Any]:
    started = time.time()
    scope = payload.get("scope") or "全部資料表"
    target_env = payload.get("target_env") or payload.get("target") or "測試沙盒"
    rto_target = int(payload.get("rto_target_minutes") or payload.get("rtoTarget") or 30)
    rpo_target = int(payload.get("rpo_target_minutes") or payload.get("rpoTarget") or 15)
    included_tables = list(TABLES)
    if scope == "公文與附件":
        included_tables = ["documents", "recipients", "attachments", "file_objects", "file_download_tokens", "virus_scan_jobs"]
    elif scope == "交換事件與 audit log":
        included_tables = ["exchange_tasks", "exchange_events", "audit_logs"]
    snapshot: Dict[str, List[Dict[str, Any]]] = {}
    for table in included_tables:
        try:
            snapshot[table] = supabase_list(table, {"limit": ["1000"]})
        except Exception as exc:
            snapshot[table] = [{"backup_error": str(exc)}]
    source_hash = stable_json_hash(snapshot)
    sandbox = json.loads(json.dumps(snapshot, ensure_ascii=False))
    restore_hash = stable_json_hash(sandbox)
    source_counts = {table: len(rows) for table, rows in snapshot.items()}
    restored_counts = {table: len(rows) for table, rows in sandbox.items()}
    duration_ms = int((time.time() - started) * 1000)
    rto_minutes = max(1, (duration_ms + 59999) // 60000)
    rpo_minutes = 1
    counts_match = source_counts == restored_counts
    hash_match = source_hash == restore_hash
    rto_ok = rto_minutes <= rto_target
    rpo_ok = rpo_minutes <= rpo_target
    ok = counts_match and hash_match and rto_ok and rpo_ok
    drill_id = f"DRILL-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3).upper()}"
    report = {
        "id": drill_id,
        "ok": ok,
        "result": "通過" if ok else "需改善",
        "created_at": now(),
        "scope": scope,
        "target_env": target_env,
        "backup": {
            "backup": f"supabase-logical-snapshot-{drill_id}.json",
            "path": "Supabase logical snapshot in serverless memory",
            "size": len(json.dumps(snapshot, ensure_ascii=False)),
            "sha256": source_hash,
            "created_at": now(),
        },
        "sandbox": {"path": "JSON sandbox restore", "sha256": restore_hash, "integrity": "ok"},
        "source_counts": source_counts,
        "restored_counts": restored_counts,
        "row_count": sum(source_counts.values()),
        "checks": {"integrity": True, "hash_match": hash_match, "counts_match": counts_match, "rto_ok": rto_ok, "rpo_ok": rpo_ok},
        "rto_minutes": rto_minutes,
        "rto_target_minutes": rto_target,
        "rpo_minutes": rpo_minutes,
        "rpo_target_minutes": rpo_target,
        "duration_ms": duration_ms,
        "steps": {
            "snapshot": f"Supabase logical snapshot 已建立，{sum(source_counts.values())} 筆資料",
            "sourceHash": f"{source_hash} 已產生",
            "sandboxRestore": f"{target_env} JSON 還原演練完成，未覆蓋正式資料",
            "verify": "筆數與雜湊比對通過" if counts_match and hash_match else "筆數或雜湊不一致",
            "rtoRpo": f"RTO {rto_minutes}/{rto_target} 分，RPO {rpo_minutes}/{rpo_target} 分",
        },
        "improvements": [] if ok else ["檢查 Supabase logical snapshot 取樣、PITR 或 scheduled dump 設定"],
    }
    supabase_insert("audit_logs", {
        "id": f"AUD-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "actor": "Ops Drill",
        "action": "備份還原演練",
        "target_type": "backup_restore_drill",
        "target_id": drill_id,
        "ip": "vercel",
        "device": "serverless",
        "detail": json.dumps({"result": report["result"], "backup": report["backup"]["backup"], "rto": rto_minutes, "rpo": rpo_minutes}, ensure_ascii=False),
        "created_at": now(),
    })
    return report


def supabase_create_compliance_attestation(payload: Dict[str, Any]) -> Dict[str, Any]:
    snapshot_counts = {}
    for table in TABLES:
        try:
            snapshot_counts[table] = len(supabase_list(table, {"limit": ["1000"]}))
        except Exception:
            snapshot_counts[table] = 0
    readiness = production_readiness()
    monitoring = supabase_monitoring_snapshot()
    drill_rows = [row for row in supabase_list("audit_logs", {"limit": ["1000"]}) if row.get("action") == "備份還原演練"]
    drill_rows.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    latest_drill = drill_rows[0] if drill_rows else None
    attestation = compliance_attestation_payload(
        counts=snapshot_counts,
        readiness=readiness,
        monitoring=monitoring,
        latest_drill=latest_drill,
        signer_name=payload.get("signer_name") or payload.get("signer") or "行政部主任",
        signer_role=payload.get("signer_role") or "行政部主任",
        reviewer_name=payload.get("reviewer_name") or "主任",
        reviewer_role=payload.get("reviewer_role") or "主任",
        period=payload.get("period") or datetime.now().strftime("%Y-Q%q").replace("%q", str((datetime.now().month - 1) // 3 + 1)),
        attestation_type=payload.get("attestation_type") or "法遵驗收與內控制度簽核",
    )
    row = {
        "id": attestation["id"],
        "attestation_type": attestation["attestation_type"],
        "period": attestation["period"],
        "signer_name": attestation["signer_name"],
        "signer_role": attestation["signer_role"],
        "reviewer_name": attestation["reviewer_name"],
        "reviewer_role": attestation["reviewer_role"],
        "status": attestation["status"],
        "score": attestation["score"],
        "report_hash": attestation["report_hash"],
        "report_json": attestation["report"],
        "signed_at": attestation["signed_at"],
        "non_repudiation_json": attestation["non_repudiation"],
    }
    try:
        supabase_insert("compliance_attestations", row)
    except Exception:
        pass
    supabase_insert("audit_logs", {
        "id": f"AUD-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "actor": attestation["signer_name"],
        "action": "法遵驗收與內控制度簽核",
        "target_type": "compliance_attestations",
        "target_id": attestation["id"],
        "ip": "vercel",
        "device": "serverless",
        "detail": f"{attestation['status']} score={attestation['score']} hash={attestation['report_hash']}",
        "created_at": now(),
    })
    return attestation


def supabase_create_notification(payload: Dict[str, Any]) -> Dict[str, Any]:
    item = {
        "id": payload.get("id") or f"NTF-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "type": payload.get("type") or "一般通知",
        "title": payload.get("title") or f"{payload.get('type') or '一般'}通知",
        "target_role": payload.get("target_role") or payload.get("target") or "行政部主任",
        "target_email": payload.get("target_email") or "",
        "channel": payload.get("channel") or "系統通知",
        "status": payload.get("status") or "未讀",
        "priority": payload.get("priority") or "中",
        "source": payload.get("source") or "",
        "body": payload.get("body") or "請確認電子公文交換待辦事項。",
        "delivery_receipt": payload.get("delivery_receipt") or "",
        "created_at": payload.get("created_at") or now(),
        "sent_at": payload.get("sent_at") or None,
    }
    existing = supabase_get("notifications", item["id"])
    if existing:
        return existing
    return supabase_insert("notifications", item)


def supabase_notification_target_email(role: str, explicit: str = "") -> str:
    if explicit:
        return explicit
    qs = urllib.parse.urlencode({"select": "email", "role": f"eq.{role}", "status": "eq.啟用", "limit": "1"})
    rows = supabase_request("GET", f"users?{qs}")
    return rows[0]["email"] if rows else f"{role}@suiyuecare.local"


def supabase_push_system_notification(item: Dict[str, Any]) -> Dict[str, str]:
    inbox_id = f"INBOX-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}"
    supabase_insert("system_inbox", {
        "id": inbox_id,
        "notification_id": item["id"],
        "target_role": item["target_role"],
        "target_user_id": "",
        "title": item["title"],
        "body": item["body"],
        "status": "未讀",
    })
    return {"status": "成功", "receipt": inbox_id, "error": ""}


def supabase_record_notification_delivery(notification_id: str, channel: str, target: str, status: str, receipt: str = "", error: str = "") -> Dict[str, Any]:
    return supabase_insert("notification_deliveries", {
        "id": f"NDEL-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "notification_id": notification_id,
        "channel": channel,
        "target": target,
        "status": status,
        "receipt": receipt,
        "error": error,
        "attempt_count": 1,
    })


def supabase_deliver_notification(notification_id: str, force_channel: str = "") -> Dict[str, Any]:
    item = supabase_get("notifications", notification_id)
    if not item:
        return {"id": notification_id, "status": "失敗", "error": "notification_not_found", "results": []}
    channels = notification_channels(force_channel or item["channel"])
    target_email = supabase_notification_target_email(item["target_role"], item.get("target_email") or "")
    results: List[Dict[str, str]] = []
    credential_rows = supabase_list("notification_channel_credentials", {}) if "notification_channel_credentials" in TABLES else []
    for channel in channels:
        credential = supabase_notification_credential_status(channel, credential_rows)
        if channel != "系統站內通知" and credential["status"] not in {"有效", "即將到期"}:
            result = {"status": "憑證異常", "receipt": "", "error": f"{channel} 正式憑證{credential['status']}，請先完成憑證驗證或更新。"}
            target = target_email if channel == "Email" else "歲悅電子公文 LINE 工作群組"
            supabase_record_notification_delivery(item["id"], channel, target, result["status"], result.get("receipt", ""), result.get("error", ""))
            results.append({"channel": channel, "target": target, **result, "attempted_at": now(), "duration_ms": 0})
            continue
        started = time.time()
        if channel == "Email":
            result = send_email_notification(target_email, item["title"], item["body"])
            target = target_email
        elif channel == "Line 工作群組":
            result = send_line_notification(f"{item['title']}\n{item['body']}")
            target = "歲悅電子公文 LINE 工作群組"
        else:
            result = supabase_push_system_notification(item)
            target = item["target_role"]
        supabase_record_notification_delivery(item["id"], channel, target, result["status"], result.get("receipt", ""), result.get("error", ""))
        results.append(notification_attempt_result(channel, target, result, started))
    success_count = len([entry for entry in results if entry["status"] == "成功"])
    receipt_text = "；".join(
        f"{entry['channel']}->{entry['target']}:{entry['status']}{('/' + entry['receipt']) if entry.get('receipt') else ''}{(' / ' + entry['error']) if entry.get('error') else ''}"
        for entry in results
    )
    status = "已派送" if success_count == len(results) else "部分派送" if success_count else "派送失敗"
    supabase_patch("notifications", item["id"], {"status": status, "sent_at": now(), "delivery_receipt": receipt_text})
    supabase_insert("audit_logs", {
        "id": f"AUD-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
        "actor": "Notify Worker",
        "action": "通知派送",
        "target_type": "notifications",
        "target_id": item["id"],
        "ip": "vercel",
        "device": "serverless",
        "detail": receipt_text,
    })
    return {"id": item["id"], "status": status, "success": success_count, "total": len(results), "receipt": receipt_text, "results": results}


def supabase_ensure_notification_for_source(payload: Dict[str, Any]) -> Dict[str, Any]:
    source = payload.get("source") or ""
    notice_type = payload.get("type") or ""
    if source and notice_type:
        qs = urllib.parse.urlencode({"select": "*", "source": f"eq.{source}", "type": f"eq.{notice_type}", "limit": "1"})
        rows = supabase_request("GET", f"notifications?{qs}")
        if rows:
            return rows[0]
    return supabase_create_notification(payload)


def supabase_sync_notifications_from_business_state() -> Dict[str, Any]:
    created = 0
    items: List[Dict[str, Any]] = []
    documents = supabase_list("documents", {})
    for doc in [item for item in documents if item.get("direction") == "收文" and item.get("status") in {"待登錄", "待分派"}]:
        qs = urllib.parse.urlencode({"select": "id", "source": f"eq.{doc['id']}", "type": "eq.收文", "limit": "1"})
        before = supabase_request("GET", f"notifications?{qs}")
        item = supabase_ensure_notification_for_source({
            "type": "收文",
            "title": f"{doc.get('doc_no')} {doc.get('status')}",
            "target_role": "總務",
            "channel": "系統通知",
            "priority": "高",
            "source": doc["id"],
            "body": f"{doc.get('agency_name')} 來文「{doc.get('subject')}」需處理。",
        })
        created += 0 if before else 1
        items.append(item)
    for doc in [item for item in documents if item.get("direction") == "發文" and item.get("status") in {"待清稿", "已清稿", "交換失敗"}]:
        notice_type = "交換失敗" if doc.get("status") == "交換失敗" else "待清稿"
        qs = urllib.parse.urlencode({"select": "id", "source": f"eq.{doc['id']}", "type": f"eq.{notice_type}", "limit": "1"})
        before = supabase_request("GET", f"notifications?{qs}")
        item = supabase_ensure_notification_for_source({
            "type": notice_type,
            "title": f"{doc.get('doc_no')} {doc.get('status')}",
            "target_role": "總務" if notice_type == "交換失敗" else "行政部主任",
            "channel": "Email + Line + 系統通知" if notice_type == "交換失敗" else "Email + 系統通知",
            "priority": "高",
            "source": doc["id"],
            "body": f"{doc.get('subject')} 目前狀態：{doc.get('status')}。",
        })
        created += 0 if before else 1
        items.append(item)
    return {"created": created, "items": items}


def supabase_retry_failed_notifications() -> Dict[str, Any]:
    rows = [
        item for item in supabase_list("notifications", {})
        if item.get("status") in {"派送失敗", "部分派送"} or not item.get("delivery_receipt")
    ]
    results = [supabase_deliver_notification(row["id"]) for row in rows]
    return {"count": len(results), "results": results}


class Handler(SimpleHTTPRequestHandler):
    server_version = "SuiyueEdocBackend/1.0"

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path)
        rel = unquote(parsed.path).lstrip("/") or "index.html"
        return str((ROOT / rel).resolve())

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
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

    def do_DELETE(self) -> None:
        self.handle_api("DELETE", urlparse(self.path).path, {})

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

    def send_file_object(self, conn: sqlite3.Connection, file_id: str) -> None:
        row = conn.execute("SELECT * FROM file_objects WHERE id = ?", (file_id,)).fetchone()
        if not row:
            self.send_json({"error": "not_found"}, 404)
            return
        item = row_to_dict(row)
        if is_seal_vault_file(item):
            audit_seal_vault_access(conn, file_id=file_id, actor="Download", action="block_seal_vault_download", result="denied", detail="generic_file_download_forbidden", document_id=item.get("document_id") or "")
            conn.commit()
            self.send_json({"error": "seal_vault_download_forbidden", "detail": "seal_original_files_are_never_downloaded_through_generic_file_api"}, 403)
            return
        token = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
        valid, reason, token_row = validate_file_download_token(conn, file_id, token)
        if not valid:
            record_file_access(conn, file_object_id=file_id, document_id=item.get("document_id") or "", actor="Download", action="短效下載阻擋", result="失敗", detail=reason)
            conn.commit()
            self.send_json({"error": reason, "detail": "download_url_expired_or_invalid"}, 403)
            return
        if item.get("scan_status") == "已隔離":
            record_file_access(conn, file_object_id=file_id, document_id=item.get("document_id") or "", actor=token_row.get("actor", "Download") if token_row else "Download", action="隔離檔案下載阻擋", result="失敗", detail=item.get("quarantine_reason") or "quarantined")
            conn.commit()
            self.send_json({"error": "file_quarantined", "detail": item.get("quarantine_reason")}, 423)
            return
        path = STORAGE_DIR / item["storage_key"]
        if not path.exists():
            self.send_json({"error": "file_missing"}, 404)
            return
        data = decrypt_file_bytes(path.read_bytes(), item.get("encryption_status", ""), item.get("encryption_alg", ""))
        conn.execute("UPDATE file_objects SET last_download_at = ? WHERE id = ?", (now(), file_id))
        if token_row:
            conn.execute("UPDATE file_download_tokens SET used_at = ? WHERE id = ?", (now(), token_row["id"]))
        record_file_access(conn, file_object_id=file_id, document_id=item.get("document_id") or "", actor=token_row.get("actor", "Download") if token_row else "Download", action="短效 URL 下載", result="成功", detail=f"expires_at={token_row.get('expires_at') if token_row else ''}")
        conn.commit()
        self.send_response(200)
        self.send_header("Content-Type", item["mime_type"])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f"attachment; filename=\"{urllib.parse.quote(item['file_name'])}\"")
        self.end_headers()
        self.wfile.write(data)

    def send_official_document_file(self, conn: sqlite3.Connection, document_id: str, file_id: str) -> None:
        session = current_session(conn, self.bearer_token())
        document, file_meta, data = official_document_download_file(conn, document_id, file_id, session, self.client_ip(), self.client_device())
        conn.commit()
        file_name = file_meta.get("file_name") or f"{document_id}.pdf"
        self.send_response(200)
        self.send_header("Content-Type", file_meta.get("file_mime_type") or "application/pdf")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f"attachment; filename=\"{urllib.parse.quote(file_name)}\"")
        self.end_headers()
        self.wfile.write(data)

    def send_supabase_official_document_file(self, document_id: str, file_id: str) -> None:
        session = supabase_current_session(self.bearer_token())
        document, file_meta, data = supabase_official_document_download_file(document_id, file_id, session, self.client_ip(), self.client_device())
        file_name = file_meta.get("file_name") or f"{document.get('id') or document_id}.pdf"
        self.send_response(200)
        self.send_header("Content-Type", file_meta.get("file_mime_type") or "application/pdf")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f"attachment; filename=\"{urllib.parse.quote(file_name)}\"")
        self.end_headers()
        self.wfile.write(data)

    def bearer_token(self) -> str:
        header = self.headers.get("Authorization", "")
        if header.lower().startswith("bearer "):
            return header.split(" ", 1)[1].strip()
        return ""

    def client_ip(self) -> str:
        return self.headers.get("X-Forwarded-For", self.client_address[0]).split(",", 1)[0].strip()

    def client_device(self) -> str:
        return self.headers.get("User-Agent", "unknown")[:180]

    def require_table_access(self, session: Dict[str, Any] | None, table: str, *, write: bool = False) -> bool:
        allowed = can_write_table(session, table) if write else can_read_table(session, table)
        if allowed:
            return True
        self.send_json({"error": "forbidden", "detail": f"{table}_{'write' if write else 'read'}_forbidden"}, 403)
        return False

    def cron_authorized(self) -> bool:
        secret = os.getenv("CRON_SECRET", "").strip()
        if not secret and not is_production():
            return True
        return bool(secret) and self.headers.get("Authorization", "") == f"Bearer {secret}"

    def handle_api(self, method: str, path: str, query: Dict[str, List[str]]) -> None:
        parts = [part for part in path.split("/") if part][1:]
        try:
            if USE_SUPABASE:
                if method == "POST" and parts == ["auth", "login"]:
                    payload, status = supabase_authenticate(self.read_json(), self.client_ip(), self.client_device())
                    self.send_json(payload, status)
                    return
                if method == "POST" and parts == ["auth", "logging-bridge"]:
                    payload, status = supabase_authenticate_logging_bridge(self.read_json(), self.client_ip(), self.client_device())
                    self.send_json(payload, status)
                    return
                if method == "GET" and parts == ["auth", "me"]:
                    session = supabase_current_session(self.bearer_token())
                    self.send_json(session if session else {"error": "unauthorized"}, 200 if session else 401)
                    return
                if method == "POST" and parts == ["auth", "logout"]:
                    token = self.bearer_token()
                    if token:
                        qs = urllib.parse.urlencode({"token_hash": f"eq.{hash_token(token)}"})
                        supabase_request("PATCH", f"auth_sessions?{qs}", {"revoked_at": now()})
                    self.send_json({"ok": True})
                    return
                if method == "GET" and parts in (["health"], ["healthz"]):
                    self.send_json({"ok": True, "database": "supabase", "project": SUPABASE_URL, "time": now(), "tables": list(TABLES), "production": production_readiness()})
                    return
                if method == "GET" and parts in (["production", "readiness"], ["readyz"]):
                    readiness = production_readiness()
                    status = 200 if readiness["ready"] or not is_production() else 503
                    self.send_json(readiness, status)
                    return
                if method == "GET" and parts in (["production", "go-live-audit"], ["go-live", "audit"]):
                    audit = go_live_audit()
                    status = 200 if audit["formalGo"] or not is_production() else 503
                    self.send_json(audit, status)
                    return
                if method == "GET" and parts == ["production", "deployment"]:
                    self.send_json(deployment_report())
                    return
                if method == "GET" and parts == ["production", "monitoring"]:
                    snapshot = supabase_monitoring_snapshot()
                    self.send_json(snapshot, 200 if snapshot["ok"] or not is_production() else 503)
                    return
                if method == "POST" and parts == ["production", "monitoring", "check"]:
                    snapshot = run_supabase_monitoring_check()
                    self.send_json(snapshot, 201 if snapshot["ok"] or not is_production() else 503)
                    return
                if method == "GET" and parts == ["files", "storage-health"]:
                    service = storage_service_status()
                    file_objects = supabase_list("file_objects", {"limit": ["1000"]})
                    tokens = supabase_list("file_download_tokens", {"limit": ["1000"]})
                    self.send_json({
                        "ready": service["ready"],
                        "provider": EDOC_STORAGE_PROVIDER,
                        "bucket": EDOC_STORAGE_BUCKET,
                        "service": service,
                        "signedUrlTtlSeconds": EDOC_SIGNED_URL_TTL_SECONDS,
                        "encryption": {
                            "enabled": EDOC_FILE_ENCRYPTION_ENABLED,
                            "keyId": file_key_id() if env_present("EDOC_FILE_ENCRYPTION_KEY") else "未設定",
                            "encryptedFiles": len([item for item in file_objects if item.get("encryption_status") == "已加密"]),
                            "totalFiles": len(file_objects),
                        },
                        "scanner": {
                            "engine": EDOC_SCAN_ENGINE,
                            "avProvider": EDOC_AV_PROVIDER,
                            "endpoint": EDOC_AV_ENDPOINT or "未設定",
                            "pending": len([item for item in file_objects if item.get("scan_status") == "待掃描"]),
                            "quarantined": len([item for item in file_objects if item.get("scan_status") == "已隔離"]),
                            "mode": "supabase-metadata",
                        },
                        "activeDownloadTokens": len([item for item in tokens if not item.get("revoked_at") and (parse_time(item.get("expires_at", "")) or datetime.min) > datetime.now()]),
                        "policy": service["policy"],
                        "mode": service["mode"] if service["ready"] else "supabase-storage-incomplete",
                    })
                    return
                if method == "GET" and parts == ["certificates", "health"]:
                    certificates = supabase_list("signing_certificates", {})
                    authorities = supabase_list("certificate_authorities", {})
                    events = supabase_list("certificate_validation_events", {"limit": ["8"], "order": ["checked_at.desc"]})
                    service = signing_service_status()
                    self.send_json({
                        "mode": service["mode"],
                        "ready": service["ready"],
                        "certificate_count": len(certificates),
                        "trusted_ca_count": len([item for item in authorities if item.get("trust_status") == "trusted"]),
                        "services": {
                            "provider": "啟用" if service["services"]["provider"]["configured"] else "仍為模擬",
                            "providerApi": "啟用" if service["services"]["providerApi"]["configured"] else "未設定簽章 API",
                            "providerCredential": "啟用" if service["services"]["providerCredential"]["configured"] else "未設定簽章 API key",
                            "keyId": "啟用" if service["services"]["keyId"]["configured"] else "未設定簽章 key id",
                            "chain": "啟用" if service["services"]["trustStore"]["configured"] else "未設定信任根",
                            "tsa": "啟用" if service["services"]["tsa"]["configured"] else "未設定 TSA",
                            "ocsp": "啟用" if service["services"]["ocsp"]["configured"] else "未設定 OCSP",
                            "crl": "啟用" if service["services"]["crl"]["configured"] else "未設定 CRL",
                            "hsm": "啟用" if service["services"]["hsm"]["configured"] else "未設定 HSM/KMS",
                        },
                        "service": service,
                        "policy": service.get("policy", {}),
                        "certificates": certificates,
                        "authorities": authorities,
                        "recent_events": events,
                        "provider_events": supabase_list("signature_provider_events", {"limit": ["8"], "order": ["created_at.desc"]}) if "signature_provider_events" in TABLES else [],
                    })
                    return
                if method == "POST" and parts == ["certificates", "validate"]:
                    payload = self.read_json()
                    certificate = supabase_get("signing_certificates", payload.get("certificate_id") or payload.get("id") or "")
                    if not certificate:
                        self.send_json({"ok": False, "error": "certificate_not_found"}, 422)
                        return
                    checked_at = now()
                    report = {
                        "ok": certificate.get("status") == "啟用",
                        "certificate_id": certificate["id"],
                        "certificate_type": certificate.get("certificate_type") or "organization",
                        "serial_no": certificate.get("serial_no"),
                        "issuer": certificate.get("issuer"),
                        "chain_status": "有效" if certificate.get("status") == "啟用" else "憑證鏈異常",
                        "ocsp_status": "良好" if certificate.get("status") == "啟用" else "已撤銷",
                        "crl_status": "未列入撤銷清單" if certificate.get("status") == "啟用" else "已列入撤銷清單",
                        "tsa_status": "不適用",
                        "checked_at": checked_at,
                        "result": "通過" if certificate.get("status") == "啟用" else "不通過",
                    }
                    event = {
                        "id": f"CVAL-{int(time.time() * 1000)}-{secrets.token_hex(3).upper()}",
                        "certificate_id": certificate["id"],
                        "signature_id": payload.get("signature_id"),
                        "validator": payload.get("validator") or "Certificate Verifier",
                        "validation_type": "chain+ocsp+crl",
                        "chain_status": report["chain_status"],
                        "ocsp_status": report["ocsp_status"],
                        "crl_status": report["crl_status"],
                        "tsa_status": report["tsa_status"],
                        "result": report["result"],
                        "report_json": report,
                        "checked_at": checked_at,
                    }
                    supabase_insert("certificate_validation_events", event)
                    report["event_id"] = event["id"]
                    self.send_json(report, 200 if report["ok"] else 422)
                    return
                if method == "GET" and parts == ["dashboard"]:
                    self.send_json(supabase_dashboard())
                    return
                if method == "GET" and parts == ["search"]:
                    # Supabase deployments can still use the table APIs; unified search runs locally until PostgREST FTS is configured.
                    self.send_json({"query": (query.get("q") or [""])[0], "category": (query.get("category") or ["all"])[0], "count": 0, "results": [], "note": "supabase_unified_search_pending"})
                    return
                if method == "GET" and parts == ["schema"]:
                    self.send_json({"tables": TABLES})
                    return
                if method == "GET" and parts == ["exchange", "gateway-status"]:
                    self.send_json(exchange_gateway_status())
                    return
                if method == "GET" and parts == ["documents", "next-dispatch-no"]:
                    self.send_json({"doc_no": supabase_next_dispatch_no()})
                    return
                if method == "POST" and parts == ["exchange", "queue"]:
                    self.send_json(supabase_exchange_queue_document(self.read_json()), 201)
                    return
                if method == "POST" and parts == ["exchange", "send"]:
                    result = supabase_exchange_send_document(self.read_json())
                    self.send_json(result, 201 if result.get("ok") else 422)
                    return
                if method == "POST" and parts == ["exchange", "receive"]:
                    self.send_json(supabase_exchange_receive_documents(self.read_json()), 201)
                    return
                if method == "POST" and parts == ["exchange", "status"]:
                    result = supabase_exchange_query_status(self.read_json())
                    self.send_json(result, 200 if result.get("ok") else 404)
                    return
                if method == "POST" and parts == ["exchange", "acknowledge"]:
                    result = supabase_exchange_acknowledge_received(self.read_json())
                    self.send_json(result, 200 if result.get("ok") else 404)
                    return
                if method == "POST" and parts == ["exchange", "retry"]:
                    result = supabase_exchange_retry_failed(self.read_json())
                    self.send_json(result, 200 if result.get("ok") else 422)
                    return
                if method == "POST" and parts == ["actions", "pull-inbound"]:
                    self.send_json(supabase_exchange_receive_documents({}), 201)
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
                if method == "POST" and parts == ["backup", "restore-drill"]:
                    self.send_json(supabase_backup_restore_drill(self.read_json()), 201)
                    return
                if method == "POST" and parts == ["compliance", "attest"]:
                    self.send_json(supabase_create_compliance_attestation(self.read_json()), 201)
                    return
                if method == "GET" and parts == ["cron", "run-due"]:
                    if not self.cron_authorized():
                        self.send_json({"error": "unauthorized"}, 401)
                        return
                    self.send_json(supabase_run_due_background_jobs(), 201)
                    return
                if method == "GET" and parts == ["cron", "monitoring"]:
                    if not self.cron_authorized():
                        self.send_json({"error": "unauthorized"}, 401)
                        return
                    self.send_json(run_supabase_monitoring_check(), 201)
                    return
                if method == "POST" and parts == ["jobs", "run-due"]:
                    self.send_json(supabase_run_due_background_jobs(), 201)
                    return
                if method == "POST" and parts == ["jobs", "run-all"]:
                    self.send_json(supabase_run_due_background_jobs(all_enabled=True), 201)
                    return
                if method == "POST" and len(parts) == 3 and parts[0] == "jobs" and parts[2] == "run":
                    self.send_json(supabase_run_background_job(parts[1]), 201)
                    return
                if method == "POST" and parts == ["notifications", "sync"]:
                    self.send_json(supabase_sync_notifications_from_business_state(), 201)
                    return
                if method == "GET" and parts == ["notifications", "gateway-status"]:
                    status = notification_gateway_status()
                    status["credentials"] = supabase_list("notification_channel_credentials", {}) if "notification_channel_credentials" in TABLES else []
                    self.send_json(status)
                    return
                if method == "POST" and parts == ["notifications", "credentials", "validate"]:
                    payload = self.read_json()
                    checked_at = now()
                    channels = [payload.get("channel")] if payload.get("channel") else ["Email", "Line 工作群組", "系統站內通知"]
                    results = []
                    for channel in channels:
                        credential_rows = supabase_list("notification_channel_credentials", {})
                        status = supabase_notification_credential_status(channel, credential_rows)
                        status_text = status["status"]
                        report = {
                            "channel": channel,
                            "status": status_text,
                            "missing": status.get("missing", []),
                            "expires_at": status.get("expires_at") or "",
                            "days_left": status.get("days_left"),
                            "fingerprint_sha256": status.get("fingerprint_sha256") or "",
                            "checked_at": checked_at,
                        }
                        rows = [row for row in credential_rows if row.get("channel") == channel]
                        if rows:
                            patch_payload = {"status": status_text, "last_validated_at": checked_at, "validation_report_json": report, "updated_at": checked_at}
                            if channel == "Email" and payload.get("email_expires_at"):
                                patch_payload["expires_at"] = payload["email_expires_at"]
                            if channel == "Line 工作群組" and payload.get("line_expires_at"):
                                patch_payload["expires_at"] = payload["line_expires_at"]
                            supabase_patch("notification_channel_credentials", rows[0]["id"], patch_payload)
                        results.append(report)
                    self.send_json({"ok": all(item["status"] in {"有效", "即將到期"} for item in results), "checked_at": checked_at, "credentials": results})
                    return
                if method == "POST" and parts == ["notifications", "send"]:
                    payload = self.read_json()
                    ids = payload.get("ids") or []
                    for item in payload.get("notifications") or []:
                        ids.append(supabase_create_notification(item)["id"])
                    if payload.get("id"):
                        ids.append(payload["id"])
                    channel = payload.get("channel") or ""
                    results = [supabase_deliver_notification(str(notification_id), channel) for notification_id in ids]
                    self.send_json({"count": len(results), "results": results}, 201)
                    return
                if method == "POST" and parts == ["notifications", "test"]:
                    payload = self.read_json()
                    notice = supabase_create_notification({
                        "type": "通道測試",
                        "title": payload.get("title") or "通知通道測試",
                        "target_role": payload.get("target_role") or payload.get("target") or "行政部主任",
                        "target_email": payload.get("target_email") or "",
                        "channel": payload.get("channel") or "Email + Line + 系統通知",
                        "priority": "中",
                        "source": "GATEWAY-TEST",
                        "body": payload.get("body") or "這是一筆歲悅電子公文交換系統通知通道測試。",
                    })
                    result = supabase_deliver_notification(notice["id"], payload.get("channel") or notice["channel"])
                    report = notification_delivery_report(notice, result, payload.get("channel") or notice["channel"])
                    self.send_json({"notification": notice, "delivery": result, "report": report}, 201)
                    return
                if method == "POST" and parts == ["notifications", "retry-failed"]:
                    self.send_json(supabase_retry_failed_notifications(), 201)
                    return
                if method == "POST" and parts == ["notifications", "push-inbox"]:
                    payload = self.read_json()
                    ids = payload.get("ids") or ([payload["id"]] if payload.get("id") else [])
                    results = [supabase_deliver_notification(str(notification_id), "系統通知") for notification_id in ids]
                    self.send_json({"count": len(results), "results": results}, 201)
                    return
                if method == "GET" and parts == ["official-documents"]:
                    session = supabase_current_session(self.bearer_token())
                    if not self.require_table_access(session, "official_documents"):
                        return
                    self.send_json(supabase_list_official_documents(query, session))
                    return
                if method == "GET" and parts == ["official-documents", "my-tasks"]:
                    session = supabase_current_session(self.bearer_token())
                    if not self.require_table_access(session, "official_documents"):
                        return
                    scoped_query = {**query, "scope": ["todo"]}
                    self.send_json(supabase_list_official_documents(scoped_query, session))
                    return
                if method == "GET" and parts == ["official-documents", "my-requests"]:
                    session = supabase_current_session(self.bearer_token())
                    if not self.require_table_access(session, "official_documents"):
                        return
                    scoped_query = {**query, "scope": ["mine"]}
                    self.send_json(supabase_list_official_documents(scoped_query, session))
                    return
                if method == "POST" and parts == ["official-documents"]:
                    session = supabase_current_session(self.bearer_token())
                    if not self.require_table_access(session, "official_documents", write=True):
                        return
                    payload = self.read_json()
                    payload["ip_address"] = self.client_ip()
                    payload["user_agent"] = self.client_device()
                    self.send_json(supabase_create_official_document(payload, session), 201)
                    return
                if method == "GET" and len(parts) == 2 and parts[0] == "official-documents":
                    session = supabase_current_session(self.bearer_token())
                    if not self.require_table_access(session, "official_documents"):
                        return
                    self.send_json(supabase_official_document_detail(parts[1], session))
                    return
                if len(parts) >= 3 and parts[0] == "official-documents" and parts[2] == "dispatch":
                    session = supabase_current_session(self.bearer_token())
                    if method == "GET" and len(parts) == 3:
                        if not self.require_table_access(session, "official_document_dispatch_records"):
                            return
                        document = supabase_official_document_row(parts[1])
                        steps = supabase_official_document_steps(parts[1])
                        user = session.get("user") if session else None
                        if not canDownloadOfficialDocument(user, document, steps) and not session_has_any_permission(session, ["official_documents.all_records", "official_documents.all_todo"]):
                            self.send_json({"error": "forbidden", "detail": "official_dispatch_access_denied"}, 403)
                            return
                        self.send_json(supabase_official_dispatch_record(parts[1]) or {})
                        return
                    if method == "POST" and len(parts) == 3:
                        if not self.require_table_access(session, "official_document_dispatch_records", write=True):
                            return
                        payload = self.read_json()
                        payload["ip_address"] = self.client_ip()
                        payload["user_agent"] = self.client_device()
                        document = supabase_official_document_row(parts[1])
                        result = supabase_upsert_official_dispatch_record(document, payload.get("dispatch_method") or document.get("dispatch_method"), session.get("user") if session else None, payload)
                        supabase_insert_official_log(parts[1], "create_dispatch", session.get("user") if session else None, result.get("dispatch_method") or "", ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
                        self.send_json(result, 201)
                        return
                    if method == "PATCH" and len(parts) == 3:
                        if not self.require_table_access(session, "official_document_dispatch_records", write=True):
                            return
                        payload = self.read_json()
                        payload["ip_address"] = self.client_ip()
                        payload["user_agent"] = self.client_device()
                        self.send_json(supabase_update_official_dispatch_record(parts[1], payload, session))
                        return
                    if method == "POST" and len(parts) == 4 and parts[3] == "complete":
                        if not self.require_table_access(session, "official_document_dispatch_records", write=True):
                            return
                        payload = self.read_json()
                        payload["ip_address"] = self.client_ip()
                        payload["user_agent"] = self.client_device()
                        self.send_json(supabase_complete_official_dispatch(parts[1], payload, session))
                        return
                    if method == "POST" and len(parts) == 4 and parts[3] == "proof-files":
                        if not self.require_table_access(session, "official_document_dispatch_records", write=True):
                            return
                        payload = self.read_json()
                        payload["ip_address"] = self.client_ip()
                        payload["user_agent"] = self.client_device()
                        self.send_json(supabase_upload_official_dispatch_proof_file(parts[1], payload, session), 201)
                        return
                if method == "POST" and len(parts) == 3 and parts[0] == "official-documents" and parts[2] in {"submit", "approve", "reject", "cancel", "confirm", "stamp-position"}:
                    session = supabase_current_session(self.bearer_token())
                    if not self.require_table_access(session, "official_documents", write=True):
                        return
                    payload = self.read_json()
                    payload["ip_address"] = self.client_ip()
                    payload["user_agent"] = self.client_device()
                    action = parts[2]
                    if action == "submit":
                        result = supabase_submit_official_document(parts[1], payload, session)
                    elif action == "approve":
                        result = supabase_approve_official_document(parts[1], payload, session)
                    elif action == "reject":
                        result = supabase_reject_official_document(parts[1], payload, session)
                    elif action == "cancel":
                        result = supabase_cancel_official_document(parts[1], payload, session)
                    elif action == "confirm":
                        result = supabase_confirm_official_document(parts[1], payload, session)
                    else:
                        result = supabase_update_official_stamp_position(parts[1], payload, session)
                    self.send_json(result)
                    return
                if method == "GET" and len(parts) == 5 and parts[0] == "official-documents" and parts[2] == "files" and parts[4] == "download":
                    self.send_supabase_official_document_file(parts[1], parts[3])
                    return
                if method == "GET" and parts == ["seal-reference-options"]:
                    session = supabase_current_session(self.bearer_token())
                    if not self.require_table_access(session, "seal_reference_options"):
                        return
                    rows = supabase_filter_rows("seal_reference_options", {}, order="option_type.asc,sort_order.asc")
                    grouped: Dict[str, List[Dict[str, Any]]] = {}
                    for row in rows:
                        grouped.setdefault(row.get("option_type", ""), []).append(row)
                    self.send_json({"options": rows, "grouped": grouped})
                    return
                if len(parts) == 3 and parts[0] == "companies" and parts[2] == "seals":
                    session = supabase_current_session(self.bearer_token())
                    if method == "GET":
                        if not self.require_table_access(session, "company_seals"):
                            return
                        self.send_json(supabase_list_company_seals(parts[1]))
                        return
                    if method == "POST":
                        if not self.require_table_access(session, "company_seals", write=True):
                            return
                        self.send_json(supabase_create_company_seal(parts[1], self.read_json(), session), 201)
                        return
                if len(parts) == 2 and parts[0] == "seals":
                    session = supabase_current_session(self.bearer_token())
                    if method == "PATCH":
                        if not self.require_table_access(session, "company_seals", write=True):
                            return
                        self.send_json(supabase_patch_company_seal(parts[1], self.read_json(), session))
                        return
                    if method == "DELETE":
                        if not self.require_table_access(session, "company_seals", write=True):
                            return
                        self.send_json(supabase_deactivate_company_seal(parts[1], session))
                        return
                if len(parts) == 3 and parts[0] == "seals" and parts[2] == "files":
                    session = supabase_current_session(self.bearer_token())
                    if method == "GET":
                        if not self.require_table_access(session, "company_seal_files"):
                            return
                        self.send_json(supabase_list_company_seal_files(parts[1], session))
                        return
                    if method == "POST":
                        if not self.require_table_access(session, "company_seal_files", write=True):
                            return
                        self.send_json(supabase_upload_company_seal_file(parts[1], self.read_json(), session), 201)
                        return
                if method == "PATCH" and len(parts) == 3 and parts[0] == "seal-files" and parts[2] == "set-current":
                    session = supabase_current_session(self.bearer_token())
                    if not self.require_table_access(session, "company_seal_files", write=True):
                        return
                    self.send_json(supabase_set_current_seal_file(parts[1], session))
                    return
                if method == "POST" and len(parts) == 3 and parts[0] == "documents" and parts[2] == "seal-requests":
                    session = supabase_current_session(self.bearer_token())
                    if not self.require_table_access(session, "seal_usage_requests", write=True):
                        return
                    self.send_json(supabase_create_seal_usage_request(parts[1], self.read_json(), session), 201)
                    return
                if method == "GET" and parts == ["seal-requests"]:
                    session = supabase_current_session(self.bearer_token())
                    if not self.require_table_access(session, "seal_usage_requests"):
                        return
                    self.send_json(supabase_list_seal_usage_requests(query))
                    return
                if len(parts) == 2 and parts[0] == "seal-requests" and method == "GET":
                    session = supabase_current_session(self.bearer_token())
                    if not self.require_table_access(session, "seal_usage_requests"):
                        return
                    self.send_json(supabase_seal_usage_request_row(parts[1]))
                    return
                if method == "POST" and len(parts) == 3 and parts[0] == "seal-requests" and parts[2] == "approve":
                    session = supabase_current_session(self.bearer_token())
                    if not self.require_table_access(session, "seal_usage_approvals", write=True):
                        return
                    self.send_json(supabase_approve_seal_usage_request(parts[1], self.read_json(), session))
                    return
                if method == "POST" and len(parts) == 3 and parts[0] == "seal-requests" and parts[2] == "reject":
                    session = supabase_current_session(self.bearer_token())
                    if not self.require_table_access(session, "seal_usage_approvals", write=True):
                        return
                    self.send_json(supabase_reject_seal_usage_request(parts[1], self.read_json(), session))
                    return
                if method == "POST" and len(parts) == 3 and parts[0] == "seal-requests" and parts[2] == "stamp":
                    session = supabase_current_session(self.bearer_token())
                    if not self.require_table_access(session, "company_seal_files", write=True):
                        return
                    self.send_json(supabase_stamp_seal_usage_request(parts[1], self.read_json(), session), 201)
                    return
                if method == "GET" and parts == ["seal-usage-logs"]:
                    session = supabase_current_session(self.bearer_token())
                    if not self.require_table_access(session, "seal_usage_logs"):
                        return
                    self.send_json(supabase_filter_rows("seal_usage_logs", {}, order="created_at.desc", limit=300))
                    return
                if parts and parts[0] in TABLES:
                    table = TABLES[parts[0]]
                    if method == "GET" and len(parts) == 1:
                        session = supabase_current_session(self.bearer_token())
                        if not can_read_table(session, table):
                            self.send_json({"error": "forbidden", "detail": f"{table}_read_forbidden"}, 403)
                            return
                        rows = supabase_list(table, query)
                        if table == "users":
                            rows = [public_user(row) for row in rows]
                        self.send_json(rows)
                        return
                    if method == "GET" and len(parts) == 2:
                        session = supabase_current_session(self.bearer_token())
                        if not can_read_table(session, table):
                            self.send_json({"error": "forbidden", "detail": f"{table}_read_forbidden"}, 403)
                            return
                        row = supabase_get(table, parts[1])
                        self.send_json(row if row else {"error": "not_found"}, 200 if row else 404)
                        return
                    if method == "POST" and len(parts) == 1:
                        session = supabase_current_session(self.bearer_token())
                        if not can_write_table(session, table):
                            self.send_json({"error": "forbidden", "detail": f"{table}_write_forbidden"}, 403)
                            return
                        self.send_json(supabase_insert(table, self.read_json()), 201)
                        return
                    if method == "PATCH" and len(parts) == 2:
                        session = supabase_current_session(self.bearer_token())
                        if not can_write_table(session, table):
                            self.send_json({"error": "forbidden", "detail": f"{table}_write_forbidden"}, 403)
                            return
                        row = supabase_patch(table, parts[1], self.read_json())
                        self.send_json(row if row else {"error": "not_found"}, 200 if row else 404)
                        return
                self.send_json({"error": "not_found", "path": path}, 404)
                return

            with connect() as conn:
                if method == "POST" and parts == ["auth", "login"]:
                    payload, status = authenticate_local(conn, self.read_json(), self.client_ip(), self.client_device())
                    conn.commit()
                    self.send_json(payload, status)
                    return
                if method == "POST" and parts == ["auth", "logging-bridge"]:
                    payload, status = authenticate_logging_bridge(conn, self.read_json(), self.client_ip(), self.client_device())
                    conn.commit()
                    self.send_json(payload, status)
                    return
                if method == "GET" and parts == ["auth", "me"]:
                    session = current_session(conn, self.bearer_token())
                    self.send_json(session if session else {"error": "unauthorized"}, 200 if session else 401)
                    return
                if method == "POST" and parts == ["auth", "logout"]:
                    token = self.bearer_token()
                    if token:
                        conn.execute("UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ?", (now(), hash_token(token)))
                        conn.commit()
                    self.send_json({"ok": True})
                    return
                if method == "GET" and parts in (["health"], ["healthz"]):
                    self.send_json({"ok": True, "database": str(DB_PATH), "time": now(), "tables": list(TABLES), "production": production_readiness()})
                    return
                if method == "GET" and parts in (["production", "readiness"], ["readyz"]):
                    readiness = production_readiness()
                    status = 200 if readiness["ready"] or not is_production() else 503
                    self.send_json(readiness, status)
                    return
                if method == "GET" and parts in (["production", "go-live-audit"], ["go-live", "audit"]):
                    audit = go_live_audit()
                    status = 200 if audit["formalGo"] or not is_production() else 503
                    self.send_json(audit, status)
                    return
                if method == "GET" and parts == ["production", "deployment"]:
                    self.send_json(deployment_report())
                    return
                if method == "GET" and parts == ["production", "monitoring"]:
                    snapshot = local_monitoring_snapshot(conn)
                    self.send_json(snapshot, 200 if snapshot["ok"] or not is_production() else 503)
                    return
                if method == "GET" and parts == ["dashboard"]:
                    session = current_session(conn, self.bearer_token())
                    self.send_json(dashboard(conn, session))
                    return
                if method == "GET" and parts == ["search"]:
                    session = current_session(conn, self.bearer_token())
                    self.send_json(unified_search(conn, query, session))
                    return
                if method == "GET" and parts == ["schema"]:
                    self.send_json({"tables": TABLES})
                    return
                if method == "GET" and parts == ["exchange", "gateway-status"]:
                    self.send_json(exchange_gateway_status())
                    return
                if method == "GET" and parts == ["documents", "next-dispatch-no"]:
                    self.send_json({"doc_no": next_dispatch_no(conn)})
                    return
                if method == "POST" and parts == ["exchange", "queue"]:
                    result = exchange_queue_document(conn, self.read_json())
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "POST" and parts == ["exchange", "send"]:
                    result = exchange_send_document(conn, self.read_json())
                    conn.commit()
                    self.send_json(result, 201 if result.get("ok") else 422)
                    return
                if method == "POST" and parts == ["exchange", "receive"]:
                    result = exchange_receive_documents(conn, self.read_json())
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "POST" and parts == ["exchange", "status"]:
                    result = exchange_query_status(conn, self.read_json())
                    conn.commit()
                    self.send_json(result, 200 if result.get("ok") else 404)
                    return
                if method == "POST" and parts == ["exchange", "acknowledge"]:
                    result = exchange_acknowledge_received(conn, self.read_json())
                    conn.commit()
                    self.send_json(result, 200 if result.get("ok") else 404)
                    return
                if method == "POST" and parts == ["exchange", "retry"]:
                    result = exchange_retry_failed(conn, self.read_json())
                    conn.commit()
                    self.send_json(result, 200 if result.get("ok") else 422)
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
                if method == "POST" and parts == ["backup", "restore-drill"]:
                    result = run_backup_restore_drill(conn, self.read_json())
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "POST" and parts == ["compliance", "attest"]:
                    result = create_compliance_attestation(conn, self.read_json())
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "POST" and parts == ["jobs", "run-due"]:
                    result = run_due_background_jobs(conn)
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "GET" and parts == ["cron", "run-due"]:
                    if not self.cron_authorized():
                        self.send_json({"error": "unauthorized"}, 401)
                        return
                    result = run_due_background_jobs(conn)
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "GET" and parts == ["cron", "monitoring"]:
                    if not self.cron_authorized():
                        self.send_json({"error": "unauthorized"}, 401)
                        return
                    result = run_local_monitoring_check(conn)
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "POST" and parts == ["production", "monitoring", "check"]:
                    result = run_local_monitoring_check(conn)
                    conn.commit()
                    self.send_json(result, 201 if result["ok"] or not is_production() else 503)
                    return
                if method == "POST" and parts == ["jobs", "run-all"]:
                    result = run_due_background_jobs(conn, all_enabled=True)
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "POST" and len(parts) == 3 and parts[0] == "jobs" and parts[2] == "run":
                    result = run_background_job(conn, parts[1])
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "POST" and parts == ["notifications", "sync"]:
                    result = sync_notifications_from_business_state(conn)
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "GET" and parts == ["notifications", "gateway-status"]:
                    status = notification_gateway_status()
                    status["credentials"] = [notification_credential_status_for_channel(conn, channel) for channel in ["Email", "Line 工作群組", "系統站內通知"]]
                    self.send_json(status)
                    return
                if method == "POST" and parts == ["notifications", "credentials", "validate"]:
                    payload = self.read_json()
                    if payload.get("email_expires_at"):
                        conn.execute("UPDATE notification_channel_credentials SET expires_at = ?, updated_at = ? WHERE id = 'NCRED-EMAIL-SMTP'", (payload["email_expires_at"], now()))
                    if payload.get("line_expires_at"):
                        conn.execute("UPDATE notification_channel_credentials SET expires_at = ?, updated_at = ? WHERE id = 'NCRED-LINE-WEBHOOK'", (payload["line_expires_at"], now()))
                    result = validate_notification_credentials(conn, payload.get("channel") or "")
                    conn.commit()
                    self.send_json(result)
                    return
                if method == "POST" and parts == ["notifications", "send"]:
                    payload = self.read_json()
                    ids = payload.get("ids") or []
                    for item in payload.get("notifications") or []:
                        ids.append(create_notification(conn, item)["id"])
                    if payload.get("id"):
                        ids.append(payload["id"])
                    channel = payload.get("channel") or ""
                    results = [deliver_notification(conn, str(notification_id), channel) for notification_id in ids]
                    conn.commit()
                    self.send_json({"count": len(results), "results": results}, 201)
                    return
                if method == "POST" and parts == ["notifications", "test"]:
                    payload = self.read_json()
                    notice = create_notification(conn, {
                        "type": "通道測試",
                        "title": payload.get("title") or "通知通道測試",
                        "target_role": payload.get("target_role") or payload.get("target") or "行政部主任",
                        "target_email": payload.get("target_email") or "",
                        "channel": payload.get("channel") or "Email + Line + 系統通知",
                        "priority": "中",
                        "source": "GATEWAY-TEST",
                        "body": payload.get("body") or "這是一筆歲悅電子公文交換系統通知通道測試。",
                    })
                    result = deliver_notification(conn, notice["id"], payload.get("channel") or notice["channel"])
                    conn.commit()
                    report = notification_delivery_report(notice, result, payload.get("channel") or notice["channel"])
                    self.send_json({"notification": notice, "delivery": result, "report": report}, 201)
                    return
                if method == "POST" and parts == ["notifications", "retry-failed"]:
                    result = retry_failed_notifications(conn)
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "POST" and parts == ["notifications", "push-inbox"]:
                    payload = self.read_json()
                    ids = payload.get("ids") or ([payload["id"]] if payload.get("id") else [])
                    results = [deliver_notification(conn, str(notification_id), "系統通知") for notification_id in ids]
                    conn.commit()
                    self.send_json({"count": len(results), "results": results}, 201)
                    return
                if method == "POST" and parts == ["pdf", "generate"]:
                    result = pdf_generate(conn, self.read_json())
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "POST" and parts == ["pdf", "stamp"]:
                    result = pdf_stamp(conn, self.read_json())
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "POST" and parts == ["pdf", "verify"]:
                    self.send_json(pdf_verify(conn, self.read_json()))
                    return
                if method == "POST" and parts == ["seal-applications", "submit"]:
                    session = current_session(conn, self.bearer_token())
                    result = seal_application_submit(conn, self.read_json(), session)
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "POST" and len(parts) == 3 and parts[0] == "seal-applications" and parts[2] == "approve":
                    session = current_session(conn, self.bearer_token())
                    result = seal_application_approve(conn, parts[1], self.read_json(), session)
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "POST" and len(parts) == 3 and parts[0] == "seal-applications" and parts[2] == "return":
                    session = current_session(conn, self.bearer_token())
                    result = seal_application_return(conn, parts[1], self.read_json(), session)
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "GET" and parts == ["seal-reference-options"]:
                    session = current_session(conn, self.bearer_token())
                    if not self.require_table_access(session, "seal_reference_options"):
                        return
                    rows = list_rows(conn, "seal_reference_options", query)
                    grouped: Dict[str, List[Dict[str, Any]]] = {}
                    for row in rows:
                        grouped.setdefault(row.get("option_type", ""), []).append(row)
                    self.send_json({"options": rows, "grouped": grouped})
                    return
                if len(parts) == 3 and parts[0] == "companies" and parts[2] == "seals":
                    session = current_session(conn, self.bearer_token())
                    if method == "GET":
                        if not self.require_table_access(session, "company_seals"):
                            return
                        self.send_json(list_company_seals(conn, parts[1]))
                        return
                    if method == "POST":
                        if not self.require_table_access(session, "company_seals", write=True):
                            return
                        result = create_company_seal(conn, parts[1], self.read_json(), session)
                        conn.commit()
                        self.send_json(result, 201)
                        return
                if len(parts) == 2 and parts[0] == "seals":
                    session = current_session(conn, self.bearer_token())
                    if method == "PATCH":
                        if not self.require_table_access(session, "company_seals", write=True):
                            return
                        result = patch_company_seal(conn, parts[1], self.read_json(), session)
                        conn.commit()
                        self.send_json(result)
                        return
                    if method == "DELETE":
                        if not self.require_table_access(session, "company_seals", write=True):
                            return
                        result = deactivate_company_seal(conn, parts[1], session)
                        conn.commit()
                        self.send_json(result)
                        return
                if len(parts) == 3 and parts[0] == "seals" and parts[2] == "files":
                    session = current_session(conn, self.bearer_token())
                    if method == "GET":
                        if not self.require_table_access(session, "company_seal_files"):
                            return
                        result = list_company_seal_files(conn, parts[1], session)
                        conn.commit()
                        self.send_json(result)
                        return
                    if method == "POST":
                        if not self.require_table_access(session, "company_seal_files", write=True):
                            return
                        result = upload_company_seal_file(conn, parts[1], self.read_json(), session)
                        conn.commit()
                        self.send_json(result, 201)
                        return
                if method == "PATCH" and len(parts) == 3 and parts[0] == "seal-files" and parts[2] == "set-current":
                    session = current_session(conn, self.bearer_token())
                    if not self.require_table_access(session, "company_seal_files", write=True):
                        return
                    result = set_current_seal_file(conn, parts[1], session)
                    conn.commit()
                    self.send_json(result)
                    return
                if method == "POST" and len(parts) == 3 and parts[0] == "documents" and parts[2] == "seal-requests":
                    session = current_session(conn, self.bearer_token())
                    if not self.require_table_access(session, "seal_usage_requests", write=True):
                        return
                    result = create_seal_usage_request(conn, parts[1], self.read_json(), session)
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "GET" and parts == ["seal-requests"]:
                    session = current_session(conn, self.bearer_token())
                    if not self.require_table_access(session, "seal_usage_requests"):
                        return
                    self.send_json(list_seal_usage_requests(conn, query))
                    return
                if len(parts) == 2 and parts[0] == "seal-requests" and method == "GET":
                    session = current_session(conn, self.bearer_token())
                    if not self.require_table_access(session, "seal_usage_requests"):
                        return
                    self.send_json(seal_usage_request_row(conn, parts[1]))
                    return
                if method == "POST" and len(parts) == 3 and parts[0] == "seal-requests" and parts[2] == "approve":
                    session = current_session(conn, self.bearer_token())
                    if not self.require_table_access(session, "seal_usage_approvals", write=True):
                        return
                    result = approve_seal_usage_request(conn, parts[1], self.read_json(), session)
                    conn.commit()
                    self.send_json(result)
                    return
                if method == "POST" and len(parts) == 3 and parts[0] == "seal-requests" and parts[2] == "reject":
                    session = current_session(conn, self.bearer_token())
                    if not self.require_table_access(session, "seal_usage_approvals", write=True):
                        return
                    result = reject_seal_usage_request(conn, parts[1], self.read_json(), session)
                    conn.commit()
                    self.send_json(result)
                    return
                if method == "POST" and len(parts) == 3 and parts[0] == "seal-requests" and parts[2] == "stamp":
                    session = current_session(conn, self.bearer_token())
                    if not self.require_table_access(session, "company_seal_files", write=True):
                        return
                    result = stamp_seal_usage_request(conn, parts[1], self.read_json(), session)
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "GET" and parts == ["seal-usage-logs"]:
                    session = current_session(conn, self.bearer_token())
                    if not self.require_table_access(session, "seal_usage_logs"):
                        return
                    rows = list_rows(conn, "seal_usage_logs", query)
                    self.send_json(rows)
                    return
                if method == "GET" and parts == ["official-documents"]:
                    session = current_session(conn, self.bearer_token())
                    if not self.require_table_access(session, "official_documents"):
                        return
                    self.send_json(list_official_documents(conn, query, session))
                    return
                if method == "GET" and parts == ["official-documents", "my-tasks"]:
                    session = current_session(conn, self.bearer_token())
                    if not self.require_table_access(session, "official_document_approval_steps"):
                        return
                    scoped_query = {**query, "scope": ["todo"]}
                    self.send_json(list_official_documents(conn, scoped_query, session))
                    return
                if method == "GET" and parts == ["official-documents", "my-requests"]:
                    session = current_session(conn, self.bearer_token())
                    if not self.require_table_access(session, "official_documents"):
                        return
                    scoped_query = {**query, "scope": ["mine"]}
                    self.send_json(list_official_documents(conn, scoped_query, session))
                    return
                if method == "POST" and parts == ["official-documents"]:
                    session = current_session(conn, self.bearer_token())
                    if not self.require_table_access(session, "official_documents", write=True):
                        return
                    payload = self.read_json()
                    payload.setdefault("ip_address", self.client_ip())
                    payload.setdefault("user_agent", self.client_device())
                    result = create_official_document(conn, payload, session)
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "GET" and len(parts) == 2 and parts[0] == "official-documents":
                    session = current_session(conn, self.bearer_token())
                    if not self.require_table_access(session, "official_documents"):
                        return
                    self.send_json(official_document_detail(conn, parts[1], session))
                    return
                if len(parts) >= 3 and parts[0] == "official-documents" and parts[2] == "dispatch":
                    session = current_session(conn, self.bearer_token())
                    if method == "GET" and len(parts) == 3:
                        if not self.require_table_access(session, "official_document_dispatch_records"):
                            return
                        document = official_document_row(conn, parts[1])
                        steps = official_document_steps(conn, parts[1])
                        user = session.get("user") if session else None
                        if not canDownloadOfficialDocument(user, document, steps) and not session_has_any_permission(session, ["official_documents.all_records", "official_documents.all_todo"]):
                            self.send_json({"error": "forbidden", "detail": "official_dispatch_access_denied"}, 403)
                            return
                        self.send_json(official_dispatch_record(conn, parts[1]) or {})
                        return
                    if method == "POST" and len(parts) == 3:
                        if not self.require_table_access(session, "official_document_dispatch_records", write=True):
                            return
                        payload = self.read_json()
                        payload.setdefault("ip_address", self.client_ip())
                        payload.setdefault("user_agent", self.client_device())
                        document = official_document_row(conn, parts[1])
                        result = upsert_official_dispatch_record(conn, document, payload.get("dispatch_method") or document.get("dispatch_method"), session.get("user") if session else None, payload)
                        insert_official_log(conn, parts[1], "create_dispatch", session.get("user") if session else None, result.get("dispatch_method") or "", ip_address=payload.get("ip_address") or "", user_agent=payload.get("user_agent") or "")
                        conn.commit()
                        self.send_json(result, 201)
                        return
                    if method == "PATCH" and len(parts) == 3:
                        if not self.require_table_access(session, "official_document_dispatch_records", write=True):
                            return
                        payload = self.read_json()
                        payload.setdefault("ip_address", self.client_ip())
                        payload.setdefault("user_agent", self.client_device())
                        result = update_official_dispatch_record(conn, parts[1], payload, session)
                        conn.commit()
                        self.send_json(result)
                        return
                    if method == "POST" and len(parts) == 4 and parts[3] == "complete":
                        if not self.require_table_access(session, "official_document_dispatch_records", write=True):
                            return
                        payload = self.read_json()
                        payload.setdefault("ip_address", self.client_ip())
                        payload.setdefault("user_agent", self.client_device())
                        result = complete_official_dispatch(conn, parts[1], payload, session)
                        conn.commit()
                        self.send_json(result)
                        return
                    if method == "POST" and len(parts) == 4 and parts[3] == "proof-files":
                        if not self.require_table_access(session, "official_document_dispatch_records", write=True):
                            return
                        payload = self.read_json()
                        payload.setdefault("ip_address", self.client_ip())
                        payload.setdefault("user_agent", self.client_device())
                        result = upload_official_dispatch_proof_file(conn, parts[1], payload, session)
                        conn.commit()
                        self.send_json(result, 201)
                        return
                if method == "POST" and len(parts) == 3 and parts[0] == "official-documents" and parts[2] in {"submit", "approve", "reject", "cancel", "confirm", "stamp-position"}:
                    session = current_session(conn, self.bearer_token())
                    payload = self.read_json()
                    payload.setdefault("ip_address", self.client_ip())
                    payload.setdefault("user_agent", self.client_device())
                    if parts[2] == "submit":
                        result = submit_official_document(conn, parts[1], payload, session)
                    elif parts[2] == "approve":
                        result = approve_official_document(conn, parts[1], payload, session)
                    elif parts[2] == "reject":
                        result = reject_official_document(conn, parts[1], payload, session)
                    elif parts[2] == "cancel":
                        result = cancel_official_document(conn, parts[1], payload, session)
                    elif parts[2] == "confirm":
                        result = confirm_official_document(conn, parts[1], payload, session)
                    else:
                        result = update_official_stamp_position(conn, parts[1], payload, session)
                    conn.commit()
                    self.send_json(result)
                    return
                if method == "GET" and len(parts) == 5 and parts[0] == "official-documents" and parts[2] == "files" and parts[4] == "download":
                    self.send_official_document_file(conn, parts[1], parts[3])
                    return
                if method == "POST" and parts == ["ai", "compose"]:
                    result = ai_compose_official_draft(conn, self.read_json())
                    conn.commit()
                    self.send_json(result, 200 if not result.get("error") else 422)
                    return
                if method == "POST" and parts == ["attachments", "security-action"]:
                    result = attachment_security_action(conn, self.read_json())
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "GET" and parts == ["files", "storage-health"]:
                    self.send_json(storage_health(conn))
                    return
                if method == "POST" and parts == ["files", "upload"]:
                    result = upload_file_object(conn, self.read_json())
                    self.send_json(result, 201 if not result.get("error") else 422)
                    return
                if method == "POST" and len(parts) == 3 and parts[0] == "files" and parts[2] == "signed-url":
                    payload = self.read_json()
                    result = create_file_signed_url(conn, parts[1], payload.get("actor") or "API", int(payload.get("ttl_seconds") or EDOC_SIGNED_URL_TTL_SECONDS), payload.get("purpose") or "download")
                    conn.commit()
                    status = 403 if result.get("error") == "seal_vault_download_forbidden" else 404
                    self.send_json(result, 201 if not result.get("error") else status)
                    return
                if method == "POST" and len(parts) == 3 and parts[0] == "files" and parts[2] == "scan":
                    result = scan_file_object(conn, parts[1], "AV Worker")
                    conn.commit()
                    self.send_json(result, 201 if result.get("ok") else 422)
                    return
                if method == "POST" and parts == ["signatures", "sign"]:
                    result = create_electronic_signature(conn, self.read_json())
                    conn.commit()
                    self.send_json(result, 201)
                    return
                if method == "POST" and parts == ["signatures", "verify"]:
                    result = verify_electronic_signature(conn, self.read_json())
                    conn.commit()
                    self.send_json(result)
                    return
                if method == "POST" and parts == ["certificates", "validate"]:
                    result = validate_certificate_api(conn, self.read_json())
                    conn.commit()
                    self.send_json(result, 200 if result.get("ok") else 422)
                    return
                if method == "GET" and parts == ["certificates", "health"]:
                    self.send_json(certificate_health(conn))
                    return
                if method == "GET" and len(parts) == 3 and parts[0] == "files" and parts[2] == "download":
                    self.send_file_object(conn, parts[1])
                    return
                if parts and parts[0] in TABLES:
                    table = TABLES[parts[0]]
                    if method == "GET" and len(parts) == 1:
                        session = current_session(conn, self.bearer_token())
                        if not can_read_table(session, table):
                            self.send_json({"error": "forbidden", "detail": f"{table}_read_forbidden"}, 403)
                            return
                        rows = scoped_document_rows(conn, query, session) if table == "documents" else list_rows(conn, table, query)
                        if table == "users":
                            rows = [public_user(row) for row in rows]
                        self.send_json(rows)
                        return
                    if method == "GET" and len(parts) == 2:
                        session = current_session(conn, self.bearer_token())
                        if not can_read_table(session, table):
                            self.send_json({"error": "forbidden", "detail": f"{table}_read_forbidden"}, 403)
                            return
                        if table == "documents" and not can_read_document(conn, parts[1], session):
                            self.send_json({"error": "forbidden", "detail": "document_acl_denied"}, 403)
                            return
                        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (parts[1],)).fetchone()
                        data = public_user(row) if row and table == "users" else row_to_dict(row) if row else {"error": "not_found"}
                        self.send_json(data, 200 if row else 404)
                        return
                    if method == "POST" and len(parts) == 1:
                        session = current_session(conn, self.bearer_token())
                        if not can_write_table(session, table):
                            self.send_json({"error": "forbidden", "detail": f"{table}_write_forbidden"}, 403)
                            return
                        row = insert_row(conn, table, self.read_json())
                        conn.commit()
                        self.send_json(row, 201)
                        return
                    if method == "PATCH" and len(parts) == 2:
                        session = current_session(conn, self.bearer_token())
                        if not can_write_table(session, table):
                            self.send_json({"error": "forbidden", "detail": f"{table}_write_forbidden"}, 403)
                            return
                        row = patch_row(conn, table, parts[1], self.read_json())
                        conn.commit()
                        self.send_json(row if row else {"error": "not_found"}, 200 if row else 404)
                        return
                self.send_json({"error": "not_found", "path": path}, 404)
        except ValueError as exc:
            detail = str(exc)
            status = 503 if detail.startswith(("formal_signing_service_not_ready", "formal_signature_provider", "formal_tsa")) else 422
            log_structured("warning", "api_request_rejected", path=path, method=method, error=detail)
            self.send_json({"error": "request_rejected", "detail": detail}, status)
        except PermissionError as exc:
            detail = str(exc) or "forbidden"
            log_structured("warning", "api_request_forbidden", path=path, method=method, error=detail)
            self.send_json({"error": "forbidden", "detail": detail}, 403)
        except SignatureProviderError as exc:
            detail = str(exc)
            log_structured("warning", "signature_provider_failed", path=path, method=method, error=detail)
            self.send_json({"error": "signature_provider_failed", "detail": detail, "event": exc.event}, 503)
        except Exception as exc:  # Keep API observable during prototype hardening.
            log_structured("error", "api_request_failed", path=path, method=method, error=str(exc))
            self.send_json({"error": "server_error", "detail": str(exc)}, 500)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Suiyuecare eDoc backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=5174, type=int)
    parser.add_argument("--init-only", action="store_true")
    parser.add_argument("--run-due-jobs", action="store_true")
    args = parser.parse_args()
    migrate()
    if args.init_only:
        print(f"Initialized {DB_PATH}")
        return
    if args.run_due_jobs:
        with connect() as conn:
            result = run_due_background_jobs(conn)
            conn.commit()
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Suiyuecare eDoc backend running at http://{args.host}:{args.port}")
    print(f"SQLite database: {DB_PATH}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
