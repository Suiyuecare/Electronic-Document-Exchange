"""Offline DR evidence validation; never cloud upload or promotion authority.

Seven date labels are insufficient. This checks snapshot availability over an
elapsed window, original restore receipts, and actual downloaded encrypted
bytes. Permission and key-custody observations still require a human reviewer.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import os

SHA = re.compile(r"[a-f0-9]{40}\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")
ID = re.compile(r"B-[0-9]{3,8}\Z")
PERSON = re.compile(r"P-[0-9]{3,6}\Z")
FORBIDDEN = re.compile(r"https?://|Bearer\s|(?:vcp_|sb_secret_|sk-proj-)|@|-----BEGIN", re.I)
MAGIC = b"EDOCBK01"
RECEIPT = re.compile(r"(?:DRILL|RESTORE)-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}\Z")
RECEIPT_KEYS = {"schema_version", "receipt_id", "ok", "result", "created_at", "source_project_ref",
                "target_project_ref", "target_type", "target_isolated", "database", "storage", "backup",
                "rto_minutes", "rpo_minutes", "duration_seconds", "limitations", "receipt_sha256"}


class ContinuityInvalid(ValueError):
    """Only fixed, non-sensitive diagnostic codes."""


def shape(value, keys, code):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ContinuityInvalid(code)


def instant(value):
    if not isinstance(value, str):
        raise ContinuityInvalid("time_invalid")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ContinuityInvalid("time_invalid") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise ContinuityInvalid("timezone_required")
    return result.astimezone(timezone.utc)


def artifact_parts(name):
    if not isinstance(name, str) or "\\" in name or ":" in name:
        raise ContinuityInvalid("artifact_path_invalid")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or str(path) != name or any(part in {".", ".."} for part in path.parts):
        raise ContinuityInvalid("artifact_path_invalid")
    return path.parts


@contextmanager
def private_root_descriptor(root):
    """Traverse all ancestors with openat/NOFOLLOW, then check the private root."""
    root = Path(root).absolute()
    if ".." in root.parts:
        raise ContinuityInvalid("private_evidence_root_path_invalid")
    fd = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in root.parts[1:]:
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except OSError:
                raise ContinuityInvalid("artifact_symlink_or_directory_invalid") from None
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise ContinuityInvalid("private_evidence_root_required")
        yield fd
    finally:
        os.close(fd)


def validate_private_root(root):
    with private_root_descriptor(root):
        pass


def file_metadata(info, maximum):
    if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid()
            or info.st_nlink != 1 or info.st_size > maximum):
        raise ContinuityInvalid("artifact_private_file_required")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextmanager
def private_artifact_stream(root, name, *, maximum=8*1024*1024):
    parts = artifact_parts(name)
    with private_root_descriptor(root) as root_fd:
        fd = os.dup(root_fd)
        try:
            for part in parts[:-1]:
                try:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except OSError:
                    raise ContinuityInvalid("artifact_symlink_or_directory_invalid") from None
                os.close(fd)
                fd = child
                info = os.fstat(fd)
                if info.st_mode & 0o077 or info.st_uid != os.getuid():
                    raise ContinuityInvalid("artifact_private_directory_required")
            try:
                leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            except OSError:
                raise ContinuityInvalid("artifact_symlink_or_file_invalid") from None
            with os.fdopen(leaf, "rb") as stream:
                before = file_metadata(os.fstat(stream.fileno()), maximum)
                yield stream, before
                if file_metadata(os.fstat(stream.fileno()), maximum) != before:
                    raise ContinuityInvalid("artifact_changed_during_validation")
        finally:
            os.close(fd)


def private_artifact(root, name, *, maximum=8*1024*1024):
    """Compatibility path inspector; validating code reads the held descriptor."""
    with private_artifact_stream(root, name, maximum=maximum):
        return Path(root) / name


def private_bytes(root, name, *, maximum=8*1024*1024):
    with private_artifact_stream(root, name, maximum=maximum) as (stream, info):
        content = stream.read(maximum + 1)
        if len(content) != info[2] or len(content) > maximum:
            raise ContinuityInvalid("artifact_changed_during_validation")
        return content, info[:2]


def encrypted_file_evidence(root, name):
    with private_artifact_stream(root, name, maximum=2**50) as (stream, info):
        # Header/nonce/tag validation detects empty/plain bytes; authenticity
        # still requires the real offline restore receipt and manual review.
        if info[2] <= len(MAGIC) + 12 + 16 or stream.read(len(MAGIC)) != MAGIC:
            raise ContinuityInvalid("encrypted_archive_format_invalid")
        if len(stream.read(12)) != 12:
            raise ContinuityInvalid("encrypted_archive_format_invalid")
        stream.seek(-16, 2)
        if len(stream.read(16)) != 16:
            raise ContinuityInvalid("encrypted_archive_format_invalid")
        stream.seek(0)
        value = hashlib.sha256()
        size = 0
        for block in iter(lambda: stream.read(1024*1024), b""):
            value.update(block)
            size += len(block)
        if size != info[2]:
            raise ContinuityInvalid("artifact_changed_during_validation")
        return {"sha256": value.hexdigest(), "bytes": size, "identity": info[:2], "name": PurePosixPath(name).name}


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            value.update(block)
    return value.hexdigest()


def verify_receipt(content, *, snapshot, archive_hash, archive_file, archive_bytes, rto_target,
                   expected_source_project_hash, now, minimum_created, maximum_created, kind):
    report = json.loads(content, object_pairs_hook=unique_keys)
    shape(report, RECEIPT_KEYS, "restore_receipt_schema_invalid")
    expected = dict(report)
    claimed = expected.pop("receipt_sha256", None)
    canonical = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if claimed != hashlib.sha256(canonical).hexdigest():
        raise ContinuityInvalid("restore_receipt_hash_invalid")
    if (type(report.get("schema_version")) is not int or report["schema_version"] != 1
            or report.get("ok") is not True or report.get("target_isolated") is not True
            or report.get("target_type") != "isolated_local_postgresql"
            or report["result"] != "通過"):
        raise ContinuityInvalid("actual_isolated_restore_required")
    if (not isinstance(report["receipt_id"], str) or not RECEIPT.fullmatch(report["receipt_id"])
            or not report["receipt_id"].startswith(kind + "-")
            or not isinstance(report["target_project_ref"], str)
            or not re.fullmatch(r"local-postgres-[a-f0-9]{16}", report["target_project_ref"])):
        raise ContinuityInvalid("restore_receipt_identity_invalid")
    source = report["source_project_ref"]
    if (not isinstance(source, str) or not re.fullmatch(r"[a-z0-9]{20}", source)
            or hashlib.sha256(source.encode()).hexdigest() != expected_source_project_hash):
        raise ContinuityInvalid("restore_source_project_binding_invalid")
    created = instant(report["created_at"])
    if not snapshot <= created <= now or not minimum_created <= created <= maximum_created:
        raise ContinuityInvalid("restore_receipt_time_invalid")
    database, storage, backup = (report.get(key) for key in ("database", "storage", "backup"))
    shape(database, {"restored", "integrity", "counts_match", "row_hashes_match", "permissions_match",
                     "table_count", "row_count", "policy_count", "schemas"}, "restore_database_schema_invalid")
    shape(storage, {"restored", "hash_match", "counts_match", "object_count", "bytes", "target_type", "private", "empty_source"}, "restore_storage_schema_invalid")
    shape(backup, {"encrypted", "algorithm", "sha256", "bytes", "file", "snapshot_at"}, "restore_backup_schema_invalid")
    if (database.get("schemas") != ["edoc", "edoc_private"]
            or not all(database.get(key) is True for key in ("restored", "integrity", "counts_match", "row_hashes_match", "permissions_match"))
            or not all(storage.get(key) is True for key in ("restored", "hash_match", "counts_match", "private"))
            or backup.get("encrypted") is not True or backup.get("algorithm") != "AES-256-GCM"
            or backup.get("sha256") != archive_hash or backup.get("file") != archive_file
            or type(backup.get("bytes")) is not int or backup["bytes"] != archive_bytes
            or instant(backup.get("snapshot_at")) != snapshot):
        raise ContinuityInvalid("restore_scope_or_integrity_invalid")
    for value in (database["table_count"], database["row_count"], database["policy_count"], storage["object_count"], storage["bytes"]):
        if type(value) is not int or value < 0:
            raise ContinuityInvalid("restore_counts_invalid")
    if (database["table_count"] == 0 or storage["target_type"] != "private_local_filesystem"
            or type(storage["empty_source"]) is not bool
            or storage["empty_source"] != (storage["object_count"] == 0)
            or (storage["object_count"] == 0 and storage["bytes"] != 0)
            or not isinstance(report["limitations"], list) or not report["limitations"]
            or any(not isinstance(value, str) for value in report["limitations"])):
        raise ContinuityInvalid("restore_counts_or_limitations_invalid")
    seconds = report.get("duration_seconds")
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= rto_target * 60:
        raise ContinuityInvalid("rto_target_not_met")
    if (type(report["rto_minutes"]) is not int or report["rto_minutes"] != max(1, math.ceil(seconds/60))
            or type(report["rpo_minutes"]) is not int or not 0 <= report["rpo_minutes"] <= 15
            or report["rpo_minutes"] * 60 < (created-snapshot).total_seconds() - 1
            or max(0, report["rpo_minutes"] - 1) * 60 > (created-snapshot).total_seconds() + 1
            or (created-snapshot).total_seconds() > 15*60 + 1):
        raise ContinuityInvalid("restore_receipt_timing_inconsistent")
    return {"duration": seconds, "receipt_id": report["receipt_id"], "target": report["target_project_ref"],
            "counts": [database[key] for key in ("table_count", "row_count", "policy_count")]
                      + [storage[key] for key in ("object_count", "bytes")]}


def verify_backup(row, root, rto_target, *, expected_source_project_hash, now):
    """Read original receipts and bytes, never a virtual file reference."""
    receipt, receipt_identity = private_bytes(root, row["local_receipt"])
    if not isinstance(row["local_receipt_sha256"], str) or not HASH.fullmatch(row["local_receipt_sha256"]) or hashlib.sha256(receipt).hexdigest() != row["local_receipt_sha256"]:
        raise ContinuityInvalid("local_receipt_file_hash_invalid")
    archive = encrypted_file_evidence(root, row["archive"])
    downloaded = encrypted_file_evidence(root, row["offsite_copy"])
    if archive["identity"] == downloaded["identity"]:
        raise ContinuityInvalid("offsite_download_cannot_be_local_original")
    claimed = row["archive_sha256"]
    if not isinstance(claimed, str) or not HASH.fullmatch(claimed) or archive["sha256"] != claimed or downloaded["sha256"] != claimed:
        raise ContinuityInvalid("offsite_download_bytes_hash_invalid")
    snapshot = instant(row["snapshot_at"])
    original = verify_receipt(receipt, snapshot=snapshot, archive_hash=claimed,
                   archive_file=archive["name"], archive_bytes=archive["bytes"], rto_target=rto_target,
                   expected_source_project_hash=expected_source_project_hash, now=now,
                   minimum_created=instant(row["snapshot_at"]), maximum_created=instant(row["finished_at"]), kind="DRILL")
    if row["offsite_permissions"] != "PRIVATE_REVIEWED" or not isinstance(row["offsite_object_ref"], str) or not ID.fullmatch(row["offsite_object_ref"]):
        raise ContinuityInvalid("private_offsite_permission_review_required")
    if row["restore_receipt"] is not None:
        restored, restored_identity = private_bytes(root, row["restore_receipt"])
        if restored_identity == receipt_identity:
            raise ContinuityInvalid("offsite_restore_cannot_reuse_local_receipt")
        restored = verify_receipt(restored, snapshot=snapshot, archive_hash=claimed,
                              archive_file=downloaded["name"], archive_bytes=downloaded["bytes"], rto_target=rto_target,
                              expected_source_project_hash=expected_source_project_hash, now=now,
                              minimum_created=instant(row["available_at"]), maximum_created=now, kind="RESTORE")
        if (restored["receipt_id"] == original["receipt_id"] or restored["target"] == original["target"]
                or restored["counts"] != original["counts"]):
            raise ContinuityInvalid("offsite_restore_binding_invalid")
        return restored["duration"]
    return None


def assess(record, *, expected_candidate, expected_source_project_hash, evidence_root, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ContinuityInvalid("timezone_required")
    validate_private_root(evidence_root)
    if FORBIDDEN.search(json.dumps(record, ensure_ascii=False, allow_nan=False)):
        raise ContinuityInvalid("sensitive_or_connection_data_forbidden")
    shape(record, {"schema_version", "candidate_commit", "source_project_ref_sha256", "environment", "government_exchange", "window_start", "window_end", "rpo_target_minutes", "rto_target_minutes", "schedule_activated", "offsite_approved", "key_custody_confirmed", "custodian_id", "reviewer_id", "attempts"}, "record_schema_invalid")
    if (type(record["schema_version"]) is not int or record["schema_version"] != 1
            or not SHA.fullmatch(expected_candidate or "") or record["candidate_commit"] != expected_candidate
            or record["government_exchange"] != "DISABLED"):
        raise ContinuityInvalid("candidate_or_government_scope_invalid")
    if (not isinstance(expected_source_project_hash, str) or not HASH.fullmatch(expected_source_project_hash)
            or record["source_project_ref_sha256"] != expected_source_project_hash):
        raise ContinuityInvalid("approved_source_project_binding_required")
    if record["environment"] not in {"isolated_fixture", "operator_host"}:
        raise ContinuityInvalid("environment_invalid")
    start, end = instant(record["window_start"]), instant(record["window_end"])
    if not 7*86400 <= (end-start).total_seconds() <= 31*86400 or end > now:
        raise ContinuityInvalid("seven_elapsed_days_required")
    for field, maximum in (("rpo_target_minutes", 15), ("rto_target_minutes", 30)):
        if type(record[field]) is not int or not 1 <= record[field] <= maximum:
            raise ContinuityInvalid("recovery_target_invalid")
    if (now-end).total_seconds() > record["rpo_target_minutes"] * 60:
        raise ContinuityInvalid("continuity_window_stale")
    for field in ("schedule_activated", "offsite_approved", "key_custody_confirmed"):
        if type(record[field]) is not bool:
            raise ContinuityInvalid("operator_observation_invalid")
    for field in ("custodian_id", "reviewer_id"):
        if not isinstance(record[field], str) or not PERSON.fullmatch(record[field]):
            raise ContinuityInvalid("operator_review_required")
    if record["custodian_id"] == record["reviewer_id"]:
        raise ContinuityInvalid("independent_review_required")
    rows = record["attempts"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20000:
        raise ContinuityInvalid("attempts_invalid")
    keys = {"id", "started_at", "finished_at", "snapshot_at", "available_at", "outcome", "failure_alert_at", "local_receipt", "local_receipt_sha256", "archive", "archive_sha256", "offsite_copy", "offsite_permissions", "offsite_object_ref", "restore_receipt"}
    successful, failures, seen, restores = [], [], set(), []
    for row in rows:
        shape(row, keys, "attempt_schema_invalid")
        if not isinstance(row["id"], str) or not ID.fullmatch(row["id"]) or row["id"] in seen or row["outcome"] not in {"success", "failed", "interrupted"}:
            raise ContinuityInvalid("attempt_identity_invalid")
        seen.add(row["id"])
        begun, finished = instant(row["started_at"]), instant(row["finished_at"])
        if not start-timedelta_seconds(record["rpo_target_minutes"]*60) <= begun <= finished <= end:
            raise ContinuityInvalid("attempt_time_invalid")
        if row["outcome"] != "success":
            if any(row[field] is not None for field in keys - {"id", "started_at", "finished_at", "outcome", "failure_alert_at"}):
                raise ContinuityInvalid("failure_cannot_claim_backup_success")
            alert = instant(row["failure_alert_at"])
            if not finished <= alert <= min(end, finished+timedelta_seconds(300)):
                raise ContinuityInvalid("failure_alert_not_observed_in_time")
            failures.append(finished)
            continue
        if row["failure_alert_at"] is not None:
            raise ContinuityInvalid("success_cannot_claim_failure_alert")
        snapshot, available = instant(row["snapshot_at"]), instant(row["available_at"])
        if not begun <= snapshot <= finished <= available <= end:
            raise ContinuityInvalid("snapshot_availability_invalid")
        restored = verify_backup(row, evidence_root, record["rto_target_minutes"],
                                 expected_source_project_hash=expected_source_project_hash, now=now)
        if restored is not None:
            restores.append(restored)
        successful.append((available, snapshot))
    successful.sort()
    latest = None
    worst = 0.0
    target_seconds = record["rpo_target_minutes"]*60
    for available, snapshot in successful:
        if available <= start:
            latest = max(latest, snapshot) if latest is not None else snapshot
            continue
        if latest is None:
            raise ContinuityInvalid("initial_recovery_point_missing")
        worst = max(worst, (available-latest).total_seconds())
        latest = max(latest, snapshot)
    if latest is None:
        raise ContinuityInvalid("initial_recovery_point_missing")
    worst = max(worst, (now-latest).total_seconds())
    availability = [available for available, _ in successful]
    retried = True
    for failure in failures:
        next_index = bisect_right(availability, failure)
        if next_index == len(availability) or availability[next_index] > failure+timedelta_seconds(target_seconds):
            retried = False
            break
    scope_passed = worst <= target_seconds and retried and bool(restores)
    operator_ready = scope_passed and record["environment"] == "operator_host" and all(record[field] is True for field in ("schedule_activated", "offsite_approved", "key_custody_confirmed"))
    return {"schema_valid": True, "candidate_commit": expected_candidate, "source_project_ref_sha256": expected_source_project_hash, "environment": record["environment"], "elapsed_days": (end-start).total_seconds()/86400, "successful_backups": len(successful), "failed_or_interrupted_attempts": len(failures), "maximum_snapshot_age_minutes": worst/60, "current_snapshot_age_minutes": (now-latest).total_seconds()/60, "observed_retry_within_rpo": retried, "offsite_restore_count": len(restores), "scope_continuity_passed": scope_passed, "operator_evidence_ready_for_review": operator_ready, "permission_and_custody_independently_verified": False, "archive_encryption_independently_authenticated": False, "restore_execution_independently_verified": False, "promotion_authorized": False, "government_exchange": "DISABLED"}


def timedelta_seconds(seconds):
    from datetime import timedelta
    return timedelta(seconds=seconds)


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContinuityInvalid("duplicate_json_key")
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--source-project-ref-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        root = args.evidence_root
        validate_private_root(root)
        content, _ = private_bytes(args.record.parent, args.record.name, maximum=16*1024*1024)
        record = json.loads(content, object_pairs_hook=unique_keys)
        report = assess(record, expected_candidate=args.candidate_commit,
                        expected_source_project_hash=args.source_project_ref_sha256, evidence_root=root)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0 if report["operator_evidence_ready_for_review"] else 2
    except (ContinuityInvalid, OSError, UnicodeError, ValueError, TypeError, KeyError, OverflowError):
        print(json.dumps({"schema_valid": False, "error_code": "invalid_continuity_evidence", "promotion_authorized": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
