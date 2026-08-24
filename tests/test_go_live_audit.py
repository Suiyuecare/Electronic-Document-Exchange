from __future__ import annotations

import json
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
                "EDOC_SEAL_STORAGE_BUCKET",
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
                "PORTAL_HANDOFF_SECRET",
                "EDOC_FINANCE_BRIDGE_URL",
                "EDOC_FINANCE_BRIDGE_SECRET",
                "EDOC_FINANCE_BRIDGE_TIMEOUT_SECONDS",
            ]
        }

    def tearDown(self) -> None:
        for name, value in self._constants.items():
            setattr(backend, name, value)

    def apply_formal_env(self) -> mock._patch_dict:
        values = {
            "EDOC_DEPLOYMENT_ENV": "production",
            "EDOC_PUBLIC_BASE_URL": "https://edoc.suiyuecare.com",
            "EDOC_LAUNCH_COMPANY_MODE": "finance_active",
            "EDOC_PDF_EDITOR_V2_COMPANY_MODE": "finance_active",
            "EDOC_PORTAL_HANDOFF_SECRET": "portal-handoff-secret-at-least-32-bytes",
            "EDOC_FINANCE_BRIDGE_URL": "https://finance.example.com/edoc-identity-snapshot",
            "EDOC_FINANCE_BRIDGE_SECRET": "finance-bridge-secret-at-least-32-bytes",
            "EDOC_FINANCE_BRIDGE_TIMEOUT_SECONDS": "3",
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
            "EDOC_SEAL_STORAGE_BUCKET": "edoc-seal-vault",
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
        backend.EDOC_SEAL_STORAGE_BUCKET = "edoc-seal-vault"
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
        backend.PORTAL_HANDOFF_SECRET = values["EDOC_PORTAL_HANDOFF_SECRET"]
        backend.EDOC_FINANCE_BRIDGE_URL = values["EDOC_FINANCE_BRIDGE_URL"]
        backend.EDOC_FINANCE_BRIDGE_SECRET = values["EDOC_FINANCE_BRIDGE_SECRET"]
        backend.EDOC_FINANCE_BRIDGE_TIMEOUT_SECONDS = 3.0
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
        self.assertTrue(any(item["key"] == "exchange" and item["status"] != "pass" for item in audit["categories"]))

    def test_edoc_password_login_is_blocked_in_production(self) -> None:
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
        self.assertEqual(session["error"], "finance_sso_required")

    def test_launch_readiness_exercises_senior_applicants_and_skips_empty_entities(self) -> None:
        self.assertIn("主管", backend.INTERNAL_LAUNCH_APPLICANT_ROLES)
        self.assertIn("主任", backend.INTERNAL_LAUNCH_APPLICANT_ROLES)
        self.assertIn("主任", backend.INTERNAL_LAUNCH_REQUIRED_ROLES)
        companies = [{"id": "CO-EMPTY"}, {"id": "CO-READY"}]
        applicant = {
            "id": "applicant-1",
            "role": "主管",
            "logging_role_key": "section_chief",
            "account_source": "finance",
        }
        actor = {"id": "actor-1", "account_source": "finance"}

        with mock.patch.object(backend, "finance_workflow_step_failure_reason", return_value=""):
            readiness = backend.build_internal_launch_workflow_readiness(
                companies,
                {"CO-READY": [applicant]},
                lambda _step, _applicant, _company: actor,
            )

        self.assertTrue(readiness["ready"])
        self.assertTrue(readiness["applicantReady"])
        self.assertEqual(readiness["companyCount"], 2)
        self.assertEqual(readiness["applicableCompanyCount"], 1)
        self.assertEqual(len(readiness["routeChecks"]), 2)
        empty = next(item for item in readiness["applicantCoverage"] if item["company_id"] == "CO-EMPTY")
        self.assertFalse(empty["applicable"])
        self.assertTrue(empty["ready"])
        self.assertTrue(all("applicant_manager" not in item["steps"] for item in [
            {"steps": [step["step_key"] for step in route["steps"]]}
            for route in readiness["routeChecks"]
        ]))

    def test_supabase_readiness_reports_non_seal_completion_separately(self) -> None:
        role_counts = {
            role: 1
            for role in dict.fromkeys([
                *backend.INTERNAL_LAUNCH_APPLICANT_ROLES,
                *backend.INTERNAL_LAUNCH_REQUIRED_ROLES,
            ])
        }
        workflow = {
            "ready": True,
            "applicantReady": True,
            "applicableCompanyCount": 1,
            "applicantCoverage": [{"company_id": "CO-1", "applicable": True, "ready": True}],
            "routeCodes": ["A", "C"],
            "routeChecks": [{"ready": True}],
            "workflowSteps": [{"ready": True}],
            "blockers": [],
        }
        with (
            mock.patch.object(backend, "supabase_internal_launch_user_counts", return_value=role_counts),
            mock.patch.object(
                backend,
                "supabase_internal_launch_access_readiness",
                return_value={"ready": True, "blockers": [], "warnings": [], "checks": {}},
            ),
            mock.patch.object(
                backend,
                "supabase_scoped_internal_launch_companies",
                return_value=([{"id": "CO-1"}], {"mode": "finance_active"}, [{"id": "CO-1"}]),
            ),
            mock.patch.object(
                backend,
                "supabase_internal_launch_finance_applicants_by_company",
                return_value={"CO-1": [{"id": "applicant-1"}]},
            ),
            mock.patch.object(backend, "build_internal_launch_workflow_readiness", return_value=workflow),
            mock.patch.object(
                backend,
                "supabase_internal_launch_company_seal_checks",
                return_value=([{"company_id": "CO-1"}], ["CO-1 尚未上傳印章"]),
            ),
            mock.patch.object(
                backend,
                "supabase_internal_launch_user_journeys",
                return_value=[{"title": "非印章流程", "ready": True, "missing": []}],
            ),
        ):
            readiness = backend.supabase_internal_launch_data_readiness()

        self.assertFalse(readiness["ready"])
        self.assertTrue(readiness["readyWithoutSealAssets"])
        self.assertFalse(readiness["sealAssetsReady"])
        self.assertEqual(readiness["nonSealBlockers"], [])
        self.assertEqual(readiness["sealBlockers"], ["CO-1 尚未上傳印章"])

    def test_public_login_decision_distinguishes_only_missing_seal_assets(self) -> None:
        readiness = {
            "launchScope": "internal_official",
            "databaseMode": "supabase",
            "ready": False,
            "internalGo": False,
            "missing": [],
            "blockers": ["去識別化公司尚未上傳正式印章"],
            "warnings": [],
            "checks": {
                "supabase": True,
                "privateStorage": True,
                "demoAccountsDisabled": True,
                "formalExchangeDisabled": True,
                "launchData": False,
                "financeBridge": {"configured": True},
                "portalHandoff": {"configured": True},
                "antivirus": {"ready": True},
                "pdfEditorV2CompanyScope": {"configured": True, "coversLaunchScope": True},
            },
            "dataReadiness": {
                "ready": False,
                "readyWithoutSealAssets": True,
                "sealAssetsReady": False,
                "nonSealBlockers": [],
                "sealBlockers": ["去識別化公司尚未上傳正式印章"],
            },
        }
        next_action = json.dumps({"primaryAction": {}}, ensure_ascii=False).encode("utf-8")
        with mock.patch.object(
            backend,
            "production_next_action_artifact",
            return_value={"content": next_action.decode("utf-8")},
        ):
            payload = json.loads(backend.production_login_release_decision_artifact(readiness)["content"])

        self.assertTrue(payload["generalEmployeeLoginAllowed"])
        self.assertTrue(payload["currentState"]["nonSealWorkflowReady"])
        self.assertFalse(payload["currentState"]["sealAssetsReady"])
        self.assertEqual(payload["currentState"]["nonSealBlockerCount"], 0)
        self.assertEqual(payload["currentState"]["sealBlockerCount"], 1)
        codes = {item["code"] for item in payload["operationRestrictions"]}
        self.assertIn("SEAL_ASSETS_NOT_READY", codes)
        self.assertNotIn("WORKFLOW_DATA_NOT_READY", codes)

    def test_public_login_decision_keeps_skipped_data_audit_unknown(self) -> None:
        readiness = {
            "launchScope": "internal_official",
            "databaseMode": "supabase",
            "ready": False,
            "internalGo": False,
            "missing": [],
            "blockers": [],
            "warnings": [],
            "checks": {
                "supabase": True,
                "privateStorage": True,
                "demoAccountsDisabled": True,
                "formalExchangeDisabled": True,
                "launchData": False,
                "financeBridge": {"configured": True},
                "portalHandoff": {"configured": True},
                "antivirus": {"ready": True},
                "pdfEditorV2CompanyScope": {"configured": True, "coversLaunchScope": True},
            },
        }
        next_action = json.dumps({"primaryAction": {}}, ensure_ascii=False).encode("utf-8")
        with mock.patch.object(
            backend,
            "production_next_action_artifact",
            return_value={"content": next_action.decode("utf-8")},
        ):
            payload = json.loads(backend.production_login_release_decision_artifact(readiness)["content"])

        state = payload["currentState"]
        self.assertFalse(state["dataReadinessEvaluated"])
        self.assertIsNone(state["launchData"])
        self.assertIsNone(state["nonSealWorkflowReady"])
        self.assertIsNone(state["sealAssetsReady"])
        self.assertIsNone(state["nonSealBlockerCount"])
        self.assertIsNone(state["sealBlockerCount"])
        codes = {item["code"] for item in payload["operationRestrictions"]}
        self.assertNotIn("WORKFLOW_DATA_NOT_READY", codes)
        self.assertNotIn("SEAL_ASSETS_NOT_READY", codes)


if __name__ == "__main__":
    unittest.main()
