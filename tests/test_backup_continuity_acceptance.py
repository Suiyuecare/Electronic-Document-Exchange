"""Synthetic continuity fixtures do not establish live offsite DR."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import backup_continuity_acceptance as continuity
from tests.test_backup_restore_runner import runner

SHA = "a"*40
SOURCE_REF = "a"*20
SOURCE_HASH = hashlib.sha256(SOURCE_REF.encode()).hexdigest()
NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


class BackupContinuityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root.chmod(0o700)
        self.start = NOW-timedelta(days=7)
        self.record = {"schema_version": 1, "candidate_commit": SHA, "source_project_ref_sha256": SOURCE_HASH, "environment": "isolated_fixture",
            "government_exchange": "DISABLED", "window_start": self.start.isoformat(), "window_end": NOW.isoformat(),
            "rpo_target_minutes": 15, "rto_target_minutes": 30, "schedule_activated": False,
            "offsite_approved": False, "key_custody_confirmed": False, "custodian_id": "P-001", "reviewer_id": "P-002", "attempts": []}
        for number in range(1009):
            stamp = self.start+timedelta(minutes=number*10)
            self.record["attempts"].append(self.success(number+1, stamp))

    def success(self, number, stamp):
        return {"id": f"B-{number:06d}", "started_at": stamp.isoformat(), "finished_at": stamp.isoformat(),
            "snapshot_at": stamp.isoformat(), "available_at": stamp.isoformat(), "outcome": "success",
            "failure_alert_at": None, "local_receipt": "source.receipt.json", "local_receipt_sha256": "b"*64,
            "archive": "source.aesgcm", "archive_sha256": "c"*64, "offsite_copy": "downloaded.aesgcm",
            "offsite_permissions": "PRIVATE_REVIEWED", "offsite_object_ref": f"B-{number:06d}",
            "restore_receipt": "downloaded.receipt.json" if number == 1009 else None}

    def assess_fixture(self):
        # Coverage unit test only; byte and receipt checks are exercised below.
        with mock.patch.object(continuity, "verify_backup", side_effect=lambda row, *_, **__: 12 if row["restore_receipt"] else None):
            return continuity.assess(self.record, expected_candidate=SHA, expected_source_project_hash=SOURCE_HASH, evidence_root=self.root, now=NOW)

    def test_full_coverage_fixture_passes_scope_but_never_claims_live_dr(self):
        result = self.assess_fixture()
        self.assertTrue(result["scope_continuity_passed"])
        self.assertEqual(result["maximum_snapshot_age_minutes"], 10)
        self.assertFalse(result["operator_evidence_ready_for_review"])
        self.assertFalse(result["permission_and_custody_independently_verified"])
        self.assertFalse(result["promotion_authorized"])
        self.assertFalse(result["archive_encryption_independently_authenticated"])
        self.assertFalse(result["restore_execution_independently_verified"])

    def test_seven_daily_successes_do_not_meet_fifteen_minute_rpo(self):
        self.record["attempts"] = [row for number, row in enumerate(self.record["attempts"]) if number % 144 == 0]
        self.assertFalse(self.assess_fixture()["scope_continuity_passed"])

    def test_missing_initial_or_trailing_recovery_point_is_not_hidden(self):
        self.record["attempts"].pop(0)
        with self.assertRaisesRegex(continuity.ContinuityInvalid, "initial_recovery"):
            self.assess_fixture()
        self.setUp()
        self.record["attempts"] = self.record["attempts"][:-2]
        self.assertFalse(self.assess_fixture()["scope_continuity_passed"])

    def test_failed_attempt_requires_observed_alert_and_bounded_retry(self):
        failed = {key: None for key in self.record["attempts"][0]}
        stamp = self.start+timedelta(minutes=20)
        failed.update(id="B-999999", started_at=stamp.isoformat(), finished_at=stamp.isoformat(), outcome="failed", failure_alert_at=(stamp+timedelta(seconds=60)).isoformat())
        self.record["attempts"].append(failed)
        result = self.assess_fixture()
        self.assertEqual(result["failed_or_interrupted_attempts"], 1)
        self.assertTrue(result["observed_retry_within_rpo"])
        failed["failure_alert_at"] = None
        with self.assertRaises(continuity.ContinuityInvalid):
            self.assess_fixture()

    def test_failure_cannot_reuse_success_receipt(self):
        row = self.record["attempts"][2]
        row.update(outcome="interrupted", failure_alert_at=row["finished_at"])
        with self.assertRaisesRegex(continuity.ContinuityInvalid, "failure_cannot_claim"):
            self.assess_fixture()

    def test_duplicate_id_future_or_short_window_rejected(self):
        for field, value in (("window_end", (NOW+timedelta(minutes=1)).isoformat()), ("window_start", (NOW-timedelta(days=6)).isoformat()), ("candidate_commit", "b"*40)):
            original = self.record[field]
            self.record[field] = value
            with self.subTest(field=field), self.assertRaises(continuity.ContinuityInvalid):
                self.assess_fixture()
            self.record[field] = original
        self.record["attempts"][1]["id"] = self.record["attempts"][0]["id"]
        with self.assertRaisesRegex(continuity.ContinuityInvalid, "identity"):
            self.assess_fixture()

    def artifact(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        path.chmod(0o600)
        return path

    def receipt(self, name, archive_hash, snapshot):
        archive_file = "downloaded.aesgcm" if name.startswith("downloaded") else "source.aesgcm"
        restored = name.startswith("downloaded")
        report = {"schema_version": 1, "receipt_id": ("RESTORE-20261011-000000-00000002" if restored else "DRILL-20261011-000000-00000001"),
            "ok": True, "result": "通過", "created_at": snapshot, "source_project_ref": SOURCE_REF,
            "target_project_ref": "local-postgres-" + ("b" if restored else "a") * 16,
            "target_isolated": True, "target_type": "isolated_local_postgresql",
            "database": {"schemas": ["edoc", "edoc_private"], "table_count": 2, "row_count": 3, "policy_count": 2,
                **{key: True for key in ("restored", "integrity", "counts_match", "row_hashes_match", "permissions_match")}},
            "storage": {"object_count": 0, "bytes": 0, "target_type": "private_local_filesystem", "empty_source": True,
                **{key: True for key in ("restored", "hash_match", "counts_match", "private")}},
            "backup": {"encrypted": True, "algorithm": "AES-256-GCM", "sha256": archive_hash, "file": archive_file, "bytes": (self.root / archive_file).stat().st_size, "snapshot_at": snapshot}, "duration_seconds": 12}
        report.update(rto_minutes=1, rpo_minutes=0, limitations=["synthetic fixture; no live source, restore execution, or offsite proof"])
        data = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        report["receipt_sha256"] = hashlib.sha256(data).hexdigest()
        return self.artifact(name, json.dumps(report).encode())

    def byte_fixture(self):
        row = copy.deepcopy(self.record["attempts"][-1])
        plaintext = self.artifact("synthetic-source", b"synthetic tar bytes; not live backup proof")
        archive = self.root / "source.aesgcm"
        runner.encrypt_file(plaintext, archive, b"k"*32)
        downloaded = self.artifact("downloaded.aesgcm", archive.read_bytes())
        row["archive_sha256"] = continuity.digest(archive)
        receipt = self.receipt("source.receipt.json", row["archive_sha256"], row["snapshot_at"])
        row["local_receipt_sha256"] = continuity.digest(receipt)
        self.receipt("downloaded.receipt.json", row["archive_sha256"], row["snapshot_at"])
        return row, downloaded

    def verify(self, row):
        return continuity.verify_backup(row, self.root, 30, expected_source_project_hash=SOURCE_HASH, now=NOW)

    def test_actual_materialized_bytes_and_original_receipts_are_required(self):
        row, downloaded = self.byte_fixture()
        self.assertEqual(12, self.verify(row))
        corrupted = bytearray(downloaded.read_bytes())
        corrupted[24] ^= 1
        downloaded.write_bytes(corrupted)
        with self.assertRaisesRegex(continuity.ContinuityInvalid, "bytes_hash"):
            self.verify(row)

    def test_local_original_or_virtual_reference_not_offsite_download(self):
        row, _ = self.byte_fixture()
        row["offsite_copy"] = row["archive"]
        with self.assertRaisesRegex(continuity.ContinuityInvalid, "local_original"):
            self.verify(row)
        row["offsite_copy"] = "sediment://virtual-reference"
        with self.assertRaises(continuity.ContinuityInvalid):
            self.verify(row)

    def test_receipt_tamper_missing_restore_or_wrong_snapshot_cannot_pass(self):
        row, _ = self.byte_fixture()
        data = json.loads((self.root / row["restore_receipt"]).read_bytes())
        data["duration_seconds"] = 1
        self.artifact(row["restore_receipt"], json.dumps(data).encode())
        with self.assertRaisesRegex(continuity.ContinuityInvalid, "receipt_hash"):
            self.verify(row)
        for attempt in self.record["attempts"]:
            attempt["restore_receipt"] = None
        self.assertFalse(self.assess_fixture()["scope_continuity_passed"])

    def test_private_files_no_traversal_and_no_self_review(self):
        row, downloaded = self.byte_fixture()
        downloaded.chmod(0o644)
        with self.assertRaisesRegex(continuity.ContinuityInvalid, "private_file"):
            self.verify(row)
        for path in ("../outside", "/etc/passwd", "x\\outside"):
            with self.subTest(path=path), self.assertRaises(continuity.ContinuityInvalid):
                continuity.private_artifact(self.root, path)
        self.record["reviewer_id"] = self.record["custodian_id"]
        with self.assertRaisesRegex(continuity.ContinuityInvalid, "independent"):
            self.assess_fixture()

    def test_historical_window_does_not_hide_current_snapshot_age(self):
        with mock.patch.object(continuity, "verify_backup", return_value=12):
            with self.assertRaisesRegex(continuity.ContinuityInvalid, "window_stale"):
                continuity.assess(self.record, expected_candidate=SHA, expected_source_project_hash=SOURCE_HASH,
                                  evidence_root=self.root, now=NOW+timedelta(days=90))
            result = continuity.assess(self.record, expected_candidate=SHA, expected_source_project_hash=SOURCE_HASH,
                                      evidence_root=self.root, now=NOW+timedelta(minutes=10))
            self.assertEqual(10, result["current_snapshot_age_minutes"])

    def test_wrong_approved_source_hash_cannot_accept_record(self):
        with self.assertRaisesRegex(continuity.ContinuityInvalid, "approved_source"):
            continuity.assess(self.record, expected_candidate=SHA, expected_source_project_hash="b"*64,
                              evidence_root=self.root, now=NOW)

    def resign_receipt(self, row, changes, *, name="source.receipt.json"):
        data = json.loads((self.root/name).read_bytes())
        changes(data)
        data.pop("receipt_sha256", None)
        data["receipt_sha256"] = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        receipt = self.artifact(name, json.dumps(data).encode())
        if name == row["local_receipt"]:
            row["local_receipt_sha256"] = continuity.digest(receipt)

    def test_full_runner_receipt_rejects_wrong_source_count_time_and_target(self):
        row, _ = self.byte_fixture()
        original = (self.root/row["local_receipt"]).read_bytes()
        checks = (
            (lambda data: data.update(source_project_ref="b"*20), "source_project_binding"),
            (lambda data: data["database"].update(table_count=True), "counts_invalid"),
            (lambda data: data.update(created_at=(NOW+timedelta(minutes=1)).isoformat()), "receipt_time"),
            (lambda data: data.update(target_project_ref="a-production-project"), "receipt_identity"),
            (lambda data: data.pop("rpo_minutes"), "receipt_schema"),
        )
        for change, code in checks:
            self.artifact(row["local_receipt"], original)
            self.resign_receipt(row, change)
            with self.subTest(code=code), self.assertRaisesRegex(continuity.ContinuityInvalid, code):
                self.verify(row)

    def test_empty_plaintext_or_truncated_archive_cannot_be_saved_by_metadata(self):
        row, _ = self.byte_fixture()
        for content in (b"", b"not encrypted", continuity.MAGIC + b"n"*12 + b"t"*16):
            self.artifact(row["archive"], content)
            self.artifact(row["offsite_copy"], content)
            row["archive_sha256"] = continuity.digest(self.root/row["archive"])
            receipt = self.receipt(row["local_receipt"], row["archive_sha256"], row["snapshot_at"])
            row["local_receipt_sha256"] = continuity.digest(receipt)
            self.receipt(row["restore_receipt"], row["archive_sha256"], row["snapshot_at"])
            with self.subTest(bytes=len(content)), self.assertRaisesRegex(continuity.ContinuityInvalid, "encrypted_archive_format"):
                self.verify(row)

    def test_direct_assess_root_symlink_ancestor_public_directory_and_hardlink_fail(self):
        import os
        row, _ = self.byte_fixture()
        self.root.chmod(0o755)
        with self.assertRaisesRegex(continuity.ContinuityInvalid, "private_evidence_root"):
            self.assess_fixture()
        self.root.chmod(0o700)
        os.link(self.root/row["local_receipt"], self.root/"linked.receipt.json")
        with self.assertRaisesRegex(continuity.ContinuityInvalid, "private_file"):
            continuity.private_artifact(self.root, "linked.receipt.json")
        (self.root/"linked.receipt.json").unlink()
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(continuity.ContinuityInvalid, "symlink_or_directory"):
            continuity.private_artifact(alias, row["local_receipt"])
        parent = self.root / "unsafe"
        parent.mkdir(mode=0o755)
        parent.chmod(0o755)  # The runner deliberately leaves umask 0077 active.
        self.artifact("unsafe/evidence.json", b"{}")
        with self.assertRaisesRegex(continuity.ContinuityInvalid, "private_directory"):
            continuity.private_artifact(self.root, "unsafe/evidence.json")


if __name__ == "__main__":
    unittest.main()
