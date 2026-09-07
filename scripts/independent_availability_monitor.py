#!/usr/bin/env python3
"""External, credential-free health probes; alert only on an outage transition.

The runner is GitHub Actions, not the eDoc process/Supabase cron. The private
base URL comes from configuration. Neither URL nor response text is logged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
from urllib import error, request
from urllib.parse import urlsplit


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
            or parsed.port not in {None, 443}):
        raise ValueError("monitor_base_url_invalid")
    return value.rstrip("/")


def probe(base_url: str, route: str, opener=None) -> dict:
    opener = opener or request.build_opener(NoRedirect())
    started = time.monotonic()
    status = 0
    ok = False
    code = "transport_unavailable"
    try:
        req = request.Request(base_url + route, headers={"Accept": "application/json",
            "User-Agent": "edoc-independent-monitor/1"})
        with opener.open(req, timeout=8) as response:
            status = response.status
            raw = response.read(4097)
            if len(raw) > 4096:
                code = "response_too_large"
            else:
                payload = json.loads(raw)
                ok = (status == 200 and isinstance(payload, dict)
                      and payload.get("ok") is True
                      and (route != "/api/readyz" or payload.get("ready") is True))
                code = "healthy" if ok else "readiness_failed"
    except error.HTTPError as exc:
        status = exc.code
        code = "http_failure"
    except (ValueError, UnicodeError):
        code = "response_invalid"
    except Exception:
        pass
    return {"route": route, "ok": ok, "status": status, "code": code,
            "elapsedMs": round((time.monotonic() - started) * 1000)}


def check_availability(base_url: str, probe_fn=probe, sleep_fn=time.sleep) -> tuple[bool | None, list]:
    attempts = []
    # A single failed dependency probe is not an outage. Recovery also needs
    # two consecutive healthy pairs before clearing an existing incident.
    healthy_streak = 0
    failure_streak = 0
    for attempt in range(3):
        results = [probe_fn(base_url, route) for route in ("/api/healthz", "/api/readyz")]
        attempts.append(results)
        pair_healthy = all(row["ok"] for row in results)
        healthy_streak = healthy_streak + 1 if pair_healthy else 0
        failure_streak = 0 if pair_healthy else failure_streak + 1
        if healthy_streak >= 2:
            return True, attempts
        if failure_streak >= 2:
            return False, attempts
        if attempt < 2:
            sleep_fn(2)
    return None, attempts


def transition(previous: dict, healthy: bool | None, now: float) -> dict:
    fresh = (previous.get("schemaVersion") == 1 and isinstance(previous.get("checkedAt"), (int, float))
             and 0 <= now - previous["checkedAt"] < 172800)
    old = previous.get("status") if fresh else "unknown"
    if old not in {"healthy", "outage", "unknown"}:
        old = "unknown"
    status = old if healthy is None else ("healthy" if healthy else "outage")
    return {"schemaVersion": 1, "status": status, "checkedAt": now,
            "observation": "inconclusive" if healthy is None else status,
            "alert": status == "outage" and old != "outage",
            "recovered": status == "healthy" and old == "outage"}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".monitor-")
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(state, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    try:
        base_url = validate_base_url(os.environ.get("EDOC_MONITOR_BASE_URL", ""))
        path = Path(os.environ.get("EDOC_MONITOR_STATE", ".monitor-state/availability.json"))
        try:
            previous = json.loads(path.read_text()) if path.stat().st_size < 4096 else {}
        except (OSError, ValueError):
            previous = {}
        if not isinstance(previous, dict):
            previous = {}
        healthy, attempts = check_availability(base_url)
        state = transition(previous, healthy, time.time())
        save_state(path, state)
        print(json.dumps({**state, "attempts": attempts}))
        if state["alert"]:
            print("::error::EDOC_AVAILABILITY_OUTAGE — repeated public health/readiness probes failed.")
        elif state["recovered"]:
            print("::notice::EDOC_AVAILABILITY_RECOVERED — two consecutive healthy checks.")
        return 1 if state["alert"] else 0
    except Exception:
        print("::error::EDOC_MONITOR_RUNNER_FAILED — inspect runner configuration; no response data logged.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
