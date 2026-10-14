"""Candidate feature remains unavailable before server-owned release approval."""
import types
import sqlite3
import unittest
from unittest import mock

import official_handover as policy
import official_handover_followup as followup
import official_handover_service as service
import official_handover_store as store
import backend as application
import official_listing


class HandoverFeatureGateTest(unittest.TestCase):
    def test_missing_and_non_boolean_server_configuration_are_disabled(self):
        for value in (None, False, "1", "true", 1, {}, {"enabled": True}):
            backend = types.SimpleNamespace(EDOC_OFFBOARDING_HANDOVER_ENABLED=value)
            with self.subTest(value=value):
                self.assertFalse(policy.enabled(backend))
                with self.assertRaisesRegex(PermissionError, "handover_feature_disabled"):
                    policy.require_enabled(backend)
        self.assertFalse(policy.enabled(types.SimpleNamespace()))
        self.assertTrue(policy.enabled(types.SimpleNamespace(EDOC_OFFBOARDING_HANDOVER_ENABLED=True)))

    def test_disabled_followup_never_reads_any_table(self):
        backend, conn = mock.Mock(), mock.Mock()
        backend.EDOC_OFFBOARDING_HANDOVER_ENABLED = False
        self.assertIsNone(followup.load(backend, {"id": "UNTRUSTED"}, conn=conn))
        self.assertIsNone(followup.load(backend, {"id": "UNTRUSTED"}))
        backend.supabase_get.assert_not_called()
        backend.supabase_filter_rows.assert_not_called()
        conn.execute.assert_not_called()

    def test_disabled_sqlite_listing_works_with_no_handover_schema_or_helpers(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        application.register_sqlite_functions(conn)
        conn.executescript(application.SCHEMA)
        conn.execute("DROP TABLE IF EXISTS official_document_followup_owners")
        conn.execute("DROP TABLE IF EXISTS official_document_handovers")
        conn.execute("INSERT INTO companies(id,name,created_at,updated_at) VALUES ('CO','Synthetic','x','x')")
        conn.execute("INSERT INTO official_documents(id,company_id,source_type,title,applicant_id,current_status,created_at,updated_at) VALUES ('DOC','CO','uploaded_pdf','Synthetic','ACTOR','draft','2026-10-11 10:00:00','x')")
        session = {"user": {"id": "ACTOR", "company_id": "CO"}, "permissions": []}
        statements = []; conn.set_trace_callback(statements.append)
        with mock.patch.object(application, "EDOC_OFFBOARDING_HANDOVER_ENABLED", False, create=True), mock.patch.object(application, "official_document_followup_binding", side_effect=AssertionError("disabled helper called"), create=True):
            rows = official_listing.list_sqlite(application, conn, {"scope": ["mine"]}, session)
        self.assertEqual(["DOC"], [row["id"] for row in rows])
        self.assertFalse(rows[0]["can_create_linked_application"])
        self.assertFalse(any("official_document_followup_owners" in sql or "official_document_handovers" in sql for sql in statements))

    def test_disabled_projection_does_not_accept_stale_or_forged_followup_binding(self):
        session = {"user": {"id": "ACTOR", "company_id": "CO"}, "permissions": []}
        config = official_listing.options({"scope": ["all"]}, session["user"], session, application)
        bundle = {"document": {"id": "DOC", "company_id": "CO", "applicant_id": "ORIGINAL", "created_at": "2026-10-11 10:00:00", "current_status": "rejected", "metadata_json": "{}"},
                  "followup_binding": {"process_owner_user_id": "ACTOR", "original_applicant_id": "ORIGINAL", "company_id": "CO", "handover_id": "FORGED"}}
        with mock.patch.object(application, "EDOC_OFFBOARDING_HANDOVER_ENABLED", False, create=True):
            self.assertIsNone(official_listing.project(application, bundle, config, session["user"], session))

    def test_disabled_api_adapters_reject_before_auth_or_database_lookup(self):
        backend, conn = mock.Mock(), mock.Mock()
        backend.EDOC_OFFBOARDING_HANDOVER_ENABLED = False
        session = {"user": {"id": "FAKE", "role": "行政部門主任"},
                   "feature_offboarding_handover": True}
        for adapter in (service.Service, followup.LinkedApplication):
            with self.subTest(adapter=adapter.__name__), self.assertRaisesRegex(PermissionError, "handover_feature_disabled"):
                adapter(backend, session, conn)
        for adapter, args in ((store.propose, (conn, "CASE", {}, session)),
                              (store.confirm, (conn, "OPERATION", session)),
                              (store.reject, (conn, "OPERATION", "reason", session))):
            with self.subTest(adapter=adapter.__name__), self.assertRaisesRegex(PermissionError, "handover_feature_disabled"):
                adapter(*args, backend=backend)
        conn.execute.assert_not_called()
        backend.supabase_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
