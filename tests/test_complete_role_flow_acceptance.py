"""Acceptance runner cannot turn synthetic results into real launch proof."""
import socket
import unittest
from unittest import mock

from tools import complete_role_flow_acceptance as acceptance


class AcceptanceRunnerBoundaryTest(unittest.TestCase):
    def test_external_connections_are_denied_before_connect_and_loopback_remains_usable(self):
        with acceptance.loopback_only(), socket.socket() as sock:
            with self.assertRaisesRegex(PermissionError, "acceptance_external_network_forbidden"):
                sock.connect(("192.0.2.1", 443))
            with self.assertRaisesRegex(PermissionError, "acceptance_external_network_forbidden"):
                sock.connect_ex(("example.invalid", 443))
            with self.assertRaisesRegex(PermissionError, "acceptance_external_network_forbidden"):
                socket.getaddrinfo("example.invalid", 443)
            self.assertTrue(socket.getaddrinfo("127.0.0.1", 443))
        with acceptance.loopback_only(), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            with self.assertRaisesRegex(PermissionError, "acceptance_external_network_forbidden"):
                sock.sendto(b"synthetic", ("192.0.2.1", 53))
        server = socket.socket(); self.addCleanup(server.close)
        server.bind(("127.0.0.1", 0)); server.listen(1)
        with acceptance.loopback_only(), socket.socket() as client:
            client.connect(server.getsockname())
            peer, _ = server.accept(); peer.close()

    def test_terminal_group_counts_only_four_declared_decisions_not_inherited_suites(self):
        suite = acceptance.suite_for("terminal_decline", acceptance.GROUPS["terminal_decline"])
        self.assertEqual(4, suite.countTestCases())

    def test_successful_fixture_report_cannot_attest_human_devices_storage_or_promotion(self):
        with mock.patch.object(acceptance, "source_digest", return_value="a" * 64):
            report = acceptance.collect({"handover_default_off": acceptance.GROUPS["handover_default_off"]})
        self.assertTrue(report["isolated_scope_passed"])
        for field in ("real_human_sso_verified", "physical_devices_verified", "hosted_storage_verified", "external_notification_delivery_verified", "production_accounts_changed", "promotion_authorized"):
            self.assertIs(report[field], False)
        self.assertEqual("DISABLED", report["government_exchange"])


if __name__ == "__main__":
    unittest.main()
