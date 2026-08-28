import unittest
from unittest import mock

import backend


class EditorRuntimeMutationGateTestCase(unittest.TestCase):
    def test_gate_is_noop_outside_production(self):
        with (
            mock.patch.object(backend, "is_production", return_value=False),
            mock.patch.object(backend, "production_runtime_dependency_readiness") as probe,
        ):
            backend.require_production_editor_runtime_ready()

        probe.assert_not_called()

    def test_gate_returns_503_business_code_when_runtime_is_incomplete(self):
        with (
            mock.patch.object(backend, "is_production", return_value=True),
            mock.patch.object(
                backend,
                "production_runtime_dependency_readiness",
                return_value={
                    "ready": False,
                    "errorCodes": ["database_required_editor_table_missing"],
                },
            ),
        ):
            with self.assertRaisesRegex(ValueError, "^editor_runtime_maintenance$"):
                backend.require_production_editor_runtime_ready()

        self.assertEqual(
            backend.api_value_error_status("editor_runtime_maintenance"),
            503,
        )

    def test_new_editor_draft_is_rejected_before_identity_or_database_write(self):
        with (
            mock.patch.object(
                backend,
                "require_production_editor_runtime_ready",
                side_effect=ValueError("editor_runtime_maintenance"),
            ) as gate,
            mock.patch.object(backend, "supabase_official_session_user") as identity,
            mock.patch.object(backend, "supabase_insert") as insert,
        ):
            with self.assertRaisesRegex(ValueError, "^editor_runtime_maintenance$"):
                backend.supabase_create_official_editor_draft({}, None)

        gate.assert_called_once_with()
        identity.assert_not_called()
        insert.assert_not_called()

    def test_upload_intent_is_rejected_before_asset_or_capability_creation(self):
        with (
            mock.patch.object(
                backend,
                "require_production_editor_runtime_ready",
                side_effect=ValueError("editor_runtime_maintenance"),
            ) as gate,
            mock.patch.object(backend, "supabase_official_document_row") as document,
            mock.patch.object(backend, "_supabase_create_signed_upload_token") as token,
        ):
            with self.assertRaisesRegex(ValueError, "^editor_runtime_maintenance$"):
                backend.supabase_create_official_editor_upload_intent(
                    "OD-DEIDENTIFIED",
                    {},
                    None,
                )

        gate.assert_called_once_with()
        document.assert_not_called()
        token.assert_not_called()

    def test_finalize_and_preflight_are_rejected_before_document_reads(self):
        for function, args in (
            (
                backend.supabase_finalize_official_editor_upload,
                ("OD-DEIDENTIFIED", "ASSET-DEIDENTIFIED", {}, None),
            ),
            (
                backend.supabase_preflight_official_editor,
                ("OD-DEIDENTIFIED", {}, None),
            ),
        ):
            with (
                self.subTest(function=function.__name__),
                mock.patch.object(
                    backend,
                    "require_production_editor_runtime_ready",
                    side_effect=ValueError("editor_runtime_maintenance"),
                ) as gate,
                mock.patch.object(backend, "supabase_official_document_row") as document,
            ):
                with self.assertRaisesRegex(ValueError, "^editor_runtime_maintenance$"):
                    function(*args)

            gate.assert_called_once_with()
            document.assert_not_called()


if __name__ == "__main__":
    unittest.main()
