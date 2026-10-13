"""Validated split seal groups. Original Seal Vault bytes are never changed."""
from __future__ import annotations

import io
import math
import re


SEAM_EDGES = frozenset({"left", "right", "top", "bottom"})


def _seam_description(element: dict) -> tuple[str, int, int, str]:
    props = element.get("properties") or {}
    mode, count, index = props.get("seamMode"), props.get("seamPartCount"), props.get("seamPartIndex")
    if type(count) is not int or type(index) is not int:
        raise ValueError("editor_seam_group_invalid")
    if mode == "pair":
        if count != 2 or index not in (0, 1) or props.get("seamEdge") not in (None, "pair"):
            raise ValueError("editor_seam_group_invalid")
        return mode, count, index, "right" if index == 0 else "left"
    if mode != "grouped" or count not in range(1, 6) or index not in range(count) or not isinstance(props.get("seamEdge"), str) or props["seamEdge"] not in SEAM_EDGES:
        raise ValueError("editor_seam_group_invalid")
    return mode, count, index, props["seamEdge"]


def _display_geometry(page: dict, item: dict) -> tuple[float, float, float, float, float, float]:
    width, height = float(page["widthPt"]), float(page["heightPt"])
    x, y, w, h = (float(item[key]) for key in ("x", "y", "width", "height"))
    rotation = int(page.get("rotation") or 0) % 360
    if rotation == 90:
        return y, x, h, w, height, width
    if rotation == 180:
        return width - x - w, y, w, h, width, height
    if rotation == 270:
        return height - y - h, width - x - w, h, w, height, width
    return x, height - y - h, w, h, width, height


def require_grouped_company_seal(element: dict, seal: dict) -> None:
    """New batch seams use the classified owner's own primary large seal only.

    Existing pair manifests remain valid; no physical seal is reclassified as a
    continuous seal. The caller supplies the server-attested owner profile,
    never a classification from editable element properties.
    """
    if (element.get("properties") or {}).get("seamMode") != "grouped":
        return
    owner = seal.get("owner_kind")
    primary = "establishment_seal" if owner == "company" else "official_seal" if owner == "institution" else None
    if not primary or seal.get("seal_category") != primary or seal.get("seal_size_type") != "large_seal":
        raise ValueError("editor_seam_company_large_seal_required")


def validate_seam_groups(state: dict) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for element in state.get("elements") or []:
        props = element.get("properties") or {}
        group_id = props.get("seamGroupId")
        if not group_id:
            if any(key in props for key in ("seamPartIndex", "seamPartCount", "seamMode", "seamEdge")):
                raise ValueError("editor_seam_group_invalid")
            continue
        if element.get("kind") != "seal" or not isinstance(group_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", group_id):
            raise ValueError("editor_seam_group_invalid")
        _seam_description(element)
        if float(element.get("rotation") or 0) % 360 != 0:
            raise ValueError("editor_seam_rotation_locked")
        groups.setdefault(group_id, []).append(element)
    for members in groups.values():
        mode, count, _, edge = _seam_description(members[0])
        if len(members) != count or {item["properties"]["seamPartIndex"] for item in members} != set(range(count)) or len({item.get("pageId") for item in members}) != count:
            raise ValueError("editor_seam_group_incomplete")
        first = members[0]
        ordered_members = sorted(members, key=lambda item: item["properties"]["seamPartIndex"])
        indexes = [next((i for i, page in enumerate(state.get("pages", [])) if page.get("pageId") == item.get("pageId")), -1) for item in ordered_members]
        if indexes[0] < 0 or indexes != list(range(indexes[0], indexes[0] + count)):
            raise ValueError("editor_seam_pages_not_adjacent")
        offsets = []
        for item in members:
            item_mode, item_count, _, item_edge = _seam_description(item)
            if item_mode != mode or item_count != count or (mode == "grouped" and item_edge != edge):
                raise ValueError("editor_seam_seal_mismatch")
            for key in ("sealId", "sealFileId", "sealFileSha256"):
                if first["properties"].get(key) != item["properties"].get(key):
                    raise ValueError("editor_seam_seal_mismatch")
            for key in ("width", "height", "opacity"):
                if not math.isclose(float(first.get(key, 1)), float(item.get(key, 1)), abs_tol=0.0001):
                    raise ValueError("editor_seam_seal_mismatch")
            page = next((page for page in state.get("pages", []) if page.get("pageId") == item.get("pageId")), None)
            if not page:
                raise ValueError("editor_seam_group_incomplete")
            if mode == "pair" and not math.isclose(float(item["width"]), float(item["height"]), abs_tol=0.0001):
                raise ValueError("editor_seam_seal_mismatch")
            left, top, w, h, display_width, display_height = _display_geometry(page, item)
            horizontal = item_edge in {"top", "bottom"}
            actual = top if horizontal else left
            expected = 0 if item_edge in {"left", "top"} else display_height - h if horizontal else display_width - w
            offset = left if horizontal else top
            limit = display_width - w if horizontal else display_height - h
            if not all(math.isfinite(value) for value in (actual, expected, offset, limit)) or offset < -0.001 or offset > limit + 0.001 or not math.isclose(actual, expected, abs_tol=0.001):
                raise ValueError("editor_seam_position_mismatch")
            offsets.append(offset)
        if any(not math.isclose(offsets[0], offset, abs_tol=0.001) for offset in offsets[1:]):
            raise ValueError("editor_seam_position_mismatch")
    return groups


def split_seal_raster(data: bytes, part_index: int, page_rotation: int = 0, *, part_count: int = 2, edge: str = "pair") -> bytes:
    """Keep the calibrated full canvas and move one unscaled strip to its edge.

    Integer boundaries cover every original pixel exactly once, even for image
    dimensions not divisible by the group size. Legacy pair edges are retained.
    """
    from PIL import Image

    if type(part_count) is not int or type(part_index) is not int or part_count not in range(1, 6) or part_index not in range(part_count) or not isinstance(edge, str) or edge not in SEAM_EDGES | {"pair"} or (edge == "pair" and part_count != 2):
        raise ValueError("editor_seam_group_invalid")
    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGBA")
        # New batch groups follow the PDF's displayed orientation. Rotate only
        # by quarter-turn pixel permutations before slicing, then return the
        # unchanged physical canvas axes for insertion. This prevents squeezing
        # a rectangular original into a swapped width/height box on /Rotate=90.
        rotation = page_rotation % 360
        if rotation not in (0, 90, 180, 270):
            raise ValueError("editor_seam_group_invalid")
        if edge != "pair" and rotation:
            image = image.rotate(-rotation, expand=True)
        width, height = image.size
        horizontal = edge in {"top", "bottom"}
        extent = height if horizontal else width
        if extent < part_count:
            raise ValueError("editor_seam_image_invalid")
        start, end = extent * part_index // part_count, extent * (part_index + 1) // part_count
        output = Image.new("RGBA", image.size, (0, 0, 0, 0))
        far_edge = edge in {"right", "bottom"} or (edge == "pair" and part_index == 0)
        target = extent - (end - start) if far_edge else 0
        if horizontal:
            output.paste(image.crop((0, start, width, end)), (0, target))
        else:
            output.paste(image.crop((start, 0, end, height)), (target, 0))
        if rotation:
            output = output.rotate(rotation, expand=True)
        stream = io.BytesIO()
        output.save(stream, format="PNG")
        return stream.getvalue()


def seam_element_for_position(state: dict, position: dict) -> dict | None:
    """Resolve only immutable-manifest metadata, never caller-supplied crop values."""
    seals = sorted([item for item in state.get("elements") or [] if item.get("kind") == "seal"], key=lambda item: int(item.get("zIndex") or 0))
    order_index = position.get("order_index")
    if any((item.get("properties") or {}).get("seamGroupId") for item in seals) and type(order_index) is not int:
        raise ValueError("editor_seam_position_mismatch")
    index = int(order_index or 0) - 1
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
    """A locked seam must output all bound strips exactly once, never partly."""
    seals = sorted([item for item in state.get("elements") or [] if item.get("kind") == "seal"], key=lambda item: int(item.get("zIndex") or 0))
    if not any((item.get("properties") or {}).get("seamGroupId") for item in seals):
        return
    if any(type(position.get("order_index")) is not int for position in positions):
        raise ValueError("editor_seam_position_mismatch")
    indexes = [position["order_index"] for position in positions]
    if sorted(indexes) != list(range(1, len(seals) + 1)):
        raise ValueError("editor_seam_position_mismatch")
    for position in positions:
        seam_element_for_position(state, position)
