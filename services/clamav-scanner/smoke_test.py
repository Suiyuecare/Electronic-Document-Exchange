#!/usr/bin/env python3
"""Run safe clean/EICAR checks against a deployed eDoc AV gateway."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.request


def signature(secret: bytes, message: bytes) -> str:
    return "v1=" + hmac.new(secret, message, hashlib.sha256).hexdigest()


def scan(endpoint: str, secret: bytes, data: bytes) -> str:
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(24)
    digest = hashlib.sha256(data).hexdigest()
    body_digest = hashlib.sha256(data).hexdigest()
    request_signature = signature(
        secret,
        f"v1\n{timestamp}\n{nonce}\n{body_digest}".encode("ascii"),
    )
    request = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Content-Type": "application/octet-stream",
            "Cache-Control": "no-store",
            "X-EDOC-AV-Timestamp": timestamp,
            "X-EDOC-AV-Nonce": nonce,
            "X-EDOC-AV-Body-SHA256": body_digest,
            "X-EDOC-AV-Content-SHA256": digest,
            "X-EDOC-AV-Content-Length": str(len(data)),
            "X-EDOC-AV-Signature": request_signature,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        raw = response.read(16 * 1024)
        response_timestamp = response.headers.get("X-EDOC-AV-Response-Timestamp", "")
        response_signature = response.headers.get("X-EDOC-AV-Response-Signature", "")
    expected = signature(
        secret,
        f"v1-response\n{response_timestamp}\n{nonce}\n{hashlib.sha256(raw).hexdigest()}".encode("ascii"),
    )
    if not hmac.compare_digest(response_signature, expected):
        raise RuntimeError("AV response signature validation failed")
    result = json.loads(raw)
    if result.get("sha256") != digest or result.get("sizeBytes") != len(data):
        raise RuntimeError("AV response integrity validation failed")
    return str(result.get("status") or "")


def main() -> None:
    endpoint = os.getenv("EDOC_AV_ENDPOINT", "").strip()
    secret = os.getenv("EDOC_AV_API_KEY", "").encode("utf-8")
    if not endpoint.startswith("https://") or len(secret) < 32:
        raise SystemExit("Set EDOC_AV_ENDPOINT and a 32+ byte EDOC_AV_API_KEY")
    clean = scan(endpoint, secret, b"%PDF-1.4\n% safe eDoc antivirus smoke fixture\n%%EOF")
    eicar = scan(
        endpoint,
        secret,
        b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*",
    )
    if clean != "clean" or eicar != "infected":
        raise SystemExit("AV smoke result mismatch")
    print("clean=passed eicar=quarantined response_hmac=passed")


if __name__ == "__main__":
    main()
