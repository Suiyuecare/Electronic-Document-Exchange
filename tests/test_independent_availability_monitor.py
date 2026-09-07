import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError

from scripts.independent_availability_monitor import check_availability, probe, save_state, transition, validate_base_url


class IndependentMonitorTests(unittest.TestCase):
    def test_repeated_outage_only_alerts_once_and_recovery_resets(self):
        first = transition({}, False, 100)
        self.assertTrue(first["alert"])
        second = transition(first, False, 200)
        self.assertFalse(second["alert"])
        recovery = transition(second, True, 300)
        self.assertTrue(recovery["recovered"])
        self.assertTrue(transition(recovery, False, 400)["alert"])

    def test_stale_or_future_cache_cannot_hide_outage(self):
        for previous in [{}, {"schemaVersion": 1, "checkedAt": 900000, "status": "outage"},
                         {"schemaVersion": 1, "checkedAt": 1, "status": "outage"}]:
            self.assertTrue(transition(previous, False, 500000)["alert"])

    def test_transient_failure_then_two_successful_checks_recovers(self):
        results = iter([False, True, True, True, True, True])
        healthy, attempts = check_availability("https://example.invalid", lambda *_: {"ok": next(results)}, lambda _: None)
        self.assertTrue(healthy)
        self.assertEqual(len(attempts), 3)

    def test_one_success_does_not_clear_an_outage(self):
        results = iter([False, False, False, False, True, True])
        healthy, _ = check_availability("https://example.invalid", lambda *_: {"ok": next(results)}, lambda _: None)
        self.assertFalse(healthy)

    def test_alternating_checks_do_not_invent_an_outage_or_recovery(self):
        for pairs in [(True, False, True), (False, True, False)]:
            results = iter(value for pair in pairs for value in (pair, pair))
            observation, _ = check_availability("https://example.invalid", lambda *_: {"ok": next(results)}, lambda _: None)
            self.assertIsNone(observation)
            for old_status in ["healthy", "outage"]:
                previous = {"schemaVersion": 1, "checkedAt": 90, "status": old_status}
                state = transition(previous, observation, 100)
                self.assertEqual(state["status"], old_status)
                self.assertFalse(state["alert"])
                self.assertFalse(state["recovered"])

    def test_redirect_and_response_text_not_leaked(self):
        opener = mock.Mock()
        opener.open.side_effect = HTTPError("https://secret.invalid", 302, "person@example.test", {}, None)
        data = probe("https://example.invalid", "/api/readyz", opener)
        self.assertFalse(data["ok"])
        self.assertNotIn("secret", json.dumps(data))
        self.assertNotIn("person", json.dumps(data))

    def test_ready_endpoint_must_explicitly_be_ready(self):
        for payload, expected in [(b'{"ok":true}', False), (b'{"ok":true,"ready":true}', True), (b'<html>sign in</html>', False)]:
            response = mock.MagicMock(status=200)
            response.__enter__.return_value = response
            response.read.return_value = payload
            opener = mock.Mock()
            opener.open.return_value = response
            self.assertEqual(probe("https://example.invalid", "/api/readyz", opener)["ok"], expected)

    def test_url_is_https_and_cannot_contain_secret_query(self):
        for value in ["http://example.invalid", "https://u:secret@example.invalid", "https://example.invalid?a=secret", "https://example.invalid/path"]:
            with self.assertRaises(ValueError):
                validate_base_url(value)

    def test_state_atomic_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = transition({}, True, 100)
            save_state(path, state)
            self.assertEqual(json.loads(path.read_text()), state)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
