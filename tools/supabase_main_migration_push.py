#!/usr/bin/env python3
"""Fail-closed main eDoc Supabase migration launcher.

Fresh empty projects need roles.sql before the historical migration chain;
existing projects must never load roles.sql again. This wrapper proves which
state the linked project is in before constructing the only permitted command.
It never accepts or prints a database password, service-role key or URL.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LINKED_REF_PATH = ROOT / "supabase" / ".temp" / "project-ref"
PINNED_CLI_VERSION = "2.116.0"


class CutoverError(RuntimeError):
    pass


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )
    if completed.returncode != 0:
        raise CutoverError("supabase_cutover_command_failed")
    return completed


def require_pinned_cli() -> None:
    completed = run(["supabase", "--version"], capture=True)
    if (completed.stdout or "").strip() != PINNED_CLI_VERSION:
        raise CutoverError("supabase_cli_version_mismatch")


def linked_query_rows(sql: str) -> list[dict[str, Any]]:
    """Run a read-only linked query using the CLI's machine-readable contract.

    Supabase CLI 2.105 does not provide JSON for ``migration list``.  Its
    ``db query`` command does, but only the agent-enabled JSON path reliably
    emits the result on stdout.  Treat every unexpected envelope as unknown
    state so a deployment can never guess whether roles.sql is safe to load.
    """

    completed = run(
        [
            "supabase",
            "db",
            "query",
            "--linked",
            "--agent",
            "yes",
            "--output-format",
            "json",
            sql,
        ],
        capture=True,
    )
    try:
        payload = json.loads(completed.stdout or "null")
    except json.JSONDecodeError as exc:
        raise CutoverError("supabase_db_query_json_invalid") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise CutoverError("supabase_db_query_rows_missing")
    rows = payload["rows"]
    if not all(isinstance(row, dict) for row in rows):
        raise CutoverError("supabase_db_query_rows_invalid")
    return rows


def linked_migration_state() -> set[str]:
    existence_rows = linked_query_rows(
        "select pg_catalog.to_regclass('supabase_migrations.schema_migrations') "
        "is not null as migration_table_exists"
    )
    if len(existence_rows) != 1 or not isinstance(
        existence_rows[0].get("migration_table_exists"), bool
    ):
        raise CutoverError("supabase_migration_table_state_unknown")
    if not existence_rows[0]["migration_table_exists"]:
        return set()

    version_rows = linked_query_rows(
        "select version::text as version "
        "from supabase_migrations.schema_migrations order by version"
    )
    versions: set[str] = set()
    for row in version_rows:
        version = row.get("version")
        if not isinstance(version, str) or not re.fullmatch(r"[0-9]{8,18}", version):
            raise CutoverError("supabase_migration_version_invalid")
        if version in versions:
            raise CutoverError("supabase_migration_version_duplicate")
        versions.add(version)
    return versions


def require_pristine_fresh_project() -> None:
    rows = linked_query_rows(
        "select "
        "(select pg_catalog.count(*) from pg_catalog.pg_class relation_row "
        "join pg_catalog.pg_namespace namespace_row "
        "on namespace_row.oid = relation_row.relnamespace "
        "where namespace_row.nspname = 'public' "
        "and relation_row.relkind in ('r','p','v','m','f','S') "
        "and not exists (select 1 from pg_catalog.pg_depend dependency_row "
        "where dependency_row.classid = 'pg_catalog.pg_class'::pg_catalog.regclass "
        "and dependency_row.objid = relation_row.oid "
        "and dependency_row.deptype = 'e')) as public_app_relation_count, "
        "(select pg_catalog.count(*) from pg_catalog.pg_proc procedure_row "
        "join pg_catalog.pg_namespace namespace_row "
        "on namespace_row.oid = procedure_row.pronamespace "
        "where namespace_row.nspname = 'public' "
        "and not exists (select 1 from pg_catalog.pg_depend dependency_row "
        "where dependency_row.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass "
        "and dependency_row.objid = procedure_row.oid "
        "and dependency_row.deptype = 'e')) as public_app_function_count, "
        "(select pg_catalog.count(*) from auth.users) as auth_user_count, "
        "(select pg_catalog.count(*) from storage.buckets) as storage_bucket_count, "
        "(select pg_catalog.count(*) from storage.objects) as storage_object_count"
    )
    expected_fields = {
        "public_app_relation_count",
        "public_app_function_count",
        "auth_user_count",
        "storage_bucket_count",
        "storage_object_count",
    }
    if len(rows) != 1 or set(rows[0]) != expected_fields:
        raise CutoverError("fresh_project_pristine_state_unknown")
    for field in expected_fields:
        value = rows[0].get(field)
        if type(value) is not int or value < 0:
            raise CutoverError("fresh_project_pristine_state_invalid")
        if value != 0:
            raise CutoverError("fresh_empty_mode_refuses_nonempty_project")


def require_dedicated_existing_project() -> None:
    """Refuse to run eDoc's global Data API hardening on a shared project.

    The forward chain intentionally revokes browser grants and policies across
    the public schema before restoring the exact eDoc backend allowlist.  That
    is correct only for a dedicated eDoc database.  Applying it to the legacy
    website/CMS database would disable unrelated public pages, forms and
    analytics, so identify that topology before even constructing db push.
    """

    rows = linked_query_rows(
        "select "
        "(select pg_catalog.count(*) from pg_catalog.pg_class relation_row "
        "join pg_catalog.pg_namespace namespace_row "
        "on namespace_row.oid = relation_row.relnamespace "
        "where namespace_row.nspname = 'public' "
        "and relation_row.relkind in ('r','p','v','m','f') "
        "and relation_row.relname = any(array["
        "'pages','page_sections','media','article_categories','articles',"
        "'analytics_page_views','analytics_events','form_submissions',"
        "'content_templates','courses','recruiting_pages','site_settings',"
        "'cms_content_areas','cms_change_sets'])) as shared_module_marker_count, "
        "(select pg_catalog.count(*) from storage.buckets "
        "where id not in ('edoc-private','edoc-seal-vault')) "
        "as unrelated_storage_bucket_count"
    )
    expected_fields = {
        "shared_module_marker_count",
        "unrelated_storage_bucket_count",
    }
    if len(rows) != 1 or set(rows[0]) != expected_fields:
        raise CutoverError("existing_project_partition_state_unknown")
    for field in expected_fields:
        value = rows[0].get(field)
        if type(value) is not int or value < 0:
            raise CutoverError("existing_project_partition_state_invalid")
        if value != 0:
            raise CutoverError("existing_main_project_refuses_shared_module_project")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("fresh-empty", "existing"))
    parser.add_argument("--project-ref", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply after the default dry-run. Requires the normal Supabase confirmation/credentials.",
    )
    args = parser.parse_args()

    linked_ref = LINKED_REF_PATH.read_text(encoding="utf-8").strip() if LINKED_REF_PATH.exists() else ""
    if not linked_ref:
        raise CutoverError("supabase_project_not_linked")
    if linked_ref != args.project_ref.strip():
        raise CutoverError("supabase_linked_project_ref_mismatch")

    require_pinned_cli()
    before = linked_migration_state()
    if args.mode == "fresh-empty" and before:
        raise CutoverError("fresh_empty_mode_refuses_project_with_migration_history")
    if args.mode == "existing" and not before:
        raise CutoverError("existing_mode_refuses_empty_project")
    if args.mode == "fresh-empty":
        require_pristine_fresh_project()
    else:
        require_dedicated_existing_project()

    command = ["supabase", "db", "push", "--linked"]
    if args.mode == "fresh-empty":
        command.append("--include-roles")
    if not args.apply:
        command.append("--dry-run")

    print(
        "Validated linked project state; running "
        + ("fresh roles-first migration path." if args.mode == "fresh-empty" else "forward-only existing-project path.")
    )
    run(command)

    if args.apply and args.mode == "fresh-empty" and not linked_migration_state():
        raise CutoverError("fresh_project_migrations_not_recorded_after_push")
    print("Migration command completed. Run the production cutover checks before deployment.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CutoverError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None
