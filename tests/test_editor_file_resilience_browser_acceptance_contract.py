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


if __name__ == "__main__":
    unittest.main()
