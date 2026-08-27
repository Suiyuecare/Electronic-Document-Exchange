from __future__ import annotations

import copy
import hashlib
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import backend


ROOT = Path(__file__).resolve().parents[1]
TENANT_ID = "00000000-0000-0000-0000-000000000001"
OTHER_TENANT_ID = "00000000-0000-0000-0000-000000000999"
ORGANIZATION_ETAG = hashlib.sha256(b"finance-directory-v14").hexdigest()


def javascript_function(source: str, name: str) -> str:
    matches = list(
        re.finditer(
            rf"(?:async\s+)?function\s+{re.escape(name)}\([^)]*\)\s*\{{",
            source,
        )
    )
    if not matches:
        raise AssertionError(f"JavaScript function not found: {name}")
    match = matches[-1]
    depth = 0
    quote = ""
    escaped = False
    for position in range(match.end() - 1, len(source)):
        char = source[position]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {'"', "'", "`"}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[match.start():position + 1]
    raise AssertionError(f"JavaScript function is not balanced: {name}")


def element_opening_tag(source: str, element_id: str) -> str:
    match = re.search(
        rf'<(?P<tag>[a-zA-Z][\w-]*)\b(?=[^>]*\bid="{re.escape(element_id)}")[^>]*>',
        source,
    )
    if match is None:
        raise AssertionError(f"HTML element not found: #{element_id}")
    return match.group(0)


class FinanceDirectoryBackendContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.companies = [
            {
                "id": "FINCO-E100",
                "finance_tenant_id": TENANT_ID,
                "finance_entity_id": "E100",
                "source_system": "finance",
                "name": "去識別化甲公司",
                "tax_id": "00000001",
                "address": "去識別化甲地址",
                "status": "active",
            },
            {
                "id": "FINCO-E200",
                "finance_tenant_id": TENANT_ID,
                "finance_entity_id": "E200",
                "source_system": "finance",
                "name": "去識別化乙公司",
                "tax_id": "00000002",
                "address": "去識別化乙地址",
                "status": "active",
            },
            {
                "id": "FINCO-E300",
                "finance_tenant_id": TENANT_ID,
                "finance_entity_id": "E300",
                "source_system": "finance",
                "name": "已停用公司",
                "tax_id": "00000003",
                "address": "去識別化丙地址",
                "status": "inactive",
            },
            {
                "id": "FINCO-X999",
                "finance_tenant_id": OTHER_TENANT_ID,
                "finance_entity_id": "X999",
                "source_system": "finance",
                "name": "其他租戶公司",
                "tax_id": "00000999",
                "address": "其他租戶地址",
                "status": "active",
            },
        ]
        self.state = {
            "finance_tenant_id": TENANT_ID,
            "version_no": 14,
            "etag": ORGANIZATION_ETAG,
            "last_synced_from_finance_at": "2026-08-25T15:01:00+08:00",
        }
        self.units = [
            {
                "id": "FINORG-UNIT-A",
                "finance_tenant_id": TENANT_ID,
                "finance_unit_id": "00000000-0000-0000-0000-000000000100",
                "code": "D100",
                "name": "去識別化甲部門",
                "unit_type": "department",
                "parent_finance_unit_id": None,
                "sort_order": 10,
                "is_posting_unit": True,
                "entity_scope_mode": "explicit",
                "entity_codes": ["E100"],
                "status": "active",
            },
            {
                "id": "FINORG-UNIT-B",
                "finance_tenant_id": TENANT_ID,
                "finance_unit_id": "00000000-0000-0000-0000-000000000200",
                "code": "D200",
                "name": "去識別化乙部門",
                "unit_type": "department",
                "parent_finance_unit_id": None,
                "sort_order": 20,
                "is_posting_unit": True,
                "entity_scope_mode": "explicit",
                "entity_codes": ["E200"],
                "status": "active",
            },
            {
                "id": "FINORG-UNIT-C",
                "finance_tenant_id": TENANT_ID,
                "finance_unit_id": "00000000-0000-0000-0000-000000000300",
                "code": "D300",
                "name": "停用公司部門",
                "unit_type": "department",
                "parent_finance_unit_id": None,
                "sort_order": 30,
                "is_posting_unit": True,
                "entity_scope_mode": "explicit",
                "entity_codes": ["E300"],
                "status": "active",
            },
            {
                "id": "FINORG-UNIT-INACTIVE",
                "finance_tenant_id": TENANT_ID,
                "finance_unit_id": "00000000-0000-0000-0000-000000000400",
                "code": "D400",
                "name": "已停用部門",
                "unit_type": "department",
                "parent_finance_unit_id": None,
                "sort_order": 40,
                "is_posting_unit": True,
                "entity_scope_mode": "explicit",
                "entity_codes": ["E100"],
                "status": "inactive",
            },
            {
                "id": "FINORG-UNIT-X",
                "finance_tenant_id": OTHER_TENANT_ID,
                "finance_unit_id": "00000000-0000-0000-0000-000000000999",
                "code": "X999",
                "name": "其他租戶部門",
                "unit_type": "department",
                "parent_finance_unit_id": None,
                "sort_order": 999,
                "is_posting_unit": True,
                "entity_scope_mode": "all",
                "entity_codes": [],
                "status": "active",
            },
        ]

    def filter_rows(self, table: str, filters: dict | None = None, **_kwargs) -> list[dict]:
        rows = {
            "companies": self.companies,
            "finance_organization_projection_state": [self.state],
            "finance_organization_units": self.units,
        }.get(table, [])
        expected = filters or {}
        return copy.deepcopy([
            row
            for row in rows
            if all(row.get(key) == value for key, value in expected.items())
        ])

    def get_row(self, table: str, row_id: str) -> dict | None:
        if table != "companies":
            return None
        return copy.deepcopy(next((row for row in self.companies if row["id"] == row_id), None))

    def call_directory(self, user: dict) -> dict:
        directory = getattr(backend, "supabase_finance_directory", None)
        self.assertTrue(
            callable(directory),
            "backend.supabase_finance_directory(session) 尚未實作",
        )
        with (
            patch.object(backend, "supabase_filter_rows", side_effect=self.filter_rows),
            patch.object(backend, "supabase_get", side_effect=self.get_row),
            patch.object(
                backend,
                "pdf_editor_v2_enabled_for_company",
                side_effect=lambda company_id: bool(company_id),
            ),
        ):
            return directory({"user": user, "permissions": []})

    def assert_common_contract(self, result: dict, *, current_company_id: str) -> None:
        self.assertEqual(
            set(result),
            {
                "source",
                "schemaVersion",
                "directoryVersion",
                "syncedAt",
                "currentCompanyId",
                "companies",
                "departments",
                "organization",
            },
        )
        self.assertEqual(result["source"], "finance")
        self.assertEqual(result["schemaVersion"], 2)
        self.assertIsInstance(result["directoryVersion"], str)
        self.assertTrue(result["directoryVersion"])
        self.assertEqual(result["syncedAt"], self.state["last_synced_from_finance_at"])
        self.assertEqual(result["currentCompanyId"], current_company_id)
        for company in result["companies"]:
            self.assertTrue(company["pdf_editor_v2"])
            self.assertEqual(company["feature_flags"], {"pdf_editor_v2": True})
            self.assertEqual(company["featureFlags"], {"pdf_editor_v2": True})
        self.assertEqual(
            result["organization"],
            {
                "tenantId": TENANT_ID,
                "versionNo": 14,
                "etag": ORGANIZATION_ETAG,
            },
        )
        self.assertNotIn("units", result)

    def test_ordinary_user_receives_only_own_company_and_its_departments(self) -> None:
        result = self.call_directory(
            {
                "id": "FIN-U100",
                "company_id": "FINCO-E100",
                "finance_tenant_id": TENANT_ID,
                "account_source": "finance",
                "role": "員工",
                "logging_role_key": "staff",
            }
        )

        self.assert_common_contract(result, current_company_id="FINCO-E100")
        self.assertEqual([row["id"] for row in result["companies"]], ["FINCO-E100"])
        self.assertEqual([row["name"] for row in result["departments"]], ["去識別化甲部門"])

    def test_privileged_operational_roles_receive_all_active_companies(self) -> None:
        roles = (
            ("執行長", "ceo"),
            ("行政部主任", "admin_director"),
            ("總務", "ga_chief"),
        )
        for role, logging_role_key in roles:
            with self.subTest(role=role):
                result = self.call_directory(
                    {
                        "id": f"FIN-{logging_role_key}",
                        "company_id": "FINCO-E100",
                        "finance_tenant_id": TENANT_ID,
                        "account_source": "finance",
                        "role": role,
                        "logging_role_key": logging_role_key,
                    }
                )

                self.assert_common_contract(result, current_company_id="FINCO-E100")
                self.assertEqual(
                    {row["id"] for row in result["companies"]},
                    {"FINCO-E100", "FINCO-E200"},
                )
                self.assertEqual(
                    {row["name"] for row in result["departments"]},
                    {"去識別化甲部門", "去識別化乙部門"},
                )

    def test_renamed_department_uses_current_finance_name_for_workflow_snapshot(self) -> None:
        user = {
            "id": "FIN-U100",
            "finance_tenant_id": TENANT_ID,
            "unit": "去識別化舊部門名稱",
            "external_account_payload_json": {
                "financeProfile": {
                    "departmentCode": "D100",
                    "departmentName": "去識別化舊部門名稱",
                }
            },
        }
        canonical_row = {
            **self.units[0],
            "name": "去識別化新部門名稱",
        }
        payloads = (
            {
                "applicant_department_id": "D100",
                "applicant_department_name": "去識別化舊部門名稱",
            },
            {
                "applicant_department_id": "D100",
                "applicant_department_name": "去識別化新部門名稱",
            },
        )
        for payload in payloads:
            with (
                self.subTest(payload=payload),
                patch.object(backend, "is_production", return_value=True),
                patch.object(backend, "USE_SUPABASE", True),
                patch.object(backend, "supabase_filter_rows", return_value=[canonical_row]) as lookup,
            ):
                resolved = backend.authoritative_applicant_department(user, payload)

            self.assertEqual(
                resolved,
                {"id": "D100", "name": "去識別化新部門名稱"},
            )
            lookup.assert_called_once_with(
                "finance_organization_units",
                {
                    "finance_tenant_id": TENANT_ID,
                    "code": "D100",
                    "status": "active",
                },
                order="id.asc",
                limit=2,
            )

    def test_department_projection_missing_duplicate_or_cross_tenant_fails_closed(self) -> None:
        user = {
            "id": "FIN-U100",
            "finance_tenant_id": TENANT_ID,
            "unit": "去識別化舊部門名稱",
            "external_account_payload_json": {
                "financeProfile": {
                    "departmentCode": "D100",
                    "departmentName": "去識別化舊部門名稱",
                }
            },
        }
        valid = {**self.units[0], "name": "去識別化新部門名稱"}
        unsafe_results = (
            [],
            [valid, {**valid, "id": "FINORG-DUPLICATE"}],
            [{**valid, "finance_tenant_id": OTHER_TENANT_ID}],
        )
        for rows in unsafe_results:
            with (
                self.subTest(rows=rows),
                patch.object(backend, "is_production", return_value=True),
                patch.object(backend, "USE_SUPABASE", True),
                patch.object(backend, "supabase_filter_rows", return_value=rows),
            ):
                with self.assertRaisesRegex(
                    PermissionError,
                    "finance_unit_projection_unavailable",
                ):
                    backend.authoritative_applicant_department(
                        user,
                        {
                            "applicant_department_id": "D100",
                            "applicant_department_name": "去識別化舊部門名稱",
                        },
                    )


class FinanceOwnedGenericWriteBoundaryTest(unittest.TestCase):
    def test_company_and_department_generic_reads_are_blocked(self) -> None:
        session = {
            "user": {"id": "FIN-USER", "role": "員工", "company_id": "FINCO-E100"},
            "permissions": ["official_documents.compose"],
        }
        for table in ("companies", "company_registry", "department_registry"):
            with self.subTest(table=table):
                self.assertFalse(
                    backend.can_access_generic_table_api(session, table),
                    "公司與部門只能透過 tenant/company scoped /finance-directory 讀取。",
                )

    def test_company_and_department_generic_writes_are_blocked_in_production(self) -> None:
        previous = backend.DEPLOYMENT_ENV
        backend.DEPLOYMENT_ENV = "production"
        session = {
            "user": {"id": "FIN-CEO", "role": "執行長", "company_id": "FINCO-E100"},
            "permissions": ["system_permissions.manage", "seals.manage"],
        }
        try:
            for table in ("companies", "company_registry", "department_registry"):
                with self.subTest(table=table):
                    self.assertTrue(backend.finance_master_generic_write_blocked(table))
                    self.assertFalse(
                        backend.can_access_generic_table_api(session, table, write=True),
                        "即使是執行長，也必須回 Finance 修改公司與部門主檔。",
                    )
            self.assertFalse(backend.finance_master_generic_write_blocked("official_documents"))
        finally:
            backend.DEPLOYMENT_ENV = previous


class FinanceDirectoryFrontendContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "app.js").read_text(encoding="utf-8")

    def test_edoc_has_no_company_or_department_master_write_ui(self) -> None:
        for element_id in (
            "addCompanyBtn",
            "companyRegistryForm",
            "companyNameInput",
            "companyTaxIdInput",
            "addDepartmentBtn",
            "departmentRegistryForm",
            "departmentCompanyInput",
            "departmentNameInput",
            "departmentManagerInput",
        ):
            with self.subTest(element_id=element_id):
                self.assertFalse(
                    f'id="{element_id}"' in self.html,
                    f"eDoc 不可保留 Finance 主檔寫入控制項 #{element_id}。",
                )

        for implementation in (
            "function addCompanyRegistryItem()",
            "function addDepartmentRegistryItem()",
            'persistToBackend("/company_registry"',
            'persistToBackend("/department_registry"',
        ):
            with self.subTest(implementation=implementation):
                self.assertFalse(
                    implementation in self.js,
                    f"eDoc 不可保留 Finance 主檔寫入程式：{implementation}",
                )

    def test_all_internal_company_and_department_fields_use_finance_choices(self) -> None:
        for field_id in (
            "contractCompanyInput",
            "officialCompanySelect",
            "composeCompanySelect",
            "uploadedSealCompany",
            "simpleSealCompanySelect",
            "companySealCompanySelect",
            "sealUsageCompanySelect",
            "contractDepartmentInput",
            "inboundArchiveDepartment",
            "officialDispatchUnitInput",
            "uploadedSealDepartment",
            "sealDepartmentInput",
            "reportUnit",
        ):
            with self.subTest(field_id=field_id):
                opening = element_opening_tag(self.html, field_id)
                self.assertTrue(
                    opening.lstrip().lower().startswith("<select"),
                    f"#{field_id} 必須由 Finance 目錄選擇，不可自由輸入。",
                )

    def test_finance_directory_loads_companies_and_departments_from_scoped_endpoint(self) -> None:
        loader = javascript_function(self.js, "loadFinanceCompanyDirectory")
        refresher = javascript_function(self.js, "refreshFinanceDirectory")
        self.assertIn("refreshFinanceDirectory", loader)
        self.assertIn('backendRequest("/finance-directory")', refresher)
        self.assertRegex(refresher, r"\bpayload\.companies\b")
        self.assertRegex(refresher, r"\bpayload\.departments\b")
        self.assertNotIn('backendRequest("/companies")', loader + refresher)

    def test_authenticated_directory_refreshes_every_thirty_seconds(self) -> None:
        interval_constant = re.search(
            r"(?:const|let)\s+FINANCE_DIRECTORY_REFRESH_INTERVAL_MS\s*=\s*30_000\s*;",
            self.js,
        )
        self.assertIsNotNone(
            interval_constant,
            "前端必須以 FINANCE_DIRECTORY_REFRESH_INTERVAL_MS = 30_000 鎖定刷新週期。",
        )
        starter = javascript_function(self.js, "startFinanceDirectoryRefresh")
        self.assertIn("loadFinanceCompanyDirectory()", starter)
        self.assertRegex(
            starter,
            r"(?:window\.)?setInterval\([\s\S]*?FINANCE_DIRECTORY_REFRESH_INTERVAL_MS\s*\)",
        )
        self.assertIn("clearInterval", starter)
        enter_app = javascript_function(self.js, "enterApp")
        self.assertIn("startFinanceDirectoryRefresh()", enter_app)

    def test_account_department_prefers_stable_finance_code_after_rename(self) -> None:
        resolver = javascript_function(self.js, "preferredFinanceDepartment")
        self.assertIn("external_account_payload_json", resolver)
        self.assertIn("financeProfile.departmentCode", resolver)
        self.assertIn("department.code", resolver)
        self.assertIn("department.financeUnitId", resolver)
        self.assertIn("codeMatches.length === 1", resolver)
        self.assertLess(
            resolver.index("if (departmentCode)"),
            resolver.index("department.name === unitName"),
            "穩定 Finance 部門代碼必須優先於可能過期的名稱。",
        )


if __name__ == "__main__":
    unittest.main()
