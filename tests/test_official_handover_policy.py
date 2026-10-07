"""Synthetic offboarding policy tests. No person, Google or production calls."""
import copy
import json
import unittest

import official_handover as policy


class HandoverPolicyTest(unittest.TestCase):
    def setUp(self):
        self.company = {"id": "COMPANY-TEST", "finance_tenant_id": "TENANT-TEST",
                        "source_system": "finance", "status": "active"}
        self.document = {"id": "DOCUMENT-TEST", "company_id": self.company["id"],
                         "applicant_id": "APPLICANT-TEST", "content_revision": 3,
                         "current_status": "pending_department_head", "current_step": "department_head",
                         "updated_at": "2026-10-07 08:00:00", "stamped_file_id": None,
                         "title": "Synthetic document", "subject": "Synthetic subject",
                         "description": "Synthetic content", "source_type": "blank_editor",
                         "dispatch_no": "DO-NOT-COPY", "metadata_json": {"secret": "DO-NOT-COPY"}}
        self.proposer = self.user("PROPOSER-TEST", "總務")
        self.confirmer = self.user("CONFIRMER-TEST", "行政部主任")
        self.former = self.user("FORMER-TEST", "主任", status="停用")
        self.successor = self.user("SUCCESSOR-TEST", "主任")
        self.steps = [self.step("S1", 1, "applicant_manager", "MANAGER-TEST", "approved"),
                      self.step("S2", 2, "department_head", self.former["id"]),
                      self.step("S3", 3, "applicant_confirm", "APPLICANT-TEST")]
        self.steps[0].update(decision_actor_user_id="ACTUAL-DELEGATE-TEST",
                             approved_at="2026-10-07 07:00:00", comment="Actual decision",
                             decision_evidence_json={"files": [{"sha256": "A" * 64}]})
        self.stamp = {"id": "STAMP-TEST", "status": "pending", "claim_token": None,
                      "updated_at": self.document["updated_at"]}

    def user(self, identity, role, *, status="啟用"):
        return {"id": identity, "name": identity, "role": role, "status": status,
                "company_id": self.company["id"], "finance_tenant_id": self.company["finance_tenant_id"],
                "account_source": "finance"}

    def step(self, identity, order, key, actor, status="pending"):
        return {"id": identity, "document_id": self.document["id"], "workflow_generation": 1,
                "step_order": order, "step_key": key, "step_name": key, "approver_user_id": actor,
                "approver_name": actor, "approver_role": "主任", "status": status,
                "comment": "Old pending note", "approved_at": None, "review_started_at": "old",
                "decision_actor_user_id": None, "decision_evidence_json": {"stale_review": True},
                "created_at": "old", "updated_at": "old"}

    def proposal(self, **changes):
        payload = {"operation_id": "HANDOVER-OPERATION-0001", "kind": "pending_approver",
                   "reason": "Synthetic offboarding handover", "expected_fingerprint":
                   policy.handover_fingerprint(self.document, self.steps, self.stamp), **changes}
        return policy.propose_handover(self.document, self.steps, self.company, self.proposer,
                                       self.former, self.successor, payload,
                                       timestamp="2026-10-07 09:00:00", stamp=self.stamp)

    def confirm(self, request=None):
        return policy.confirm_handover(request or self.proposal(), self.document, self.steps,
                                       self.company, self.confirmer, self.proposer, self.former,
                                       self.successor, timestamp="2026-10-07 09:01:00", stamp=self.stamp)

    def test_proposal_does_not_mutate_or_grant_access(self):
        before = copy.deepcopy((self.document, self.steps, self.former, self.successor))
        request = self.proposal()
        self.assertEqual("pending", request["status"])
        self.assertIsNone(request["confirmer_user_id"])
        self.assertEqual(before, (self.document, self.steps, self.former, self.successor))

    def test_review_handover_preserves_actual_approved_actor_and_original(self):
        original = copy.deepcopy((self.document, self.steps))
        plan = self.confirm()
        rows = plan["replacement_steps"]
        self.assertEqual([2, 2, 2], [row["workflow_generation"] for row in rows])
        self.assertEqual("ACTUAL-DELEGATE-TEST", rows[0]["decision_actor_user_id"])
        self.assertEqual("Actual decision", rows[0]["comment"])
        self.assertEqual(self.steps[0]["decision_evidence_json"]["files"], rows[0]["decision_evidence_json"]["files"])
        self.assertEqual(self.successor["id"], rows[1]["approver_user_id"])
        self.assertEqual("APPLICANT-TEST", rows[2]["approver_user_id"])
        self.assertEqual(["S2", "S3"], plan["skip_step_ids"])
        self.assertTrue(set(row["id"] for row in rows).isdisjoint(row["id"] for row in self.steps))
        self.assertEqual(original, (self.document, self.steps))
        for row in rows[1:]:
            self.assertNotIn("stale_review", row["decision_evidence_json"])
            self.assertIsNone(row["decision_actor_user_id"])
            self.assertIsNone(row["approved_at"])
        self.assertEqual("2026-10-07 09:01:00", rows[1]["review_started_at"])
        self.assertIsNone(rows[2]["review_started_at"])

    def test_deterministic_step_ids_do_not_duplicate_on_identical_plan(self):
        request = self.proposal()
        self.assertEqual(self.confirm(request), self.confirm(request))

    def test_proposer_and_confirmer_cannot_be_same_person_or_parties(self):
        request = self.proposal()
        for actor in (self.proposer, self.successor, self.former):
            with self.subTest(actor=actor["id"]):
                self.confirmer = {**actor, "role": "行政部主任", "status": "啟用"}
                with self.assertRaises(PermissionError): self.confirm(request)

    def test_sysadmin_ceo_employee_do_not_gain_business_confirmation(self):
        request = self.proposal()
        for role in ("系統管理者", "執行長", "員工", "總務"):
            self.confirmer["role"] = role
            with self.subTest(role=role), self.assertRaises(PermissionError): self.confirm(request)

    def test_invalid_scope_and_live_roles_deny_proposals(self):
        for who, field, value in (
            ("proposer", "role", "執行長"), ("proposer", "status", "停用"),
            ("former", "status", "啟用"), ("former", "account_source", "manual"),
            ("successor", "status", "停用"), ("successor", "company_id", "OTHER"),
            ("successor", "finance_tenant_id", "OTHER"), ("successor", "account_source", "manual"),
            ("successor", "role", "員工"), ("successor", "id", "APPLICANT-TEST"),
            ("successor", "id", "MANAGER-TEST"), ("proposer", "id", "SUCCESSOR-TEST")):
            with self.subTest(who=who, field=field, value=value):
                original = getattr(self, who)
                setattr(self, who, {**original, field: value})
                with self.assertRaises(PermissionError): self.proposal()
                setattr(self, who, original)

    def test_scope_and_role_are_revalidated_at_confirmation(self):
        request = self.proposal()
        for who, field, value in (("successor", "status", "停用"), ("former", "status", "啟用"),
                                   ("confirmer", "finance_tenant_id", "OTHER"), ("proposer", "role", "員工"),
                                   ("successor", "role", "員工")):
            original = getattr(self, who)
            setattr(self, who, {**original, field: value})
            with self.subTest(who=who, field=field), self.assertRaises(PermissionError): self.confirm(request)
            setattr(self, who, original)

    def test_changed_version_assignment_decision_or_stamp_requires_reload(self):
        request = self.proposal()
        for section, field, value in (("document", "content_revision", 4), ("document", "updated_at", "later"),
                                     ("document", "current_step", "applicant_manager"),
                                     ("stamp", "claim_token", "CLAIMED")):
            original = getattr(self, section)
            setattr(self, section, {**original, field: value})
            with self.subTest(section=section, field=field), self.assertRaises(policy.HandoverConflict): self.confirm(request)
            setattr(self, section, original)
        self.steps[0]["decision_actor_user_id"] = "CHANGED-ACTOR"
        with self.assertRaises(policy.HandoverConflict): self.confirm(request)

    def test_irreversible_or_terminal_review_states_are_not_reassigned(self):
        for status in policy.NON_REVIEW_STATES:
            self.document["current_status"] = status
            with self.subTest(status=status), self.assertRaises(policy.HandoverConflict): self.proposal()

    def test_corrupt_or_foreign_workflow_is_not_repaired_by_guess(self):
        for field, value in (("document_id", "FOREIGN"), ("step_key", "applicant_manager"),
                             ("step_order", 1), ("id", "S1")):
            original = self.steps[1]
            self.steps[1] = {**original, field: value}
            with self.subTest(field=field), self.assertRaises(ValueError): self.proposal()
            self.steps[1] = original

    def test_operation_and_reason_validation(self):
        for changes in ({"operation_id": "bad"}, {"operation_id": "x" * 121},
                        {"kind": "auto_admin"}, {"reason": "短"}, {"reason": "x" * 2001}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError): self.proposal(**changes)
        with self.assertRaises(policy.HandoverConflict): self.proposal(expected_fingerprint="forged")

    def test_pending_request_cannot_be_confirmed_twice_by_policy(self):
        request = self.confirm()["request"]
        with self.assertRaises(policy.HandoverConflict): self.confirm(request)

    def followup(self):
        self.former = self.user("APPLICANT-TEST", "員工", status="停用")
        self.successor = self.user("OWNER-TEST", "員工")
        return self.confirm(self.proposal(kind="followup_owner"))

    def test_followup_is_separate_and_does_not_rewrite_approved_or_sent_case(self):
        self.document.update(current_status="dispatched", stamped_file_id="FINAL-ORIGINAL")
        self.stamp.update(status="stamped", claim_token="COMMITTED")
        original = copy.deepcopy((self.document, self.steps))
        plan = self.followup()
        self.assertEqual([], plan["replacement_steps"])
        self.assertEqual({}, plan["document_patch"])
        self.assertEqual("APPLICANT-TEST", plan["followup_binding"]["original_applicant_id"])
        self.assertEqual("OWNER-TEST", plan["followup_binding"]["process_owner_user_id"])
        self.assertEqual(original, (self.document, self.steps))

    def test_linked_application_strips_number_id_metadata_files_and_approval(self):
        self.document["current_status"] = "rejected"
        plan = self.followup()
        original = copy.deepcopy(self.document)
        seed = policy.linked_application_seed(self.document, plan["followup_binding"], self.company,
                                             self.successor, today="2026-10-07")
        self.assertEqual(self.document["description"], seed["payload"]["description"])
        self.assertEqual("2026-10-07", seed["payload"]["dispatch_date"])
        for key in ("id", "dispatch_no", "applicant_id", "applicant_name", "metadata_json", "stamped_file_id",
                    "approval_steps", "current_status", "content_revision", "seal_id"):
            self.assertNotIn(key, seed["payload"])
        self.assertEqual(original, self.document)
        self.assertTrue(seed["requires_fresh_files"])
        self.assertTrue(seed["requires_full_approval"])

    def test_new_application_not_permitted_for_sent_original_or_forged_binding(self):
        self.document["current_status"] = "rejected"
        binding = self.followup()["followup_binding"]
        for field, value in (("handover_id", ""), ("process_owner_user_id", "FORGED"),
                              ("finance_tenant_id", "OTHER"), ("correction_policy", "edit_original")):
            with self.subTest(field=field), self.assertRaises(PermissionError):
                policy.linked_application_seed(self.document, {**binding, field: value}, self.company,
                                               self.successor, today="2026-10-07")
        self.document["current_status"] = "dispatched"
        with self.assertRaises(policy.HandoverConflict):
            policy.linked_application_seed(self.document, binding, self.company, self.successor, today="2026-10-07")

    def test_json_evidence_from_database_is_preserved(self):
        self.steps[0]["decision_evidence_json"] = json.dumps(self.steps[0]["decision_evidence_json"])
        self.assertEqual("A" * 64, self.confirm()["replacement_steps"][0]["decision_evidence_json"]["files"][0]["sha256"])


if __name__ == "__main__":
    unittest.main()
