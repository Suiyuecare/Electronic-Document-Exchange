from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def javascript_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    next_function = source.find("\nfunction ", start + 1)
    next_async_function = source.find("\nasync function ", start + 1)
    candidates = [index for index in (next_function, next_async_function) if index >= 0]
    return source[start:min(candidates) if candidates else len(source)]


class FrontendAuthoritativeWorkflowsContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.audit = (ROOT / "tools" / "audit_authorized_ui.mjs").read_text(encoding="utf-8")

    def test_authenticated_session_clears_seed_records_before_render(self) -> None:
        clearing = javascript_function(self.js, "clearFrontendSeedRecordsForAuthenticatedSession")
        self.assertIn("hasAuthenticatedBackendSession()", clearing)
        self.assertIn("explicitFrontendFixturesEnabled()", clearing)
        for collection in (
            "dispatchDocs",
            "notificationItems",
            "contractRecords",
            "trackingCases",
            "opsApiLogs",
            "opsConfigVersions",
            "opsAuditLog",
        ):
            self.assertIn(collection, clearing)
        self.assertIn("Object.assign(jagentState", clearing)
        self.assertIn('center: "未檢查"', clearing)
        self.assertIn('token: ""', clearing)
        self.assertIn("Object.assign(opsState", clearing)
        apply_user = javascript_function(self.js, "applyAuthUser")
        self.assertIn("clearFrontendSeedRecordsForAuthenticatedSession();", apply_user)

    def test_workflow_readiness_blocks_submit_and_uses_finance_source(self) -> None:
        readiness = javascript_function(self.js, "loadOfficialWorkflowReadiness")
        self.assertIn("/official-documents/workflow-readiness?route_code=", readiness)
        self.assertIn('sourceOfTruth: "finance"', readiness)
        compose_submit = self.js[self.js.index('document.querySelector("#composeForm").addEventListener'):]
        self.assertIn("await loadOfficialWorkflowReadiness", compose_submit)
        uploaded_submit = self.js[self.js.rindex("async function submitUploadedSealApplication") :]
        self.assertIn("await loadOfficialWorkflowReadiness", uploaded_submit)
        self.assertIn("workflowReadinessAllowsSubmit", uploaded_submit)

    def test_inbound_archive_is_draft_then_attachment_then_register(self) -> None:
        archive = javascript_function(self.js, "createInboundArchiveFromForm")
        draft = archive.index('path: "/inbound-documents/drafts"')
        attachment = archive.index("/attachments`")
        register = archive.index('path: "/inbound-documents/register"')
        self.assertLess(draft, attachment)
        self.assertLess(attachment, register)
        self.assertIn("expected_version: draft.version", archive)
        self.assertIn("rememberInboundArchiveDraft", archive)

    def test_dispatch_export_is_a_real_scoped_csv_download(self) -> None:
        export = javascript_function(self.js, "exportFilteredDispatchCsv")
        self.assertIn("filteredDispatchDocs()", export)
        self.assertIn('new Blob(["\\uFEFF", content]', export)
        self.assertIn("anchor.click()", export)
        self.assertIn('addEventListener("click", exportFilteredDispatchCsv)', self.js)

    def test_decision_dialog_has_evidence_gate_and_focus_trap(self) -> None:
        submit = javascript_function(self.js, "submitOfficialDecision")
        self.assertIn("officialDecisionEvidenceComplete()", submit)
        self.assertIn("review_acknowledgements", submit)
        trap = javascript_function(self.js, "trapOfficialDecisionFocus")
        self.assertIn('event.key !== "Tab"', trap)
        self.assertIn("officialDecisionPreviousFocus", javascript_function(self.js, "closeOfficialDecisionDialog"))

    def test_authorized_ui_audit_calls_existing_navigation_function(self) -> None:
        self.assertIn("secondaryRoutesForRole(activeRole())", self.audit)
        self.assertNotIn("moreNavigationRoutesForRole", self.audit)

    def test_ops_health_uses_real_exchange_status_without_fake_jagent_success(self) -> None:
        health = javascript_function(self.js, "runOpsHealthCheck")
        self.assertIn('/exchange/gateway-status', health)
        self.assertIn("exchange.formalConnection", health)
        self.assertIn("exchange.formalExchangeDisabled", health)
        self.assertIn('jagentState.center = formalExchangeReady ? "已連線" : "未啟用"', health)
        self.assertIn('code: formalExchangeReady ? "FORMAL-READY" : "FORMAL-DISABLED"', health)
        self.assertNotIn("Math.random", health)
        self.assertNotIn("tk_", health)
        self.assertNotIn("Token ${tokenTimeLeft()}", health)


if __name__ == "__main__":
    unittest.main()
