"""Explicit seal-owner taxonomy and calibrated continuous-seal geometry.

No company name, image name, or document body is used to infer owner kind.
Existing category identifiers remain stable for historical workflow evidence.
"""
from __future__ import annotations

import math
import re
from typing import Any, Iterable
import seal_scan_exceptions

OWNER_KINDS = frozenset({"company", "institution", "unclassified"})
CONTINUOUS_CATEGORY = "continuous_seal"
CONTINUOUS_SIZE = "single_seal"
CONTINUOUS_POLICY = "continuous-seal-v1-calibrated"
OFFICIAL_POLICY = "official-seal-v1-calibrated"
CATEGORY_LABELS = {
    "establishment_seal": "公司章",
    "general_seal": "便章",
    "official_seal": "圖記章",
    CONTINUOUS_CATEGORY: "連續章",
    "bank_seal": "銀行章",
    "other": "其他章",
}
SIZE_LABELS = {"large_seal": "大章", "small_seal": "小章", CONTINUOUS_SIZE: "單枚"}


def owner_kind(value: Any) -> str:
    result = str(value or "unclassified").strip()
    if result not in OWNER_KINDS:
        raise ValueError("invalid_seal_owner_kind")
    return result


def expected_dimension_policy(size_type: Any, square_policy: str) -> str:
    return CONTINUOUS_POLICY if str(size_type) == CONTINUOUS_SIZE else square_policy


def validate_category_size(category: Any, size_type: Any) -> None:
    continuous = str(category) == CONTINUOUS_CATEGORY
    single = str(size_type) == CONTINUOUS_SIZE
    if continuous != single:
        raise ValueError("seal_category_size_mismatch")


def category_label(category: Any) -> str:
    return CATEGORY_LABELS.get(str(category), str(category or ""))


def application_category_allowed(kind: Any, category: Any) -> bool:
    normalized = owner_kind(kind)
    if normalized == "unclassified":
        return False
    allowed = {"general_seal", CONTINUOUS_CATEGORY}
    allowed.update({"establishment_seal", "official_seal"} if normalized == "unclassified" else {"establishment_seal"} if normalized == "company" else {"official_seal"})
    return str(category) in allowed


def require_application_category(kind: Any, category: Any) -> None:
    if owner_kind(kind) == "unclassified":
        raise ValueError("seal_owner_classification_required")
    if not application_category_allowed(kind, category):
        raise ValueError("seal_owner_policy_mismatch" if str(category) in {"establishment_seal", "official_seal"} else "unsupported_application_seal_category")


def slot_label(category: str, size_type: str) -> str:
    label = category_label(category)
    return label if size_type == CONTINUOUS_SIZE else f"{label}－{SIZE_LABELS.get(size_type, size_type)}"


def required_slots(kind: Any) -> list[dict[str, str]]:
    normalized = owner_kind(kind)
    primary = ["establishment_seal"] if normalized == "company" else ["official_seal"] if normalized == "institution" else ["establishment_seal", "official_seal"]
    slots = [
        {"category": category, "size_type": size, "label": slot_label(category, size),
         "applicability": "conditional" if normalized == "unclassified" else "required"}
        for category in primary for size in ("large_seal", "small_seal")
    ]
    slots.extend({"category": "general_seal", "size_type": size,
                  "label": slot_label("general_seal", size), "applicability": "required"}
                 for size in ("large_seal", "small_seal"))
    slots.append({"category": CONTINUOUS_CATEGORY, "size_type": CONTINUOUS_SIZE,
                  "label": "連續章", "applicability": "required"})
    return slots


def inventory(company_id: str, kind: Any, seals: Iterable[dict[str, Any]]) -> dict[str, Any]:
    normalized = owner_kind(kind)
    rows = list(seals)
    slots = []
    for slot in required_slots(normalized):
        matches = [row for row in rows if row.get("seal_category") == slot["category"]
                   and row.get("seal_size_type") == slot["size_type"] and row.get("is_active")]
        ready = [row for row in matches if row.get("current_file") and row["current_file"].get("usable") is True]
        status = "ready" if ready else "unusable_current" if any(row.get("current_file_status") for row in matches) else "missing_current" if matches else "missing_record"
        slots.append({**slot, "digital_status": status, "available_count": len(ready),
                      "record_count": len(matches), "seal_ids": [row["id"] for row in matches if row.get("id")]})
    return {"company_id": company_id, "owner_kind": normalized,
            "classification_required": normalized == "unclassified",
            "required_slots": slots,
            "missing_slots": [slot for slot in slots if slot["applicability"] == "required" and slot["digital_status"] != "ready"],
            "conditional_slots": [slot for slot in slots if slot["applicability"] == "conditional"],
            "physical_inventory_verified": False,
            "ready": normalized != "unclassified" and all(slot["digital_status"] == "ready" for slot in slots)}


def launch_inventory(company_id: str, company_name: str, kind: Any, seals: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    rows = list(seals)
    report = inventory(company_id, kind, rows)
    required = []
    blockers = [f"{company_name} 尚未明確設定公司／機構印章種類。"] if report["classification_required"] else []
    for slot in report["required_slots"]:
        if slot["applicability"] != "required":
            continue
        ready = next((row for row in rows if row.get("id") in slot["seal_ids"] and row.get("current_file") and row["current_file"].get("usable") is True), None)
        action = "電子章檔已可用" if slot["digital_status"] == "ready" else "校正或補上可用的 current 電子章檔" if slot["digital_status"] == "unusable_current" else "上傳 current 電子章檔" if slot["record_count"] else "建立章槽並上傳電子章檔（不代表實體章不存在）"
        required.append({**slot, "active": bool(slot["record_count"]), "currentFile": slot["digital_status"] == "ready",
                         "sealCount": slot["record_count"], "sealIds": slot["seal_ids"],
                         "firstSealId": slot["seal_ids"][0] if slot["seal_ids"] else "",
                         "currentSealId": (ready or {}).get("id") or "", "nextAction": action})
        if slot["digital_status"] != "ready":
            blockers.append(f"{company_name} 的{slot['label']}尚無可用電子章檔。")
    return {**report, "company_name": company_name, "launchScopeIncluded": True, "requiredSeals": required}, blockers


def rectangular_geometry(size_type: str, width: Any = None, height: Any = None, *, dpi: int = 250) -> dict[str, Any]:
    if width is None or height is None:
        raise ValueError("seal_manual_calibration_required")
    try:
        w, h = float(width), float(height)
    except (TypeError, ValueError) as exc:
        raise ValueError("seal_render_size_invalid") from exc
    if size_type not in {CONTINUOUS_SIZE, "large_seal", "small_seal"}:
        raise ValueError("seal_dimension_profile_missing")
    if any(not math.isfinite(value) or value < 1.0 or value > 200.0 for value in (w, h)):
        raise ValueError("seal_render_size_out_of_range")
    return {"seal_size_type": size_type, "size_mm": None,
            "default_width_mm": None, "default_height_mm": None,
            "min_width_mm": 1.0, "min_height_mm": 1.0,
            "max_width_mm": 200.0, "max_height_mm": 200.0,
            "width_mm": w, "height_mm": h, "width_pt": w * 72.0 / 25.4,
            "height_pt": h * 72.0 / 25.4,
            "min_width_px": math.ceil(w / 25.4 * dpi),
            "min_height_px": math.ceil(h / 25.4 * dpi),
            "min_short_edge_px": math.ceil(min(w, h) / 25.4 * dpi),
            "calibration_dpi": dpi, "dimension_policy_version": CONTINUOUS_POLICY if size_type == CONTINUOUS_SIZE else OFFICIAL_POLICY,
            "calibration_required": True}


def rectangular_file_dimensions_valid(row: dict[str, Any], size_type: str) -> bool:
    expected = CONTINUOUS_POLICY if size_type == CONTINUOUS_SIZE else OFFICIAL_POLICY
    if not row.get("dimension_validated") or row.get("dimension_policy_version") != expected:
        return False
    try:
        profile = rectangular_geometry(size_type, row.get("render_width_mm"), row.get("render_height_mm"))
        width, height = int(row.get("pixel_width") or 0), int(row.get("pixel_height") or 0)
        source_ratio = float(row.get("source_aspect_ratio"))
        ratio = width / height
        return bool(width >= profile["min_width_px"] and height >= profile["min_height_px"]
                    and math.isfinite(source_ratio) and abs(source_ratio - ratio) <= 0.000001
                    and abs(ratio / (profile["width_mm"] / profile["height_mm"]) - 1.0) <= 0.01)
    except (ValueError, TypeError, ZeroDivisionError):
        return False


def category_policy_valid(category: Any, size_type: Any, file_row: dict[str, Any]) -> bool:
    policy = str(file_row.get("dimension_policy_version") or "")
    if policy == seal_scan_exceptions.POLICY:
        entry = seal_scan_exceptions.file_entry(file_row, size_type)
        return bool(entry and entry["seal_category"] == category)
    if policy == CONTINUOUS_POLICY:
        return category == CONTINUOUS_CATEGORY and size_type == CONTINUOUS_SIZE
    if policy == OFFICIAL_POLICY:
        return category == "official_seal" and size_type in {"large_seal", "small_seal"}
    return category != CONTINUOUS_CATEGORY and size_type != CONTINUOUS_SIZE


def backing_metadata_matches(seal_file: dict[str, Any], file_object: dict[str, Any] | None) -> bool:
    if not file_object or not seal_file.get("file_object_id"):
        return False
    try:
        return bool(str(file_object.get("id") or "") == str(seal_file.get("file_object_id"))
                    and str(file_object.get("sha256") or "") == str(seal_file.get("file_hash") or "")
                    and re.fullmatch(r"[0-9a-fA-F]{64}", str(seal_file.get("file_hash") or ""))
                    and int(file_object.get("size_bytes") or 0) == int(seal_file.get("file_size") or 0) > 0
                    and str(file_object.get("mime_type") or "") == str(seal_file.get("file_mime_type") or "")
                    and str(file_object.get("storage_key") or "") == str(seal_file.get("file_storage_key") or "")
                    and bool(file_object.get("storage_key")))
    except (TypeError, ValueError):
        return False
