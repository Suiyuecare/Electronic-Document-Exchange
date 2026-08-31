import unittest

import backend


class SafeRuntimeDiagnosticTests(unittest.TestCase):
    def test_retains_machine_codes_without_response_content(self) -> None:
        self.assertEqual(
            backend.safe_runtime_diagnostic_code(RuntimeError("finance_identity_revision_conflict")),
            "finance_identity_revision_conflict",
        )
        self.assertEqual(
            backend.safe_runtime_diagnostic_code(RuntimeError('Supabase 404: {"code":"PGRST202","message":"private data"}')),
            "PGRST202",
        )
        self.assertEqual(
            backend.safe_runtime_diagnostic_code(RuntimeError('Supabase 409: {"code":"23505","detail":"private data"}')),
            "postgres_23505",
        )

    def test_falls_back_to_exception_type_only(self) -> None:
        code = backend.safe_runtime_diagnostic_code(RuntimeError("email=user@example.com"))
        self.assertEqual(code, "runtime_error")
        self.assertNotIn("example", code)


if __name__ == "__main__":
    unittest.main()
