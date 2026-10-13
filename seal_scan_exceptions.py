"""One user-approved, exact-byte 200 DPI original-scan exception.

This is provenance metadata, not seal artwork. It does not authorize an actor,
activate a stamp, relax the general 250 DPI policy, or alter original pixels.
Only the 22 faithful PNGs from the approved 1:1 source can use this policy.
"""
from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

POLICY = "original-scan-200dpi-20260914-v1"
SOURCE_SHA256 = "95d90878c71f0efd874de4b0e812daebd536ec23435bb3a5ffb0dde9ed604b2e"
_ROWS = (
    ("8e47708f7838e097c31a94ee261da349f8fe4d84187da60f923f0b8f5067a0df","FINCO-263DD88BDAAA","CSEAL-FINCO-263DD88BDAAA-establishment_seal-large_seal","establishment_seal","large_seal",235,237,29.845,30.099,1),
    ("8a620f14bb6730bbbaa08f8d54a1b3b6872ef2ef0889917692293184f719f416","FINCO-263DD88BDAAA","CSEAL-FINCO-263DD88BDAAA-establishment_seal-small_seal","establishment_seal","small_seal",116,119,14.732,15.113,1),
    ("362d7b21d3c0433e1b37f32309dc5e3b87388e7b7d3f4ccc662eea0d8ee9edd6","FINCO-263DD88BDAAA","CSEAL-FINCO-263DD88BDAAA-bank_seal-large_seal","bank_seal","large_seal",236,240,29.972,30.48,1),
    ("a760f16ca1f5e29edf141f6f8807865bf3a81aa00a294fdf616ea4eb79d0a6c2","FINCO-263DD88BDAAA","CSEAL-FINCO-263DD88BDAAA-bank_seal-small_seal","bank_seal","small_seal",128,119,16.256,15.113,1),
    ("e1b08350f16327a056dd7fcd63bf5033ab833e448010afbd48a805a4e0069dbd","CO-002","CSEAL-CO-002-EST-L","establishment_seal","large_seal",211,207,26.797,26.289,2),
    ("ccfb0e087067844a4e7d4afe51fee634c5c572276ca8dd5132f20f58daa1227e","CO-002","CSEAL-CO-002-EST-S","establishment_seal","small_seal",126,124,16.002,15.748,2),
    ("48b910ea4ccf6e33191933a5d7029c44eea4eb88a6132b223100e29ef2eb366d","CO-002","CSEAL-CO-002-BANK-L","bank_seal","large_seal",221,213,28.067,27.051,2),
    ("baffd6716eaca45d349365e195f751d8889b1e680855ea86421e45d44279ae56","CO-002","CSEAL-CO-002-BANK-S","bank_seal","small_seal",124,123,15.748,15.621,2),
    ("33a28ffb114a6fca2855915cbe195252afff001e89cc1e25a033d4c026e8ad6c","CO-004","CSEAL-CO-004-EST-L","establishment_seal","large_seal",205,205,26.035,26.035,3),
    ("f2203b43f74e535a613cbdb6e3ce11826fb712a30ac3ed50b866efe1fcc60180","CO-004","CSEAL-CO-004-EST-S","establishment_seal","small_seal",128,131,16.256,16.637,3),
    ("b7d5dda2261ea8f07083418d29634f520f65bb3915610ffcd7510e03a8f2bdd5","CO-004","CSEAL-CO-004-BANK-L","bank_seal","large_seal",211,206,26.797,26.162,3),
    ("662e7c187bcd55413090cb71edad57880a5f7b622b088a14c3311b937656e3a4","CO-004","CSEAL-CO-004-BANK-S","bank_seal","small_seal",136,138,17.272,17.526,3),
    ("c4139a4b9013c582e1ce68ced15828f45a2ea4d96c6c72d224e6fdf362eaa1dd","CO-001","CSEAL-CO-001-EST-L","establishment_seal","large_seal",213,208,27.051,26.416,4),
    ("b0b3ebb6cc0bbc0baae2838a5e57d61db0637a4745d3ff79f643054b89bbbdc7","CO-001","CSEAL-CO-001-EST-S","establishment_seal","small_seal",119,116,15.113,14.732,4),
    ("c1d4ad0f7618e2cc1275ed5b454a04ada4fe4e01ad56c6fe388061fc5aa11d53","CO-001","CSEAL-CO-001-BANK-L","bank_seal","large_seal",214,208,27.178,26.416,4),
    ("4271ba55c9536f7ad808602a3fd7532612f9a3a8d93e4bb611c14211aad12379","CO-001","CSEAL-CO-001-BANK-S","bank_seal","small_seal",148,136,18.796,17.272,4),
    ("a300936f86617156c88f0867ffde3cd763381f6e7bea65a2b7345105e18775e7","CO-005","CSEAL-CO-005-BANK-L","bank_seal","large_seal",211,208,26.797,26.416,5),
    ("6bac3cb23dbb70702cfa2c19d48fac147b8552babc268dec176474cfe189d69e","CO-005","CSEAL-CO-005-BANK-S","bank_seal","small_seal",148,143,18.796,18.161,5),
    ("079e4845086f2af65d9c3d6eeb69349e1822928ed9b7a5c477522c4922a3b16b","CO-005","CSEAL-CO-005-official_seal-large_seal","official_seal","large_seal",448,635,56.896,80.645,5),
    ("6fc9c30acf425bc57cc84ec5ee5528f62218b6c265c6c37cb8af11d70631e459","CO-006","CSEAL-CO-006-BANK-L","bank_seal","large_seal",266,264,33.782,33.528,6),
    ("107f8cc21b0afae3218f4e354fe6f0a39feb959f85d38b3e306495d63632b64b","CO-006","CSEAL-CO-006-BANK-S","bank_seal","small_seal",123,119,15.621,15.113,6),
    ("5a0e37eb44a0df6ff4a4e32dc5b0b1fa086e7901cc835fb658a0c0c10f226b0d","CO-006","CSEAL-CO-006-official_seal-large_seal","official_seal","large_seal",438,609,55.626,77.343,6),
)
_KEYS = ("png_sha256", "company_id", "seal_id", "seal_category", "seal_size_type", "pixel_width", "pixel_height", "render_width_mm", "render_height_mm", "source_page")


def approved_metadata(seal: dict[str, Any]) -> list[dict[str, Any]]:
    """Authorized catalog metadata only; never image bytes or Storage keys."""
    return [dict(zip(_KEYS, row), source_pdf_sha256=SOURCE_SHA256,
                 dimension_policy_version=POLICY, calibration_dpi=200)
            for row in _ROWS if row[1:5] == tuple(str(seal.get(key) or "") for key in ("company_id", "id", "seal_category", "seal_size_type"))]


def profile(entry: dict[str, Any]) -> dict[str, Any]:
    w, h = float(entry["render_width_mm"]), float(entry["render_height_mm"])
    return {"seal_size_type": entry["seal_size_type"], "size_mm": None,
            "width_mm": w, "height_mm": h, "width_pt": w * 72 / 25.4, "height_pt": h * 72 / 25.4,
            "default_width_mm": w, "default_height_mm": h,
            "min_width_mm": w, "max_width_mm": w, "min_height_mm": h, "max_height_mm": h,
            "min_width_px": entry["pixel_width"], "min_height_px": entry["pixel_height"],
            "min_short_edge_px": min(entry["pixel_width"], entry["pixel_height"]),
            "calibration_dpi": 200, "dimension_policy_version": POLICY,
            "calibration_required": False, "original_scan_exception": True}


def metadata_valid(seal_id, company_id, category, size, digest, pixels_w,
                   pixels_h, ratio, mm_w, mm_h, policy, validated) -> bool:
    entry = file_entry({"seal_id": seal_id, "file_hash": digest, "pixel_width": pixels_w,
                        "pixel_height": pixels_h, "source_aspect_ratio": ratio,
                        "render_width_mm": mm_w, "render_height_mm": mm_h,
                        "dimension_policy_version": policy, "dimension_validated": validated}, size)
    return bool(entry and entry["company_id"] == company_id and entry["seal_category"] == category)


def upload_match(seal: dict[str, Any], file_hash: str, width: int, height: int,
                 physical_w: Any, physical_h: Any) -> dict[str, Any] | None:
    for entry in approved_metadata(seal):
        if entry["png_sha256"] != str(file_hash).lower():
            continue
        try:
            if (width != entry["pixel_width"] or height != entry["pixel_height"]
                    or not abs(float(physical_w) - entry["render_width_mm"]) <= 0.000001
                    or not abs(float(physical_h) - entry["render_height_mm"]) <= 0.000001):
                raise ValueError("approved_original_scan_geometry_mismatch")
            return entry
        except (TypeError, OverflowError) as exc:
            raise ValueError("approved_original_scan_geometry_mismatch") from exc
    return None


def file_entry(row: dict[str, Any], size_type: Any) -> dict[str, Any] | None:
    attested = row.get("dimension_validated")
    if row.get("dimension_policy_version") != POLICY or not (attested is True or type(attested) is int and attested == 1):
        return None
    if type(row.get("pixel_width")) is not int or type(row.get("pixel_height")) is not int:
        return None
    try:
        numeric_invalid = any(type(row.get(key)) not in (int,float,Decimal) or not math.isfinite(float(row[key]))
                              for key in ("source_aspect_ratio","render_width_mm","render_height_mm"))
    except (OverflowError, ValueError):
        return None
    if numeric_invalid:
        return None
    for values in _ROWS:
        entry = dict(zip(_KEYS, values))
        try:
            if (str(row.get("file_hash") or "").lower() == entry["png_sha256"] and row.get("seal_id") == entry["seal_id"]
                    and size_type == entry["seal_size_type"]
                    and int(row.get("pixel_width") or 0) == entry["pixel_width"]
                    and int(row.get("pixel_height") or 0) == entry["pixel_height"]
                    and math.isfinite(float(row.get("source_aspect_ratio")))
                    and abs(float(row["source_aspect_ratio"]) - entry["pixel_width"] / entry["pixel_height"]) <= 0.000001
                    and abs(float(row.get("render_width_mm")) - entry["render_width_mm"]) <= 0.000001
                    and abs(float(row.get("render_height_mm")) - entry["render_height_mm"]) <= 0.000001):
                return entry
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def geometry_profile(size_type: Any, width: Any, height: Any) -> dict[str, Any]:
    """Conversion only, not authorization; callers must first validate the file."""
    for values in _ROWS:
        entry = dict(zip(_KEYS, values))
        if entry["seal_size_type"] == size_type and abs(float(width) - entry["render_width_mm"]) <= 0.000001 and abs(float(height) - entry["render_height_mm"]) <= 0.000001:
            return profile(entry)
    raise ValueError("approved_original_scan_geometry_mismatch")
