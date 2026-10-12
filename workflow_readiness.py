"""Bounded read-only list cursors and truthful, timezone-aware time metrics.

This module has no database or network side effects. Authorization is supplied
by the backend and repeated by its read-only SQL RPCs; cursors cannot grant it.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
LIST_MAX_ROWS = 100000
DEADLINE_BUCKETS = (
    ("overdue", "已逾期"), ("today", "今日到期"),
    ("next_day", "明日到期"), ("next_2_3_days", "2–3 日內到期"),
    ("later", "4 日後到期"), ("unknown", "期限未設定／無法判定"),
)
WAITING_BUCKETS = (
    ("0_1_days", "已等待 0–1 日"), ("2_3_days", "已等待 2–3 日"),
    ("4_7_days", "已等待 4–7 日"), ("8_plus_days", "已等待 8 日以上"),
    ("unknown", "起算時間未知"),
)
SOURCE_LABELS = {"inbound": "收文未結", "reply": "待回覆人次", "approval": "目前待簽關卡"}


def inbound_list_options(query: dict | None, scope: dict) -> dict:
    query = query or {}
    def value(key, default=""):
        item = query.get(key, [default])
        return str(item[0] if isinstance(item, list) and item else default).strip()
    paginated = value("paginated") in {"1", "true"}
    try:
        size = int(value("page_size", "50"))
    except ValueError:
        raise ValueError("inbound_list_page_size_invalid") from None
    if not 1 <= size <= 100:
        raise ValueError("inbound_list_page_size_invalid")
    filters = {"status": value("status"), "assignee_user_id": value("assignee_user_id"), "q": value("q")}
    if any(len(filters[key]) > limit for key, limit in (("status", 80), ("assignee_user_id", 160), ("q", 200))):
        raise ValueError("inbound_list_filter_invalid")
    binding = hashlib.sha256(json.dumps({"scope": scope, "filters": filters}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    after = None
    token = value("cursor")
    if token:
        if not paginated or len(token) > 1500:
            raise ValueError("inbound_list_cursor_invalid")
        try:
            decoded = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
            if not isinstance(decoded, dict) or set(decoded) != {"v", "binding", "created", "id"}:
                raise ValueError
            if decoded["v"] != 1 or decoded["binding"] != binding:
                raise ValueError
            if not all(isinstance(decoded[key], str) and 0 < len(decoded[key]) <= limit for key, limit in (("created", 100), ("id", 200))):
                raise ValueError
            after = (decoded["created"], decoded["id"])
        except (ValueError, KeyError, TypeError, binascii.Error, UnicodeError):
            raise ValueError("inbound_list_cursor_invalid") from None
    return {"paginated": paginated, "page_size": size, "binding": binding, "after": after, **filters}


def inbound_cursor(row: dict, binding: str) -> str:
    content = {"v": 1, "binding": binding, "created": str(row["created_at"]), "id": str(row["id"])}
    return base64.urlsafe_b64encode(json.dumps(content, separators=(",", ":")).encode()).decode().rstrip("=")


def inbound_page(items: list, count: int, options: dict) -> dict:
    size = options["page_size"]
    more = len(items) > size
    page = items[:size]
    return {"items": page, "nextCursor": inbound_cursor(page[-1], options["binding"]) if more and page else None,
            "hasMore": more, "count": count, "pageSize": size, "scopeComplete": True}


def parse_metric_time(value: Any, *, system_timezone=timezone.utc, date_deadline=False):
    """User-entered deadlines are Taipei; offsetless system events use host TZ.

    Date-only deadlines include their entire local calendar day. Missing,
    malformed and date-only event timestamps are unknown, not an invented age.
    """
    text = str(value or "").strip()
    if not text or len(text) > 100:
        return None
    try:
        if len(text) == 10:
            if not date_deadline:
                return None
            stamp = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=TAIPEI)
            return stamp + timedelta(days=1) - timedelta(microseconds=1)
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=TAIPEI if date_deadline else system_timezone)
        return stamp.astimezone(TAIPEI)
    except (ValueError, TypeError, OverflowError):
        return None


def timeliness_report(rows: Iterable[dict], *, generated_at: datetime, scope: dict,
                      data_complete=True, errors=None, system_timezone=timezone.utc) -> dict:
    if generated_at.tzinfo is None:
        raise ValueError("timeliness_clock_timezone_required")
    clock = generated_at.astimezone(TAIPEI)
    deadline = {key: 0 for key, _ in DEADLINE_BUCKETS}
    waiting = {key: 0 for key, _ in WAITING_BUCKETS}
    totals = {"pending": 0, "overdue": 0, "unknownDue": 0, "unknownAge": 0}
    sources = {key: {"key": key, "label": label, **totals} for key, label in SOURCE_LABELS.items()}
    seen = set()
    for row in rows:
        key = (row.get("source"), str(row.get("id") or ""))
        if key[0] not in sources or not key[1] or key in seen:
            raise ValueError("timeliness_row_binding_invalid")
        seen.add(key)
        source = sources[key[0]]
        totals["pending"] += 1
        source["pending"] += 1
        due = parse_metric_time(row.get("due_at"), system_timezone=system_timezone, date_deadline=True)
        if due is None:
            bucket = "unknown"
            totals["unknownDue"] += 1
            source["unknownDue"] += 1
        elif due < clock:
            bucket = "overdue"
            totals["overdue"] += 1
            source["overdue"] += 1
        else:
            days = (due.date() - clock.date()).days
            bucket = "today" if days == 0 else "next_day" if days == 1 else "next_2_3_days" if days <= 3 else "later"
        deadline[bucket] += 1
        entered = parse_metric_time(row.get("entered_at"), system_timezone=system_timezone)
        if entered is None or entered > clock:
            bucket = "unknown"
            totals["unknownAge"] += 1
            source["unknownAge"] += 1
        else:
            days = (clock - entered).total_seconds() / 86400
            bucket = "0_1_days" if days < 2 else "2_3_days" if days < 4 else "4_7_days" if days < 8 else "8_plus_days"
        waiting[bucket] += 1
    return {"version": 1, "timezone": "Asia/Taipei", "generatedAt": clock.isoformat(timespec="seconds"),
            "dataComplete": data_complete is True, "scope": scope, "totals": totals,
            "deadlineBuckets": [{"key": key, "label": label, "count": deadline[key]} for key, label in DEADLINE_BUCKETS],
            "waitingBuckets": [{"key": key, "label": label, "count": waiting[key]} for key, label in WAITING_BUCKETS],
            "sources": list(sources.values()), "errors": list(errors or []),
            "timeBasis": "收文自登錄、回覆自派發、簽核自目前關卡進入時間；未結回覆按人次計數"}
