"""Scoped, keyset-paginated official work lists. No per-document HTTP reads."""
import base64
import hashlib
import json
from datetime import datetime


PAGE_MAX = 100
STATUS_LABELS = {
    "draft": "草稿", "pending_applicant_manager": "申請人主管", "pending_department_head": "部門主任",
    "pending_admin_director": "行政部門主任", "pending_general_affairs_review": "總務專員", "pending_ceo": "執行長",
    "pending_approval": "待簽核", "approved": "已核准", "stamping": "用印中", "stamped": "已完成用印",
    "pending_general_affairs_dispatch": "等待總務寄發", "returned_to_applicant_for_send": "回申請人自行寄發",
    "dispatched": "已由總務正式發文", "sent_by_applicant": "已由申請人自行寄出", "closed": "已結案歸檔",
    "rejected": "已駁回", "cancelled": "已取消", "stamping_failed": "用印失敗",
}
STEP_LABELS = {
    "applicant_manager": "申請人主管", "department_head": "部門主任", "ceo": "執行長",
    "admin_director": "行政部門主任", "general_affairs_review": "總務專員", "applicant_confirm": "申請人收件",
}


def matches_search(item, term):
    """Match the visible work-list fields before the result page is filled."""
    values = [str(item.get(k) or "") for k in ("id", "dispatch_no", "title", "subject", "recipient",
              "applicant_name", "company_name", "current_status", "current_step_name")]
    values.append(STATUS_LABELS.get(item.get("current_status"), ""))
    steps = sorted(item["approval_steps"], key=lambda step: int(step.get("step_order") or 0))
    current = next((s for s in steps if s.get("status") == "rejected"
                    or (s.get("status") != "approved" and s.get("step_key") == item.get("current_step"))), steps[-1] if steps else {})
    if item.get("current_status") == "draft":
        values.extend(["草稿", item.get("applicant_name") or "申請人"])
    else:
        values.append(current.get("step_name") or STEP_LABELS.get(current.get("step_key")) or current.get("step_key") or "草稿")
        values.append((current.get("decision_actor_name") or "簽核人待確認") if current.get("status") in {"approved", "rejected"}
                      else (current.get("approver_name") or current.get("approver_role") or "尚未指派"))
    return any(term.casefold() in value.casefold() for value in values)


def options(query, user, session, api):
    query = query or {}
    first = lambda key: str((query.get(key) or [""])[0]).strip()
    size = first("page_size")
    if size and (not size.isdigit() or not 1 <= int(size) <= PAGE_MAX):
        raise ValueError("official_list_page_size_invalid")
    result = {key: first(key) for key in ("scope", "status", "company_id", "applicant_id", "search", "view")}
    if len(result["search"]) > 200 or result["view"] not in {"", "attention", "my_pending", "delegated", "overdue", "processed"}:
        raise ValueError("official_list_filter_invalid")
    result.update(actor_id=str(user["id"]), actor_company_id=str(user.get("company_id") or ""),
                  company_wide=api.session_has_any_permission(session, ["official_documents.all_records", "official_documents.all_todo"]))
    fingerprint = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()[:24]
    result.update(page_size=int(size) if size else None, fingerprint=fingerprint, after=None)
    cursor = first("cursor")
    if cursor:
        try:
            if len(cursor) > 2048:
                raise ValueError()
            decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if (not isinstance(decoded, list) or len(decoded) != 3 or decoded[0] != fingerprint or not isinstance(decoded[1], str)
                    or not isinstance(decoded[2], str) or not decoded[2] or len(decoded[2]) > 200):
                raise ValueError()
            datetime.fromisoformat(decoded[1])
            result["after"] = (decoded[1], decoded[2])
        except (ValueError, TypeError, IndexError, UnicodeError):
            raise ValueError("official_list_cursor_invalid") from None
    return result


def cursor_for(config, item):
    raw = json.dumps([config["fingerprint"], str(item["created_at"]), str(item["id"])], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def active_delegation(api, document, steps, user, bundle):
    current = next((s for s in steps if s.get("step_key") == document.get("current_step")
                    and s.get("status") == "pending" and s.get("step_key") != "applicant_confirm"
                    and api.official_step_status(str(s.get("step_key") or "")) == document.get("current_status")), None)
    if not current or current.get("approver_user_id") == user.get("id"):
        return None
    rows = [d for d in bundle.get("delegations", [])
            if d.get("company_id") == document.get("company_id")
            and d.get("principal_user_id") == current.get("approver_user_id")
            and d.get("delegate_user_id") == user.get("id") and api._active_delegation_at(d)]
    if len(rows) != 1:
        return None
    actors = {a["id"]: a for a in bundle.get("delegation_users", [])}
    principal, delegate = actors.get(current.get("approver_user_id")), actors.get(user.get("id"))
    if not principal or not delegate:
        return None
    return rows[0] if api.official_delegation_actor_qualification_current(document, principal, delegate) else None


def category(api, item, user):
    status = item.get("current_status")
    dispatch = item.get("dispatch_record") or {}
    delegated = bool(item.get("can_act") and item.get("delegation_id") and item.get("acting_for_user_id"))
    mine = bool(item.get("can_act") and not item.get("delegation_id"))
    retry_mine = bool(item.get("can_retry_stamp"))
    dispatch_mine = dispatch.get("dispatch_status") == "pending" and item.get("can_manage_dispatch")
    returned = status == "rejected" and item.get("applicant_id") == user.get("id")
    pending = next((s for s in item["approval_steps"] if s.get("step_key") == item.get("current_step") and s.get("status") == "pending"), {})
    due = api.parse_date_value(str(pending.get("due_at") or item.get("correction_due_at") or item.get("correction_due_date") or item.get("due_at") or ""))
    if (mine or delegated or dispatch_mine or returned or retry_mine) and due and due < datetime.now() and status not in {"closed", "cancelled"}:
        return "overdue"
    if delegated:
        return "delegated"
    if mine or dispatch_mine or returned or retry_mine or (status == "draft" and item.get("applicant_id") == user.get("id")):
        return "my_pending"
    return "processed"


def project(api, bundle, config, user, session):
    item = dict(bundle["document"])
    all_steps = bundle.get("steps") or []
    generation = max((int(s.get("workflow_generation") or 1) for s in all_steps), default=0)
    steps = [s for s in all_steps if int(s.get("workflow_generation") or 1) == generation]
    current_ids = {s["id"] for s in steps}
    display_steps = [s for s in api.official_step_decision_display(all_steps, bundle.get("decision_logs") or []) if s["id"] in current_ids]
    participant = user["id"] in api.official_document_participant_ids(item, all_steps, bundle.get("snapshots") or [])
    # Independent defense even if a storage adapter returns an overbroad page.
    company = str(user.get("company_id") or "")
    if company and item.get("company_id") != company and not participant:
        return None
    for query_key, field in (("status", "current_status"), ("company_id", "company_id"), ("applicant_id", "applicant_id")):
        if config[query_key] and item.get(field) != config[query_key]:
            return None
    scope = config["scope"]
    if scope == "mine" and item.get("applicant_id") != user["id"]:
        return None
    delegation = active_delegation(api, item, steps, user, bundle)
    if scope not in {"mine", "todo"} and not participant and not delegation and not (company and config["company_wide"]):
        return None
    pending = next((s for s in steps if s.get("status") == "pending" and s.get("step_key") == item.get("current_step")), None)
    dispatch = bundle.get("dispatch_record")
    stamp = bundle.get("stamp_request")
    if dispatch:
        dispatch = dict(dispatch)
        method = api.official_dispatch_method(dispatch.get("dispatch_method"))
        dispatch["dispatch_method_label"] = api.OFFICIAL_DISPATCH_METHODS[method]["label"]
        dispatch["dispatch_owner_name"] = bundle.get("dispatch_owner_name") or dispatch.get("dispatch_owner_user_id") or dispatch.get("dispatch_owner_type") or ""
        dispatch["proof_file"] = api.official_file_metadata(bundle["dispatch_proof"]) if bundle.get("dispatch_proof") else None
    seal = api.official_seal_context_from_document(item)
    item.update(official_seal=seal, document_category=(seal or {}).get("document_category") or "",
                approval_route_code=(seal or {}).get("approval_route_code") or "",
                approval_route_name=(seal or {}).get("approval_route_name") or "",
                approval_steps=display_steps,
                stamp_request=api.official_application_package(item, [], [], [], stamp).get("stamp_request"),
                dispatch_record=dispatch, current_step_name=next((s.get("step_name", "") for s in steps if s.get("step_key") == item.get("current_step")), ""),
                can_download=bool(participant or delegation),
                can_manage_dispatch=bool(api.official_dispatch_record_editable(dispatch) and api.can_manage_official_dispatch(user, item, dispatch, session, steps)),
                can_retry_stamp=bool(api.official_stamp_recoverable(item, stamp) and api.can_retry_official_stamp(user, steps)),
                can_confirm=bool(item.get("applicant_id") == user["id"] and item.get("current_step") == "applicant_confirm" and item.get("current_status") in {"stamped", "dispatched", "sent_by_applicant"}),
                can_act=bool(pending and (pending.get("approver_user_id") == user["id"] or delegation)),
                acting_for_user_id=pending.get("approver_user_id") if pending and delegation else "",
                delegation_id=delegation.get("id") if delegation else "")
    if scope == "todo" and not (item["can_act"] or item["can_retry_stamp"] or (dispatch and dispatch.get("dispatch_status") == "pending" and dispatch.get("dispatch_owner_user_id") == user["id"])):
        return None
    if config["view"]:
        current_category = category(api, item, user)
        if current_category not in ({"my_pending", "delegated", "overdue"} if config["view"] == "attention" else {config["view"]}):
            return None
    if config["search"] and not matches_search(item, config["search"]):
        return None
    return item


def collect(api, config, user, session, fetch):
    if config["scope"] == "mine" and config["applicant_id"] and config["applicant_id"] != user["id"]:
        return {"items": [], "next_cursor": None, "has_more": False} if config["page_size"] else []
    items, after = [], config["after"]
    while True:
        bundles = fetch(after)
        if not isinstance(bundles, list) or len(bundles) > PAGE_MAX:
            raise RuntimeError("official_list_invalid_response")
        for bundle in bundles:
            document = bundle.get("document") if isinstance(bundle, dict) else None
            if not isinstance(document, dict) or not document.get("id") or not document.get("created_at"):
                raise RuntimeError("official_list_invalid_response")
            key = (str(document["created_at"]), str(document["id"]))
            if after and key >= after:
                raise RuntimeError("official_list_cursor_not_advancing")
            after = key
            row = project(api, bundle, config, user, session)
            if row is not None:
                items.append(row)
                if config["page_size"] and len(items) > config["page_size"]:
                    return {"items": items[:-1], "next_cursor": cursor_for(config, items[-2]), "has_more": True}
        if len(bundles) < PAGE_MAX:
            return {"items": items, "next_cursor": None, "has_more": False} if config["page_size"] else items


def list_supabase(api, query, session):
    user = api.supabase_official_session_user(session)
    config = options(query, user, session, api)
    def fetch(after):
        request = {k: v for k, v in config.items() if k not in {"after", "fingerprint", "page_size"}}
        request.update(limit=PAGE_MAX, after_created_at=after[0] if after else "", after_id=after[1] if after else "")
        result = api.supabase_request("POST", "rpc/edoc_list_official_document_candidates", {"p_request": request})
        if isinstance(result, dict):
            result = result.get("items")
        return result
    return collect(api, config, user, session, fetch)


def list_sqlite(api, conn, query, session):
    user = api.official_session_user(session)
    config = options(query, user, session, api)
    def fetch(after):
        where, params = [], []
        for key, field in (("status", "current_status"), ("company_id", "company_id"), ("applicant_id", "applicant_id")):
            if config[key]:
                where.append(f"d.{field} = ?")
                params.append(config[key])
        if config["scope"] == "mine":
            where.append("d.applicant_id = ?")
            params.append(user["id"])
        # Only possible participants/company readers enter the candidate page.
        where.append("""(d.applicant_id = ? OR (d.company_id = ? AND ?)
          OR EXISTS(SELECT 1 FROM official_document_approval_steps s WHERE s.document_id=d.id AND (s.approver_user_id=? OR s.decision_actor_user_id=?))
          OR EXISTS(SELECT 1 FROM approval_step_actor_snapshots a WHERE a.source_id=d.id AND a.source_type IN ('official_document','official_documents','official_document_application') AND a.approver_user_id=?)
          OR EXISTS(SELECT 1 FROM official_workflow_delegations x JOIN official_document_approval_steps s ON s.document_id=d.id AND s.approver_user_id=x.principal_user_id AND s.step_key=d.current_step AND s.status='pending' WHERE x.company_id=d.company_id AND x.delegate_user_id=? AND x.status='active'))""")
        params.extend([user["id"], user.get("company_id") or "", bool(config["company_wide"] and user.get("company_id")), user["id"], user["id"], user["id"], user["id"]])
        if after:
            where.append("(d.created_at, d.id) < (?, ?)")
            params.extend(after)
        docs = [dict(r) for r in conn.execute("SELECT d.* FROM official_documents d WHERE " + " AND ".join(where) + " ORDER BY d.created_at DESC,d.id DESC LIMIT ?", [*params, PAGE_MAX])]
        if not docs:
            return []
        ids = [d["id"] for d in docs]
        marks = ",".join("?" for _ in ids)
        def grouped(table, column, order=""):
            out = {key: [] for key in ids}
            for row in conn.execute(f"SELECT * FROM {table} WHERE {column} IN ({marks})" + (f" ORDER BY {order}" if order else ""), ids):
                out[row[column]].append(dict(row))
            return out
        steps = grouped("official_document_approval_steps", "document_id", "workflow_generation,step_order,id")
        snapshots = grouped("approval_step_actor_snapshots", "source_id")
        dispatches = grouped("official_document_dispatch_records", "document_id", "created_at DESC,id DESC")
        stamps = grouped("official_document_stamp_requests", "document_id", "created_at DESC,id DESC")
        logs = grouped("official_document_approval_logs", "document_id", "created_at,id")
        delegations = [dict(r) for r in conn.execute("SELECT * FROM official_workflow_delegations WHERE delegate_user_id=? AND status='active'", (user["id"],))]
        actor_ids = {user["id"], *(r["principal_user_id"] for r in delegations), *(r["dispatch_owner_user_id"] for rows in dispatches.values() for r in rows if r.get("dispatch_owner_user_id"))}
        actors = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM users WHERE id IN (" + ",".join("?" for _ in actor_ids) + ")", list(actor_ids))}
        proofs = grouped("official_document_files", "document_id")
        result = []
        for d in docs:
            identity = d["id"]
            dispatch = next(iter(dispatches[identity]), None)
            result.append({"document": d, "steps": steps[identity],
                           "snapshots": [s for s in snapshots[identity] if s.get("source_type") in api.OFFICIAL_DOCUMENT_ACTOR_SNAPSHOT_SOURCE_TYPES],
                           "dispatch_record": dispatch, "stamp_request": next(iter(stamps[identity]), None), "decision_logs": logs[identity],
                           "delegations": delegations, "delegation_users": list(actors.values()),
                           "dispatch_owner_name": actors.get((dispatch or {}).get("dispatch_owner_user_id"), {}).get("name"),
                           "dispatch_proof": next((f for f in proofs[identity] if f["id"] == (dispatch or {}).get("proof_file_id")), None)})
        return result
    return collect(api, config, user, session, fetch)
