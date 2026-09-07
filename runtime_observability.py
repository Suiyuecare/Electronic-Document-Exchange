"""Privacy-by-construction error correlation for the runtime log channel.

No exception text, request bodies, headers, identities, document ids, source
lines or local variables may enter an event. This works without a vendor key.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

VERSION = "edoc-runtime-errors-v1"
RESOURCES = frozenset({"auth", "official-documents", "company-seals", "seal-requests",
    "dashboard", "notifications", "monitoring", "cron", "health", "healthz", "readyz",
    "documents", "files", "finance", "users", "settings", "backups", "jobs"})
SOURCE_FILES = frozenset({"backend.py", "finance_bridge.py", "exchange_gateway.py",
    "runtime_observability.py", "vercel_sandbox_antivirus.py"})


def route_group(path: str) -> str:
    try:
        parts = urlsplit(str(path)).path.split("/")
        resource = parts[2] if len(parts) > 2 and parts[1] == "api" else "other"
        return "/api/" + (resource if resource in RESOURCES else "other")
    except (TypeError, ValueError):
        return "/api/other"


def capture_runtime_error(*, method: str, path: str, status: int,
                          exception: BaseException | None = None, stream=None) -> str:
    """Emit a bounded event; log-channel failure must never break the response."""
    event_id = "ERR-" + secrets.token_hex(12).upper()
    family = "internal_error"
    for cls, code in ((TimeoutError, "timeout"), (ConnectionError, "connection"),
                      (PermissionError, "permission"), (ValueError, "validation"),
                      (OSError, "io_error")):
        if isinstance(exception, cls):
            family = code
            break
    frames = []
    tb = exception.__traceback__ if exception else None
    while tb is not None:
        filename = Path(tb.tb_frame.f_code.co_filename).name
        if filename in SOURCE_FILES:
            frames.append({"file": filename, "line": int(tb.tb_lineno)})
        tb = tb.tb_next
    frames = frames[-8:]
    safe_method = method if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"} else "OTHER"
    fingerprint_parts = [route_group(path), safe_method, int(status), family, frames]
    event = {
        "level": "error", "message": "runtime_error", "eventId": event_id,
        "rendererVersion": VERSION,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "route": fingerprint_parts[0], "method": safe_method,
        "status": int(status), "errorCode": family, "frames": frames,
        "fingerprint": hashlib.sha256(json.dumps(fingerprint_parts, sort_keys=True).encode()).hexdigest(),
    }
    try:
        print(json.dumps(event, ensure_ascii=True), file=stream or sys.stderr, flush=True)
    except Exception:
        pass
    return event_id


def error_tracking_status() -> dict:
    # Merely defining SENTRY_DSN does not install or activate an SDK.
    return {"enabled": True, "provider": "structured_runtime_logs", "version": VERSION,
            "correlationId": True, "sentryConnected": False, "longTermArchive": False}
