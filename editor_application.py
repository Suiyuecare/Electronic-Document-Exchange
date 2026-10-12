"""Pure rules for editable PDF applications; no Storage or external calls."""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Callable


APPLICATION_LIMITS = {
    "company_id": 180, "title": 2000, "subject": 2000, "description": 20000,
    "request_reason": 20000, "handler_name": 300, "dispatch_unit": 300,
    "applicant_department_id": 180, "applicant_department_name": 300,
    "document_category": 300,
}
TOKEN_FIELDS = {"expected_content_revision", "expected_editor_revision_id", "expected_editor_manifest_sha256"}


def application_patch(payload: dict[str, Any]) -> dict[str, str]:
    if not isinstance(payload, dict) or set(payload) - set(APPLICATION_LIMITS) - TOKEN_FIELDS - {"ip_address", "user_agent"}:
        raise ValueError("editor_application_fields_invalid")
    patch = {}
    for key, limit in APPLICATION_LIMITS.items():
        if key not in payload:
            continue
        value = payload[key]
        if not isinstance(value, str) or len(value) > limit or "\x00" in value:
            raise ValueError("editor_application_fields_invalid")
        patch[key] = value.strip()
    if not patch or ("title" in patch and not patch["title"]):
        raise ValueError("official_document_title_required")
    return patch


def expected_versions(payload: dict[str, Any]) -> tuple[int, str, str]:
    revision = payload.get("expected_content_revision")
    revision_id = payload.get("expected_editor_revision_id")
    manifest = payload.get("expected_editor_manifest_sha256")
    if type(revision) is not int or revision < 0:
        raise ValueError("compose_content_revision_required")
    if not isinstance(revision_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,180}", revision_id):
        raise ValueError("editor_revision_conflict")
    if not isinstance(manifest, str) or not re.fullmatch(r"[A-Fa-f0-9]{64}", manifest):
        raise ValueError("editor_revision_conflict")
    return revision, revision_id, manifest


def company_editable(document: dict[str, Any], *, is_v2: bool, has_history: bool, irreversible: bool) -> bool:
    return bool(is_v2 and document.get("source_type") == "uploaded_pdf"
                and document.get("current_status") == "draft"
                and not str(document.get("dispatch_no") or "").strip()
                and not has_history and not irreversible)


def remove_foreign_seals(state: dict[str, Any], company_id: str,
                         seal_lookup: Callable[[str], dict[str, Any] | None]) -> tuple[dict[str, Any], list[str]]:
    """Remove mismatched seals and every member of their seam group, not text/PDF."""
    result = copy.deepcopy(state)
    remove, groups = set(), set()
    for element in result.get("elements") or []:
        if element.get("kind") != "seal":
            continue
        props = element.get("properties") or {}
        identity = str(props.get("sealId") or props.get("seal_id") or element.get("sealId") or "")
        seal = seal_lookup(identity) if identity else None
        if not seal or str(seal.get("company_id") or "") != company_id:
            remove.add(str(element.get("id") or ""))
            if props.get("seamGroupId"):
                groups.add(props["seamGroupId"])
    for element in result.get("elements") or []:
        if (element.get("properties") or {}).get("seamGroupId") in groups:
            remove.add(str(element.get("id") or ""))
    result["elements"] = [element for element in result.get("elements") or [] if str(element.get("id") or "") not in remove]
    return result, sorted(remove)


def require_preflight_application_version(document: dict[str, Any], asset_metadata: dict[str, Any]) -> None:
    """No old prepared PDF can confirm an application whose fields have changed."""
    witness = asset_metadata.get("application_content_revision")
    if type(witness) is not int or witness != int(document.get("content_revision") or 0):
        raise ValueError("editor_preflight_not_completed")
    if str(asset_metadata.get("application_company_id") or "") != str(document.get("company_id") or ""):
        raise ValueError("editor_preflight_not_completed")
    if asset_metadata.get("application_snapshot") != application_snapshot(document):
        raise ValueError("editor_preflight_not_completed")


def application_snapshot(document: dict[str, Any]) -> dict[str, str]:
    metadata = document.get("metadata_json") or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    fields = ("company_id", "applicant_id", "applicant_department_id", "applicant_department_name",
              "title", "subject", "description", "request_reason")
    return {**{key: str(document.get(key) or "") for key in fields},
            "document_category": str((metadata.get("official_seal") or {}).get("document_category") or "")}
