from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import backend


SPEC = importlib.util.spec_from_file_location(
    "receipt_fixture_runner", Path(__file__).resolve().parents[1] / "scripts/backup_restore_drill.py"
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class BackupRunnerEvidenceTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.now = datetime.now(timezone.utc)
        self.started_at = (self.now - timedelta(seconds=5)).timestamp()
        self.source_ref = "a" * 20
        self.drill_id = "DRILL-20261008-000000-A1B2C3"
        plaintext = root / "synthetic-archive"
        plaintext.write_bytes(b"deidentified backup acceptance fixture")
        archive = root / (self.drill_id + ".tar.aesgcm")
        runner.encrypt_file(plaintext, archive, b"s" * 32)
        storage = runner.restore_storage([], root, root / "restored-storage")
        manifest = {
            "source_snapshot_at": (self.now - timedelta(seconds=2)).isoformat(),
            "created_at": self.now.isoformat(), "source_project_ref": self.source_ref,
            "database": {"tables": [{"rows": 1}, {"rows": 2}], "policies": ["synthetic-policy"]},
        }
        # Use the actual receipt writer; no alternate/imaginary receipt format.
        self.receipt = runner.save_receipt(
            manifest, archive, storage, 2, self.drill_id,
            SimpleNamespace(rto_target_minutes=30, rpo_target_minutes=15), root,
        )
        self.now = datetime.now(timezone.utc)

    @staticmethod
    def signed(receipt):
        receipt = copy.deepcopy(receipt)
        receipt.pop("receipt_sha256", None)
        receipt["receipt_sha256"] = hashlib.sha256(runner.canonical(receipt)).hexdigest()
        return receipt

    def validate(self, evidence=None, **overrides):
        arguments = {
            "drill_id": self.drill_id, "source_ref": self.source_ref,
            "rto_target": 30, "rpo_target": 15,
            "request_started_at": self.started_at, "checked_at": self.now,
        }
        arguments.update(overrides)
        return backend.validate_backup_restore_runner_evidence(
            self.receipt if evidence is None else evidence, **arguments
        )

    def test_actual_runner_receipt_passes_without_fabricated_fields(self):
        result = self.validate()
        self.assertTrue(result["ok"])
        self.assertFalse(result["blocked"])
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["receipt_id"], self.drill_id)
        self.assertEqual(result["receipt_verification"], "canonical_hash_and_request_matched")
        self.assertEqual(result["row_count"], 3)
        self.assertEqual(result["storage_object_count"], 0)
        self.assertTrue(result["storage"]["empty_source"])
        self.assertFalse(result["unattendedCloudDR"])
        self.assertEqual(result["offsiteValidation"], "not_verified_by_restore_receipt")
        self.assertEqual(result["pdfSampleValidation"], "not_performed_by_restore_receipt")

    def test_invalid_expected_request_context_is_not_trusted(self):
        for override in ({"source_ref": ""}, {"source_ref": "not-a-project"}, {"drill_id": "../synthetic-invalid"}, {"rto_target": True}, {"rpo_target": "15"}):
            with self.subTest(override=override):
                result = self.validate(**override)
                self.assertFalse(result["ok"])
                self.assertFalse(result["checks"]["receipt_valid"])

    def test_partial_summary_or_non_object_never_becomes_verified_receipt(self):
        partial = {
            "ok": True, "receipt_id": self.drill_id, "receipt_sha256": "a" * 64,
            "target_isolated": True, "target_project_ref": "different-project",
            "database": {"restored": True, "integrity": True, "counts_match": True},
            "storage": {"restored": True, "hash_match": True, "counts_match": True},
            "rto_minutes": 1,
        }
        for evidence in ({}, [], "synthetic-invalid", partial):
            with self.subTest(evidence=evidence):
                result = self.validate(evidence)
                self.assertFalse(result["ok"])
                self.assertFalse(result["checks"]["receipt_valid"])
                self.assertEqual(result["receipt_verification"], "unverified")

    def test_complete_receipt_hash_is_recomputed_not_only_format_checked(self):
        for field in ("receipt_sha256", "database"):
            with self.subTest(field=field):
                receipt = copy.deepcopy(self.receipt)
                if field == "receipt_sha256":
                    receipt[field] = "a" * 64
                else:
                    receipt[field]["row_count"] = 999
                result = self.validate(receipt)
                self.assertFalse(result["ok"])
                self.assertEqual(result["error_code"], "restore_runner_receipt_hash_mismatch")
                self.assertFalse(result["checks"]["receipt_hash_match"])

    def test_prior_receipt_other_source_or_nonisolated_target_are_rejected(self):
        patches = [
            {"receipt_id": "DRILL-20261007-000000-A1B2C3"},
            {"source_project_ref": "b" * 20},
            {"target_project_ref": self.source_ref},
            {"target_project_ref": "remote-production"},
            {"target_type": "production"}, {"target_isolated": "false"},
        ]
        for patch in patches:
            with self.subTest(patch=patch):
                result = self.validate(self.signed({**self.receipt, **patch}))
                self.assertFalse(result["ok"])
                self.assertEqual(result["error_code"], "restore_runner_receipt_context_mismatch")
                self.assertFalse(result["checks"]["receipt_valid"])

    def test_bool_lookalikes_missing_integrity_or_private_storage_fail_closed(self):
        fields = [
            ("database", "restored"), ("database", "integrity"),
            ("database", "counts_match"), ("database", "row_hashes_match"),
            ("database", "permissions_match"), ("storage", "restored"),
            ("storage", "hash_match"), ("storage", "counts_match"),
            ("storage", "private"), ("backup", "encrypted"),
        ]
        for group, name in fields:
            for value in ("false", 1, False, None):
                with self.subTest(group=group, name=name, value=value):
                    receipt = copy.deepcopy(self.receipt)
                    receipt[group][name] = value
                    result = self.validate(self.signed(receipt))
                    self.assertFalse(result["ok"])
                    self.assertEqual(result["error_code"], "restore_runner_integrity_evidence_incomplete")
        for value in ("false", 1, False, None):
            with self.subTest(upstream_ok=value):
                result = self.validate(self.signed({**self.receipt, "ok": value}))
                self.assertFalse(result["ok"])

    def test_count_scope_empty_storage_and_archive_evidence_are_not_assumed(self):
        cases = [
            ("database", "schemas", ["public"]), ("database", "table_count", 0),
            ("database", "row_count", True), ("database", "policy_count", -1),
            ("storage", "target_type", "public_bucket"),
            ("storage", "object_count", "0"), ("storage", "empty_source", False),
            ("storage", "bytes", 12), ("backup", "algorithm", "none"),
            ("backup", "sha256", "not-a-hash"), ("backup", "bytes", 0),
            ("backup", "file", "../private-file.tar.aesgcm"),
        ]
        for group, name, value in cases:
            with self.subTest(group=group, name=name, value=value):
                receipt = copy.deepcopy(self.receipt)
                receipt[group][name] = value
                self.assertFalse(self.validate(self.signed(receipt))["ok"])

    def test_missing_timing_or_nonfinite_measurement_cannot_default_to_zero(self):
        for field in ("rto_minutes", "rpo_minutes", "duration_seconds", "created_at"):
            with self.subTest(field=field):
                receipt = copy.deepcopy(self.receipt)
                receipt.pop(field)
                result = self.validate(self.signed(receipt))
                self.assertFalse(result["ok"])
                self.assertFalse(result["checks"]["receipt_valid"])
        for field, value in (
            ("rto_minutes", True), ("rto_minutes", "1"), ("rto_minutes", 0),
            ("rpo_minutes", False), ("rpo_minutes", -1), ("rpo_minutes", "0"),
            ("duration_seconds", True), ("duration_seconds", -1),
            ("duration_seconds", float("nan")), ("duration_seconds", float("inf")),
            ("duration_seconds", 10 ** 1000),
        ):
            with self.subTest(field=field, value=value):
                result = self.validate(self.signed({**self.receipt, field: value}))
                self.assertFalse(result["ok"])

    def test_exceeded_or_underreported_rto_rpo_preserves_integrity_but_is_blocked(self):
        for patch in (
            {"rto_minutes": 31, "duration_seconds": 1801},
            {"rto_minutes": 1, "duration_seconds": 61},
            {"rpo_minutes": 16},
        ):
            with self.subTest(patch=patch):
                result = self.validate(self.signed({**self.receipt, **patch}))
                self.assertFalse(result["ok"])
                self.assertTrue(result["checks"]["receipt_valid"])
                self.assertTrue(result["checks"]["database_restored"])
                self.assertTrue(result["checks"]["storage_restored"])
        receipt = copy.deepcopy(self.receipt)
        receipt["backup"]["snapshot_at"] = (self.now - timedelta(minutes=2)).isoformat()
        receipt["rpo_minutes"] = 1
        self.assertFalse(self.validate(self.signed(receipt))["checks"]["rpo_ok"])

    def test_stale_future_naive_or_malformed_receipt_time_is_rejected(self):
        for value in (
            "not-a-time", None, self.now.replace(tzinfo=None).isoformat(),
            (self.now + timedelta(minutes=2)).isoformat(),
            (self.now - timedelta(minutes=2)).isoformat(),
        ):
            with self.subTest(value=value):
                result = self.validate(self.signed({**self.receipt, "created_at": value}))
                self.assertFalse(result["ok"])
                self.assertEqual(result["error_code"], "restore_runner_timestamp_evidence_invalid")
        receipt = copy.deepcopy(self.receipt)
        receipt["backup"]["snapshot_at"] = (self.now + timedelta(minutes=1)).isoformat()
        self.assertFalse(self.validate(self.signed(receipt))["ok"])

    def test_invalid_snapshot_timestamp_is_never_echoed_in_blocked_response(self):
        for sensitive_value in ("private-key-synthetic-canary", {"token": "synthetic-private-canary"}, ["synthetic-private-canary"]):
            with self.subTest(value=sensitive_value):
                receipt = copy.deepcopy(self.receipt)
                receipt["backup"]["snapshot_at"] = sensitive_value
                result = self.validate(self.signed(receipt))
                self.assertFalse(result["ok"])
                self.assertEqual(result["error_code"], "restore_runner_timestamp_evidence_invalid")
                self.assertNotIn("snapshot_at", result["backup"])
                self.assertNotIn("canary", json.dumps(result))

    def test_provider_extras_are_not_returned_as_sensitive_ui_or_audit_fields(self):
        receipt = copy.deepcopy(self.receipt)
        receipt["database"]["rows"] = [{"synthetic_secret": "must-not-return"}]
        receipt["storage"]["paths"] = ["must-not-return"]
        result = self.validate(self.signed(receipt))
        self.assertTrue(result["ok"])
        self.assertNotIn("must-not-return", json.dumps(result))

    def call_endpoint(self, evidence_factory):
        audit_rows = []
        requests = []

        def response(request, **_kwargs):
            payload = json.loads(request.data)
            requests.append(payload)
            value = evidence_factory(payload)
            return io.BytesIO(json.dumps(value, allow_nan=True).encode("utf-8"))

        with (
            mock.patch.object(backend, "SUPABASE_URL", "https://" + self.source_ref + ".supabase.co"),
            mock.patch.object(backend, "EDOC_RESTORE_DRILL_ENDPOINT", "https://isolated-runner.example.test/restore"),
            mock.patch.object(backend, "EDOC_RESTORE_DRILL_TOKEN", "synthetic-test-token"),
            mock.patch.object(backend, "_urlopen_no_redirect", side_effect=response),
            mock.patch.object(backend, "supabase_insert", side_effect=lambda _table, row: audit_rows.append(row)),
        ):
            result = backend.supabase_backup_restore_drill({})
        return result, requests, audit_rows

    def correlated_receipt(self, request):
        receipt = copy.deepcopy(self.receipt)
        receipt["receipt_id"] = request["drill_id"]
        receipt["backup"]["file"] = request["drill_id"] + ".tar.aesgcm"
        return self.signed(receipt)

    def test_endpoint_records_success_only_for_verified_current_receipt(self):
        result, requests, audit_rows = self.call_endpoint(self.correlated_receipt)
        self.assertTrue(result["ok"])
        self.assertEqual(result["id"], result["receipt_id"])
        self.assertEqual(len(requests), 1)
        self.assertNotIn("pdf_open_sample", requests[0]["required_checks"])
        self.assertEqual(audit_rows[0]["result"], "success")
        self.assertNotIn("synthetic-test-token", json.dumps(result) + json.dumps(audit_rows))

    def test_endpoint_returns_blocked_not_500_for_unverifiable_or_wrong_receipts(self):
        for factory in (lambda _request: [], lambda _request: self.receipt, lambda _request: {"ok": True, "receipt_sha256": "a" * 64}):
            with self.subTest(factory=factory):
                result, _requests, audit_rows = self.call_endpoint(factory)
                self.assertFalse(result["ok"])
                self.assertTrue(result["blocked"])
                self.assertEqual(result["receipt_verification"], "unverified")
                self.assertEqual(audit_rows[0]["result"], "failed")

    def test_endpoint_rejects_invalid_targets_without_contacting_runner(self):
        for name, value in (
            ("rto_target_minutes", True), ("rto_target_minutes", "30"),
            ("rto_target_minutes", 0), ("rto_target_minutes", 121),
            ("rpo_target_minutes", None), ("rpo_target_minutes", -1),
            ("rpo_target_minutes", 1441),
        ):
            with self.subTest(name=name, value=value), mock.patch.object(backend, "_urlopen_no_redirect") as transport, mock.patch.object(backend, "supabase_insert"):
                result = backend.supabase_backup_restore_drill({name: value})
                self.assertFalse(result["ok"])
                self.assertEqual(result["error_code"], "restore_runner_targets_invalid")
                transport.assert_not_called()

    def test_missing_runner_remains_explicitly_unverified_without_transport(self):
        with mock.patch.object(backend, "EDOC_RESTORE_DRILL_ENDPOINT", ""), mock.patch.object(backend, "EDOC_RESTORE_DRILL_TOKEN", ""), mock.patch.object(backend, "_urlopen_no_redirect") as transport, mock.patch.object(backend, "supabase_insert"):
            result = backend.supabase_backup_restore_drill({})
        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertEqual(result["receipt_verification"], "unverified")
        self.assertFalse(result["unattendedCloudDR"])
        transport.assert_not_called()

    def test_endpoint_caps_receipt_size_and_does_not_echo_provider_content(self):
        result, _requests, audit_rows = self.call_endpoint(lambda _request: {"synthetic_private": "must-not-return" * 6000})
        self.assertFalse(result["ok"])
        self.assertEqual(result["detail"], "isolated_restore_runner_failed")
        self.assertNotIn("must-not-return", json.dumps(result) + json.dumps(audit_rows))


if __name__ == "__main__":
    unittest.main()
