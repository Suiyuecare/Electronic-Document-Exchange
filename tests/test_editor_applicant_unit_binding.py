"""Production-mode applicant identity regression; no hosted services or real users.

Senior Finance accounts can be assigned to a division, which must not be
replaced by the first department shown in a general organizational directory.
"""
from __future__ import annotations

import copy
import json
import unittest
from contextlib import ExitStack
from unittest import mock

import backend


class EditorApplicantUnitBindingTests(unittest.TestCase):
    def setUp(self):
        self.tenant = "00000000-0000-0000-0000-000000000001"
        self.other_tenant = "00000000-0000-0000-0000-000000000002"
        self.company = {
            "id": "CO-001", "finance_tenant_id": self.tenant,
            "finance_entity_id": "E1", "name": "隔離測試公司",
            "source_system": "finance", "status": "active",
        }
        self.other_company = {
            **self.company, "id": "CO-OTHER", "finance_entity_id": "E2",
            "name": "隔離測試第二公司",
        }
        self.division = {
            "id": "FINORG-DIVISION", "finance_unit_id": "unit-division",
            "finance_tenant_id": self.tenant, "code": "A1000",
            "name": "隔離測試公司", "unit_type": "division", "status": "active",
            "parent_finance_unit_id": None, "sort_order": 1,
            "entity_scope_mode": "explicit", "entity_codes": ["E1"],
        }
        self.department = {
            **self.division, "id": "FINORG-DEPARTMENT", "finance_unit_id": "unit-department",
            "code": "D1000", "name": "隔離測試行政部", "unit_type": "department",
            "parent_finance_unit_id": "unit-division", "sort_order": 2,
        }
        self.units = [self.division, self.department]
        self.user = {
            "id": "FIN-ISOLATED-CEO", "name": "隔離測試申請人",
            "email": "isolated@example.invalid", "role": "執行長",
            "account_source": "finance", "logging_role_key": "ceo",
            "finance_tenant_id": self.tenant, "company_id": self.company["id"],
            "unit": self.division["name"],
            "external_account_payload_json": json.dumps({"financeProfile": {
                "departmentCode": "A1000", "departmentName": self.division["name"],
            }}),
        }
        self.session = {"user": self.user, "permissions": ["official_documents.compose"]}
        self.inserted = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in (("is_production", True), ("pdf_editor_v2_enabled_for_company", True), ("launch_company_in_scope", True)):
            self.stack.enter_context(mock.patch.object(backend, name, return_value=value))
        self.stack.enter_context(mock.patch.object(backend, "USE_SUPABASE", True))
        self.stack.enter_context(mock.patch.object(backend, "supabase_filter_rows", side_effect=self.filter_rows))
        self.stack.enter_context(mock.patch.object(backend, "supabase_get", side_effect=self.get_row))
        # The target is Finance identity validation, not runtime provisioning.
        self.stack.enter_context(mock.patch.object(backend, "require_production_editor_runtime_ready"))
        self.stack.enter_context(mock.patch.object(backend, "_supabase_editor_latest_revision", return_value=None))
        self.stack.enter_context(mock.patch.object(backend, "supabase_insert", side_effect=self.insert_row))
        self.stack.enter_context(mock.patch.object(backend, "supabase_insert_official_log"))

    def filter_rows(self, table, filters, **_kwargs):
        rows = {
            "companies": [self.company, self.other_company],
            "finance_organization_units": self.units,
            "finance_organization_projection_state": [{
                "finance_tenant_id": self.tenant, "version_no": 1, "etag": "isolated",
            }],
        }.get(table, [])
        return copy.deepcopy([row for row in rows if all(row.get(key) == value for key, value in filters.items())])

    def get_row(self, table, row_id):
        if table == "companies":
            return copy.deepcopy(next((row for row in [self.company, self.other_company] if row["id"] == row_id), None))
        return None

    def insert_row(self, table, payload):
        self.inserted.append((table, copy.deepcopy(payload)))
        return copy.deepcopy(payload)

    def directory(self):
        return backend.supabase_finance_directory(self.session)

    def payload(self, *, department=None):
        department = department or self.directory()["currentApplicantDepartment"]
        return {
            "company_id": self.company["id"], "document_category": "合作意向書",
            "title": "隔離 PDF 編輯草稿", "request_reason": "去識別化測試",
            "applicant_department_id": department["code"],
            "applicant_department_name": department["name"],
        }

    def test_ceo_division_is_returned_without_expanding_department_directory(self):
        result = self.directory()
        self.assertEqual([item["code"] for item in result["departments"]], ["D1000"])
        self.assertEqual(result["currentApplicantDepartment"], {
            "id": "A1000", "code": "A1000", "name": "隔離測試公司",
            "financeUnitId": "unit-division", "companyId": "CO-001",
            "unitType": "division", "entityCodes": ["E1"],
        })

    def test_current_division_draft_succeeds_without_a_seal_or_approval_manager(self):
        result = backend.supabase_create_official_editor_draft(self.payload(), self.session)
        self.assertTrue(result["document_id"])
        stored = next(row for table, row in self.inserted if table == "official_documents")
        self.assertEqual(stored["applicant_department_id"], "A1000")
        self.assertEqual(stored["applicant_department_name"], self.division["name"])
        self.assertEqual(stored["company_id"], self.company["id"])
        self.assertEqual(stored["applicant_id"], self.user["id"])
        self.assertEqual(stored["current_status"], "draft")
        self.assertEqual(len(result["editor_state"]["elements"]), 0)

    def test_explicit_same_company_department_selection_is_allowed(self):
        payload = self.payload(department=self.department)
        backend.supabase_create_official_editor_draft(payload, self.session)
        stored = next(row for table, row in self.inserted if table == "official_documents")
        self.assertEqual(stored["applicant_department_id"], "D1000")
        self.assertEqual(self.user["unit"], self.division["name"])

    def test_employee_and_supervisor_current_department_is_bound_identically(self):
        for role, key in (("員工", "staff"), ("主管", "section_chief"), ("行政部主任", "admin_director")):
            with self.subTest(role=role):
                self.user.update({"role": role, "logging_role_key": key, "unit": self.department["name"]})
                self.user["external_account_payload_json"] = {"financeProfile": {
                    "departmentCode": "D1000", "departmentName": self.department["name"],
                }}
                self.assertEqual(self.directory()["currentApplicantDepartment"]["code"], "D1000")
                backend.supabase_create_official_editor_draft(self.payload(), self.session)

    def test_department_rename_is_canonical_and_unrelated_stale_name_is_rejected(self):
        previous_name = self.division["name"]
        self.division["name"] = "隔離測試公司新名稱"
        self.assertEqual(self.directory()["currentApplicantDepartment"]["name"], self.division["name"])
        for accepted in (previous_name, self.division["name"]):
            with self.subTest(name=accepted):
                payload = self.payload()
                payload["applicant_department_name"] = accepted
                backend.supabase_create_official_editor_draft(payload, self.session)
                stored = [row for table, row in self.inserted if table == "official_documents"][-1]
                self.assertEqual(stored["applicant_department_name"], self.division["name"])
        payload["applicant_department_name"] = "非本人部門"
        with self.assertRaisesRegex(PermissionError, "finance_unit_payload_mismatch"):
            backend.supabase_create_official_editor_draft(payload, self.session)

    def test_invalid_current_unit_never_falls_back_to_another_department(self):
        valid = copy.deepcopy(self.division)
        unsafe_sets = (
            [self.department],
            [{**valid, "status": "inactive"}, self.department],
            [{**valid, "finance_tenant_id": self.other_tenant}, self.department],
            [valid, {**valid, "id": "FINORG-DUPLICATE"}, self.department],
            [{**valid, "entity_codes": ["E2"]}, self.department],
        )
        for units in unsafe_sets:
            with self.subTest(units=[unit["id"] for unit in units]):
                self.units = units
                self.assertIsNone(self.directory()["currentApplicantDepartment"])

    def test_missing_profile_or_unbound_company_has_no_applicant_metadata(self):
        self.user["external_account_payload_json"] = {}
        self.assertIsNone(self.directory()["currentApplicantDepartment"])
        self.user["external_account_payload_json"] = {"financeProfile": {"departmentCode": "A1000"}}
        self.company["finance_tenant_id"] = self.other_tenant
        self.assertIsNone(self.directory()["currentApplicantDepartment"])

    def test_cached_department_cannot_create_after_authority_is_removed(self):
        payload = self.payload()
        valid = copy.deepcopy(self.division)
        for units in (
            [self.department],
            [{**valid, "status": "inactive"}, self.department],
            [{**valid, "finance_tenant_id": self.other_tenant}, self.department],
            [valid, {**valid, "id": "FINORG-DUPLICATE"}, self.department],
        ):
            with self.subTest(units=[unit["id"] for unit in units]):
                self.units = units
                with self.assertRaisesRegex(PermissionError, "finance_unit_projection_unavailable"):
                    backend.supabase_create_official_editor_draft(payload, self.session)
                self.assertEqual(self.inserted, [])

    def test_cross_company_and_missing_permissions_remain_denied(self):
        payload = self.payload()
        payload["company_id"] = self.other_company["id"]
        with self.assertRaisesRegex(PermissionError, "finance_unit_company_mismatch"):
            backend.supabase_create_official_editor_draft(payload, self.session)
        self.session["permissions"] = []
        with self.assertRaisesRegex(PermissionError, "official_document_create_forbidden"):
            backend.supabase_create_official_editor_draft(self.payload(), self.session)
        self.assertEqual(self.inserted, [])

    def test_all_applicant_roles_choose_same_tenant_company_without_role_change(self):
        other_unit = {**self.department, "id": "FINORG-SECOND", "finance_unit_id": "unit-second", "code": "D2000", "name": "隔離測試乙部", "entity_codes": ["E2"]}
        self.units.append(other_unit)
        for role, key in (("員工", "staff"), ("主管", "section_chief"), ("主任", "department_head"), ("執行長", "ceo"), ("行政部主任", "admin_director"), ("總務", "ga_chief")):
            with self.subTest(role=role):
                self.user.update({"role": role, "logging_role_key": key})
                original = copy.deepcopy(self.user)
                directory = self.directory()
                self.assertEqual({row["id"] for row in directory["editorApplicantCompanies"]}, {"CO-001", "CO-OTHER"})
                payload = {**self.payload(department=other_unit), "company_id": "CO-OTHER"}
                backend.supabase_create_official_editor_draft(payload, self.session)
                stored = [row for table, row in self.inserted if table == "official_documents"][-1]
                self.assertEqual((stored["company_id"], stored["applicant_department_id"]), ("CO-OTHER", "D2000"))
                self.assertEqual(self.user, original)
                self.assertEqual(stored["applicant_id"], original["id"])
                self.assertEqual(backend._supabase_editor_assert_document_access(stored, self.session, write=True)["role"], role)

    def test_cross_tenant_inactive_unmirrored_or_missing_tenant_company_denied(self):
        for mutation in ({"finance_tenant_id": self.other_tenant}, {"status": "inactive"}, {"source_system": "manual"}, {"finance_entity_id": ""}):
            with self.subTest(mutation=mutation):
                old = copy.deepcopy(self.other_company)
                self.other_company.update(mutation)
                with self.assertRaisesRegex(PermissionError, "official_document_company_forbidden"):
                    backend.official_editor_company(self.user, "CO-OTHER")
                self.other_company = old
        self.user["finance_tenant_id"] = ""
        with self.assertRaisesRegex(PermissionError, "official_document_company_forbidden"):
            backend.official_editor_company(self.user, "CO-001")

    def test_directory_creation_choice_does_not_expand_general_records_scope(self):
        self.user.update({"role": "員工", "logging_role_key": "staff"})
        result = self.directory()
        self.assertEqual([row["id"] for row in result["companies"]], ["CO-001"])
        self.assertEqual({row["id"] for row in result["editorApplicantCompanies"]}, {"CO-001", "CO-OTHER"})
        self.assertEqual(result["currentCompanyId"], "CO-001")
        self.assertEqual(result["currentApplicantDepartment"]["code"], "A1000")

    def test_stale_disabled_duplicate_or_invalid_selected_department_fails_closed(self):
        baseline = copy.deepcopy(self.department)
        payload = self.payload(department=self.department)
        for replacement in ({**baseline, "status": "inactive"}, {**baseline, "unit_type": "position"}, {**baseline, "entity_scope_mode": "bogus"}, {**baseline, "entity_codes": ["E2"]}):
            self.units = [self.division, replacement]
            with self.assertRaises(PermissionError):
                backend.supabase_create_official_editor_draft(payload, self.session)
            if replacement.get("entity_codes") != ["E2"]:
                self.assertNotIn("D1000", [row["code"] for row in self.directory()["editorApplicantDepartments"]])
        self.units = [self.division, baseline, {**baseline, "id": "DUPLICATE"}]
        with self.assertRaises(PermissionError):
            backend.supabase_create_official_editor_draft(payload, self.session)

    def test_department_inheritance_is_company_scoped_and_cycles_rejected(self):
        self.department.update({"entity_scope_mode": "inherit", "entity_codes": []})
        self.assertEqual(backend.authoritative_editor_applicant_department(self.user, self.payload(department=self.department), self.company)["id"], "D1000")
        self.division.update({"entity_scope_mode": "inherit", "parent_finance_unit_id": self.department["finance_unit_id"]})
        with self.assertRaisesRegex(PermissionError, "finance_unit_company_mismatch"):
            backend.authoritative_editor_applicant_department(self.user, self.payload(department=self.department), self.company)

    def test_selected_department_patch_is_canonical_and_keeps_actor_hierarchy(self):
        document = {"company_id": "CO-001", "source_type": "uploaded_pdf", "applicant_department_id": "A1000", "applicant_department_name": self.division["name"], "metadata_json": {"pdf_editor_v2": True}}
        actor = copy.deepcopy(self.user)
        selected = backend._editor_correction_department(self.user, document, self.payload(department=self.department))
        self.assertEqual(selected, {"id": "D1000", "name": self.department["name"]})
        self.assertEqual(self.user, actor)
        with self.assertRaisesRegex(PermissionError, "finance_unit_payload_mismatch"):
            backend._editor_correction_department(self.user, document, {**self.payload(department=self.department), "dispatch_unit": "偽造高階單位"})

    def test_company_and_submitted_case_remain_immutable_and_other_applicant_denied(self):
        backend.supabase_create_official_editor_draft(self.payload(), self.session)
        document = next(row for table, row in self.inserted if table == "official_documents")
        document["current_status"] = "pending_general_affairs_review"
        with self.assertRaisesRegex(ValueError, "editor_locked_after_submit"):
            backend._supabase_editor_assert_document_access(document, self.session, write=True)
        document["current_status"] = "draft"
        document["applicant_id"] = "ANOTHER-APPLICANT"
        with self.assertRaisesRegex(PermissionError, "official_editor_write_forbidden"):
            backend._supabase_editor_assert_document_access(document, self.session, write=True)
        with self.assertRaisesRegex(PermissionError, "official_document_company_forbidden"):
            backend._official_correction_plan(document, {"company_id": "CO-OTHER"}, None)

    def test_metadata_only_empty_v2_draft_does_not_require_pdf(self):
        document = {"source_type": "uploaded_pdf", "metadata_json": {"pdf_editor_v2": True}}
        self.assertTrue(backend._editor_metadata_only_correction(document, {"title": "new"}, None))
        self.assertFalse(backend._editor_metadata_only_correction(document, {"stamp_positions": []}, None))
        self.assertFalse(backend._editor_metadata_only_correction({**document, "source_type": "blank_editor"}, {"title": "new"}, None))


if __name__ == "__main__":
    unittest.main()
