"""Private, incomplete compose snapshots; never allocate numbers or start approvals."""
import hashlib
import json
import re
import sqlite3

SQLITE_COMPOSE_DRAFT_SQL = """
CREATE TABLE IF NOT EXISTS official_document_compose_drafts (
 id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id),
 applicant_id TEXT NOT NULL REFERENCES users(id), revision INTEGER NOT NULL DEFAULT 1,
 snapshot_json TEXT NOT NULL, snapshot_hash TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_compose_draft_owner ON official_document_compose_drafts(applicant_id, company_id, archived, updated_at);
"""

SELECTORS = frozenset("composeCompanySelect docType priority composeApprovalCategorySelect dispatchNo dispatchDate composeOutputMode recipient copyRecipients documentPurpose contactAddress contactOwner contactPhone contactFax contactEmail largeSealType smallSealType subject bodyText attachmentDetails".split())

def draft_payload(draft_id, payload, user):
    if not re.fullmatch(r"OD-[0-9a-fA-F-]{36}", draft_id):
        raise ValueError("compose_draft_id_invalid")
    revision = payload.get("expected_revision")
    if type(revision) is not int or revision < 0:
        raise ValueError("compose_draft_revision_required")
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("values"), dict):
        raise ValueError("compose_draft_snapshot_invalid")
    if snapshot.get("userId") != user.get("id") or snapshot.get("companyId") != user.get("company_id"):
        raise PermissionError("compose_draft_scope_forbidden")
    values = snapshot["values"]
    if any(k.lstrip("#") not in SELECTORS or not isinstance(v, str) or len(v) > 50000 for k, v in values.items()):
        raise ValueError("compose_draft_snapshot_invalid")
    # Only a data snapshot: no file bytes, private URLs or executable markup.
    clean = {"schemaVersion": 2, "userId": user["id"], "companyId": user["company_id"], "values": values,
             "draftRequestId": str(snapshot.get("draftRequestId") or "")[:160], "currentComposeDraftId": str(snapshot.get("currentComposeDraftId") or "")[:160],
             "officialContentRevision": snapshot.get("officialContentRevision"),
             "officialDocumentId": str(snapshot.get("officialDocumentId") or "")[:160],
             "sealPlacements": snapshot.get("sealPlacements") or {}}
    encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > 240000:
        raise ValueError("compose_draft_too_large")
    return revision, encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()

def public_draft(row):
    row = dict(row)
    snapshot = row.get("snapshot_json") or {}
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot)
    return {"id": row["id"], "revision": int(row["revision"]), "snapshot": snapshot,
            "updatedAt": row["updated_at"], "archived": bool(row.get("archived"))}

def save_sqlite_draft(conn, draft_id, payload, user, timestamp):
    revision, encoded, digest = draft_payload(draft_id, payload, user)
    row = conn.execute("SELECT * FROM official_document_compose_drafts WHERE id = ?", (draft_id,)).fetchone()
    if row:
        if row["applicant_id"] != user["id"] or row["company_id"] != user["company_id"]:
            raise PermissionError("compose_draft_scope_forbidden")
        if row["snapshot_hash"] == digest and bool(row["archived"]) == bool(payload.get("archived")):
            return public_draft(row)  # Lost response: exact replay is idempotent.
        changed = conn.execute("UPDATE official_document_compose_drafts SET snapshot_json=?, snapshot_hash=?, revision=revision+1, archived=?, updated_at=? WHERE id=? AND revision=? AND applicant_id=? AND company_id=?",
                               (encoded, digest, int(bool(payload.get("archived"))), timestamp, draft_id, revision, user["id"], user["company_id"])).rowcount
        if changed != 1:
            raise ValueError("compose_draft_revision_conflict")
    else:
        if revision != 0:
            raise ValueError("compose_draft_revision_conflict")
        try:
            conn.execute("INSERT INTO official_document_compose_drafts VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)",
                         (draft_id, user["company_id"], user["id"], encoded, digest, int(bool(payload.get("archived"))), timestamp, timestamp))
        except sqlite3.IntegrityError as exc:
            raise ValueError("compose_draft_revision_conflict") from exc
    return public_draft(conn.execute("SELECT * FROM official_document_compose_drafts WHERE id=?", (draft_id,)).fetchone())

def attachment_id(document_id, upload_id):
    if not upload_id:
        return ""
    if not re.fullmatch(r"[a-zA-Z0-9_-]{16,100}", str(upload_id)):
        raise ValueError("official_attachment_upload_id_invalid")
    return "ODATT-" + hashlib.sha256((document_id + "\n" + upload_id).encode()).hexdigest()[:40].upper()

def require_content_revision(document, payload):
    """New compose UI is guarded; legacy non-compose API workflows stay compatible."""
    metadata = document.get("metadata_json") or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    guarded = document.get("source_type") == "blank_editor" and (metadata.get("source") == "compose_form" or (metadata.get("extra") or {}).get("source") == "compose_form")
    expected = payload.get("expected_content_revision")
    if guarded and (type(expected) is not int or expected < 0):
        raise ValueError("compose_content_revision_required")
    if expected is not None and (type(expected) is not int or expected != int(document.get("content_revision") or 0)):
        raise ValueError("compose_content_revision_conflict")
