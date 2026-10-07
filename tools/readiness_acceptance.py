"""Offline, fail-closed acceptance bookkeeping; never deployment authority.

This validator checks a locally retained, redacted evidence index. It cannot
prove that a person completed OAuth, that a screenshot is genuine, or that a
manual reviewer is trustworthy. Even a complete checklist only becomes ready
for manual review; it never authorizes promotion, migrations or staff changes.
No network, credentials, directory reads or application mutations are used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Any

SCHEMA_VERSION = 1
STATES = frozenset({"PENDING", "PASS", "FAIL"})
GATES = {
    "offboarding_handover": (
        "public_and_shared_database", "independent_confirmation", "live_successor_qualification",
        "completed_evidence_immutable", "stale_and_duplicate_requests", "tenant_boundary",
        "linked_case_full_approval", "signed_and_sent_not_repeated",
    ),
    "human_sso_and_personnel": (
        "personally_operated_google_login", "cross_module_new_tab_reload", "logout_identity_isolation",
        "ordinary_employee_least_privilege", "session_revocation", "new_employee_and_org_change",
    ),
    "performance_and_devices": (
        "separate_readiness_and_cloud_save", "warm_workspace_p95", "a4_editable_p95",
        "large_and_non_a4_results", "physical_desktop_tablet_phone", "weak_network_retry_no_loss",
    ),
    "notifications_and_delivery": (
        "correct_live_recipient", "approval_return_addsign_dispatch", "overdue_only",
        "deduplicated_bounded_retry", "actual_mail_receipt", "delivery_proof_not_read_receipt",
        "failed_delivery_remains_failed", "in_app_task_retained",
    ),
    "backup_and_recovery": (
        "encrypted_offsite_storage_and_database", "key_separation_and_handover", "isolated_restore_integrity",
        "rpo_and_rto", "seven_days_schedule", "interruption_recovery", "failure_and_stale_alert",
    ),
    "operation_documents": (
        "all_five_roles_short_guide", "current_buttons_and_permissions", "no_removed_or_disabled_feature_claim",
        "desktop_tablet_phone_findability",
    ),
}
PARTICIPANT_ROLES = ("employee", "manager", "general_affairs", "administrative_director",
                     "responsible_person", "ordinary_employee")
SSO_CHECKS = ("finance_or_apm_login", "edoc_new_tab", "direct_url", "reload", "logout_switch_isolation",
              "role_journey", "least_privilege")
EVIDENCE_KINDS = frozenset({"manual_observation", "isolated_test_report", "production_readonly_report",
                            "physical_device_measurement", "restore_report", "guide_review"})
PERSON = re.compile(r"P-[0-9]{3,6}\Z")
EVIDENCE = re.compile(r"E-[0-9]{3,6}\Z")
COMMIT = re.compile(r"[a-f0-9]{40}\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")
SENSITIVE = re.compile(
    r"Bearer\s+[A-Za-z0-9._-]+|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|"
    r"(?:vcp_|sb_secret_|sk_live_|sk-proj-)[A-Za-z0-9_-]+|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|https?://|postgres(?:ql)?://",
    re.IGNORECASE,
)


class AcceptanceInvalid(ValueError):
    """Safe diagnostic codes only, never rejected source values."""


def _shape(value: Any, keys: set[str], code: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise AcceptanceInvalid(code)
    return value


def _time(value: Any, code: str) -> datetime:
    if not isinstance(value, str):
        raise AcceptanceInvalid(code)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise AcceptanceInvalid(code) from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise AcceptanceInvalid(code)
    return result.astimezone(timezone.utc)


def _state(value: Any, code: str) -> str:
    if not isinstance(value, str) or value not in STATES:
        raise AcceptanceInvalid(code)
    return value


def _no_sensitive(value: Any) -> None:
    # Reject unexpected free-form payloads containing common credentials,
    # identities or connection URLs. Evidence is redacted before indexing.
    if SENSITIVE.search(json.dumps(value, ensure_ascii=False)):
        raise AcceptanceInvalid("sensitive_or_connection_data_not_allowed")


def template(candidate_commit: str, *, now: datetime | None = None) -> dict:
    if not COMMIT.fullmatch(candidate_commit or ""):
        raise AcceptanceInvalid("candidate_commit_invalid")
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    return {
        "schema_version": SCHEMA_VERSION, "candidate_commit": candidate_commit,
        "created_at": stamp, "not_automatic_release_authority": True,
        "government_exchange": "DISABLED", "evidence": [],
        "gates": {name: {"status": "PENDING", "checks": {key: "PENDING" for key in checks},
                         "evidence_ids": [], "reviewer_id": None, "reviewed_at": None}
                  for name, checks in GATES.items()},
        "human_participants": {role: {"participant_id": None, "finance_role": None,
                                      "role_source": "PENDING", "has_admin_or_companywide_permissions": False,
                                      "status": "PENDING", "personally_operated": False,
                                      "human_google_oauth_observed": False, "synthetic_identity_used": False,
                                      "checks": {key: "PENDING" for key in SSO_CHECKS},
                                      "devices": [], "evidence_ids": [], "reviewer_id": None,
                                      "reviewed_at": None}
                               for role in PARTICIPANT_ROLES},
        "measurements": {"environment": "PENDING", "warm_workspace_ms": [], "a4_editable_ms": [],
                         "rpo_minutes": None, "rto_minutes": None, "backup_success_dates": []},
    }


def _evidence_files(records: Any, root: Path, candidate: str, now: datetime) -> dict:
    if not isinstance(records, list) or len(records) > 200:
        raise AcceptanceInvalid("evidence_inventory_invalid")
    index = {}
    keys = {"id", "path", "sha256", "recorded_at", "retain_until", "redacted", "kind", "candidate_commit"}
    for record in records:
        row = _shape(record, keys, "evidence_schema_invalid")
        identity = row["id"]
        if not isinstance(identity, str) or not EVIDENCE.fullmatch(identity) or identity in index:
            raise AcceptanceInvalid("evidence_identity_invalid")
        if (row["candidate_commit"] != candidate or row["redacted"] is not True
                or not isinstance(row["kind"], str) or row["kind"] not in EVIDENCE_KINDS):
            raise AcceptanceInvalid("evidence_binding_or_redaction_invalid")
        recorded, retained = _time(row["recorded_at"], "evidence_time_invalid"), _time(row["retain_until"], "evidence_retention_invalid")
        if recorded > now or retained <= now or retained <= recorded:
            raise AcceptanceInvalid("evidence_expired_or_future")
        if not isinstance(row["path"], str):
            raise AcceptanceInvalid("evidence_path_invalid")
        path = PurePosixPath(row["path"])
        if (path.is_absolute() or not path.parts or any(part in {"..", "."} for part in path.parts)
                or "\\" in row["path"] or path.suffix.lower() not in {".json", ".txt", ".png", ".jpg"}):
            raise AcceptanceInvalid("evidence_path_invalid")
        target = root
        for component in path.parts:
            target = target / component
            if target.is_symlink():
                raise AcceptanceInvalid("evidence_symlink_forbidden")
        if not target.is_file() or target.stat().st_size > 8 * 1024 * 1024:
            raise AcceptanceInvalid("evidence_missing_or_oversized")
        content = target.read_bytes()
        if not isinstance(row["sha256"], str) or not HASH.fullmatch(row["sha256"]) or hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise AcceptanceInvalid("evidence_hash_mismatch")
        if path.suffix.lower() in {".json", ".txt"}:
            try:
                decoded = content.decode("utf-8")
            except UnicodeError:
                raise AcceptanceInvalid("evidence_text_encoding_invalid") from None
            if SENSITIVE.search(decoded):
                raise AcceptanceInvalid("evidence_contains_sensitive_data")
        index[identity] = row
    return index


def _references(values: Any, index: dict, code: str) -> list[str]:
    if (not isinstance(values, list) or any(not isinstance(v, str) for v in values)
            or len(values) != len(set(values)) or any(v not in index for v in values)):
        raise AcceptanceInvalid(code)
    return values


def _review(row: dict, now: datetime, *, subject: str | None = None) -> None:
    if not isinstance(row["reviewer_id"], str) or not PERSON.fullmatch(row["reviewer_id"]):
        raise AcceptanceInvalid("manual_reviewer_required")
    if subject is not None and row["reviewer_id"] == subject:
        raise AcceptanceInvalid("independent_manual_reviewer_required")
    if _time(row["reviewed_at"], "review_time_invalid") > now:
        raise AcceptanceInvalid("review_in_future")


def _participants(value: Any, index: dict, now: datetime) -> tuple[bool, list[str]]:
    records = _shape(value, set(PARTICIPANT_ROLES), "human_participant_roster_invalid")
    complete, identities = True, []
    keys = {"participant_id", "finance_role", "role_source", "has_admin_or_companywide_permissions",
            "status", "personally_operated", "human_google_oauth_observed",
            "synthetic_identity_used", "checks", "devices", "evidence_ids", "reviewer_id", "reviewed_at"}
    for role, record in records.items():
        row = _shape(record, keys, "human_participant_schema_invalid")
        status = _state(row["status"], "human_participant_status_invalid")
        checks = _shape(row["checks"], set(SSO_CHECKS), "human_participant_checks_invalid")
        for checked in checks.values():
            _state(checked, "human_check_status_invalid")
        refs = _references(row["evidence_ids"], index, "human_evidence_invalid")
        for flag in ("personally_operated", "human_google_oauth_observed", "synthetic_identity_used",
                     "has_admin_or_companywide_permissions"):
            if not isinstance(row[flag], bool):
                raise AcceptanceInvalid("human_observation_flag_invalid")
        if not isinstance(row["devices"], list) or any(device not in {"desktop", "physical_phone", "physical_tablet"} for device in row["devices"]):
            raise AcceptanceInvalid("human_device_invalid")
        if row["participant_id"] is not None:
            if not isinstance(row["participant_id"], str) or not PERSON.fullmatch(row["participant_id"]):
                raise AcceptanceInvalid("participant_pseudonym_invalid")
            identities.append(row["participant_id"])
        if status != "PASS":
            complete = False
            continue
        if (not row["participant_id"] or not isinstance(row["finance_role"], str) or not row["finance_role"]
                or row["role_source"] != "finance_authoritative_read" or not row["personally_operated"]
                or not row["human_google_oauth_observed"] or row["synthetic_identity_used"]
                or any(checked != "PASS" for checked in checks.values())
                or not {"desktop", "physical_phone"}.issubset(row["devices"])
                or not refs or any(index[ref]["kind"] != "manual_observation" for ref in refs)):
            raise AcceptanceInvalid("human_oauth_acceptance_incomplete_not_synthetic")
        if role == "ordinary_employee" and (row["finance_role"] not in {"員工", "職員"}
                                             or row["has_admin_or_companywide_permissions"]):
            raise AcceptanceInvalid("ordinary_employee_must_be_nonprivileged")
        expected_roles = {"manager": {"主管", "主任", "部門主任"}, "general_affairs": {"總務"},
                          "administrative_director": {"行政部主任", "行政部門主任"},
                          "responsible_person": {"執行長", "負責人", "老闆"}}
        if role in expected_roles and row["finance_role"] not in expected_roles[role]:
            raise AcceptanceInvalid("human_directory_role_mismatch")
        _review(row, now, subject=row["participant_id"])
    if len(identities) != len(set(identities)):
        raise AcceptanceInvalid("distinct_human_participants_required")
    return complete, identities


def _numbers(values: Any) -> list[float]:
    if not isinstance(values, list) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values):
        raise AcceptanceInvalid("measurement_samples_invalid")
    return sorted(values)


def _p95(values: list[float]) -> float:
    return values[math.ceil(0.95 * len(values)) - 1]


def validate(checklist: Any, *, expected_candidate: str, evidence_root: Path,
             now: datetime | None = None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    _no_sensitive(checklist)
    top = _shape(checklist, {"schema_version", "candidate_commit", "created_at", "not_automatic_release_authority",
                            "government_exchange", "evidence", "gates", "human_participants", "measurements"}, "checklist_schema_invalid")
    if (not COMMIT.fullmatch(expected_candidate or "") or top["candidate_commit"] != expected_candidate
            or type(top["schema_version"]) is not int or top["schema_version"] != SCHEMA_VERSION):
        raise AcceptanceInvalid("candidate_commit_or_schema_mismatch")
    if top["not_automatic_release_authority"] is not True or top["government_exchange"] != "DISABLED":
        raise AcceptanceInvalid("release_authority_or_government_scope_invalid")
    if _time(top["created_at"], "checklist_time_invalid") > now:
        raise AcceptanceInvalid("checklist_in_future")
    index = _evidence_files(top["evidence"], evidence_root, expected_candidate, now)
    human_complete, _ = _participants(top["human_participants"], index, now)
    gates = _shape(top["gates"], set(GATES), "six_separate_gates_required")
    state = {}
    for name, row in gates.items():
        _shape(row, {"status", "checks", "evidence_ids", "reviewer_id", "reviewed_at"}, "gate_schema_invalid")
        status = _state(row["status"], "gate_status_invalid")
        checks = _shape(row["checks"], set(GATES[name]), "gate_check_coverage_invalid")
        for checked in checks.values():
            _state(checked, "gate_check_status_invalid")
        refs = _references(row["evidence_ids"], index, "gate_evidence_invalid")
        if status == "PASS":
            if any(checked != "PASS" for checked in checks.values()) or not refs:
                raise AcceptanceInvalid("gate_pass_without_complete_evidence")
            _review(row, now)
            if name == "human_sso_and_personnel" and not human_complete:
                raise AcceptanceInvalid("human_sso_roster_incomplete")
            if name == "offboarding_handover" and not human_complete:
                raise AcceptanceInvalid("handover_requires_human_acceptance")
        state[name] = status
    metrics = _shape(top["measurements"], {"environment", "warm_workspace_ms", "a4_editable_ms", "rpo_minutes",
                                          "rto_minutes", "backup_success_dates"}, "measurement_schema_invalid")
    if metrics["environment"] not in {"PENDING", "hosted_test", "production_readonly", "local_isolated"}:
        raise AcceptanceInvalid("measurement_environment_invalid")
    warm, a4 = _numbers(metrics["warm_workspace_ms"]), _numbers(metrics["a4_editable_ms"])
    if state["performance_and_devices"] == "PASS":
        if metrics["environment"] not in {"hosted_test", "production_readonly"} or len(warm) < 20 or len(a4) < 20:
            raise AcceptanceInvalid("hosted_performance_samples_required")
        if _p95(warm) > 500 or _p95(a4) > 2000:
            raise AcceptanceInvalid("performance_target_not_met")
        refs = gates["performance_and_devices"]["evidence_ids"]
        if not any(index[ref]["kind"] == "physical_device_measurement" for ref in refs):
            raise AcceptanceInvalid("physical_device_evidence_required")
    if state["backup_and_recovery"] == "PASS":
        for field, maximum in (("rpo_minutes", 15), ("rto_minutes", 30)):
            number = metrics[field]
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not 0 <= number <= maximum:
                raise AcceptanceInvalid("recovery_target_not_met")
        days = metrics["backup_success_dates"]
        if (not isinstance(days, list) or any(not isinstance(day, str) for day in days)
                or len(days) < 7 or len(days) != len(set(days))):
            raise AcceptanceInvalid("seven_consecutive_backup_days_required")
        try:
            parsed = sorted(datetime.strptime(value, "%Y-%m-%d").date() for value in days)
        except (TypeError, ValueError):
            raise AcceptanceInvalid("backup_dates_invalid") from None
        if parsed[-1] > now.date() or any((right-left).days != 1 for left, right in zip(parsed, parsed[1:])):
            raise AcceptanceInvalid("seven_consecutive_backup_days_required")
        if not any(index[ref]["kind"] == "restore_report" for ref in gates["backup_and_recovery"]["evidence_ids"]):
            raise AcceptanceInvalid("isolated_restore_evidence_required")
    complete = all(value == "PASS" for value in state.values())
    return {"schema_valid": True, "candidate_commit": expected_candidate, "gates": state,
            "checklist_complete": complete, "human_evidence_reviewed": human_complete,
            "status": "READY_FOR_MANUAL_REVIEW" if complete else "PENDING_OR_FAILED_ACCEPTANCE",
            "promotion_authorized": False, "human_oauth_independently_verified": False,
            "government_exchange": "DISABLED", "secret_values_logged": False,
            "limitations": "local_record_validation_is_not_independent_oauth_proof_or_release_authority"}


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AcceptanceInvalid("duplicate_json_key")
        result[key] = value
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-commit", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--template", action="store_true")
    action.add_argument("--checklist", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.template:
            print(json.dumps(template(args.candidate_commit), ensure_ascii=False, indent=2))
            return 0
        if args.evidence_root is None:
            raise AcceptanceInvalid("evidence_root_required")
        if args.checklist.is_symlink() or not args.checklist.is_file() or args.checklist.stat().st_size > 1024*1024:
            raise AcceptanceInvalid("checklist_file_invalid")
        data = json.loads(args.checklist.read_text(), object_pairs_hook=_unique_pairs)
        report = validate(data, expected_candidate=args.candidate_commit, evidence_root=args.evidence_root)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report["checklist_complete"] else 2
    except (AcceptanceInvalid, OSError, UnicodeError, json.JSONDecodeError, TypeError, KeyError):
        # No source values, paths, credentials or arbitrary exception text.
        print(json.dumps({"schema_valid": False, "status": "INVALID_ACCEPTANCE_RECORD",
                          "promotion_authorized": False, "secret_values_logged": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
