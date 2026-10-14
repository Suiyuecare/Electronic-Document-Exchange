"""Combine human, per-profile latency and continuous DR evidence fail-closed.

All reports remain bookkeeping for independent review, not deployment
authority. Neither a fast loopback fixture nor seven daily backup labels can
complete this record. No network, login impersonation, or writes occur.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import readiness_acceptance, service_level_acceptance, backup_continuity_acceptance


def assess(checklist, latency, continuity, *, candidate, source_project_ref_sha256,
           evidence_root, backup_evidence_root, now=None):
    # Validate here, not only in a child CLI. All in-process/combined entry
    # points must enforce the same private-root and no-link boundaries.
    backup_continuity_acceptance.validate_private_root(evidence_root)
    backup_continuity_acceptance.validate_private_root(backup_evidence_root)
    if isinstance(checklist, dict) and isinstance(checklist.get("evidence"), list):
        for row in checklist["evidence"]:
            if isinstance(row, dict) and isinstance(row.get("path"), str):
                backup_continuity_acceptance.private_bytes(evidence_root, row["path"])
    human = readiness_acceptance.validate(checklist, expected_candidate=candidate, evidence_root=evidence_root, now=now)
    speed = service_level_acceptance.assess(latency, expected_candidate=candidate, now=now)
    recovery = backup_continuity_acceptance.assess(continuity, expected_candidate=candidate,
                expected_source_project_hash=source_project_ref_sha256, evidence_root=backup_evidence_root, now=now)
    checks = {
        "six_independent_acceptance_gates": human["checklist_complete"] is True,
        "hosted_physical_latency_per_profile": speed["hosted_physical_evidence_ready_for_review"] is True,
        "seven_days_continuous_private_offsite_recovery": recovery["operator_evidence_ready_for_review"] is True,
    }
    ready = all(checks.values())
    return {"candidate_commit": candidate, "record_checks": checks,
            "status": "READY_FOR_INDEPENDENT_REVIEW" if ready else "PENDING_OR_FAILED_ACCEPTANCE",
            "independent_human_oauth_verified": False, "independent_physical_measurements_verified": False,
            "independent_offsite_permissions_and_custody_verified": False,
            "government_exchange": "DISABLED", "promotion_authorized": False}


def read_record(path, maximum):
    content, _ = backup_continuity_acceptance.private_bytes(path.parent, path.name, maximum=maximum)
    return json.loads(content, object_pairs_hook=readiness_acceptance._unique_pairs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--source-project-ref-sha256", required=True)
    parser.add_argument("--checklist", type=Path, required=True)
    parser.add_argument("--latency-record", type=Path, required=True)
    parser.add_argument("--continuity-record", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--backup-evidence-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = assess(read_record(args.checklist, 1024*1024), read_record(args.latency_record, 20*1024*1024),
                        read_record(args.continuity_record, 16*1024*1024), candidate=args.candidate_commit,
                        source_project_ref_sha256=args.source_project_ref_sha256,
                        evidence_root=args.evidence_root, backup_evidence_root=args.backup_evidence_root)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report["status"] == "READY_FOR_INDEPENDENT_REVIEW" else 2
    except (ValueError, OSError, UnicodeError, TypeError, KeyError, OverflowError):
        print(json.dumps({"status": "INVALID_ACCEPTANCE_RECORD", "promotion_authorized": False,
                          "government_exchange": "DISABLED", "secret_values_logged": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
