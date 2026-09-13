"""Keep the real upload pipeline gate isolated and free of database mocks."""
import ast
import importlib.util
import os
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tests/support/local_supabase_editor_upload_pipeline_gate.py"
SPEC = importlib.util.spec_from_file_location("editor_upload_pipeline_gate", PATH)
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class LocalSupabaseUploadPipelineGateTests(unittest.TestCase):
    def test_hosted_or_ambiguous_origins_are_denied_before_backend_import(self):
        for origin in (
            "https://example.supabase.co", "http://127.0.0.1.evil.invalid:54321",
            "http://localhost:54321/path", "http://localhost:54321?token=x",
            "http://localhost:54321#fragment", "http://user@localhost:54321",
            "http://localhost@evil.invalid:54321", "",
        ):
            with self.subTest(origin=origin), mock.patch.dict(os.environ, {
                "EDOC_LOCAL_SUPABASE_URL": origin,
                "EDOC_LOCAL_SUPABASE_SERVICE_ROLE_KEY": "synthetic-local",
                "EDOC_LOCAL_SUPABASE_ANON_KEY": "synthetic-anon",
            }):
                with self.assertRaisesRegex(GATE.PipelineGateFailure, "pipeline_gate_loopback_required"):
                    GATE.loopback_configuration()

    def test_local_configuration_rebinds_all_database_and_storage_destinations(self):
        with mock.patch.dict(os.environ, {
            "EDOC_LOCAL_SUPABASE_URL": "http://127.0.0.1:54321",
            "EDOC_LOCAL_SUPABASE_SERVICE_ROLE_KEY": "synthetic-local",
            "EDOC_LOCAL_SUPABASE_ANON_KEY": "synthetic-anon",
            "EDOC_STORAGE_SUPABASE_URL": "https://never-contact.invalid",
            "EDOC_STORAGE_SERVICE_ROLE_KEY": "never-use-this",
            "EDOC_DEPLOYMENT_ENV": "production",
            "EDOC_SUPABASE_SCHEMA": "edoc",
        }):
            self.assertEqual(GATE.loopback_configuration(), "http://127.0.0.1:54321")
            self.assertEqual(os.environ["SUPABASE_URL"], os.environ["EDOC_STORAGE_SUPABASE_URL"])
            self.assertEqual(os.environ["EDOC_OBJECT_STORAGE_URL"], "http://127.0.0.1:54321/storage/v1")
            self.assertEqual(os.environ["EDOC_STORAGE_SERVICE_ROLE_KEY"], "synthetic-local")
            self.assertEqual(os.environ["EDOC_DEPLOYMENT_ENV"], "development")
            self.assertEqual(os.environ["EDOC_SUPABASE_SCHEMA"], "public")

    def test_gate_calls_shipping_pipeline_without_database_or_auth_overrides(self):
        tree = ast.parse(PATH.read_text(encoding="utf-8"))
        calls = {node.func.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and isinstance(node.func.value, ast.Name) and node.func.value.id == "backend"}
        self.assertTrue({"supabase_create_official_editor_upload_intent",
                         "supabase_finalize_official_editor_upload", "supabase_get_official_editor_state",
                         "supabase_storage_download", "supabase_filter_rows"}.issubset(calls))
        assignments = {target.attr for node in ast.walk(tree) if isinstance(node, ast.Assign)
                       for target in node.targets if isinstance(target, ast.Attribute)
                       and isinstance(target.value, ast.Name) and target.value.id == "backend"}
        self.assertEqual(assignments, {"_supabase_storage_endpoint_issue"})
        self.assertNotIn("unittest.mock", PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
