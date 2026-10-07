#!/usr/bin/env python3
"""Privileged signed-identity probe, NOT human Google SSO acceptance.

The tool receives Portal and Finance credentials only through the process
environment (normally ``vercel env run -e production``).  It never prints
tokens, secrets, account ids, names or email addresses.  Five accounts are
sampled from the intersection of confirmed Portal Google identities and active
Finance master rows, then exercised through the real eDoc handoff/session and
directory endpoints. This mints handoffs as sampled users and therefore requires
separate explicit authorization. It must not be used for the named human SSO
acceptance plan; normal invocation fails before reading secrets or accounts.
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

SAFE_FAILURE_CODES = frozenset({
    "signed_identity_probe_requires_explicit_authorization_not_human_sso",
    "portal_handoff_secret_too_short", "eligible_portal_finance_accounts_below_five",
    "supabase_linked_inventory_failed", "supabase_linked_inventory_invalid",
    "handoff_cookie_missing", "handoff_redirect_invalid", "handoff_exchange_token_invalid",
    "handoff_exchange_account_source_invalid", "finance_directory_company_missing",
    "finance_directory_departments_missing", "acceptance_session_cleanup_failed",
    "acceptance_session_not_revoked", "acceptance_network_unavailable",
    "acceptance_origin_invalid", "acceptance_unexpected_failure",
    "missing_environment_portal_handoff_signing_secret", "missing_environment_supabase_url",
    "missing_environment_supabase_service_role_key", "missing_environment_finance_source_supabase_url",
    "missing_environment_finance_source_secret_key", "missing_environment_edoc_storage_supabase_url",
    "editor_acceptance_network_unavailable", "editor_acceptance_download_url_invalid",
    "editor_acceptance_json_invalid", "editor_acceptance_tus_endpoint_invalid",
    "editor_acceptance_tus_credentials_invalid", "editor_acceptance_tus_metadata_missing",
    "editor_acceptance_tus_location_invalid", "editor_acceptance_page_count_invalid",
    "editor_acceptance_a4_geometry_invalid", "editor_acceptance_page_orientation_invalid",
    "editor_acceptance_draft_id_invalid", "editor_acceptance_pdf_policy_preflight_or_hash_failed",
    "editor_acceptance_finalize_not_idempotent", "editor_acceptance_saved_content_changed",
    "editor_acceptance_prepared_hash_mismatch", "editor_acceptance_prepared_text_missing",
    "editor_acceptance_original_changed", "editor_acceptance_change_summary_invalid",
    "editor_acceptance_draft_unexpectedly_submitted", "editor_acceptance_session_invalid",
    "editor_acceptance_no_eligible_applicant", "editor_acceptance_unexpected_failure",
    "editor_acceptance_session_cleanup_failed",
})
HTTP_FAILURE_PREFIXES = (
    "portal_auth_inventory_http", "finance_inventory_http", "handoff_http",
    "handoff_exchange_http", "auth_me_http", "finance_directory_http",
    "editor_acceptance_http", "editor_acceptance_tus_create_http",
    "editor_acceptance_tus_patch_http", "editor_acceptance_tus_head_http",
    "editor_acceptance_download_http",
)


class AcceptanceError(RuntimeError):
    """Machine-readable acceptance failure without account data."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def safe_failure_code(error: Exception | str, *, fallback: str = "acceptance_unexpected_failure") -> str:
    """Only literal local codes and bounded HTTP status codes may enter reports."""
    value = str(error)
    if value in SAFE_FAILURE_CODES:
        return value
    if any(re.fullmatch(re.escape(prefix) + r"_[1-5][0-9]{2}", value) for prefix in HTTP_FAILURE_PREFIXES):
        return value
    return fallback if fallback in SAFE_FAILURE_CODES else "acceptance_unexpected_failure"


def configured_supabase_origin(name: str) -> str:
    """An exact operator-configured project, never a wildcard provider domain."""
    origin = required_environment(name).rstrip("/")
    if re.fullmatch(r"https://[a-z0-9]{20}\.supabase\.co", origin) is None:
        raise AcceptanceError("acceptance_origin_invalid")
    return origin


def json_request_origins() -> frozenset[str]:
    origins = {EDOC_ORIGIN, PORTAL_ORIGIN}
    for name in ("SUPABASE_URL", "FINANCE_SOURCE_SUPABASE_URL"):
        if os.environ.get(name):
            origins.add(configured_supabase_origin(name))
    return frozenset(origins)


def require_allowed_https_url(url: str, origins: frozenset[str]) -> None:
    try:
        parsed = urllib.parse.urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        valid = (parsed.scheme == "https" and origin in origins
                 and parsed.username is None and parsed.password is None
                 and not parsed.fragment and "\\" not in url
                 and not any(ord(character) < 32 or ord(character) == 127 for character in url))
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise AcceptanceError("acceptance_origin_invalid")


def required_environment(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise AcceptanceError(f"missing_environment_{name.lower()}")
    return value


def request_bytes(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    data: bytes | None = None,
    cookie_jar: http.cookiejar.CookieJar | None = None,
) -> tuple[int, dict, bytes]:
    require_allowed_https_url(url, json_request_origins())
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
    handlers = [NoRedirect()]
    if cookie_jar is not None:
        handlers.append(urllib.request.HTTPCookieProcessor(cookie_jar))
    try:
        with urllib.request.build_opener(*handlers).open(request, timeout=TIMEOUT_SECONDS) as response:
            return int(response.status), dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return int(error.code), dict(error.headers), error.read()
    except (urllib.error.URLError, TimeoutError):
        raise AcceptanceError("acceptance_network_unavailable") from None


def request_json(url: str, *, headers: dict[str, str] | None = None,
                 method: str = "GET", data: bytes | None = None,
                 cookie_jar: http.cookiejar.CookieJar | None = None) -> tuple[int, dict]:
    status, _headers, body = request_bytes(url, headers=headers, method=method, data=data, cookie_jar=cookie_jar)
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
    except json.JSONDecodeError:
        raise AcceptanceError("supabase_linked_inventory_invalid") from None
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

    portal_url = configured_supabase_origin("SUPABASE_URL")
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

    finance_url = configured_supabase_origin("FINANCE_SOURCE_SUPABASE_URL")
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
    status, _headers, body = request_bytes(
        f"{finance_url}/rest/v1/finance_users?{query}",
        headers={
            "Accept": "application/json",
            "apikey": finance_key,
            "User-Agent": "edoc-live-acceptance/1",
        },
    )
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


def _acceptance_for_account(email: str, auth_user_id: str, secret: str, ordinal: int, issued_tokens: list[str]) -> dict[str, int]:
    jar = http.cookiejar.CookieJar()
    form = urllib.parse.urlencode(
        {"token": signed_handoff(email, auth_user_id, secret, ordinal)}
    ).encode("ascii")
    final_status, response_headers, _body = request_bytes(
        f"{EDOC_ORIGIN}/api/auth/handoff",
        data=form,
        method="POST",
        cookie_jar=jar, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": PORTAL_ORIGIN,
            "User-Agent": "edoc-live-acceptance/1",
        },
    )
    if final_status != 303:
        raise AcceptanceError(f"handoff_http_{final_status}")
    # A successful handoff returns a same-origin root location. Inspect it,
    # never replay the signed POST or automatically follow a credentialed hop.
    location = next((str(value) for key, value in response_headers.items() if key.lower() == "location"), "")
    target = urllib.parse.urljoin(EDOC_ORIGIN, location)
    require_allowed_https_url(target, frozenset({EDOC_ORIGIN}))
    if not location or target != EDOC_ORIGIN + "/":
        raise AcceptanceError("handoff_redirect_invalid")
    if not list(jar):
        raise AcceptanceError("handoff_cookie_missing")

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
        cookie_jar=jar,
    )
    if exchange_status != 200:
        raise AcceptanceError(f"handoff_exchange_http_{exchange_status}")
    token = str(exchange.get("token") or "")
    user = exchange.get("user") or {}
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
        raise AcceptanceError("handoff_exchange_token_invalid")
    issued_tokens.append(token)
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


def acceptance_for_account(email: str, auth_user_id: str, secret: str, ordinal: int) -> dict[str, int]:
    issued_tokens: list[str] = []
    try:
        result = _acceptance_for_account(email, auth_user_id, secret, ordinal, issued_tokens)
    finally:
        for token in issued_tokens:
            headers = {"Authorization": f"Bearer {token}"}
            status, payload = request_json(
                f"{EDOC_ORIGIN}/api/auth/logout", method="POST", data=b"", headers=headers,
            )
            if status != 200 or not payload.get("ok"):
                raise AcceptanceError("acceptance_session_cleanup_failed")
            me_status, _ = request_json(f"{EDOC_ORIGIN}/api/auth/me", headers=headers)
            if me_status != 401:
                raise AcceptanceError("acceptance_session_not_revoked")
    result["sessionRevoked"] = len(issued_tokens)
    return result


def main() -> int:
    if os.getenv("EDOC_ALLOW_SIGNED_IDENTITY_PROBE") != "1":
        raise AcceptanceError("signed_identity_probe_requires_explicit_authorization_not_human_sso")
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
            failures[safe_failure_code(error)] += 1
        except Exception:
            failures["acceptance_unexpected_failure"] += 1

    result = {
        "eligibleAccounts": len(eligible),
        "sampledAccounts": len(sampled),
        "passedAccounts": totals["handoff303"],
        "checks": dict(sorted(totals.items())),
        "failureCodes": dict(sorted(failures.items())),
        "piiPrinted": False,
        "coverage": "verified_google_identity_signed_handoff_and_directory",
        "humanGoogleLoginExercised": False,
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if totals["handoff303"] == SAMPLE_SIZE and not failures else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(
            json.dumps(
                {
                    "eligibleAccounts": 0,
                    "sampledAccounts": 0,
                    "passedAccounts": 0,
                    "checks": {},
                    "failureCodes": {safe_failure_code(error): 1},
                    "piiPrinted": False,
                    "humanGoogleLoginExercised": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        raise SystemExit(1)
