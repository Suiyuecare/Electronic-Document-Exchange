from __future__ import annotations

import sqlite3
import unittest

import backend


class InboundMutationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        backend.register_sqlite_functions(self.conn)
        self.conn.executescript(backend.SCHEMA)
        self.conn.execute(
            "INSERT INTO companies (id, name, finance_tenant_id, source_system, status, created_at, updated_at) VALUES (?, ?, ?, 'finance', 'active', ?, ?)",
            ("CO-001", "去識別化測試公司", "TENANT-001", backend.now(), backend.now()),
        )
        self.employee = self.add_user(
            "FIN-EMP",
            "employee@example.invalid",
            "新進員工",
            "居家照顧部",
            "員工",
            "staff",
            "EMP-1",
        )
        self.ga = self.add_user(
            "FIN-GA",
            "ga@example.invalid",
            "總務測試員",
            "總務行政課",
            "總務",
            "ga_chief",
            "GA-1",
        )

    def tearDown(self) -> None:
        self.conn.close()

    def add_user(
        self,
        user_id: str,
        email: str,
        name: str,
        unit: str,
        role: str,
        logging_role_key: str,
        finance_employee_id: str,
    ) -> dict:
        row = {
            "id": user_id,
            "auth_user_id": None,
            "account_source": "finance",
            "logging_account_id": finance_employee_id,
            "logging_role_key": logging_role_key,
            "finance_employee_id": finance_employee_id,
            "finance_tenant_id": "TENANT-001",
            "company_id": "CO-001",
            "company_name": "去識別化測試公司",
            "company_address": "測試地址",
            "manager_employee_id": "",
            "manager_name": "",
            "manager_email": "",
            "manager_role_key": "",
            "approval_manager_employee_id": "",
            "approval_manager_name": "",
            "approval_manager_email": "",
            "approval_manager_role_key": "",
            "external_account_payload_json": "{}",
            "last_synced_from_logging_at": backend.now(),
            "name": name,
            "email": email,
            "password_hash": None,
            "unit": unit,
            "title": role,
            "job_level": "職員",
            "role": role,
            "provider": "Finance Google SSO",
            "mfa_status": "由 Finance 管理",
            "status": "啟用",
            "last_login_at": None,
            "created_at": backend.now(),
        }
        backend.insert_row(self.conn, "users", row)
        return row

    def session(self, user: dict, *permissions: str) -> dict:
        return {"user": dict(user), "permissions": list(permissions)}

    def draft_payload(self, key: str = "draft-request-0001") -> dict:
        return {
            "idempotency_key": key,
            "source_type": "local_unit_physical",
            "receive_no": "測試收文第0001號",
            "sender_name": "去識別化來文單位",
            "subject": "去識別化收文測試",
        }

    def test_local_physical_inbound_is_bound_to_session_finance_unit(self) -> None:
        payload = self.draft_payload()
        payload["recipient_department_name"] = "總務行政課"
        with self.assertRaisesRegex(PermissionError, "finance_unit_payload_mismatch"):
            backend.mutate_inbound_draft(
                self.conn,
                payload,
                self.session(self.employee),
            )

        missing_unit = {**self.employee, "unit": ""}
        payload.pop("recipient_department_name")
        with self.assertRaisesRegex(PermissionError, "finance_unit_required"):
            backend.mutate_inbound_draft(
                self.conn,
                payload,
                self.session(missing_unit),
            )

    def test_draft_idempotency_and_version_conflict_are_fail_closed(self) -> None:
        session = self.session(self.employee)
        created = backend.mutate_inbound_draft(self.conn, self.draft_payload(), session)
        self.assertEqual(created["version"], 1)
        self.assertEqual(created["item"]["recipient_department_name"], "居家照顧部")
        self.assertFalse(created["replayed"])

        replay = backend.mutate_inbound_draft(self.conn, self.draft_payload(), session)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["item"]["id"], created["item"]["id"])

        changed = {**self.draft_payload(), "subject": "同 key 不同內容"}
        with self.assertRaisesRegex(ValueError, "inbound_idempotency_conflict"):
            backend.mutate_inbound_draft(self.conn, changed, session)

        stale = {
            **self.draft_payload("register-request-0001"),
            "document_id": created["item"]["id"],
            "expected_version": 2,
        }
        with self.assertRaisesRegex(ValueError, "inbound_version_conflict"):
            backend.mutate_inbound_registration(self.conn, stale, session)

        registered = backend.mutate_inbound_registration(
            self.conn,
            {**stale, "expected_version": 1},
            session,
        )
        self.assertEqual(registered["version"], 2)
        self.assertEqual(registered["item"]["status"], "registered")

    def test_assignment_and_exception_use_canonical_versioned_response(self) -> None:
        employee_session = self.session(self.employee)
        created = backend.mutate_inbound_registration(
            self.conn,
            {**self.draft_payload("register-request-0002"), "receive_no": "測試收文第0002號"},
            employee_session,
        )
        ga_session = self.session(
            self.ga,
            "official_documents.receive",
            "official_documents.all_todo",
        )
        assigned = backend.mutate_inbound_assignment(
            self.conn,
            created["item"]["id"],
            {
                "idempotency_key": "assign-request-0001",
                "expected_version": created["version"],
                "assignee_user_id": self.employee["id"],
                "due_at": "2026-08-31 18:00:00",
            },
            ga_session,
        )
        self.assertEqual(assigned["mutation"], "assign")
        self.assertEqual(assigned["version"], 2)
        self.assertEqual(assigned["item"]["assignee_user_id"], self.employee["id"])

        exception = backend.mutate_inbound_exception(
            self.conn,
            created["item"]["id"],
            {
                "idempotency_key": "exception-request-0001",
                "expected_version": assigned["version"],
                "exception_type": "附件不完整",
                "note": "去識別化測試說明",
            },
            ga_session,
        )
        self.assertEqual(exception["version"], 3)
        self.assertEqual(exception["item"]["status"], "exception")
        self.assertEqual(exception["item"]["metadata"]["exception"]["type"], "附件不完整")

    def test_editor_draft_department_cannot_be_forged(self) -> None:
        session = self.session(self.employee, "official_documents.compose")
        payload = {
            "company_id": "CO-001",
            "document_category": "合作意向書",
            "approval_route_code": "A",
            "subject": "去識別化電子用印草稿",
            "applicant_department_name": "總務行政課",
        }
        with self.assertRaisesRegex(PermissionError, "finance_unit_payload_mismatch"):
            backend.create_official_editor_draft(self.conn, payload, session)

        payload.pop("applicant_department_name")
        created = backend.create_official_editor_draft(self.conn, payload, session)
        row = self.conn.execute(
            "SELECT applicant_department_id, applicant_department_name FROM official_documents WHERE id = ?",
            (created["id"],),
        ).fetchone()
        self.assertEqual(row["applicant_department_name"], "居家照顧部")
        self.assertEqual(row["applicant_department_id"], "居家照顧部")

    def test_workflow_readiness_allows_draft_but_blocks_missing_finance_relationships(self) -> None:
        self.add_user(
            "FIN-ADMIN",
            "admin@example.invalid",
            "行政主任",
            "總務行政課",
            "行政部主任",
            "admin_director",
            "ADMIN-1",
        )
        session = self.session(self.employee, "official_documents.compose")
        readiness = backend.official_applicant_workflow_readiness(
            self.conn,
            session,
            "A",
        )
        self.assertTrue(readiness["createDraftAllowed"])
        self.assertFalse(readiness["submitAllowed"])
        self.assertIn("applicant_manager", readiness["missingStepKeys"])
        self.assertIn("department_head", readiness["missingStepKeys"])
        self.assertEqual(readiness["sourceOfTruth"], "finance")


if __name__ == "__main__":
    unittest.main()
