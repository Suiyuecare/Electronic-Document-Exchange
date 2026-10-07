"""Acceptance records stay pending; fake identities never enable release."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import readiness_acceptance as acceptance

SHA = "818e2dd89b6b2af60799940c4215ee0f418f1c37"
NOW = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)


class ReadinessAcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.record = acceptance.template(SHA, now=NOW)

    def validate(self):
        return acceptance.validate(self.record, expected_candidate=SHA, evidence_root=self.root, now=NOW)

    def evidence(self, kind="manual_observation", content=b"Redacted synthetic acceptance fixture only."):
        number = len(self.record["evidence"]) + 1
        filename = f"evidence-{number}.txt"
        target = self.root / filename
        target.write_bytes(content)
        identity = f"E-{number:03d}"
        self.record["evidence"].append({"id": identity, "path": filename,
            "sha256": hashlib.sha256(content).hexdigest(), "recorded_at": (NOW-timedelta(hours=1)).isoformat(),
            "retain_until": (NOW+timedelta(days=90)).isoformat(), "redacted": True,
            "kind": kind, "candidate_commit": SHA})
        return identity

    def human_records(self):
        roles = ("主管", "主任", "總務", "行政部門主任", "執行長", "員工")
        for number, (role, finance) in enumerate(zip(acceptance.PARTICIPANT_ROLES, roles), 1):
            row = self.record["human_participants"][role]
            row.update(participant_id=f"P-{number:03d}", finance_role=finance, status="PASS",
                       role_source="finance_authoritative_read", has_admin_or_companywide_permissions=False,
                       personally_operated=True, human_google_oauth_observed=True, synthetic_identity_used=False,
                       checks={key: "PASS" for key in acceptance.SSO_CHECKS}, devices=["desktop", "physical_phone"],
                       evidence_ids=[self.evidence()], reviewer_id="P-900", reviewed_at=NOW.isoformat())

    def pass_gate(self, name, kind="manual_observation"):
        row = self.record["gates"][name]
        row.update(status="PASS", checks={key: "PASS" for key in acceptance.GATES[name]},
                   evidence_ids=[self.evidence(kind)], reviewer_id="P-900", reviewed_at=NOW.isoformat())

    def complete(self):
        self.human_records()
        for gate in acceptance.GATES:
            kind = {"performance_and_devices": "physical_device_measurement", "backup_and_recovery": "restore_report"}.get(gate, "manual_observation")
            self.pass_gate(gate, kind)
        self.record["measurements"].update(environment="hosted_test", warm_workspace_ms=[200]*20,
            a4_editable_ms=[1200]*20, rpo_minutes=10, rto_minutes=20,
            backup_success_dates=[(NOW-timedelta(days=n)).strftime("%Y-%m-%d") for n in range(7)])

    def test_template_all_six_gates_and_people_pending_no_release_authority(self):
        result = self.validate()
        self.assertEqual(6, len(result["gates"]))
        self.assertEqual({"PENDING"}, set(result["gates"].values()))
        self.assertFalse(result["checklist_complete"])
        self.assertFalse(result["promotion_authorized"])
        self.assertFalse(result["human_oauth_independently_verified"])

    def test_complete_record_only_ready_for_manual_review_not_promotion(self):
        self.complete()
        result = self.validate()
        self.assertTrue(result["checklist_complete"])
        self.assertEqual("READY_FOR_MANUAL_REVIEW", result["status"])
        self.assertFalse(result["promotion_authorized"])
        self.assertFalse(result["human_oauth_independently_verified"])

    def test_candidate_change_invalidates_every_prior_record(self):
        self.record["candidate_commit"] = "a"*40
        with self.assertRaisesRegex(acceptance.AcceptanceInvalid, "commit"): self.validate()

    def test_candidate_sha_is_exact_full_lowercase_not_branch_or_prefix(self):
        for value in ("main", "818e2dd", "A"*40, None):
            with self.subTest(value=value), self.assertRaises(acceptance.AcceptanceInvalid): acceptance.template(value)

    def test_schema_bool_is_not_integer_version(self):
        self.record["schema_version"] = True
        with self.assertRaises(acceptance.AcceptanceInvalid): self.validate()

    def test_missing_gate_or_unknown_authority_field_denied(self):
        del self.record["gates"]["operation_documents"]
        with self.assertRaises(acceptance.AcceptanceInvalid): self.validate()
        self.record = acceptance.template(SHA, now=NOW)
        self.record["allow_deploy"] = True
        with self.assertRaises(acceptance.AcceptanceInvalid): self.validate()

    def test_government_exchange_remains_disabled(self):
        self.record["government_exchange"] = "ENABLED"
        with self.assertRaises(acceptance.AcceptanceInvalid): self.validate()

    def test_pass_needs_all_checks_evidence_and_manual_reviewer(self):
        self.pass_gate("operation_documents")
        row = self.record["gates"]["operation_documents"]
        for field, value in (("checks", {key: "PENDING" for key in acceptance.GATES["operation_documents"]}),
                             ("evidence_ids", []), ("reviewer_id", None), ("reviewed_at", None)):
            before = copy.deepcopy(row[field])
            row[field] = value
            with self.subTest(field=field), self.assertRaises(acceptance.AcceptanceInvalid): self.validate()
            row[field] = before

    def test_isolated_fixture_cannot_satisfy_human_record(self):
        self.human_records()
        self.pass_gate("human_sso_and_personnel")
        self.record["evidence"][0]["kind"] = "isolated_test_report"
        with self.assertRaisesRegex(acceptance.AcceptanceInvalid, "not_synthetic"): self.validate()

    def test_signed_identity_probe_flag_does_not_count_as_human_oauth(self):
        self.human_records()
        row = self.record["human_participants"]["manager"]
        row["synthetic_identity_used"] = True
        with self.assertRaisesRegex(acceptance.AcceptanceInvalid, "not_synthetic"): self.validate()
        row["synthetic_identity_used"] = False
        row["human_google_oauth_observed"] = False
        with self.assertRaises(acceptance.AcceptanceInvalid): self.validate()

    def test_handover_remains_pending_without_complete_human_roster(self):
        self.pass_gate("offboarding_handover", "isolated_test_report")
        with self.assertRaisesRegex(acceptance.AcceptanceInvalid, "requires_human"): self.validate()

    def test_ordinary_employee_not_manager_or_administrator(self):
        self.human_records()
        row = self.record["human_participants"]["ordinary_employee"]
        for role in ("主管", "執行長", "系統管理者", "總務", "行政部門主任"):
            row["finance_role"] = role
            with self.subTest(role=role), self.assertRaisesRegex(acceptance.AcceptanceInvalid, "nonprivileged"): self.validate()

    def test_duplicate_person_cannot_fill_ordinary_and_supervisor(self):
        self.human_records()
        self.record["human_participants"]["ordinary_employee"]["participant_id"] = "P-002"
        with self.assertRaisesRegex(acceptance.AcceptanceInvalid, "distinct"): self.validate()

    def test_employee_role_with_admin_permissions_not_least_privilege(self):
        self.human_records()
        self.record["human_participants"]["ordinary_employee"]["has_admin_or_companywide_permissions"] = True
        with self.assertRaisesRegex(acceptance.AcceptanceInvalid, "nonprivileged"): self.validate()

    def test_browser_claimed_role_not_finance_authoritative_read(self):
        self.human_records()
        self.record["human_participants"]["manager"]["role_source"] = "browser_role_claim"
        with self.assertRaises(acceptance.AcceptanceInvalid): self.validate()

    def test_wrong_finance_role_cannot_fill_business_role(self):
        self.human_records()
        self.record["human_participants"]["general_affairs"]["finance_role"] = "員工"
        with self.assertRaisesRegex(acceptance.AcceptanceInvalid, "role_mismatch"): self.validate()

    def test_self_review_is_not_independent_human_review(self):
        self.human_records()
        row = self.record["human_participants"]["manager"]
        row["reviewer_id"] = row["participant_id"]
        with self.assertRaisesRegex(acceptance.AcceptanceInvalid, "independent"): self.validate()

    def test_browser_viewport_emulation_not_physical_phone(self):
        self.human_records()
        self.record["human_participants"]["manager"]["devices"] = ["desktop", "phone_viewport"]
        with self.assertRaises(acceptance.AcceptanceInvalid): self.validate()

    def test_unknown_or_skipped_status_is_never_pass(self):
        for status in ("SKIP", "SUCCESS", True, None):
            self.record["gates"]["operation_documents"]["status"] = status
            with self.subTest(status=status), self.assertRaises(acceptance.AcceptanceInvalid): self.validate()

    def test_missing_tampered_or_wrong_candidate_evidence_denied(self):
        ref = self.evidence()
        row = self.record["evidence"][0]
        for field, value in (("path", "missing.txt"), ("sha256", "f"*64), ("candidate_commit", "b"*40), ("redacted", False)):
            before = row[field]
            row[field] = value
            with self.subTest(field=field), self.assertRaises(acceptance.AcceptanceInvalid): self.validate()
            row[field] = before
        self.assertEqual(ref, row["id"])

    def test_expired_or_future_evidence_is_not_retained_proof(self):
        self.evidence()
        row = self.record["evidence"][0]
        row["retain_until"] = NOW.isoformat()
        with self.assertRaisesRegex(acceptance.AcceptanceInvalid, "expired"): self.validate()
        row["retain_until"] = (NOW+timedelta(days=90)).isoformat()
        row["recorded_at"] = (NOW+timedelta(minutes=1)).isoformat()
        with self.assertRaises(acceptance.AcceptanceInvalid): self.validate()

    def test_absolute_traversal_or_symlink_evidence_denied(self):
        self.evidence()
        row = self.record["evidence"][0]
        for path in ("/etc/passwd", "../outside.txt", "x\\..\\outside.txt"):
            row["path"] = path
            with self.subTest(path=path), self.assertRaises(acceptance.AcceptanceInvalid): self.validate()
        (self.root/"link.txt").symlink_to(self.root/"evidence-1.txt")
        row["path"] = "link.txt"
        with self.assertRaisesRegex(acceptance.AcceptanceInvalid, "symlink"): self.validate()

    def test_credentials_and_identity_not_allowed_in_record_or_text_artifacts(self):
        for content in (b"Bearer synthetic-secret", b"person@example.invalid", b"vcp_SyntheticCredentials", b"https://private.example.invalid"):
            self.record = acceptance.template(SHA, now=NOW)
            self.evidence(content=content)
            with self.subTest(content=content[:8]), self.assertRaisesRegex(acceptance.AcceptanceInvalid, "sensitive"): self.validate()
        self.record = acceptance.template(SHA, now=NOW)
        self.record["human_participants"]["employee"]["participant_id"] = "real-name@example.invalid"
        with self.assertRaisesRegex(acceptance.AcceptanceInvalid, "sensitive"): self.validate()

    def test_duplicate_or_unindexed_evidence_reference_denied(self):
        self.pass_gate("operation_documents")
        row = self.record["gates"]["operation_documents"]
        for refs in (["E-999"], ["E-001", "E-001"]):
            row["evidence_ids"] = refs
            with self.subTest(refs=refs), self.assertRaises(acceptance.AcceptanceInvalid): self.validate()

    def test_local_latency_cannot_satisfy_hosted_performance(self):
        self.complete()
        self.record["measurements"]["environment"] = "local_isolated"
        with self.assertRaisesRegex(acceptance.AcceptanceInvalid, "hosted"): self.validate()

    def test_too_few_samples_and_p95_target_failure_not_hidden(self):
        self.complete()
        self.record["measurements"]["warm_workspace_ms"] = [20]*19
        with self.assertRaises(acceptance.AcceptanceInvalid): self.validate()
        self.record["measurements"]["warm_workspace_ms"] = [600]*20
        with self.assertRaisesRegex(acceptance.AcceptanceInvalid, "not_met"): self.validate()

    def test_invalid_sample_boolean_nan_and_negative_rejected(self):
        for sample in (True, float("nan"), -1, "200"):
            self.record["measurements"]["warm_workspace_ms"] = [sample]
            with self.subTest(sample=sample), self.assertRaises(acceptance.AcceptanceInvalid): self.validate()

    def test_backup_one_day_or_gaps_not_seven_successful_days(self):
        self.complete()
        row = self.record["measurements"]
        for dates in (["2026-10-08"], ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05", "2026-10-06", "2026-10-08"]):
            row["backup_success_dates"] = dates
            with self.subTest(dates=dates), self.assertRaisesRegex(acceptance.AcceptanceInvalid, "consecutive"): self.validate()

    def test_backup_rpo_and_rto_measured_targets_required(self):
        self.complete()
        row = self.record["measurements"]
        for field, value in (("rpo_minutes", 16), ("rto_minutes", 31), ("rto_minutes", None), ("rpo_minutes", True)):
            before = row[field]
            row[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(acceptance.AcceptanceInvalid, "not_met"): self.validate()
            row[field] = before

    def test_restore_and_physical_evidence_kinds_required(self):
        self.complete()
        for gate in ("backup_and_recovery", "performance_and_devices"):
            ref = self.record["gates"][gate]["evidence_ids"][0]
            row = next(item for item in self.record["evidence"] if item["id"] == ref)
            before = row["kind"]
            row["kind"] = "isolated_test_report"
            with self.subTest(gate=gate), self.assertRaises(acceptance.AcceptanceInvalid): self.validate()
            row["kind"] = before

    def test_cli_pending_is_nonzero_and_logs_no_source_values(self):
        target = self.root/"checklist.json"
        target.write_text(json.dumps(self.record))
        actual_validate = acceptance.validate
        with mock.patch("sys.stdout", new_callable=io.StringIO) as output, mock.patch.object(
                acceptance, "validate", side_effect=lambda value, **kwargs: actual_validate(value, **kwargs, now=NOW)):
            code = acceptance.main(["--candidate-commit", SHA, "--checklist", str(target), "--evidence-root", str(self.root)])
        self.assertEqual(2, code)
        self.assertFalse(json.loads(output.getvalue())["promotion_authorized"])

    def test_cli_duplicate_json_keys_rejected_without_echo(self):
        target = self.root/"checklist.json"
        target.write_text('{"private_value":"Bearer never-log-this", "private_value":1}')
        with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            code = acceptance.main(["--candidate-commit", SHA, "--checklist", str(target), "--evidence-root", str(self.root)])
        self.assertEqual(1, code)
        self.assertNotIn("never-log-this", output.getvalue())
        self.assertFalse(json.loads(output.getvalue())["schema_valid"])

    def test_validator_has_no_network_or_impersonation_side_effect(self):
        import socket
        with mock.patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            self.assertFalse(self.validate()["promotion_authorized"])


if __name__ == "__main__":
    unittest.main()
