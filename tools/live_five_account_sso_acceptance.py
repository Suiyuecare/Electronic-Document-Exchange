#!/usr/bin/env python3
"""Run a PII-free five-account Portal -> eDoc production SSO acceptance.

The tool receives Portal and Finance credentials only through the process
environment (normally ``vercel env run -e production``).  It never prints
tokens, secrets, account ids, names or email addresses.  Five accounts are
sampled from the intersection of confirmed Portal Google identities and active
Finance master rows, then exercised through the real eDoc handoff/session and
directory endpoints.
"""

from __future__ import annotations

import base64
from collections import Counter
import hashlib
import hmac
import http.cookiejar
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


EDOC_ORIGIN = "https://edoc.suiyuecare.com"
PORTAL_ORIGIN = "https://login.suiyuecare.com"
SAMPLE_SIZE = 5
TIMEOUT_SECONDS = 30


class AcceptanceError(RuntimeError):
    """Machine-readable acceptance failure without account data."""


class RecordingRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self) -> None:
        super().__init__()
        self.statuses: list[int] = []

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        self.statuses.append(int(code))
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


def required_environment(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise AcceptanceError(f"missing_environment_{name.lower()}")
    return value


def request_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    data: bytes | None = None,
    opener: urllib.request.OpenerDirector | None = None,
) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            "User-Agent": "edoc-live-acceptance/1",
            **(headers or {}),
        },
    )
    try:
        response = (opener or urllib.request.build_opener()).open(
            request,
            timeout=TIMEOUT_SECONDS,
        )
        status = int(response.status)
        body = response.read()
    except urllib.error.HTTPError as error:
        status = int(error.code)
        body = error.read()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    return status, payload if isinstance(payload, dict) else {}


def linked_query_rows(workdir: str, sql: str) -> list[dict]:
    result = subprocess.run(
        [
            "supabase",
            "db",
            "query",
            "--workdir",
            workdir,
            "--linked",
            "--output",
            "json",
            sql,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise AcceptanceError("supabase_linked_inventory_failed")
    start = result.stdout.find("{")
    try:
        payload = json.loads(result.stdout[start:]) if start >= 0 else {}
    except json.JSONDecodeError as error:
        raise AcceptanceError("supabase_linked_inventory_invalid") from error
    rows = payload.get("rows")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise AcceptanceError("supabase_linked_inventory_invalid")
    return rows


def portal_google_accounts() -> dict[str, str]:
    linked_workdir = str(os.environ.get("PORTAL_SUPABASE_WORKDIR") or "").strip()
    if linked_workdir:
        rows = linked_query_rows(
            linked_workdir,
            """
            select auth_user.id::text as id, lower(auth_user.email) as email
            from auth.users auth_user
            where auth_user.email_confirmed_at is not null
              and (
                coalesce(auth_user.raw_app_meta_data ->> 'provider', '') = 'google'
                or coalesce(auth_user.raw_app_meta_data -> 'providers', '[]'::jsonb) ? 'google'
                or exists (
                  select 1 from auth.identities identity_row
                  where identity_row.user_id = auth_user.id
                    and identity_row.provider = 'google'
                )
              )
            order by auth_user.id
            """,
        )
        return {
            str(row.get("email") or "").strip().lower(): str(row.get("id") or "").strip()
            for row in rows
            if str(row.get("email") or "").strip() and str(row.get("id") or "").strip()
        }

    portal_url = required_environment("SUPABASE_URL").rstrip("/")
    service_key = required_environment("SUPABASE_SERVICE_ROLE_KEY")
    status, payload = request_json(
        f"{portal_url}/auth/v1/admin/users?page=1&per_page=1000",
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
        },
    )
    if status != 200 or not isinstance(payload.get("users"), list):
        raise AcceptanceError(f"portal_auth_inventory_http_{status}")

    accounts: dict[str, str] = {}
    for user in payload["users"]:
        if not isinstance(user, dict) or not user.get("email_confirmed_at"):
            continue
        email = str(user.get("email") or "").strip().lower()
        user_id = str(user.get("id") or "").strip()
        providers = {
            str((user.get("app_metadata") or {}).get("provider") or ""),
            *[
                str(item)
                for item in ((user.get("app_metadata") or {}).get("providers") or [])
            ],
            *[
                str((identity or {}).get("provider") or "")
                for identity in (user.get("identities") or [])
                if isinstance(identity, dict)
            ],
        }
        if email and user_id and "google" in providers:
            accounts[email] = user_id
    return accounts


def active_finance_emails() -> set[str]:
    linked_workdir = str(os.environ.get("FINANCE_SUPABASE_WORKDIR") or "").strip()
    if linked_workdir:
        rows = linked_query_rows(
            linked_workdir,
            """
            select lower(finance_user.email) as email
            from public.finance_users finance_user
            where finance_user.active is true
              and finance_user.org_status = 'active'
            order by finance_user.id
            """,
        )
        return {
            str(row.get("email") or "").strip().lower()
            for row in rows
            if str(row.get("email") or "").strip()
        }

    finance_url = required_environment("FINANCE_SOURCE_SUPABASE_URL").rstrip("/")
    finance_key = required_environment("FINANCE_SOURCE_SECRET_KEY")
    query = urllib.parse.urlencode(
        {
            "select": "email",
            "active": "eq.true",
            "org_status": "eq.active",
            "order": "id.asc",
            "limit": "1000",
        }
    )
    request = urllib.request.Request(
        f"{finance_url}/rest/v1/finance_users?{query}",
        headers={
            "Accept": "application/json",
            "apikey": finance_key,
            "User-Agent": "edoc-live-acceptance/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status = int(response.status)
            body = response.read()
    except urllib.error.HTTPError as error:
        status = int(error.code)
        body = error.read()
    try:
        rows = json.loads(body.decode("utf-8")) if body else []
    except (UnicodeDecodeError, json.JSONDecodeError):
        rows = []
    if status != 200 or not isinstance(rows, list):
        raise AcceptanceError(f"finance_inventory_http_{status}")
    return {
        str(row.get("email") or "").strip().lower()
        for row in rows
        if isinstance(row, dict) and str(row.get("email") or "").strip()
    }


def base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def signed_handoff(email: str, auth_user_id: str, secret: str, ordinal: int) -> str:
    issued_at = int(time.time())
    payload = {
        "email": email,
        "iat": issued_at,
        "exp": issued_at + 300,
        "jti": f"live-{ordinal}-{uuid.uuid4().hex}",
        "source": "logging-portal",
        "aud": "edoc",
        "moduleId": "edoc",
        "authUserId": auth_user_id,
    }
    encoded = base64url(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    signature = base64url(
        hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{encoded}.{signature}"


def acceptance_for_account(email: str, auth_user_id: str, secret: str, ordinal: int) -> dict[str, int]:
    jar = http.cookiejar.CookieJar()
    redirect = RecordingRedirect()
    handoff_opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        redirect,
    )
    form = urllib.parse.urlencode(
        {"token": signed_handoff(email, auth_user_id, secret, ordinal)}
    ).encode("ascii")
    request = urllib.request.Request(
        f"{EDOC_ORIGIN}/api/auth/handoff",
        data=form,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": PORTAL_ORIGIN,
            "User-Agent": "edoc-live-acceptance/1",
        },
    )
    try:
        response = handoff_opener.open(request, timeout=TIMEOUT_SECONDS)
        final_status = int(response.status)
        response.read()
    except urllib.error.HTTPError as error:
        final_status = int(error.code)
        error.read()
    if 303 not in redirect.statuses or final_status != 200:
        raise AcceptanceError(f"handoff_http_{final_status}")
    if not list(jar):
        raise AcceptanceError("handoff_cookie_missing")

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    exchange_status, exchange = request_json(
        f"{EDOC_ORIGIN}/api/auth/handoff-session",
        method="POST",
        data=b"",
        headers={
            "Content-Length": "0",
            "Origin": EDOC_ORIGIN,
            "X-EDOC-Handoff-Exchange": "1",
            "Sec-Fetch-Site": "same-origin",
        },
        opener=opener,
    )
    if exchange_status != 200:
        code = re.sub(r"[^a-z0-9_]+", "_", str(exchange.get("error") or "unknown").lower())
        raise AcceptanceError(f"handoff_exchange_http_{exchange_status}_{code[:80]}")
    token = str(exchange.get("token") or "")
    user = exchange.get("user") or {}
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
        raise AcceptanceError("handoff_exchange_token_invalid")
    if str(user.get("account_source") or "").lower() != "finance":
        raise AcceptanceError("handoff_exchange_account_source_invalid")

    authorization = {"Authorization": f"Bearer {token}"}
    me_status, me = request_json(
        f"{EDOC_ORIGIN}/api/auth/me",
        headers=authorization,
    )
    me_user = me.get("user") or {}
    if me_status != 200 or str(me_user.get("account_source") or "").lower() != "finance":
        raise AcceptanceError(f"auth_me_http_{me_status}")

    directory_status, directory = request_json(
        f"{EDOC_ORIGIN}/api/finance-directory",
        headers=authorization,
    )
    if directory_status != 200:
        raise AcceptanceError(f"finance_directory_http_{directory_status}")
    if not str(directory.get("currentCompanyId") or ""):
        raise AcceptanceError("finance_directory_company_missing")
    if not isinstance(directory.get("departments"), list) or not directory["departments"]:
        raise AcceptanceError("finance_directory_departments_missing")

    return {
        "handoff303": 1,
        "exchange200": 1,
        "authMe200": 1,
        "directory200": 1,
        "financeOwned": 1,
        "companyBound": 1,
        "departmentsPresent": 1,
    }


def main() -> int:
    secret = required_environment("PORTAL_HANDOFF_SIGNING_SECRET")
    if len(secret.encode("utf-8")) < 32:
        raise AcceptanceError("portal_handoff_secret_too_short")
    portal_accounts = portal_google_accounts()
    finance_emails = active_finance_emails()
    eligible = sorted(set(portal_accounts) & finance_emails)
    if len(eligible) < SAMPLE_SIZE:
        raise AcceptanceError("eligible_portal_finance_accounts_below_five")

    sampled = random.SystemRandom().sample(eligible, SAMPLE_SIZE)
    totals: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    for ordinal, email in enumerate(sampled, start=1):
        try:
            totals.update(
                acceptance_for_account(
                    email,
                    portal_accounts[email],
                    secret,
                    ordinal,
                )
            )
        except AcceptanceError as error:
            failures[str(error)] += 1

    result = {
        "eligibleAccounts": len(eligible),
        "sampledAccounts": len(sampled),
        "passedAccounts": totals["handoff303"],
        "checks": dict(sorted(totals.items())),
        "failureCodes": dict(sorted(failures.items())),
        "piiPrinted": False,
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if totals["handoff303"] == SAMPLE_SIZE and not failures else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcceptanceError as error:
        print(
            json.dumps(
                {
                    "eligibleAccounts": 0,
                    "sampledAccounts": 0,
                    "passedAccounts": 0,
                    "checks": {},
                    "failureCodes": {str(error): 1},
                    "piiPrinted": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        raise SystemExit(1)
