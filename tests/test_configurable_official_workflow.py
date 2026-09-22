"""Configurable approvals over synthetic PDF/seal/identity data only."""
from __future__ import annotations

import copy
import json
import unittest
from unittest import mock

import backend
from tests import test_general_document_seal_workflow as seal_fixture


class ConfigurableOfficialWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.fixture = seal_fixture.GeneralDocumentSealWorkflowTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.conn = self.fixture.conn
        self.session = self.fixture.session
        self.target_id = self.fixture.fixture.applicant_ids[4]
        self.conn.execute("UPDATE users SET account_source='finance' WHERE id=?", (self.target_id,))

    def _review(self, detail):
        step = next(row for row in detail["approval_steps"] if row["step_key"] == detail["current_step"] and row["status"] == "pending")
        session = self.fixture.fixture._session_for_user_id(step["approver_user_id"])
        for file in detail["files"]:
            if file["file_type"] in {"original_pdf", "prepared_pdf", "generated_pdf", "attachment"}:
                backend.official_document_download_file(self.conn, detail["id"], file["id"], session)
        payload = {"expected_step_id": step["id"], "comment": "Synthetic reviewed approval", "prepared_sha256": detail["stamp_request"]["prepared_sha256"], "manifest_sha256": detail["stamp_request"]["editor_manifest_sha256"], "review_acknowledgements": {"original_reviewed": True, "edited_version_reviewed": True, "attachments_reviewed": True}}
        return step, session, payload

    def _approve(self, detail):
        _, session, payload = self._review(detail)
        return backend.approve_official_document(self.conn, detail["id"], payload, session)

    def _configure(self, nodes):
        config = backend.local_official_workflow_config(self.conn)
        return backend.save_local_official_workflow_config(self.conn, {"expected_version": config["version"], "categories": {"服務委託合約": {"nodes": nodes}}})

    def test_per_category_config_survives_save_and_conflicts_fail_closed(self):
        node = {"id": "designated", "name": "指定 Finance 簽核", "assignee": {"type": "user", "user_id": self.target_id}}
        saved = self._configure([node])
        loaded = backend.local_official_workflow_config(self.conn)
        self.assertEqual(loaded["categories"]["服務委託合約"]["nodes"], [node])
        self.assertEqual(saved["version"], loaded["version"])
        with self.assertRaisesRegex(ValueError, "version_conflict"):
            backend.save_local_official_workflow_config(self.conn, {"expected_version": saved["version"] - 1, "categories": saved["categories"]})
        with self.assertRaisesRegex(ValueError, "assignee_invalid"):
            self._configure([{**node, "assignee": {"type": "role", "role_key": "general_affairs_review"}}])
        with self.assertRaisesRegex(ValueError, "node_id_invalid"):
            self._configure([node, node])
        with self.assertRaisesRegex(ValueError, "nodes_invalid"):
            self._configure([{**node, "id": f"step{i}"} for i in range(13)])
        with self.assertRaisesRegex(PermissionError, "workflow_config_manage_forbidden"):
            backend.save_local_official_workflow_config(self.conn, {"expected_version": saved["version"]}, self.session)

    def test_configured_person_is_real_first_step_and_locked_after_settings_change(self):
        config = self._configure([{"id": "person", "name": "指定簽核", "assignee": {"type": "user", "user_id": self.target_id}}])
        detail, _, saved, _ = self.fixture._submitted()
        self.assertEqual(detail["current_step"], "approval_person")
        self.assertEqual(detail["current_status"], "pending_approval")
        self.assertEqual([row["step_key"] for row in detail["approval_steps"]], ["approval_person", "general_affairs_review", "applicant_confirm"])
        self.assertEqual(detail["approval_steps"][0]["approver_user_id"], self.target_id)
        locked = detail["metadata"]["official_seal"]["workflow_config_snapshot"]
        self.assertEqual(locked["version"], config["version"])
        self._configure([])
        unchanged = backend.official_document_detail(self.conn, detail["id"], self.session)
        self.assertEqual(unchanged["metadata"]["official_seal"]["workflow_config_snapshot"], locked)
        result = self.fixture.fixture._approve_and_stamp(unchanged)
        self.assertEqual(result["current_status"], "stamped")
        self.assertEqual(backend.get_official_editor_state(self.conn, detail["id"], self.session)["state"], saved["state"])

    def test_return_previous_creates_new_ids_and_requires_review_again(self):
        detail = self._approve(self.fixture._submitted()[0])
        old_rows = copy.deepcopy(detail["approval_steps"])
        step, session, payload = self._review(detail)
        payload["operation_id"] = "RETURN-OPERATION-001"
        returned = backend.mutate_official_workflow(self.conn, detail["id"], "return_previous", payload, session)
        self.assertEqual(returned["current_step"], old_rows[0]["step_key"])
        self.assertEqual(returned["approval_steps"][0]["workflow_generation"], 2)
        self.assertTrue(set(row["id"] for row in returned["approval_steps"]).isdisjoint(row["id"] for row in old_rows))
        self.assertEqual(self.conn.execute("SELECT status FROM official_document_approval_steps WHERE id=?", (old_rows[0]["id"],)).fetchone()[0], "approved")
        for row in returned["approval_steps"]:
            self.assertTrue(json.loads(row["decision_evidence_json"])["copied_from_step_id"])
        retried = backend.mutate_official_workflow(self.conn, detail["id"], "return_previous", payload, session)
        self.assertTrue(retried["action_result"]["idempotent"])
        with self.assertRaisesRegex(ValueError, "operation_conflict"):
            backend.mutate_official_workflow(self.conn, detail["id"], "return_previous", {**payload, "comment": "Changed comment"}, session)
        with self.assertRaisesRegex(ValueError, "already_claimed"):
            backend.approve_official_document(self.conn, detail["id"], {**payload, "expected_step_id": step["id"]}, self.fixture.fixture._session_for_user_id(old_rows[0]["approver_user_id"]))
        self.assertEqual(self.fixture.fixture._approve_and_stamp(returned)["current_status"], "stamped")

    def test_add_sign_approves_current_then_target_then_original_suffix(self):
        detail = self.fixture._submitted()[0]
        original = detail["approval_steps"]
        step, session, payload = self._review(detail)
        payload.update({"operation_id": "ADDSIGN-OPERATION-001", "target_user_id": self.target_id, "placement": "after"})
        added = backend.mutate_official_workflow(self.conn, detail["id"], "add_sign", payload, session)
        rows = added["approval_steps"]
        self.assertEqual(rows[0]["status"], "approved")
        self.assertEqual(rows[0]["decision_actor_user_id"], session["user"]["id"])
        self.assertEqual(rows[1]["approver_user_id"], self.target_id)
        self.assertEqual(rows[1]["status"], "pending")
        self.assertEqual([row["step_key"] for row in rows[2:]], [row["step_key"] for row in original[1:]])
        self.assertEqual(added["current_step"], rows[1]["step_key"])
        self.assertEqual(added["current_status"], "pending_approval")
        advanced = self._approve(added)
        self.assertEqual(advanced["current_step"], original[1]["step_key"])
        self.assertEqual(self.fixture.fixture._approve_and_stamp(advanced)["current_status"], "stamped")

    def test_add_sign_after_general_affairs_stamps_only_after_extra_approval(self):
        detail = self.fixture._submitted()[0]
        while detail["current_step"] != "general_affairs_review":
            detail = self._approve(detail)
        _, session, payload = self._review(detail)
        payload.update({"operation_id": "ADDSIGN-GENERAL-AFFAIRS", "target_user_id": self.target_id, "placement": "after"})
        added = backend.mutate_official_workflow(self.conn, detail["id"], "add_sign", payload, session)
        self.assertFalse(any(file["file_type"] == "stamped_pdf" for file in added["files"]))
        result = self._approve(added)
        self.assertEqual(result["current_status"], "stamped")

    def test_withdraw_after_approval_clones_revision_and_full_resubmit(self):
        submitted, _, original, _ = self.fixture._submitted()
        detail = self._approve(submitted)
        current = next(row for row in detail["approval_steps"] if row["step_key"] == detail["current_step"])
        payload = {"operation_id": "WITHDRAW-OPERATION-001", "expected_step_id": current["id"], "expected_content_revision": detail["content_revision"], "comment": "Applicant corrects original draft"}
        result = backend.mutate_official_workflow(self.conn, detail["id"], "withdraw", payload, self.session)
        self.assertEqual(result["current_status"], "draft")
        self.assertEqual(result["content_revision"], detail["content_revision"] + 1)
        revision = backend.get_official_editor_state(self.conn, detail["id"], self.session)
        self.assertGreater(revision["revisionNo"], original["revisionNo"])
        self.assertEqual(revision["state"]["revisionNo"], revision["revisionNo"])
        self.assertEqual(backend.canonical_editor_manifest(revision["state"]), revision["manifestSha256"])
        self.assertEqual(backend.get_official_editor_state(self.conn, detail["id"], self.session)["status"], "draft")
        self.assertEqual(json.loads(self.conn.execute("SELECT editor_state_json FROM official_document_editor_revisions WHERE id=?", (original["id"],)).fetchone()[0]), original["state"])
        preflight = backend.preflight_official_editor(self.conn, detail["id"], {"editorRevisionId": revision["id"], "manifestSha256": revision["manifestSha256"]}, self.session)
        resubmitted = backend.submit_official_document(self.conn, detail["id"], {**{key: preflight[key] for key in ("editorRevisionId", "manifestSha256", "preparedFileId", "preparedSha256")}, "content_revision": result["content_revision"]}, self.session)
        self.assertEqual(resubmitted["current_step"], submitted["current_step"])
        self.assertTrue(all(row["status"] == "pending" for row in resubmitted["approval_steps"]))
        self.assertEqual(self.fixture.fixture._approve_and_stamp(resubmitted)["current_status"], "stamped")

    def test_unauthorized_stale_unreviewed_and_invalid_target_rejected(self):
        detail = self.fixture._submitted()[0]
        step, session, payload = self._review(detail)
        payload.update({"operation_id": "NEGATIVE-OPERATION-001", "target_user_id": self.target_id, "placement": "after"})
        with self.assertRaises(PermissionError):
            backend.mutate_official_workflow(self.conn, detail["id"], "add_sign", payload, self.session)
        for mutation in ({"expected_step_id": "stale"}, {"placement": "before"}, {"target_user_id": self.session["user"]["id"]}, {"prepared_sha256": "0" * 64}):
            with self.subTest(mutation=mutation), self.assertRaises((ValueError, PermissionError)):
                backend.mutate_official_workflow(self.conn, detail["id"], "add_sign", {**payload, **mutation}, session)
        self.conn.execute("UPDATE users SET company_id='CO-002' WHERE id=?", (self.target_id,))
        with self.assertRaisesRegex(ValueError, "target_invalid"):
            backend.mutate_official_workflow(self.conn, detail["id"], "add_sign", payload, session)
        self.assertEqual(backend.official_document_row(self.conn, detail["id"])["current_step"], detail["current_step"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM official_document_approval_logs WHERE action='add_sign'").fetchone()[0], 0)

    def test_supabase_wrapper_passes_identical_atomic_plan_without_partial_writes(self):
        detail = self.fixture._submitted()[0]
        _, session, payload = self._review(detail)
        payload.update({"operation_id": "SUPABASE-OPERATION-001", "target_user_id": self.target_id, "placement": "after"})
        plans = []
        def rpc(method, endpoint, body):
            self.assertEqual((method, endpoint), ("POST", "rpc/edoc_mutate_official_workflow"))
            plans.append(body["p_request"])
            return {"ok": True, "committed": True, "document_id": detail["id"], "operation_id": payload["operation_id"], "action_result": body["p_request"]["action_result"]}
        with self.fixture._supabase_adapter(), mock.patch.object(backend, "supabase_request", side_effect=rpc), mock.patch.object(backend, "supabase_official_document_detail", return_value=detail), mock.patch.object(backend, "supabase_patch") as patch, mock.patch.object(backend, "supabase_insert") as insert:
            result = backend.supabase_mutate_official_workflow(detail["id"], "add_sign", payload, session)
        self.assertEqual(len(plans), 1)
        self.assertIsInstance(plans[0]["document_patch"]["metadata_json"], dict)
        self.assertEqual(plans[0]["steps"][0]["status"], "approved")
        self.assertEqual(plans[0]["steps"][1]["approver_user_id"], self.target_id)
        self.assertEqual(result["action_result"]["action"], "add_sign")
        patch.assert_not_called()
        insert.assert_not_called()

    def test_actions_preserve_receipt_history_and_all_participant_downloads(self):
        detail = self._approve(self.fixture._submitted()[0])
        old_receipt = next(row for row in detail["approval_steps"] if row["step_key"] == "applicant_confirm")
        _, session, payload = self._review(detail)
        payload.update({"operation_id": "RETURN-RECEIPT-HISTORY"})
        returned = backend.mutate_official_workflow(self.conn, detail["id"], "return_previous", payload, session)
        final = self.fixture.fixture._approve_and_stamp(returned)
        file = next(row for row in final["files"] if row["file_type"] == "stamped_pdf")
        participants = backend.official_document_participant_ids(final, final["approval_step_history"])
        for user_id in participants:
            participant = self.fixture.fixture._session_for_user_id(user_id)
            self.assertTrue(backend.official_document_download_file(self.conn, final["id"], file["id"], participant)[2].startswith(b"%PDF"))
        confirmed = backend.confirm_official_document(self.conn, final["id"], {}, self.session)
        self.assertEqual(confirmed["current_status"], "closed")
        self.assertEqual(next(row for row in confirmed["approval_steps"] if row["step_key"] == "applicant_confirm")["status"], "approved")
        self.assertEqual(self.conn.execute("SELECT status FROM official_document_approval_steps WHERE id=?", (old_receipt["id"],)).fetchone()[0], "skipped")

    def test_atomic_failure_rolls_back_steps_document_log_and_notice(self):
        detail = self.fixture._submitted()[0]
        _, session, payload = self._review(detail)
        payload.update({"operation_id": "ATOMIC-NOTICE-FAILURE", "target_user_id": self.target_id})
        before = backend.official_document_row(self.conn, detail["id"])
        before_steps = backend.official_document_steps(self.conn, detail["id"])
        with mock.patch.object(backend, "create_notification", side_effect=RuntimeError("synthetic notification failure")):
            with self.assertRaisesRegex(RuntimeError, "synthetic"):
                backend.mutate_official_workflow(self.conn, detail["id"], "add_sign", payload, session)
        self.assertEqual(backend.official_document_row(self.conn, detail["id"]), before)
        self.assertEqual(backend.official_document_steps(self.conn, detail["id"]), before_steps)
        self.assertFalse(self.conn.execute("SELECT 1 FROM official_document_approval_logs WHERE id=?", (payload["operation_id"],)).fetchone())

    def test_readiness_uses_category_config_and_preserves_finance_seniority_rules(self):
        self._configure([{"id": "person", "name": "指定簽核", "assignee": {"type": "user", "user_id": self.target_id}}])
        readiness = backend.official_applicant_workflow_readiness(self.conn, self.session, "A", "服務委託合約", "CO-001", "任意申請部門")
        self.assertEqual(readiness["routeCode"], "C")
        self.assertEqual(readiness["steps"][0]["approverUserId"], self.target_id)
        self.assertEqual(readiness["configurationVersion"], backend.local_official_workflow_config(self.conn)["version"])
        default = backend.normalize_official_workflow_config()
        for role, absent in (("section_chief", {"applicant_manager"}), ("department_head", {"applicant_manager", "department_head"})):
            steps = backend.configured_official_workflow_steps(default, "服務委託合約", role)
            self.assertFalse(absent.intersection(step["key"] for step in steps))
            self.assertEqual([step["key"] for step in steps[-2:]], ["general_affairs_review", "applicant_confirm"])

    def test_capabilities_and_candidates_never_grant_admin_or_applicant_self_approval(self):
        detail = self.fixture._submitted()[0]
        self.assertEqual(detail["available_actions"], ["withdraw"])
        _, reviewer, _ = self._review(detail)
        reviewed = backend.official_document_detail(self.conn, detail["id"], reviewer)
        self.assertIn("add-sign", reviewed["available_actions"])
        self.assertNotIn("return-previous", reviewed["available_actions"])
        self.assertNotIn("withdraw", reviewed["available_actions"])
        candidates = backend.official_workflow_candidates(reviewer, document_id=detail["id"], conn=self.conn)["candidates"]
        self.assertIn(self.target_id, {row["id"] for row in candidates})
        self.assertNotIn(self.session["user"]["id"], {row["id"] for row in candidates})
        with self.assertRaises(PermissionError):
            backend.official_workflow_candidates(self.session, document_id=detail["id"], conn=self.conn)
        unrelated = {"id": "SYNTHETIC-ADMIN", "role": "系統管理員"}
        self.assertEqual(backend.official_workflow_action_capabilities(detail, detail["approval_steps"], unrelated)["available_actions"], [])

    def test_first_return_inactive_target_and_irreversible_withdraw_are_blocked(self):
        detail = self.fixture._submitted()[0]
        step, reviewer, payload = self._review(detail)
        payload["operation_id"] = "BLOCKED-ACTION-001"
        with self.assertRaisesRegex(ValueError, "previous_step_unavailable"):
            backend.mutate_official_workflow(self.conn, detail["id"], "return_previous", payload, reviewer)
        self.conn.execute("UPDATE users SET status='停用' WHERE id=?", (self.target_id,))
        with self.assertRaisesRegex(ValueError, "target_invalid"):
            backend.mutate_official_workflow(self.conn, detail["id"], "add_sign", {**payload, "target_user_id": self.target_id}, reviewer)
        self.conn.execute("UPDATE official_document_stamp_requests SET claim_token=? WHERE document_id=?", ("claim-already-held", detail["id"]))
        with self.assertRaisesRegex(ValueError, "action_conflict"):
            backend.mutate_official_workflow(self.conn, detail["id"], "withdraw", {**payload, "expected_content_revision": detail["content_revision"]}, self.session)
        self.assertEqual(backend.official_document_row(self.conn, detail["id"])["current_step"], detail["current_step"])

    def test_completed_decision_and_provenance_cannot_be_rewritten(self):
        detail = self.fixture._submitted()[0]
        _, reviewer, payload = self._review(detail)
        payload.update({"operation_id": "IMMUTABLE-ADDSIGN-001", "target_user_id": self.target_id})
        added = backend.mutate_official_workflow(self.conn, detail["id"], "add_sign", payload, reviewer)
        pending = added["approval_steps"][1]
        with self.assertRaisesRegex(Exception, "decision_evidence_immutable"):
            self.conn.execute("UPDATE official_document_approval_steps SET decision_evidence_json='{}' WHERE id=?", (pending["id"],))
        advanced = self._approve(added)
        with self.assertRaisesRegex(Exception, "decision_evidence_immutable"):
            self.conn.execute("UPDATE official_document_approval_steps SET decision_evidence_json='{}',decision_actor_user_id=NULL WHERE id=?", (pending["id"],))
        self.assertTrue(advanced["current_step"])

    def test_supabase_config_write_uses_one_cas_rpc(self):
        administrator = {"user": {"id": "SYNTHETIC-SETTINGS", "company_id": "CO-001"}, "permissions": ["settings.manage"]}
        request = {"expected_version": 0, "operation_id": "CONFIG-SUPABASE-001", "categories": {"服務委託合約": {"nodes": []}}}
        captured = []
        def rpc(method, endpoint, body):
            self.assertEqual((method, endpoint), ("POST", "rpc/edoc_save_official_workflow_config"))
            captured.append(body["p_request"])
            return {"ok": True, "version": 1, "config": body["p_request"]["config"]}
        with mock.patch.object(backend, "supabase_request", side_effect=rpc), mock.patch.object(backend, "supabase_insert") as insert, mock.patch.object(backend, "supabase_patch") as patch:
            result = backend.supabase_save_official_workflow_config(request, administrator)
        self.assertEqual(result["version"], 1)
        self.assertEqual(captured[0]["expected_version"], 0)
        insert.assert_not_called()
        patch.assert_not_called()
        for code in ("official_workflow_config_conflict", "official_workflow_step_conflict", "official_workflow_operation_conflict", "official_workflow_generation_conflict", "official_workflow_irreversible"):
            self.assertEqual(backend.api_value_error_status(code), 409)

    def test_submission_ids_bind_actual_generation_and_preserve_legacy_retries(self):
        document = {"id": "SYNTHETIC-DOC", "created_at": "2026-09-22 00:00:00", "current_status": "draft", "metadata_json": "{}"}
        legacy = backend._supabase_official_submission_operation_ids(document, "SYNTHETIC-APPLICANT")
        first = backend._supabase_official_submission_operation_ids(document, "SYNTHETIC-APPLICANT", workflow_generation=1)
        second = backend._supabase_official_submission_operation_ids(document, "SYNTHETIC-APPLICANT", workflow_generation=4)
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, legacy)
        pending = {**document, "current_status": "pending_approval", "metadata_json": json.dumps({"official_seal": {"submission_generation": 4}})}
        self.assertEqual(backend._supabase_official_submission_operation_ids(pending, "SYNTHETIC-APPLICANT"), second)
        self.assertEqual(backend._supabase_official_submission_operation_ids({**pending, "metadata_json": "{}"}, "SYNTHETIC-APPLICANT"), legacy)

    def test_config_operation_hash_ignores_server_time_but_binds_semantic_changes(self):
        administrator = {"user": {"id": "SYNTHETIC-SETTINGS", "company_id": "CO-001"}, "permissions": ["settings.manage"]}
        payload = {"expected_version": 0, "operation_id": "CONFIG-STABLE-RETRY", "categories": {"服務委託合約": {"nodes": []}}}
        requests = []
        def rpc(method, endpoint, body):
            self.assertEqual((method, endpoint), ("POST", "rpc/edoc_save_official_workflow_config"))
            request = body["p_request"]
            requests.append(copy.deepcopy(request))
            return {"ok": True, "version": request["expected_version"] + 1, "config": request["config"]}
        with mock.patch.object(backend, "supabase_request", side_effect=rpc):
            for timestamp, request in (
                ("2026-09-22 01:00:00", payload),
                ("2026-09-22 01:00:05", payload),
                ("2026-09-22 01:00:05", {**payload, "name": "Changed workflow name"}),
                ("2026-09-22 01:00:05", {**payload, "expected_version": 1}),
            ):
                with mock.patch.object(backend, "now", return_value=timestamp):
                    backend.supabase_save_official_workflow_config(request, administrator)
        self.assertNotEqual(requests[0]["config"]["updated_at"], requests[1]["config"]["updated_at"])
        self.assertEqual(requests[0]["config_sha256"], requests[1]["config_sha256"])
        self.assertNotEqual(requests[0]["config_sha256"], requests[2]["config_sha256"])
        self.assertNotEqual(requests[0]["config_sha256"], requests[3]["config_sha256"])

    def test_repeated_designated_actor_cannot_use_old_button_to_approve_next_node(self):
        self._configure([{"id": f"person{i}", "name": f"指定簽核{i}", "assignee": {"type": "user", "user_id": self.target_id}} for i in range(2)])
        detail = self.fixture._submitted()[0]
        _, reviewer, payload = self._review(detail)
        advanced = backend.approve_official_document(self.conn, detail["id"], payload, reviewer)
        self.assertEqual(advanced["current_step"], "approval_person1")
        with self.assertRaisesRegex(ValueError, "already_claimed"):
            backend.approve_official_document(self.conn, detail["id"], payload, reviewer)
        self.assertEqual(backend.official_document_row(self.conn, detail["id"])["current_step"], "approval_person1")

    def _verified_cross_company_target(self):
        tenant = "SYNTHETIC-WORKFLOW-TENANT"
        self.conn.execute("UPDATE companies SET source_system='finance',finance_entity_id='SYNTHETIC-ENTITY',finance_tenant_id=?,status='啟用' WHERE id='CO-001'", (tenant,))
        self.conn.execute("UPDATE users SET finance_tenant_id=? WHERE id=?", (tenant, self.session["user"]["id"]))
        self.conn.execute("UPDATE users SET company_id='CO-002',finance_tenant_id=? WHERE id=?", (tenant, self.target_id))
        self.session = self.fixture.fixture._session_for_user_id(self.session["user"]["id"])
        return backend.active_user_by_id(self.conn, self.target_id), backend.official_company_row(self.conn, "CO-001")

    def test_designated_document_scope_matches_verified_v2_exception_only(self):
        target, company = self._verified_cross_company_target()
        applicant = self.session["user"]
        compose = {"company_id": "CO-001", "source_type": "blank_editor", "metadata_json": {"pdf_editor_v2": True}}
        uploaded = {**compose, "source_type": "uploaded_pdf"}
        self.assertTrue(backend.official_designated_actor_allowed(target, applicant, company))
        self.assertFalse(backend.official_designated_actor_allowed(target, applicant, company, compose))
        self.assertTrue(backend.official_designated_actor_allowed(target, applicant, company, uploaded))
        for document, owner, organization in (
            ({**uploaded, "metadata_json": {"pdf_editor_v2": "false"}}, applicant, company),
            ({**uploaded, "metadata_json": {}}, applicant, company),
            (uploaded, applicant, {**company, "source_system": "local"}),
            (uploaded, applicant, {**company, "status": "inactive"}),
            (uploaded, applicant, {**company, "finance_entity_id": ""}),
            (uploaded, {**applicant, "status": "停用"}, company),
            (uploaded, {**applicant, "finance_tenant_id": ""}, company),
            (uploaded, applicant, {**company, "finance_tenant_id": "OTHER-TENANT"}),
        ):
            with self.subTest(document=document, owner=owner["id"], company=organization["id"]):
                self.assertFalse(backend.official_designated_actor_allowed(target, owner, organization, document))
        node = {"key": "approval_person", "assignee": {"type": "user", "user_id": self.target_id}}
        with self.assertRaisesRegex(ValueError, "designated_company_forbidden"):
            backend.resolve_official_step_approver(self.conn, node, applicant, company, compose)
        with self.fixture._supabase_adapter():
            with self.assertRaisesRegex(ValueError, "designated_company_forbidden"):
                backend.supabase_resolve_official_step_approver(node, applicant, company, compose)
            self.assertEqual(backend.supabase_resolve_official_step_approver(node, applicant, company, uploaded)["id"], self.target_id)

    def test_readiness_scopes_compose_and_uploaded_pdf_independently_in_both_backends(self):
        self._configure([{"id": "person", "name": "指定簽核", "assignee": {"type": "user", "user_id": self.target_id}}])
        self._verified_cross_company_target()
        for source in ("blank_editor", "uploaded_pdf"):
            with self.subTest(source=source):
                local = backend.official_applicant_workflow_readiness(self.conn, self.session, "C", "服務委託合約", "CO-001", "", source)
                with self.fixture._supabase_adapter():
                    remote = backend.supabase_official_applicant_workflow_readiness(self.session, "C", "服務委託合約", "CO-001", "", source)
                for result in (local, remote):
                    step = result["steps"][0]
                    self.assertEqual(step["ready"], source == "uploaded_pdf")
                    if source == "blank_editor":
                        self.assertEqual(step["reason"], "designated_company_forbidden")
                        self.assertFalse(result["submitAllowed"])
                    else:
                        self.assertEqual(step["approverUserId"], self.target_id)

    def test_compose_add_sign_candidates_and_actions_reject_cross_company_in_both_backends(self):
        detail = self.fixture._submitted()[0]
        _, reviewer, payload = self._review(detail)
        self._verified_cross_company_target()
        document = {**backend.official_document_row(self.conn, detail["id"]), "source_type": "blank_editor"}
        payload.update(operation_id="SCOPE-COMPOSE-ADDSIGN", target_user_id=self.target_id)
        with mock.patch.object(backend, "official_document_row", return_value=document):
            candidates = backend.official_workflow_candidates(reviewer, document_id=detail["id"], conn=self.conn)["candidates"]
            self.assertNotIn(self.target_id, {row["id"] for row in candidates})
            with mock.patch.object(backend, "sqlite_official_decision_document_evidence", return_value={"attachments": []}), mock.patch.object(backend, "sqlite_official_review_access_evidence", return_value={}), mock.patch.object(backend, "official_approval_decision_evidence", return_value={}):
                with self.assertRaisesRegex(ValueError, "designated_company_forbidden"):
                    backend.mutate_official_workflow(self.conn, detail["id"], "add_sign", payload, reviewer)
        with self.fixture._supabase_adapter(), mock.patch.object(backend, "supabase_official_document_row", return_value=document), mock.patch.object(backend, "supabase_request") as rpc:
            candidates = backend.official_workflow_candidates(reviewer, document_id=detail["id"])["candidates"]
            self.assertNotIn(self.target_id, {row["id"] for row in candidates})
            with mock.patch.object(backend, "supabase_official_decision_document_evidence", return_value={"attachments": []}), mock.patch.object(backend, "supabase_official_review_access_evidence", return_value={}), mock.patch.object(backend, "official_approval_decision_evidence", return_value={}):
                with self.assertRaisesRegex(ValueError, "designated_company_forbidden"):
                    backend.supabase_mutate_official_workflow(detail["id"], "add_sign", payload, reviewer)
            rpc.assert_not_called()
        self.assertFalse(self.conn.execute("SELECT 1 FROM official_document_approval_logs WHERE id=?", (payload["operation_id"],)).fetchone())

    def test_compose_submission_rejects_cross_company_designated_actor_before_locks(self):
        document_id, _, _ = self.fixture._draft()
        self._configure([{"id": "person", "name": "指定簽核", "assignee": {"type": "user", "user_id": self.target_id}}])
        self._verified_cross_company_target()
        document = {**backend.official_document_row(self.conn, document_id), "source_type": "blank_editor"}
        with mock.patch.object(backend, "official_document_row", return_value=document), mock.patch.object(backend, "lock_official_editor_submission") as lock:
            with self.assertRaisesRegex(ValueError, "designated_company_forbidden"):
                backend.submit_official_document(self.conn, document_id, {}, self.session)
            lock.assert_not_called()
        with self.fixture._supabase_adapter(), mock.patch.object(backend, "supabase_official_document_row", return_value=document), mock.patch.object(backend, "supabase_lock_official_editor_submission") as lock, mock.patch.object(backend, "supabase_request") as rpc:
            with self.assertRaisesRegex(ValueError, "designated_company_forbidden"):
                backend.supabase_submit_official_document(document_id, {}, self.session)
            lock.assert_not_called()
            rpc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
