"""Exercise native120 in the shipping localhost browser with synthetic pixels.

Only a disposable fixture registry is patched in memory. No genuine stamp,
employee login, hosted database, government provider or deployment is touched.
The original-source hashes are verified separately by registry unit tests.
"""
import argparse
import base64
import hashlib
import io
from pathlib import Path
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend
import seal_scan_20261013 as scan
from PIL import Image, ImageDraw
from tools import verify_grouped_seam_browser as existing


def run(output: Path, owner_kind: str) -> dict:
    patchers = []

    def prepare(kind: str) -> dict:
        category = "establishment_seal" if kind == "company" else "official_seal"
        image = Image.new("RGBA", (125, 124), (255, 255, 255, 0))
        draw = ImageDraw.Draw(image)
        for index in range(5):
            draw.rectangle((index * 25 + 1, 1, index * 25 + 23, 122), outline=(180, index * 20, 0, 255), width=2)
        stream = io.BytesIO(); image.save(stream, "PNG"); data = stream.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        with backend.connect() as conn:
            backend.patch_company_seal_policy(conn, "CO-001", {"owner_kind": kind})
            record = conn.execute("select id from company_seals where company_id='CO-001' and seal_category=? and seal_size_type='large_seal' order by id limit 1", (category,)).fetchone()
            seal_id = record["id"] if record else backend.create_company_seal(conn, "CO-001", {"seal_name": "Synthetic native120 primary", "seal_category": category, "seal_size_type": "large_seal"})["id"]
            patch = mock.patch.object(scan, "_ROWS", ((digest, "CO-001", seal_id, category, "large_seal", 125, 124, 26.458, 26.247, 1),))
            patch.start(); patchers.append(patch)
            backend.upload_company_seal_file(conn, seal_id, {"file_name": "synthetic-native120-not-a-real-stamp.png", "file_mime_type": "image/png",
                "content_base64": base64.b64encode(data).decode(), "render_width_mm": 26.458, "render_height_mm": 26.247})
            current = backend.require_current_company_seal_file(conn, seal_id)
            if current["dimension_policy_version"] != scan.POLICY:
                raise AssertionError("native120_fixture_policy_not_persisted")
            conn.commit()
            return {"id": seal_id, "file_id": current["id"], "sha256": current["file_hash"],
                    "width_mm": 26.458, "height_mm": 26.247, "category": category, "owner_kind": kind,
                    "dimension_policy_version": scan.POLICY, "synthetic_only": True}

    try:
        with mock.patch.object(existing, "prepare_company_seal", side_effect=prepare):
            return existing.run(output, owner_kind)
    finally:
        for patch in reversed(patchers):
            patch.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--owner-kind", choices=("company", "institution"), required=True)
    args = parser.parse_args()
    raise SystemExit(0 if run(args.output, args.owner_kind)["passed"] else 1)
