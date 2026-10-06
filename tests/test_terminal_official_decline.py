"""Terminal decisions and withdrawal boundary; synthetic identities/PDF only."""
import copy
import json
from unittest import mock
import backend
from tests.test_configurable_official_workflow import ConfigurableOfficialWorkflowTest
from tools.terminal_decline_shared_forward import render_shared_forward, FORWARD_NAME
from tools.shared_supabase_bootstrap import ROOT


class TerminalOfficialDeclineTest(ConfigurableOfficialWorkflowTest):
    def decline_payload(self, detail):
        step, session, payload = self._review(detail)
        return step, session, {**payload, "operation_id": "DECLINE-" + detail["id"], "comment": "Synthetic terminal decision reason"}

    def test_terminal_decline_preserves_history_files_and_notifies_applicant(self):
        detail = self._approve(self.fixture._submitted()[0])
        previous = copy.deepcopy(detail["approval_steps"][0])
        step, session, payload = self.decline_payload(detail)
        revisions = self.conn.execute("SELECT COUNT(*) FROM official_document_editor_revisions WHERE document_id=?", (detail["id"],)).fetchone()[0]
        result = backend.mutate_official_workflow(self.conn, detail["id"], "decline", payload, session)
        self.assertEqual(("declined", ""), (result["current_status"], result["current_step"]))
        self.assertEqual([], result["available_actions"])
        self.assertFalse(result["can_correct"] or result["can_resubmit"])
        self.assertEqual(detail["content_revision"], result["content_revision"])
        self.assertEqual(previous, result["approval_steps"][0])
        current = next(row for row in result["approval_steps"] if row["id"] == step["id"])
        self.assertEqual("rejected", current["status"])
        self.assertEqual(session["user"]["id"], current["decision_actor_user_id"])
        self.assertEqual("decline", json.loads(current["decision_evidence_json"])["decision_type"])
        self.assertFalse(any(row["status"] == "pending" for row in result["approval_steps"]))
        self.assertEqual(revisions, self.conn.execute("SELECT COUNT(*) FROM official_document_editor_revisions WHERE document_id=?", (detail["id"],)).fetchone()[0])
        self.assertEqual({f["id"] for f in detail["files"]}, {f["id"] for f in result["files"]})
        self.assertFalse(result.get("stamped_file_id"))
        self.assertEqual("cancelled", result["stamp_request"]["status"])
        notification = self.conn.execute("SELECT target_user_id,title,body FROM notifications WHERE source=? ORDER BY created_at DESC", (detail["id"],)).fetchall()
        self.assertTrue(any(row[0] == detail["applicant_id"] and row[1] == "案件不通過，已終止" and row[2] == payload["comment"] for row in notification))
        self.assertTrue(backend.mutate_official_workflow(self.conn, detail["id"], "decline", payload, session)["action_result"]["idempotent"])
        with self.assertRaisesRegex(ValueError, "operation_conflict"):
            backend.mutate_official_workflow(self.conn, detail["id"], "decline", {**payload, "comment": "Different terminal reason"}, session)
        for action, actor in (("withdraw", self.session), ("add_sign", session), ("return_previous", session)):
            with self.subTest(action=action), self.assertRaises((ValueError, PermissionError)):
                backend.mutate_official_workflow(self.conn, detail["id"], action, {**payload, "operation_id": payload["operation_id"] + action}, actor)
        with self.assertRaises(ValueError):
            backend.cancel_official_document(self.conn, detail["id"], {}, self.session)
        with self.assertRaises((ValueError, PermissionError)):
            backend.submit_official_document(self.conn, detail["id"], {}, self.session)
        with self.assertRaises((ValueError, PermissionError)):
            backend.approve_official_document(self.conn, detail["id"], payload, session)

    def test_decline_requires_current_actor_review_reason_and_unclaimed_stamp(self):
        detail = self.fixture._submitted()[0]
        step, session, payload = self.decline_payload(detail)
        for mutation in ({"comment": "short"}, {"expected_step_id": "stale"}, {"prepared_sha256": "0" * 64}, {"review_acknowledgements": {}}):
            with self.subTest(mutation=mutation), self.assertRaises((ValueError, PermissionError)):
                backend.mutate_official_workflow(self.conn, detail["id"], "decline", {**payload, **mutation}, session)
        with self.assertRaises(PermissionError):
            backend.mutate_official_workflow(self.conn, detail["id"], "decline", payload, self.session)
        self.conn.execute("UPDATE official_document_stamp_requests SET claim_token='synthetic-claimed' WHERE document_id=?", (detail["id"],))
        for actor in (self.session, session):
            latest = backend.official_document_detail(self.conn, detail["id"], actor)
            self.assertEqual([], latest["available_actions"])
        with self.assertRaisesRegex(ValueError, "conflict"):
            backend.mutate_official_workflow(self.conn, detail["id"], "decline", payload, session)
        with self.assertRaises(ValueError):
            backend.cancel_official_document(self.conn, detail["id"], {}, self.session)
        self.assertEqual(detail["current_status"], backend.official_document_row(self.conn, detail["id"])["current_status"])

    def test_hosted_decline_uses_single_terminal_rpc(self):
        detail = self.fixture._submitted()[0]
        _, session, payload = self.decline_payload(detail)
        def rpc(method, endpoint, body):
            self.assertEqual((method, endpoint), ("POST", "rpc/edoc_decline_official_document"))
            plan = body["p_request"]
            self.assertEqual("decline", plan["decision_evidence"]["decision_type"])
            self.assertEqual("declined", plan["document_patch"]["current_status"])
            self.assertEqual([], plan["steps"])
            return {"ok": True, "committed": True, "document_id": detail["id"], "operation_id": payload["operation_id"], "action_result": plan["action_result"]}
        with self.fixture._supabase_adapter(), mock.patch.object(backend, "supabase_request", side_effect=rpc), mock.patch.object(backend, "supabase_official_document_detail", return_value=detail), mock.patch.object(backend, "supabase_patch") as patch, mock.patch.object(backend, "supabase_insert") as insert:
            backend.supabase_mutate_official_workflow(detail["id"], "decline", payload, session)
        patch.assert_not_called()
        insert.assert_not_called()

    def test_shared_forward_is_deterministic_and_browser_roles_denied(self):
        text = render_shared_forward()
        self.assertEqual(text, (ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text())
        self.assertIn("revoke all on function edoc.edoc_decline_official_document(jsonb) from public,anon,authenticated", text)
        self.assertIn("to edoc_backend", text)
        self.assertNotIn("public.official_documents", text)
