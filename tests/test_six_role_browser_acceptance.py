from __future__ import annotations

import unittest
from unittest import mock
from pathlib import Path
import re

from tests.support.five_account_browser_fixture import BROWSER_ROLES, isolated_browser_session
import tests.test_five_account_http_acceptance as fixture_module
from tools.six_role_browser_acceptance import ROUTES, VIEWPORTS, require_local_origin


class SixRoleBrowserFixtureContractTests(unittest.TestCase):
    def test_interface_font_does_not_block_initial_render_or_change_document_font(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "index.html").read_text()
        js = (root / "app.js").read_text()
        self.assertRegex(html, r'<link id="interfaceFontStylesheet"[^>]+media="print"')
        self.assertIn('if (interfaceFontStylesheet.sheet) applyInterfaceFont();', js)
        self.assertIn('interfaceFontStylesheet.addEventListener("load", applyInterfaceFont, { once: true });', js)
        self.assertNotRegex(html, r'id="interfaceFontStylesheet"[^>]*onload=')
        for asset in ("entry-bootstrap.js", "app.js", "styles.css"):
            self.assertIn(asset + "?v=20260908-launch-six-items-r1", html)
        self.assertIn("edukai", js.lower())

    def test_mobile_header_touch_targets_are_at_least_44px(self):
        css = (Path(__file__).resolve().parents[1] / "styles.css").read_text()
        for selector in (".mobile-menu-button", ".mobile-drawer-close", ".topbar-notification-button"):
            rules = re.findall(re.escape(selector) + r"\s*\{([^}]+)\}", css)
            self.assertTrue(any(re.search(r"(?<!-)width:\s*44px", rule) and re.search(r"(?<!-)height:\s*44px", rule) for rule in rules), selector)

    def test_six_roles_and_six_existing_routes_are_explicit(self):
        self.assertEqual(len(set(BROWSER_ROLES)), 6)
        self.assertEqual(ROUTES, ("dashboard", "compose", "electronicSeal", "approvalLog", "inbound", "settings"))
        self.assertEqual(VIEWPORTS, {"desktop": (1440, 1000), "mobile": (390, 844)})

    def test_only_new_loopback_origin_is_accepted(self):
        require_local_origin("http://127.0.0.1:54321")
        for value in ("https://edoc.example.test", "https://127.0.0.1:1234", "http://127.0.0.1", "http://127.0.0.1:1234/path", "http://127.0.0.1.attacker.test:1234"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                require_local_origin(value)

    def test_fixture_sessions_never_call_portal_handoff(self):
        fixture = fixture_module.FiveAccountHttpAcceptanceTest
        fixture.setUpClass()
        try:
            with mock.patch.object(fixture, "_portal_session", side_effect=AssertionError("must_not_self_sign")):
                seen = set()
                for role in BROWSER_ROLES:
                    session = isolated_browser_session(fixture, role)
                    self.assertNotIn(session["user"]["id"], seen)
                    seen.add(session["user"]["id"])
                    response = fixture._expect_json("GET", "/api/auth/me", 200, token=session["token"])
                    self.assertEqual(response["user"]["id"], session["user"]["id"])
                    self.assertEqual(response["user"]["account_source"], "finance")
                with self.assertRaises(ValueError):
                    isolated_browser_session(fixture, "root")
                with mock.patch.object(fixture, "origin", "https://edoc.example.test"), self.assertRaises(ValueError):
                    isolated_browser_session(fixture, "staff")
        finally:
            fixture.tearDownClass()


if __name__ == "__main__":
    unittest.main()
