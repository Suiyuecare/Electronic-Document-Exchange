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
                    "https://storage-project.storage.supabase.co/storage/v1/upload/resumable",
                )

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
