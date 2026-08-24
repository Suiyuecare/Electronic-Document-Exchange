from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import unittest
from unittest import mock

import backend


ROOT = Path(__file__).resolve().parents[1]


class FinanceCompanyScopeContractTest(unittest.TestCase):
    def test_finance_active_mode_does_not_require_manual_company_ids(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "EDOC_LAUNCH_COMPANY_MODE": "finance_active",
                "EDOC_LAUNCH_COMPANY_IDS": "CO-OLD",
                "EDOC_PDF_EDITOR_V2_COMPANY_MODE": "finance_active",
                "EDOC_PDF_EDITOR_V2_COMPANY_IDS": "CO-OLD",
            },
            clear=False,
        ):
            self.assertEqual(backend.launch_company_scope_ids(), [])
            self.assertTrue(backend.launch_company_in_scope("CO-NEW"))
            self.assertTrue(backend.pdf_editor_v2_enabled_for_company("CO-NEW"))
            scope = backend.launch_company_scope_metadata(
                [{"id": "CO-NEW", "name": "Finance 新增公司"}]
            )
            self.assertEqual(scope["sourceOfTruth"], "finance")
            self.assertEqual(scope["includedCompanyIds"], ["CO-NEW"])

    def test_manual_allowlist_remains_fail_closed_emergency_mode(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "EDOC_LAUNCH_COMPANY_MODE": "manual_allowlist",
                "EDOC_LAUNCH_COMPANY_IDS": "CO-001, CO-002",
                "EDOC_PDF_EDITOR_V2_COMPANY_MODE": "manual_allowlist",
                "EDOC_PDF_EDITOR_V2_COMPANY_IDS": "CO-002",
            },
            clear=False,
        ):
            self.assertTrue(backend.launch_company_in_scope("CO-001"))
            self.assertFalse(backend.launch_company_in_scope("CO-999"))
            self.assertTrue(backend.pdf_editor_v2_enabled_for_company("CO-002"))
            self.assertFalse(backend.pdf_editor_v2_enabled_for_company("CO-001"))

    def test_invalid_modes_fail_closed(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "EDOC_LAUNCH_COMPANY_MODE": "anything",
                "EDOC_PDF_EDITOR_V2_COMPANY_MODE": "anything",
            },
            clear=False,
        ):
            self.assertFalse(backend.launch_company_in_scope("CO-001"))
            self.assertFalse(backend.pdf_editor_v2_enabled_for_company("CO-001"))

    def test_finance_active_company_is_authorized_without_a_static_id_list(self) -> None:
        previous = backend.DEPLOYMENT_ENV
        backend.DEPLOYMENT_ENV = "production"
        try:
            with mock.patch.dict(
                os.environ,
                {
                    "EDOC_LAUNCH_COMPANY_MODE": "finance_active",
                    "EDOC_LAUNCH_COMPANY_IDS": "",
                },
                clear=False,
            ):
                company = {
                    "id": "CO-AUTO",
                    "status": "active",
                    "source_system": "finance",
                    "finance_entity_id": "E-AUTO",
                }
                self.assertEqual(backend.assert_seal_company_scope(company)["id"], "CO-AUTO")
        finally:
            backend.DEPLOYMENT_ENV = previous


class FinanceMasterUiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "app.js").read_text(encoding="utf-8")

    def test_edoc_does_not_offer_a_second_editable_personnel_roster(self) -> None:
        self.assertNotIn('id="accountInviteBtn"', self.html)
        self.assertNotIn('id="accountRosterImportBtn"', self.html)
        self.assertNotIn('id="accountName"', self.html)
        self.assertNotIn('id="opsFormalAccountRosterImportBtn"', self.js)
        self.assertNotIn('id="opsCompanyLaunchRosterImportBtn"', self.js)
        self.assertIn("人員資料不在 eDoc 重複編輯", self.html)
        self.assertIn("會計系統（唯一來源）", self.js)

    def test_no_demo_role_accounts_are_created_by_sync_button(self) -> None:
        start = self.js.index("function syncAccountsFromRoles()")
        end = self.js.index("\nfunction recordLogin", start)
        body = self.js[start:end]
        self.assertNotIn("userAccounts.push", body)
        self.assertIn("不會在 eDoc 建立預設或 demo 帳號", body)

    def test_finance_refresh_revalidates_current_session(self) -> None:
        start = self.js.index("async function refreshFinanceAccountProjection()")
        end = self.js.index("\nfunction runAccountAction", start)
        body = self.js[start:end]
        self.assertIn('backendRequest("/auth/me")', body)
        self.assertIn("loadFinanceCompanyDirectory()", body)


class FinanceMasterWriteBoundaryTest(unittest.TestCase):
    def test_production_generic_api_cannot_mutate_finance_master_tables(self) -> None:
        previous = backend.DEPLOYMENT_ENV
        backend.DEPLOYMENT_ENV = "production"
        try:
            for table in ("users", "companies", "module_account_links"):
                with self.subTest(table=table):
                    self.assertTrue(backend.finance_master_generic_write_blocked(table))
            self.assertFalse(backend.finance_master_generic_write_blocked("official_documents"))
        finally:
            backend.DEPLOYMENT_ENV = previous

    def test_production_blocks_legacy_personnel_and_company_csv_writes(self) -> None:
        previous = backend.DEPLOYMENT_ENV
        backend.DEPLOYMENT_ENV = "production"
        conn = sqlite3.connect(":memory:")
        try:
            with self.assertRaisesRegex(PermissionError, "finance_personnel_master_read_only"):
                backend.import_formal_account_roster(conn, {"rows": [{}]})
            with self.assertRaisesRegex(PermissionError, "finance_company_master_read_only"):
                backend.import_company_launch_roster(conn, {"rows": [{}]})
            with self.assertRaisesRegex(PermissionError, "finance_personnel_master_read_only"):
                backend.supabase_import_formal_account_roster({"rows": [{}]})
            with self.assertRaisesRegex(PermissionError, "finance_company_master_read_only"):
                backend.supabase_import_company_launch_roster({"rows": [{}]})
        finally:
            conn.close()
            backend.DEPLOYMENT_ENV = previous


if __name__ == "__main__":
    unittest.main()
