from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
import unittest

import backend


class LoggingAlignedPermissionsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(backend.SCHEMA)
        backend.seed(self.conn)
        backend.seed_auth(self.conn)
        backend.ensure_allowed_edoc_users(self.conn)
        backend.normalize_legacy_document_owners(self.conn)
        backend.seed_department_isolation_examples(self.conn)
        backend.seed_document_acl_examples(self.conn)
        backend.seed_jobs(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def login_session(self, email: str) -> dict:
        session, status = backend.authenticate_local(
            self.conn,
            {"email": email, "password": "demo1234", "provider": "unittest"},
            "127.0.0.1",
            "unittest",
        )
        self.assertEqual(status, 200)
        return session

    def test_role_permissions_follow_logging_module_action_codes(self) -> None:
        admin_codes = set(backend.role_permission_codes(self.conn, "行政部主任"))
        general_affairs_codes = set(backend.role_permission_codes(self.conn, "總務"))
        employee_codes = set(backend.role_permission_codes(self.conn, "員工"))
        supervisor_codes = set(backend.role_permission_codes(self.conn, "主管"))

        self.assertIn("system_permissions.manage", admin_codes)
        self.assertIn("system_permissions.view", admin_codes)
        self.assertIn("official_documents.receive", general_affairs_codes)
        self.assertIn("exchange.manage", general_affairs_codes)
        self.assertIn("official_documents.compose", employee_codes)
        self.assertIn("official_documents.records", employee_codes)
        self.assertIn("official_documents.todo", supervisor_codes)
        self.assertIn("reports.operational_view", supervisor_codes)
        self.assertNotIn("official_documents.receive", employee_codes)
        self.assertNotIn("system_permissions.manage", general_affairs_codes)

    def test_backoffice_tables_require_matching_permissions(self) -> None:
        sales_session = self.login_session("sales-assistant@suiyuecare.com")
        supervisor_session = self.login_session("director@suiyuecare.com")
        admin_session = self.login_session("records@suiyuecare.com")

        for session in [sales_session, supervisor_session]:
            with self.subTest(role=session["user"]["role"]):
                self.assertFalse(backend.can_read_table(session, "users"))
                self.assertFalse(backend.can_read_table(session, "role_permissions"))
                self.assertFalse(backend.can_read_table(session, "audit_logs"))
                self.assertFalse(backend.can_write_table(session, "users"))

        self.assertTrue(backend.can_read_table(admin_session, "users"))
        self.assertTrue(backend.can_read_table(admin_session, "role_permissions"))
        self.assertTrue(backend.can_read_table(admin_session, "audit_logs"))
        self.assertTrue(backend.can_write_table(admin_session, "users"))
        self.assertFalse(backend.can_read_table(None, "documents"))
        self.assertFalse(backend.can_write_table(None, "documents"))

    def test_dashboard_counts_are_scoped_to_logged_in_role(self) -> None:
        sales_session = self.login_session("sales-assistant@suiyuecare.com")
        supervisor_session = self.login_session("director@suiyuecare.com")
        admin_session = self.login_session("records@suiyuecare.com")

        for session in [sales_session, supervisor_session, admin_session]:
            with self.subTest(role=session["user"]["role"]):
                scoped_docs = backend.scoped_document_rows(self.conn, {}, session)
                metrics = backend.dashboard(self.conn, session)
                self.assertEqual(metrics["documents"], len(scoped_docs))

        self.assertEqual(backend.dashboard(self.conn, sales_session)["auditLogs"], 0)
        self.assertEqual(backend.dashboard(self.conn, supervisor_session)["auditLogs"], 0)
        self.assertGreater(backend.dashboard(self.conn, admin_session)["auditLogs"], 0)
        self.assertEqual(backend.dashboard(self.conn, None)["documents"], 0)

    def test_unified_search_respects_backoffice_table_permissions(self) -> None:
        sales_session = self.login_session("sales-assistant@suiyuecare.com")
        admin_session = self.login_session("records@suiyuecare.com")

        restricted = backend.unified_search(self.conn, {"category": ["audit_logs"], "q": ["登入"]}, sales_session)
        allowed = backend.unified_search(self.conn, {"category": ["audit_logs"], "q": ["登入"]}, admin_session)

        self.assertEqual(restricted["count"], 0)
        self.assertGreater(allowed["count"], 0)

    def test_permission_change_audit_uses_logging_snapshots(self) -> None:
        backend.patch_row(self.conn, "users", "USR-007", {"role": "人資", "job_level": "課長"})

        row = self.conn.execute(
            """
            SELECT *
            FROM audit_logs
            WHERE event_type = 'permission_change'
            ORDER BY rowid DESC
            LIMIT 1
            """
        ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["severity"], "critical")
        self.assertEqual(row["module_code"], "system_permissions")
        self.assertEqual(row["resource_type"], "user_role")
        self.assertEqual(row["target_email"], "sales-assistant@suiyuecare.com")
        before = json.loads(row["before_snapshot_json"])
        after = json.loads(row["after_snapshot_json"])
        self.assertEqual(before["role"], "業務助理")
        self.assertEqual(after["role"], "人資")
        self.assertEqual(after["job_level"], "課長")

    def test_roster_profile_derives_edoc_role_and_scope(self) -> None:
        cases = [
            ({"職等": "職員", "職稱": "居家照顧服務員", "所屬部門": "居家照顧部"}, ("員工", "department")),
            ({"職等": "組長", "職稱": "居家服務督導", "所屬部門": "居家照顧部"}, ("主管", "department")),
            ({"職等": "區經理", "職稱": "區經理", "所屬區域": "新北市"}, ("主管", "region")),
            ({"職等": "課長", "職稱": "總務課長", "所屬部門": "行政部"}, ("總務", "company")),
            ({"職等": "部長", "職稱": "行政部長", "所屬部門": "行政部"}, ("行政部主任", "company")),
            ({"職等": "課長", "職稱": "人資課長", "所屬部門": "行政部"}, ("人資", "department")),
            ({"職等": "課長", "職稱": "會計課長", "所屬部門": "行政部"}, ("會計", "department")),
            ({"職等": "董事會", "職稱": "董事"}, ("董事會", "group")),
            ({"職等": "外部檢核單位", "職稱": "外部檢核"}, ("外部檢核單位", "custom")),
        ]

        for row, expected in cases:
            with self.subTest(row=row):
                profile = backend.edoc_roster_permission_profile(row)
                self.assertEqual((profile["role"], profile["data_scope"]), expected)

    def test_finance_bridge_creates_edoc_session_and_account_link(self) -> None:
        payload = {
            "source": "logging",
            "user": {
                "id": "logging-ceo-001",
                "name": "執行長測試",
                "email": "ceo.bridge@suiyuecare.com",
                "role": "ceo",
                "permissions": ["request:admin", "system:settings"],
            },
        }

        session, status = backend.authenticate_logging_bridge(self.conn, payload, "127.0.0.1", "unittest")

        self.assertEqual(status, 200)
        self.assertTrue(session["token"])
        self.assertEqual(session["user"]["account_source"], "finance")
        self.assertEqual(session["user"]["role"], "執行長")
        self.assertEqual(session["bridge"]["loggingRoleKey"], "ceo")
        self.assertIn("official_documents.all_records", session["permissions"])
        self.assertIn("settings.system_manage", session["permissions"])
        link = self.conn.execute(
            """
            SELECT *
            FROM module_account_links
            WHERE source_system = 'finance'
              AND source_account_id = 'logging-ceo-001'
              AND target_module = 'edoc'
            """
        ).fetchone()
        self.assertIsNotNone(link)
        self.assertEqual(link["target_role_key"], "執行長")

    def test_signed_hris_quick_login_payload_enters_as_employee(self) -> None:
        user = {
            "id": "hris-staff-001",
            "name": "員工測試",
            "email": "staff.bridge@suiyuecare.com",
            "role": "staff",
        }
        signature = hmac.new(
            backend.HRIS_QUICK_LOGIN_SECRET.encode("utf-8"),
            backend.canonical_hris_quick_login_payload(user).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        session, status = backend.authenticate_logging_bridge(
            self.conn,
            {"v": 1, "user": user, "signature": signature},
            "127.0.0.1",
            "unittest",
        )

        self.assertEqual(status, 200)
        self.assertEqual(session["user"]["role"], "員工")
        self.assertEqual(session["user"]["logging_role_key"], "staff")
        self.assertIn("official_documents.compose", session["permissions"])
        self.assertNotIn("official_documents.receive", session["permissions"])

    def test_signed_portal_handoff_enters_as_general_affairs(self) -> None:
        original_secret = backend.PORTAL_HANDOFF_SECRET
        portal_secret = "unit-test-portal-handoff-secret-32-bytes"
        backend.PORTAL_HANDOFF_SECRET = portal_secret
        payload = {
            "source": "logging-portal",
            "moduleId": "edoc",
            "profileId": "EMP-0006",
            "loggingAccountId": "EMP-0006",
            "displayName": "總務測試",
            "email": "ga.portal@suiyuecare.com",
            "role": "ga-chief",
            "sourceRoleKey": "ga-chief",
            "title": "總務課長",
            "department": "行政部",
            "moduleActions": ["view", "submit", "approve", "assign"],
            "jti": "portal-handoff-unit-test-0001",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
        }
        encoded = backend.base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("utf-8").rstrip("=")
        signature = backend.base64url_hmac_sha256(portal_secret, encoded)

        try:
            session, status = backend.authenticate_logging_bridge(
                self.conn,
                {"portal": "1", "payload": encoded, "signature": signature, "token": f"{encoded}.{signature}"},
                "127.0.0.1",
                "unittest",
            )

            self.assertEqual(status, 200, session)
            self.assertEqual(session["user"]["role"], "總務")
            self.assertEqual(session["user"]["logging_role_key"], "ga_chief")
            self.assertEqual(session["bridge"]["sourceSystem"], "finance")
            self.assertIn("official_documents.receive", session["permissions"])
        finally:
            backend.PORTAL_HANDOFF_SECRET = original_secret


if __name__ == "__main__":
    unittest.main()
