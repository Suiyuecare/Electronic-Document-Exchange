"""Server-side offboarding policy; no external calls or browser authority.

Callers must load all inputs from authoritative Finance/EDOC storage and commit
the returned plan atomically with live version/identity checks. This module does
not grant access or persist changes by itself. Production exposure is gated on
SQLite/PostgreSQL/API/browser parity and human SSO acceptance.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

PROPOSER_ROLES = frozenset({"總務"})
CONFIRMER_ROLES = frozenset({"行政部主任", "行政部門主任"})
KINDS = frozenset({"pending_approver", "followup_owner"})
NON_REVIEW_STATES = frozenset({
    "draft", "rejected", "declined", "cancelled", "approved", "stamping",
    "stamped", "stamping_failed", "pending_general_affairs_dispatch",
    "returned_to_applicant_for_send", "dispatched", "sent_by_applicant", "closed",
})


class HandoverConflict(ValueError):
    """A changed version requires explicit reload, not silent reassignment."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _object(value: Any) -> dict:
    if isinstance(value, str):
        value = json.loads(value or "{}")
    if not isinstance(value, dict):
        raise ValueError("handover_corrupt_evidence")
    return value


def _identity(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{8,120}", value):
        raise ValueError(f"handover_{label}_invalid")
    return value


def _scope(document: dict, company: dict, user: dict, *, active: bool = True) -> None:
    tenant = company.get("finance_tenant_id")
    if (not document.get("id") or not document.get("company_id")
            or company.get("id") != document["company_id"] or not tenant
            or company.get("source_system") != "finance" or company.get("status") != "active"
            or not user.get("id") or user.get("account_source") != "finance"
            or user.get("company_id") != company["id"]
            or user.get("finance_tenant_id") != tenant
            or (active and user.get("status") != "啟用")):
        raise PermissionError("handover_finance_scope_forbidden")


def _current_steps(document: dict, steps: list[dict]) -> list[dict]:
    if not steps:
        return []
    if any(row.get("document_id") != document["id"] for row in steps):
        raise ValueError("handover_step_document_mismatch")
    generation = max(int(row.get("workflow_generation") or 1) for row in steps)
    rows = sorted((copy.deepcopy(row) for row in steps
                   if int(row.get("workflow_generation") or 1) == generation),
                  key=lambda row: int(row["step_order"]))
    if (len({row.get("id") for row in rows}) != len(rows)
            or len({row.get("step_key") for row in rows}) != len(rows)
            or len({row.get("step_order") for row in rows}) != len(rows)
            or any(not row.get("id") or row.get("status") not in {"pending", "approved", "rejected", "skipped"} for row in rows)):
        raise ValueError("handover_corrupt_workflow")
    return rows


def _snapshot(document: dict, rows: list[dict], stamp: dict | None, binding: dict | None = None) -> dict:
    # Assignment changes, actual decisions and a newly claimed stamp matter
    # even when legacy second-resolution updated_at happens to be unchanged.
    payload = {"document": {key: document.get(key) for key in (
        "id", "company_id", "applicant_id", "current_status", "current_step",
        "content_revision", "updated_at", "stamped_file_id")},
        "steps": [{key: row.get(key) for key in (
            "id", "workflow_generation", "step_order", "step_key", "approver_user_id",
            "approver_name", "approver_role", "status", "decision_actor_user_id",
            "approved_at", "updated_at", "decision_evidence_json")} for row in rows],
        "stamp": {key: (stamp or {}).get(key) for key in (
            "id", "status", "claim_token", "stamped_file_id", "updated_at")}}
    for step in payload["steps"]:
        step["decision_evidence_json"] = _object(step["decision_evidence_json"] or {})
    if binding:
        payload["followup_binding"] = {key: binding.get(key) for key in (
            "document_id", "original_applicant_id", "process_owner_user_id", "handover_id",
            "company_id", "finance_tenant_id", "correction_policy", "updated_at")}
    return payload


def _fingerprint(document: dict, rows: list[dict], stamp: dict | None, binding: dict | None = None) -> str:
    return hashlib.sha256(_json(_snapshot(document, rows, stamp, binding)).encode()).hexdigest()


def _eligible(document: dict, rows: list[dict], former: dict, successor: dict,
              kind: str, stamp: dict | None, binding: dict | None = None) -> list[dict]:
    if kind not in KINDS:
        raise ValueError("handover_kind_invalid")
    if former.get("status") == "啟用":
        raise PermissionError("handover_former_still_active")
    if former["id"] == successor["id"]:
        raise PermissionError("handover_successor_invalid")
    if kind == "followup_owner":
        expected_former = (binding or {}).get("process_owner_user_id") or document.get("applicant_id")
        if former["id"] != expected_former:
            raise PermissionError("handover_not_original_applicant")
        if successor["id"] == document.get("applicant_id"):
            raise PermissionError("handover_successor_invalid")
        return []
    if (document.get("current_status") in NON_REVIEW_STATES
            or document.get("current_step") in {"", None, "applicant_confirm", "auto_stamp"}
            or document.get("stamped_file_id")
            or (stamp and (stamp.get("claim_token") or stamp.get("stamped_file_id")
                           or stamp.get("status") in {"stamping", "stamped", "completed"}))):
        raise HandoverConflict("handover_workflow_irreversible")
    pending = [row for row in rows if row.get("status") == "pending"]
    if not pending or pending[0]["step_key"] != document["current_step"]:
        raise HandoverConflict("handover_current_step_conflict")
    expected_status = ("pending_approval" if pending[0]["step_key"].startswith("approval_")
                       else "pending_" + pending[0]["step_key"])
    if document.get("current_status") != expected_status:
        raise HandoverConflict("handover_current_step_conflict")
    targets = [row for row in pending if row.get("approver_user_id") == former["id"]
               and row["step_key"] != "applicant_confirm"]
    if not targets:
        raise HandoverConflict("handover_pending_assignment_missing")
    if successor["id"] == document.get("applicant_id"):
        raise PermissionError("handover_self_approval_forbidden")
    if any(row.get("approver_user_id") == successor["id"] for row in rows):
        raise PermissionError("handover_duplicate_approver_forbidden")
    # An equivalent live Finance role is the conservative default. A custom
    # designated-person node does not turn a regular employee into a manager.
    if not former.get("role") or successor.get("role") != former["role"]:
        raise PermissionError("handover_successor_role_forbidden")
    if any(row.get("status") in {"rejected", "skipped"} for row in rows):
        raise HandoverConflict("handover_corrupt_active_generation")
    return targets


def propose_handover(document: dict, steps: list[dict], company: dict,
                     proposer: dict, former: dict, successor: dict,
                     payload: dict, *, timestamp: str, stamp: dict | None = None, binding: dict | None = None) -> dict:
    """Validate a proposal without changing document, assignments or permissions."""
    operation_id = _identity(payload.get("operation_id"), "operation_id")
    kind = payload.get("kind")
    reason = str(payload.get("reason") or "").strip()
    if kind not in KINDS or not 6 <= len(reason) <= 2000 or not timestamp:
        raise ValueError("handover_proposal_invalid")
    for user, active in ((proposer, True), (former, False), (successor, True)):
        _scope(document, company, user, active=active)
    if proposer.get("role") not in PROPOSER_ROLES:
        raise PermissionError("handover_propose_forbidden")
    if proposer["id"] in {former["id"], successor["id"], document.get("applicant_id")}:
        raise PermissionError("handover_proposer_is_party")
    rows = _current_steps(document, steps)
    targets = _eligible(document, rows, former, successor, kind, stamp, binding)
    fingerprint = _fingerprint(document, rows, stamp, binding)
    if payload.get("expected_fingerprint") != fingerprint:
        raise HandoverConflict("handover_version_conflict")
    body = {"document_id": document["id"], "company_id": company["id"],
            "finance_tenant_id": company["finance_tenant_id"], "kind": kind,
            "former_user_id": former["id"], "successor_user_id": successor["id"],
            "proposer_user_id": proposer["id"], "reason": reason,
            "expected_fingerprint": fingerprint, "step_ids": [row["id"] for row in targets]}
    if binding:
        body["previous_handover_id"] = binding["handover_id"]
    return {**body, "id": operation_id,
            "request_sha256": hashlib.sha256(_json(body).encode()).hexdigest(),
            "status": "pending", "created_at": timestamp, "updated_at": timestamp,
            "confirmer_user_id": None, "confirmed_at": None}


def handover_fingerprint(document: dict, steps: list[dict], stamp: dict | None = None, binding: dict | None = None) -> str:
    return _fingerprint(document, _current_steps(document, steps), stamp, binding)


def handover_snapshot(document: dict, steps: list[dict], stamp: dict | None = None, binding: dict | None = None) -> dict:
    """Typed CAS witness for PostgreSQL; no cross-runtime JSON-text hashing."""
    return _snapshot(document, _current_steps(document, steps), stamp, binding)


def confirm_handover(request: dict, document: dict, steps: list[dict], company: dict,
                     confirmer: dict, proposer: dict, former: dict, successor: dict,
                     *, timestamp: str, stamp: dict | None = None, binding: dict | None = None) -> dict:
    """Plan a new immutable generation, or a separate follow-up binding.

    Idempotent committed replay belongs to the transactional adapter, which
    must match the original request and confirmer before returning a receipt.
    """
    _identity(request.get("id"), "operation_id")
    for user, active in ((confirmer, True), (proposer, True), (former, False), (successor, True)):
        _scope(document, company, user, active=active)
    if (confirmer.get("role") not in CONFIRMER_ROLES
            or proposer.get("role") not in PROPOSER_ROLES
            or confirmer["id"] in {proposer["id"], former["id"], successor["id"], document.get("applicant_id")}
            or request.get("proposer_user_id") != proposer["id"]
            or request.get("former_user_id") != former["id"]
            or request.get("successor_user_id") != successor["id"]
            or request.get("document_id") != document["id"]
            or request.get("company_id") != company["id"]
            or request.get("finance_tenant_id") != company["finance_tenant_id"]):
        raise PermissionError("handover_confirm_forbidden")
    if request.get("status") != "pending":
        raise HandoverConflict("handover_request_already_resolved")
    rows = _current_steps(document, steps)
    if request.get("expected_fingerprint") != _fingerprint(document, rows, stamp, binding):
        raise HandoverConflict("handover_version_conflict")
    if request.get("previous_handover_id") != (binding or {}).get("handover_id"):
        raise HandoverConflict("handover_version_conflict")
    targets = _eligible(document, rows, former, successor, request.get("kind"), stamp, binding)
    if request.get("step_ids") != [row["id"] for row in targets]:
        raise HandoverConflict("handover_assignment_conflict")
    result = {"request": {**copy.deepcopy(request), "status": "approved",
                          "confirmer_user_id": confirmer["id"], "confirmed_at": timestamp,
                          "updated_at": timestamp},
              "document_id": document["id"], "expected_fingerprint": request["expected_fingerprint"],
              "replacement_steps": [], "skip_step_ids": [], "document_patch": {},
              "notification_user_ids": sorted({proposer["id"], successor["id"]}),
              "followup_binding": None}
    if request["kind"] == "followup_owner":
        result["followup_binding"] = {
            "document_id": document["id"], "original_applicant_id": document["applicant_id"],
            "process_owner_user_id": successor["id"], "handover_id": request["id"],
            "company_id": company["id"], "finance_tenant_id": company["finance_tenant_id"],
            "correction_policy": "linked_new_application", "updated_at": timestamp}
        return result
    generation = int(rows[0].get("workflow_generation") or 1) + 1
    replaced_ids = {row["id"] for row in targets}
    for source in rows:
        fresh = copy.deepcopy(source)
        fresh.update(id="HSTEP-" + hashlib.sha256(
            f"{request['id']}:{source['id']}:{generation}".encode()).hexdigest()[:40],
            workflow_generation=generation, created_at=timestamp, updated_at=timestamp)
        if source["status"] == "approved":
            evidence = copy.deepcopy(_object(source.get("decision_evidence_json") or {}))
        else:
            evidence = {}
            fresh.update(comment="", approved_at=None, review_started_at=None,
                         decision_actor_user_id=None)
            result["skip_step_ids"].append(source["id"])
        fresh["decision_evidence_json"] = {**evidence, "copied_from_step_id": source["id"]}
        if source["status"] == "pending":
            # Reuse the existing immutable workflow-operation provenance
            # contract. Introducing an arbitrary evidence key would make the
            # canonical review validator reject a later real approval.
            fresh["decision_evidence_json"]["added_by_operation_id"] = request["id"]
        if source["id"] in replaced_ids:
            fresh.update(approver_user_id=successor["id"], approver_name=successor["name"])
        result["replacement_steps"].append(fresh)
    current = next(row for row in result["replacement_steps"] if row["status"] == "pending")
    current["review_started_at"] = timestamp
    result["document_patch"] = {"updated_at": timestamp}
    result["notification_user_ids"] = sorted(set(result["notification_user_ids"] + [current["approver_user_id"]]))
    return result


def linked_application_seed(document: dict, binding: dict, company: dict, owner: dict,
                            *, today: str) -> dict:
    """Return safe new-case content, never the original ID, number or approval.

    Attachments and editor/stamp placements are deliberately not copied. They
    need fresh authorized selection and integrity checks on the new case.
    The adapter must persist the original/new relation server-side, not trust
    browser metadata, and apply normal creation/numbering/approval rules.
    """
    _scope(document, company, owner)
    if (binding.get("process_owner_user_id") != owner["id"]
            or binding.get("document_id") != document["id"]
            or binding.get("original_applicant_id") != document["applicant_id"]
            or binding.get("company_id") != company["id"]
            or binding.get("finance_tenant_id") != company["finance_tenant_id"]
            or binding.get("correction_policy") != "linked_new_application"
            or not binding.get("handover_id")):
        raise PermissionError("handover_linked_application_forbidden")
    if document.get("current_status") not in {"draft", "rejected"}:
        raise HandoverConflict("handover_original_not_correctable")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", today):
        raise ValueError("handover_dispatch_date_invalid")
    content_keys = ("company_id", "source_type", "title", "subject", "description", "method",
                    "recipient", "document_type", "dispatch_method", "output_mode", "request_reason")
    return {"payload": {**{key: copy.deepcopy(document[key]) for key in content_keys if key in document},
                        "dispatch_date": today},
            "relation": {"original_document_id": document["id"],
                         "handover_id": binding["handover_id"], "created_by_user_id": owner["id"],
                         "relation_type": "offboarding_correction"},
            "requires_fresh_files": True, "requires_full_approval": True}


def reject_handover(request: dict, document: dict, company: dict, actor: dict,
                     *, reason: str, timestamp: str) -> dict:
    """Resolve a stale proposal without granting authority or changing a case.

    Rejection remains possible when the proposed successor or proposer has
    since left. Otherwise an invalid pending proposal could block all recovery.
    """
    _scope(document, company, actor)
    reason = str(reason or "").strip()
    if actor.get("role") not in CONFIRMER_ROLES or actor["id"] in {
        request.get("proposer_user_id"), request.get("former_user_id"),
        request.get("successor_user_id"), document.get("applicant_id")
    } or request.get("document_id") != document["id"] or request.get("company_id") != company["id"] \
            or request.get("finance_tenant_id") != company["finance_tenant_id"]:
        raise PermissionError("handover_reject_forbidden")
    if request.get("status") != "pending":
        raise HandoverConflict("handover_request_already_resolved")
    if not 2 <= len(reason) <= 2000 or not timestamp:
        raise ValueError("handover_rejection_reason_required")
    return {**copy.deepcopy(request), "status": "rejected", "confirmer_user_id": actor["id"],
            "rejection_reason": reason, "updated_at": timestamp}
