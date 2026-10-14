"""Validate deidentified latency evidence without treating fixtures as live proof.

Each declared device/network profile is assessed independently. Failed samples
are retained in the denominator; cold starts are never mixed into warm SLOs.
This offline tool cannot attest that a physical-device claim is genuine.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re

SHA = re.compile(r"[a-f0-9]{40}\Z")
ID = re.compile(r"[A-Z]-[0-9]{3,8}\Z")
DEVICES = {"desktop", "tablet", "phone"}
NETWORKS = {"office_wifi", "mobile_5g", "weak_network", "loopback"}
METRICS = {"workspace_interactive", "pdf_editable", "cloud_saved"}
PROFILES = {"workspace", "typical_a4", "large_pdf", "non_a4"}
FORBIDDEN = re.compile(r"https?://|Bearer\s|(?:vcp_|sb_secret_|sk-proj-)|@|-----BEGIN", re.I)


class EvidenceInvalid(ValueError):
    """Fixed diagnostic codes only."""


def shape(value, keys, code):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise EvidenceInvalid(code)
    return value


def instant(value):
    if not isinstance(value, str):
        raise EvidenceInvalid("sample_time_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise EvidenceInvalid("sample_time_invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceInvalid("sample_timezone_required")
    return parsed.astimezone(timezone.utc)


def finite(value, *, maximum=3600000):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum:
        raise EvidenceInvalid("duration_invalid")
    return value


def assess(record, *, expected_candidate, now=None):
    now = now or datetime.now(timezone.utc)
    if FORBIDDEN.search(json.dumps(record, ensure_ascii=False, allow_nan=False)):
        raise EvidenceInvalid("sensitive_or_connection_data_forbidden")
    shape(record, {"schema_version", "candidate_commit", "environment", "government_exchange", "profiles", "samples"}, "record_schema_invalid")
    if (type(record["schema_version"]) is not int or record["schema_version"] != 1
            or not SHA.fullmatch(expected_candidate or "") or record["candidate_commit"] != expected_candidate):
        raise EvidenceInvalid("candidate_binding_invalid")
    if record["government_exchange"] != "DISABLED":
        raise EvidenceInvalid("government_exchange_must_remain_disabled")
    environment = record["environment"]
    if environment not in {"local_isolated", "hosted_test", "production_readonly"}:
        raise EvidenceInvalid("environment_invalid")
    declared = record["profiles"]
    if not isinstance(declared, list) or not 1 <= len(declared) <= 30:
        raise EvidenceInvalid("profiles_invalid")
    profiles = {}
    for row in declared:
        shape(row, {"id", "device", "network", "physical_device"}, "profile_schema_invalid")
        if (not isinstance(row["id"], str) or not ID.fullmatch(row["id"]) or row["id"] in profiles
                or row["device"] not in DEVICES or row["network"] not in NETWORKS
                or type(row["physical_device"]) is not bool):
            raise EvidenceInvalid("profile_invalid")
        if environment != "local_isolated" and row["network"] == "loopback":
            raise EvidenceInvalid("loopback_is_not_hosted_measurement")
        profiles[row["id"]] = row
    rows = record["samples"]
    if not isinstance(rows, list) or len(rows) > 50000:
        raise EvidenceInvalid("samples_invalid")
    seen, grouped, other = set(), {}, []
    for row in rows:
        shape(row, {"id", "profile_id", "metric", "document_profile", "cache_state", "duration_ms", "outcome", "bytes", "pages", "recorded_at"}, "sample_schema_invalid")
        if (not isinstance(row["id"], str) or not ID.fullmatch(row["id"]) or row["id"] in seen
                or row["profile_id"] not in profiles or row["metric"] not in METRICS
                or row["document_profile"] not in PROFILES or row["cache_state"] not in {"warm", "cold"}
                or row["outcome"] not in {"success", "error", "timeout", "cancelled"}):
            raise EvidenceInvalid("sample_identity_or_scope_invalid")
        seen.add(row["id"])
        finite(row["duration_ms"])
        if any(type(row[key]) is not int or not 0 <= row[key] <= limit for key, limit in (("bytes", 50*1024*1024), ("pages", 300))):
            raise EvidenceInvalid("file_profile_invalid")
        if row["document_profile"] == "typical_a4" and (not 0 < row["bytes"] <= 5*1024*1024 or not 1 <= row["pages"] <= 10):
            raise EvidenceInvalid("typical_a4_profile_invalid")
        if instant(row["recorded_at"]) > now:
            raise EvidenceInvalid("future_sample_invalid")
        key = (row["profile_id"], row["metric"], row["document_profile"], row["cache_state"])
        grouped.setdefault(key, []).append(row)
    required = (("workspace_interactive", "workspace", "warm", 500), ("pdf_editable", "typical_a4", "warm", 2000))
    results = []
    for profile_id, profile in profiles.items():
        for metric, document, cache, target in required:
            samples = grouped.pop((profile_id, metric, document, cache), [])
            values = sorted(row["duration_ms"] for row in samples)
            p95 = values[math.ceil(len(values)*.95)-1] if values else None
            failures = sum(row["outcome"] != "success" for row in samples)
            results.append({"profile_id": profile_id, "device": profile["device"], "network": profile["network"], "metric": metric,
                            "samples": len(values), "failed_samples": failures, "p95_ms": p95, "target_ms": target,
                            "passed": len(values) >= 30 and failures == 0 and p95 <= target})
    for key, samples in grouped.items():
        values = sorted(row["duration_ms"] for row in samples)
        other.append({"profile_id": key[0], "metric": key[1], "document_profile": key[2], "cache_state": key[3],
                      "samples": len(values), "failed_samples": sum(row["outcome"] != "success" for row in samples),
                      "p95_ms": values[math.ceil(len(values)*.95)-1]})
    scope_passed = all(row["passed"] for row in results)
    physical = ({row["device"] for row in profiles.values() if row["physical_device"]} == DEVICES
                and all(row["physical_device"] for row in profiles.values()))
    accepted = scope_passed and physical and environment != "local_isolated"
    return {"schema_valid": True, "candidate_commit": expected_candidate, "environment": environment,
            "profile_results": results, "separate_observations": other, "scope_slo_passed": scope_passed,
            "hosted_physical_evidence_ready_for_review": accepted, "physical_claim_independently_verified": False,
            "promotion_authorized": False, "government_exchange": "DISABLED"}


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceInvalid("duplicate_json_key")
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--candidate-commit", required=True)
    args = parser.parse_args(argv)
    try:
        if args.record.is_symlink() or not args.record.is_file() or args.record.stat().st_size > 20*1024*1024:
            raise EvidenceInvalid("record_file_invalid")
        report = assess(json.loads(args.record.read_text(), object_pairs_hook=unique_keys), expected_candidate=args.candidate_commit)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0 if report["hosted_physical_evidence_ready_for_review"] else 2
    except (EvidenceInvalid, OSError, UnicodeError, ValueError, TypeError, OverflowError):
        print(json.dumps({"schema_valid": False, "error_code": "invalid_latency_evidence", "promotion_authorized": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
