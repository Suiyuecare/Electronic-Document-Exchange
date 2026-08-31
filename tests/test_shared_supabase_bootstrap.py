from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "shared_supabase_bootstrap.py"


def load_tool_module():
    spec = importlib.util.spec_from_file_location("shared_supabase_bootstrap", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("shared_bootstrap_tool_import_failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FAKE_SUPABASE = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
log_path = Path(os.environ["FAKE_SUPABASE_LOG"])
state_path = Path(os.environ["FAKE_SUPABASE_STATE"])
with log_path.open("a", encoding="utf-8") as log_file:
    log_file.write(json.dumps(args) + "\n")

if args == ["--version"]:
    print(os.environ.get("FAKE_SUPABASE_VERSION", "2.105.0"))
    raise SystemExit(0)

if args[:2] == ["db", "query"] and "--file" in args:
    sql_path = Path(args[args.index("--file") + 1])
    sql = sql_path.read_text(encoding="utf-8")
    if sql.endswith("commit;\n"):
        state_path.write_text("committed", encoding="utf-8")
    elif not sql.endswith("rollback;\n"):
        raise SystemExit(90)
    raise SystemExit(0)

if args[:2] == ["db", "query"]:
    sql = args[-1]
    if "public_users" in sql:
        rows = [{
            "public_users": 5,
            "public_employees": 5,
            "public_companies": 3,
            "public_departments": 8,
            "hr_document_objects": 2,
        }]
    elif "edoc_schema_exists" in sql:
        committed = state_path.read_text(encoding="utf-8").strip() == "committed"
        rows = [{
            "edoc_schema_exists": committed,
            "edoc_role_exists": committed,
        }]
    else:
        raise SystemExit(91)
    print(json.dumps({"rows": rows, "rowCount": len(rows)}))
    raise SystemExit(0)

raise SystemExit(92)
'''


class SharedSupabaseBootstrapTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = load_tool_module()

    def test_transform_retargets_objects_but_preserves_public_pseudo_role(self) -> None:
        source = """begin;
create table public.users(id text);
set search_path = pg_catalog, public, private;
select * from public.users where current_user = 'service_role';
revoke all on schema private from public, anon, authenticated;
grant select on public.users to service_role;
select 1 from pg_namespace where nspname = 'public';
commit;
"""
        transformed = self.tool.transform_sql(source)

        self.assertNotIn("begin;", transformed.lower())
        self.assertNotIn("commit;", transformed.lower())
        self.assertIn("create table edoc.users", transformed)
        self.assertIn("search_path = pg_catalog, edoc, edoc_private", transformed)
        self.assertIn("current_user = 'edoc_backend'", transformed)
        self.assertIn(
            "revoke all on schema edoc_private from public, anon, authenticated",
            transformed,
        )
        self.assertIn("grant select on edoc.users to edoc_backend", transformed)
        self.assertIn("nspname = 'edoc'", transformed)

    def test_bundle_is_atomic_manifest_complete_and_rollback_by_default(self) -> None:
        bundle = self.tool.render_bundle()
        manifest = self.tool.load_manifest()

        self.assertEqual(bundle.lower().count("\nbegin;\n"), 1)
        self.assertTrue(bundle.endswith("rollback;\n"))
        self.assertNotIn("public.users(id", bundle)
        self.assertIn("create role edoc_backend", bundle)
        self.assertIn("create schema edoc authorization postgres", bundle)
        self.assertIn(
            "set local search_path = edoc, edoc_private, extensions, pg_catalog",
            bundle,
        )
        self.assertIn("edoc.edoc_runtime_identity()", bundle)
        self.assertIn("hr-documents is unreachable", bundle)
        self.assertIn("to edoc_backend", bundle)
        self.assertIn("from public, anon, authenticated, service_role", bundle)
        self.assertEqual(
            bundle.count("-- BEGIN TRANSFORMED SOURCE:"),
            len(manifest) + 1,
        )
        for name in manifest:
            self.assertIn(f"-- BEGIN TRANSFORMED SOURCE: {name}", bundle)

    def test_commit_bundle_requires_explicit_render_choice(self) -> None:
        bundle = self.tool.render_bundle(commit=True)
        self.assertTrue(bundle.endswith("commit;\n"))
        self.assertFalse(bundle.endswith("rollback;\n"))

    def test_fresh_replay_guards_ignore_unrelated_hr_auth_and_storage(self) -> None:
        source = """if exists (select 1 from auth.users) then
      v_exact_fresh_sentinel := false;
    end if;
    if exists (select 1 from storage.objects) then
      v_exact_fresh_sentinel := false;
    end if;
"""
        transformed = self.tool.transform_sql(source)
        self.assertIn("join edoc.users linked_user", transformed)
        self.assertIn(
            "where bucket_id in ('edoc-private', 'edoc-seal-vault')",
            transformed,
        )
        self.assertNotIn("exists (select 1 from auth.users)", transformed)
        self.assertNotIn("exists (select 1 from storage.objects)", transformed)

    def test_manifest_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="edoc-shared-manifest-") as temp:
            base = Path(temp)
            migrations = base / "migrations"
            migrations.mkdir()
            (migrations / "20260101000000_one.sql").write_text(
                "select 1;\n",
                encoding="utf-8",
            )
            manifest = base / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "directory": "supabase/migrations",
                        "migrations": ["20260101000000_missing.sql"],
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                self.tool,
                "MIGRATIONS_DIR",
                migrations,
            ), mock.patch.object(self.tool, "MANIFEST_PATH", manifest):
                with self.assertRaisesRegex(
                    self.tool.SharedBootstrapError,
                    "shared_manifest_repository_mismatch",
                ):
                    self.tool.load_manifest()

    def test_render_output_must_stay_inside_repository(self) -> None:
        with tempfile.TemporaryDirectory(prefix="edoc-shared-output-") as temp:
            with self.assertRaisesRegex(
                self.tool.SharedBootstrapError,
                "shared_output_must_be_in_repository",
            ):
                self.tool._write_output(Path(temp) / "bundle.sql", "select 1;\n")


class SharedSupabaseBootstrapApplyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = load_tool_module()
        self.temp = tempfile.TemporaryDirectory(prefix="edoc-shared-apply-")
        self.root = Path(self.temp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.fake_cli = self.bin_dir / "supabase"
        self.fake_cli.write_text(FAKE_SUPABASE, encoding="utf-8")
        self.fake_cli.chmod(0o755)
        self.log_path = self.root / "commands.jsonl"
        self.state_path = self.root / "state.txt"
        self.state_path.write_text("fresh", encoding="utf-8")
        self.linked_ref = self.root / "project-ref"
        self.linked_ref.write_text("abcdefghijklmnopqrst\n", encoding="utf-8")
        self.tool.LINKED_REF_PATH = self.linked_ref
        self.environment = mock.patch.dict(
            os.environ,
            {
                "PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "FAKE_SUPABASE_LOG": str(self.log_path),
                "FAKE_SUPABASE_STATE": str(self.state_path),
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temp.cleanup()

    def commands(self) -> list[list[str]]:
        return [
            json.loads(line)
            for line in self.log_path.read_text(encoding="utf-8").splitlines()
        ]

    def test_default_apply_is_rollback_and_preserves_hr_fingerprint(self) -> None:
        self.tool.apply_bundle(
            "abcdefghijklmnopqrst",
            commit=False,
            acknowledge=False,
        )
        self.assertEqual(self.state_path.read_text(encoding="utf-8"), "fresh")
        commands = self.commands()
        self.assertEqual(commands[0], ["--version"])
        self.assertTrue(any("--file" in command for command in commands))
        self.assertGreaterEqual(
            sum("public_users" in command[-1] for command in commands if command),
            2,
        )

    def test_live_commit_requires_acknowledgement_before_sql(self) -> None:
        with self.assertRaisesRegex(
            self.tool.SharedBootstrapError,
            "shared_commit_acknowledgement_required",
        ):
            self.tool.apply_bundle(
                "abcdefghijklmnopqrst",
                commit=True,
                acknowledge=False,
            )
        self.assertFalse(any("--file" in command for command in self.commands()))

    def test_acknowledged_commit_records_namespace_state(self) -> None:
        self.tool.apply_bundle(
            "abcdefghijklmnopqrst",
            commit=True,
            acknowledge=True,
        )
        self.assertEqual(self.state_path.read_text(encoding="utf-8"), "committed")

    def test_cli_and_linked_project_must_match(self) -> None:
        with self.assertRaisesRegex(
            self.tool.SharedBootstrapError,
            "shared_linked_project_ref_mismatch",
        ):
            self.tool.apply_bundle(
                "zyxwvutsrqponmlkjihg",
                commit=False,
                acknowledge=False,
            )
        self.assertFalse(any("--file" in command for command in self.commands()))


if __name__ == "__main__":
    unittest.main()
