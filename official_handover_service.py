"""Authenticated, company-scoped handover API shared by hosted and local storage.

Browser claims never establish role, tenant, assignee or CAS evidence. Read
responses contain only operational metadata, not files or identity secrets.
"""
from __future__ import annotations

import json
import re
import urllib.parse

import official_handover as policy
import official_handover_store as store

MANAGERS = policy.PROPOSER_ROLES | policy.CONFIRMER_ROLES


def _page(query):
    try:
        page = int((query.get("page") or ["1"])[0])
        size = int((query.get("page_size") or ["20"])[0])
    except (TypeError, ValueError, IndexError):
        raise ValueError("handover_pagination_invalid") from None
    if not 1 <= page <= 10000 or not 1 <= size <= 50:
        raise ValueError("handover_pagination_invalid")
    return page, size


class Service:
    def __init__(self, backend, session, conn=None):
        self.backend, self.session, self.conn = backend, session, conn
        identity = (session or {}).get("user", {}).get("id")
        if not identity:
            raise PermissionError("authentication_required")
        self.actor = self.get("users", identity)
        if (not self.actor or self.actor.get("status") != "啟用"
                or self.actor.get("account_source") != "finance"
                or self.actor.get("role") not in MANAGERS):
            raise PermissionError("handover_manage_forbidden")
        self.company = self.get("companies", self.actor.get("company_id"))
        policy._scope({"id": "scope", "company_id": self.actor.get("company_id")}, self.company or {}, self.actor)

    def get(self, table, identity):
        if self.conn is not None:
            row = self.conn.execute(f"SELECT * FROM {table} WHERE id=?", (identity,)).fetchone()
            return dict(row) if row else None
        return self.backend.supabase_get(table, identity)

    def rows(self, table, filters, *, order="id", limit=2001, offset=0):
        if self.conn is not None:
            where = " AND ".join(key + "=?" for key in filters)
            rows = self.conn.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
                                     (*filters.values(), limit, offset))
            return [dict(row) for row in rows]
        params = {"select": "*", "limit": str(limit), "offset": str(offset),
                  "order": ",".join(part.strip().replace(" ", ".") for part in order.split(","))}
        params.update({key: "eq." + str(value) for key, value in filters.items()})
        return self.backend.supabase_request("GET", table + "?" + urllib.parse.urlencode(params))

    def load(self, document_id):
        document = self.get("official_documents", document_id)
        if not document:
            raise ValueError("official_document_not_found")
        policy._scope(document, self.company, self.actor)
        steps = self.rows("official_document_approval_steps", {"document_id": document_id},
                          order="workflow_generation,step_order,id")
        if len(steps) > 2000:
            raise ValueError("handover_workflow_history_limit")
        stamps = self.rows("official_document_stamp_requests", {"document_id": document_id},
                           order="created_at desc,id desc", limit=1)
        return document, steps, stamps[0] if stamps else None

    def binding(self, document):
        import official_handover_followup
        raw = self.rows("official_document_followup_owners", {"document_id": document["id"]}, order="document_id", limit=1)
        if not raw:
            return None
        result = official_handover_followup.load(self.backend, document, conn=self.conn, allow_inactive_owner=True)
        if not result:
            raise PermissionError("handover_followup_lineage_invalid")
        return result

    def rpc(self, request):
        try:
            result = self.backend.supabase_request("POST", "rpc/edoc_manage_official_handover", {"p_request": request})
        except RuntimeError as exc:
            marker = str(exc)
            if re.fullmatch(r"supabase_request_failed:(401|403):42501", marker):
                raise PermissionError("handover_authorization_changed") from None
            if re.fullmatch(r"supabase_request_failed:400:22023", marker):
                raise ValueError("handover_request_invalid") from None
            if re.fullmatch(r"supabase_request_failed:404:P0002", marker):
                raise ValueError("handover_request_not_found") from None
            raise
        if not isinstance(result, dict):
            raise RuntimeError("handover_rpc_response_invalid")
        return result

    def _requests(self, document_id):
        rows = self.rows("official_document_handovers", {"document_id": document_id},
                         order="created_at desc,id desc", limit=101)
        if len(rows) > 100:
            raise ValueError("handover_history_limit")
        return [self._present_request(row) for row in rows]

    def _present_request(self, row):
        record = store._request(row)
        result = {key: record.get(key) for key in ("id", "document_id", "kind", "former_user_id",
                  "successor_user_id", "proposer_user_id", "confirmer_user_id", "status", "reason", "created_at", "confirmed_at")}
        result["resolution_reason"] = record.get("rejection_reason") or ""
        for key in ("former", "successor", "proposer", "confirmer"):
            if not record.get(key + "_user_id"):
                result[key + "_name"] = ""
                continue
            user = self.get("users", record.get(key + "_user_id")) or {}
            result[key + "_name"] = user.get("name") or "人員資料已異動"
        result["can_confirm"] = record.get("status") == "pending" and self.actor.get("role") in policy.CONFIRMER_ROLES and self.actor["id"] not in {
            record.get("proposer_user_id"), record.get("former_user_id"), record.get("successor_user_id")}
        return result

    def queue(self, query):
        page, size = _page(query)
        view = (query.get("view") or ["needs"])[0]
        if view not in {"needs", "pending", "history"}:
            raise ValueError("handover_queue_view_invalid")
        request = {"action": "queue", "actor_id": self.actor["id"], "page": page, "page_size": size, "view": view}
        if self.conn is None:
            return self.rpc(request)
        former_scope = "u.account_source='finance' AND u.company_id=d.company_id AND u.finance_tenant_id=? AND u.status<>'啟用'"
        if view in {"pending", "history"}:
            condition = "EXISTS (SELECT 1 FROM official_document_handovers h WHERE h.document_id=d.id" + (" AND h.status='pending'" if view == "pending" else "") + ")"
            params = []
        else:
            condition = f"""d.current_status NOT IN ('closed','declined','cancelled') AND (
                (NOT EXISTS(SELECT 1 FROM official_document_followup_owners f WHERE f.document_id=d.id)
                 AND EXISTS(SELECT 1 FROM users u WHERE u.id=d.applicant_id AND {former_scope}))
                OR EXISTS(SELECT 1 FROM official_document_followup_owners f JOIN users u ON u.id=f.process_owner_user_id
                  WHERE f.document_id=d.id AND {former_scope})
                OR EXISTS(SELECT 1 FROM official_document_approval_steps s JOIN users u ON u.id=s.approver_user_id
                  WHERE s.document_id=d.id AND s.workflow_generation=(SELECT max(workflow_generation) FROM official_document_approval_steps WHERE document_id=d.id)
                  AND s.status='pending' AND s.step_key<>'applicant_confirm' AND {former_scope}))"""
            params = [self.company["finance_tenant_id"]] * 3
        rows = self.conn.execute(f"SELECT d.id,d.dispatch_no,d.subject,d.current_status,d.updated_at FROM official_documents d WHERE d.company_id=? AND ({condition}) ORDER BY d.updated_at DESC,d.id LIMIT ? OFFSET ?",
                                 (self.company["id"], *params, size+1, (page-1)*size)).fetchall()
        return {"items": [dict(row) for row in rows[:size]], "page": page, "page_size": size,
                "has_more": len(rows) > size, "view": view,
                "can_propose": self.actor["role"] in policy.PROPOSER_ROLES,
                "can_confirm": self.actor["role"] in policy.CONFIRMER_ROLES}

    def context(self, document_id, query):
        document, steps, stamp = self.load(document_id)
        targets = []
        current = policy._current_steps(document, steps)
        binding = self.binding(document)
        identities = [("followup_owner", binding["process_owner_user_id"] if binding else document.get("applicant_id"))]
        identities += [("pending_approver", row.get("approver_user_id")) for row in current
                       if row.get("status") == "pending" and row.get("step_key") != "applicant_confirm"]
        for kind, identity in sorted({pair for pair in identities if pair[1]}):
            user = self.get("users", identity)
            if not user or user.get("status") == "啟用":
                continue
            try:
                policy._scope(document, self.company, user, active=False)
            except PermissionError:
                continue
            targets.append({"kind": kind, "former_user_id": user["id"], "former_name": user["name"], "former_role": user.get("role")})
        kind = (query.get("kind") or [targets[0]["kind"] if targets else ""])[0]
        former_id = (query.get("former_user_id") or [targets[0]["former_user_id"] if targets else ""])[0]
        target = next((row for row in targets if row["kind"] == kind and row["former_user_id"] == former_id), None)
        page, size = _page(query)
        candidates, block = [], ""
        if target and self.actor["role"] in policy.PROPOSER_ROLES:
            former = self.get("users", former_id)
            filters = {"company_id": self.company["id"], "finance_tenant_id": self.company["finance_tenant_id"],
                       "account_source": "finance", "status": "啟用"}
            if kind == "pending_approver": filters["role"] = former.get("role")
            # Bound and explicit. Never silently drop valid candidates: the
            # browser can request the next candidate page independently.
            rows = self.rows("users", filters, order="name,id", limit=size+1, offset=(page-1)*size)
            for user in rows[:size]:
                try:
                    if self.actor["id"] in {user["id"], former_id, document.get("applicant_id")}:
                        continue
                    policy._eligible(document, current, former, user, kind, stamp, binding)
                except (PermissionError, ValueError) as exc:
                    if isinstance(exc, policy.HandoverConflict): block = str(exc)
                    continue
                candidates.append({"id": user["id"], "name": user["name"], "role": user.get("role")})
            more = len(rows) > size
        else:
            more = False
        return {"document": {key: document.get(key) for key in ("id", "dispatch_no", "subject", "current_status")},
                "expected_fingerprint": policy.handover_fingerprint(document, steps, stamp, binding), "targets": targets,
                "selected_kind": kind, "selected_former_user_id": former_id, "candidates": candidates,
                "candidate_page": page, "has_more_candidates": more, "blocked_reason": block,
                "requests": self._requests(document_id), "can_propose": self.actor["role"] in policy.PROPOSER_ROLES,
                "can_confirm": self.actor["role"] in policy.CONFIRMER_ROLES}

    def propose(self, document_id, payload):
        if self.conn is not None:
            return store.propose(self.conn, document_id, payload, self.session, backend=self.backend)
        if self.actor["role"] not in policy.PROPOSER_ROLES:
            raise PermissionError("handover_propose_forbidden")
        document, steps, stamp = self.load(document_id)
        operation = policy._identity(payload.get("operation_id"), "operation_id")
        existing = self.get("official_document_handovers", operation)
        if existing:
            record = store._request(existing)
            expected = {"document_id": document_id, "proposer_user_id": self.actor["id"],
                        "former_user_id": payload.get("former_user_id"), "successor_user_id": payload.get("successor_user_id"),
                        "kind": payload.get("kind"), "reason": str(payload.get("reason") or "").strip(),
                        "expected_fingerprint": payload.get("expected_fingerprint")}
            if any(record.get(key) != value for key, value in expected.items()):
                raise policy.HandoverConflict("handover_operation_conflict")
            snapshot = existing["expected_snapshot"]
            snapshot = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
        else:
            binding = self.binding(document)
            record = policy.propose_handover(document, steps, self.company, self.actor,
                self.get("users", payload.get("former_user_id")) or {},
                self.get("users", payload.get("successor_user_id")) or {}, payload, timestamp=self.backend.now(), stamp=stamp, binding=binding)
            snapshot = policy.handover_snapshot(document, steps, stamp, binding)
        return self.rpc({
            "action": "propose", "actor_id": self.actor["id"], "handover_id": operation,
            "document_id": document_id, "record": record, "expected_snapshot": snapshot})

    def resolve(self, request_id, action, payload):
        if action not in {"confirm", "reject"}: raise ValueError("handover_action_invalid")
        if self.conn is not None:
            return (store.confirm(self.conn, request_id, self.session, backend=self.backend) if action == "confirm"
                    else store.reject(self.conn, request_id, payload.get("reason"), self.session, backend=self.backend))
        if self.actor["role"] not in policy.CONFIRMER_ROLES:
            raise PermissionError("handover_confirm_forbidden")
        row = self.get("official_document_handovers", request_id)
        if not row: raise ValueError("handover_request_not_found")
        self.load(row["document_id"])
        return self.rpc({
            "action": action, "actor_id": self.actor["id"], "handover_id": request_id,
            "document_id": row["document_id"], "reason": payload.get("reason")})
