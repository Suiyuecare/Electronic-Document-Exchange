"""Safety/fixture contracts; these are not substitutes for the browser journeys."""
import unittest
from unittest import mock

from tools import editor_race_browser_acceptance as acceptance


class EditorRaceBrowserAcceptanceContractTest(unittest.TestCase):
    def test_only_loopback_http_fixture_origins_are_accepted(self):
        acceptance.require_local_origin("http://127.0.0.1:8000")
        for origin in ("https://example.invalid", "http://localhost:8000", "http://127.0.0.1:8000/api"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                acceptance.require_local_origin(origin)

    def test_git_ref_is_not_interpreted_by_a_shell(self):
        with mock.patch.object(acceptance.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                acceptance.source_at("HEAD; echo unsafe", "app.js")
            run.assert_not_called()

    def test_fetch_delays_keep_the_actual_server_status(self):
        self.assertIn("await window.__raceRealFetch(...args)", acceptance.TRANSPORT)
        self.assertIn("row.status=response.status", acceptance.TRANSPORT)
        self.assertIn("return response", acceptance.TRANSPORT)
        self.assertNotIn("new Response", acceptance.TRANSPORT)

    def test_touch_uses_native_browser_input_and_loopback_cdp_only(self):
        self.assertIn("local_cdp_required", acceptance.NATIVE_TOUCH)
        self.assertIn("Input.dispatchTouchEvent", acceptance.NATIVE_TOUCH)
        self.assertNotIn("new PointerEvent", acceptance.NATIVE_TOUCH)
        self.assertNotIn("setPointerCapture=", acceptance.NATIVE_TOUCH)


if __name__ == "__main__":
    unittest.main()
