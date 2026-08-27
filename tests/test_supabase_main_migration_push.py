from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "supabase_main_migration_push.py"


def load_tool_module():
    spec = importlib.util.spec_from_file_location("supabase_main_migration_push", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("supabase_push_tool_import_failed")
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

if args[:2] == ["db", "query"]:
    required = {"--linked", "--agent", "yes", "--output-format", "json"}
    if not required.issubset(set(args)):
        raise SystemExit(81)
    if os.environ.get("FAKE_SUPABASE_MALFORMED") == "1":
        print("not-json")
        raise SystemExit(0)
    sql = args[-1]
    state = state_path.read_text(encoding="utf-8").strip()
    if "public_app_relation_count" in sql:
        counts = {
            "public_app_relation_count": 0,
            "public_app_function_count": 0,
            "auth_user_count": 0,
            "storage_bucket_count": 0,
            "storage_object_count": 0,
        }
        dirty_field = os.environ.get("FAKE_SUPABASE_DIRTY_FIELD", "")
        if dirty_field:
            counts[dirty_field] = 1
        rows = [counts]
    elif "to_regclass" in sql:
        rows = [{"migration_table_exists": state == "existing"}]
    elif "schema_migrations" in sql and "version" in sql:
        rows = [{"version": "20260827000000"}] if state == "existing" else []
    else:
        raise SystemExit(82)
    print(json.dumps({"rows": rows, "rowCount": len(rows)}))
    raise SystemExit(0)

if args[:2] == ["db", "push"]:
    if "--dry-run" not in args:
        state_path.write_text("existing", encoding="utf-8")
    raise SystemExit(0)

raise SystemExit(83)
'''


class SupabaseMainMigrationPushTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = load_tool_module()
        self.temp = tempfile.TemporaryDirectory(prefix="edoc-supabase-push-")
        self.root = Path(self.temp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.fake_cli = self.bin_dir / "supabase"
        self.fake_cli.write_text(FAKE_SUPABASE, encoding="utf-8")
        self.fake_cli.chmod(0o755)
        self.log_path = self.root / "commands.jsonl"
        self.state_path = self.root / "state.txt"
        self.project_ref_path = self.root / "project-ref"
        self.project_ref_path.write_text("abcdefghijklmnopqrst\n", encoding="utf-8")
        self.tool.LINKED_REF_PATH = self.project_ref_path
        self.env = mock.patch.dict(
            os.environ,
            {
                "PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "FAKE_SUPABASE_LOG": str(self.log_path),
                "FAKE_SUPABASE_STATE": str(self.state_path),
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def run_main(self, mode: str, *, apply: bool = False) -> list[list[str]]:
        argv = [
            str(TOOL_PATH),
            mode,
            "--project-ref",
            "abcdefghijklmnopqrst",
        ]
        if apply:
            argv.append("--apply")
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.tool.main(), 0)
        return [
            json.loads(line)
            for line in self.log_path.read_text(encoding="utf-8").splitlines()
        ]

    def test_fresh_empty_dry_run_uses_machine_query_and_roles_first(self) -> None:
        self.state_path.write_text("empty", encoding="utf-8")
        commands = self.run_main("fresh-empty")
        query_command = next(command for command in commands if command[:2] == ["db", "query"])
        self.assertEqual(commands[0], ["--version"])
        self.assertIn("--agent", query_command)
        self.assertIn("yes", query_command)
        self.assertIn("--output-format", query_command)
        self.assertIn("json", query_command)
        self.assertEqual(commands[-1][:2], ["db", "push"])
        self.assertIn("--include-roles", commands[-1])
        self.assertIn("--dry-run", commands[-1])

    def test_existing_dry_run_never_includes_roles(self) -> None:
        self.state_path.write_text("existing", encoding="utf-8")
        commands = self.run_main("existing")
        self.assertGreaterEqual(len(commands), 3)
        self.assertEqual(commands[-1][:2], ["db", "push"])
        self.assertNotIn("--include-roles", commands[-1])
        self.assertIn("--dry-run", commands[-1])

    def test_fresh_apply_rechecks_recorded_remote_history(self) -> None:
        self.state_path.write_text("empty", encoding="utf-8")
        commands = self.run_main("fresh-empty", apply=True)
        push_commands = [command for command in commands if command[:2] == ["db", "push"]]
        self.assertEqual(len(push_commands), 1)
        self.assertIn("--include-roles", push_commands[0])
        self.assertNotIn("--dry-run", push_commands[0])
        self.assertEqual(self.state_path.read_text(encoding="utf-8"), "existing")
        self.assertGreaterEqual(
            sum(command[:2] == ["db", "query"] for command in commands),
            3,
        )

    def test_malformed_query_output_fails_closed_before_push(self) -> None:
        self.state_path.write_text("empty", encoding="utf-8")
        with mock.patch.dict(os.environ, {"FAKE_SUPABASE_MALFORMED": "1"}, clear=False):
            with self.assertRaisesRegex(
                self.tool.CutoverError, "supabase_db_query_json_invalid"
            ):
                self.tool.linked_migration_state()
        commands = [
            json.loads(line)
            for line in self.log_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertFalse(any(command[:2] == ["db", "push"] for command in commands))

    def test_unpinned_cli_fails_closed_before_query_or_push(self) -> None:
        self.state_path.write_text("empty", encoding="utf-8")
        with mock.patch.dict(
            os.environ, {"FAKE_SUPABASE_VERSION": "2.106.0"}, clear=False
        ):
            with self.assertRaisesRegex(
                self.tool.CutoverError, "supabase_cli_version_mismatch"
            ):
                self.run_main("fresh-empty")
        commands = [
            json.loads(line)
            for line in self.log_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(commands, [["--version"]])

    def test_fresh_empty_rejects_any_public_auth_or_storage_state(self) -> None:
        dirty_fields = (
            "public_app_relation_count",
            "public_app_function_count",
            "auth_user_count",
            "storage_bucket_count",
            "storage_object_count",
        )
        for index, dirty_field in enumerate(dirty_fields):
            with self.subTest(dirty_field=dirty_field):
                self.state_path.write_text("empty", encoding="utf-8")
                if index:
                    self.log_path.write_text("", encoding="utf-8")
                with mock.patch.dict(
                    os.environ,
                    {"FAKE_SUPABASE_DIRTY_FIELD": dirty_field},
                    clear=False,
                ):
                    argv = [
                        str(TOOL_PATH),
                        "fresh-empty",
                        "--project-ref",
                        "abcdefghijklmnopqrst",
                    ]
                    with mock.patch.object(sys, "argv", argv):
                        with self.assertRaisesRegex(
                            self.tool.CutoverError,
                            "fresh_empty_mode_refuses_nonempty_project",
                        ):
                            self.tool.main()
                commands = [
                    json.loads(line)
                    for line in self.log_path.read_text(encoding="utf-8").splitlines()
                ]
                self.assertFalse(
                    any(command[:2] == ["db", "push"] for command in commands)
                )


if __name__ == "__main__":
    unittest.main()
