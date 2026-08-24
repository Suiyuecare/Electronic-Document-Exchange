#!/usr/bin/env python3
"""Small authenticated HTTPS-to-clamd gateway for eDoc uploads.

The Cloud Run proxy terminates HTTPS.  This process never logs request bodies,
signed object URLs, file names, hashes, signatures, or secrets.  Requests are
authenticated with a short-lived HMAC envelope before any scan result is
accepted.  Large files are fetched from a short-lived, allow-listed Supabase
Storage URL so the Cloud Run HTTP/1 request never crosses its 32 MiB limit.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import socket
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterable


SCHEMA_VERSION = 1
MAX_CLOCK_SKEW_SECONDS = 60
REPLAY_TTL_SECONDS = 120
NONCE_RE = re.compile(r"^[A-Fa-f0-9]{32,128}$")
SHA256_RE = re.compile(r"^[A-Fa-f0-9]{64}$")
SIGNATURE_RE = re.compile(r"^v1=([A-Fa-f0-9]{64})$")
SAFE_MALWARE_SIGNATURE_RE = re.compile(r"[^A-Za-z0-9._-]")


class ScanContractError(Exception):
    def __init__(self, code: str, status: int = HTTPStatus.BAD_REQUEST):
        super().__init__(code)
        self.code = code
        self.status = int(status)


class ReplayCache:
    def __init__(self) -> None:
        self._items: dict[str, float] = {}
        self._lock = threading.Lock()

    def claim(self, nonce: str, now_value: float | None = None) -> bool:
        current = time.time() if now_value is None else now_value
        with self._lock:
            self._items = {
                key: expires_at
                for key, expires_at in self._items.items()
                if expires_at > current
            }
            if nonce in self._items:
                return False
            self._items[nonce] = current + REPLAY_TTL_SECONDS
            return True


REPLAY_CACHE = ReplayCache()


def required_secret() -> bytes:
    value = os.getenv("EDOC_AV_SHARED_SECRET", "")
    if len(value.encode("utf-8")) < 32:
        raise RuntimeError("EDOC_AV_SHARED_SECRET must contain at least 32 bytes")
    return value.encode("utf-8")


def allowed_source_hosts() -> set[str]:
    return {
        item.strip().lower().rstrip(".")
        for item in os.getenv("EDOC_AV_ALLOWED_SOURCE_HOSTS", "").split(",")
        if item.strip()
    }


def request_signing_message(timestamp: str, nonce: str, body_sha256: str) -> bytes:
    return f"v1\n{timestamp}\n{nonce}\n{body_sha256.lower()}".encode("ascii")


def response_signing_message(timestamp: str, nonce: str, body_sha256: str) -> bytes:
    return f"v1-response\n{timestamp}\n{nonce}\n{body_sha256.lower()}".encode("ascii")


def signature_for(secret: bytes, message: bytes) -> str:
    return "v1=" + hmac.new(secret, message, hashlib.sha256).hexdigest()


def validate_source_url(value: str) -> str:
    parsed = urllib.parse.urlparse(str(value or ""))
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or parsed.fragment
        or (parsed.port not in (None, 443))
        or host not in allowed_source_hosts()
        or not parsed.path.startswith("/storage/v1/object/sign/")
        or not parsed.query
    ):
        raise ScanContractError("source_url_forbidden", HTTPStatus.FORBIDDEN)
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def source_chunks(url: str, expected_size: int, max_size: int) -> Iterable[bytes]:
    request = urllib.request.Request(
        validate_source_url(url),
        headers={"Accept": "application/octet-stream", "Cache-Control": "no-store"},
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            header_size = response.headers.get("Content-Length")
            if header_size:
                actual_header_size = int(header_size)
                if actual_header_size != expected_size or actual_header_size > max_size:
                    raise ScanContractError("source_size_mismatch", HTTPStatus.UNPROCESSABLE_ENTITY)
            remaining = max_size
            while True:
                block = response.read(min(1024 * 1024, remaining + 1))
                if not block:
                    break
                remaining -= len(block)
                if remaining < 0:
                    raise ScanContractError("source_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                yield block
    except ScanContractError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise ScanContractError("source_download_failed", HTTPStatus.BAD_GATEWAY) from exc


def _read_clamd_response(scanner: socket.socket) -> str:
    response = bytearray()
    while len(response) < 4096:
        block = scanner.recv(1024)
        if not block:
            break
        response.extend(block)
        if b"\0" in block or b"\n" in block:
            break
    return bytes(response).split(b"\0", 1)[0].decode("utf-8", "replace").strip()


def scan_chunks(
    chunks: Iterable[bytes],
    *,
    expected_sha256: str,
    expected_size: int,
) -> dict[str, object]:
    if not SHA256_RE.fullmatch(expected_sha256 or ""):
        raise ScanContractError("expected_sha256_invalid")
    max_size = min(60, max(1, int(os.getenv("EDOC_AV_MAX_FILE_SIZE_MB", "50")))) * 1024 * 1024
    if expected_size < 1 or expected_size > max_size:
        raise ScanContractError("expected_size_invalid", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    host = os.getenv("CLAMD_HOST", "127.0.0.1")
    port = int(os.getenv("CLAMD_PORT", "3310"))
    timeout = min(120, max(2, int(os.getenv("CLAMD_TIMEOUT_SECONDS", "60"))))
    digest = hashlib.sha256()
    size = 0
    try:
        with socket.create_connection((host, port), timeout=timeout) as scanner:
            scanner.settimeout(timeout)
            scanner.sendall(b"zINSTREAM\0")
            for chunk in chunks:
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_size:
                    raise ScanContractError("source_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                digest.update(chunk)
                scanner.sendall(struct.pack("!I", len(chunk)))
                scanner.sendall(chunk)
            scanner.sendall(struct.pack("!I", 0))
            clamd_result = _read_clamd_response(scanner)
    except ScanContractError:
        raise
    except (OSError, TimeoutError, ValueError) as exc:
        raise ScanContractError("clamd_unavailable", HTTPStatus.SERVICE_UNAVAILABLE) from exc

    actual_sha256 = digest.hexdigest()
    if size != expected_size or not hmac.compare_digest(actual_sha256, expected_sha256.lower()):
        raise ScanContractError("source_integrity_mismatch", HTTPStatus.UNPROCESSABLE_ENTITY)
    if clamd_result.endswith(" OK") or clamd_result == "OK":
        status = "clean"
        malware_signature = ""
    else:
        found = re.search(r":\s*(.+?)\s+FOUND$", clamd_result)
        if not found:
            raise ScanContractError("clamd_response_invalid", HTTPStatus.SERVICE_UNAVAILABLE)
        status = "infected"
        malware_signature = SAFE_MALWARE_SIGNATURE_RE.sub("-", found.group(1))[:120] or "Malware-Found"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "engine": "ClamAV",
        "signature": malware_signature,
        "sha256": actual_sha256,
        "sizeBytes": size,
        "scannedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def clamd_ping() -> bool:
    try:
        with socket.create_connection(
            (os.getenv("CLAMD_HOST", "127.0.0.1"), int(os.getenv("CLAMD_PORT", "3310"))),
            timeout=2,
        ) as scanner:
            scanner.sendall(b"zPING\0")
            return _read_clamd_response(scanner) == "PONG"
    except (OSError, TimeoutError, ValueError):
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = "eDocAV/1"

    def log_message(self, _format: str, *_args) -> None:
        # Do not emit URLs, query strings, hashes, request headers or file data.
        return

    def _json(self, status: int, payload: dict[str, object], *, nonce: str = "") -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if nonce:
            response_timestamp = str(int(time.time()))
            body_sha256 = hashlib.sha256(body).hexdigest()
            self.send_header("X-EDOC-AV-Response-Timestamp", response_timestamp)
            self.send_header("X-EDOC-AV-Response-Signature", signature_for(
                required_secret(),
                response_signing_message(response_timestamp, nonce, body_sha256),
            ))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if urllib.parse.urlparse(self.path).path != "/healthz":
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "code": "not_found"})
            return
        ready = clamd_ping()
        self._json(
            HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
            {"ok": ready, "status": "ready" if ready else "not_ready", "schemaVersion": SCHEMA_VERSION},
        )

    def do_POST(self) -> None:
        nonce = ""
        try:
            if urllib.parse.urlparse(self.path).path != "/v1/scan":
                raise ScanContractError("not_found", HTTPStatus.NOT_FOUND)
            timestamp = self.headers.get("X-EDOC-AV-Timestamp", "")
            nonce = self.headers.get("X-EDOC-AV-Nonce", "")
            body_sha256 = self.headers.get("X-EDOC-AV-Body-SHA256", "").lower()
            signature = self.headers.get("X-EDOC-AV-Signature", "")
            if not timestamp.isdigit() or abs(int(time.time()) - int(timestamp)) > MAX_CLOCK_SKEW_SECONDS:
                raise ScanContractError("request_expired", HTTPStatus.UNAUTHORIZED)
            if not NONCE_RE.fullmatch(nonce) or not SHA256_RE.fullmatch(body_sha256):
                raise ScanContractError("request_envelope_invalid", HTTPStatus.UNAUTHORIZED)
            match = SIGNATURE_RE.fullmatch(signature)
            if not match:
                raise ScanContractError("request_signature_invalid", HTTPStatus.UNAUTHORIZED)
            content_length = int(self.headers.get("Content-Length", "-1"))
            inline_limit = min(8, max(1, int(os.getenv("EDOC_AV_INLINE_MAX_MB", "4")))) * 1024 * 1024
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            request_limit = inline_limit if content_type == "application/octet-stream" else 64 * 1024
            if content_length < 1 or content_length > request_limit:
                raise ScanContractError("request_size_invalid", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            body = self.rfile.read(content_length)
            actual_body_sha256 = hashlib.sha256(body).hexdigest()
            if not hmac.compare_digest(body_sha256, actual_body_sha256):
                raise ScanContractError("request_body_hash_mismatch", HTTPStatus.UNAUTHORIZED)
            expected_signature = signature_for(
                required_secret(),
                request_signing_message(timestamp, nonce, body_sha256),
            )
            if not hmac.compare_digest(signature, expected_signature):
                raise ScanContractError("request_signature_invalid", HTTPStatus.UNAUTHORIZED)
            if not REPLAY_CACHE.claim(nonce):
                raise ScanContractError("request_replayed", HTTPStatus.CONFLICT)

            expected_sha256 = self.headers.get("X-EDOC-AV-Content-SHA256", "").lower()
            expected_size = int(self.headers.get("X-EDOC-AV-Content-Length", "0"))
            if content_type == "application/octet-stream":
                chunks: Iterable[bytes] = (body,)
            elif content_type == "application/json":
                try:
                    payload = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ScanContractError("request_json_invalid") from exc
                if set(payload) != {"schemaVersion", "sourceUrl", "sha256", "sizeBytes"} or payload.get("schemaVersion") != 1:
                    raise ScanContractError("request_schema_invalid")
                expected_sha256 = str(payload.get("sha256") or "").lower()
                expected_size = int(payload.get("sizeBytes") or 0)
                max_size = min(60, max(1, int(os.getenv("EDOC_AV_MAX_FILE_SIZE_MB", "50")))) * 1024 * 1024
                chunks = source_chunks(str(payload.get("sourceUrl") or ""), expected_size, max_size)
            else:
                raise ScanContractError("request_content_type_invalid", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)

            result = scan_chunks(chunks, expected_sha256=expected_sha256, expected_size=expected_size)
            self._json(HTTPStatus.OK, result, nonce=nonce)
        except ScanContractError as exc:
            self._json(exc.status, {"ok": False, "code": exc.code, "schemaVersion": SCHEMA_VERSION}, nonce=nonce if NONCE_RE.fullmatch(nonce or "") else "")
        except Exception:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "code": "internal_error", "schemaVersion": SCHEMA_VERSION})


def main() -> None:
    required_secret()
    if not allowed_source_hosts():
        raise RuntimeError("EDOC_AV_ALLOWED_SOURCE_HOSTS must contain the exact Supabase Storage host")
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
