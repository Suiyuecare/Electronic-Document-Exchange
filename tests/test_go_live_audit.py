from __future__ import annotations

import os
import sqlite3
import unittest
from unittest import mock

import backend


class GoLiveAuditTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._constants = {
            name: getattr(backend, name)
            for name in [
                "DEPLOYMENT_ENV",
                "USE_SUPABASE",
                "SUPABASE_URL",
                "SUPABASE_SERVICE_ROLE_KEY",
                "EDOC_STORAGE_PROVIDER",
                "EDOC_STORAGE_BUCKET",
                "EDOC_OBJECT_STORAGE_URL",
                "EDOC_STORAGE_ACCESS_MODE",
                "EDOC_FILE_ENCRYPTION_ENABLED",
                "EDOC_SCAN_ENGINE",
                "EDOC_AV_PROVIDER",
                "EDOC_AV_ENDPOINT",
                "EDOC_MAX_FILE_SIZE_MB",
                "EDOC_ALLOWED_MIME_TYPES",
                "EDOC_SIGNATURE_PROVIDER",
                "EDOC_SIGNATURE_API_URL",
                "EDOC_SIGNATURE_API_KEY",
                "EDOC_SIGNATURE_KEY_ID",
                "EDOC_HSM_PROVIDER",
                "EDOC_CERT_TRUST_STORE",
                "EDOC_TSA_URL",
                "EDOC_TSA_API_KEY",
                "EDOC_OCSP_RESPONDER_URL",
                "EDOC_CRL_DISTRIBUTION_URL",
                "EDOC_EXCHANGE_PROVIDER",
            ]
        }

    def tearDown(self) -> None:
        for name, value in self._constants.items():
            setattr(backend, name, value)

    def apply_formal_env(self) -> mock._patch_dict:
        values = {
            "EDOC_DEPLOYMENT_ENV": "production",
            "EDOC_PUBLIC_BASE_URL": "https://edoc.suiyuecare.com",
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-role",
            "CRON_SECRET": "cron-secret",
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_FROM": "notify@suiyuecare.com",
            "SMTP_CREDENTIAL_EXPIRES_AT": "2026-12-31",
            "LINE_WEBHOOK_URL": "https://line.example/webhook",
            "LINE_CREDENTIAL_EXPIRES_AT": "2026-12-31",
            "APP_SECRET": "app-secret",
            "INBOX_SIGNING_KEY_EXPIRES_AT": "2026-12-31",
            "EDOC_STORAGE_PROVIDER": "supabase",
            "EDOC_STORAGE_BUCKET": "edoc-private",
            "EDOC_OBJECT_STORAGE_URL": "https://project.supabase.co/storage/v1",
            "EDOC_STORAGE_ACCESS_MODE": "server-signed-url",
            "EDOC_FILE_ENCRYPTION_KEY": "file-key",
            "EDOC_SCAN_ENGINE": "ClamAV-compatible",
            "EDOC_AV_PROVIDER": "ClamAV-compatible",
            "EDOC_AV_ENDPOINT": "tcp://clamav.internal:3310",
            "EDOC_AV_API_KEY": "av-key",
            "EDOC_MAX_FILE_SIZE_MB": "100",
            "EDOC_ALLOWED_MIME_TYPES": "application/pdf",
            "EDOC_SIGNATURE_PROVIDER": "formal-provider",
            "EDOC_SIGNATURE_API_URL": "https://signature.example/api",
            "EDOC_SIGNATURE_API_KEY": "signature-key",
            "EDOC_SIGNATURE_KEY_ID": "hsm-key",
            "EDOC_HSM_PROVIDER": "hsm",
            "EDOC_CERT_TRUST_STORE": "trust-store",
            "EDOC_TSA_URL": "https://tsa.example/timestamp",
            "EDOC_TSA_API_KEY": "tsa-key",
            "EDOC_OCSP_RESPONDER_URL": "https://ocsp.example",
            "EDOC_CRL_DISTRIBUTION_URL": "https://crl.example/list",
            "EDOC_DISABLE_DEMO_ACCOUNTS": "true",
            "MONITORING_WEBHOOK_URL": "https://monitor.example/webhook",
            "SENTRY_DSN": "https://sentry.example/1",
        }
        patcher = mock.patch.dict(os.environ, values, clear=False)
        patcher.start()
        backend.DEPLOYMENT_ENV = "production"
        backend.USE_SUPABASE = True
        backend.SUPABASE_URL = values["SUPABASE_URL"]
        backend.SUPABASE_SERVICE_ROLE_KEY = values["SUPABASE_SERVICE_ROLE_KEY"]
        backend.EDOC_STORAGE_PROVIDER = "supabase"
        backend.EDOC_STORAGE_BUCKET = "edoc-private"
        backend.EDOC_OBJECT_STORAGE_URL = values["EDOC_OBJECT_STORAGE_URL"]
        backend.EDOC_STORAGE_ACCESS_MODE = "server-signed-url"
        backend.EDOC_FILE_ENCRYPTION_ENABLED = True
        backend.EDOC_SCAN_ENGINE = "ClamAV-compatible"
        backend.EDOC_AV_PROVIDER = "ClamAV-compatible"
        backend.EDOC_AV_ENDPOINT = values["EDOC_AV_ENDPOINT"]
        backend.EDOC_MAX_FILE_SIZE_MB = 100
        backend.EDOC_ALLOWED_MIME_TYPES = "application/pdf"
        backend.EDOC_SIGNATURE_PROVIDER = "formal-provider"
        backend.EDOC_SIGNATURE_API_URL = values["EDOC_SIGNATURE_API_URL"]
        backend.EDOC_SIGNATURE_API_KEY = values["EDOC_SIGNATURE_API_KEY"]
        backend.EDOC_SIGNATURE_KEY_ID = values["EDOC_SIGNATURE_KEY_ID"]
        backend.EDOC_HSM_PROVIDER = "hsm"
        backend.EDOC_CERT_TRUST_STORE = "trust-store"
        backend.EDOC_TSA_URL = values["EDOC_TSA_URL"]
        backend.EDOC_TSA_API_KEY = values["EDOC_TSA_API_KEY"]
        backend.EDOC_OCSP_RESPONDER_URL = values["EDOC_OCSP_RESPONDER_URL"]
        backend.EDOC_CRL_DISTRIBUTION_URL = values["EDOC_CRL_DISTRIBUTION_URL"]
        return patcher

    def test_production_missing_formal_services_is_no_go(self) -> None:
        with mock.patch.dict(os.environ, {"EDOC_DEPLOYMENT_ENV": "production"}, clear=True):
            backend.DEPLOYMENT_ENV = "production"
            backend.USE_SUPABASE = False
            backend.EDOC_EXCHANGE_PROVIDER = "mock"

            audit = backend.go_live_audit()

        self.assertEqual(audit["decision"], "NO_GO")
        self.assertFalse(audit["formalGo"])
        self.assertTrue(audit["internalPilotAllowed"])
        self.assertTrue(any("Supabase" in item for item in audit["formalBlockers"]))
        self.assertTrue(any(item["key"] == "database" and item["status"] == "fail" for item in audit["categories"]))

    def test_complete_readiness_still_blocks_formal_exchange_when_provider_is_mock(self) -> None:
        patcher = self.apply_formal_env()
        try:
            backend.EDOC_EXCHANGE_PROVIDER = "mock"

            audit = backend.go_live_audit()
        finally:
            patcher.stop()

        self.assertEqual(audit["decision"], "NO_GO")
        self.assertTrue(audit["readiness"]["ready"])
        self.assertFalse(audit["formalGo"])
        self.assertTrue(audit["internalPilotAllowed"])
        self.assertTrue(any(item["key"] == "exchange" and item["status"] == "fail" for item in audit["categories"]))

    def test_demo_password_is_blocked_when_production_policy_is_enabled(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(backend.SCHEMA)
        backend.seed(conn)
        backend.seed_auth(conn)
        backend.ensure_allowed_edoc_users(conn)
        try:
            with mock.patch.dict(os.environ, {"EDOC_DISABLE_DEMO_ACCOUNTS": "true"}, clear=False):
                backend.DEPLOYMENT_ENV = "production"
                session, status = backend.authenticate_local(
                    conn,
                    {"email": "edoc@suiyuecare.com", "password": "demo1234", "provider": "unittest"},
                    "127.0.0.1",
                    "unittest",
                )
        finally:
            conn.close()

        self.assertEqual(status, 403)
        self.assertEqual(session["error"], "demo_login_disabled")


if __name__ == "__main__":
    unittest.main()
