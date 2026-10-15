"""Scoped dispatch pages and atomic mutations shared by storage adapters.

Only exact recipients receive an outbox item. External delivery belongs to the
existing notification worker, never to a database transaction.
"""
from contextlib import contextmanager
import hashlib
import json
import re
import secrets

from workflow_readiness import inbound_list_options, inbound_page


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS internal_dispatch_mutations (
  actor_user_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  request_sha256 TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(actor_user_id, idempotency_key),
  FOREIGN KEY(dispatch_id) REFERENCES internal_dispatches(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_dispatch_keyset ON internal_dispatches(created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_dispatch_inbound ON internal_dispatches(inbound_document_id,id);
CREATE INDEX IF NOT EXISTS idx_dispatch_recipient_actor ON internal_dispatch_recipients(recipient_user_id,dispatch_id);
"""


@contextmanager
def atomic(conn):
    """Acquire SQLite's write reservation before any state-dependent read."""
    owns = not conn.in_transaction
    name = "dispatch_" + secrets.token_hex(6)
    if owns:
        conn.execute("BEGIN IMMEDIATE")
    else:
        conn.execute(f"SAVEPOINT {name}")
        conn.execute("UPDATE internal_dispatch_mutations SET created_at=created_at WHERE 0")
    try:
        yield
        conn.commit() if owns else conn.execute(f"RELEASE SAVEPOINT {name}")
    except Exception:
        if owns:
            conn.rollback()
        else:
            conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
            conn.execute(f"RELEASE SAVEPOINT {name}")
        raise


def pending_count(recipients):
    return sum(bool(r.get("action_required")) and r.get("status") not in {"replied", "reassigned"} for r in recipients)


def actor_recipient(recipients, actor_id):
    current = [r for r in recipients if r.get("recipient_user_id") == actor_id and r.get("status") != "reassigned"]
    return max(current, key=lambda r: (bool(r.get("action_required")) and r.get("status") != "replied",
                                       str(r.get("created_at") or ""), str(r.get("id") or "")), default=None)


def request_identity(payload):
    key = str(payload.get("idempotency_key") or "").strip()
    # Legacy clients have no stable request identity. Do not merge legitimate
    # identical dispatches by a content hash; the current UI always sends a key.
    if not key:
        key = "legacy-" + secrets.token_hex(16)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}", key):
        raise ValueError("internal_dispatch_idempotency_key_required")
    semantic = {k: payload.get(k) for k in ("title", "subject", "body", "inbound_document_id", "official_document_id", "document_id", "recipients", "reply_required", "reply_due_days", "due_at", "metadata") if k in payload}
    digest = hashlib.sha256(json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return key, digest


def options(api, query, user, session):
    needs_reply = str(((query or {}).get("needs_reply") or [""])[0]) in {"1", "true"}
    scope = {"actor": user["id"], "company": user.get("company_id") or "", "tenant": user.get("finance_tenant_id") or "",
             "wide": api.session_has_any_permission(session, ["official_documents.all_records", "official_documents.all_todo"]), "needs_reply": needs_reply}
    try:
        opts = inbound_list_options(query, scope)
    except ValueError as exc:
        raise ValueError(str(exc).replace("inbound_list_", "internal_dispatch_list_")) from None
    if opts["assignee_user_id"] or opts["q"]:
        raise ValueError("internal_dispatch_list_filter_invalid")
    return opts, scope


def local_list(api, conn, query, session):
    user = api.official_session_user(session)
    opts, scope = options(api, query, user, session)
    # Scope is applied before keyset/limit, including company-wide readers.
    where = ["COALESCE(i.company_id,o.company_id,s.company_id,'') = ?",
             "COALESCE(i.finance_tenant_id,c.finance_tenant_id,s.finance_tenant_id,'') = ?"]
    params = [scope["company"], scope["tenant"]]
    if not scope["wide"]:
        where.append("(d.sender_user_id=? OR EXISTS(SELECT 1 FROM internal_dispatch_recipients r WHERE r.dispatch_id=d.id AND r.recipient_user_id=?))")
        params.extend([user["id"], user["id"]])
    if opts["status"]:
        where.append("d.status=?")
        params.append(opts["status"])
    if scope["needs_reply"]:
        where.append("d.status NOT IN ('closed','cancelled') AND COALESCE(d.closed_at,'')='' AND EXISTS(SELECT 1 FROM internal_dispatch_recipients r WHERE r.dispatch_id=d.id AND r.recipient_user_id=? AND r.action_required=1 AND r.status NOT IN ('replied','reassigned'))")
        params.append(user["id"])
    if opts["after"]:
        where.append("(d.created_at,d.id)<(?,?)")
        params.extend(opts["after"])
    sql = """SELECT d.id FROM internal_dispatches d
      LEFT JOIN inbound_documents i ON i.id=d.inbound_document_id
      LEFT JOIN official_documents o ON o.id=d.official_document_id AND i.id IS NULL
      LEFT JOIN companies c ON c.id=o.company_id
      LEFT JOIN users s ON s.id=d.sender_user_id AND i.id IS NULL AND o.id IS NULL
      WHERE """ + " AND ".join(where) + " ORDER BY d.created_at DESC,d.id DESC"
    if opts["paginated"]:
        sql += " LIMIT ?"
        params.append(opts["page_size"] + 1)
    items = []
    for row in conn.execute(sql, params):
        try:
            items.append(api.internal_dispatch_detail(conn, row["id"], session))
        except PermissionError:
            # Retain the detail ACL as a second boundary, never broaden it.
            continue
    if opts["paginated"]:
        page = inbound_page(items, len(items), opts)
        page.pop("count", None)
        return page
    return items


def hosted_list(api, query, session):
    user = api.supabase_official_session_user(session)
    opts, scope = options(api, query, user, session)
    items, after = [], opts["after"]
    while True:
        result = rpc(api, "edoc_list_internal_dispatches_v1", {"p_actor_user_id": user["id"], "p_company_wide": scope["wide"],
            "p_needs_reply": scope["needs_reply"],
            "p_status": opts["status"], "p_limit": opts["page_size"] + 1 if opts["paginated"] else 101,
            "p_after_created": after[0] if after else None, "p_after_id": after[1] if after else None})
        batch = result.get("items")
        if not isinstance(batch, list):
            raise RuntimeError("internal_dispatch_list_response_invalid")
        # RPC is backend-only and derives tenant/company from the stored actor.
        items.extend(batch if opts["paginated"] else batch[:100])
        if opts["paginated"] or len(batch) <= 100:
            break
        after = (batch[99]["created_at"], batch[99]["id"])
    if opts["paginated"]:
        page = inbound_page(items, len(items), opts)
        page.pop("count", None)
        return page
    return items


def rpc(api, name, payload):
    try:
        result = api.supabase_request("POST", "rpc/" + name, payload)
    except RuntimeError as exc:
        for code in ("internal_dispatch_idempotency_conflict", "internal_dispatch_pending_replies", "internal_dispatch_closed",
                     "internal_dispatch_not_found", "internal_dispatch_recipient_not_found", "internal_dispatch_reply_not_required",
                     "internal_dispatch_create_forbidden", "internal_dispatch_company_forbidden", "internal_dispatch_view_forbidden",
                     "internal_dispatch_close_forbidden", "internal_dispatch_reply_forbidden", "internal_dispatch_recipient_company_forbidden"):
            if code in str(exc):
                raise (PermissionError if code.endswith("forbidden") or code.endswith("not_required") else ValueError)(code) from exc
        raise
    if isinstance(result, list) and len(result) == 1:
        result = result[0]
    if not isinstance(result, dict):
        raise RuntimeError("internal_dispatch_rpc_response_invalid")
    return result


def create_plan(api, payload, user, validated):
    key, request_hash = request_identity(payload)
    dispatch_id = "IDISP-" + secrets.token_hex(16).upper()
    stamp = api.now()
    recipients, notices = [], []
    seen = set()
    default = bool(payload.get("reply_required", False))
    for rec, target in validated:
        uid = str((target or {}).get("id") or "")
        department = str(rec.get("department_id") or rec.get("recipient_department_id") or "")
        identity = ("user", uid) if uid else ("department", department)
        if identity in seen:
            raise ValueError("internal_dispatch_duplicate_recipient")
        seen.add(identity)
        required = bool(rec.get("action_required", default))
        recipients.append({"id": "IDREC-" + secrets.token_hex(16).upper(), "dispatch_id": dispatch_id,
            "recipient_type": identity[0], "recipient_user_id": uid, "recipient_department_id": department,
            "recipient_name": (target or {}).get("name") or rec.get("name") or rec.get("recipient_name") or "",
            "action_required": required, "status": "pending" if required else "informed", "read_at": "", "replied_at": "",
            "created_at": stamp, "updated_at": stamp})
    required = any(r["action_required"] for r in recipients)
    days, due = api.internal_dispatch_deadline(payload, required)
    row = {"id": dispatch_id, "official_document_id": payload.get("official_document_id") or payload.get("document_id") or None,
           "inbound_document_id": payload.get("inbound_document_id") or None,
           "title": payload.get("title") or payload.get("subject") or "內部派文", "subject": payload.get("subject") or payload.get("title") or "內部派文",
           "body": payload.get("body") or "", "sender_user_id": user["id"], "sender_name": user.get("name") or user.get("email") or "",
           "sender_department": user.get("unit") or "", "reply_required": required, "reply_due_days": days or None, "due_at": due,
           "reply_status": "pending" if required else "not_required", "status": "sent", "metadata_json": payload.get("metadata") or {},
           "created_at": stamp, "updated_at": stamp, "closed_at": ""}
    for rec, (_, target) in zip(recipients, validated):
        if target:
            notice = (f"請於 {due} 前處理並回覆。" if due else "請處理並回覆。") if rec["action_required"] else "此件僅供知悉，不需回覆。"
            notices.append({"id": "NTF-DISPATCH-" + hashlib.sha256((dispatch_id + ":" + target["id"]).encode()).hexdigest()[:32],
                "type": "內部派文", "title": row["subject"], **api.exact_notification_target_payload(target, user.get("company_id") or ""),
                "channel": "Email + 系統通知", "source": dispatch_id, "action_url": "/#inbound",
                "body": f"{row['sender_name']} 發送內部公文。{notice}", "created_at": stamp})
    return {"key": key, "hash": request_hash, "dispatch": row, "recipients": recipients, "notices": notices}


def validate_create(api, conn, payload, session, hosted=False):
    user = api.require_internal_dispatch_creator(session)
    recipients = payload.get("recipients") or []
    if not isinstance(recipients, list) or not recipients:
        raise ValueError("internal_dispatch_recipients_required")
    if not all(isinstance(r, dict) for r in recipients):
        raise ValueError("invalid_internal_dispatch_recipient")
    validated = api._validated_supabase_internal_dispatch_recipients(user, recipients) if hosted else api._validated_local_internal_dispatch_recipients(conn, user, recipients)
    inbound = payload.get("inbound_document_id")
    if inbound:
        api.supabase_inbound_document_detail(inbound, session) if hosted else api.inbound_document_detail(conn, inbound, session)
    official = payload.get("official_document_id") or payload.get("document_id")
    if official:
        api._assert_supabase_internal_dispatch_scope({"official_document_id": official}, session) if hosted else api._assert_local_internal_dispatch_scope(conn, {"official_document_id": official}, session)
    return user, create_plan(api, payload, user, validated)


def local_create(api, conn, payload, session):
    with atomic(conn):
        user, plan = validate_create(api, conn, payload, session)
        existing = conn.execute("SELECT * FROM internal_dispatch_mutations WHERE actor_user_id=? AND idempotency_key=?", (user["id"], plan["key"])).fetchone()
        if existing:
            if existing["request_sha256"] != plan["hash"]:
                raise ValueError("internal_dispatch_idempotency_conflict")
            return api.internal_dispatch_detail(conn, existing["dispatch_id"], session)
        api.insert_row(conn, "internal_dispatches", plan["dispatch"])
        for recipient in plan["recipients"]:
            api.insert_row(conn, "internal_dispatch_recipients", recipient)
        for notice in plan["notices"]:
            api.create_notification(conn, notice)
        api.internal_dispatch_log(conn, plan["dispatch"]["id"], user, "create_internal_dispatch", plan["dispatch"]["subject"], payload)
        conn.execute("INSERT INTO internal_dispatch_mutations VALUES(?,?,?,?,?)", (user["id"], plan["key"], plan["hash"], plan["dispatch"]["id"], api.now()))
        return api.internal_dispatch_detail(conn, plan["dispatch"]["id"], session)


def hosted_create(api, payload, session):
    user, plan = validate_create(api, None, payload, session, hosted=True)
    result = rpc(api, "edoc_create_internal_dispatch_v1", {"p_actor_user_id": user["id"], "p_plan": plan})
    return api.supabase_internal_dispatch_detail(result["id"], session)


def local_close(api, conn, dispatch_id, payload, session):
    with atomic(conn):
        user = api.official_session_user(session)
        detail = api.internal_dispatch_detail(conn, dispatch_id, session)
        if detail.get("sender_user_id") != user["id"] and not api.session_has_any_permission(session, ["official_documents.all_todo", "official_documents.all_records"]):
            raise PermissionError("internal_dispatch_close_forbidden")
        if detail["status"] == "closed":
            return detail
        if detail["status"] == "cancelled":
            raise ValueError("internal_dispatch_closed")
        if pending_count(detail["recipients"]):
            raise ValueError("internal_dispatch_pending_replies")
        conn.execute("UPDATE internal_dispatches SET status='closed',closed_at=?,updated_at=? WHERE id=?", (api.now(), api.now(), dispatch_id))
        api.internal_dispatch_log(conn, dispatch_id, user, "close_internal_dispatch", payload.get("comment") or "內部派文結案", payload)
        return api.internal_dispatch_detail(conn, dispatch_id, session)


def transfer_local(api, conn, inbound_id, old_id, assignee, actor, payload):
    if not old_id or old_id == assignee["id"]:
        return
    rows = conn.execute("""SELECT r.* FROM internal_dispatch_recipients r JOIN internal_dispatches d ON d.id=r.dispatch_id
      WHERE d.inbound_document_id=? AND d.status NOT IN ('closed','cancelled') AND COALESCE(d.closed_at,'')=''
      AND r.recipient_user_id=? AND r.action_required=1 AND r.status NOT IN ('replied','reassigned') ORDER BY d.id,r.id""", (inbound_id, old_id)).fetchall()
    for old in rows:
        stamp = api.now()
        successor = conn.execute("SELECT * FROM internal_dispatch_recipients WHERE dispatch_id=? AND recipient_user_id=? AND status NOT IN ('replied','reassigned') ORDER BY id LIMIT 1", (old["dispatch_id"], assignee["id"])).fetchone()
        if successor:
            conn.execute("UPDATE internal_dispatch_recipients SET action_required=1,status='pending',updated_at=? WHERE id=?", (stamp, successor["id"]))
            new_id = successor["id"]
        else:
            new_id = "IDREC-" + secrets.token_hex(16).upper()
            api.insert_row(conn, "internal_dispatch_recipients", {"id": new_id, "dispatch_id": old["dispatch_id"], "recipient_type": "user",
                "recipient_user_id": assignee["id"], "recipient_department_id": assignee.get("unit") or "", "recipient_name": assignee.get("name") or "",
                "action_required": 1, "status": "pending", "created_at": stamp, "updated_at": stamp})
        conn.execute("UPDATE internal_dispatch_recipients SET action_required=0,status='reassigned',updated_at=? WHERE id=?", (stamp, old["id"]))
        conn.execute("UPDATE internal_dispatches SET reply_required=1,reply_status='pending',status='sent',updated_at=? WHERE id=?", (stamp, old["dispatch_id"]))
        detail = json.dumps({"inbound_document_id": inbound_id, "previous_recipient_id": old["id"], "previous_user_id": old_id,
                             "recipient_id": new_id, "recipient_user_id": assignee["id"]}, ensure_ascii=False, sort_keys=True)
        api.internal_dispatch_log(conn, old["dispatch_id"], actor, "reassign_internal_dispatch", detail, payload)
        api.create_notification(conn, {"id": "NTF-HANDOFF-" + hashlib.sha256((old["id"] + ":" + new_id).encode()).hexdigest()[:32],
            "type": "內部派文交接", "title": "未結派文已移交給你", **api.exact_notification_target_payload(assignee, actor.get("company_id") or ""),
            "channel": "Email + 系統通知", "source": old["dispatch_id"], "action_url": "/#inbound",
            "body": "請查看原案與期限並完成待回覆事項。"})
