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
        report = {"ok": True, "receipt_id": receipt_id, "source_project_ref": "a" * 20, "target_type": "isolated_local_postgresql", "target_isolated": True, "database": {"schemas": ["edoc", "edoc_private"], "restored": True, "integrity": True, "counts_match": True, "row_hashes_match": True, "permissions_match": True, "table_count": 2, "row_count": 3, "policy_count": 1}, "storage": {"restored": True, "hash_match": True, "counts_match": True, "private": True, "object_count": 0, "empty_source": True}, "backup": {"encrypted": True, "algorithm": "AES-256-GCM", "file": encrypted.name, "sha256": host.runner.digest_file(encrypted), "bytes": encrypted.stat().st_size, "snapshot_at": (snapshot or self.now).isoformat()}, "duration_seconds": 2}
        report["receipt_sha256"] = hashlib.sha256(host.runner.canonical(report)).hexdigest()
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
