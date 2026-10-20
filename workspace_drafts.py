"""Private unfinished work: bounded metadata pages, exact totals, no snapshot downloads."""
import base64
import hashlib
import json


def options(query, user):
    query = query or {}
    first = lambda key: str((query.get(key) or [""])[0]).strip()
    size = first("page_size") or "25"
    search = first("search")
    archived = first("archived")
    if not size.isdigit() or not 1 <= int(size) <= 100 or len(search) > 200 or archived not in {"", "0", "1"}:
        raise ValueError("workspace_drafts_filter_invalid")
    fingerprint = hashlib.sha256(json.dumps([user["id"], user["company_id"], search, archived == "1"]).encode()).hexdigest()[:24]
    result = {"actor_id": user["id"], "company_id": user["company_id"], "page_size": int(size),
              "search": search, "archived": archived == "1", "summary": first("summary") == "1", "after_at": "", "after_key": "", "fingerprint": fingerprint}
    cursor = first("cursor")
    if cursor:
        try:
            value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if len(cursor) > 2048 or not isinstance(value, list) or len(value) != 3 or value[0] != fingerprint or not all(isinstance(v, str) and v for v in value):
                raise ValueError()
            result.update(after_at=value[1], after_key=value[2])
        except (ValueError, TypeError, UnicodeError):
            raise ValueError("workspace_drafts_cursor_invalid") from None
    return result


def response(raw, config):
    if not isinstance(raw, dict) or type(raw.get("total")) is not int or raw["total"] < 0 or not isinstance(raw.get("items"), list):
        raise RuntimeError("workspace_drafts_response_invalid")
    rows = raw["items"]
    more = len(rows) > config["page_size"]
    rows = rows[:config["page_size"]]
    cursor = None
    if more and rows:
        cursor = base64.urlsafe_b64encode(json.dumps([config["fingerprint"], rows[-1]["updated_at"], rows[-1]["key"]]).encode()).decode().rstrip("=")
    return {"items": rows, "total": raw["total"], "next_cursor": cursor, "has_more": more}


# Only rows owned by the authenticated applicant enter this CTE. Cloud snapshots
# are never trusted as permission proof: a linked official case must have the
# same applicant, and submitted/terminated cases cannot reappear as stale drafts.
SQLITE_CTE = """
WITH cloud_linked AS (
 SELECT c.*, d.id AS linked_id, d.current_status AS linked_status, d.source_type AS linked_source,
 (coalesce(json_extract(c.snapshot_json,'$.officialDocumentId'),'')='' AND coalesce(json_extract(c.snapshot_json,'$.currentComposeDraftId'),'')=''
  AND coalesce(json_extract(c.snapshot_json,'$.values."#dispatchNo"'),'')=''
  AND NOT EXISTS(SELECT 1 FROM official_documents x WHERE x.id=c.id OR x.id=json_extract(c.snapshot_json,'$.draftRequestId'))) AS can_archive,
 row_number() OVER (PARTITION BY coalesce(d.id, 'cloud:' || c.id) ORDER BY c.updated_at DESC,c.id DESC) AS position
 FROM official_document_compose_drafts c
 LEFT JOIN official_documents d ON d.applicant_id=c.applicant_id
  AND d.id=coalesce(nullif(json_extract(c.snapshot_json,'$.officialDocumentId'),''),nullif(json_extract(c.snapshot_json,'$.draftRequestId'),''))
 WHERE c.applicant_id=:actor_id AND c.company_id=:company_id AND c.archived=:archived
), cloud AS (
 SELECT 'cloud:' || id AS key,id,'cloud' AS kind,coalesce(linked_source,'blank_editor') AS source_type,
 coalesce(linked_status,'draft') AS status,coalesce(linked_id,'') AS official_id,
 coalesce(nullif(json_extract(snapshot_json,'$.values."#subject"'),''),nullif(json_extract(snapshot_json,'$.values."#documentPurpose"'),''),'未命名公文') AS title,updated_at,revision,can_archive
 FROM cloud_linked WHERE position=1 AND (linked_id IS NULL OR linked_status IN ('draft','rejected')) AND (:archived=0 OR can_archive=1)
), drafts AS (
 SELECT * FROM cloud
 UNION ALL
 SELECT 'official:' || d.id,d.id,'official',d.source_type,d.current_status,d.id,coalesce(nullif(d.subject,''),nullif(d.title,''),'未命名文件'),d.updated_at,NULL,0
 FROM official_documents d WHERE :archived=0 AND d.applicant_id=:actor_id AND d.current_status IN ('draft','rejected')
 AND NOT EXISTS(SELECT 1 FROM cloud WHERE cloud.official_id=d.id)
), filtered AS (SELECT * FROM drafts WHERE :search='' OR instr(lower(title),lower(:search))>0 OR instr(lower(id),lower(:search))>0)
"""


def list_sqlite(api, conn, query, session):
    config = options(query, api.compose_draft_user(session))
    total = conn.execute(SQLITE_CTE + " SELECT count(*) FROM filtered", config).fetchone()[0]
    rows = [] if config["summary"] else [dict(row) for row in conn.execute(SQLITE_CTE + """
      SELECT * FROM filtered WHERE :after_at='' OR (updated_at,key)<(:after_at,:after_key)
      ORDER BY updated_at DESC,key DESC LIMIT :limit""", {**config, "limit": config["page_size"] + 1})]
    return response({"items": rows, "total": total}, config)


def list_supabase(api, query, session):
    config = options(query, api.compose_draft_user(session))
    raw = api.supabase_request("POST", "rpc/edoc_workspace_drafts", {"p_request": {k: v for k, v in config.items() if k != "fingerprint"}})
    return response(raw, config)
