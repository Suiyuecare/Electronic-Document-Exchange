"""Public session projections and disabled candidate API boundaries.

These tests use synthetic RAM-only users, not real employee OAuth accounts.
"""
import copy
import sqlite3
import unittest
from unittest import mock

import backend
from tests import test_login_performance_contract as finance_fixture


class BackendHandoverReleaseGateTest(unittest.TestCase):
    def setUp(self):
        self.user = {
            "id": "ACTOR-GATE", "name": "Synthetic actor", "role": "員工",
            "email": "actor@example.invalid", "status": "啟用",
            "company_id": "CO-GATE", "finance_tenant_id": "TENANT-GATE",
            "account_source": "finance", "feature_offboarding_handover": True,
        }

    def test_public_projection_overwrites_untrusted_flags_without_mutating_source(self):
        for enabled in (False, True, "1", 1, None):
            for persisted in (True, False, "enabled"):
                source = {**self.user, "feature_offboarding_handover": persisted,
                          "password_hash": "synthetic-not-a-password"}
                original = copy.deepcopy(source)
                with self.subTest(enabled=enabled, persisted=persisted), mock.patch.object(
                    backend, "EDOC_OFFBOARDING_HANDOVER_ENABLED", enabled
                ):
                    public = backend.public_user(source)
                self.assertIs(public["feature_offboarding_handover"], enabled is True)
                self.assertNotIn("password_hash", public)
                self.assertEqual(original, source)

    def test_local_auth_me_applies_live_server_gate(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(backend.SCHEMA)
        self.addCleanup(conn.close)
        conn.execute("""INSERT INTO users(id,name,email,role,status,account_source,
                     company_id,finance_tenant_id,created_at)
                     VALUES ('ACTOR-GATE','Synthetic actor','actor@example.invalid',
                     '員工','啟用','finance','CO-GATE','TENANT-GATE','2026-10-11')""")
        conn.execute("""INSERT INTO auth_sessions(id,user_id,token_hash,provider,expires_at,created_at)
                     VALUES ('SESSION-GATE','ACTOR-GATE',?,'isolated-test',
                     '2099-01-01 00:00:00','2026-10-11')""", (backend.hash_token("synthetic-session"),))
        for enabled in (False, True, False):
            with self.subTest(enabled=enabled), mock.patch.object(backend, "is_production", return_value=False), mock.patch.object(
                backend, "EDOC_OFFBOARDING_HANDOVER_ENABLED", enabled
            ):
                result = backend.current_session(conn, "synthetic-session")
            self.assertIs(result["user"]["feature_offboarding_handover"], enabled)
            self.assertEqual("ACTOR-GATE", result["user"]["id"])

    def test_hosted_auth_me_overrides_stale_rpc_flags(self):
        bundle = {"session": {"id": "SESSION-GATE", "user_id": self.user["id"],
                              "expires_at": "2099-01-01 00:00:00"},
                  "user": self.user, "permissions": ["official_documents.compose"]}
        original = copy.deepcopy(bundle)
        for enabled in (False, True, False):
            with self.subTest(enabled=enabled), mock.patch.object(backend, "is_production", return_value=False), mock.patch.object(
                backend, "EDOC_OFFBOARDING_HANDOVER_ENABLED", enabled
            ), mock.patch.object(backend, "supabase_request", return_value=bundle) as request:
                result = backend.supabase_current_session("synthetic-session")
            self.assertIs(result["user"]["feature_offboarding_handover"], enabled)
            request.assert_called_once()
        self.assertEqual(original, bundle)

    def test_atomic_finance_login_also_projects_server_gate(self):
        fixture = finance_fixture.FinanceSessionFastPathTest()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        user = {**fixture.user, "feature_offboarding_handover": True}

        def response(method, path, payload):
            self.assertEqual("rpc/edoc_create_finance_login_session_v2", path)
            return {"session": {"id": payload["p_session_id"], "user_id": user["id"],
                                "expires_at": payload["p_expires_at"]},
                    "user": copy.deepcopy(user), "permissions": ["official_documents.compose"]}

        for enabled in (False, True):
            with self.subTest(enabled=enabled), mock.patch.object(
                backend, "EDOC_OFFBOARDING_HANDOVER_ENABLED", enabled
            ), mock.patch.object(backend, "supabase_request", side_effect=response):
                result = backend.supabase_create_finance_login_session(
                    user, "127.0.0.1", "isolated-test", expected_binding=fixture.expected_binding()
                )
            self.assertIs(result["user"]["feature_offboarding_handover"], enabled)

    def test_disabled_candidate_routes_never_read_body_or_candidate_tables(self):
        handler = object.__new__(backend.Handler)
        handler.read_json = mock.Mock(side_effect=AssertionError("disabled body read"))
        handler.send_json = mock.Mock(side_effect=AssertionError("disabled success response"))
        conn = mock.Mock()
        session = {"user": {**self.user, "role": "行政部主任"},
                   "feature_offboarding_handover": True}
        routes = (
            ("GET", ["official-handovers"]),
            ("GET", ["official-documents", "CASE", "handover-context"]),
            ("POST", ["official-documents", "CASE", "handovers"]),
            ("POST", ["official-handovers", "REQUEST", "confirm"]),
            ("POST", ["official-handovers", "REQUEST", "reject"]),
            ("GET", ["official-documents", "CASE", "linked-application"]),
            ("POST", ["official-documents", "CASE", "linked-application"]),
        )
        with mock.patch.object(backend, "EDOC_OFFBOARDING_HANDOVER_ENABLED", False), mock.patch.object(
            backend, "supabase_get", side_effect=AssertionError("disabled remote lookup")
        ):
            for method, parts in routes:
                for storage in (None, conn):
                    with self.subTest(method=method, parts=parts, local=storage is not None), self.assertRaisesRegex(
                        PermissionError, "handover_feature_disabled"
                    ):
                        handler.handle_handover_api(method, parts, {}, session, storage)
        handler.read_json.assert_not_called()
        handler.send_json.assert_not_called()
        self.assertEqual([], conn.mock_calls)

    def test_candidate_tables_are_never_generic_crud(self):
        session = {"user": self.user, "permissions": ["system_permissions.manage", "official_documents.all_todo"]}
        for enabled in (False, True):
            with mock.patch.object(backend, "EDOC_OFFBOARDING_HANDOVER_ENABLED", enabled):
                for table in ("official_document_handovers", "official_document_followup_owners"):
                    for write in (False, True):
                        self.assertFalse(backend.can_access_generic_table_api(session, table, write=write))


if __name__ == "__main__":
    unittest.main()
