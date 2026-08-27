import os
import unittest
from unittest import mock

import backend


class SeparateSupabaseStorageTests(unittest.TestCase):
    def storage_config(
        self,
        *,
        storage_url: str,
        storage_key: str = "",
        publishable_key: str = "sb_publishable_browser_safe",
    ):
        return mock.patch.multiple(
            backend,
            SUPABASE_URL="https://database-project.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="sb_secret_database",
            EDOC_STORAGE_PROVIDER="supabase",
            EDOC_STORAGE_SUPABASE_URL=storage_url,
            EDOC_STORAGE_SERVICE_ROLE_KEY=storage_key,
            EDOC_STORAGE_PUBLISHABLE_KEY=publishable_key,
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
                backend, "supabase_cleanup_stale_official_editor_uploads", return_value={"count": 0, "asset_ids": []}
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

        self.assertTrue(intent["upload_url"].endswith("/storage/v1/upload/resumable/sign"))
        self.assertEqual(intent["storage_publishable_key"], "sb_publishable_browser_safe")
        self.assertEqual(intent["upload_token"], "short-lived-object-signature")
        self.assertEqual(intent["headers"]["x-signature"], "short-lived-object-signature")
        self.assertNotIn("apikey", intent["headers"])
        self.assertNotIn("authorization", {key.lower() for key in intent["headers"]})
        self.assertNotIn("sb_secret_storage", repr(intent))

    def test_tus_intent_rejects_secret_or_service_role_browser_keys(self):
        for unsafe_key in ("sb_secret_storage", "header.service_role.signature"):
            with self.subTest(unsafe_key=unsafe_key), self.storage_config(
                storage_url="https://storage-project.supabase.co",
                storage_key="sb_secret_storage",
                publishable_key=unsafe_key,
            ), mock.patch.object(
                backend,
                "pdf_editor_v2_company_scope_mode",
                return_value="finance_active",
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "editor_storage_publishable_key_invalid",
                ):
                    backend._supabase_storage_public_upload_key()
                status = backend.supabase_storage_browser_upload_key_status()
                self.assertFalse(status["ready"])
                self.assertEqual(
                    status["errorCode"],
                    "editor_storage_publishable_key_invalid",
                )
                self.assertNotIn(unsafe_key, repr(status))

    def test_legacy_anon_jwt_remains_a_browser_safe_storage_key(self):
        # Signature validation belongs to Supabase. The server only decodes the
        # public role claim to ensure it never returns a service-role JWT.
        legacy_anon = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJyb2xlIjoiYW5vbiJ9."
            "signature"
        )
        with self.storage_config(
            storage_url="https://storage-project.supabase.co",
            publishable_key=legacy_anon,
        ):
            self.assertEqual(
                backend._supabase_storage_public_upload_key(),
                legacy_anon,
            )

    def test_editor_storage_readiness_requires_browser_safe_public_key(self):
        antivirus = {
            "ready": True,
            "missingEnvironment": [],
            "configurationIssues": [],
        }
        demo_policy = {
            "disabled": True,
            "explicitDisable": True,
            "safeDefault": False,
            "explicitAllow": False,
        }
        with mock.patch.dict(os.environ, {"EDOC_OBJECT_STORAGE_URL": ""}, clear=False):
            with self.storage_config(
                storage_url="https://storage-project.supabase.co",
                storage_key="sb_secret_storage",
                publishable_key="",
            ), mock.patch.object(
                backend,
                "pdf_editor_v2_company_scope_mode",
                return_value="finance_active",
            ), mock.patch.object(
                backend,
                "launch_company_scope_mode",
                return_value="finance_active",
            ), mock.patch.object(
                backend,
                "is_production",
                return_value=True,
            ), mock.patch.object(
                backend,
                "config_present",
                return_value=True,
            ), mock.patch.object(
                backend,
                "internal_antivirus_readiness",
                return_value=antivirus,
            ), mock.patch.object(
                backend,
                "supabase_project_partition_issues",
                return_value=[],
            ), mock.patch.object(
                backend,
                "demo_account_policy_status",
                return_value=demo_policy,
            ), mock.patch.object(backend, "USE_SUPABASE", True):
                status = backend.storage_service_status()
                readiness = backend.internal_readiness()

        browser_key = status["services"]["browserUploadKey"]
        self.assertFalse(browser_key["configured"])
        self.assertEqual(
            browser_key["errorCode"],
            "editor_storage_publishable_key_required",
        )
        self.assertTrue(status["productionBlocked"])
        self.assertIn("EDOC_STORAGE_PUBLISHABLE_KEY", readiness["missing"])
        self.assertFalse(readiness["ready"])
        self.assertNotIn("sb_secret_storage", repr(status))

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
