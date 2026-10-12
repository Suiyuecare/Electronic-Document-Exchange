"""Reproducible isolated role/workflow/PDF acceptance; never a launch attestation.

Only loopback network connections are allowed during execution. Tests use
deidentified synthetic Finance identities and temporary databases/storage. A
passing report cannot attest real employee SSO, physical-device usability,
hosted Storage, external notifications, formal exchange or restore readiness.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
import importlib
import hashlib
import io
import ipaddress
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Explicit classes avoid inherited/imported fixtures being misreported as new
# coverage. Terminal decisions select only methods declared by that subclass.
GROUPS = {
    "six_role_http": ("tests.test_six_role_complete_flow.SixRoleCompleteHttpFlowTest",),
    "inbound_dispatch": ("tests.test_complete_inbound_dispatch_flow.CompleteInboundDispatchFlowTest",),
    "workflow_actions": ("tests.test_configurable_official_workflow.ConfigurableOfficialWorkflowTest",),
    "terminal_decline": ("tests.test_terminal_official_decline.TerminalOfficialDeclineTest",),
    "general_seals": ("tests.test_general_document_seal_workflow.GeneralDocumentSealWorkflowTest",),
    "compose_large_small": ("tests.test_compose_multiseal.ComposeMultiSealBackendTest",),
    "transparent_top_layer": ("tests.test_seal_front_regression.SealFrontRegressionTest",),
    "a4_conversion": ("tests.test_editor_a4_conversion.EditorA4GeometryTests", "tests.test_editor_a4_conversion.EditorA4LocalFlowTests", "tests.test_editor_a4_conversion.EditorA4SupabaseContractTests"),
    "terminal_dispatch": ("tests.test_dispatch_terminal_api_guards.DispatchTerminalApiGuardsTest",),
    "handover_default_off": ("tests.test_handover_feature_gate.HandoverFeatureGateTest",),
    "handover_policy": ("tests.test_official_handover_policy.HandoverPolicyTest",),
    "handover_forward": ("tests.test_official_handover_shared_forward.HandoverForwardContractTest",),
}
HANDOVER_GROUPS = {
    "handover_enabled_local": ("tests.test_official_handover_store.HandoverStoreTest", "tests.test_official_handover_store.HandoverExistingFileWorkflowTest", "tests.test_official_handover_service.HandoverServiceTest", "tests.test_official_handover_followup.FollowupAuthorizationTest"),
}


@contextmanager
def loopback_only():
    original = socket.socket.connect
    original_ex = socket.socket.connect_ex
    original_sendto = socket.socket.sendto
    original_getaddrinfo = socket.getaddrinfo
    def permitted(address):
        if isinstance(address, str):  # Local Unix-domain sockets.
            return
        try:
            if address[0] == "localhost" or ipaddress.ip_address(address[0]).is_loopback:
                return
        except (ValueError, TypeError, IndexError):
            pass
        raise PermissionError("acceptance_external_network_forbidden")
    def connect(sock, address):
        permitted(address); return original(sock, address)
    def connect_ex(sock, address):
        permitted(address); return original_ex(sock, address)
    def sendto(sock, data, *args):
        # UDP/DNS traffic must not bypass the TCP connection guard.
        permitted(args[-1]); return original_sendto(sock, data, *args)
    def getaddrinfo(host, port, *args, **kwargs):
        # Reject a hostname before resolution; even a rejected later TCP
        # connection must not initiate an external DNS lookup.
        permitted((host, port))
        return original_getaddrinfo(host, port, *args, **kwargs)
    with mock.patch.object(socket.socket, "connect", connect), mock.patch.object(socket.socket, "connect_ex", connect_ex), \
            mock.patch.object(socket.socket, "sendto", sendto), mock.patch.object(socket, "getaddrinfo", getaddrinfo):
        yield


def suite_for(group, paths):
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in paths:
        if group == "terminal_decline":
            module_name, class_name = name.rsplit(".", 1)
            cls = getattr(importlib.import_module(module_name), class_name)
            for method, value in sorted(cls.__dict__.items()):
                if method.startswith("test_") and callable(value):
                    suite.addTest(cls(method))
        else:
            suite.addTests(loader.loadTestsFromName(name))
    return suite


def source_digest():
    names = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                           text=True, capture_output=True, check=True).stdout.splitlines()
    digest = hashlib.sha256()
    for name in sorted(set(names)):
        path = ROOT / name
        if path.suffix not in {".py", ".js", ".css", ".html", ".json", ".sql"} or path.is_symlink() or not path.is_file():
            continue
        digest.update(name.encode()); digest.update(b"\0"); digest.update(path.read_bytes()); digest.update(b"\0")
    return digest.hexdigest()


def collect(groups):
    report = {"schema_version": 1, "scope": "isolated_synthetic_functional_acceptance",
              "recorded_at": datetime.now(timezone.utc).isoformat(), "groups": [],
              "real_human_sso_verified": False, "physical_devices_verified": False,
              "hosted_storage_verified": False, "external_notification_delivery_verified": False,
              "government_exchange": "DISABLED", "production_accounts_changed": False,
              "promotion_authorized": False}
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    report["base_commit"] = head
    report["working_tree_has_candidate_changes"] = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip())
    report["source_sha256_before"] = source_digest()
    with loopback_only(), redirect_stdout(io.StringIO()):
        for group, paths in groups.items():
            start = time.monotonic()
            result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite_for(group, paths))
            row = {"id": group, "tests_run": result.testsRun, "failures": len(result.failures),
                   "errors": len(result.errors), "skips": len(result.skipped),
                   "duration_ms": round((time.monotonic() - start)*1000, 2),
                   "passed": result.wasSuccessful() and result.testsRun > 0 and not result.skipped,
                   "failed_test_ids": [test.id() for test, _ in result.failures + result.errors],
                   "error_code": "isolated_test_failed" if result.failures or result.errors else ""}
            report["groups"].append(row)
            print(json.dumps(row, ensure_ascii=False), file=sys.stderr, flush=True)
    if "six_role_http" in groups:
        from tests.test_six_role_complete_flow import SixRoleCompleteHttpFlowTest
        report["six_role_flow"] = SixRoleCompleteHttpFlowTest.last_report
    report["source_sha256_after"] = source_digest()
    report["source_changed_during_acceptance"] = report["source_sha256_before"] != report["source_sha256_after"]
    report["isolated_scope_passed"] = bool(report["groups"]) and all(row["passed"] for row in report["groups"]) and not report["source_changed_during_acceptance"]
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", action="append", choices=sorted({**GROUPS, **HANDOVER_GROUPS}))
    parser.add_argument("--include-handover", action="store_true", help="Exercise locally enabled candidate only; does not enable runtime feature")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    available = {**GROUPS, **(HANDOVER_GROUPS if args.include_handover else {})}
    selected = args.group or list(available)
    if any(name not in available for name in selected):
        parser.error("handover candidate tests require --include-handover")
    report = collect({name: available[name] for name in selected})
    output = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.report:
        if args.report.is_symlink():
            raise ValueError("acceptance_report_symlink_forbidden")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output)
    print(output, end="")
    return 0 if report["isolated_scope_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
