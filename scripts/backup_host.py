#!/usr/bin/env python3
"""Prepared, opt-in host-assisted eDoc backups. No cloud upload or scheduler activation.

The config contains paths and timing only, never credentials. A scheduled run
uses the operator's existing authorized Supabase CLI and existing encryption
key, records safe evidence, and never calls a mail or Drive API.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import stat
import sys
from types import SimpleNamespace

SPEC = importlib.util.spec_from_file_location("edoc_backup_runner", Path(__file__).with_name("backup_restore_drill.py"))
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

CONFIG_KEYS = {
    "schemaVersion", "sourceProjectRef", "storageProjectRef", "supabaseWorkdir",
    "supabaseExecutable", "pythonExecutable", "pgBinDir", "outputDir", "stateDir",
    "encryptionKeyFile", "intervalSeconds", "timeoutSeconds", "maximumSnapshotAgeMinutes",
    "rtoTargetMinutes", "rpoTargetMinutes",
}
PATH_KEYS = {"supabaseWorkdir", "supabaseExecutable", "pythonExecutable", "pgBinDir", "outputDir", "stateDir", "encryptionKeyFile"}
LABEL = "com.suiyuecare.edoc.backup-host"


def utc_now():
    return datetime.now(timezone.utc)


def private_file(path, *, maximum_bytes=65536):
    path = Path(path).expanduser()
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise runner.DrillError("operator_file_permissions_invalid")
    if info.st_size > maximum_bytes:
        raise runner.DrillError("operator_file_too_large")
    return path


def persistent_path(path):
    path = Path(path).expanduser()
    if not path.is_absolute():
        return False
    resolved = path.resolve()
    temporary_roots = (Path("/tmp"), Path("/private/tmp"), Path("/var/tmp"), Path("/private/var/tmp"), Path("/var/folders"), Path("/private/var/folders"), Path("/Volumes"))
    return not any(resolved == root or root in resolved.parents for root in temporary_roots) and not any(part in {".cache", "Caches"} for part in resolved.parts)


def load_config(path):
    path = private_file(path)
    if not persistent_path(path) or path.resolve() == runner.ROOT or runner.ROOT in path.resolve().parents:
        raise runner.DrillError("operator_config_must_be_outside_repository")
    config = json.loads(path.read_bytes())
    if not isinstance(config, dict) or set(config) != CONFIG_KEYS or config["schemaVersion"] != 1:
        raise runner.DrillError("operator_config_schema_invalid")
    for name in ("sourceProjectRef", "storageProjectRef"):
        if not isinstance(config[name], str) or not re.fullmatch(r"[a-z0-9]{20}", config[name]):
            raise runner.DrillError("operator_config_project_invalid")
    for name in PATH_KEYS:
        if not isinstance(config[name], str) or not persistent_path(config[name]):
            raise runner.DrillError("operator_config_requires_persistent_paths")
        config[name] = str(Path(config[name]).expanduser().absolute())
    if Path(config["supabaseExecutable"]).name != "supabase":
        raise runner.DrillError("operator_supabase_executable_invalid")
    bounds = {"intervalSeconds": (300, 604800), "timeoutSeconds": (60, 7200), "maximumSnapshotAgeMinutes": (5, 20160), "rtoTargetMinutes": (1, 120), "rpoTargetMinutes": (1, 1440)}
    for name, (low, high) in bounds.items():
        if type(config[name]) is not int or not low <= config[name] <= high:
            raise runner.DrillError("operator_config_timing_invalid")
    if config["timeoutSeconds"] + 30 >= config["intervalSeconds"]:
        raise runner.DrillError("operator_schedule_interval_too_short")
    key = Path(config["encryptionKeyFile"]).resolve()
    output = Path(config["outputDir"]).resolve()
    if key == output or output in key.parents:
        raise runner.DrillError("encryption_key_must_be_separate_from_backups")
    config["_path"] = str(path.resolve())
    return config


def runtime_check(config):
    """Read-only; does not read key bytes, resolve CLI credentials or connect."""
    codes = []
    if sys.version_info < (3, 12) or not persistent_path(sys.executable) or not persistent_path(sys.base_prefix):
        codes.append("persistent_python_312_required")
    if Path(sys.executable).resolve() != Path(config["pythonExecutable"]).resolve():
        codes.append("configured_python_not_in_use")
    for name in ("supabaseExecutable", "pythonExecutable"):
        path = Path(config[name])
        if not path.is_file() or not os.access(path, os.X_OK) or path.stat().st_mode & 0o022:
            codes.append("operator_executable_invalid")
    for name in ("pg_dump", "pg_restore", "initdb", "pg_ctl"):
        path = Path(config["pgBinDir"]) / name
        if not persistent_path(path) or not path.is_file() or not os.access(path, os.X_OK) or path.stat().st_mode & 0o022:
            codes.append("persistent_postgres_tools_required")
    try:
        key = private_file(config["encryptionKeyFile"], maximum_bytes=32)
        if key.stat().st_size != 32:
            codes.append("existing_encryption_key_invalid")
    except (OSError, runner.DrillError):
        codes.append("existing_encryption_key_missing_or_unprotected")
    try:
        linked = (Path(config["supabaseWorkdir"]) / "supabase/.temp/project-ref").read_text().strip()
        if linked != config["sourceProjectRef"]:
            codes.append("source_project_link_mismatch")
    except OSError:
        codes.append("source_project_link_missing")
    return sorted(set(codes))


def parse_time(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone_required")
    return parsed.astimezone(timezone.utc)


def safe_error(exc):
    code = str(exc) if isinstance(exc, runner.DrillError) else "host_backup_unexpected_failure"
    return code if re.fullmatch(r"[a-z][a-z0-9_]{0,95}", code) else "host_backup_failed"


def validate_success(report, config):
    """A returned success is insufficient without durable, matching evidence."""
    if report.get("ok") is not True or report.get("target_type") != "isolated_local_postgresql" or report.get("target_isolated") is not True:
        raise runner.DrillError("backup_validation_failed")
    if report.get("source_project_ref") != config["sourceProjectRef"]:
        raise runner.DrillError("backup_source_project_mismatch")
    database, storage, backup = (report.get(name, {}) for name in ("database", "storage", "backup"))
    if not all(database.get(name) is True for name in ("restored", "integrity", "counts_match", "row_hashes_match", "permissions_match")):
        raise runner.DrillError("database_validation_failed")
    if database.get("schemas") != list(runner.SCHEMAS):
        raise runner.DrillError("backup_schema_scope_mismatch")
    if not all(storage.get(name) is True for name in ("restored", "hash_match", "counts_match", "private")):
        raise runner.DrillError("storage_validation_failed")
    if backup.get("encrypted") is not True or backup.get("algorithm") != "AES-256-GCM":
        raise runner.DrillError("backup_encryption_unverified")
    receipt_id = report.get("receipt_id", "")
    if not re.fullmatch(r"DRILL-\d{8}-\d{6}-[a-f0-9]{8}", receipt_id) or backup.get("file") != receipt_id + ".tar.aesgcm":
        raise runner.DrillError("backup_evidence_id_invalid")
    output = Path(config["outputDir"])
    encrypted = private_file(output / backup["file"], maximum_bytes=2**50)
    receipt = private_file(output / (receipt_id + ".receipt.json"))
    expected_report = dict(report)
    claimed = expected_report.pop("receipt_sha256", "")
    if claimed != hashlib.sha256(runner.canonical(expected_report)).hexdigest() or receipt.read_bytes() != runner.canonical(report):
        raise runner.DrillError("backup_receipt_hash_mismatch")
    if backup.get("bytes") != encrypted.stat().st_size or backup.get("sha256") != runner.digest_file(encrypted):
        raise runner.DrillError("backup_archive_hash_mismatch")
    return {"receiptId": receipt_id, "snapshotAt": parse_time(backup["snapshot_at"]).isoformat(), "archiveSha256": backup["sha256"], "archiveBytes": backup["bytes"], "receiptFileSha256": runner.digest_file(receipt), "canonicalReceiptSha256": claimed, "tableCount": database["table_count"], "rowCount": database["row_count"], "policyCount": database["policy_count"], "storageObjectCount": storage["object_count"], "storageEmpty": storage["empty_source"], "durationSeconds": report["duration_seconds"]}


def record_attempt(config, attempt):
    state = runner.private_directory(config["stateDir"])
    history = runner.private_directory(state / "history")
    runner.atomic_private_json(history / (attempt["attemptId"] + ".json"), attempt, replace=False)
    runner.atomic_private_json(state / "last-attempt.json", attempt)
    if attempt["ok"]:
        runner.atomic_private_json(state / "last-success.json", attempt)


def record_started(config, attempt):
    state = runner.private_directory(config["stateDir"])
    history = runner.private_directory(state / "history")
    started = {**attempt, "phase": "running"}
    runner.atomic_private_json(history / (attempt["attemptId"] + ".started.json"), started, replace=False)
    runner.atomic_private_json(state / "last-attempt.json", started)


def run_guarded(config, lock):
    codes = runtime_check(config)
    if codes:
        raise runner.DrillError(codes[0])
    # CLI auth stays inside its supported client; no cookie/token extraction.
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join((str(Path(config["supabaseExecutable"]).parent), str(Path(config["pythonExecutable"]).parent), "/usr/bin", "/bin", "/usr/sbin", "/sbin"))
    args = SimpleNamespace(pg_bin_dir=config["pgBinDir"], supabase_workdir=config["supabaseWorkdir"], source_project_ref=config["sourceProjectRef"], storage_project_ref=config["storageProjectRef"], output_dir=config["outputDir"], encryption_key_file=config["encryptionKeyFile"], rto_target_minutes=config["rtoTargetMinutes"], rpo_target_minutes=config["rpoTargetMinutes"], timeout_seconds=config["timeoutSeconds"], require_existing_key=True, restore_backup=None, env_file=None)
    try:
        report = runner.execute(args, held_lock=lock)
    finally:
        os.environ["PATH"] = old_path
    if report.get("ok") is not True:
        raise runner.DrillError("backup_recovery_time_or_age_target_exceeded")
    return validate_success(report, config)


def run_once(config):
    os.umask(0o077)
    attempt = {"schemaVersion": 1, "attemptId": "HOST-" + utc_now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4), "startedAt": utc_now().isoformat(), "ok": False, "targetType": "host_assisted_isolated_restore", "unattendedCloudDR": False, "offsiteValidation": "not_performed_by_host_runner"}
    try:
        with runner.SourceLock(config["sourceProjectRef"]) as lock:
            record_started(config, attempt)
            try:
                with runner.bounded_operation(config["timeoutSeconds"]):
                    attempt.update({"ok": True, "evidence": run_guarded(config, lock)})
            except Exception as exc:
                attempt["errorCode"] = safe_error(exc)
            attempt["finishedAt"] = utc_now().isoformat()
            attempt["phase"] = "finished"
            record_attempt(config, attempt)
    except Exception as exc:
        # No second writer may race the active run's mutable status pointers.
        # Lock contention is reported to the caller, not persisted over it.
        attempt["errorCode"] = safe_error(exc)
        attempt["ok"] = False
        attempt["finishedAt"] = utc_now().isoformat()
    return attempt


def health(config, *, now=None):
    """No writes, key reads, network or credential refresh on a health query."""
    result = {"schemaVersion": 1, "checkedAt": (now or utc_now()).isoformat(), "status": "missing", "lastSuccessPreserved": False, "maximumSnapshotAgeMinutes": config["maximumSnapshotAgeMinutes"], "unattendedCloudDR": False, "offsiteValidation": "not_verified_by_host_runner", "errorCodes": []}
    state = Path(config["stateDir"])
    try:
        success = json.loads(private_file(state / "last-success.json").read_bytes())
    except FileNotFoundError:
        result["errorCodes"] = ["host_backup_success_missing"]
        return result
    except (ValueError, OSError, runner.DrillError):
        result["status"], result["errorCodes"] = "invalid", ["host_backup_state_invalid"]
        return result
    try:
        evidence = success["evidence"]
        if success.get("ok") is not True:
            raise ValueError("success_required")
        receipt_id = evidence["receiptId"]
        if not re.fullmatch(r"DRILL-\d{8}-\d{6}-[a-f0-9]{8}", receipt_id):
            raise ValueError("receipt_invalid")
        receipt = private_file(Path(config["outputDir"]) / (receipt_id + ".receipt.json"))
        report = json.loads(receipt.read_bytes())
        checked = validate_success(report, config)
        if checked != evidence:
            raise ValueError("state_evidence_changed")
        age = ((now or utc_now()) - parse_time(evidence["snapshotAt"])).total_seconds() / 60
        if age < -1:
            raise ValueError("future_snapshot")
        result.update({"status": "stale" if age > config["maximumSnapshotAgeMinutes"] else "healthy", "snapshotAgeMinutes": max(0, int(age)), "lastSuccessPreserved": True, "receiptId": receipt_id})
        if result["status"] == "stale":
            result["errorCodes"].append("host_backup_snapshot_expired")
    except (KeyError, TypeError, ValueError, OSError, runner.DrillError):
        result["status"], result["errorCodes"] = "invalid", ["host_backup_evidence_invalid"]
        return result
    try:
        latest = json.loads(private_file(state / "last-attempt.json").read_bytes())
        if latest.get("phase") == "running":
            elapsed = ((now or utc_now()) - parse_time(latest["startedAt"])).total_seconds()
            code = "host_backup_operation_in_progress" if 0 <= elapsed <= config["timeoutSeconds"] + 30 else "host_backup_interrupted_or_unconfirmed"
            result["errorCodes"].append(code)
            if result["status"] == "healthy":
                result["status"] = "running" if code.endswith("in_progress") else "degraded"
        elif latest.get("ok") is False:
            result["errorCodes"].append("host_backup_latest_attempt_failed")
            if result["status"] == "healthy":
                result["status"] = "degraded"
    except FileNotFoundError:
        pass
    except (KeyError, TypeError, ValueError, OSError, runner.DrillError):
        result["errorCodes"].append("host_backup_latest_attempt_invalid")
        result["status"] = "degraded" if result["status"] == "healthy" else result["status"]
    return result


def prepare_launch_agent(config):
    codes = runtime_check(config)
    if codes:
        raise runner.DrillError(codes[0])
    pending = runner.private_directory(Path(config["stateDir"]) / "pending")
    logs = runner.private_directory(Path(config["stateDir"]) / "logs")
    # Intentionally outside ~/Library/LaunchAgents. No launchctl/load/bootstrap
    # call exists in this script; preparing does not activate a schedule.
    path = pending / (LABEL + ".plist")
    data = {"Label": LABEL, "ProgramArguments": [config["pythonExecutable"], str(Path(__file__).resolve()), "--config", config["_path"], "run"], "WorkingDirectory": str(Path(__file__).resolve().parent), "StartInterval": config["intervalSeconds"], "RunAtLoad": False, "ProcessType": "Background", "LowPriorityIO": True, "Nice": 10, "ThrottleInterval": 300, "AbandonProcessGroup": False, "StandardOutPath": str(logs / "scheduler.stdout.log"), "StandardErrorPath": str(logs / "scheduler.stderr.log"), "Umask": 0o077}
    # A plist is configuration, not secret material; use exclusive creation to
    # avoid replacing an operator's reviewed candidate with silent changes.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        plistlib.dump(data, stream)
    return {"prepared": True, "activated": False, "label": LABEL, "path": str(path), "intervalSeconds": config["intervalSeconds"], "unattendedCloudDR": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("mode", choices=("check", "status", "run", "prepare-launch-agent"))
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.mode == "check":
            codes = runtime_check(config)
            result = {"ok": not codes, "errorCodes": codes, "writesPerformed": False, "credentialRefreshPerformed": False, "scheduleActivated": False}
        elif args.mode == "status":
            result = health(config)
        elif args.mode == "prepare-launch-agent":
            result = prepare_launch_agent(config)
        else:
            result = run_once(config)
    except Exception as exc:
        result = {"ok": False, "errorCode": safe_error(exc)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") is True or result.get("prepared") is True or result.get("status") == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
