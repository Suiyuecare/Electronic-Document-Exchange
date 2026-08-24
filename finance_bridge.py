"""Server-to-server Finance identity bridge for EDOC.

The browser never calls this module and never receives the bridge secret.  Keep
this adapter deliberately small: Finance owns the roster and organization
logic; EDOC authenticates one request and validates the returned snapshot.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, Tuple


FINANCE_BRIDGE_SCHEMA_VERSION = 1
FINANCE_BRIDGE_MAX_RESPONSE_BYTES = 1024 * 1024
FINANCE_MEMBER_SYNC_SCHEMA_VERSION = 1
FINANCE_MEMBER_SYNC_MAX_REQUEST_BYTES = 256 * 1024
FINANCE_MEMBER_SYNC_MAX_AGE_SECONDS = 60
FINANCE_MEMBER_SYNC_EVENT_TYPES = {"member.changed", "company.changed"}
FINANCE_MEMBER_SYNC_ACTOR_SLOTS = {
    "applicantManager",
    "departmentHead",
    "ceo",
    "adminDirector",
    "generalAffairs",
}


class FinanceBridgeError(RuntimeError):
    """Base class whose message is always a non-sensitive machine code."""


class FinanceBridgeDenied(FinanceBridgeError):
    """Finance definitively denied or disabled the identity."""


class FinanceBridgeUnavailable(FinanceBridgeError):
    """The bridge could not provide a trustworthy current snapshot."""


class FinanceBridgeContractError(FinanceBridgeUnavailable):
    """The upstream response did not match the pinned contract."""


class FinanceMemberSyncError(RuntimeError):
    """Base class for the inbound Finance projection contract."""


class FinanceMemberSyncAuthError(FinanceMemberSyncError):
    """The inbound request could not be authenticated or was outside its window."""


class FinanceMemberSyncContractError(FinanceMemberSyncError):
    """The authenticated JSON did not match the pinned member-sync contract."""


def compact_finance_bridge_body(email: str, request_id: str) -> bytes:
    """Return the exact bytes covered by the request signature."""
    return json.dumps(
        {"email": str(email or "").strip().lower(), "requestId": str(request_id or "").strip()},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def finance_bridge_signature(secret: str, timestamp: str, nonce: str, raw_body: bytes) -> str:
    signed = b".".join((timestamp.encode("ascii"), nonce.encode("ascii"), raw_body))
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def finance_member_sync_signature(secret: str, timestamp: str, nonce: str, raw_body: bytes) -> str:
    """Sign the exact inbound roster event bytes with the shared bridge key."""
    signed = b".".join((timestamp.encode("ascii"), nonce.encode("ascii"), raw_body))
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def _sync_required_text(parent: Dict[str, Any], key: str, *, max_length: int = 512) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    return value.strip()


def _validate_sync_auth_user_id(parent: Dict[str, Any]) -> None:
    value = parent.get("authUserId")
    if value is None:
        return
    text = _sync_required_text(parent, "authUserId", max_length=36)
    try:
        parsed = uuid.UUID(text)
    except (ValueError, AttributeError) as exc:
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid") from exc
    if str(parsed) != text.lower():
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")


def _validate_member_sync_company(
    company: Any,
    *,
    allow_missing_name: bool = False,
) -> Dict[str, Any]:
    if not isinstance(company, dict):
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    allowed = {"tenantId", "entityId", "name", "taxId", "address", "active", "sourceUpdatedAt"}
    if set(company) - allowed:
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    _sync_required_text(company, "entityId", max_length=128)
    if allow_missing_name:
        name = company.get("name")
        if name is not None and (not isinstance(name, str) or len(name.strip()) > 300):
            raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    else:
        _sync_required_text(company, "name", max_length=300)
    for key, max_length in (("taxId", 64), ("address", 1000)):
        value = company.get(key)
        if allow_missing_name and value is None:
            continue
        if not isinstance(value, str) or len(value) > max_length:
            raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    _sync_required_text(company, "tenantId", max_length=128)
    if "sourceUpdatedAt" in company and company.get("sourceUpdatedAt") is not None:
        _sync_required_text(company, "sourceUpdatedAt", max_length=64)
    if "active" in company and not isinstance(company.get("active"), bool):
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    return company


def _validate_member_sync_identity(identity: Any, source_revision: int) -> Dict[str, Any]:
    if not isinstance(identity, dict):
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    allowed = {
        "tenantId", "financeUserId", "memberRevision", "name", "email", "role",
        "roleLabel", "entityId", "departmentCode", "orgStatus", "sourceUpdatedAt",
        "departmentName", "unitName", "jobTitle", "extension", "contactEmail",
        "active", "sourceActive", "authUserBound", "googleLoginVerified", "authUserId",
    }
    if set(identity) - allowed:
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    for key, max_length in (
        ("financeUserId", 160), ("name", 300), ("email", 254), ("role", 128),
        ("roleLabel", 300), ("entityId", 128), ("departmentCode", 160),
        ("orgStatus", 64), ("sourceUpdatedAt", 64),
    ):
        _sync_required_text(identity, key, max_length=max_length)
    email = str(identity["email"]).strip()
    if email.count("@") != 1 or any(char.isspace() for char in email):
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    for key in ("active", "authUserBound", "googleLoginVerified"):
        if not isinstance(identity.get(key), bool):
            raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    member_revision = identity.get("memberRevision", source_revision)
    if isinstance(member_revision, bool) or not isinstance(member_revision, int) or member_revision != source_revision:
        raise FinanceMemberSyncContractError("finance_member_sync_revision_mismatch")
    _sync_required_text(identity, "tenantId", max_length=128)
    if "sourceActive" in identity:
        if not isinstance(identity.get("sourceActive"), bool):
            raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
        # ``sourceActive`` is deliberately redundant: it lets the receiver
        # reject an upstream projection that accidentally changes the meaning
        # of ``active`` from Finance employment state to EDOC login readiness.
        if identity.get("sourceActive") is not identity.get("active"):
            raise FinanceMemberSyncContractError("finance_member_sync_active_mismatch")
    _validate_sync_auth_user_id(identity)
    for key, max_length in (
        ("departmentName", 300), ("unitName", 300), ("jobTitle", 300),
        ("extension", 64), ("contactEmail", 254),
    ):
        if key in identity and identity.get(key) is not None:
            value = identity.get(key)
            if not isinstance(value, str) or len(value.strip()) > max_length:
                raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    contact_email = str(identity.get("contactEmail") or "").strip()
    if contact_email and (contact_email.count("@") != 1 or any(char.isspace() for char in contact_email)):
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    return identity


def _validate_member_sync_actor(actor: Any) -> None:
    if actor is None:
        return
    if not isinstance(actor, dict):
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    allowed = {
        "tenantId", "financeUserId", "memberRevision", "name", "email", "role", "roleLabel", "entityId",
        "departmentCode", "departmentName", "unitName", "jobTitle", "extension", "contactEmail",
        "orgStatus", "sourceUpdatedAt", "active", "sourceActive", "authUserBound", "googleLoginVerified", "authUserId",
    }
    if set(actor) - allowed:
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    for key, max_length in (
        ("financeUserId", 160), ("name", 300), ("email", 254), ("role", 128),
        ("roleLabel", 300), ("entityId", 128), ("departmentCode", 160),
        ("orgStatus", 64), ("sourceUpdatedAt", 64),
    ):
        _sync_required_text(actor, key, max_length=max_length)
    for key in ("active", "authUserBound", "googleLoginVerified"):
        if not isinstance(actor.get(key), bool):
            raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    if "memberRevision" in actor:
        actor_revision = actor.get("memberRevision")
        if isinstance(actor_revision, bool) or not isinstance(actor_revision, int) or actor_revision < 1:
            raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    if "sourceActive" in actor:
        if not isinstance(actor.get("sourceActive"), bool):
            raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
        if actor.get("sourceActive") is not actor.get("active"):
            raise FinanceMemberSyncContractError("finance_member_sync_active_mismatch")
    email = str(actor["email"]).strip()
    if email.count("@") != 1 or any(char.isspace() for char in email):
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    for key, max_length in (
        ("tenantId", 128), ("authUserId", 160), ("departmentName", 300),
        ("unitName", 300), ("jobTitle", 300), ("extension", 64), ("contactEmail", 254),
    ):
        if key in actor and actor.get(key) is not None:
            value = actor.get(key)
            if not isinstance(value, str) or len(value.strip()) > max_length:
                raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    contact_email = str(actor.get("contactEmail") or "").strip()
    if contact_email and (contact_email.count("@") != 1 or any(char.isspace() for char in contact_email)):
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    _validate_sync_auth_user_id(actor)


def verify_finance_member_sync_request(
    raw_body: bytes,
    headers: Dict[str, Any],
    secret: str,
    *,
    now_timestamp: int | None = None,
) -> Dict[str, Any]:
    """Authenticate and validate one Finance→EDOC projection event.

    Authentication is intentionally completed before JSON parsing.  The caller
    must atomically claim the returned nonce hash in the database before any
    projection write.
    """
    if not isinstance(raw_body, bytes) or not raw_body or len(raw_body) > FINANCE_MEMBER_SYNC_MAX_REQUEST_BYTES:
        raise FinanceMemberSyncContractError("finance_member_sync_request_size_invalid")
    if len(str(secret or "").encode("utf-8")) < 32:
        raise FinanceMemberSyncAuthError("finance_member_sync_not_configured")
    normalized_headers = {str(key).strip().lower(): str(value).strip() for key, value in headers.items()}
    timestamp = normalized_headers.get("x-finance-timestamp", "")
    nonce = normalized_headers.get("x-finance-nonce", "")
    signature = normalized_headers.get("x-finance-signature", "").lower()
    # The wire contract is Unix seconds.  Milliseconds are deliberately not
    # coerced because silently changing units weakens expiry checks.
    if not re.fullmatch(r"[0-9]{10}", timestamp):
        raise FinanceMemberSyncAuthError("finance_member_sync_auth_invalid")
    if not re.fullmatch(r"[A-Za-z0-9_-]{22,128}", nonce):
        raise FinanceMemberSyncAuthError("finance_member_sync_auth_invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", signature):
        raise FinanceMemberSyncAuthError("finance_member_sync_auth_invalid")
    request_time = int(timestamp)
    current_time = int(time.time()) if now_timestamp is None else int(now_timestamp)
    if abs(current_time - request_time) > FINANCE_MEMBER_SYNC_MAX_AGE_SECONDS:
        raise FinanceMemberSyncAuthError("finance_member_sync_request_expired")
    expected_signature = finance_member_sync_signature(secret, timestamp, nonce, raw_body)
    if not hmac.compare_digest(signature, expected_signature):
        raise FinanceMemberSyncAuthError("finance_member_sync_auth_invalid")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinanceMemberSyncContractError("finance_member_sync_json_invalid") from exc
    if not isinstance(payload, dict):
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    common = {"source", "schemaVersion", "eventId", "eventType", "sourceRevision", "occurredAt", "company"}
    event_type = payload.get("eventType")
    allowed = common | ({"identity", "actors", "workflowReady", "issues"} if event_type == "member.changed" else set())
    if set(payload) - allowed or payload.get("source") != "finance":
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    if payload.get("schemaVersion") != FINANCE_MEMBER_SYNC_SCHEMA_VERSION or event_type not in FINANCE_MEMBER_SYNC_EVENT_TYPES:
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    event_id = _sync_required_text(payload, "eventId", max_length=160)
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", event_id):
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    source_revision = payload.get("sourceRevision")
    if isinstance(source_revision, bool) or not isinstance(source_revision, int) or source_revision < 1:
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    _sync_required_text(payload, "occurredAt", max_length=64)
    if event_type == "company.changed":
        company = _validate_member_sync_company(payload.get("company"))
        if "active" not in company or "sourceUpdatedAt" not in company:
            raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    else:
        issues = payload.get("issues")
        if not isinstance(issues, list) or len(issues) > 50:
            raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
        company_missing = "company_missing" in issues
        company = _validate_member_sync_company(
            payload.get("company"),
            allow_missing_name=company_missing,
        )
        if not str(company.get("name") or "").strip() and not company_missing:
            raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
        identity = _validate_member_sync_identity(payload.get("identity"), source_revision)
        if str(identity["entityId"]).strip() != str(company["entityId"]).strip():
            raise FinanceMemberSyncContractError("finance_member_sync_company_mismatch")
        tenant_id = str(identity["tenantId"]).strip()
        if tenant_id != str(company["tenantId"]).strip():
            raise FinanceMemberSyncContractError("finance_member_sync_tenant_mismatch")
        if not isinstance(payload.get("workflowReady"), bool):
            raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
        actors = payload.get("actors")
        if actors is not None:
            if not isinstance(actors, dict) or set(actors) - FINANCE_MEMBER_SYNC_ACTOR_SLOTS:
                raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
            for actor in actors.values():
                _validate_member_sync_actor(actor)
                if actor is not None and str(actor.get("tenantId") or "").strip() != tenant_id:
                    raise FinanceMemberSyncContractError("finance_member_sync_tenant_mismatch")
    return {
        "payload": payload,
        "timestamp": request_time,
        "nonce": nonce,
        "nonceHash": hashlib.sha256(nonce.encode("ascii")).hexdigest(),
        "payloadSha256": hashlib.sha256(raw_body).hexdigest(),
    }


def finance_member_event_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the pinned member event into the existing Finance snapshot shape."""
    if payload.get("eventType") != "member.changed":
        raise FinanceMemberSyncContractError("finance_member_sync_contract_invalid")
    identity = dict(payload.get("identity") or {})
    identity["memberRevision"] = int(payload["sourceRevision"])
    actors = {slot: None for slot in FINANCE_MEMBER_SYNC_ACTOR_SLOTS}
    actors.update(payload.get("actors") or {})
    return {
        "ok": True,
        "source": "finance",
        "schemaVersion": FINANCE_BRIDGE_SCHEMA_VERSION,
        "eventId": payload["eventId"],
        "snapshotAt": payload["occurredAt"],
        "identity": identity,
        "company": dict(payload["company"]),
        "actors": actors,
        "workflowReady": bool(payload.get("workflowReady")),
        "issues": list(payload.get("issues") or []),
    }


def signed_finance_bridge_request(
    email: str,
    request_id: str,
    secret: str,
    *,
    timestamp: str | None = None,
    nonce: str | None = None,
) -> Tuple[bytes, Dict[str, str]]:
    if len(str(secret or "").encode("utf-8")) < 32:
        raise FinanceBridgeUnavailable("finance_bridge_secret_too_short")
    raw_body = compact_finance_bridge_body(email, request_id)
    request_timestamp = timestamp or str(int(time.time()))
    request_nonce = nonce or secrets.token_urlsafe(24).rstrip("=")
    signature = finance_bridge_signature(secret, request_timestamp, request_nonce, raw_body)
    return raw_body, {
        "content-type": "application/json",
        "accept": "application/json",
        "x-edoc-timestamp": request_timestamp,
        "x-edoc-nonce": request_nonce,
        "x-edoc-signature": signature,
        "cache-control": "no-store",
    }


def _required_object(parent: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise FinanceBridgeContractError("finance_bridge_contract_invalid")
    return value


def _required_text(parent: Dict[str, Any], key: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value.strip():
        raise FinanceBridgeContractError("finance_bridge_contract_invalid")
    return value.strip()


def validate_finance_bridge_snapshot(snapshot: Any, expected_email: str) -> Dict[str, Any]:
    """Validate only the pinned v1 response; do not coerce authorization data."""
    if not isinstance(snapshot, dict):
        raise FinanceBridgeContractError("finance_bridge_contract_invalid")
    if snapshot.get("ok") is not True:
        raise FinanceBridgeDenied("finance_identity_denied")
    if snapshot.get("source") != "finance" or snapshot.get("schemaVersion") != FINANCE_BRIDGE_SCHEMA_VERSION:
        raise FinanceBridgeContractError("finance_bridge_contract_invalid")
    _required_text(snapshot, "snapshotAt")

    identity = _required_object(snapshot, "identity")
    company = _required_object(snapshot, "company")
    actors = _required_object(snapshot, "actors")
    if not isinstance(snapshot.get("workflowReady"), bool) or not isinstance(snapshot.get("issues"), list):
        raise FinanceBridgeContractError("finance_bridge_contract_invalid")

    for key in (
        "financeUserId",
        "name",
        "email",
        "role",
        "roleLabel",
        "entityId",
        "departmentCode",
        "orgStatus",
        "sourceUpdatedAt",
    ):
        _required_text(identity, key)
    for key in ("active", "authUserBound", "googleLoginVerified"):
        if not isinstance(identity.get(key), bool):
            raise FinanceBridgeContractError("finance_bridge_contract_invalid")
    if identity["email"].strip().lower() != str(expected_email or "").strip().lower():
        raise FinanceBridgeDenied("finance_identity_mismatch")
    if not identity["active"] or not identity["authUserBound"] or not identity["googleLoginVerified"]:
        raise FinanceBridgeDenied("finance_identity_denied")
    if identity["orgStatus"].strip().lower() not in {"active", "enabled", "啟用", "在職"}:
        raise FinanceBridgeDenied("finance_identity_denied")

    for key in ("entityId", "name"):
        _required_text(company, key)
    for key in ("taxId", "address"):
        if key not in company or company.get(key) is None or not isinstance(company.get(key), str):
            raise FinanceBridgeContractError("finance_bridge_contract_invalid")
    if company["entityId"].strip() != identity["entityId"].strip():
        raise FinanceBridgeDenied("finance_company_mismatch")

    # The actor value shape is validated by EDOC only when that exact workflow
    # step is required.  Finance may return null for an unavailable optional
    # actor while workflowReady=false.
    for key in ("applicantManager", "departmentHead", "ceo", "adminDirector", "generalAffairs"):
        if key not in actors or (actors[key] is not None and not isinstance(actors[key], dict)):
            raise FinanceBridgeContractError("finance_bridge_contract_invalid")
    return snapshot


def fetch_finance_bridge_snapshot(
    *,
    url: str,
    secret: str,
    timeout_seconds: float,
    email: str,
    request_id: str,
    require_https: bool = True,
) -> Dict[str, Any]:
    """Fetch one current Finance snapshot without logging request/response PII."""
    endpoint = str(url or "").strip()
    parsed = urllib.parse.urlparse(endpoint)
    if not endpoint or not secret:
        raise FinanceBridgeUnavailable("finance_bridge_not_configured")
    if len(str(secret).encode("utf-8")) < 32:
        raise FinanceBridgeUnavailable("finance_bridge_secret_too_short")
    if parsed.scheme not in ({"https"} if require_https else {"https", "http"}) or not parsed.netloc:
        raise FinanceBridgeUnavailable("finance_bridge_endpoint_invalid")
    if parsed.username or parsed.password or parsed.fragment:
        raise FinanceBridgeUnavailable("finance_bridge_endpoint_invalid")
    try:
        timeout = float(timeout_seconds)
    except (TypeError, ValueError) as exc:
        raise FinanceBridgeUnavailable("finance_bridge_timeout_invalid") from exc
    if timeout <= 0 or timeout > 15:
        raise FinanceBridgeUnavailable("finance_bridge_timeout_invalid")

    raw_body, headers = signed_finance_bridge_request(email, request_id, secret)
    request = urllib.request.Request(endpoint, data=raw_body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_response = response.read(FINANCE_BRIDGE_MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403, 404, 409, 422}:
            raise FinanceBridgeDenied("finance_identity_denied") from exc
        raise FinanceBridgeUnavailable("finance_bridge_unavailable") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FinanceBridgeUnavailable("finance_bridge_unavailable") from exc
    if len(raw_response) > FINANCE_BRIDGE_MAX_RESPONSE_BYTES:
        raise FinanceBridgeContractError("finance_bridge_response_too_large")
    try:
        payload = json.loads(raw_response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinanceBridgeContractError("finance_bridge_contract_invalid") from exc
    return validate_finance_bridge_snapshot(payload, email)
