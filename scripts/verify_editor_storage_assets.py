#!/usr/bin/env python3
"""Verify finalized PDF Editor assets without exposing document metadata.

This operator-only gate downloads private objects server-side, recomputes byte
length and SHA-256, and emits aggregate machine evidence only.  Before the
storage-job migration it checks the existing asset/file-object/byte binding;
``--post-migration`` additionally requires the durable storage-job binding.
No object path, file name, hash, document ID, user ID, content, or credential
is printed or written to disk.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib import parse


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend  # noqa: E402


ALLOWED_KINDS = {"source_pdf", "import_pdf", "image"}


def require_configuration() -> None:
    if not backend.USE_SUPABASE:
        raise RuntimeError("database_supabase_mode_required")
    if backend.EDOC_STORAGE_PROVIDER != "supabase":
        raise RuntimeError("supabase_storage_provider_required")
    if backend.EDOC_STORAGE_SUPABASE_MODE != "dedicated-project":
        raise RuntimeError("dedicated_storage_mode_required")
    if backend.EDOC_STORAGE_BUCKET != "edoc-private":
        raise RuntimeError("editor_storage_bucket_invalid")
    if not backend.SUPABASE_URL or not backend.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("database_runtime_config_missing")
    if not backend.object_storage_endpoint() or not backend.storage_service_role_key():
        raise RuntimeError("storage_runtime_config_missing")
    issues = backend.supabase_project_partition_issues()
    if issues:
        raise RuntimeError("storage_project_partition_invalid")


def finalized_asset_page(offset: int, limit: int) -> list[dict[str, Any]]:
    params = {
        "select": (
            "id,document_id,asset_kind,file_object_id,size_bytes,sha256,"
            "expected_sha256,storage_bucket,storage_path,upload_status"
        ),
        "asset_kind": "in.(source_pdf,import_pdf,image)",
        "upload_status": "eq.finalized",
        "order": "id.asc",
        "limit": str(limit),
        "offset": str(offset),
    }
    rows = backend.supabase_request(
        "GET",
        "official_document_editor_assets?" + parse.urlencode(params),
    )
    if not isinstance(rows, list):
        raise RuntimeError("editor_asset_inventory_contract_invalid")
    return [row for row in rows if isinstance(row, dict)]


def asset_error_code(
    asset: dict[str, Any],
    *,
    post_migration: bool = False,
) -> str:
    try:
        asset_id = str(asset.get("id") or "")
        document_id = str(asset.get("document_id") or "")
        digest = str(asset.get("sha256") or "").upper()
        expected_digest = str(asset.get("expected_sha256") or "").upper()
        size_bytes = int(asset.get("size_bytes") or 0)
        bucket = str(asset.get("storage_bucket") or "")
        storage_path = str(asset.get("storage_path") or "")
        file_object_id = str(asset.get("file_object_id") or "")
        expected_prefix = (
            f"editor-final/{document_id}/{asset_id}/{digest}-"
        )
        if (
            not asset_id
            or not document_id
            or str(asset.get("asset_kind") or "") not in ALLOWED_KINDS
            or not re.fullmatch(r"[A-F0-9]{64}", digest)
            or expected_digest != digest
            or size_bytes <= 0
            or bucket != backend.EDOC_STORAGE_BUCKET
            or not storage_path.startswith(expected_prefix)
            or not file_object_id
        ):
            return "editor_asset_metadata_invalid"

        file_object = backend.supabase_get("file_objects", file_object_id)
        if not file_object:
            return "editor_asset_file_object_missing"
        if (
            str(file_object.get("document_id") or "") != document_id
            or str(file_object.get("bucket") or "") != bucket
            or str(file_object.get("storage_key") or "") != storage_path
            or str(file_object.get("storage_provider") or "") != "supabase"
            or str(file_object.get("sha256") or "").upper() != digest
            or int(file_object.get("size_bytes") or 0) != size_bytes
        ):
            return "editor_asset_file_object_mismatch"

        if post_migration:
            jobs = backend.supabase_filter_rows(
                "official_document_editor_storage_jobs",
                {"asset_id": asset_id, "document_id": document_id},
                limit=2,
            )
            if len(jobs) != 1:
                return "editor_storage_job_missing"
            job = jobs[0]
            if (
                str(job.get("status") or "") not in {"committed", "cleaned"}
                or str(job.get("final_file_object_id") or "") != file_object_id
                or str(job.get("final_bucket") or "") != bucket
                or str(job.get("final_path") or "") != storage_path
                or str(job.get("expected_sha256") or "").upper() != digest
                or int(job.get("expected_size_bytes") or 0) != size_bytes
            ):
                return "editor_storage_job_mismatch"

        data = backend.supabase_storage_download(storage_path, bucket)
        try:
            if len(data) != size_bytes:
                return "editor_asset_byte_size_mismatch"
            if backend.sha256_bytes(data) != digest:
                return "editor_asset_byte_hash_mismatch"
        finally:
            del data
        return ""
    except Exception:
        return "editor_asset_verification_unavailable"


def verify_all(*, post_migration: bool = False) -> dict[str, Any]:
    checked = 0
    valid = 0
    errors: Counter[str] = Counter()
    page_size = 200
    offset = 0
    while True:
        rows = finalized_asset_page(offset, page_size)
        for asset in rows:
            checked += 1
            error_code = asset_error_code(asset, post_migration=post_migration)
            if error_code:
                errors[error_code] += 1
            else:
                valid += 1
        if len(rows) < page_size:
            break
        offset += page_size
    return {
        "gate": "editor_storage_asset_byte_inventory",
        "phase": "post-migration" if post_migration else "pre-migration",
        "passed": not errors,
        "checkedAssetCount": checked,
        "validAssetCount": valid,
        "invalidAssetCount": checked - valid,
        "errorCounts": dict(sorted(errors.items())),
        "aggregateOnly": True,
        "containsPaths": False,
        "containsNames": False,
        "containsHashes": False,
        "containsDocumentContent": False,
        "storageJobBindingChecked": post_migration,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--acknowledge-private-document-download",
        action="store_true",
        help="Required operator acknowledgement for the read-only private-byte check.",
    )
    parser.add_argument(
        "--post-migration",
        action="store_true",
        help="Also require the durable editor Storage job/file binding.",
    )
    args = parser.parse_args()
    if not args.acknowledge_private_document_download:
        print(
            json.dumps(
                {
                    "gate": "editor_storage_asset_byte_inventory",
                    "passed": False,
                    "errorCode": "operator_acknowledgement_required",
                    "aggregateOnly": True,
                },
                separators=(",", ":"),
            )
        )
        return 2
    try:
        require_configuration()
        result = verify_all(post_migration=args.post_migration)
    except Exception as error:
        code = str(error)
        if not re.fullmatch(r"[a-z0-9_]{3,96}", code):
            code = "editor_asset_inventory_unavailable"
        result = {
            "gate": "editor_storage_asset_byte_inventory",
            "phase": "post-migration" if args.post_migration else "pre-migration",
            "passed": False,
            "errorCode": code,
            "aggregateOnly": True,
            "containsPaths": False,
            "containsNames": False,
            "containsHashes": False,
            "containsDocumentContent": False,
        }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
