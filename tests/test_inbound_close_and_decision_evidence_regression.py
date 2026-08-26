from __future__ import annotations

import base64
import inspect
import re
import sqlite3
import unittest
from pathlib import Path

import backend


ROOT = Path(__file__).resolve().parents[1]


def javascript_function(source: str, name: str) -> str:
    """Return one named function without depending on generated line numbers."""
    marker = f"function {name}("
    function_start = source.index(marker)
    signature_end = source.index(")", function_start)
    body_start = source.index("{", signature_end)
    depth = 0
    quote = ""
    escaped = False
    line_comment = False
    block_comment = False
    index = body_start
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if char == "*" and following == "/":
                block_comment = False
                index += 2
                continue
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            index += 1
            continue
        if char == "/" and following == "/":
            line_comment = True
            index += 2
            continue
        if char == "/" and following == "*":
            block_comment = True
            index += 2
            continue
        if char in {'"', "'", "`"}:
            quote = char
            index += 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[function_start : index + 1]
        index += 1
    raise AssertionError(f"Unterminated JavaScript function: {name}")


class InboundCloseAndAttachmentRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        backend.register_sqlite_functions(self.conn)
        self.conn.executescript(backend.SCHEMA)
        self._add_company("CO-A", "TENANT-A", "去識別化甲公司")
        self._add_company("CO-B", "TENANT-B", "去識別化乙公司")
        self.ga = self._add_user("GA-A", "CO-A", "TENANT-A", "總務甲")
        self.other_company_ga = self._add_user("GA-B", "CO-B", "TENANT-B", "總務乙")
        self.wrong_tenant_ga = self._add_user("GA-A-WRONG", "CO-A", "TENANT-B", "錯誤租戶總務")

    def tearDown(self) -> None:
        self.conn.close()

    def _add_company(self, company_id: str, tenant_id: str, name: str) -> None:
        timestamp = backend.now()
        self.conn.execute(
            """
            INSERT INTO companies (
              id, name, finance_tenant_id, source_system, status, created_at, updated_at
            ) VALUES (?, ?, ?, 'finance', 'active', ?, ?)
            """,
            (company_id, name, tenant_id, timestamp, timestamp),
        )

    def _add_user(self, user_id: str, company_id: str, tenant_id: str, name: str) -> dict:
        row = {
            "id": user_id,
            "account_source": "finance",
            "finance_employee_id": user_id,
            "finance_tenant_id": tenant_id,
            "company_id": company_id,
            "company_name": f"{company_id}-company",
            "external_account_payload_json": "{}",
            "name": name,
            "email": f"{user_id.lower()}@example.invalid",
            "unit": "總務行政課",
            "title": "總務",
            "role": "總務",
            "provider": "Finance Google SSO",
            "mfa_status": "由 Finance 管理",
            "status": "啟用",
            "created_at": backend.now(),
        }
        backend.insert_row(self.conn, "users", row)
        return row

    @staticmethod
    def _session(user: dict) -> dict:
        return {
            "user": dict(user),
            "permissions": [
                "official_documents.receive",
                "official_documents.all_todo",
                "official_documents.all_records",
            ],
        }

    def _insert_inbound(
        self,
        document_id: str,
        *,
        company_id: str | None = "CO-A",
        tenant_id: str | None = "TENANT-A",
        status: str = "registered",
        version: int = 1,
    ) -> None:
        timestamp = backend.now()
        self.conn.execute(
            """
            INSERT INTO inbound_documents (
              id, company_id, finance_tenant_id, receive_no, source_type,
              sender_name, subject, status, metadata_json, mutation_version,
              created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'local_unit_physical', ?, ?, ?, '{}', ?, ?, ?, ?)
            """,
            (
                document_id,
                company_id,
                tenant_id,
                f"測試收文-{document_id}",
                "去識別化來文單位",
                f"去識別化主旨-{document_id}",
                status,
                version,
                self.ga["id"],
                timestamp,
                timestamp,
            ),
        )

    @staticmethod
    def _attachment_payload() -> dict:
        return {
            "file_name": "去識別化附件.txt",
            "file_mime_type": "text/plain",
            "content_base64": base64.b64encode(b"sanitized attachment").decode("ascii"),
        }

    def test_close_is_idempotent_versioned_and_uses_compare_and_swap(self) -> None:
        self._insert_inbound("INB-CLOSE-1")
        session = self._session(self.ga)
        payload = {
            "idempotency_key": "close-request-0001",
            "expected_version": 1,
            "comment": "去識別化結案說明",
        }

        closed = backend.close_inbound_document(self.conn, "INB-CLOSE-1", payload, session)
        self.assertEqual(closed["mutation"], "close")
        self.assertEqual(closed["version"], 2)
        self.assertEqual(closed["item"]["status"], "closed")
        self.assertFalse(closed["replayed"])

        replay = backend.close_inbound_document(self.conn, "INB-CLOSE-1", payload, session)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["version"], 2)
        self.assertEqual(replay["item"]["id"], closed["item"]["id"])

        self._insert_inbound("INB-CLOSE-STALE")
        with self.assertRaisesRegex(ValueError, "inbound_version_conflict"):
            backend.close_inbound_document(
                self.conn,
                "INB-CLOSE-STALE",
                {
                    "idempotency_key": "close-request-stale-0001",
                    "expected_version": 2,
                },
                session,
            )
        row = self.conn.execute(
            "SELECT status, mutation_version FROM inbound_documents WHERE id = ?",
            ("INB-CLOSE-STALE",),
        ).fetchone()
        self.assertEqual((row["status"], row["mutation_version"]), ("registered", 1))

    def test_close_rejects_company_and_tenant_scope_mismatch_without_mutation(self) -> None:
        self._insert_inbound("INB-CLOSE-SCOPE")
        attempts = (
            (self.other_company_ga, "close-other-company-0001"),
            (self.wrong_tenant_ga, "close-wrong-tenant-0001"),
        )
        for user, key in attempts:
            with self.subTest(user=user["id"]):
                with self.assertRaisesRegex(PermissionError, "scope|tenant|company|forbidden"):
                    backend.close_inbound_document(
                        self.conn,
                        "INB-CLOSE-SCOPE",
                        {"idempotency_key": key, "expected_version": 1},
                        self._session(user),
                    )
        row = self.conn.execute(
            "SELECT status, mutation_version FROM inbound_documents WHERE id = ?",
            ("INB-CLOSE-SCOPE",),
        ).fetchone()
        self.assertEqual((row["status"], row["mutation_version"]), ("registered", 1))

    def test_supabase_close_uses_the_same_atomic_rpc_contract(self) -> None:
        adapter = inspect.getsource(backend.supabase_close_inbound_document)
        self.assertIn("supabase_atomic_inbound_mutation", adapter)
        self.assertIn('"close"', adapter)

        migration = (
            ROOT / "supabase/migrations/20260826033323_inbound_mutation_contract.sql"
        ).read_text(encoding="utf-8")
        self.assertRegex(migration, r"v_mutation\s+not\s+in\s*\([^)]*'close'")
        self.assertRegex(
            migration,
            re.compile(
                r"set\s+status\s*=\s*'closed'.*?"
                r"mutation_version\s*=\s*mutation_version\s*\+\s*1.*?"
                r"where\s+id\s*=\s*v_document_id.*?"
                r"mutation_version\s*=\s*v_current_version",
                re.IGNORECASE | re.DOTALL,
            ),
        )
        self.assertIn("inbound_document_scope_forbidden", migration)
        self.assertIn("inbound_version_conflict", migration)

    def test_attachment_upload_fails_closed_for_missing_or_mismatched_scope(self) -> None:
        cases = (
            ("INB-NO-COMPANY", None, "TENANT-A"),
            ("INB-NO-TENANT", "CO-A", None),
            ("INB-OTHER-COMPANY", "CO-B", "TENANT-B"),
            ("INB-OTHER-TENANT", "CO-A", "TENANT-B"),
        )
        for document_id, company_id, tenant_id in cases:
            self._insert_inbound(document_id, company_id=company_id, tenant_id=tenant_id)
            with self.subTest(document_id=document_id):
                with self.assertRaisesRegex(PermissionError, "scope|tenant|company|forbidden"):
                    backend.upload_inbound_attachment(
                        self.conn,
                        document_id,
                        self._attachment_payload(),
                        self._session(self.ga),
                    )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM inbound_document_attachments").fetchone()[0],
            0,
        )

    def test_attachment_upload_cannot_change_closed_or_archived_record(self) -> None:
        for status in ("closed", "archived"):
            document_id = f"INB-{status.upper()}"
            self._insert_inbound(document_id, status=status)
            with self.subTest(status=status):
                with self.assertRaisesRegex((ValueError, PermissionError), "state|closed|archived|immutable|locked"):
                    backend.upload_inbound_attachment(
                        self.conn,
                        document_id,
                        self._attachment_payload(),
                        self._session(self.ga),
                    )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM inbound_document_attachments").fetchone()[0],
            0,
        )

    def test_legacy_post_route_cannot_bypass_canonical_mutation_api(self) -> None:
        route_source = inspect.getsource(backend.Handler.handle_api)
        self.assertIn("inbound_canonical_mutation_required", route_source)
        self.assertRegex(
            route_source,
            re.compile(
                r"parts\s*==\s*\[?[\"']inbound-documents[\"']\]?|"
                r"len\(parts\)\s*==\s*1",
            ),
        )
        self.assertNotIn("supabase_create_inbound_document(payload, session)", route_source)
        self.assertNotIn("create_inbound_document(conn, payload, session)", route_source)


class OfficialDecisionEvidenceRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = (ROOT / "app.js").read_text(encoding="utf-8")

    def test_original_evidence_never_falls_back_to_prepared_pdf(self) -> None:
        function = javascript_function(self.js, "officialDecisionEvidenceFiles")
        source_selection, remainder = function.split("const attachments", 1)
        self.assertNotIn('"prepared_pdf"', source_selection)
        for file_type in ("original_pdf", "source_pdf", "generated_pdf"):
            self.assertIn(f'"{file_type}"', source_selection)
        self.assertIn('file.file_type === "prepared_pdf"', remainder)

    def test_reject_and_approve_share_the_complete_evidence_gate(self) -> None:
        availability = javascript_function(self.js, "updateOfficialDecisionSubmitAvailability")
        reject_branch = availability.index('if (action === "reject")')
        shared_prefix = availability[:reject_branch]
        self.assertRegex(
            shared_prefix,
            re.compile(r"evidenceReady\s*=\s*officialDecisionEvidenceComplete\(\)"),
        )
        self.assertRegex(
            availability,
            re.compile(
                r"if\s*\(\s*action\s*===\s*[\"']reject[\"']\s*\)\s*\{"
                r".*?submit\.disabled\s*=\s*!\([^)]*evidenceReady",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            availability[reject_branch:],
            re.compile(r"fullDetailReady\s*&&\s*evidenceReady"),
        )

        submission = javascript_function(self.js, "submitOfficialDecision")
        approve_branch = submission.index('if (action === "approve")')
        common_guard = submission[:approve_branch]
        self.assertRegex(
            common_guard,
            re.compile(
                r"(every\(officialDecisionEvidenceReady\)|"
                r"Object\.values\([^)]*acknowledgement[^)]*\)\.every\(Boolean\)|"
                r"officialDecisionEvidenceComplete)",
                re.IGNORECASE,
            ),
        )
        self.assertRegex(common_guard, re.compile(r"return\s*;"))


if __name__ == "__main__":
    unittest.main()
