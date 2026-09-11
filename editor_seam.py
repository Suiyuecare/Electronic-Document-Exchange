"""Validated split seal groups. Original Seal Vault bytes are never changed."""
from __future__ import annotations

import io
import math
import re


def validate_seam_groups(state: dict) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for element in state.get("elements") or []:
        props = element.get("properties") or {}
        group_id = props.get("seamGroupId")
        if not group_id:
            if any(key in props for key in ("seamPartIndex", "seamPartCount", "seamMode")):
                raise ValueError("editor_seam_group_invalid")
            continue
        if element.get("kind") != "seal" or not isinstance(group_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", group_id):
            raise ValueError("editor_seam_group_invalid")
        if props.get("seamMode") != "pair" or props.get("seamPartCount") != 2 or type(props.get("seamPartIndex")) is not int or props["seamPartIndex"] not in (0, 1):
            raise ValueError("editor_seam_group_invalid")
        if float(element.get("rotation") or 0) % 360 != 0:
            raise ValueError("editor_seam_rotation_locked")
        groups.setdefault(group_id, []).append(element)
    for members in groups.values():
        if len(members) != 2 or {item["properties"]["seamPartIndex"] for item in members} != {0, 1} or len({item.get("pageId") for item in members}) != 2:
            raise ValueError("editor_seam_group_incomplete")
        left, right = members
        ordered_members = sorted(members, key=lambda item: item["properties"]["seamPartIndex"])
        indexes = [next((i for i, page in enumerate(state.get("pages", [])) if page.get("pageId") == item.get("pageId")), -1) for item in ordered_members]
        if indexes[0] < 0 or indexes[1] != indexes[0] + 1:
            raise ValueError("editor_seam_pages_not_adjacent")
        for key in ("sealId", "sealFileId", "sealFileSha256"):
            if left["properties"].get(key) != right["properties"].get(key):
                raise ValueError("editor_seam_seal_mismatch")
        for key in ("width", "height", "opacity"):
            if not math.isclose(float(left.get(key, 1)), float(right.get(key, 1)), abs_tol=0.0001):
                raise ValueError("editor_seam_seal_mismatch")
        tops = []
        for item in members:
            page = next((page for page in state.get("pages", []) if page.get("pageId") == item.get("pageId")), None)
            if not page:
                raise ValueError("editor_seam_group_incomplete")
            x, y, size = float(item["x"]), float(item["y"]), float(item["width"])
            if not math.isclose(size, float(item["height"]), abs_tol=0.0001):
                raise ValueError("editor_seam_seal_mismatch")
            width, height, rotation = float(page["widthPt"]), float(page["heightPt"]), int(page.get("rotation") or 0) % 360
            if rotation == 90: edge, top, display_width = y, x, height
            elif rotation == 180: edge, top, display_width = width - x - size, y, width
            elif rotation == 270: edge, top, display_width = height - y - size, width - x - size, height
            else: edge, top, display_width = x, height - y - size, width
            expected = display_width - size if item["properties"]["seamPartIndex"] == 0 else 0
            if not math.isclose(edge, expected, abs_tol=0.001):
                raise ValueError("editor_seam_position_mismatch")
            tops.append(top)
        if not math.isclose(tops[0], tops[1], abs_tol=0.001):
            raise ValueError("editor_seam_position_mismatch")
    return groups


def split_seal_raster(data: bytes, part_index: int, page_rotation: int = 0) -> bytes:
    """Keep calibrated full-canvas size; place each unscaled half at its seam edge."""
    from PIL import Image

    if type(part_index) is not int or part_index not in (0, 1):
        raise ValueError("editor_seam_group_invalid")
    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGBA")
        width, height = image.size
        if width < 2:
            raise ValueError("editor_seam_image_invalid")
        midpoint = width // 2
        output = Image.new("RGBA", image.size, (0, 0, 0, 0))
        if part_index == 0:
            output.paste(image.crop((0, 0, midpoint, height)), (width - midpoint, 0))
        else:
            output.paste(image.crop((midpoint, 0, width, height)), (0, 0))
        if page_rotation % 360:
            output = output.rotate(page_rotation % 360, expand=True)
        stream = io.BytesIO()
        output.save(stream, format="PNG")
        return stream.getvalue()


def seam_element_for_position(state: dict, position: dict) -> dict | None:
    """Resolve only immutable-manifest metadata, never caller-supplied crop values."""
    seals = sorted([item for item in state.get("elements") or [] if item.get("kind") == "seal"], key=lambda item: int(item.get("zIndex") or 0))
    index = int(position.get("order_index") or 0) - 1
    if index < 0 or index >= len(seals):
        if any((item.get("properties") or {}).get("seamGroupId") for item in seals):
            raise ValueError("editor_seam_position_mismatch")
        return None
    element = seals[index]
    props = element.get("properties") or {}
    if not props.get("seamGroupId"):
        return None
    if element.get("pageId") != position.get("page_ref") or props.get("sealFileId") != position.get("locked_seal_file_id") or props.get("sealFileSha256") != position.get("locked_seal_sha256"):
        raise ValueError("editor_seam_position_mismatch")
    for key in ("x", "y", "width", "height", "rotation", "opacity"):
        default = 1 if key == "opacity" else 0
        if not math.isclose(float(element.get(key, default)), float(position.get(key, default)), abs_tol=0.001):
            raise ValueError("editor_seam_position_mismatch")
    return element


def validate_seam_positions(state: dict, positions: list[dict]) -> None:
    """A locked seam must output both halves exactly once, never a partial pair."""
    seals = sorted([item for item in state.get("elements") or [] if item.get("kind") == "seal"], key=lambda item: int(item.get("zIndex") or 0))
    if not any((item.get("properties") or {}).get("seamGroupId") for item in seals):
        return
    indexes = [int(position.get("order_index") or 0) for position in positions]
    if sorted(indexes) != list(range(1, len(seals) + 1)):
        raise ValueError("editor_seam_position_mismatch")
    for position in positions:
        seam_element_for_position(state, position)
