"""Short-lived, exact-source maintenance import; never impersonates staff SSO."""
from __future__ import annotations
import hashlib
import hmac
import re
import time
import urllib.error
from dataclasses import dataclass
import seal_scan_20261013 as scan

ACTOR = "system:codex-operator-import"
HEADER = "X-EDOC-Native120-Seal-Import-Key"


@dataclass(frozen=True)
class _OperatorContext:
    key_sha256: str
    started_at_epoch: int
    expires_at_epoch: int


def authorize(provided: str, env, *, clock=None) -> _OperatorContext:
    """Checks only key hashes; raw authorization is never returned or logged."""
    now=int(time.time() if clock is None else clock)
    expected=str(env.get("EDOC_NATIVE120_SEAL_IMPORT_KEY_SHA256") or "")
    try:
        started=int(env.get("EDOC_NATIVE120_SEAL_IMPORT_STARTED_AT") or "0")
        expires=int(env.get("EDOC_NATIVE120_SEAL_IMPORT_EXPIRES_AT") or "0")
    except (TypeError,ValueError):
        raise PermissionError("approved_scan_import_unauthorized") from None
    if (not re.fullmatch(r"[0-9a-f]{64}",expected) or not isinstance(provided,str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}",provided)
        or not 0 < expires-started <= 3600 or not started <= now < expires
        or not hmac.compare_digest(hashlib.sha256(provided.encode()).hexdigest(),expected)):
        raise PermissionError("approved_scan_import_unauthorized")
    return _OperatorContext(expected,started,expires)


def import_one(runtime, context: _OperatorContext, payload):
    """AV/Storage/atomic RPC pipeline; no session=None or caller-set attestation."""
    if not isinstance(context,_OperatorContext) or not context.started_at_epoch <= time.time() < context.expires_at_epoch:
        raise PermissionError("approved_scan_import_unauthorized")
    if not isinstance(payload,dict) or set(payload)!={"source_pdf_sha256","seal_id","content_base64"} or any(not isinstance(v,str) for v in payload.values()):
        raise ValueError("approved_scan_import_payload_invalid")
    if payload["source_pdf_sha256"] != scan.SOURCE_SHA256:
        raise ValueError("approved_scan_import_source_invalid")
    rows=[r for r in scan._ROWS if r[2]==payload["seal_id"]]
    if len(rows)!=1: raise ValueError("approved_scan_import_slot_invalid")
    expected=dict(zip(scan._KEYS,rows[0]))
    if not runtime.USE_SUPABASE or not runtime.is_production():
        raise RuntimeError("approved_scan_import_production_runtime_required")
    runtime.require_production_editor_runtime_ready()
    batches=runtime.supabase_filter_rows("approved_native120_scan_import_batches",{"batch_id":scan.POLICY},limit=1)
    batch=batches[0] if batches else None
    if (not batch or batch.get("status")!="open" or batch.get("key_sha256")!=context.key_sha256
        or batch.get("source_pdf_sha256")!=scan.SOURCE_SHA256
        or int(batch.get("started_at_epoch") or 0)!=context.started_at_epoch
        or int(batch.get("expires_at_epoch") or 0)!=context.expires_at_epoch):
        raise PermissionError("approved_scan_import_permit_closed")
    seal=runtime.supabase_get("company_seals",expected["seal_id"])
    if not seal or scan.approved_metadata(seal)!=[dict(expected,source_pdf_sha256=scan.SOURCE_SHA256,dimension_policy_version=scan.POLICY,calibration_dpi=120)]:
        raise ValueError("approved_scan_import_slot_invalid")
    runtime.assert_seal_company_scope(runtime.supabase_get("companies",expected["company_id"]))
    if not seal.get("is_active"): raise ValueError("approved_scan_import_slot_unavailable")
    data=runtime.decode_seal_file_content(payload["content_base64"])
    digest=hashlib.sha256(data).hexdigest()
    if digest!=expected["png_sha256"]: raise ValueError("approved_scan_import_hash_invalid")
    file_name=digest+".png"
    info=runtime.validate_seal_file_upload(file_name,"image/png",data,expected["seal_size_type"],expected["render_width_mm"],expected["render_height_mm"],expected["seal_category"],seal)
    existing=runtime.supabase_filter_rows("company_seal_files",{"seal_id":seal["id"],"is_current":True},limit=2)
    if existing:
        if len(existing)!=1 or not scan.file_entry(existing[0],seal["seal_size_type"]) or str(existing[0].get("file_hash") or "").lower()!=digest:
            raise ValueError("approved_scan_import_current_conflict")
        backing=runtime.supabase_get("file_objects",existing[0].get("file_object_id") or "")
        if not runtime.seal_policy.backing_metadata_matches(existing[0],backing) or not runtime.seal_file_av_is_clean(backing):
            raise ValueError("approved_scan_import_existing_backing_invalid")
        restored=runtime.supabase_storage_download(backing["storage_key"],runtime.EDOC_SEAL_STORAGE_BUCKET)
        if hashlib.sha256(restored).hexdigest()!=digest: raise ValueError("approved_scan_import_existing_hash_invalid")
    # This calls the actual configured provider. Failure stops before Storage.
    status,signature=runtime.scan_seal_upload_bytes(data,file_name)
    if status!="已通過": raise ValueError("seal_file_antivirus_rejected")
    if not context.started_at_epoch <= time.time() < context.expires_at_epoch:
        raise PermissionError("approved_scan_import_unauthorized")
    object_id="FILE-APPROVED-"+digest
    file_id="SFILE-APPROVED-"+digest
    storage_key=f"seal-vault/seals/{seal['id']}/SEAL-VAULT/{object_id}.png"
    if not existing:
        try:
            runtime.supabase_storage_upload(storage_key,data,"image/png",runtime.EDOC_SEAL_STORAGE_BUCKET)
        except ValueError:
            # Create-only retries reuse only identical actual prior bytes.
            prior=runtime.supabase_storage_download(storage_key,runtime.EDOC_SEAL_STORAGE_BUCKET)
            if len(prior)!=len(data) or hashlib.sha256(prior).hexdigest()!=digest:
                raise ValueError("approved_scan_import_storage_conflict") from None
        restored=runtime.supabase_storage_download(storage_key,runtime.EDOC_SEAL_STORAGE_BUCKET)
        if len(restored)!=len(data) or hashlib.sha256(restored).hexdigest()!=digest:
            raise ValueError("approved_scan_import_storage_verification_failed")
    if not context.started_at_epoch <= time.time() < context.expires_at_epoch:
        raise PermissionError("approved_scan_import_unauthorized")
    params={"p_seal_id":seal["id"],"p_object_id":object_id,"p_file_id":file_id,
            "p_storage_key":storage_key,"p_file_name":file_name,"p_file_size":len(data),
            "p_sha256":digest.upper(),"p_pixel_width":info["pixel_width"],"p_pixel_height":info["pixel_height"],
            "p_ratio":info["source_aspect_ratio"],"p_width_mm":info["render_width_mm"],"p_height_mm":info["render_height_mm"],
            "p_scan_engine":runtime.EDOC_SCAN_ENGINE,"p_scan_signature":signature,
            "p_source_pdf_sha256":scan.SOURCE_SHA256,"p_key_sha256":context.key_sha256}
    def reconcile_unknown_commit():
        # Specific audit binds this key-hash batch to the deterministic file.
        # Do not turn a known denial or a historical matching row into success.
        if not context.started_at_epoch <= time.time() < context.expires_at_epoch:
            raise RuntimeError("approved_scan_import_commit_unconfirmed")
        permit_rows=runtime.supabase_filter_rows("approved_native120_scan_import_batches",{"batch_id":scan.POLICY},limit=1)
        permit=permit_rows[0] if permit_rows else {}
        audit=runtime.supabase_get("audit_logs","AUD-IMPORT-"+context.key_sha256+"-"+digest)
        if (permit.get("status") not in {"open","completed"} or permit.get("key_sha256")!=context.key_sha256
            or permit.get("source_pdf_sha256")!=scan.SOURCE_SHA256 or not audit
            or int(permit.get("started_at_epoch") or 0)!=context.started_at_epoch
            or int(permit.get("expires_at_epoch") or 0)!=context.expires_at_epoch
            or audit.get("actor")!=ACTOR or audit.get("action")!="operator_import_native120_scan"
            or audit.get("target_type")!="company_seal_files" or not audit.get("target_id")
            or scan.SOURCE_SHA256 not in str(audit.get("detail") or "")):
            raise RuntimeError("approved_scan_import_commit_unconfirmed")
        # A pre-existing custodian version may have a non-operator ID. Its
        # immutable per-batch audit, not a caller ID, is the confirmation anchor.
        persisted=runtime.supabase_get("company_seal_files",audit["target_id"])
        if (not persisted or not scan.file_entry(persisted,seal["seal_size_type"])
            or persisted.get("seal_id")!=seal["id"] or str(persisted.get("file_hash") or "").lower()!=digest
            or not persisted.get("is_current")):
            raise RuntimeError("approved_scan_import_commit_unconfirmed")
        backing=runtime.supabase_get("file_objects",persisted.get("file_object_id") or "")
        if not runtime.seal_policy.backing_metadata_matches(persisted,backing) or not runtime.seal_file_av_is_clean(backing):
            raise RuntimeError("approved_scan_import_commit_unconfirmed")
        confirmed=runtime.supabase_storage_download(backing["storage_key"],runtime.EDOC_SEAL_STORAGE_BUCKET)
        if hashlib.sha256(confirmed).hexdigest()!=digest: raise RuntimeError("approved_scan_import_commit_unconfirmed")
        return {"file":persisted,"import_status":"already_registered","completed_file_count":permit.get("completed_file_count"),"batch_status":permit.get("status")}
    try:
        result=runtime.supabase_request("POST","rpc/edoc_import_approved_native120_scan_file",params)
    except (urllib.error.URLError,TimeoutError,ConnectionError):
        result=reconcile_unknown_commit()
    except RuntimeError as error:
        if str(error)!="supabase_response_invalid" and not re.fullmatch(r"supabase_request_failed:50[0234](?::[A-Za-z0-9_-]+)?",str(error)):
            raise
        result=reconcile_unknown_commit()
    item=result.get("file") if isinstance(result,dict) else None
    if (not item or not scan.file_entry(item,seal["seal_size_type"]) or not item.get("is_current")
        or str(item.get("file_hash") or "").lower()!=digest):
        raise RuntimeError("approved_scan_import_commit_unconfirmed")
    # Read the same authoritative catalog projection used by the editor. A
    # committed file is not equivalent to a selectable, usable current stamp.
    catalog=runtime.supabase_company_seal_row(seal["id"])
    current=catalog.get("current_file") or {}
    selectable=bool(catalog.get("selectable") and current.get("id")==item["id"]
                    and str(current.get("file_hash") or "").lower()==digest)
    return {"ok":True,"import_status":result.get("import_status"),"seal_id":seal["id"],
            "file_id":item["id"],"completed_file_count":result.get("completed_file_count"),"batch_status":result.get("batch_status"),
            "catalog_selectable":selectable,"availability_reason":catalog.get("availability_reason")}
