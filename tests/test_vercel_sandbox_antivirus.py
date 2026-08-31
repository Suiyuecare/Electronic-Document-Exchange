import hashlib
import importlib.metadata
import inspect
import types
import unittest
from unittest import mock

import vercel_sandbox_antivirus as av


class _Policy:
    @staticmethod
    def custom(value):
        return ("custom", value)

    @staticmethod
    def deny_all():
        return ("deny-all", {})


class _Rule:
    pass


class _Source:
    def __init__(self, *, snapshot_id):
        self.snapshot_id = snapshot_id


class _Resources:
    def __init__(self, *, vcpus):
        self.vcpus = vcpus


class _Process:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


class _Filesystem:
    def __init__(self, owner):
        self.owner = owner

    def write_bytes(self, path, data, mode=None):
        self.owner.events.append(("write", path, data, mode))

    def remove(self, path):
        self.owner.events.append(("remove", path))


class _Sandbox:
    def __init__(self, *, data, scan_process=None, update_process=None, hash_override=""):
        self.data = data
        self.scan_process = scan_process or _Process(0, "")
        self.update_process = update_process or _Process(0, "definitions current")
        self.hash_override = hash_override
        self.events = []
        self.fs = _Filesystem(self)

    def __enter__(self):
        self.events.append(("enter",))
        return self

    def __exit__(self, *_args):
        self.events.append(("destroy",))

    def update_network_policy(self, policy):
        self.events.append(("policy", policy))

    def run_process(self, command, args, **kwargs):
        self.events.append(("run", command, tuple(args), kwargs))
        if command == "freshclam":
            return self.update_process
        if command == "sha256sum":
            digest = self.hash_override or hashlib.sha256(self.data).hexdigest()
            return _Process(0, f"{digest}  {av.SCAN_PATH}\n")
        if command == "clamscan":
            return self.scan_process
        raise AssertionError(command)


def _sdk(sandbox, calls):
    def create_sandbox(**kwargs):
        calls.append(kwargs)
        return sandbox

    return types.SimpleNamespace(
        NetworkPolicy=_Policy,
        NetworkPolicyRule=_Rule,
        SnapshotSource=_Source,
        SandboxResources=_Resources,
        create_sandbox=create_sandbox,
    )


class VercelSandboxAntivirusTestCase(unittest.TestCase):
    snapshot_id = "snap_1234567890abcdefghijklmnop"

    def test_pinned_sdk_exposes_required_public_surface(self):
        sdk = av._load_sdk()

        self.assertEqual(importlib.metadata.version("vercel"), "0.10.0")
        self.assertEqual(importlib.metadata.version("vercel-sandbox"), "0.4.0")
        self.assertTrue(callable(sdk.create_sandbox))
        self.assertTrue(
            {
                "source",
                "execution_time_limit",
                "resources",
                "persistent",
                "network_policy",
                "destroy",
            }.issubset(inspect.signature(sdk.create_sandbox).parameters)
        )
        self.assertEqual(sdk.NetworkPolicy.deny_all().mode, "deny-all")
        self.assertEqual(
            sdk.SnapshotSource(snapshot_id=self.snapshot_id).snapshot_id,
            self.snapshot_id,
        )
        self.assertEqual(sdk.SandboxResources(vcpus=2).vcpus, 2)

    def run_scan(self, payload=b"%PDF clean", **sandbox_kwargs):
        sandbox = _Sandbox(data=payload, **sandbox_kwargs)
        calls = []
        with mock.patch.object(av, "_load_sdk", return_value=_sdk(sandbox, calls)):
            result = av.scan_bytes(
                payload,
                snapshot_id=self.snapshot_id,
                expected_sha256=hashlib.sha256(payload).hexdigest(),
            )
        return result, sandbox, calls

    def test_clean_scan_updates_definitions_denies_egress_then_writes(self):
        result, sandbox, calls = self.run_scan()
        self.assertEqual((result.status, result.signature), ("clean", "ClamAV-Clean"))
        self.assertEqual(calls[0]["persistent"], False)
        self.assertEqual(calls[0]["destroy"], True)
        self.assertEqual(calls[0]["network_policy"][0], "custom")
        commands = [event[:2] for event in sandbox.events if event[0] in {"run", "policy", "write"}]
        self.assertEqual(
            commands,
            [
                ("run", "freshclam"),
                ("policy", ("deny-all", {})),
                ("write", av.SCAN_PATH),
                ("run", "sha256sum"),
                ("run", "clamscan"),
            ],
        )
        write = next(event for event in sandbox.events if event[0] == "write")
        self.assertEqual(write[2], b"%PDF clean")
        self.assertEqual(write[3], 0o600)

    def test_infected_scan_returns_sanitized_signature(self):
        result, _, _ = self.run_scan(
            scan_process=_Process(1, f"{av.SCAN_PATH}: Eicar Test/Signature FOUND\n")
        )
        self.assertEqual(result.status, "infected")
        self.assertEqual(result.signature, "Eicar-Test-Signature")

    def test_definition_update_failure_fails_before_user_bytes_are_written(self):
        sandbox = _Sandbox(data=b"safe", update_process=_Process(2, "network failed"))
        with mock.patch.object(av, "_load_sdk", return_value=_sdk(sandbox, [])):
            with self.assertRaisesRegex(av.SandboxAntivirusScanFailed, "definitions_update_failed"):
                av.scan_bytes(b"safe", snapshot_id=self.snapshot_id)
        self.assertFalse(any(event[0] == "write" for event in sandbox.events))

    def test_remote_hash_mismatch_fails_closed(self):
        with self.assertRaisesRegex(av.SandboxAntivirusScanFailed, "remote_hash_mismatch"):
            self.run_scan(hash_override="0" * 64)

    def test_unknown_clamscan_response_fails_closed(self):
        with self.assertRaisesRegex(av.SandboxAntivirusScanFailed, "clamav_failed"):
            self.run_scan(scan_process=_Process(2, "scanner error"))

    def test_invalid_snapshot_expected_hash_and_size_fail_closed(self):
        with self.assertRaises(av.SandboxAntivirusNotReady):
            av.scan_bytes(b"safe", snapshot_id="not-a-snapshot")
        with self.assertRaisesRegex(av.SandboxAntivirusScanFailed, "hash_mismatch"):
            av.scan_bytes(b"safe", snapshot_id=self.snapshot_id, expected_sha256="0" * 64)
        with self.assertRaisesRegex(av.SandboxAntivirusScanFailed, "payload_too_large"):
            av.scan_bytes(b"12", snapshot_id=self.snapshot_id, max_file_size_bytes=1)


if __name__ == "__main__":
    unittest.main()
