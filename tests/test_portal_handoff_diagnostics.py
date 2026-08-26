from __future__ import annotations

import io
import unittest
import urllib.parse
from unittest import mock
from pathlib import Path

import backend


ROOT = Path(__file__).resolve().parents[1]


class PortalHandoffDiagnosticsTestCase(unittest.TestCase):
    @staticmethod
    def form_handler(fields: list[tuple[str, str]]) -> backend.Handler:
        raw = urllib.parse.urlencode(fields).encode("utf-8")
        handler = object.__new__(backend.Handler)
        handler.headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Content-Length": str(len(raw)),
        }
        handler.rfile = io.BytesIO(raw)
        return handler

    def test_handoff_form_accepts_current_compact_token(self) -> None:
        handler = self.form_handler([("token", "encoded.signature")])

        self.assertEqual(
            handler.read_form_urlencoded(),
            {"token": "encoded.signature"},
        )

    def test_handoff_form_accepts_legacy_signed_pair_during_rollout(self) -> None:
        handler = self.form_handler([
            ("payload", "encoded"),
            ("signature", "signature"),
        ])

        self.assertEqual(
            handler.read_form_urlencoded(),
            {"payload": "encoded", "signature": "signature"},
        )

    def test_handoff_form_rejects_mixed_partial_duplicate_or_extra_fields(self) -> None:
        invalid_forms = [
            [("payload", "encoded")],
            [("token", "encoded.signature"), ("payload", "encoded"), ("signature", "signature")],
            [("token", "first"), ("token", "second")],
            [("token", "encoded.signature"), ("email", "member@example.invalid")],
        ]

        for fields in invalid_forms:
            with self.subTest(fields=fields):
                with self.assertRaisesRegex(ValueError, "invalid_handoff_form"):
                    self.form_handler(fields).read_form_urlencoded()

    def test_diagnostic_code_allows_only_machine_codes(self) -> None:
        self.assertEqual(
            backend.Handler.safe_handoff_diagnostic_code("Finance_Identity_Denied"),
            "finance_identity_denied",
        )
        self.assertEqual(
            backend.Handler.safe_handoff_diagnostic_code("email=user@example.com"),
            "unknown",
        )
        self.assertEqual(
            backend.Handler.safe_handoff_diagnostic_code("payload.signature"),
            "unknown",
        )

    def test_failure_log_contains_only_code_and_status(self) -> None:
        handler = object.__new__(backend.Handler)
        with mock.patch.object(handler, "log_error") as log_error:
            handler.log_handoff_failure("invalid_signature", 403)

        log_error.assert_called_once_with(
            "portal_handoff_failed code=%s status=%d",
            "invalid_signature",
            403,
        )

    def test_missing_or_stale_visible_marker_probes_http_only_handoff_before_redirect(self) -> None:
        bootstrap = (ROOT / "entry-bootstrap.js").read_text(encoding="utf-8")
        app = (ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn("window.__edocProbeHttpOnlyHandoff = true", bootstrap)
        self.assertNotIn('loginUrl.searchParams.set("module", "edoc")', bootstrap)
        self.assertIn("hasVisibleMarker || window.__edocProbeHttpOnlyHandoff === true", app)
        self.assertIn(
            'if (error?.status === 401 && error?.code === "handoff_session_missing")',
            app,
        )
        self.assertNotIn(
            '!hasVisibleMarker && error?.status === 401 && error?.code === "handoff_session_missing"',
            app,
        )
        self.assertIn("return null;", app)

    def test_transient_handoff_and_session_failures_retry_without_discarding_credentials(self) -> None:
        app = (ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn("async function backendAuthRequestWithTransientRetry", app)
        self.assertIn("const retryDelaysMs = [350, 900];", app)
        self.assertIn("error.retryable = data.retryable === true;", app)
        self.assertIn("if (isRetryableAuthError(error)) shouldClearVisibleMarker = false;", app)
        self.assertIn("if (shouldClearVisibleMarker) clearPostedHandoffMarker();", app)

        resume_start = app.index("async function tryResumePlatformSession()")
        resume_end = app.index("\nfunction renderQueueRows()", resume_start)
        resume_source = app[resume_start:resume_end]
        transient_branch = resume_source.index("if (isRetryableAuthError(error))")
        discard_session = resume_source.index("localStorage.removeItem(authStorageKey);", transient_branch)
        self.assertLess(
            transient_branch,
            discard_session,
            "retryable Finance outages must be handled before the valid local session can be discarded",
        )
        self.assertIn('returnToLoggingPortalModulePicker("sso_unavailable", "replace")', resume_source)


if __name__ == "__main__":
    unittest.main()
