from __future__ import annotations

import json
import unittest
from unittest import mock

import backend


class SharedSupabaseSchemaModeTestCase(unittest.TestCase):
    def shared_config(self, **overrides):
        values = {
            "SUPABASE_URL": "https://shared-project.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_edoc_custom_role",
            "EDOC_SUPABASE_SCHEMA": "edoc",
            "EDOC_SUPABASE_BACKEND_ROLE": "edoc_backend",
            "EDOC_STORAGE_PROVIDER": "supabase",
            "EDOC_STORAGE_SUPABASE_MODE": "shared-project-schema",
            "EDOC_STORAGE_SUPABASE_URL": "https://shared-project.supabase.co",
            "EDOC_STORAGE_SERVICE_ROLE_KEY": "sb_secret_edoc_custom_role",
            "EDOC_OBJECT_STORAGE_URL": "",
        }
        values.update(overrides)
        return mock.patch.multiple(backend, **values)

    def test_valid_shared_project_configuration_is_accepted(self) -> None:
        with self.shared_config():
            self.assertEqual(backend.supabase_project_partition_issues(), [])

    def test_shared_project_rejects_unsafe_schema_role_key_and_split_storage(self) -> None:
        cases = (
            (
                {"EDOC_SUPABASE_SCHEMA": "public"},
                "shared_project_edoc_schema_required",
            ),
            (
                {"EDOC_SUPABASE_BACKEND_ROLE": "service_role"},
                "shared_project_backend_role_required",
            ),
            (
                {"SUPABASE_SERVICE_ROLE_KEY": "legacy.jwt.value"},
                "shared_project_custom_role_secret_required",
            ),
            (
                {
                    "EDOC_STORAGE_SUPABASE_URL": (
                        "https://different-project.supabase.co"
                    )
                },
                "shared_project_storage_url_mismatch",
            ),
            (
                {"EDOC_STORAGE_SERVICE_ROLE_KEY": "sb_secret_different"},
                "shared_project_storage_key_mismatch",
            ),
        )
        for overrides, expected in cases:
            with self.subTest(expected=expected), self.shared_config(**overrides):
                self.assertIn(
                    expected,
                    backend.supabase_project_partition_issues(),
                )

    def test_non_shared_mode_rejects_custom_schema_or_role(self) -> None:
        with self.shared_config(
            EDOC_STORAGE_SUPABASE_MODE="same-project",
            EDOC_SUPABASE_SCHEMA="edoc",
            EDOC_SUPABASE_BACKEND_ROLE="edoc_backend",
        ):
            self.assertIn(
                "supabase_schema_role_mode_mismatch",
                backend.supabase_project_partition_issues(),
            )

    def test_postgrest_headers_select_edoc_schema_without_bearer_secret(self) -> None:
        with self.shared_config():
            headers = backend.supabase_headers({"Prefer": "return=representation"})

        self.assertEqual(headers["Accept-Profile"], "edoc")
        self.assertEqual(headers["Content-Profile"], "edoc")
        self.assertEqual(headers["apikey"], "sb_secret_edoc_custom_role")
        self.assertEqual(headers["Prefer"], "return=representation")
        self.assertNotIn("Authorization", headers)

    def test_historical_public_mode_does_not_send_profile_headers(self) -> None:
        with mock.patch.multiple(
            backend,
            SUPABASE_URL="https://dedicated-project.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="legacy.jwt.value",
            EDOC_SUPABASE_SCHEMA="public",
            EDOC_SUPABASE_BACKEND_ROLE="service_role",
        ):
            headers = backend.supabase_headers()

        self.assertNotIn("Accept-Profile", headers)
        self.assertNotIn("Content-Profile", headers)
        self.assertEqual(headers["Authorization"], "Bearer legacy.jwt.value")

    def test_identity_probe_requires_exact_role_schema_and_mode(self) -> None:
        expected = {
            "databaseRole": "edoc_backend",
            "schemaName": "edoc",
            "storageMode": "shared-project-schema",
        }
        with self.shared_config(), mock.patch.object(
            backend,
            "_readiness_http_json",
            return_value=[expected],
        ) as fetch:
            result = backend._probe_shared_supabase_identity(0.25)

        self.assertTrue(result["ready"])
        self.assertTrue(result["checked"])
        self.assertEqual(result["errorCode"], "")
        self.assertTrue(fetch.call_args.args[0].endswith("/rpc/edoc_runtime_identity"))
        self.assertEqual(fetch.call_args.kwargs["method"], "POST")
        self.assertEqual(fetch.call_args.kwargs["body"], b"{}")
        self.assertEqual(fetch.call_args.kwargs["headers"]["Accept-Profile"], "edoc")
        self.assertEqual(fetch.call_args.kwargs["headers"]["Content-Profile"], "edoc")
        self.assertFalse(fetch.call_args.kwargs["allow_redirects"])

        for field, bad_value in (
            ("databaseRole", "service_role"),
            ("schemaName", "public"),
            ("storageMode", "same-project"),
        ):
            mismatch = dict(expected)
            mismatch[field] = bad_value
            with self.subTest(field=field), self.shared_config(), mock.patch.object(
                backend,
                "_readiness_http_json",
                return_value=mismatch,
            ):
                result = backend._probe_shared_supabase_identity(0.25)
                self.assertFalse(result["ready"])
                self.assertEqual(
                    result["errorCode"],
                    "shared_project_identity_mismatch",
                )
                self.assertNotIn(bad_value, json.dumps(result))

    def test_identity_probe_is_omitted_outside_shared_mode(self) -> None:
        with mock.patch.object(
            backend,
            "EDOC_STORAGE_SUPABASE_MODE",
            "dedicated-project",
        ), mock.patch.object(backend, "_readiness_http_json") as fetch:
            result = backend._probe_shared_supabase_identity(0.25)

        self.assertTrue(result["ready"])
        self.assertFalse(result["checked"])
        fetch.assert_not_called()

    def test_runtime_readiness_includes_shared_identity_gate(self) -> None:
        ready_probe = {"ready": True, "checked": True, "errorCode": ""}
        with self.shared_config(), mock.patch.object(
            backend,
            "is_production",
            return_value=True,
        ), mock.patch.object(
            backend,
            "_probe_main_supabase_query",
            return_value=ready_probe,
        ), mock.patch.object(
            backend,
            "_probe_main_supabase_rpcs",
            return_value=ready_probe,
        ), mock.patch.object(
            backend,
            "_probe_supabase_private_buckets",
            return_value=ready_probe,
        ), mock.patch.object(
            backend,
            "_probe_supabase_publishable_key_affinity",
            return_value=ready_probe,
        ), mock.patch.object(
            backend,
            "_probe_antivirus_runtime",
            return_value=ready_probe,
        ), mock.patch.object(
            backend,
            "_probe_shared_supabase_identity",
            return_value={
                "ready": False,
                "checked": True,
                "errorCode": "shared_project_identity_mismatch",
            },
        ) as identity:
            readiness = backend.production_runtime_dependency_readiness()

        self.assertFalse(readiness["ready"])
        self.assertIn("sharedProjectIdentity", readiness["checks"])
        self.assertIn(
            "shared_project_identity_mismatch",
            readiness["errorCodes"],
        )
        identity.assert_called_once()


if __name__ == "__main__":
    unittest.main()
