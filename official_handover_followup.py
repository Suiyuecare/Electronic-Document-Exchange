"""Narrow server-owned authorization for a confirmed original-applicant handover.

This is responsibility, not impersonation: original identities and approvals
are immutable. No browser-supplied binding or session role is authoritative.
"""
import official_handover as policy
import official_handover_store as store
import hashlib
from datetime import date


def validate(document, binding, request, company, original, owner, *, ancestry=(), allow_inactive_owner=False):
    policy._scope(document, company, original, active=False)
    policy._scope(document, company, owner, active=not allow_inactive_owner)
    chain = [request, *ancestry]
    seen = set()
    for index, current in enumerate(chain):
        if (current.get("id") in seen or current.get("status") != "approved"
                or current.get("kind") != "followup_owner" or current.get("document_id") != document["id"]
                or current.get("company_id") != company["id"] or current.get("finance_tenant_id") != company["finance_tenant_id"]
                or not current.get("confirmed_at") or not current.get("confirmer_user_id")
                or current["confirmer_user_id"] in {current.get("proposer_user_id"), current.get("former_user_id"), current.get("successor_user_id"), original["id"]}):
            raise PermissionError("handover_followup_lineage_invalid")
        seen.add(current["id"])
        parent = chain[index + 1] if index + 1 < len(chain) else None
        if parent:
            if current.get("previous_handover_id") != parent["id"] or current.get("former_user_id") != parent.get("successor_user_id"):
                raise PermissionError("handover_followup_lineage_invalid")
        elif current.get("previous_handover_id") or current.get("former_user_id") != original["id"]:
            raise PermissionError("handover_followup_lineage_invalid")
    if (original.get("status") == "啟用" or original["id"] != document.get("applicant_id")
            or binding.get("document_id") != document["id"]
            or binding.get("original_applicant_id") != original["id"]
            or binding.get("process_owner_user_id") != owner["id"]
            or binding.get("company_id") != company["id"]
            or binding.get("finance_tenant_id") != company["finance_tenant_id"]
            or binding.get("correction_policy") != "linked_new_application"
            or request.get("status") != "approved" or request.get("kind") != "followup_owner"
            or request.get("id") != binding.get("handover_id")
            or request.get("document_id") != document["id"]
            or request.get("company_id") != company["id"]
            or request.get("finance_tenant_id") != company["finance_tenant_id"]
            or request.get("successor_user_id") != owner["id"]
            or not request.get("confirmed_at") or not request.get("confirmer_user_id")
            or request["confirmer_user_id"] in {request.get("proposer_user_id"), original["id"], owner["id"]}):
        raise PermissionError("handover_followup_binding_invalid")
    return dict(binding)


def load(backend, document, *, conn=None, actor_id=None, allow_inactive_owner=False):
    def get(table, identity):
        if conn is not None:
            row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (identity,)).fetchone()
            return dict(row) if row else None
        return backend.supabase_get(table, identity)
    if conn is not None:
        row = conn.execute("SELECT * FROM official_document_followup_owners WHERE document_id=?", (document["id"],)).fetchone()
        binding = dict(row) if row else None
    else:
        rows = backend.supabase_filter_rows("official_document_followup_owners", {"document_id": document["id"]}, limit=1)
        binding = rows[0] if rows else None
    if not binding or (actor_id is not None and binding.get("process_owner_user_id") != actor_id):
        return None
    record = get("official_document_handovers", binding.get("handover_id"))
    if not record:
        return None
    original = get("users", document.get("applicant_id")) or {}
    owner = get("users", binding.get("process_owner_user_id")) or {}
    company = get("companies", document.get("company_id")) or {}
    try:
        confirmed = store._request(record)
        ancestry, current, seen = [], confirmed, {confirmed["id"]}
        while current.get("previous_handover_id"):
            if len(ancestry) >= 99 or current["previous_handover_id"] in seen:
                raise ValueError("handover_followup_lineage_invalid")
            parent = get("official_document_handovers", current["previous_handover_id"])
            if not parent:
                raise ValueError("handover_followup_lineage_invalid")
            current = store._request(parent)
            seen.add(current["id"]); ancestry.append(current)
        validate(document, binding, confirmed, company, original, owner,
                 ancestry=ancestry, allow_inactive_owner=allow_inactive_owner)
    except (PermissionError, ValueError, KeyError):
        return None
    return {**binding, "owner": owner}


class LinkedApplication:
    """Create a fileless, unapproved draft from immutable original content.

    The new ID/number and relation witness are server-owned. Retried operation
    IDs return the same case; the original is never corrected or resubmitted.
    """
    def __init__(self, backend, session, conn=None):
        self.api, self.session, self.conn = backend, session, conn
        identity = (session or {}).get("user", {}).get("id")
        if not identity:
            raise PermissionError("authentication_required")
        if conn is not None:
            self.actor = store._actor(conn, session)
        else:
            self.actor = backend.supabase_get("users", identity) or {}
            if self.actor.get("status") != "啟用" or self.actor.get("account_source") != "finance":
                raise PermissionError("handover_finance_actor_inactive")
        if not backend.session_has_any_permission(session, ["official_documents.compose", "official_documents.all_todo"]):
            raise PermissionError("official_document_create_forbidden")

    def context(self, identity):
        api, conn = self.api, self.conn
        doc = api.official_document_row(conn, identity) if conn is not None else api.supabase_official_document_row(identity)
        binding = load(api, doc, conn=conn, actor_id=self.actor["id"])
        if not binding:
            raise PermissionError("handover_linked_application_forbidden")
        company = api.official_company_row(conn, doc["company_id"]) if conn is not None else api.supabase_official_company_row(doc["company_id"])
        seed = policy.linked_application_seed(doc, binding, company, self.actor, today=date.today().isoformat())
        steps = api.official_document_steps(conn, identity) if conn is not None else api.supabase_official_document_steps(identity)
        stamp = api.official_document_stamp_request(conn, identity) if conn is not None else api.supabase_official_document_stamp_request(identity)
        return {**seed, "expected_fingerprint": policy.handover_fingerprint(doc, steps, stamp, binding),
                "snapshot": policy.handover_snapshot(doc, steps, stamp, binding)}, doc, binding

    def create(self, identity, payload):
        operation = policy._identity(payload.get("operation_id"), "operation_id")
        # A savepoint holds the original write reservation across validation,
        # draft/relation creation, so failure cannot leave an unlinked case.
        if self.conn is not None:
            with store._transaction(self.conn):
                self.conn.execute("UPDATE official_documents SET updated_at=updated_at WHERE id=?", (identity,))
                return self._create(identity, operation, payload)
        return self._create(identity, operation, payload)

    def _create(self, identity, operation, payload):
        api, conn = self.api, self.conn
        seed, original, binding = self.context(identity)
        digest = hashlib.sha256(operation.encode()).hexdigest()
        new_id, log_id = "ODLINK-" + digest[:32], "ODLINKLOG-" + digest[:32]
        witness = (dict(row) if (row := conn.execute("SELECT * FROM official_document_approval_logs WHERE id=?", (log_id,)).fetchone()) else None) if conn is not None else api.supabase_get("official_document_approval_logs", log_id)
        if witness:
            evidence = api.parse_json_any(witness.get("decision_evidence_json"), {})
            if (witness.get("document_id") != new_id or witness.get("actor_id") != self.actor["id"]
                    or evidence.get("original_document_id") != identity
                    or evidence.get("handover_id") != binding["handover_id"]
                    or evidence.get("expected_fingerprint") != payload.get("expected_fingerprint")):
                raise policy.HandoverConflict("handover_operation_conflict")
            return {"document_id": new_id, "original_document_id": identity, "idempotent": True}
        if seed["expected_fingerprint"] != payload.get("expected_fingerprint"):
            raise policy.HandoverConflict("handover_version_conflict")
        department = api.authoritative_applicant_department(self.actor)
        evidence = {**seed["relation"], "operation_id": operation,
                    "expected_fingerprint": seed["expected_fingerprint"], "requires_fresh_files": True,
                    "requires_full_approval": True}
        state = api.validate_editor_state({"schemaVersion": api.EDOC_EDITOR_SCHEMA_VERSION,
            "revisionNo": 1, "sourceFiles": [], "pages": [], "elements": [], "manifestSha256": ""})
        state["manifestSha256"] = api.canonical_editor_manifest(state)
        if conn is None:
            result = api.supabase_request("POST", "rpc/edoc_manage_official_handover", {"p_request": {
                "action": "linked_create", "document_id": identity, "actor_id": self.actor["id"],
                "handover_id": binding["handover_id"], "operation_id": operation,
                "expected_snapshot": seed["snapshot"], "expected_fingerprint": seed["expected_fingerprint"],
                "department": department, "editor_state": state, "renderer_version": api.EDOC_EDITOR_RENDERER_VERSION}})
            if not isinstance(result, dict) or result.get("document_id") != new_id or result.get("original_document_id") != identity:
                raise RuntimeError("handover_linked_response_invalid")
            return result
        timestamp = api.now()
        metadata = {"linked_application": evidence, "requires_fresh_files": True}
        if original["source_type"] == "uploaded_pdf":
            metadata.update(pdf_editor_v2=True, editor_schema_version=api.EDOC_EDITOR_SCHEMA_VERSION)
        else:
            metadata["source"] = "compose_form"
        doc = {**seed["payload"], "id": new_id, "applicant_id": self.actor["id"],
            "applicant_name": self.actor.get("name") or "", "handler_name": self.actor.get("name") or "",
            "applicant_department_id": department["id"], "applicant_department_name": department["name"],
            "dispatch_unit": department["name"], "requires_stamp": original["requires_stamp"],
            "current_status": "draft", "current_step": "", "metadata_json": metadata,
            "created_at": timestamp, "updated_at": timestamp}
        api.insert_row(conn, "official_documents", doc)
        if original["source_type"] == "uploaded_pdf":
            api._insert_editor_revision(conn, new_id, state, self.actor)
        api.insert_row(conn, "official_document_approval_logs", {"id": log_id, "document_id": new_id,
            "actor_id": self.actor["id"], "actor_name": self.actor.get("name") or "", "action": "linked_from",
            "comment": "離職案件補正另立新案；原案保留", "decision_evidence_json": policy._json(evidence), "created_at": timestamp})
        api.insert_official_log(conn, identity, "linked_to", self.actor, "new_document_id=" + new_id,
                                decision_evidence=evidence)
        return {"document_id": new_id, "original_document_id": identity, "idempotent": False}
