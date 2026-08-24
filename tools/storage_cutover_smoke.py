#!/usr/bin/env python3
"""De-identified, self-cleaning smoke test for the configured private Storage."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    if "--config-stdin" in sys.argv:
        if sys.stdin.isatty():
            import termios

            attributes = termios.tcgetattr(sys.stdin.fileno())
            attributes[3] &= ~termios.ECHO
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, attributes)
        config = json.loads(sys.stdin.readline())
        allowed = {
            "EDOC_STORAGE_PROVIDER",
            "EDOC_STORAGE_SUPABASE_URL",
            "EDOC_STORAGE_SERVICE_ROLE_KEY",
            "EDOC_STORAGE_BUCKET",
            "EDOC_SEAL_STORAGE_BUCKET",
        }
        if set(config) - allowed:
            raise RuntimeError("storage_cutover_config_key_forbidden")
        for key, value in config.items():
            os.environ[key] = str(value)

    import backend

    payload = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )
    object_key = f"smoke-tests/storage-cutover-{secrets.token_hex(8)}.pdf"
    uploaded = False
    deleted = False
    download_matches = False
    delete_verified = False
    signed_origin = ""
    try:
        backend.supabase_storage_upload(
            object_key,
            payload,
            "application/pdf",
            backend.EDOC_STORAGE_BUCKET,
        )
        uploaded = True
        signed = backend.supabase_storage_create_signed_download_url(
            object_key,
            backend.EDOC_STORAGE_BUCKET,
            file_name="storage-cutover-smoke.pdf",
            ttl_seconds=60,
        )
        parsed = urllib.parse.urlparse(signed["url"])
        signed_origin = f"{parsed.scheme}://{parsed.netloc}"
        with urllib.request.urlopen(signed["url"], timeout=20) as response:
            downloaded = response.read()
        download_matches = hashlib.sha256(downloaded).digest() == hashlib.sha256(payload).digest()
        if not download_matches:
            raise RuntimeError("storage_cutover_download_hash_mismatch")
        backend.supabase_storage_delete(object_key, backend.EDOC_STORAGE_BUCKET)
        deleted = True
        try:
            backend.supabase_storage_download(object_key, backend.EDOC_STORAGE_BUCKET)
        except ValueError as exc:
            delete_verified = "404" in str(exc)
        if not delete_verified:
            raise RuntimeError("storage_cutover_delete_not_verified")
    finally:
        if uploaded and not deleted:
            try:
                backend.supabase_storage_delete(object_key, backend.EDOC_STORAGE_BUCKET)
            except Exception:
                pass

    print(json.dumps({
        "ok": uploaded and download_matches and deleted and delete_verified,
        "provider": backend.EDOC_STORAGE_PROVIDER,
        "bucket": backend.EDOC_STORAGE_BUCKET,
        "separateSupabaseProject": not backend.storage_uses_database_supabase_project(),
        "signedOrigin": signed_origin,
        "uploaded": uploaded,
        "downloadHashMatched": download_matches,
        "deleted": deleted,
        "deleteVerified": delete_verified,
        "containsSecrets": False,
        "containsPersonalData": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
