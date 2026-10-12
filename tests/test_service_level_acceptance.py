import copy
from datetime import datetime, timezone
import unittest

from tools import service_level_acceptance as slo

SHA = "a"*40
NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


class ServiceLevelAcceptanceTests(unittest.TestCase):
    def record(self, environment="hosted_test", physical=True):
        profiles, samples = [], []
        for index, device in enumerate(("desktop", "tablet", "phone"), 1):
            profile = f"P-{index:03d}"
            profiles.append({"id": profile, "device": device, "network": "office_wifi", "physical_device": physical})
            for metric, document, duration in (("workspace_interactive", "workspace", 250), ("pdf_editable", "typical_a4", 1300)):
                for _ in range(30):
                    samples.append({"id": f"S-{len(samples)+1:04d}", "profile_id": profile, "metric": metric,
                                    "document_profile": document, "cache_state": "warm", "duration_ms": duration,
                                    "outcome": "success", "bytes": 1024, "pages": 2, "recorded_at": NOW.isoformat()})
        return {"schema_version": 1, "candidate_commit": SHA, "environment": environment,
                "government_exchange": "DISABLED", "profiles": profiles, "samples": samples}

    def assess(self, value):
        return slo.assess(value, expected_candidate=SHA, now=NOW)

    def test_all_profiles_need_thirty_each_and_never_authorize_release(self):
        result = self.assess(self.record())
        self.assertTrue(result["hosted_physical_evidence_ready_for_review"])
        self.assertFalse(result["physical_claim_independently_verified"])
        self.assertFalse(result["promotion_authorized"])
        self.assertEqual([30]*6, [row["samples"] for row in result["profile_results"]])

    def test_local_or_emulated_profiles_cannot_pass_hosted_device_gate(self):
        for environment, physical in (("local_isolated", True), ("hosted_test", False)):
            result = self.assess(self.record(environment, physical))
            self.assertTrue(result["scope_slo_passed"])
            self.assertFalse(result["hosted_physical_evidence_ready_for_review"])

    def test_twenty_nine_samples_not_covered_by_other_device_samples(self):
        record = self.record()
        record["samples"].pop(0)
        result = self.assess(record)
        self.assertFalse(result["scope_slo_passed"])
        self.assertEqual(29, result["profile_results"][0]["samples"])

    def test_cold_starts_are_reported_separately_not_blended(self):
        record = self.record()
        cold = copy.deepcopy(record["samples"][0])
        cold.update(id="S-0999", cache_state="cold", duration_ms=9000)
        record["samples"].append(cold)
        result = self.assess(record)
        self.assertTrue(result["scope_slo_passed"])
        self.assertEqual(9000, result["separate_observations"][0]["p95_ms"])

    def test_failure_is_retained_even_when_p95_fast(self):
        record = self.record()
        record["samples"][0]["outcome"] = "timeout"
        result = self.assess(record)
        self.assertFalse(result["scope_slo_passed"])
        self.assertEqual(1, result["profile_results"][0]["failed_samples"])
        self.assertEqual(30, result["profile_results"][0]["samples"])

    def test_slow_tail_fails_nearest_rank_p95(self):
        record = self.record()
        for row in record["samples"][:2]: row["duration_ms"] = 501
        result = self.assess(record)
        self.assertEqual(501, result["profile_results"][0]["p95_ms"])
        self.assertFalse(result["scope_slo_passed"])

    def test_duplicate_wrong_commit_unknown_scope_and_secrets_fail_closed(self):
        for change in (lambda r: r.update(candidate_commit="b"*40),
                       lambda r: r["samples"].append(copy.deepcopy(r["samples"][0])),
                       lambda r: r["profiles"][0].update(network="https://private.invalid"),
                       lambda r: r.update(extra=True),
                       lambda r: r.update(government_exchange="ENABLED")):
            record = self.record(); change(record)
            with self.assertRaises((slo.EvidenceInvalid, ValueError)): self.assess(record)

    def test_unbounded_nonfinite_boolean_future_and_naive_timing_rejected(self):
        for field, value in (("duration_ms", True), ("duration_ms", -1), ("duration_ms", float("nan")),
                             ("duration_ms", 10**1000), ("recorded_at", "2027-01-01T00:00:00Z"),
                             ("recorded_at", "2026-10-11T00:00:00"), ("pages", False), ("bytes", 0)):
            record = self.record(); record["samples"][30][field] = value
            with self.subTest(field=field, value=repr(value)[:30]), self.assertRaises((slo.EvidenceInvalid, ValueError, OverflowError)):
                self.assess(record)

    def test_hosted_loopback_claim_rejected(self):
        record = self.record(); record["profiles"][0]["network"] = "loopback"
        with self.assertRaises(slo.EvidenceInvalid): self.assess(record)


if __name__ == "__main__": unittest.main()
