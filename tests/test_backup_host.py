import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from types import SimpleNamespace

SPEC = importlib.util.spec_from_file_location("backup_host", Path(__file__).resolve().parents[1] / "scripts/backup_host.py")
host = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(host)


class BackupHostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "backups"
        self.output.mkdir(mode=0o700)
        self.state = self.root / "state"
        self.now = datetime.now(timezone.utc)
        self.config = {"schemaVersion": 1, "sourceProjectRef": "a" * 20, "storageProjectRef": "a" * 20, "supabaseWorkdir": str(self.root / "work"), "supabaseExecutable": "/opt/operator/bin/supabase", "pythonExecutable": "/opt/operator/venv/bin/python", "pgBinDir": "/opt/operator/pg/bin", "outputDir": str(self.output), "stateDir": str(self.state), "encryptionKeyFile": str(self.root / "keys/key"), "intervalSeconds": 3600, "timeoutSeconds": 600, "maximumSnapshotAgeMinutes": 90, "rtoTargetMinutes": 30, "rpoTargetMinutes": 15, "_path": str(self.root / "operator.json")}
        self.report = self.fixture_report()

    def fixture_report(self, *, snapshot=None):
        receipt_id = "DRILL-20260908-000000-1234abcd"
        encrypted = self.output / (receipt_id + ".tar.aesgcm")
        encrypted.write_bytes(b"EDOCBK01 synthetic encrypted fixture")
        encrypted.chmod(0o600)
        report = {"schema_version": 1, "ok": True, "receipt_id": receipt_id, "created_at": (self.now + timedelta(seconds=2)).isoformat(), "source_project_ref": "a" * 20, "target_type": "isolated_local_postgresql", "target_isolated": True, "database": {"schemas": ["edoc", "edoc_private"], "restored": True, "integrity": True, "counts_match": True, "row_hashes_match": True, "permissions_match": True, "table_count": 2, "row_count": 3, "policy_count": 1}, "storage": {"restored": True, "hash_match": True, "counts_match": True, "private": True, "object_count": 0, "empty_source": True}, "backup": {"encrypted": True, "algorithm": "AES-256-GCM", "file": encrypted.name, "sha256": host.runner.digest_file(encrypted), "bytes": encrypted.stat().st_size, "snapshot_at": (snapshot or self.now).isoformat()}, "duration_seconds": 2, "rto_minutes": 1, "rpo_minutes": 1}
        return self.publish_receipt(report)

    def publish_receipt(self, report):
        report = {key: value for key, value in report.items() if key != "receipt_sha256"}
        report["receipt_sha256"] = hashlib.sha256(host.runner.canonical(report)).hexdigest()
        receipt_id = report["receipt_id"]
        receipt = self.output / (receipt_id + ".receipt.json")
        receipt.write_bytes(host.runner.canonical(report))
        receipt.chmod(0o600)
        return report

    def run_mock(self, outcome):
        original_lock = host.runner.SourceLock
        with mock.patch.object(host, "runtime_check", return_value=[]), mock.patch.object(host.runner, "SourceLock", side_effect=lambda source: original_lock(source, self.root / "locks")), mock.patch.object(host.runner, "execute", **({"side_effect": outcome} if isinstance(outcome, BaseException) else {"return_value": outcome})):
            return host.run_once(self.config)

    def test_success_is_durable_and_failure_preserves_exact_previous_success(self):
        success = self.run_mock(self.report)
        self.assertTrue(success["ok"])
        previous = (self.state / "last-success.json").read_bytes()
        failure = self.run_mock(RuntimeError("private-address@example.test secret credential"))
        self.assertFalse(failure["ok"])
        self.assertEqual(previous, (self.state / "last-success.json").read_bytes())
        self.assertNotIn("private-address", json.dumps(failure))
        self.assertEqual(host.health(self.config, now=self.now)["status"], "degraded")
        self.assertEqual(len(list((self.state / "history").glob("*.json"))), 4)

    def test_receipt_file_hash_and_canonical_hash_are_explicitly_different(self):
        evidence = host.validate_success(self.report, self.config)
        self.assertNotEqual(evidence["receiptFileSha256"], evidence["canonicalReceiptSha256"])

    def test_stale_status_is_read_only_and_never_refreshes_credentials(self):
        self.run_mock(self.report)
        before = {path: path.read_bytes() for path in self.state.rglob("*") if path.is_file()}
        with mock.patch.object(host.runner, "linked_source_environment") as credentials, mock.patch.object(host.runner, "load_key") as key, mock.patch.object(host.runner, "execute") as execute:
            result = host.health(self.config, now=self.now + timedelta(minutes=91))
        self.assertEqual(result["status"], "stale")
        self.assertIn("host_backup_snapshot_expired", result["errorCodes"])
        self.assertFalse(result["unattendedCloudDR"])
        credentials.assert_not_called(); key.assert_not_called(); execute.assert_not_called()
        self.assertEqual(before, {path: path.read_bytes() for path in self.state.rglob("*") if path.is_file()})

    def test_first_run_status_and_interruption_do_not_require_prior_success(self):
        host.record_started(self.config, {"attemptId": "HOST-fixture-first", "startedAt": self.now.isoformat(), "ok": False})
        before = {path: path.read_bytes() for path in self.state.rglob("*") if path.is_file()}
        with mock.patch.object(host.runner, "linked_source_environment") as credentials, mock.patch.object(host.runner, "load_key") as key, mock.patch.object(host.runner, "execute") as execute:
            active = host.health(self.config, now=self.now + timedelta(seconds=1))
            interrupted = host.health(self.config, now=self.now + timedelta(seconds=650))
        self.assertEqual(active["status"], "running")
        self.assertIn("host_backup_success_missing", active["errorCodes"])
        self.assertIn("host_backup_operation_in_progress", active["errorCodes"])
        self.assertEqual(interrupted["status"], "degraded")
        self.assertIn("host_backup_interrupted_or_unconfirmed", interrupted["errorCodes"])
        self.assertFalse(active["lastSuccessPreserved"])
        self.assertFalse(interrupted["lastSuccessPreserved"])
        self.assertFalse((self.state / "last-success.json").exists())
        self.assertEqual(before, {path: path.read_bytes() for path in self.state.rglob("*") if path.is_file()})
        credentials.assert_not_called(); key.assert_not_called(); execute.assert_not_called()

    def test_first_failure_remains_visible_without_fabricating_success(self):
        self.assertFalse(self.run_mock(RuntimeError("synthetic-failure"))["ok"])
        result = host.health(self.config, now=self.now + timedelta(seconds=3))
        self.assertEqual(result["status"], "degraded")
        self.assertIn("host_backup_latest_attempt_failed", result["errorCodes"])
        self.assertIn("host_backup_success_missing", result["errorCodes"])
        self.assertFalse(result["lastSuccessPreserved"])

    def test_first_invalid_attempt_is_not_hidden_by_missing_success(self):
        for data in (None, {}, {"phase": "running", "startedAt": "invalid", "ok": False}, {"phase": "running", "startedAt": self.now.isoformat(), "ok": True}, {"phase": "finished", "startedAt": self.now.isoformat(), "ok": False}):
            with self.subTest(data=data):
                host.runner.atomic_private_json(self.state / "last-attempt.json", data)
                result = host.health(self.config)
                self.assertEqual(result["status"], "degraded")
                self.assertIn("host_backup_latest_attempt_invalid", result["errorCodes"])
                self.assertFalse(result["lastSuccessPreserved"])

    def test_non_object_success_state_is_invalid_not_missing(self):
        for data in (None, [], "synthetic-invalid"):
            with self.subTest(data=data):
                host.runner.atomic_private_json(self.state / "last-success.json", data)
                result = host.health(self.config)
                self.assertEqual(result["status"], "invalid")
                self.assertIn("host_backup_state_invalid", result["errorCodes"])
                self.assertFalse(result["lastSuccessPreserved"])

    def test_rpo_target_breach_is_visible_before_maximum_snapshot_expiry(self):
        self.run_mock(self.report)
        result = host.health(self.config, now=self.now + timedelta(minutes=16))
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["maximumSnapshotAgeMinutes"], 90)
        self.assertEqual(result["rpoTargetMinutes"], 15)
        self.assertFalse(result["snapshotWithinRpoTarget"])
        self.assertTrue(result["lastSuccessPreserved"])
        self.assertIn("host_backup_snapshot_rpo_target_exceeded", result["errorCodes"])
        self.assertNotIn("host_backup_snapshot_expired", result["errorCodes"])

    def test_actual_runner_receipt_schema_is_accepted(self):
        encrypted = self.output / self.report["backup"]["file"]
        (self.output / (self.report["receipt_id"] + ".receipt.json")).unlink()
        manifest = {"source_snapshot_at": self.now.isoformat(), "created_at": self.now.isoformat(), "source_project_ref": "a" * 20, "database": {"tables": [{"rows": 1}, {"rows": 2}], "policies": ["synthetic-policy"]}}
        report = host.runner.save_receipt(manifest, encrypted, self.report["storage"], 2, self.report["receipt_id"], SimpleNamespace(rto_target_minutes=30, rpo_target_minutes=15), self.output)
        self.assertEqual(host.validate_success(report, self.config)["receiptId"], report["receipt_id"])

    def test_missing_time_evidence_cannot_publish_success(self):
        for field in ("schema_version", "created_at", "duration_seconds", "rto_minutes", "rpo_minutes"):
            with self.subTest(field=field):
                report = dict(self.report)
                report.pop(field)
                report = self.publish_receipt(report)
                self.assertFalse(self.run_mock(report)["ok"])
                self.assertFalse((self.state / "last-success.json").exists())

    def test_receipt_rejects_invalid_types_nonfinite_and_underreported_times(self):
        cases = [
            ("schema_version", True), ("schema_version", 2),
            ("duration_seconds", True), ("duration_seconds", -1),
            ("duration_seconds", float("nan")), ("duration_seconds", float("inf")),
            ("duration_seconds", 10 ** 1000),
            ("rto_minutes", True), ("rto_minutes", "1"), ("rto_minutes", 0),
            ("rpo_minutes", False), ("rpo_minutes", "1"), ("rpo_minutes", -1),
            ("duration_seconds", 61),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                report = self.publish_receipt(dict(self.report, **{field: value}))
                with self.assertRaises(host.runner.DrillError):
                    host.validate_success(report, self.config)
        report = dict(self.report, created_at=(self.now + timedelta(minutes=2)).isoformat(), rpo_minutes=1)
        with mock.patch.object(host, "utc_now", return_value=self.now + timedelta(minutes=2)):
            with self.assertRaisesRegex(host.runner.DrillError, "timing_inconsistent"):
                host.validate_success(self.publish_receipt(report), self.config)

    def test_receipt_rejects_bad_or_future_timestamps(self):
        for value in (None, "not-a-time", self.now.replace(tzinfo=None).isoformat(), (self.now + timedelta(minutes=2)).isoformat()):
            with self.subTest(value=value):
                with self.assertRaisesRegex(host.runner.DrillError, "time_invalid"):
                    host.validate_success(self.publish_receipt(dict(self.report, created_at=value)), self.config)
        report = dict(self.report, backup={**self.report["backup"], "snapshot_at": (self.now + timedelta(seconds=3)).isoformat()})
        with self.assertRaisesRegex(host.runner.DrillError, "time_invalid"):
            host.validate_success(self.publish_receipt(report), self.config)

    def test_target_breach_does_not_replace_previous_success(self):
        self.run_mock(self.report)
        previous = (self.state / "last-success.json").read_bytes()
        for patch in ({"rto_minutes": 31, "duration_seconds": 1801}, {"rpo_minutes": 16}):
            with self.subTest(patch=patch):
                report = self.publish_receipt(dict(self.report, **patch))
                failure = self.run_mock(report)
                self.assertFalse(failure["ok"])
                self.assertEqual(failure["errorCode"], "backup_recovery_time_or_age_target_exceeded")
                self.assertEqual(previous, (self.state / "last-success.json").read_bytes())

    def test_corrupt_archive_cannot_be_reported_healthy_or_replace_success(self):
        self.run_mock(self.report)
        previous = (self.state / "last-success.json").read_bytes()
        (self.output / self.report["backup"]["file"]).write_bytes(b"same-count-corrupt")
        self.assertEqual(host.health(self.config)["status"], "invalid")
        self.assertFalse(self.run_mock(self.report)["ok"])
        self.assertEqual(previous, (self.state / "last-success.json").read_bytes())

    def test_interrupted_marker_remains_visible_without_fabricating_success(self):
        self.run_mock(self.report)
        previous = (self.state / "last-success.json").read_bytes()
        host.record_started(self.config, {"attemptId": "HOST-fixture-interrupted", "startedAt": self.now.isoformat(), "ok": False})
        active = host.health(self.config, now=self.now + timedelta(seconds=1))
        self.assertEqual(active["status"], "running")
        expired = host.health(self.config, now=self.now + timedelta(seconds=650))
        self.assertEqual(expired["status"], "degraded")
        self.assertIn("host_backup_interrupted_or_unconfirmed", expired["errorCodes"])
        self.assertEqual(previous, (self.state / "last-success.json").read_bytes())

    def test_lock_contention_does_not_change_active_run_status(self):
        self.run_mock(self.report)
        before = (self.state / "last-attempt.json").read_bytes()
        with host.runner.SourceLock("a" * 20, self.root / "locks"):
            blocked = self.run_mock(self.report)
        self.assertEqual(blocked["errorCode"], "source_backup_already_running")
        self.assertEqual(before, (self.state / "last-attempt.json").read_bytes())

    def test_prepare_only_writes_candidate_not_installed_or_activated_job(self):
        with mock.patch.object(host, "runtime_check", return_value=[]), mock.patch.object(host.runner, "checked_run") as commands:
            result = host.prepare_launch_agent(self.config)
        commands.assert_not_called()
        self.assertFalse(result["activated"])
        path = Path(result["path"])
        self.assertEqual(path.parent, (self.state / "pending").resolve())
        plist = plistlib.loads(path.read_bytes())
        self.assertFalse(plist["RunAtLoad"])
        self.assertEqual(plist["ProgramArguments"][-1], "run")
        self.assertNotIn("SUPABASE_ACCESS_TOKEN", json.dumps(plist))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_temporary_or_cache_runtime_paths_are_rejected(self):
        for path in ("/tmp/python", "/private/tmp/pg", "/Users/operator/.cache/python", "/Volumes/Postgres/bin/pg_dump", "relative/python"):
            self.assertFalse(host.persistent_path(path), path)

    def test_config_rejects_unknown_secret_fields_and_colocated_key(self):
        path = self.root / "config.json"
        data = {key: value for key, value in self.config.items() if key != "_path"}
        data["SUPABASE_ACCESS_TOKEN"] = "do-not-accept-credentials"
        path.write_text(json.dumps(data)); path.chmod(0o600)
        with mock.patch.object(host, "persistent_path", return_value=True):
            with self.assertRaisesRegex(host.runner.DrillError, "schema_invalid"):
                host.load_config(path)
        data.pop("SUPABASE_ACCESS_TOKEN")
        data["encryptionKeyFile"] = str(self.output / "key")
        path.write_text(json.dumps(data))
        with mock.patch.object(host, "persistent_path", return_value=True):
            with self.assertRaisesRegex(host.runner.DrillError, "separate_from_backups"):
                host.load_config(path)

    def test_time_limit_and_source_mismatch_never_publish_success(self):
        report = dict(self.report, ok=False)
        self.assertFalse(self.run_mock(report)["ok"])
        self.assertFalse((self.state / "last-success.json").exists())
        with self.assertRaisesRegex(host.runner.DrillError, "source_project_mismatch"):
            host.validate_success(dict(self.report, source_project_ref="b" * 20), self.config)


if __name__ == "__main__":
    unittest.main()
