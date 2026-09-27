"""Harness safety only; actual UI journeys remain separately executed."""
import unittest

from tools import editor_file_resilience_browser_acceptance as acceptance


class EditorFileResilienceBrowserAcceptanceContractTest(unittest.TestCase):
    def test_loopback_fixture_only(self):
        acceptance.require_local_origin("http://127.0.0.1:8000")
        for origin in ("https://example.invalid", "http://localhost:8000", "http://127.0.0.1:8000/api"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                acceptance.require_local_origin(origin)

    def test_delay_preserves_actual_fetch_response_and_abort(self):
        self.assertIn("await window.__raceRealFetch(...args)", acceptance.TRANSPORT)
        self.assertIn("row.status=response.status", acceptance.TRANSPORT)
        self.assertIn("return response", acceptance.TRANSPORT)
        self.assertIn("signal?.addEventListener('abort',abort", acceptance.TRANSPORT)
        self.assertIn("signal?.removeEventListener('abort',abort)", acceptance.TRANSPORT)
        self.assertNotIn("new Response", acceptance.TRANSPORT)

    def test_claims_do_not_extend_to_hosted_tus_or_physical_mobile(self):
        source = acceptance.Path(acceptance.__file__).read_text()
        self.assertIn('"local_direct_not_supabase_tus"', source)
        self.assertIn('"physicalMobileVerified": False', source)
        self.assertIn('"scope": "isolated_local_real_ui_http_no_production_mutation"', source)

    def test_preload_failure_is_real_http_and_retry_uses_shipping_user_input(self):
        source = acceptance.Path(acceptance.__file__).read_text()
        self.assertIn('handler.send_response(503)', source)
        self.assertIn('return original_head(handler)', source)
        self.assertIn('self.upload(browser, "failed-preload-recovery")', source)
        self.assertIn('"samePageWithoutReload"', source)
        self.assertNotIn('window.pdfjsLib =', source)
        self.assertNotIn('window.pdfjsLibPromise =', source)


if __name__ == "__main__":
    unittest.main()
