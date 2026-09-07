#!/usr/bin/env python3
"""Fail CI on embedded high-confidence private credentials; never print them.

This preventive check does not revoke credentials exposed outside the repo and
does not claim to replace the hosting provider's secret-scanning service.
"""
from pathlib import Path
import re
import subprocess

PATTERNS = {
    "openai_private_key": re.compile(rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}"),
    "supabase_private_key": re.compile(rb"\bsb_secret_[A-Za-z0-9_-]{24,}"),
    "pem_private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
TEXT_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json", ".yml",
                 ".yaml", ".toml", ".ini", ".env", ".sql", ".md", ".txt", ".sh", ".pem", ".key"}


def detect(data: bytes) -> list[str]:
    return sorted(name for name, pattern in PATTERNS.items() if pattern.search(data))


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True)
    findings = []
    for raw_name in result.stdout.split(b"\0"):
        if not raw_name:
            continue
        path = root / raw_name.decode("utf-8")
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix not in TEXT_SUFFIXES and not path.name.startswith(".env"):
            continue
        for kind in detect(path.read_bytes()):
            findings.append({"file": str(path.relative_to(root)), "kind": kind})
    import json
    print(json.dumps({"ok": not findings, "findings": findings, "secretValuesLogged": False}))
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
