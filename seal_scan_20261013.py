"""Six exact native 120 DPI stamp crops approved for the 1:1 20261013 source.

This registry is provenance only. It cannot authorize an actor, activate a
current version, or relax the ordinary 250 DPI policy for any other bytes.
Physical canvas dimensions preserve each crop's original aspect ratio.
"""
from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

POLICY = "native-scan-120dpi-20261013-v1"
SOURCE_SHA256 = "4426fcf11ca7cd45ed8d2e942b137c7f5f4ac6efc585ad87078faaadf941487c"
CALIBRATION_DPI = 120
_ROWS = (
    ("f429854fb082934e93961458628e041b2682f94d89d726b92cc73fd1c042f8e7", "CO-007", "CSEAL-CO-007-EST-L", "establishment_seal", "large_seal", 125, 124, 26.458, 26.247, 1),
    ("4011a30985893479a30bdf2c6481cf60b9c22ce122e22a094898cebffa2082a6", "CO-007", "CSEAL-CO-007-EST-S", "establishment_seal", "small_seal", 66, 65, 13.970, 13.758, 1),
    ("5249fba51127b75b0918bb33b2b46dfa6317fb1b79109309ed4f4312a119997f", "FINCO-AE264D87483E", "CSEAL-FINCO-AE264D87483E-official_seal-large_seal", "official_seal", "large_seal", 123, 123, 26.035, 26.035, 2),
    ("d68ff63f4fd1e4a6674676640a6c1ac8fd11c019f5db8ce8473fbaec975be002", "FINCO-AE264D87483E", "CSEAL-FINCO-AE264D87483E-official_seal-small_seal", "official_seal", "small_seal", 69, 68, 14.605, 14.393, 2),
    ("100e26e3c369aa9e2c09df8ce60fba994148158826279d86d62867c56421d947", "FINCO-D7FAD93DE9AE", "CSEAL-FINCO-D7FAD93DE9AE-official_seal-large_seal", "official_seal", "large_seal", 156, 156, 33.020, 33.020, 3),
    ("0c8f7d93ee3cf50ad88065a7ffb22ebef7bfc7026353821589113da75b90d02a", "FINCO-D7FAD93DE9AE", "CSEAL-FINCO-D7FAD93DE9AE-official_seal-small_seal", "official_seal", "small_seal", 70, 69, 14.817, 14.605, 3),
)
_KEYS = ("png_sha256", "company_id", "seal_id", "seal_category", "seal_size_type", "pixel_width", "pixel_height", "render_width_mm", "render_height_mm", "source_page")


def approved_metadata(seal: dict[str, Any]) -> list[dict[str, Any]]:
    """Expected provenance for an authorized exact slot, never image bytes."""
    slot = tuple(str(seal.get(key) or "") for key in ("company_id", "id", "seal_category", "seal_size_type"))
    return [dict(zip(_KEYS, values), source_pdf_sha256=SOURCE_SHA256,
                 dimension_policy_version=POLICY, calibration_dpi=CALIBRATION_DPI)
            for values in _ROWS if values[1:5] == slot]


def profile(entry: dict[str, Any]) -> dict[str, Any]:
    width, height = float(entry["render_width_mm"]), float(entry["render_height_mm"])
    return {"seal_size_type": entry["seal_size_type"], "size_mm": None,
            "width_mm": width, "height_mm": height,
            "width_pt": width * 72 / 25.4, "height_pt": height * 72 / 25.4,
            "default_width_mm": width, "default_height_mm": height,
            "min_width_mm": width, "max_width_mm": width,
            "min_height_mm": height, "max_height_mm": height,
            "min_width_px": entry["pixel_width"], "min_height_px": entry["pixel_height"],
            "min_short_edge_px": min(entry["pixel_width"], entry["pixel_height"]),
            "calibration_dpi": CALIBRATION_DPI, "dimension_policy_version": POLICY,
            "calibration_required": False, "original_scan_exception": True}


def file_entry(row: dict[str, Any], size_type: Any) -> dict[str, Any] | None:
    attested = row.get("dimension_validated")
    if row.get("dimension_policy_version") != POLICY or not (attested is True or type(attested) is int and attested == 1):
        return None
    if type(row.get("pixel_width")) is not int or type(row.get("pixel_height")) is not int:
        return None
    try:
        if any(type(row.get(key)) not in (int, float, Decimal) or not math.isfinite(float(row[key]))
               for key in ("source_aspect_ratio", "render_width_mm", "render_height_mm")):
            return None
    except (ValueError, OverflowError):
        return None
    for values in _ROWS:
        entry = dict(zip(_KEYS, values), source_pdf_sha256=SOURCE_SHA256,
                     dimension_policy_version=POLICY, calibration_dpi=CALIBRATION_DPI)
        if (str(row.get("file_hash") or "").lower() == entry["png_sha256"]
                and row.get("seal_id") == entry["seal_id"] and size_type == entry["seal_size_type"]
                and row["pixel_width"] == entry["pixel_width"] and row["pixel_height"] == entry["pixel_height"]
                and abs(float(row["source_aspect_ratio"]) - entry["pixel_width"] / entry["pixel_height"]) <= 0.000001
                and abs(float(row["render_width_mm"]) - entry["render_width_mm"]) <= 0.000001
                and abs(float(row["render_height_mm"]) - entry["render_height_mm"]) <= 0.000001):
            return entry
    return None


def geometry_profile(size_type: Any, width: Any, height: Any) -> dict[str, Any]:
    """Unit conversion only; immutable file validation must precede this call."""
    try:
        w, h = float(width), float(height)
        if not math.isfinite(w) or not math.isfinite(h):
            raise ValueError("approved_original_scan_geometry_mismatch")
        for values in _ROWS:
            if values[4] == size_type and abs(w - values[7]) <= 0.000001 and abs(h - values[8]) <= 0.000001:
                return profile(dict(zip(_KEYS, values)))
    except (TypeError, OverflowError) as exc:
        raise ValueError("approved_original_scan_geometry_mismatch") from exc
    raise ValueError("approved_original_scan_geometry_mismatch")
