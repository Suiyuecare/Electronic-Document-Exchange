from __future__ import annotations
import base64
import copy
import unittest
import uuid
from contextlib import nullcontext
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest import mock
import backend
from tests import test_compose_output_backend as fixture


class ComposeResilienceTest(unittest.TestCase):
    setUp = fixture.ComposeOutputBackendTest.setUp
    tearDown = fixture.ComposeOutputBackendTest.tearDown
    payload = fixture.ComposeOutputBackendTest.payload
    create = fixture.ComposeOutputBackendTest.create
    def snapshot(self, **values):
        return {"schemaVersion": 2, "userId": self.session["user"]["id"], "companyId": self.session["user"]["company_id"],
                "values": {"#documentPurpose": "未完成的隔離測試用途", **values}}

    def test_incomplete_cloud_draft_does_not_allocate_number_or_create_official_case(self):
        document_count = self.conn.execute("SELECT count(*) FROM official_documents").fetchone()[0]
        key = "OD-" + str(uuid.uuid4())
        result = backend.save_compose_draft(self.conn, key, {"snapshot": self.snapshot(), "expected_revision": 0}, self.session)
        self.assertEqual(result["revision"], 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM official_documents").fetchone()[0], document_count)
        self.assertEqual(backend.list_compose_drafts(self.conn, self.session)[0]["id"], key)

    def test_cloud_draft_replay_and_stale_device_are_not_silent_overwrites(self):
        key = "OD-" + str(uuid.uuid4())
        first = {"snapshot": self.snapshot(), "expected_revision": 0}
        backend.save_compose_draft(self.conn, key, first, self.session)
        replay = backend.save_compose_draft(self.conn, key, first, self.session)
        self.assertEqual(replay["revision"], 1)
        backend.save_compose_draft(self.conn, key, {"snapshot": self.snapshot(**{"#subject": "裝置 A"}), "expected_revision": 1}, self.session)
        with self.assertRaisesRegex(ValueError, "compose_draft_revision_conflict"):
            backend.save_compose_draft(self.conn, key, {"snapshot": self.snapshot(**{"#subject": "装置 B"}), "expected_revision": 1}, self.session)
        self.assertEqual(backend.list_compose_drafts(self.conn, self.session)[0]["snapshot"]["values"]["#subject"], "裝置 A")

    def test_cloud_draft_rejects_cross_user_company_and_unknown_fields(self):
        key = "OD-" + str(uuid.uuid4())
        snapshot = self.snapshot()
        snapshot["companyId"] = "CO-002"
        with self.assertRaisesRegex(PermissionError, "scope_forbidden"):
            backend.save_compose_draft(self.conn, key, {"snapshot": snapshot, "expected_revision": 0}, self.session)
        with self.assertRaisesRegex(ValueError, "snapshot_invalid"):
            backend.save_compose_draft(self.conn, key, {"snapshot": self.snapshot(**{"#privateFileUrl": "private"}), "expected_revision": 0}, self.session)

    def test_archived_cloud_draft_disappears_from_recovery_list(self):
        key = "OD-" + str(uuid.uuid4())
        payload = {"snapshot": self.snapshot(), "expected_revision": 0}
        backend.save_compose_draft(self.conn, key, payload, self.session)
        backend.save_compose_draft(self.conn, key, {**payload, "expected_revision": 1, "archived": True}, self.session)
        self.assertFalse(backend.list_compose_drafts(self.conn, self.session))

    def test_archive_only_after_formal_submit_is_owner_scoped_cas_and_idempotent(self):
        key = "OD-" + str(uuid.uuid4())
        formal = self.create(id="OD-" + str(uuid.uuid4()), submit=True,
                             metadata={"source": "compose_form", "private_compose_draft_id": key})
        snapshot = {**self.snapshot(), "draftRequestId": formal["id"]}
        backend.save_compose_draft(self.conn, key, {"snapshot": snapshot, "expected_revision": 0}, self.session)
        body = {"official_document_id": formal["id"], "expected_revision": 1}
        with self.assertRaisesRegex(ValueError, "compose_draft_revision_conflict"):
            backend.archive_compose_draft(self.conn, key, {**body, "expected_revision": 0}, self.session)
        self.assertEqual(backend.count_compose_drafts(self.conn, self.session), {"count": 1})
        self.assertEqual(backend.archive_compose_draft(self.conn, key, body, self.session), {"archived": True})
        row = self.conn.execute("SELECT revision, archived FROM official_document_compose_drafts WHERE id=?", (key,)).fetchone()
        self.assertEqual((row["revision"], row["archived"]), (2, 1))
        self.assertEqual(backend.count_compose_drafts(self.conn, self.session), {"count": 0})
        self.assertEqual(backend.archive_compose_draft(self.conn, key, body, self.session), {"archived": True})
        self.assertEqual(backend.archive_compose_draft(self.conn, key, {**body, "expected_revision": 0}, self.session), {"archived": True})
        with self.assertRaisesRegex(ValueError, "compose_draft_revision_conflict"):
            backend.save_compose_draft(self.conn, key, {"snapshot": snapshot, "expected_revision": 1}, self.session)

    def test_archive_only_blocks_draft_document_wrong_link_and_concurrent_edit(self):
        key = "OD-" + str(uuid.uuid4())
        formal = self.create(id="OD-" + str(uuid.uuid4()), submit=False,
                             metadata={"source": "compose_form", "private_compose_draft_id": key})
        snapshot = {**self.snapshot(), "draftRequestId": formal["id"]}
        backend.save_compose_draft(self.conn, key, {"snapshot": snapshot, "expected_revision": 0}, self.session)
        body = {"official_document_id": formal["id"], "expected_revision": 1}
        with self.assertRaisesRegex(ValueError, "compose_draft_archive_document_not_submitted"):
            backend.archive_compose_draft(self.conn, key, body, self.session)
        submitted = backend.submit_official_document(self.conn, formal["id"], {
            "expected_content_revision": formal["content_revision"],
        }, self.session)
        self.assertNotEqual(submitted["current_status"], "draft")
        backend.save_compose_draft(self.conn, key, {
            "snapshot": {**snapshot, "values": {"#documentPurpose": "另一裝置較新的編輯"}}, "expected_revision": 1,
        }, self.session)
        with self.assertRaisesRegex(ValueError, "compose_draft_revision_conflict"):
            backend.archive_compose_draft(self.conn, key, body, self.session)
        self.assertEqual(backend.count_compose_drafts(self.conn, self.session), {"count": 1})
        self.assertEqual(backend.archive_compose_draft(self.conn, key, {**body, "expected_revision": 2}, self.session), {"archived": True})

        another_key = "OD-" + str(uuid.uuid4())
        backend.save_compose_draft(self.conn, another_key, {"snapshot": self.snapshot(), "expected_revision": 0}, self.session)
        with self.assertRaisesRegex(ValueError, "compose_draft_archive_link_mismatch"):
            backend.archive_compose_draft(self.conn, another_key, {**body, "expected_revision": 1}, self.session)
        self.assertEqual(backend.count_compose_drafts(self.conn, self.session), {"count": 1})

    def test_archive_only_validates_official_owner_and_legacy_link_before_noop(self):
        key = "OD-" + str(uuid.uuid4())
        formal = self.create(id="OD-" + str(uuid.uuid4()), submit=True, metadata={"source": "compose_form"})
        body = {"official_document_id": formal["id"], "expected_revision": 1}
        self.assertEqual(backend.archive_compose_draft(self.conn, key, {"official_document_id": formal["id"], "expected_revision": 0}, self.session), {"archived": True})
        backend.save_compose_draft(self.conn, key, {"snapshot": self.snapshot(), "expected_revision": 0}, self.session)
        with self.assertRaisesRegex(ValueError, "compose_draft_archive_link_required"):
            backend.archive_compose_draft(self.conn, key, body, self.session)
        backend.save_compose_draft(self.conn, key, {
            "snapshot": {**self.snapshot(), "officialDocumentId": formal["id"]}, "expected_revision": 1,
        }, self.session)
        self.assertEqual(backend.archive_compose_draft(self.conn, key, {**body, "expected_revision": 2}, self.session), {"archived": True})

        foreign = self.create(id="OD-" + str(uuid.uuid4()), submit=True, metadata={"source": "compose_form"})
        other_user = self.conn.execute("SELECT id FROM users WHERE id<>? AND company_id=? LIMIT 1",
                                       (self.session["user"]["id"], self.session["user"]["company_id"])).fetchone()["id"]
        other_session = self.fixture.session_for_user_id(other_user)
        other_session["permissions"].append("official_documents.compose")
        with self.assertRaisesRegex(PermissionError, "compose_draft_archive_document_forbidden"):
            backend.archive_compose_draft(self.conn, "OD-" + str(uuid.uuid4()), {"official_document_id": foreign["id"]}, other_session)
        with self.assertRaisesRegex(ValueError, "compose_draft_archive_payload_invalid"):
            backend.archive_compose_draft(self.conn, key, {**body, "snapshot": {}}, self.session)

    def test_supabase_archive_only_uses_scoped_cas_patch_and_noop(self):
        key = "OD-" + str(uuid.uuid4())
        formal_id = "OD-" + str(uuid.uuid4())
        user = self.session["user"]
        document = {"id": formal_id, "applicant_id": user["id"], "company_id": user["company_id"],
                    "current_status": "pending_applicant_manager", "source_type": "blank_editor",
                    "document_type": "outgoing_official_document",
                    "metadata_json": {"source": "compose_form", "extra": {"private_compose_draft_id": key}}}
        row = {"id": key, "applicant_id": user["id"], "company_id": user["company_id"],
               "revision": 3, "archived": False, "snapshot_json": self.snapshot()}
        body = {"official_document_id": formal_id, "expected_revision": 3}
        with mock.patch.object(backend, "supabase_filter_rows", side_effect=[[document], [row]]) as filtered, mock.patch.object(
            backend, "supabase_update_many", return_value=[{"id": key, "archived": True, "revision": 4}]
        ) as update:
            self.assertEqual(backend.supabase_archive_compose_draft(key, body, self.session), {"archived": True})
        self.assertEqual(filtered.call_args_list[0].args[:2], ("official_documents", {
            "id": formal_id, "applicant_id": user["id"], "company_id": user["company_id"],
        }))
        self.assertEqual(filtered.call_args_list[1].args[:2], ("official_document_compose_drafts", {
            "id": key, "applicant_id": user["id"], "company_id": user["company_id"],
        }))
        self.assertEqual(update.call_args.args[1], {
            "id": key, "applicant_id": user["id"], "company_id": user["company_id"], "archived": False, "revision": 3,
        })
        self.assertEqual(update.call_args.args[2]["revision"], 4)
        self.assertTrue(update.call_args.args[2]["archived"])
        with mock.patch.object(backend, "supabase_filter_rows", side_effect=[[document], []]), mock.patch.object(
            backend, "supabase_update_many", side_effect=AssertionError("missing row must be a no-op")
        ):
            self.assertEqual(backend.supabase_archive_compose_draft(key, {"official_document_id": formal_id, "expected_revision": 0}, self.session), {"archived": True})
        with mock.patch.object(backend, "supabase_filter_rows", side_effect=[[document], [row]]), mock.patch.object(
            backend, "supabase_update_many", side_effect=AssertionError("unknown revision must not update")
        ):
            with self.assertRaisesRegex(ValueError, "compose_draft_revision_conflict"):
                backend.supabase_archive_compose_draft(key, {"official_document_id": formal_id, "expected_revision": 0}, self.session)

    def test_supabase_archive_only_refuses_concurrent_patch_and_replay_is_idempotent(self):
        key = "OD-" + str(uuid.uuid4())
        formal_id = "OD-" + str(uuid.uuid4())
        user = self.session["user"]
        document = {"id": formal_id, "applicant_id": user["id"], "company_id": user["company_id"],
                    "current_status": "pending_applicant_manager", "source_type": "blank_editor",
                    "document_type": "outgoing_official_document",
                    "metadata_json": {"source": "compose_form", "extra": {"private_compose_draft_id": key}}}
        row = {"id": key, "applicant_id": user["id"], "company_id": user["company_id"],
               "revision": 3, "archived": False, "snapshot_json": self.snapshot()}
        body = {"official_document_id": formal_id, "expected_revision": 3}
        # A concurrent editor won the CAS after the initial read; never discard
        # the newer revision, and keep the frontend cleanup marker retryable.
        with mock.patch.object(backend, "supabase_filter_rows", side_effect=[[document], [row],
                                                               [{"id": key, "archived": False, "revision": 4}]]), mock.patch.object(
            backend, "supabase_update_many", return_value=[]
        ) as update:
            with self.assertRaisesRegex(ValueError, "compose_draft_revision_conflict"):
                backend.supabase_archive_compose_draft(key, body, self.session)
        self.assertEqual(update.call_args.args[1]["revision"], 3)
        # If the same archive request already succeeded but its response was
        # lost, the scoped read is a no-op without another PATCH.
        with mock.patch.object(backend, "supabase_filter_rows", side_effect=[[document], [{**row, "archived": True, "revision": 4}]]), mock.patch.object(
            backend, "supabase_update_many", side_effect=AssertionError("replay must not update")
        ):
            self.assertEqual(backend.supabase_archive_compose_draft(key, body, self.session), {"archived": True})

    def test_archive_post_routes_are_no_store_and_forward_only_private_cleanup(self):
        key = "OD-" + str(uuid.uuid4())
        formal_id = "OD-" + str(uuid.uuid4())
        body = {"official_document_id": formal_id, "expected_revision": 7}
        handler = object.__new__(backend.Handler)
        handler.bearer_token = lambda: "isolated-test-token"
        handler.read_json = lambda: dict(body)
        responses = []
        handler.send_json = lambda payload, status=200, **kwargs: responses.append((payload, status, kwargs.get("extra_headers")))
        route = f"/api/compose-drafts/{key}/archive"
        with mock.patch.object(backend, "USE_SUPABASE", True), mock.patch.object(
            backend, "supabase_current_session", return_value=self.session
        ), mock.patch.object(backend, "supabase_archive_compose_draft", return_value={"archived": True}) as archive:
            handler.handle_api("POST", route, {})
        archive.assert_called_once_with(key, body, self.session)
        self.assertEqual(responses.pop(), ({"archived": True}, 200, [("Cache-Control", "private, no-store")]))
        with mock.patch.object(backend, "USE_SUPABASE", False), mock.patch.object(
            backend, "connect", return_value=self.conn
        ), mock.patch.object(backend, "current_session", return_value=self.session), mock.patch.object(
            backend, "archive_compose_draft", return_value={"archived": True}
        ) as archive:
            handler.handle_api("POST", route, {})
        archive.assert_called_once_with(self.conn, key, body, self.session)
        self.assertEqual(responses.pop(), ({"archived": True}, 200, [("Cache-Control", "private, no-store")]))

    def test_cloud_draft_exact_count_and_paginated_recovery_are_owner_scoped(self):
        own_ids = []
        for _ in range(22):
            key = "OD-" + str(uuid.uuid4())
            backend.save_compose_draft(self.conn, key, {"snapshot": self.snapshot(), "expected_revision": 0}, self.session)
            own_ids.append(key)
        self.assertEqual(backend.count_compose_drafts(self.conn, self.session), {"count": 22})
        first = backend.list_compose_drafts(self.conn, self.session)
        second = backend.list_compose_drafts(self.conn, self.session, {"offset": ["20"], "limit": ["20"]})
        self.assertEqual(len(first), 20)
        self.assertEqual(len(second), 2)
        self.assertEqual({row["id"] for row in first + second}, set(own_ids))

        other = self.conn.execute(
            "SELECT id FROM users WHERE id <> ? AND company_id = ? LIMIT 1",
            (self.session["user"]["id"], self.session["user"]["company_id"]),
        ).fetchone()
        self.assertIsNotNone(other)
        other_session = self.fixture.session_for_user_id(other["id"])
        other_session["permissions"].append("official_documents.compose")
        other_key = "OD-" + str(uuid.uuid4())
        other_snapshot = {**self.snapshot(), "userId": other["id"]}
        backend.save_compose_draft(self.conn, other_key, {"snapshot": other_snapshot, "expected_revision": 0}, other_session)
        self.assertEqual(backend.count_compose_drafts(self.conn, self.session), {"count": 22})
        self.assertEqual(backend.count_compose_drafts(self.conn, other_session), {"count": 1})
        self.assertEqual(backend.count_compose_drafts(self.conn, self.session, {"probe_id": [own_ids[0]]}), {"count": 22, "probeExists": True})
        self.assertEqual(backend.count_compose_drafts(self.conn, self.session, {"probe_id": [other_key]}), {"count": 22, "probeExists": False})
        self.assertNotIn(other_key, {row["id"] for row in first + second})

        # A historical/mis-scoped row with the same applicant must not cross the
        # Finance-company boundary even if a backend import left it in storage.
        cross_company_key = "OD-" + str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO official_document_compose_drafts (id, company_id, applicant_id, revision, snapshot_json, snapshot_hash, archived, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cross_company_key, "CO-002", self.session["user"]["id"], 1, "{}", "synthetic-hash", 0, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
        self.assertEqual(backend.count_compose_drafts(self.conn, self.session), {"count": 22})
        self.assertEqual(backend.count_compose_drafts(self.conn, self.session, {"probe_id": [cross_company_key]}), {"count": 22, "probeExists": False})
        self.assertNotIn(cross_company_key, {row["id"] for row in backend.list_compose_drafts(self.conn, self.session)})

        backend.save_compose_draft(self.conn, own_ids[0], {
            "snapshot": self.snapshot(), "expected_revision": 1, "archived": True,
        }, self.session)
        self.assertEqual(backend.count_compose_drafts(self.conn, self.session), {"count": 21})
        self.assertEqual(backend.count_compose_drafts(self.conn, self.session, {"probe_id": [own_ids[0]]}), {"count": 21, "probeExists": False})
        self.assertEqual(backend.count_compose_drafts(self.conn, self.session, {"probe_id": ["OD-" + str(uuid.uuid4())]}), {"count": 21, "probeExists": False})
        no_compose = {**self.session, "permissions": []}
        with self.assertRaisesRegex(PermissionError, "official_document_create_forbidden"):
            backend.count_compose_drafts(self.conn, no_compose)
        with self.assertRaisesRegex(PermissionError, "authentication_required"):
            backend.count_compose_drafts(self.conn, None)

    def test_compose_draft_pagination_rejects_bad_values_and_caps_page_size(self):
        for query in ({"offset": ["-1"]}, {"offset": ["1000001"]}, {"limit": ["0"]}, {"limit": ["oops"]}):
            with self.subTest(query=query), self.assertRaisesRegex(ValueError, "compose_draft_pagination_invalid"):
                backend.list_compose_drafts(self.conn, self.session, query)
        self.assertEqual(backend.compose_draft_page({"offset": ["2"], "limit": ["500"]}), (2, 100))

    def test_compose_draft_count_rejects_invalid_probe_ids(self):
        for query in (
            {"probe_id": [""]}, {"probe_id": ["OD-truncated"]},
            {"probe_id": ["OD-" + "z" * 36]},
            {"probe_id": ["OD-" + str(uuid.uuid4()), "OD-" + str(uuid.uuid4())]},
        ):
            with self.subTest(query=query), self.assertRaisesRegex(ValueError, "compose_draft_id_invalid"):
                backend.count_compose_drafts(self.conn, self.session, query)
        self.assertEqual(backend.count_compose_drafts(self.conn, self.session), {"count": 0})

        handler = object.__new__(backend.Handler)
        handler.path = "/api/compose-drafts/count?probe_id="
        handled = []
        handler.handle_api = lambda *args: handled.append(args)
        handler.do_GET()
        self.assertEqual(handled, [("GET", "/api/compose-drafts/count", {"probe_id": [""]})])

    def test_supabase_compose_count_uses_exact_head_owner_filters(self):
        captured = []
        response = SimpleNamespace(headers={"Content-Range": "0-0/27"})
        def open_request(request, *, timeout):
            captured.append((request, timeout))
            return nullcontext(response)
        with mock.patch.object(backend, "SUPABASE_URL", "https://example.supabase.co"), mock.patch.object(
            backend, "SUPABASE_SERVICE_ROLE_KEY", "sb_secret_unit_test"
        ), mock.patch.object(backend, "supabase_headers", return_value={"Prefer": "count=exact"}), mock.patch.object(
            backend, "_urlopen_no_redirect", side_effect=open_request
        ):
            self.assertEqual(backend.supabase_count_compose_drafts(self.session), {"count": 27})
            response.headers["Content-Range"] = "*/0"
            self.assertEqual(backend.supabase_count_compose_drafts(self.session), {"count": 0})
            response.headers["Content-Range"] = "0-0/*"
            with self.assertRaisesRegex(RuntimeError, "supabase_count_invalid_response"):
                backend.supabase_count_compose_drafts(self.session)
        request, timeout = captured[0]
        self.assertEqual(request.get_method(), "HEAD")
        self.assertEqual(timeout, 20)
        self.assertEqual(request.get_header("Prefer"), "count=exact")
        params = parse_qs(urlparse(request.full_url).query)
        self.assertEqual(params["applicant_id"], [f"eq.{self.session['user']['id']}"])
        self.assertEqual(params["company_id"], [f"eq.{self.session['user']['company_id']}"])
        self.assertEqual(params["archived"], ["eq.false"])
        self.assertEqual(params["limit"], ["1"])

    def test_supabase_compose_probe_is_scoped_and_optional(self):
        key = "OD-" + str(uuid.uuid4())
        response = SimpleNamespace(headers={"Content-Range": "0-0/1"})
        with mock.patch.object(backend, "SUPABASE_URL", "https://example.supabase.co"), mock.patch.object(
            backend, "SUPABASE_SERVICE_ROLE_KEY", "sb_secret_unit_test"
        ), mock.patch.object(backend, "supabase_headers", return_value={"Prefer": "count=exact"}), mock.patch.object(
            backend, "_urlopen_no_redirect", return_value=nullcontext(response)
        ), mock.patch.object(backend, "supabase_filter_rows", return_value=[{"id": key}]) as filtered:
            self.assertEqual(backend.supabase_count_compose_drafts(self.session), {"count": 1})
            filtered.assert_not_called()
            self.assertEqual(backend.supabase_count_compose_drafts(self.session, {"probe_id": [key]}), {"count": 1, "probeExists": True})
            filtered.assert_called_once_with("official_document_compose_drafts", {
                "id": key, "applicant_id": self.session["user"]["id"],
                "company_id": self.session["user"]["company_id"], "archived": False,
            }, limit=1, select="id")
            filtered.reset_mock(return_value=True)
            filtered.return_value = []
            self.assertEqual(backend.supabase_count_compose_drafts(self.session, {"probe_id": [key]}), {"count": 1, "probeExists": False})

    def test_supabase_compose_list_uses_same_scope_and_requested_offset(self):
        with mock.patch.object(backend, "supabase_request", return_value=[]) as request:
            self.assertEqual(backend.supabase_list_compose_drafts(self.session, {"offset": ["20"], "limit": ["500"]}), [])
        method, path = request.call_args.args
        self.assertEqual(method, "GET")
        params = parse_qs(urlparse(path).query)
        self.assertEqual(params["applicant_id"], [f"eq.{self.session['user']['id']}"])
        self.assertEqual(params["company_id"], [f"eq.{self.session['user']['company_id']}"])
        self.assertEqual(params["archived"], ["eq.false"])
        self.assertEqual(params["offset"], ["20"])
        self.assertEqual(params["limit"], ["100"])

    def test_supabase_compose_routes_forward_count_and_pagination(self):
        handler = object.__new__(backend.Handler)
        responses = []
        handler.bearer_token = lambda: "isolated-test-token"
        handler.send_json = lambda payload, status=200, **kwargs: responses.append((payload, status, kwargs.get("extra_headers")))
        page = {"offset": ["20"], "limit": ["10"]}
        probe = {"probe_id": ["OD-" + str(uuid.uuid4())]}
        with mock.patch.object(backend, "USE_SUPABASE", True), mock.patch.object(
            backend, "supabase_current_session", return_value=self.session
        ), mock.patch.object(backend, "supabase_count_compose_drafts", side_effect=[{"count": 27}, {"count": 27, "probeExists": False}]) as count, mock.patch.object(
            backend, "supabase_list_compose_drafts", return_value=[]
        ) as listing:
            handler.handle_api("GET", "/api/compose-drafts/count", {})
            handler.handle_api("GET", "/api/compose-drafts/count", probe)
            handler.handle_api("GET", "/api/compose-drafts", page)
        no_store = [("Cache-Control", "private, no-store")]
        self.assertEqual(responses, [({"count": 27}, 200, no_store), ({"count": 27, "probeExists": False}, 200, no_store), ([], 200, no_store)])
        self.assertEqual(count.call_args_list, [mock.call(self.session, {}), mock.call(self.session, probe)])
        listing.assert_called_once_with(self.session, page)

    def test_sqlite_compose_routes_return_exact_count_and_legacy_array(self):
        key = "OD-" + str(uuid.uuid4())
        backend.save_compose_draft(self.conn, key, {"snapshot": self.snapshot(), "expected_revision": 0}, self.session)
        handler = object.__new__(backend.Handler)
        responses = []
        handler.bearer_token = lambda: "isolated-test-token"
        handler.send_json = lambda payload, status=200, **kwargs: responses.append((payload, status, kwargs.get("extra_headers")))
        with mock.patch.object(backend, "USE_SUPABASE", False), mock.patch.object(
            backend, "connect", return_value=self.conn
        ), mock.patch.object(backend, "current_session", return_value=self.session):
            handler.handle_api("GET", "/api/compose-drafts/count", {})
            handler.handle_api("GET", "/api/compose-drafts/count", {"probe_id": [key]})
            handler.handle_api("GET", "/api/compose-drafts", {})
        no_store = [("Cache-Control", "private, no-store")]
        self.assertEqual(responses[0], ({"count": 1}, 200, no_store))
        self.assertEqual(responses[1], ({"count": 1, "probeExists": True}, 200, no_store))
        self.assertEqual([row["id"] for row in responses[2][0]], [key])
        self.assertEqual(responses[2][1:], (200, no_store))

    def test_compose_content_revision_stale_patch_and_submit_rejected(self):
        draft = self.create(metadata={"source": "compose_form"})
        self.assertEqual(draft["content_revision"], 0)
        with self.assertRaisesRegex(ValueError, "revision_required"):
            backend.update_official_document_correction(self.conn, draft["id"], {"subject": "無版本"}, self.session)
        updated = backend.update_official_document_correction(self.conn, draft["id"], {"subject": "裝置一已修改", "expected_content_revision": 0}, self.session)
        self.assertEqual(updated["content_revision"], 1)
        self.assertEqual(updated["dispatch_no"], draft["dispatch_no"])
        for operation in (backend.update_official_document_correction, backend.submit_official_document):
            with self.assertRaisesRegex(ValueError, "revision_conflict"):
                operation(self.conn, draft["id"], {"subject": "裝置二舊文字", "expected_content_revision": 0}, self.session)
        self.assertEqual(backend.official_document_row(self.conn, draft["id"])["subject"], "裝置一已修改")
        self.assertEqual(backend.api_value_error_status("compose_content_revision_conflict"), 409)

    def test_attachment_response_loss_replays_same_file_and_refuses_different_bytes(self):
        draft = self.create()
        pdf = backend.build_official_pdf({"subject": "隔離附件", "body": "測試用"})
        payload = {"file_name": "fixture.pdf", "file_mime_type": "application/pdf", "content_base64": base64.b64encode(pdf).decode(), "upload_id": "fixture-upload-0000001"}
        with mock.patch.object(backend, "scan_official_upload_bytes", return_value=("clean", "fixture")):
            first = backend.upload_official_document_attachment(self.conn, draft["id"], payload, self.session)
            second = backend.upload_official_document_attachment(self.conn, draft["id"], payload, self.session)
            self.assertEqual(first["file"]["id"], second["file"]["id"])
            self.assertTrue(second["upload_replayed"])
            self.assertEqual(self.conn.execute("SELECT count(*) FROM official_document_files WHERE document_id=? AND file_type='attachment'", (draft["id"],)).fetchone()[0], 1)
            with self.assertRaisesRegex(ValueError, "upload_id_conflict"):
                backend.upload_official_document_attachment(self.conn, draft["id"], {**payload, "file_name": "changed.pdf"}, self.session)

    def test_submission_rechecks_content_revision_after_workflow_resolution(self):
        draft = self.create(metadata={"source": "compose_form"})
        original = backend.configured_official_workflow_steps
        def competing_edit(*args, **kwargs):
            steps = original(*args, **kwargs)
            self.conn.execute("UPDATE official_documents SET content_revision=content_revision+1,subject=? WHERE id=?", ("競爭更新", draft["id"]))
            return steps
        with mock.patch.object(backend, "configured_official_workflow_steps", side_effect=competing_edit), mock.patch.object(
            backend, "assert_official_document_uploads_av_clean",
        ) as scan:
            with self.assertRaisesRegex(ValueError, "compose_content_revision_conflict"):
                backend.submit_official_document(self.conn, draft["id"], {"expected_content_revision": 0}, self.session)
        scan.assert_not_called()
        self.assertEqual(backend.official_document_row(self.conn, draft["id"])["current_status"], "draft")


if __name__ == "__main__":
    unittest.main()
