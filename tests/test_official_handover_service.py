"""Synthetic API/storage tests. These do not attest human SSO acceptance."""
import copy
import json
import unittest
import urllib.parse
from unittest import mock

import backend
import official_handover_service as service
from tests import test_official_handover_store as fixture


class HandoverServiceTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.HandoverStoreTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.conn = self.fixture.conn
        self.ga = service.Service(backend, self.fixture.proposer_session, self.conn)
        self.ad = service.Service(backend, self.fixture.confirmer_session, self.conn)

    def test_read_queue_and_context_have_no_mutations_or_secrets(self):
        changes = self.conn.total_changes
        queue = self.ga.queue({})
        self.assertEqual([self.fixture.document_id], [row["id"] for row in queue["items"]])
        context = self.ga.context(self.fixture.document_id, {})
        self.assertEqual("FORMER-TEST", context["selected_former_user_id"])
        self.assertEqual(["SUCCESSOR-TEST"], [row["id"] for row in context["candidates"]])
        self.assertEqual(changes, self.conn.total_changes)
        for forbidden in ("email", "password_hash", "decision_evidence_json", "storage_key", "file_hash", "claim_token"):
            self.assertNotIn('"'+forbidden+'"', json.dumps([queue, context]))

    def test_context_and_mutation_recheck_roles_and_exact_company(self):
        fake = {"user": {"id": "APPLICANT-TEST", "role": "總務"}}
        with self.assertRaises(PermissionError): service.Service(backend, fake, self.conn)
        self.conn.execute("UPDATE users SET company_id='OTHER-COMPANY' WHERE id='PROPOSER-TEST'")
        with self.assertRaises(PermissionError): service.Service(backend, self.fixture.proposer_session, self.conn)

    def test_queue_views_and_resolve_do_not_auto_approve(self):
        payload = self.fixture.payload()
        self.ga.propose(self.fixture.document_id, payload)
        self.assertEqual(1, len(self.ga.queue({"view": ["pending"]})["items"]))
        context = self.ad.context(self.fixture.document_id, {})
        self.assertEqual([], context["candidates"])
        self.assertTrue(context["requests"][0]["can_confirm"])
        self.assertEqual("pending", self.conn.execute("SELECT status FROM official_document_approval_steps WHERE id='S2'").fetchone()[0])
        self.ad.resolve(payload["operation_id"], "confirm", {})
        self.assertEqual([], self.ga.queue({"view": ["pending"]})["items"])
        self.assertEqual([], self.ga.queue({})["items"])
        self.assertEqual(1, len(self.ga.queue({"view": ["history"]})["items"]))

    def test_bound_followup_owner_disappears_from_unassigned_queue(self):
        self.conn.execute("UPDATE users SET status='停用' WHERE id='APPLICANT-TEST'")
        self.conn.execute("UPDATE official_document_approval_steps SET approver_user_id='SUCCESSOR-TEST' WHERE id='S2'")
        context = self.ga.context(self.fixture.document_id, {})
        self.assertEqual("followup_owner", context["selected_kind"])
        payload = self.fixture.payload(kind="followup_owner", former="APPLICANT-TEST")
        self.ga.propose(self.fixture.document_id, payload)
        self.ad.resolve(payload["operation_id"], "confirm", {})
        self.assertEqual([], self.ga.queue({})["items"])

    def test_pagination_is_explicit_bounded_and_stable(self):
        for query in ({"page": ["0"]}, {"page_size": ["10000"]}, {"page": ["x"]}, {"view": ["all-tenants"]}):
            with self.subTest(query=query), self.assertRaises(ValueError): self.ga.queue(query)
        self.assertEqual([], self.ga.queue({"page": ["2"], "page_size": ["1"]})["items"])

    def test_departed_successor_returns_to_queue_for_fresh_independent_handover(self):
        self.conn.execute("UPDATE users SET status='停用' WHERE id='APPLICANT-TEST'")
        self.conn.execute("UPDATE official_document_approval_steps SET approver_user_id='MANAGER-TEST' WHERE id='S2'")
        first = self.fixture.payload(kind="followup_owner", former="APPLICANT-TEST")
        self.ga.propose(self.fixture.document_id, first)
        self.ad.resolve(first["operation_id"], "confirm", {})
        self.assertEqual([], self.ga.queue({})["items"])
        self.conn.execute("UPDATE users SET status='停用' WHERE id='SUCCESSOR-TEST'")
        self.assertEqual([self.fixture.document_id], [item["id"] for item in self.ga.queue({})["items"]])
        context = self.ga.context(self.fixture.document_id, {})
        self.assertEqual("SUCCESSOR-TEST", context["selected_former_user_id"])
        self.assertEqual("followup_owner", context["selected_kind"])
        self.assertIn("MANAGER-TEST", [item["id"] for item in context["candidates"]])

    def test_hosted_service_uses_server_actor_and_typed_cas_not_browser_fields(self):
        def get(table, identity):
            row = self.conn.execute(f"SELECT * FROM {table} WHERE id=?", (identity,)).fetchone()
            return dict(row) if row else None
        captured = []
        def request(method, path, body=None):
            if method == "POST":
                captured.append(body["p_request"])
                return {"status": "pending"}
            table, _, query = path.partition("?")
            params = urllib.parse.parse_qs(query)
            filters = {key: values[0][3:] for key, values in params.items() if values[0].startswith("eq.")}
            order = params.get("order", ["id"])[0].replace(".desc", " desc").replace(".asc", " asc")
            sql = f"SELECT * FROM {table} WHERE " + " AND ".join(key+"=?" for key in filters) + f" ORDER BY {order} LIMIT ? OFFSET ?"
            return [dict(row) for row in self.conn.execute(sql, (*filters.values(), int(params["limit"][0]), int(params["offset"][0])))]
        with mock.patch.object(backend, "supabase_get", side_effect=get), mock.patch.object(backend, "supabase_request", side_effect=request):
            hosted = service.Service(backend, self.fixture.proposer_session)
            payload = {**self.fixture.payload(), "actor_id": "CONFIRMER-TEST", "role": "行政部主任", "expected_snapshot": {"forged": True}}
            hosted.propose(self.fixture.document_id, payload)
            self.assertEqual("PROPOSER-TEST", captured[0]["actor_id"])
            self.assertNotEqual(payload["expected_snapshot"], captured[0]["expected_snapshot"])
            self.assertIn("steps", captured[0]["expected_snapshot"])

    def test_rpc_authorization_change_is_safe_403_without_upstream_message(self):
        with mock.patch.object(backend, "supabase_request", side_effect=RuntimeError("supabase_request_failed:403:42501")):
            with self.assertRaisesRegex(PermissionError, "authorization_changed"): self.ga.rpc({})
        with mock.patch.object(backend, "supabase_request", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "response_invalid"): self.ga.rpc({})

    def test_handler_routes_require_authenticated_server_session_and_local_commit(self):
        handler = object.__new__(backend.Handler)
        handler.send_json = mock.Mock()
        handler.read_json = mock.Mock(return_value=self.fixture.payload())
        with self.assertRaises(PermissionError):
            handler.handle_handover_api("GET", ["official-handovers"], {}, None, self.conn)
        handler.handle_handover_api("GET", ["official-handovers"], {}, self.fixture.proposer_session, self.conn)
        self.assertEqual(self.fixture.document_id, handler.send_json.call_args.args[0]["items"][0]["id"])
        handler.handle_handover_api("POST", ["official-documents", self.fixture.document_id, "handovers"], {}, self.fixture.proposer_session, self.conn)
        self.assertFalse(self.conn.in_transaction)
        handler.handle_handover_api("DELETE", ["official-handovers"], {}, self.fixture.proposer_session, self.conn)
        self.assertEqual(405, handler.send_json.call_args.args[1])

    def test_stale_context_then_changed_assignment_is_409_and_no_partial_writes(self):
        payload = self.fixture.payload()
        self.conn.execute("UPDATE official_documents SET content_revision=content_revision+1 WHERE id=?", (self.fixture.document_id,))
        with self.assertRaisesRegex(ValueError, "version_conflict") as caught:
            self.ga.propose(self.fixture.document_id, payload)
        self.assertEqual(409, backend.api_value_error_status(str(caught.exception)))
        self.assertEqual(0, self.conn.execute("SELECT count(*) FROM official_document_handovers").fetchone()[0])


if __name__ == "__main__": unittest.main()
