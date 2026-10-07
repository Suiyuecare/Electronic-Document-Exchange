"""SQLite transactional candidate adapter, not yet a production API.

Backend handlers must pass a server-validated session. Stored Finance rows, not
session role claims, are authoritative for every operation. No mail or exchange
is sent; notifications are in-system only and part of the same transaction.
Supabase/UI parity and human SSO acceptance remain separate release gates.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager

import official_handover as policy


def _binding(conn, document, backend):
    import official_handover_followup
    row = conn.execute("SELECT 1 FROM official_document_followup_owners WHERE document_id=?", (document["id"],)).fetchone()
    if not row:
        return None
    binding = official_handover_followup.load(backend, document, conn=conn, allow_inactive_owner=True)
    if not binding:
        raise PermissionError("handover_followup_lineage_invalid")
    return binding


@contextmanager
def _transaction(conn):
    name = "handover_" + secrets.token_hex(6)
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield
        conn.execute(f"RELEASE SAVEPOINT {name}")
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
        conn.execute(f"RELEASE SAVEPOINT {name}")
        raise


def _user(conn, identity):
    row = conn.execute("SELECT * FROM users WHERE id=?", (identity,)).fetchone()
    if not row:
        raise PermissionError("handover_finance_actor_missing")
    return dict(row)


def _actor(conn, session):
    identity = (session or {}).get("user", {}).get("id")
    if not identity:
        raise PermissionError("authentication_required")
    actor = _user(conn, identity)
    if actor.get("status") != "啟用" or actor.get("account_source") != "finance":
        raise PermissionError("handover_finance_actor_inactive")
    return actor


def _load(conn, document_id, actor, roles):
    row = conn.execute("SELECT * FROM official_documents WHERE id=?", (document_id,)).fetchone()
    if not row:
        raise ValueError("official_document_not_found")
    document = dict(row)
    row = conn.execute("SELECT * FROM companies WHERE id=?", (document["company_id"],)).fetchone()
    if not row:
        raise PermissionError("handover_finance_scope_forbidden")
    company = dict(row)
    policy._scope(document, company, actor)
    if actor.get("role") not in roles:
        raise PermissionError("handover_manage_forbidden")
    # Take SQLite's write reservation before loading versions/steps. This is
    # intentionally within the savepoint; failed authorization rolls back.
    conn.execute("UPDATE official_documents SET updated_at=updated_at WHERE id=?", (document_id,))
    document = dict(conn.execute("SELECT * FROM official_documents WHERE id=?", (document_id,)).fetchone())
    steps = [dict(row) for row in conn.execute(
        "SELECT * FROM official_document_approval_steps WHERE document_id=? ORDER BY workflow_generation,step_order", (document_id,))]
    stamp = conn.execute("SELECT * FROM official_document_stamp_requests WHERE document_id=? ORDER BY created_at DESC,id DESC LIMIT 1", (document_id,)).fetchone()
    return document, steps, company, dict(stamp) if stamp else None


def _request(row):
    record = json.loads(row["request_json"])
    for key in ("id", "document_id", "company_id", "finance_tenant_id", "kind", "former_user_id",
                "successor_user_id", "proposer_user_id", "request_sha256"):
        if record.get(key) != row[key]:
            raise ValueError("handover_stored_request_corrupt")
    return {**record, "status": row["status"], "confirmer_user_id": row["confirmer_user_id"]}


def propose(conn, document_id, payload, session, *, backend):
    with _transaction(conn):
        actor = _actor(conn, session)
        document, steps, company, stamp = _load(conn, document_id, actor, policy.PROPOSER_ROLES)
        operation = policy._identity(payload.get("operation_id"), "operation_id")
        existing = conn.execute("SELECT * FROM official_document_handovers WHERE id=?", (operation,)).fetchone()
        if existing:
            record = _request(existing)
            expected = {"document_id": document_id, "proposer_user_id": actor["id"],
                        "former_user_id": payload.get("former_user_id"), "successor_user_id": payload.get("successor_user_id"),
                        "kind": payload.get("kind"), "reason": str(payload.get("reason") or "").strip(),
                        "expected_fingerprint": payload.get("expected_fingerprint")}
            if any(record.get(key) != value for key, value in expected.items()):
                raise policy.HandoverConflict("handover_operation_conflict")
            return {"request": record, "idempotent": True}
        former = _user(conn, payload.get("former_user_id"))
        successor = _user(conn, payload.get("successor_user_id"))
        binding = _binding(conn, document, backend)
        record = policy.propose_handover(document, steps, company, actor, former, successor,
                                         payload, timestamp=backend.now(), stamp=stamp, binding=binding)
        try:
            backend.insert_row(conn, "official_document_handovers", {
                **{key: record[key] for key in ("id", "document_id", "company_id", "finance_tenant_id", "kind",
                    "former_user_id", "successor_user_id", "proposer_user_id", "confirmer_user_id", "status",
                    "request_sha256", "created_at", "updated_at")},
                "request_json": policy._json(record), "result_json": None,
                "expected_snapshot": policy._json(policy.handover_snapshot(document, steps, stamp, binding))})
        except sqlite3.IntegrityError as exc:
            raise policy.HandoverConflict("handover_pending_request_exists") from exc
        backend.log_audit(conn, actor["id"], "handover_proposed", "official_documents", document_id,
                          "handover_id=" + operation, actor_user_id=actor["id"], request_id=operation,
                          metadata={"kind": record["kind"], "request_sha256": record["request_sha256"]})
        return {"request": record, "idempotent": False}


def confirm(conn, request_id, session, *, backend):
    with _transaction(conn):
        actor = _actor(conn, session)
        row = conn.execute("SELECT * FROM official_document_handovers WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise ValueError("handover_request_not_found")
        record = _request(row)
        document, steps, company, stamp = _load(conn, record["document_id"], actor, policy.CONFIRMER_ROLES)
        row = conn.execute("SELECT * FROM official_document_handovers WHERE id=?", (request_id,)).fetchone()
        record = _request(row)
        if record["status"] == "approved":
            if record["confirmer_user_id"] != actor["id"]:
                raise PermissionError("handover_replay_actor_forbidden")
            return {**json.loads(row["result_json"]), "idempotent": True}
        if record["status"] != "pending":
            raise policy.HandoverConflict("handover_request_already_resolved")
        binding = _binding(conn, document, backend)
        if json.loads(row["expected_snapshot"]) != policy.handover_snapshot(document, steps, stamp, binding):
            raise policy.HandoverConflict("handover_version_conflict")
        plan = policy.confirm_handover(record, document, steps, company, actor,
                                       _user(conn, record["proposer_user_id"]),
                                       _user(conn, record["former_user_id"]), _user(conn, record["successor_user_id"]),
                                       timestamp=backend.now(), stamp=stamp, binding=binding)
        timestamp = plan["request"]["updated_at"]
        if plan["followup_binding"]:
            previous = binding
            binding = plan["followup_binding"]
            keys = ("document_id", "original_applicant_id", "process_owner_user_id", "handover_id",
                    "company_id", "finance_tenant_id", "correction_policy", "updated_at")
            if previous:
                changed = conn.execute("UPDATE official_document_followup_owners SET process_owner_user_id=?,handover_id=?,updated_at=? WHERE document_id=? AND handover_id=? AND process_owner_user_id=?",
                    (binding["process_owner_user_id"], binding["handover_id"], binding["updated_at"], document["id"], previous["handover_id"], previous["process_owner_user_id"]))
                if changed.rowcount != 1: raise policy.HandoverConflict("handover_version_conflict")
            else:
                conn.execute("INSERT INTO official_document_followup_owners (document_id,original_applicant_id,process_owner_user_id,handover_id,company_id,finance_tenant_id,correction_policy,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                             tuple(binding[key] for key in keys))
        for step_id in plan["skip_step_ids"]:
            changed = conn.execute("UPDATE official_document_approval_steps SET status='skipped',updated_at=? WHERE id=? AND document_id=? AND status='pending'", (timestamp, step_id, document["id"]))
            if changed.rowcount != 1:
                raise policy.HandoverConflict("handover_version_conflict")
        for step in plan["replacement_steps"]:
            backend.insert_row(conn, "official_document_approval_steps", {
                **step, "decision_evidence_json": policy._json(step["decision_evidence_json"])})
        backend.snapshot_official_document_approval_steps(conn, document["id"], plan["replacement_steps"])
        if plan["document_patch"]:
            conn.execute("UPDATE official_documents SET updated_at=? WHERE id=?", (timestamp, document["id"]))
        receipt = {"document_id": document["id"], "handover_id": request_id,
                   "kind": record["kind"], "status": "approved", "idempotent": False,
                   "workflow_generation": max((step["workflow_generation"] for step in plan["replacement_steps"]), default=None)}
        changed = conn.execute("UPDATE official_document_handovers SET status='approved',confirmer_user_id=?,request_json=?,result_json=?,updated_at=? WHERE id=? AND status='pending'", (actor["id"], policy._json(plan["request"]), policy._json(receipt), timestamp, request_id))
        if changed.rowcount != 1:
            raise policy.HandoverConflict("handover_request_already_resolved")
        backend.insert_row(conn, "official_document_approval_logs", {
            "id": "HLOG-" + request_id, "document_id": document["id"], "actor_id": actor["id"],
            "actor_name": actor["name"], "action": "handover_confirmed", "comment": record["reason"],
            "decision_evidence_json": policy._json({"handover_id": request_id,
                "former_user_id": record["former_user_id"], "successor_user_id": record["successor_user_id"],
                "proposer_user_id": record["proposer_user_id"], "confirmer_user_id": actor["id"],
                "kind": record["kind"], "request_sha256": record["request_sha256"]}), "created_at": timestamp})
        for recipient_id in plan["notification_user_ids"]:
            recipient = _user(conn, recipient_id)
            policy._scope(document, company, recipient)
            backend.create_notification(conn, {"id": "HN-" + request_id + "-" + recipient_id,
                "type": "案件交接", "title": "交接已確認", "target_user_id": recipient_id,
                "target_company_id": company["id"], "channel": "系統通知", "source": document["id"],
                "body": "請至簽核紀錄查看交接案件。", "created_at": timestamp})
        backend.log_audit(conn, actor["id"], "handover_confirmed", "official_documents", document["id"],
                          "handover_id=" + request_id, actor_user_id=actor["id"], request_id=request_id,
                          metadata={"kind": record["kind"], "request_sha256": record["request_sha256"]})
        return receipt


def reject(conn, request_id, reason, session, *, backend):
    with _transaction(conn):
        actor = _actor(conn, session)
        row = conn.execute("SELECT * FROM official_document_handovers WHERE id=?", (request_id,)).fetchone()
        if not row: raise ValueError("handover_request_not_found")
        record = _request(row)
        document, _, company, _ = _load(conn, record["document_id"], actor, policy.CONFIRMER_ROLES)
        row = conn.execute("SELECT * FROM official_document_handovers WHERE id=?", (request_id,)).fetchone()
        record = _request(row)
        if record["status"] == "rejected":
            if record["confirmer_user_id"] != actor["id"] or record.get("rejection_reason") != str(reason or "").strip():
                raise policy.HandoverConflict("handover_operation_conflict")
            return {**json.loads(row["result_json"]), "idempotent": True}
        resolved = policy.reject_handover(record, document, company, actor, reason=reason, timestamp=backend.now())
        receipt = {"document_id": document["id"], "handover_id": request_id, "status": "rejected", "idempotent": False}
        changed = conn.execute("UPDATE official_document_handovers SET status='rejected',confirmer_user_id=?,request_json=?,result_json=?,updated_at=? WHERE id=? AND status='pending'",
            (actor["id"], policy._json(resolved), policy._json(receipt), resolved["updated_at"], request_id))
        if changed.rowcount != 1: raise policy.HandoverConflict("handover_request_already_resolved")
        backend.log_audit(conn, actor["id"], "handover_rejected", "official_documents", document["id"],
                          "handover_id=" + request_id, actor_user_id=actor["id"], request_id=request_id,
                          metadata={"request_sha256": record["request_sha256"]})
        return receipt
