"""Applicant-only seal selection does not expand Vault management or file access."""
import copy
import unittest
from contextlib import ExitStack
from unittest import mock

import backend


class EditorSealCatalogScopeTests(unittest.TestCase):
    def setUp(self):
        self.user = {"id": "TEST-APPLICANT", "company_id": "CO-1", "finance_tenant_id": "TENANT-1",
                     "account_source": "finance", "role": "員工", "status": "啟用"}
        self.session = {"user": self.user, "permissions": ["official_documents.compose"]}
        self.company = {"id": "CO-2", "finance_tenant_id": "TENANT-1", "finance_entity_id": "E2",
                        "source_system": "finance", "status": "active"}
        self.seal = {"id": "SEAL-2", "company_id": "CO-2", "is_active": True, "seal_name": "測試章",
                     "seal_size_type": "large_seal", "render_width_mm": 40, "render_height_mm": 40,
                     "current_file": {"id": "FILE-2", "file_hash": "a" * 64, "version": 2,
                                      "render_width_mm": 40, "render_height_mm": 40, "usable": True,
                                      "file_object_id": "PRIVATE-OBJECT", "file_name": "private.png",
                                      "storage_key": "private-vault/path", "uploaded_by": "PRIVATE-PERSON"},
                     "current_file_status": {"storage_key": "private-vault/path"},
                     "created_by": "PRIVATE-PERSON", "purpose_description": "PRIVATE-TEXT"}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(backend, "is_production", return_value=True))
        self.stack.enter_context(mock.patch.object(backend, "launch_company_in_scope", return_value=True))
        self.stack.enter_context(mock.patch.object(backend, "supabase_official_company_row", side_effect=lambda _: self.company))
        self.stack.enter_context(mock.patch.object(backend, "supabase_official_session_user", return_value=self.user))
        self.stack.enter_context(mock.patch.object(backend, "supabase_company_seal_row", side_effect=lambda _: copy.deepcopy(self.seal)))
        self.stack.enter_context(mock.patch.object(backend, "supabase_filter_rows", return_value=[{"id": "SEAL-2"}]))

    def test_same_tenant_applicant_picker_has_only_safe_metadata(self):
        result = backend.supabase_list_company_seals("CO-2", self.session, editor=True)
        self.assertEqual(result[0]["current_file"]["file_hash"], "a" * 64)
        self.assertEqual(result[0]["render_width_mm"], 40)
        self.assertNotIn("PRIVATE", str(result))
        self.assertNotIn("storage_key", str(result))
        self.assertNotIn("file_name", str(result))
        self.assertNotIn("file_object_id", str(result))
        self.assertNotIn("current_file_status", result[0])

    def test_picker_blocks_cross_tenant_inactive_unlinked_and_read_only(self):
        for patch in ({"finance_tenant_id": "TENANT-OTHER"}, {"status": "inactive"},
                      {"source_system": "local"}, {"finance_entity_id": ""}):
            with self.subTest(patch=patch), mock.patch.object(backend, "supabase_official_company_row", return_value={**self.company, **patch}):
                with self.assertRaises(PermissionError):
                    backend.supabase_list_company_seals("CO-2", self.session, editor=True)
        with self.assertRaisesRegex(PermissionError, "official_document_create_forbidden"):
            backend.supabase_list_company_seals("CO-2", {"user": self.user, "permissions": []}, editor=True)

    def test_general_catalog_and_management_keep_original_guard(self):
        with mock.patch.object(backend, "assert_supabase_seal_company_access", side_effect=PermissionError("seal_company_access_forbidden")) as guard:
            with self.assertRaisesRegex(PermissionError, "seal_company_access_forbidden"):
                backend.supabase_list_company_seals("CO-2", self.session)
            guard.assert_called_once_with("CO-2", self.session)
        with self.assertRaisesRegex(PermissionError, "seal_custodian_role_required"):
            backend.require_seal_custodian_role(self.session)

    def test_inactive_seals_are_not_offered(self):
        self.seal["is_active"] = False
        self.assertEqual(backend.supabase_list_company_seals("CO-2", self.session, editor=True), [])
        with self.assertRaisesRegex(PermissionError, "inactive_seal_cannot_be_requested"):
            backend.assert_editor_seal_preview_company(self.user, self.seal)

    def test_cross_tenant_preview_denied_before_reading_vault(self):
        self.company["finance_tenant_id"] = "OTHER"
        with mock.patch.object(backend, "supabase_storage_download") as download:
            with self.assertRaisesRegex(PermissionError, "editor_seal_preview_company_forbidden"):
                backend.supabase_editor_seal_preview("SEAL-2", self.session)
            download.assert_not_called()

    def test_same_tenant_preview_still_requires_exact_version_hash(self):
        current = {"id": "FILE-2", "file_hash": "a" * 64}
        with mock.patch.object(backend, "supabase_require_current_company_seal_file", return_value=current), \
                mock.patch.object(backend, "supabase_storage_download") as download:
            for file_id, digest, expected in (("OLD-FILE", "a" * 64, "revision_required"),
                                              ("FILE-2", "b" * 64, "hash_mismatch")):
                with self.subTest(expected=expected), self.assertRaisesRegex((PermissionError, ValueError), expected):
                    backend.supabase_editor_seal_preview("SEAL-2", self.session, file_id=file_id, file_sha256=digest)
            download.assert_not_called()

    def test_read_only_user_cannot_bypass_picker_via_current_preview(self):
        read_only = {"user": self.user, "permissions": []}
        with mock.patch.object(backend, "supabase_storage_download") as download:
            for binding in ({}, {"file_id": "FILE-2", "file_sha256": "a" * 64}):
                with self.subTest(binding=binding), self.assertRaisesRegex(PermissionError, "official_document_create_forbidden"):
                    backend.supabase_editor_seal_preview("SEAL-2", read_only, **binding)
            download.assert_not_called()

    def test_bound_read_only_preview_must_pass_document_participant_access(self):
        read_only = {"user": self.user, "permissions": []}
        with mock.patch.object(backend, "supabase_official_document_row", return_value={"id": "DOC-2"}), \
                mock.patch.object(backend, "_supabase_editor_assert_document_access", side_effect=PermissionError("editor_document_forbidden")) as access, \
                mock.patch.object(backend, "supabase_storage_download") as download:
            with self.assertRaisesRegex(PermissionError, "editor_document_forbidden"):
                backend.supabase_editor_seal_preview("SEAL-2", read_only, file_id="FILE-2", file_sha256="a" * 64,
                                                   document_id="DOC-2", revision_id="REV-2")
            access.assert_called_once()
            download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
