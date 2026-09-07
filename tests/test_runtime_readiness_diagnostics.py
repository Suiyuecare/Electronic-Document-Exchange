import io
import itertools
import json
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest import mock

import backend


class RuntimeReadinessDiagnosticsTestCase(unittest.TestCase):
    probe_functions = {
        "databaseQuery": "_probe_main_supabase_query",
        "databaseRpcs": "_probe_main_supabase_rpcs",
        "privateStorage": "_probe_supabase_private_buckets",
        "storagePublicKeyAffinity": "_probe_supabase_publishable_key_affinity",
        "antivirus": "_probe_antivirus_runtime",
        "sharedProjectIdentity": "_probe_shared_supabase_identity",
    }

    def run_probes(self, *, failed=None, exception=None, logger_error=False):
        stream = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(backend, "is_production", return_value=True))
            stack.enter_context(mock.patch.object(
                backend, "EDOC_STORAGE_SUPABASE_MODE", "shared-project-schema",
            ))
            stack.enter_context(mock.patch.object(
                backend, "_runtime_readiness_probe_timeout_seconds", return_value=1.5,
            ))
            stack.enter_context(mock.patch.object(
                backend.time, "monotonic", side_effect=itertools.count(100, 0.01),
            ))
            network = stack.enter_context(mock.patch.object(
                backend, "_readiness_http_json", side_effect=AssertionError("no live network"),
            ))
            probes = {}
            for name, function in self.probe_functions.items():
                result = failed if name == "databaseQuery" and failed is not None else {
                    "ready": True, "errorCode": "",
                }
                probes[name] = stack.enter_context(mock.patch.object(
                    backend, function, return_value=result,
                    side_effect=exception if name == "databaseQuery" else None,
                ))
            if logger_error:
                stack.enter_context(mock.patch.object(
                    backend, "log_structured", side_effect=RuntimeError("private logger details"),
                ))
            with redirect_stdout(stream):
                result = backend.production_runtime_dependency_readiness()
            for probe in probes.values():
                probe.assert_called_once_with(1.5)
            network.assert_not_called()
        return result, stream.getvalue()

    def test_failure_logs_only_fixed_codes_boolean_and_timings(self):
        failed = {
            "ready": False, "errorCode": "database_query_unavailable",
            "url": "https://private.example/path", "response": "private document text",
            "headers": {"Authorization": "secret-test-credential"},
            "person": "sensitive-person@example.invalid",
        }
        result, output = self.run_probes(failed=failed)
        self.assertFalse(result["ready"])
        self.assertEqual(result["checks"]["databaseQuery"], failed)
        self.assertEqual(len(output.splitlines()), 1)
        event = json.loads(output)
        self.assertEqual(set(event), {
            "level", "message", "time", "ready", "checks", "durationMs", "timeoutMs",
        })
        self.assertEqual(event["message"], "runtime_readiness_failed")
        self.assertFalse(event["ready"])
        self.assertEqual(event["timeoutMs"], 1500)
        self.assertEqual(set(event["checks"]), set(self.probe_functions))
        for check in event["checks"].values():
            self.assertEqual(set(check), {"ready", "errorCode", "durationMs"})
            self.assertIsInstance(check["ready"], bool)
            self.assertGreater(check["durationMs"], 0)
            self.assertGreaterEqual(event["durationMs"], check["durationMs"])
        self.assertEqual(event["checks"]["databaseQuery"]["errorCode"], "database_query_unavailable")
        for sensitive in ("private.example", "private document", "secret-test", "sensitive-person", "Authorization"):
            self.assertNotIn(sensitive, output)

    def test_unknown_codes_are_not_serialized_even_if_they_look_like_codes(self):
        for value in (
            "credential_like_machine_code", "https://private.example?key=secret",
            "person@example.invalid", {"secret": "hidden"}, ["hidden"], None,
        ):
            with self.subTest(code_type=type(value).__name__):
                _, output = self.run_probes(failed={"ready": False, "errorCode": value})
                event = json.loads(output)
                self.assertEqual(event["checks"]["databaseQuery"]["errorCode"], "unknown_probe_failure")
                self.assertNotIn("hidden", output)
                self.assertNotIn("private.example", output)
                self.assertNotIn("credential_like_machine_code", output)

    def test_exception_keeps_existing_probe_failure_code_without_message(self):
        result, output = self.run_probes(exception=TimeoutError("secret-test-credential private.example"))
        self.assertFalse(result["ready"])
        self.assertEqual(result["errorCodes"], ["databaseQuery_probe_failed"])
        self.assertEqual(json.loads(output)["checks"]["databaseQuery"]["errorCode"], "databaseQuery_probe_failed")
        self.assertNotIn("secret-test", output)
        self.assertNotIn("private.example", output)

    def test_logger_failure_does_not_change_readiness(self):
        failed = {"ready": False, "errorCode": "database_query_unavailable"}
        result, output = self.run_probes(failed=failed, logger_error=True)
        self.assertFalse(result["ready"])
        self.assertEqual(result["errorCodes"], ["database_query_unavailable"])
        self.assertEqual(output, "")

    def test_success_is_silent_and_each_call_still_checks_dependencies(self):
        for _ in range(2):
            result, output = self.run_probes()
            self.assertTrue(result["ready"])
            self.assertEqual(output, "")

    def test_diagnostic_helper_drops_unknown_probe_and_invalid_timings(self):
        with mock.patch.object(backend, "log_structured") as logger:
            backend._log_runtime_readiness_failure(
                {"databaseQuery": {"ready": False, "errorCode": "database_query_unavailable"},
                 "private-person@example.invalid": {"ready": False, "errorCode": "secret"}},
                {"databaseQuery": float("nan")}, total_ms=float("inf"), timeout_ms=-1,
            )
        logger.assert_called_once()
        event = logger.call_args.kwargs
        self.assertEqual(set(event["checks"]), {"databaseQuery"})
        self.assertIsNone(event["checks"]["databaseQuery"]["durationMs"])
        self.assertIsNone(event["durationMs"])
        self.assertEqual(event["timeoutMs"], 0)

    def test_public_payload_stays_minimal_on_failure(self):
        result, _ = self.run_probes(failed={"ready": False, "errorCode": "database_query_unavailable"})
        with mock.patch.object(backend, "is_production", return_value=True):
            payload = backend.public_readiness_payload(result)
        self.assertEqual(set(payload), {"ok", "ready", "status", "time"})
        self.assertEqual(payload["status"], "not_ready")

    def test_nonproduction_stays_silent_without_probes(self):
        with mock.patch.object(backend, "is_production", return_value=False), mock.patch.object(
            backend, "log_structured",
        ) as logger, mock.patch.object(backend, "_probe_main_supabase_query") as probe:
            result = backend.production_runtime_dependency_readiness()
        self.assertTrue(result["ready"])
        self.assertFalse(result["checked"])
        logger.assert_not_called()
        probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
