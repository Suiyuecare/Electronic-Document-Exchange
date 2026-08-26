import os
import unittest
from unittest import mock

import backend


class SeparateSupabaseStorageTests(unittest.TestCase):
    def storage_config(self, *, storage_url: str, storage_key: str = ""):
        return mock.patch.multiple(
            backend,
            SUPABASE_URL="https://database-project.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="sb_secret_database",
            EDOC_STORAGE_PROVIDER="supabase",
            EDOC_STORAGE_SUPABASE_URL=storage_url,
            EDOC_STORAGE_SERVICE_ROLE_KEY=storage_key,
            EDOC_OBJECT_STORAGE_URL="",
        )

    def test_dedicated_storage_uses_its_own_url_and_key(self):
        with mock.patch.dict(os.environ, {"EDOC_OBJECT_STORAGE_URL": ""}, clear=False):
            with self.storage_config(
                storage_url="https://storage-project.supabase.co",
                storage_key="sb_secret_storage",
            ):
                self.assertEqual(
                    backend.object_storage_endpoint(),
                    "https://storage-project.supabase.co/storage/v1",
                )
                self.assertFalse(backend.storage_uses_database_supabase_project())
                self.assertEqual(backend.storage_service_role_key(), "sb_secret_storage")
                headers = backend.supabase_storage_headers()
                self.assertEqual(headers["apikey"], "sb_secret_storage")
                self.assertNotIn("Authorization", headers)

    def test_cross_project_storage_fails_closed_without_server_key(self):
        with mock.patch.dict(os.environ, {"EDOC_OBJECT_STORAGE_URL": ""}, clear=False):
            with self.storage_config(storage_url="https://storage-project.supabase.co"):
                self.assertEqual(backend.storage_service_role_key(), "")
                with self.assertRaisesRegex(
                    backend.SupabaseConfigurationError,
                    "supabase_storage_server_credential_missing",
                ):
                    backend.supabase_storage_headers()

    def test_same_project_storage_keeps_database_key_compatibility(self):
        with mock.patch.dict(os.environ, {"EDOC_OBJECT_STORAGE_URL": ""}, clear=False):
            with self.storage_config(storage_url="https://database-project.supabase.co"):
                self.assertTrue(backend.storage_uses_database_supabase_project())
                self.assertEqual(
                    backend.storage_service_role_key(),
                    "sb_secret_database",
                )

    def test_tus_url_is_derived_from_storage_project_not_database_project(self):
        with mock.patch.dict(os.environ, {"EDOC_OBJECT_STORAGE_URL": ""}, clear=False):
            with self.storage_config(
                storage_url="https://storage-project.supabase.co",
                storage_key="sb_secret_storage",
            ):
                self.assertEqual(
                    backend._supabase_storage_direct_tus_url(),
                    "https://storage-project.storage.supabase.co/storage/v1/upload/resumable/sign",
                )

    def test_signed_tus_route_contract_never_returns_server_credential(self):
        with mock.patch.dict(os.environ, {"EDOC_OBJECT_STORAGE_URL": ""}, clear=False):
            with self.storage_config(
                storage_url="https://storage-project.supabase.co",
                storage_key="sb_secret_storage",
            ), mock.patch.object(
                backend, "_supabase_create_signed_upload_token", return_value="short-lived-object-signature"
            ), mock.patch.object(
                backend, "_supabase_editor_assert_document_access", return_value={"id": "FIN-U1"}
            ), mock.patch.object(
                backend, "supabase_official_document_row", return_value={"id": "OD-1"}
            ), mock.patch.object(
                backend, "_supabase_editor_latest_revision", return_value={"id": "REV-1", "revision_no": 1}
            ), mock.patch.object(
                backend, "supabase_insert", side_effect=lambda _table, row: row
            ):
                intent = backend.supabase_create_official_editor_upload_intent(
                    "OD-1",
                    {
                        "file_name": "a4.pdf",
                        "mime_type": "application/pdf",
                        "size_bytes": 128,
                        "sha256": "A" * 64,
                    },
                    {"user": {"id": "FIN-U1"}},
                )

        self.assertTrue(intent["upload_url"].endswith("/upload/resumable/sign"))
        self.assertEqual(intent["headers"]["x-signature"], "short-lived-object-signature")
        self.assertNotIn("apikey", intent["headers"])
        self.assertNotIn("authorization", {key.lower() for key in intent["headers"]})
        self.assertNotIn("sb_secret_storage", repr(intent))

    def test_dedicated_mode_rejects_database_and_storage_url_alias(self):
        with self.storage_config(
            storage_url="https://database-project.supabase.co",
            storage_key="sb_secret_storage",
        ), mock.patch.object(backend, "EDOC_STORAGE_SUPABASE_MODE", "dedicated-project"):
            self.assertEqual(
                backend.supabase_project_partition_issues(),
                ["dedicated_storage_project_must_differ_from_database"],
            )

    def test_auto_mode_preserves_legal_same_project_compatibility(self):
        with self.storage_config(
            storage_url="https://database-project.supabase.co",
        ), mock.patch.object(backend, "EDOC_STORAGE_SUPABASE_MODE", "auto"):
            self.assertEqual(backend.supabase_project_partition_issues(), [])

    def test_storage_status_never_exposes_server_key(self):
        with mock.patch.dict(os.environ, {"EDOC_OBJECT_STORAGE_URL": ""}, clear=False):
            with self.storage_config(
                storage_url="https://storage-project.supabase.co",
                storage_key="sb_secret_storage",
            ), mock.patch.object(backend, "EDOC_FILE_ENCRYPTION_ENABLED", True), mock.patch.object(
                backend, "EDOC_FILE_ENCRYPTION_KEY", "test-encryption-key"
            ):
                status = backend.storage_service_status()
                self.assertTrue(status["services"]["serverCredential"]["configured"])
                self.assertTrue(status["policy"]["separateSupabaseProject"])
                self.assertNotIn("sb_secret_storage", repr(status))


if __name__ == "__main__":
    unittest.main()
