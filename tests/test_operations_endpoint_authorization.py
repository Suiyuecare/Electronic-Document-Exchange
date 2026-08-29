from __future__ import annotations

import unittest
from unittest import mock

import backend


class OperationsEndpointAuthorizationTest(unittest.TestCase):
    @staticmethod
    def _handler() -> tuple[backend.Handler, list[tuple[object, int]]]:
        handler = object.__new__(backend.Handler)
        responses: list[tuple[object, int]] = []
        handler.bearer_token = lambda: "isolated-operator-token"
        handler.send_json = lambda payload, status=200, *_headers: responses.append(
            (payload, status)
        )
        return handler, responses

    def test_production_artifact_rejects_missing_session_before_render(self) -> None:
        handler, responses = self._handler()
        artifact_calls: list[bool] = []
        handler.send_production_next_action = lambda: artifact_calls.append(True)
        with (
            mock.patch.object(backend, "USE_SUPABASE", True),
            mock.patch.object(backend, "is_production", return_value=True),
            mock.patch.object(backend, "supabase_current_session", return_value=None),
        ):
            handler.handle_api("GET", "/api/production/next-action", {})

        self.assertEqual(responses, [({"error": "unauthorized"}, 401)])
        self.assertEqual(artifact_calls, [])

    def test_production_artifact_rejects_authenticated_non_operator(self) -> None:
        handler, responses = self._handler()
        artifact_calls: list[bool] = []
        handler.send_production_next_action = lambda: artifact_calls.append(True)
        session = {"user": {"id": "USER-1"}, "permissions": []}
        with (
            mock.patch.object(backend, "USE_SUPABASE", True),
            mock.patch.object(backend, "is_production", return_value=True),
            mock.patch.object(backend, "supabase_current_session", return_value=session),
        ):
            handler.handle_api("GET", "/api/production/next-action", {})

        self.assertEqual(
            responses,
            [
                (
                    {
                        "error": "forbidden",
                        "detail": "operations_maintenance_forbidden",
                    },
                    403,
                )
            ],
        )
        self.assertEqual(artifact_calls, [])

    def test_production_artifact_allows_system_operator(self) -> None:
        handler, responses = self._handler()
        artifact_calls: list[bool] = []
        handler.send_production_next_action = lambda: artifact_calls.append(True)
        session = {
            "user": {"id": "OPS-1"},
            "permissions": ["settings.system_manage"],
        }
        with (
            mock.patch.object(backend, "USE_SUPABASE", True),
            mock.patch.object(backend, "is_production", return_value=True),
            mock.patch.object(backend, "supabase_current_session", return_value=session),
        ):
            handler.handle_api("GET", "/api/production/next-action", {})

        self.assertEqual(responses, [])
        self.assertEqual(artifact_calls, [True])

    def test_sensitive_operational_gets_are_admin_only(self) -> None:
        protected_paths = (
            ["production", "deployment"],
            ["production", "monitoring"],
            ["production", "smoke-test-pdf"],
            ["production", "dispatch-proof-template"],
            ["files", "storage-health"],
            ["certificates", "health"],
            ["schema"],
        )
        for parts in protected_paths:
            with self.subTest(parts=parts):
                self.assertTrue(
                    backend.is_operations_maintenance_endpoint("GET", parts)
                )

    def test_public_health_and_readiness_are_not_misclassified_as_admin_artifacts(self) -> None:
        for parts in (["healthz"], ["readyz"], ["production", "readiness"]):
            with self.subTest(parts=parts):
                self.assertFalse(
                    backend.is_operations_maintenance_endpoint("GET", parts)
                )
                with mock.patch.object(backend, "is_production", return_value=True):
                    self.assertFalse(
                        backend.is_production_operations_artifact_endpoint("GET", parts)
                    )


if __name__ == "__main__":
    unittest.main()
