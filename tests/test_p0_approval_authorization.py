"""P0-candidate checks over deidentified localhost HTTP only.

These tests use synthetic Finance/AV fixtures, ephemeral SQLite and local
storage. They do not exercise production SSO, hosted Supabase or real seals.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import unittest
import uuid

import backend
from tests import test_role_compose_http_journeys as journeys
from tests import test_launch_permission_regressions as delegation_fixtures


class P0ApprovalAuthorizationHttpTest(unittest.TestCase):
    setUpClass = classmethod(journeys.RoleComposeHttpJourneysTest.setUpClass.__func__)
    tearDownClass = classmethod(journeys.RoleComposeHttpJourneysTest.tearDownClass.__func__)
    api = journeys.RoleComposeHttpJourneysTest.api
    create = journeys.RoleComposeHttpJourneysTest.create
    review = journeys.RoleComposeHttpJourneysTest.review
    delegated_document = delegation_fixtures.DelegatedReviewHttpRegressionTest.delegated_document
    revoke = delegation_fixtures.DelegatedReviewHttpRegressionTest.revoke

    def pending(self):
        case = min(self.fixture.case_definitions, key=lambda row: row["ordinal"])
        draft = self.create(case, "physical")
        owner = self.tokens[case["ordinal"]]
        detail = self.api("POST", f"/api/official-documents/{draft['id']}/submit", owner, {})
        return detail, owner

    def snapshot(self, document_id):
        with backend.connect() as conn:
            result = {}
            for table, key in (("official_documents", "id"),
                               ("official_document_approval_steps", "document_id"),
                               ("official_document_stamp_requests", "document_id"),
                               ("official_document_files", "document_id")):
                result[table] = [dict(row) for row in conn.execute(
                    f"SELECT * FROM {table} WHERE {key}=? ORDER BY id", (document_id,))]
            result["decisions"] = [dict(row) for row in conn.execute(
                "SELECT * FROM official_document_approval_logs WHERE document_id=? "
                "AND action IN ('approve','reject','add_sign','decline','withdraw','auto_stamp') ORDER BY id",
                (document_id,))]
            result["file_objects"] = [dict(row) for row in conn.execute(
                "SELECT * FROM file_objects WHERE id IN (SELECT file_object_id FROM official_document_files WHERE document_id=?) ORDER BY id",
                (document_id,))]
            result["stamp_positions"] = [dict(row) for row in conn.execute(
                "SELECT * FROM official_document_stamp_positions WHERE request_id IN (SELECT id FROM official_document_stamp_requests WHERE document_id=?) ORDER BY id",
                (document_id,))]
            return json.dumps(result, sort_keys=True, ensure_ascii=False)

    def payload(self, detail):
        step = next(row for row in detail["approval_steps"] if row["step_key"] == detail["current_step"])
        target = next(row for row in detail["approval_steps"] if row["approver_user_id"] != step["approver_user_id"])
        return {
            "expected_step_id": step["id"], "operation_id": "P0-" + uuid.uuid4().hex,
            "expected_content_revision": detail["content_revision"],
            "comment": "Synthetic security negative case.", "reason_category": "fixture",
            "target_user_id": target["approver_user_id"], "placement": "after",
            "review_acknowledgements": {"original_reviewed": True, "edited_version_reviewed": True, "attachments_reviewed": True},
        }

    def assert_denied_unchanged(self, detail, token, action, payload):
        before = self.snapshot(detail["id"])
        response = self.fixture._request("POST", f"/api/official-documents/{detail['id']}/{action}",
                                         token=token, json_body=payload)
        self.assertIn(response.status, {401, 403, 409, 422}, (action, response.status, response.body))
        self.assertEqual(before, self.snapshot(detail["id"]), (action, response.status, response.body))
        return response

    def test_unassigned_self_cross_company_and_anonymous_cannot_decide_or_stamp(self):
        detail, owner = self.pending()
        steps = detail["approval_steps"]
        future = next(row for row in steps if row["step_key"] not in {detail["current_step"], "applicant_confirm"})
        unassigned = self.fixture._token_for_user_id(future["approver_user_id"])
        foreign_case = next(row for row in self.fixture.case_definitions if row["company_id"] != detail["company_id"])
        actors = {"self": owner, "future_unassigned": unassigned,
                  "cross_company": self.tokens[foreign_case["ordinal"]], "anonymous": ""}
        for label, token in actors.items():
            for action in ("approve", "reject", "add-sign", "decline", "return-previous", "retry-stamp"):
                with self.subTest(actor=label, action=action):
                    payload = self.payload(detail)
                    payload.update(actor_id=steps[0]["approver_user_id"],
                                   decision_actor_user_id=steps[0]["approver_user_id"],
                                   principal_actor_id=steps[0]["approver_user_id"],
                                   user={"id": steps[0]["approver_user_id"], "role": "執行長"})
                    self.assert_denied_unchanged(detail, token, action, payload)

    def test_disabled_and_revoked_sessions_cannot_decide(self):
        for state in ("disabled", "revoked", "forbidden_role"):
            detail, _ = self.pending()
            step, token, _ = self.review(detail)
            with backend.connect() as conn:
                original = dict(conn.execute("SELECT * FROM users WHERE id=?", (step["approver_user_id"],)).fetchone())
                if state == "revoked":
                    conn.execute("UPDATE auth_sessions SET revoked_at=? WHERE token_hash=?", (backend.now(), backend.hash_token(token)))
                elif state == "disabled":
                    conn.execute("UPDATE users SET status='停用' WHERE id=?", (original["id"],))
                else:
                    conn.execute("UPDATE users SET role='未授權角色' WHERE id=?", (original["id"],))
            try:
                for action in ("approve", "reject", "add-sign", "decline", "return-previous", "retry-stamp"):
                    with self.subTest(state=state, action=action):
                        response = self.assert_denied_unchanged(detail, token, action, self.payload(detail))
                        self.assertIn(response.status, {401, 403})
            finally:
                with backend.connect() as conn:
                    conn.execute("UPDATE users SET status=?,role=? WHERE id=?", (original["status"], original["role"], original["id"]))
                    # Restore only this ephemeral fixture's session so later
                    # scenarios do not accidentally reuse the revoked bearer.
                    conn.execute("UPDATE auth_sessions SET revoked_at=NULL WHERE token_hash=?", (backend.hash_token(token),))

    def test_forged_step_and_withdraw_revision_cannot_advance(self):
        detail, owner = self.pending()
        _, reviewer, payload = self.review(detail)
        for fake in (None, "", "STEP-DOES-NOT-EXIST", detail["approval_steps"][-1]["id"]):
            for action in ("approve", "reject", "add-sign", "decline", "return-previous"):
                with self.subTest(step=fake, action=action):
                    self.assert_denied_unchanged(detail, reviewer, action,
                                                {**self.payload(detail), **payload, "expected_step_id": fake})
        for fake_revision in (None, True, -1, 999, str(detail["content_revision"])):
            with self.subTest(withdraw_revision=fake_revision):
                self.assert_denied_unchanged(detail, owner, "withdraw",
                                            {**self.payload(detail), "expected_content_revision": fake_revision})

    def test_client_review_claim_without_server_file_access_cannot_approve(self):
        detail, _ = self.pending()
        step = next(row for row in detail["approval_steps"] if row["step_key"] == detail["current_step"])
        reviewer = self.fixture._token_for_user_id(step["approver_user_id"])
        payload = self.payload(detail)
        payload["review_access"] = {"server_verified": True, "required_file_ids": [row["id"] for row in detail["files"]]}
        payload["decision_evidence"] = {"schema_version": 2, "review_access": payload["review_access"]}
        for action in ("approve", "reject", "add-sign", "decline"):
            with self.subTest(action=action):
                self.assert_denied_unchanged(detail, reviewer, action, payload)

    def test_revoked_delegate_with_prior_valid_review_cannot_decide(self):
        detail, _, principal, delegate, delegation = self.delegated_document()
        for file in detail["files"]:
            if file["file_type"] in {"generated_pdf", "original_pdf", "prepared_pdf", "attachment"}:
                response = self.fixture._request("GET", f"/api/official-documents/{detail['id']}/files/{file['id']}/download", token=delegate)
                self.assertEqual(response.status, 200)
        self.revoke(delegation, principal)
        for action in ("approve", "reject", "add-sign", "decline", "return-previous"):
            with self.subTest(action=action):
                response = self.assert_denied_unchanged(detail, delegate, action, self.payload(detail))
                self.assertEqual(response.status, 403)

    def test_generic_file_and_workflow_crud_is_closed_even_for_ceo(self):
        detail, owner = self.pending()
        ceo_identity = next(row for row in self.fixture.identity_by_email.values() if row["role"] == "ceo")
        ceo = self.fixture._portal_session(ceo_identity["email"])
        with backend.connect() as conn:
            file_row = dict(conn.execute("SELECT * FROM official_document_files WHERE document_id=? LIMIT 1", (detail["id"],)).fetchone())
            position = conn.execute("SELECT id FROM official_document_stamp_positions WHERE request_id=? LIMIT 1", (detail["stamp_request"]["id"],)).fetchone()
        identities = {"official_documents": detail["id"], "official_document_files": file_row["id"],
                      "file_objects": file_row["file_object_id"], "official_document_stamp_positions": position["id"],
                      "official_document_approval_steps": detail["approval_steps"][0]["id"],
                      "official_document_stamp_requests": detail["stamp_request"]["id"]}
        before = self.snapshot(detail["id"])
        for label, token in (("staff", owner), ("ceo", ceo)):
            for table, row_id in identities.items():
                for method in ("POST", "PATCH", "DELETE"):
                    with self.subTest(role=label, table=table, method=method):
                        path = f"/api/{table}" + ("" if method == "POST" else f"/{row_id}")
                        response = self.fixture._request(method, path, token=token,
                                                         json_body={"id": row_id, "current_status": "approved", "status": "approved", "sha256": "0" * 64})
                        self.assertIn(response.status, {403, 404, 405}, (response.status, response.body))
        self.assertEqual(before, self.snapshot(detail["id"]))

    def test_parallel_approve_and_replay_record_exactly_one_decision(self):
        detail, _ = self.pending()
        step, reviewer, payload = self.review(detail)
        def approve():
            return self.fixture._request("POST", f"/api/official-documents/{detail['id']}/approve",
                                         token=reviewer, json_body=payload)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: approve(), range(2)))
        self.assertEqual(1, sum(response.status == 200 for response in responses), [response.status for response in responses])
        self.assertTrue(all(response.status in {200, 403, 409, 422} for response in responses))
        self.assertIn(approve().status, {403, 409, 422})
        with backend.connect() as conn:
            self.assertEqual(1, conn.execute("SELECT count(*) FROM official_document_approval_logs WHERE document_id=? AND step_id=? AND action='approve'", (detail["id"], step["id"])).fetchone()[0])
            self.assertEqual("approved", conn.execute("SELECT status FROM official_document_approval_steps WHERE id=?", (step["id"],)).fetchone()[0])
            self.assertEqual(0, conn.execute("SELECT count(*) FROM official_document_files WHERE document_id=? AND file_type='stamped_pdf'", (detail["id"],)).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
