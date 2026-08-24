"""Isolated ClamAV scanning with Vercel Sandbox.

The uploaded bytes are written only after the sandbox egress policy has been
changed to deny-all.  Each call creates a non-persistent microVM from a pinned
snapshot and destroys it on exit.  This module deliberately returns only a
small status/signature result; document names and document contents are never
used as sandbox metadata or log fields.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any


PROVIDER_ID = "vercel-sandbox-clamav-v1"
SCAN_PATH = "/tmp/edoc-upload.bin"
CLAMAV_UPDATE_DOMAIN = "database.clamav.net"
_SNAPSHOT_ID_RE = re.compile(r"^snap_[A-Za-z0-9]{16,128}$")
_SAFE_SIGNATURE_RE = re.compile(r"[^A-Za-z0-9._-]")


class SandboxAntivirusError(RuntimeError):
    """Base error whose message is safe to expose as an internal error code."""


class SandboxAntivirusNotReady(SandboxAntivirusError):
    pass


class SandboxAntivirusScanFailed(SandboxAntivirusError):
    pass


@dataclass(frozen=True)
class SandboxScanResult:
    status: str
    signature: str
    sha256: str
    size_bytes: int
    engine: str = "ClamAV"
    provider: str = PROVIDER_ID


def _load_sdk() -> Any:
    try:
        from vercel.sandbox import (  # type: ignore[import-not-found]
            NetworkPolicy,
            NetworkPolicyRule,
            SandboxResources,
            SnapshotSource,
            sync,
        )
    except (ImportError, ModuleNotFoundError) as exc:
        raise SandboxAntivirusNotReady("vercel_sandbox_sdk_missing") from exc
    return type(
        "SandboxSdk",
        (),
        {
            "NetworkPolicy": NetworkPolicy,
            "NetworkPolicyRule": NetworkPolicyRule,
            "SandboxResources": SandboxResources,
            "SnapshotSource": SnapshotSource,
            "create_sandbox": staticmethod(sync.create_sandbox),
        },
    )


def _safe_signature(value: str) -> str:
    return _SAFE_SIGNATURE_RE.sub("-", value.strip())[:120] or "Malware-Found"


def _parse_clamscan_result(returncode: int, stdout: str | None) -> tuple[str, str]:
    output = str(stdout or "").strip()
    if returncode == 0:
        # With --infected --no-summary a clean scan intentionally has no
        # stdout.  Any other return code is handled fail-closed below.
        return "clean", "ClamAV-Clean"
    if returncode == 1:
        match = re.search(r":\s*(.+?)\s+FOUND(?:\r?\n)?$", output)
        if match:
            return "infected", _safe_signature(match.group(1))
    raise SandboxAntivirusScanFailed("vercel_sandbox_clamav_failed")


def scan_bytes(
    data: bytes,
    *,
    snapshot_id: str,
    project_id: str = "",
    expected_sha256: str = "",
    timeout_seconds: int = 120,
    max_file_size_bytes: int = 100 * 1024 * 1024,
) -> SandboxScanResult:
    """Scan bytes in a fresh, no-egress microVM and return a strict result.

    The ClamAV database is refreshed while the VM can reach only the official
    database hostname.  Egress is then changed to deny-all before document
    bytes are written.  A failed update, hash mismatch, timeout, SDK error, or
    unexpected clamscan response fails closed.
    """

    if not isinstance(data, bytes) or not data:
        raise SandboxAntivirusScanFailed("vercel_sandbox_invalid_payload")
    if len(data) > max(1, int(max_file_size_bytes)):
        raise SandboxAntivirusScanFailed("vercel_sandbox_payload_too_large")
    if not _SNAPSHOT_ID_RE.fullmatch(str(snapshot_id or "")):
        raise SandboxAntivirusNotReady("vercel_sandbox_snapshot_invalid")

    digest = hashlib.sha256(data).hexdigest()
    requested_digest = str(expected_sha256 or digest).strip().lower()
    if not re.fullmatch(r"[a-f0-9]{64}", requested_digest) or requested_digest != digest:
        raise SandboxAntivirusScanFailed("vercel_sandbox_hash_mismatch")

    sdk = _load_sdk()
    timeout = max(30, min(300, int(timeout_seconds)))
    create_kwargs: dict[str, Any] = {
        "source": sdk.SnapshotSource(snapshot_id=snapshot_id),
        "execution_time_limit": timeout,
        "resources": sdk.SandboxResources(vcpus=2),
        "persistent": False,
        "network_policy": sdk.NetworkPolicy.custom(
            {CLAMAV_UPDATE_DOMAIN: (sdk.NetworkPolicyRule(),)}
        ),
        "tags": {"purpose": "edoc-antivirus", "contract": PROVIDER_ID},
        "destroy": True,
    }
    if str(project_id or "").strip():
        create_kwargs["project_id"] = str(project_id).strip()

    try:
        with sdk.create_sandbox(**create_kwargs) as sandbox:
            update = sandbox.run_process(
                "freshclam",
                ["--stdout", "--no-warnings"],
                sudo=True,
                kill_after=min(45, timeout - 10),
                capture_output=True,
            )
            if int(update.returncode) != 0:
                raise SandboxAntivirusScanFailed("vercel_sandbox_definitions_update_failed")

            # The user file must never coexist with outbound network access.
            sandbox.update_network_policy(sdk.NetworkPolicy.deny_all())
            sandbox.fs.write_bytes(SCAN_PATH, data, mode=0o600)

            verified = sandbox.run_process(
                "sha256sum",
                [SCAN_PATH],
                kill_after=15,
                capture_output=True,
            )
            remote_digest = str(verified.stdout or "").split(None, 1)[0].lower()
            if int(verified.returncode) != 0 or remote_digest != digest:
                raise SandboxAntivirusScanFailed("vercel_sandbox_remote_hash_mismatch")

            scan = sandbox.run_process(
                "clamscan",
                [
                    "--infected",
                    "--no-summary",
                    "--stdout",
                    "--alert-exceeds-max=yes",
                    "--max-filesize=100M",
                    "--max-scansize=300M",
                    "--max-files=10000",
                    "--max-recursion=16",
                    SCAN_PATH,
                ],
                kill_after=max(20, timeout - 20),
                capture_output=True,
            )
            status, signature = _parse_clamscan_result(int(scan.returncode), scan.stdout)
            try:
                sandbox.fs.remove(SCAN_PATH)
            except Exception:
                # The context manager still destroys the non-persistent VM.
                pass
    except (SandboxAntivirusError, KeyboardInterrupt):
        raise
    except Exception as exc:
        raise SandboxAntivirusScanFailed("vercel_sandbox_scan_failed") from exc

    return SandboxScanResult(
        status=status,
        signature=signature,
        sha256=digest,
        size_bytes=len(data),
    )

