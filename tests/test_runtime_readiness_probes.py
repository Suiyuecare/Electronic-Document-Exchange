import json
import unittest
import urllib.error
from unittest import mock

import backend


class RuntimeReadinessProbeTestCase(unittest.TestCase):
    def production_runtime_config(self):
        return mock.patch.multiple(
            backend,
            SUPABASE_URL="https://missing-main-project.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="sb_secret_" + ("m" * 40),
            USE_SUPABASE=True,
            EDOC_STORAGE_PROVIDER="supabase",
            EDOC_STORAGE_SUPABASE_URL="https://missing-storage-project.supabase.co",
            EDOC_STORAGE_SERVICE_ROLE_KEY="sb_secret_" + ("s" * 40),
            EDOC_STORAGE_PUBLISHABLE_KEY="sb_publishable_" + ("p" * 40),
            EDOC_STORAGE_BUCKET="edoc-private",
            EDOC_SEAL_STORAGE_BUCKET="edoc-seal-vault",
            EDOC_AV_PROVIDER=backend.VERCEL_SANDBOX_AV_PROVIDER_ID,
            EDOC_AV_SANDBOX_SNAPSHOT_ID="snap_1234567890ABCDEF",
            RUNNING_ON_VERCEL=True,
        )

    def test_nonproduction_readyz_never_probes_external_dependencies(self):
        configured = {"ready": False, "marker": "configuration-only"}
        with (
            mock.patch.object(backend, "is_production", return_value=False),
            mock.patch.object(backend, "internal_readiness", return_value=configured),
            mock.patch.object(backend.urllib.request, "urlopen") as urlopen,
            mock.patch.object(backend.socket, "create_connection") as create_connection,
        ):
            result = backend.readiness_for_public_endpoint(["readyz"])

        self.assertIs(result, configured)
        urlopen.assert_not_called()
        create_connection.assert_not_called()

    def test_format_correct_but_unreachable_supabase_returns_public_503(self):
        configured = {"ready": True, "internalGo": True, "checks": {}, "blockers": []}
        with (
            self.production_runtime_config(),
            mock.patch.dict(
                backend.os.environ,
                {
                    "EDOC_OBJECT_STORAGE_URL": "",
                    "EDOC_READINESS_PROBE_TIMEOUT_SECONDS": "0.25",
                },
                clear=False,
            ),
            mock.patch.object(backend, "is_production", return_value=True),
            mock.patch.object(backend, "internal_readiness", return_value=configured),
            mock.patch.object(
                backend.urllib.request,
                "urlopen",
                side_effect=urllib.error.URLError("name resolution failed"),
            ) as urlopen,
        ):
            payload, status = backend.public_readiness_response(["readyz"])

        self.assertEqual(status, 503)
        self.assertEqual(payload["status"], "not_ready")
        self.assertFalse(payload["ready"])
        self.assertGreaterEqual(urlopen.call_count, 3)
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("missing-main-project", serialized)
        self.assertNotIn("missing-storage-project", serialized)
        self.assertNotIn("sb_secret_", serialized)
        self.assertEqual(set(payload), {"ok", "ready", "status", "time"})

    def test_runtime_probe_requires_query_rpcs_and_two_private_buckets(self):
        rpc_paths = {
            f"/rpc/{name}": {"post": {}}
            for name in backend.EDOC_READINESS_REQUIRED_RPC_NAMES
        }

        def response_for(url, **_kwargs):
            if "official_documents?" in url:
                return []
            if url.endswith("/rest/v1/"):
                return {"paths": rpc_paths}
            if url.endswith("/storage/v1/bucket"):
                return [
                    {"id": "edoc-private", "public": False},
                    {"id": "edoc-seal-vault", "public": False},
                ]
            if url.endswith("/auth/v1/settings"):
                return {"external": {}}
            raise AssertionError(f"unexpected probe path: {url}")

        with (
            self.production_runtime_config(),
            mock.patch.dict(backend.os.environ, {"EDOC_OBJECT_STORAGE_URL": ""}, clear=False),
            mock.patch.object(backend, "is_production", return_value=True),
            mock.patch.object(backend, "_readiness_http_json", side_effect=response_for),
        ):
            readiness = backend.production_runtime_dependency_readiness()

        self.assertTrue(readiness["checked"])
        self.assertTrue(readiness["ready"])
        self.assertEqual(readiness["errorCodes"], [])
        self.assertEqual(
            readiness["checks"]["databaseRpcs"]["requiredRpcCount"],
            len(backend.EDOC_READINESS_REQUIRED_RPC_NAMES),
        )
        self.assertTrue(
            readiness["checks"]["privateStorage"]["documentBucket"]["private"]
        )
        self.assertTrue(
            readiness["checks"]["privateStorage"]["sealVaultBucket"]["private"]
        )
        self.assertTrue(readiness["checks"]["storagePublicKeyAffinity"]["ready"])
        self.assertFalse(readiness["containsEndpoint"])
        self.assertFalse(readiness["containsSecret"])
        self.assertFalse(readiness["containsPii"])

    def test_missing_rpc_or_public_bucket_fails_closed(self):
        rpc_paths = {
            f"/rpc/{name}": {"post": {}}
            for name in backend.EDOC_READINESS_REQUIRED_RPC_NAMES[1:]
        }

        def response_for(url, **_kwargs):
            if "official_documents?" in url:
                return []
            if url.endswith("/rest/v1/"):
                return {"paths": rpc_paths}
            if url.endswith("/storage/v1/bucket"):
                return [
                    {"id": "edoc-private", "public": True},
                    {"id": "edoc-seal-vault", "public": False},
                ]
            if url.endswith("/auth/v1/settings"):
                return {"external": {}}
            raise AssertionError(f"unexpected probe path: {url}")

        with (
            self.production_runtime_config(),
            mock.patch.dict(backend.os.environ, {"EDOC_OBJECT_STORAGE_URL": ""}, clear=False),
            mock.patch.object(backend, "is_production", return_value=True),
            mock.patch.object(backend, "_readiness_http_json", side_effect=response_for),
        ):
            readiness = backend.production_runtime_dependency_readiness()

        self.assertFalse(readiness["ready"])
        self.assertIn("database_required_rpc_missing", readiness["errorCodes"])
        self.assertIn("storage_bucket_not_private", readiness["errorCodes"])
        self.assertEqual(readiness["checks"]["databaseRpcs"]["missingRpcCount"], 1)
        self.assertEqual(readiness["checks"]["privateStorage"]["publicBucketCount"], 1)

    def test_storage_publishable_key_affinity_uses_public_read_only_endpoint(self):
        publishable_key = "sb_publishable_" + ("p" * 40)
        with (
            self.production_runtime_config(),
            mock.patch.object(
                backend,
                "_readiness_http_json",
                return_value={"external": {"google": True}},
            ) as fetch,
        ):
            readiness = backend._probe_supabase_publishable_key_affinity(0.25)

        self.assertTrue(readiness["ready"])
        self.assertTrue(readiness["checked"])
        self.assertFalse(readiness["containsEndpoint"])
        self.assertFalse(readiness["containsKey"])
        self.assertNotIn("missing-storage-project", repr(readiness))
        self.assertNotIn(publishable_key, repr(readiness))
        self.assertEqual(
            fetch.call_args.args[0],
            "https://missing-storage-project.supabase.co/auth/v1/settings",
        )
        self.assertEqual(fetch.call_args.kwargs["headers"]["apikey"], publishable_key)
        self.assertNotIn("Authorization", fetch.call_args.kwargs["headers"])

    def test_storage_publishable_key_affinity_rejects_non_supabase_hosts_and_ports(self):
        unsafe_urls = (
            "https://attacker.example.test",
            "https://project.supabase.co.attacker.example.test",
            "https://project.supabase.co:8443",
        )
        for project_url in unsafe_urls:
            with self.subTest(project_url=project_url):
                with (
                    self.production_runtime_config(),
                    mock.patch.object(
                        backend,
                        "EDOC_STORAGE_SUPABASE_URL",
                        project_url,
                    ),
                    mock.patch.object(backend, "_readiness_http_json") as fetch,
                ):
                    readiness = backend._probe_supabase_publishable_key_affinity(0.25)

                self.assertFalse(readiness["ready"])
                self.assertEqual(
                    readiness["errorCode"],
                    "storage_publishable_key_affinity_config_invalid",
                )
                self.assertNotIn(project_url, repr(readiness))
                fetch.assert_not_called()

    def test_storage_publishable_key_from_wrong_project_is_rejected(self):
        response = urllib.error.HTTPError(
            "https://missing-storage-project.supabase.co/auth/v1/settings",
            401,
            "Unauthorized",
            {},
            None,
        )
        with (
            self.production_runtime_config(),
            mock.patch.object(
                backend,
                "_readiness_http_json",
                side_effect=response,
            ),
        ):
            readiness = backend._probe_supabase_publishable_key_affinity(0.25)

        self.assertFalse(readiness["ready"])
        self.assertEqual(
            readiness["errorCode"],
            "storage_publishable_key_affinity_rejected",
        )
        self.assertNotIn("missing-storage-project", repr(readiness))
        self.assertNotIn("sb_publishable_", repr(readiness))

    def test_storage_publishable_key_affinity_timeout_fails_closed(self):
        with (
            self.production_runtime_config(),
            mock.patch.object(
                backend,
                "_readiness_http_json",
                side_effect=TimeoutError("probe timed out"),
            ),
        ):
            readiness = backend._probe_supabase_publishable_key_affinity(0.25)

        self.assertFalse(readiness["ready"])
        self.assertEqual(
            readiness["errorCode"],
            "storage_publishable_key_affinity_unavailable",
        )
        self.assertNotIn("probe timed out", repr(readiness))

    def test_wrong_storage_key_affinity_public_response_is_masked(self):
        rpc_paths = {
            f"/rpc/{name}": {"post": {}}
            for name in backend.EDOC_READINESS_REQUIRED_RPC_NAMES
        }
        publishable_key = "sb_publishable_" + ("p" * 40)

        def response_for(url, **_kwargs):
            if "official_documents?" in url:
                return []
            if url.endswith("/rest/v1/"):
                return {"paths": rpc_paths}
            if url.endswith("/storage/v1/bucket"):
                return [
                    {"id": "edoc-private", "public": False},
                    {"id": "edoc-seal-vault", "public": False},
                ]
            if url.endswith("/auth/v1/settings"):
                raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)
            raise AssertionError(f"unexpected probe path: {url}")

        configured = {"ready": True, "internalGo": True, "checks": {}, "blockers": []}
        with (
            self.production_runtime_config(),
            mock.patch.dict(backend.os.environ, {"EDOC_OBJECT_STORAGE_URL": ""}, clear=False),
            mock.patch.object(backend, "is_production", return_value=True),
            mock.patch.object(backend, "internal_readiness", return_value=configured),
            mock.patch.object(backend, "_readiness_http_json", side_effect=response_for),
        ):
            payload, status = backend.public_readiness_response(["readyz"])

        self.assertEqual(status, 503)
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(set(payload), {"ok", "ready", "status", "time"})
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("missing-storage-project", serialized)
        self.assertNotIn(publishable_key, serialized)
        self.assertNotIn("storage_publishable_key_affinity_rejected", serialized)

    def test_https_antivirus_health_api_is_probed_without_exposing_url(self):
        with (
            mock.patch.multiple(
                backend,
                EDOC_AV_PROVIDER="edoc-clamav-https-v1",
                EDOC_AV_ENDPOINT="https://scanner.example.test/v1/scan",
            ),
            mock.patch.object(
                backend,
                "_readiness_http_json",
                return_value={"ok": True, "status": "ready"},
            ) as fetch,
        ):
            readiness = backend._probe_antivirus_runtime(0.25)

        self.assertTrue(readiness["ready"])
        self.assertTrue(readiness["checked"])
        self.assertTrue(readiness["healthApiAvailable"])
        self.assertNotIn("scanner.example.test", repr(readiness))
        self.assertEqual(fetch.call_args.args[0], "https://scanner.example.test/healthz")

    def test_healthz_payload_remains_pure_liveness(self):
        for production in (False, True):
            with self.subTest(production=production):
                with (
                    mock.patch.object(backend, "is_production", return_value=production),
                    mock.patch.object(backend.urllib.request, "urlopen") as urlopen,
                    mock.patch.object(backend.socket, "create_connection") as create_connection,
                ):
                    payload = backend.public_health_payload(
                        database="private-database-path",
                        project="https://private-project.supabase.co",
                    )

                    self.assertEqual(set(payload), {"ok", "status", "time"})
                    self.assertTrue(payload["ok"])
                    urlopen.assert_not_called()
                    create_connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
