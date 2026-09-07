#!/usr/bin/env python3
"""De-identified, self-cleaning smoke test for the configured private Storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def verify_owned_object_deleted(backend, object_key: str) -> tuple[bool, int, str]:
    """Require an explicit object-not-found response, not merely any 4xx.

    Storage currently supports both HTTP 404 and legacy HTTP 400 with a
    JSON statusCode of 404. Never treat auth, bucket, or transport failures
    as deletion success. Probe only this smoke test's private object names.
    """
    if not re.fullmatch(r"smoke-tests/storage-cutover-[0-9a-f]{16}\.pdf", object_key):
        raise RuntimeError("storage_cutover_probe_key_forbidden")
    if backend.EDOC_STORAGE_BUCKET == backend.EDOC_SEAL_STORAGE_BUCKET:
        raise RuntimeError("storage_cutover_probe_bucket_forbidden")
    request = urllib.request.Request(
        backend.supabase_storage_object_url(object_key, backend.EDOC_STORAGE_BUCKET),
        headers=backend.supabase_storage_headers(),
        method="GET",
    )
    try:
        with backend._urlopen_no_redirect(request, timeout=20) as response:
            return False, int(response.status), ""
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        raw = backend._consume_http_error(exc)
        try:
            body = json.loads(raw)
        except (ValueError, TypeError):
            return False, status, ""
        if not isinstance(body, dict):
            return False, status, ""
        code = str(body.get("code") or "")
        not_found = (
            status in {400, 404}
            and code == "NoSuchKey"
            and str(body.get("statusCode", status)) == "404"
        )
        # Do not echo arbitrary server messages, object names, or URLs.
        return not_found, status, "NoSuchKey" if code == "NoSuchKey" else ""


def safe_failure_code(exc: Exception) -> str:
    marker = str(exc)
    if re.fullmatch(r"(?:supabase_storage|storage_cutover)_[a-z0-9_]+(?::[0-9]{3})?", marker):
        return marker
    return "storage_cutover_failed"


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
    delete_http_status = 0
    delete_storage_code = ""
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
        delete_verified, delete_http_status, delete_storage_code = verify_owned_object_deleted(backend, object_key)
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
        "deleteHttpStatus": delete_http_status,
        "deleteStorageCode": delete_storage_code,
        "containsSecrets": False,
        "containsPersonalData": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # A signed download error may contain its capability URL. Never let a
        # CLI traceback copy credentials into CI logs or an acceptance report.
        print(json.dumps({"ok": False, "errorCode": safe_failure_code(exc), "containsSecrets": False}))
        sys.exit(1)
