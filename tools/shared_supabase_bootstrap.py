#!/usr/bin/env python3
"""Build and apply the eDoc shared-project namespace bootstrap safely.

The historical eDoc migration chain is immutable and targets ``public`` with
``service_role``.  This tool verifies that exact chain, rewrites only its schema
and backend-role bindings, then wraps every statement in one transaction.  The
default apply path ends in ROLLBACK; a live commit requires two explicit flags.

No API key, database password, document content, or HR row is read or printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SUPABASE_DIR = ROOT / "supabase"
MIGRATIONS_DIR = SUPABASE_DIR / "migrations"
MANIFEST_PATH = SUPABASE_DIR / "verification" / "migration_manifest.json"
ROLES_PATH = SUPABASE_DIR / "roles.sql"
LINKED_REF_PATH = SUPABASE_DIR / ".temp" / "project-ref"
BUNDLE_VERSION = "shared-project-schema-v1"
MINIMUM_CLI_VERSION = (2, 105, 0)
PROJECT_REF_PATTERN = re.compile(r"^[a-z]{20}$")
TRANSACTION_CONTROL_PATTERN = re.compile(
    r"^\s*(?:begin|commit|rollback|start\s+transaction)\s*;\s*$",
    re.IGNORECASE,
)


class SharedBootstrapError(RuntimeError):
    """Machine-readable fail-closed bootstrap error."""


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_manifest() -> list[str]:
    try:
        payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SharedBootstrapError("shared_manifest_invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != 1
        or payload.get("directory") != "supabase/migrations"
        or not isinstance(payload.get("migrations"), list)
        or not payload["migrations"]
        or not all(
            isinstance(name, str)
            and re.fullmatch(r"[0-9]{12,18}_[a-z0-9_]+\.sql", name)
            for name in payload["migrations"]
        )
    ):
        raise SharedBootstrapError("shared_manifest_invalid")
    names = list(payload["migrations"])
    if names != sorted(names) or len(names) != len(set(names)):
        raise SharedBootstrapError("shared_manifest_order_invalid")
    actual = sorted(path.name for path in MIGRATIONS_DIR.glob("*.sql"))
    if actual != names:
        raise SharedBootstrapError("shared_manifest_repository_mismatch")
    return names


def _rewrite_search_path_line(line: str) -> str:
    if not re.search(r"\bset\s+search_path\b", line, re.IGNORECASE):
        return line
    line = re.sub(r"(?<![A-Za-z0-9_])public(?![A-Za-z0-9_])", "edoc", line)
    line = re.sub(r"(?<![A-Za-z0-9_])private(?![A-Za-z0-9_])", "edoc_private", line)
    return line


def transform_sql(source: str) -> str:
    """Deterministically retarget one historical SQL source.

    Standalone ``public`` remains the PostgreSQL pseudo-role.  Only qualified
    objects, explicit schema clauses, catalog schema predicates and search_path
    entries are rewritten.  Nested transaction controls are removed so the
    generated bundle has one atomic outer transaction.
    """

    lines = [
        line
        for line in source.replace("\r\n", "\n").splitlines()
        if not TRANSACTION_CONTROL_PATTERN.fullmatch(line)
    ]
    transformed = "\n".join(_rewrite_search_path_line(line) for line in lines)
    if source.endswith("\n"):
        transformed += "\n"

    transformed = re.sub(r"\bpublic\.", "edoc.", transformed)
    transformed = re.sub(r"\bprivate\.", "edoc_private.", transformed)
    transformed = re.sub(
        r"(\bschema\s+)public\b",
        r"\1edoc",
        transformed,
        flags=re.IGNORECASE,
    )
    transformed = re.sub(
        r"(\bschema\s+)private\b",
        r"\1edoc_private",
        transformed,
        flags=re.IGNORECASE,
    )
    transformed = re.sub(
        r"\b(nspname|schemaname|table_schema|routine_schema)\s*=\s*'public'",
        lambda match: match.group(0).replace("'public'", "'edoc'"),
        transformed,
        flags=re.IGNORECASE,
    )
    transformed = re.sub(r"\bservice_role\b", "edoc_backend", transformed)
    # The audit-chain fresh replay guard originally proved an entirely empty
    # dedicated Supabase project.  In approved shared-project mode, unrelated
    # HR Auth users and Storage objects are expected and must not be treated as
    # eDoc evidence.  Keep the guard, but scope it to eDoc identities/buckets.
    transformed = transformed.replace(
        "if exists (select 1 from auth.users) then\n"
        "      v_exact_fresh_sentinel := false;\n"
        "    end if;",
        "if exists (\n"
        "      select 1 from auth.users auth_user\n"
        "      join edoc.users linked_user on linked_user.auth_user_id = auth_user.id\n"
        "    ) then\n"
        "      v_exact_fresh_sentinel := false;\n"
        "    end if;",
    )
    transformed = transformed.replace(
        "if exists (select 1 from storage.objects) then\n"
        "      v_exact_fresh_sentinel := false;\n"
        "    end if;",
        "if exists (\n"
        "      select 1 from storage.objects\n"
        "      where bucket_id in ('edoc-private', 'edoc-seal-vault')\n"
        "    ) then\n"
        "      v_exact_fresh_sentinel := false;\n"
        "    end if;",
    )
    return transformed


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _prologue() -> str:
    return f"""-- Generated by tools/shared_supabase_bootstrap.py; do not edit.
-- Bundle: {BUNDLE_VERSION}
-- This transaction preserves every existing public HR relation and row.

begin;
select pg_catalog.pg_advisory_xact_lock(1788103601, 20260831);

do $shared_preflight$
begin
  if pg_catalog.to_regclass('public.users') is null
     or pg_catalog.to_regclass('public.employees') is null
     or pg_catalog.to_regclass('public.companies') is null
     or pg_catalog.to_regclass('public.departments') is null then
    raise exception using errcode = '55000', message = 'shared_project_hr_markers_required';
  end if;
  if pg_catalog.to_regnamespace('edoc') is not null
     or pg_catalog.to_regnamespace('edoc_private') is not null
     or exists (select 1 from pg_catalog.pg_roles where rolname = 'edoc_backend') then
    raise exception using errcode = '55000', message = 'shared_project_namespace_not_fresh';
  end if;
  if exists (
    select 1 from storage.objects
    where bucket_id in ('edoc-private', 'edoc-seal-vault')
  ) then
    raise exception using errcode = '55000', message = 'shared_project_edoc_buckets_must_be_empty';
  end if;
end
$shared_preflight$;

create role edoc_backend
  nologin nosuperuser nocreatedb nocreaterole noinherit nobypassrls;
grant edoc_backend to authenticator;

create schema edoc authorization postgres;
create schema edoc_private authorization postgres;
set local search_path = edoc, edoc_private, extensions, pg_catalog;
revoke all on schema edoc from public, anon, authenticated, service_role, authenticator;
revoke all on schema edoc_private from public, anon, authenticated, service_role, authenticator;
grant usage on schema edoc to edoc_backend;
grant usage on schema edoc_private to edoc_backend;

create table edoc_private.shared_project_migration_ledger (
  file_name text primary key,
  source_sha256 text not null check (source_sha256 ~ '^[0-9a-f]{{64}}$'),
  transformed_sha256 text not null check (transformed_sha256 ~ '^[0-9a-f]{{64}}$'),
  bundle_version text not null,
  applied_at timestamptz not null default pg_catalog.clock_timestamp()
);
alter table edoc_private.shared_project_migration_ledger owner to postgres;
revoke all on table edoc_private.shared_project_migration_ledger
  from public, anon, authenticated, service_role, authenticator, edoc_backend;
"""


def _ledger_insert(file_name: str, source: str, transformed: str) -> str:
    return (
        "insert into edoc_private.shared_project_migration_ledger "
        "(file_name, source_sha256, transformed_sha256, bundle_version) values ("
        f"{_sql_literal(file_name)}, {_sql_literal(sha256_text(source))}, "
        f"{_sql_literal(sha256_text(transformed))}, {_sql_literal(BUNDLE_VERSION)});\n"
    )


def _postlude(migration_count: int) -> str:
    return f"""
-- Final shared-project privilege boundary.  Historical browser grants are
-- revoked; the transformed exact backend grant matrix remains authoritative.
revoke all on schema edoc from public, anon, authenticated, service_role, authenticator;
revoke all privileges on all tables in schema edoc
  from public, anon, authenticated, service_role, authenticator;
revoke all privileges on all sequences in schema edoc
  from public, anon, authenticated, service_role, authenticator;
revoke all privileges on all functions in schema edoc
  from public, anon, authenticated, service_role, authenticator;
revoke all on schema edoc_private from public, anon, authenticated, service_role, authenticator;
revoke all privileges on all tables in schema edoc_private
  from public, anon, authenticated, service_role, authenticator, edoc_backend;
revoke all privileges on all sequences in schema edoc_private
  from public, anon, authenticated, service_role, authenticator, edoc_backend;
revoke all privileges on all functions in schema edoc_private
  from public, anon, authenticated, service_role, authenticator, edoc_backend;
grant usage on schema edoc to edoc_backend;
grant usage on schema edoc_private to edoc_backend;

-- edoc_backend does not bypass RLS.  Table grants from the immutable chain
-- decide which SQL commands are allowed; these policies permit only those
-- already-granted commands to pass the row-security boundary.
do $backend_rls$
declare
  relation_row record;
  policy_name text;
begin
  for relation_row in
    select class_row.relname
    from pg_catalog.pg_class class_row
    join pg_catalog.pg_namespace namespace_row
      on namespace_row.oid = class_row.relnamespace
    where namespace_row.nspname = 'edoc'
      and class_row.relkind in ('r', 'p')
    order by class_row.relname
  loop
    execute pg_catalog.format(
      'alter table edoc.%I enable row level security',
      relation_row.relname
    );
    policy_name := pg_catalog.left(
      'edoc_backend_runtime_' || relation_row.relname,
      63
    );
    if not exists (
      select 1 from pg_catalog.pg_policy policy_row
      join pg_catalog.pg_class class_row on class_row.oid = policy_row.polrelid
      join pg_catalog.pg_namespace namespace_row on namespace_row.oid = class_row.relnamespace
      where namespace_row.nspname = 'edoc'
        and class_row.relname = relation_row.relname
        and policy_row.polname = policy_name
    ) then
      execute pg_catalog.format(
        'create policy %I on edoc.%I for all to edoc_backend using (true) with check (true)',
        policy_name,
        relation_row.relname
      );
    end if;
  end loop;
end
$backend_rls$;

-- Storage stays in Supabase's managed schema.  The custom role receives only
-- object access for the two private eDoc buckets; hr-documents is unreachable.
update storage.buckets
set public = false,
    avif_autodetection = false,
    file_size_limit = 104857600,
    allowed_mime_types = array[
      'application/pdf',
      'application/xml',
      'text/xml',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'application/pkcs7-mime',
      'application/octet-stream',
      'application/zip',
      'image/png',
      'image/jpeg',
      'image/webp'
    ]::text[],
    updated_at = pg_catalog.now()
where id = 'edoc-private';

update storage.buckets
set public = false,
    avif_autodetection = false,
    file_size_limit = 3145728,
    allowed_mime_types = array['image/png', 'image/jpeg', 'image/webp']::text[],
    updated_at = pg_catalog.now()
where id = 'edoc-seal-vault';

drop policy if exists "private bucket document scoped read" on storage.objects;
drop policy if exists "private bucket authorized upload" on storage.objects;
drop policy if exists "private bucket authorized replace" on storage.objects;

revoke all on storage.buckets from edoc_backend;
revoke all on storage.objects from edoc_backend;
grant usage on schema storage to edoc_backend;
grant select on storage.buckets to edoc_backend;
grant select, insert, update, delete on storage.objects to edoc_backend;

drop policy if exists "edoc backend reads private buckets" on storage.buckets;
create policy "edoc backend reads private buckets"
on storage.buckets for select to edoc_backend
using (id in ('edoc-private', 'edoc-seal-vault') and public is false);

drop policy if exists "edoc backend reads private objects" on storage.objects;
create policy "edoc backend reads private objects"
on storage.objects for select to edoc_backend
using (bucket_id in ('edoc-private', 'edoc-seal-vault'));

drop policy if exists "edoc backend inserts private objects" on storage.objects;
create policy "edoc backend inserts private objects"
on storage.objects for insert to edoc_backend
with check (bucket_id in ('edoc-private', 'edoc-seal-vault'));

drop policy if exists "edoc backend updates private objects" on storage.objects;
create policy "edoc backend updates private objects"
on storage.objects for update to edoc_backend
using (bucket_id in ('edoc-private', 'edoc-seal-vault'))
with check (bucket_id in ('edoc-private', 'edoc-seal-vault'));

drop policy if exists "edoc backend deletes private objects" on storage.objects;
create policy "edoc backend deletes private objects"
on storage.objects for delete to edoc_backend
using (bucket_id in ('edoc-private', 'edoc-seal-vault'));

create or replace function edoc.edoc_runtime_identity()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $identity$
  select pg_catalog.jsonb_build_object(
    'databaseRole', current_user,
    'schemaName', 'edoc',
    'storageMode', 'shared-project-schema'
  )
$identity$;
alter function edoc.edoc_runtime_identity() owner to postgres;
revoke all on function edoc.edoc_runtime_identity()
  from public, anon, authenticated, service_role, authenticator;
grant execute on function edoc.edoc_runtime_identity() to edoc_backend;

-- Preserve every existing PostgREST schema and append eDoc exactly once.
do $postgrest_schema$
declare
  configured text;
  schemas text[];
begin
  select substring(config_item from '^[^=]+=(.*)$')
    into configured
  from pg_catalog.pg_roles role_row,
       pg_catalog.unnest(coalesce(role_row.rolconfig, array[]::text[])) config_item
  where role_row.rolname = 'authenticator'
    and config_item like 'pgrst.db_schemas=%'
  limit 1;

  schemas := pg_catalog.regexp_split_to_array(
    coalesce(configured, 'public,graphql_public'),
    '\\s*,\\s*'
  );
  if not ('edoc' = any(schemas)) then
    schemas := pg_catalog.array_append(schemas, 'edoc');
  end if;
  execute pg_catalog.format(
    'alter role authenticator set pgrst.db_schemas = %L',
    pg_catalog.array_to_string(schemas, ',')
  );
end
$postgrest_schema$;

notify pgrst, 'reload config';
notify pgrst, 'reload schema';

do $shared_assertions$
declare
  role_row record;
  ledger_count bigint;
begin
  select * into role_row from pg_catalog.pg_roles where rolname = 'edoc_backend';
  if role_row.rolsuper or role_row.rolcreatedb or role_row.rolcreaterole
     or role_row.rolinherit or role_row.rolbypassrls or role_row.rolcanlogin then
    raise exception using errcode = '55000', message = 'shared_project_backend_role_not_least_privilege';
  end if;
  select pg_catalog.count(*) into ledger_count
    from edoc_private.shared_project_migration_ledger;
  if ledger_count <> {migration_count + 1} then
    raise exception using errcode = '55000', message = 'shared_project_migration_ledger_incomplete';
  end if;
  if exists (
    select 1
    from information_schema.role_table_grants grant_row
    where grant_row.grantee = 'edoc_backend'
      and grant_row.table_schema = 'public'
  ) then
    raise exception using errcode = '55000', message = 'shared_project_backend_has_public_table_grant';
  end if;
end
$shared_assertions$;

select
  (select pg_catalog.count(*) from pg_catalog.pg_class class_row
   join pg_catalog.pg_namespace namespace_row on namespace_row.oid = class_row.relnamespace
   where namespace_row.nspname = 'edoc' and class_row.relkind in ('r','p','v','m'))
    as edoc_relation_count,
  (select pg_catalog.count(*) from edoc_private.shared_project_migration_ledger)
    as migration_ledger_count,
  pg_catalog.has_schema_privilege('edoc_backend', 'edoc', 'USAGE')
    as backend_schema_usage,
  not pg_catalog.has_schema_privilege('service_role', 'edoc', 'USAGE')
    as service_role_schema_denied;
"""


def render_bundle(*, commit: bool = False) -> str:
    migration_names = load_manifest()
    if not ROLES_PATH.is_file():
        raise SharedBootstrapError("shared_roles_source_missing")
    sections = [_prologue()]

    sources: list[tuple[str, str]] = [
        ("roles.sql", ROLES_PATH.read_text(encoding="utf-8"))
    ]
    sources.extend(
        (name, (MIGRATIONS_DIR / name).read_text(encoding="utf-8"))
        for name in migration_names
    )
    for file_name, source in sources:
        transformed = transform_sql(source)
        sections.append(f"\n-- BEGIN TRANSFORMED SOURCE: {file_name}\n")
        sections.append(transformed)
        if not transformed.endswith("\n"):
            sections.append("\n")
        sections.append(_ledger_insert(file_name, source, transformed))
        sections.append(f"-- END TRANSFORMED SOURCE: {file_name}\n")

    sections.append(_postlude(len(migration_names)))
    sections.append("commit;\n" if commit else "rollback;\n")
    bundle = "".join(sections)

    # Generator invariants: no historical eDoc object may still point at HR's
    # public schema and the bundle must have only one outer transaction pair.
    unsafe_patterns = {
        "shared_transform_public_object_remaining": r"\bpublic\.[A-Za-z_]",
        "shared_transform_public_catalog_predicate_remaining": (
            r"\b(?:nspname|schemaname|table_schema|routine_schema)\s*=\s*'public'"
        ),
        "shared_transform_service_role_binding_remaining": r"\bto\s+service_role\b",
        "shared_transform_public_search_path_remaining": (
            r"\bset\s+search_path\b[^\n;]*\bpublic\b"
        ),
    }
    # The postlude intentionally checks public grants, and role ACL statements
    # intentionally mention service_role.  Restrict invariant scanning to the
    # transformed source portion.
    source_region = bundle.split("-- BEGIN TRANSFORMED SOURCE:", 1)[1].split(
        "-- Final shared-project privilege boundary.",
        1,
    )[0]
    for error_code, pattern in unsafe_patterns.items():
        if re.search(pattern, source_region, re.IGNORECASE):
            raise SharedBootstrapError(error_code)
    if len(re.findall(r"(?im)^\s*begin\s*;\s*$", bundle)) != 1:
        raise SharedBootstrapError("shared_bundle_transaction_begin_invalid")
    expected_end = "commit;\n" if commit else "rollback;\n"
    if not bundle.endswith(expected_end):
        raise SharedBootstrapError("shared_bundle_transaction_end_invalid")
    return bundle


def _run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )
    if result.returncode != 0:
        raise SharedBootstrapError("shared_supabase_command_failed")
    return result


def _require_cli() -> None:
    output = (_run(["supabase", "--version"], capture=True).stdout or "").strip()
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", output)
    if not match or tuple(int(part) for part in match.groups()) < MINIMUM_CLI_VERSION:
        raise SharedBootstrapError("shared_supabase_cli_too_old")


def _require_linked_project(project_ref: str) -> None:
    if not PROJECT_REF_PATTERN.fullmatch(project_ref):
        raise SharedBootstrapError("shared_project_ref_invalid")
    try:
        linked_ref = LINKED_REF_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SharedBootstrapError("shared_project_not_linked") from exc
    if linked_ref != project_ref:
        raise SharedBootstrapError("shared_linked_project_ref_mismatch")


def _linked_query(sql: str) -> list[dict[str, Any]]:
    result = _run(
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
        payload = json.loads(result.stdout or "null")
    except json.JSONDecodeError as exc:
        raise SharedBootstrapError("shared_query_json_invalid") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise SharedBootstrapError("shared_query_rows_missing")
    if not all(isinstance(row, dict) for row in payload["rows"]):
        raise SharedBootstrapError("shared_query_rows_invalid")
    return payload["rows"]


def _hr_fingerprint() -> dict[str, int]:
    rows = _linked_query(
        "select "
        "(select count(*)::bigint from public.users) as public_users, "
        "(select count(*)::bigint from public.employees) as public_employees, "
        "(select count(*)::bigint from public.companies) as public_companies, "
        "(select count(*)::bigint from public.departments) as public_departments, "
        "(select count(*)::bigint from storage.objects where bucket_id = 'hr-documents') "
        "as hr_document_objects"
    )
    expected = {
        "public_users",
        "public_employees",
        "public_companies",
        "public_departments",
        "hr_document_objects",
    }
    if len(rows) != 1 or set(rows[0]) != expected:
        raise SharedBootstrapError("shared_hr_fingerprint_invalid")
    fingerprint: dict[str, int] = {}
    for key in expected:
        value = rows[0].get(key)
        if type(value) is not int or value < 0:
            raise SharedBootstrapError("shared_hr_fingerprint_invalid")
        fingerprint[key] = value
    return fingerprint


def apply_bundle(project_ref: str, *, commit: bool, acknowledge: bool) -> None:
    _require_cli()
    _require_linked_project(project_ref)
    if commit and not acknowledge:
        raise SharedBootstrapError("shared_commit_acknowledgement_required")
    before = _hr_fingerprint()
    bundle = render_bundle(commit=commit)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".sql",
        prefix="edoc-shared-bootstrap-",
        delete=True,
    ) as sql_file:
        sql_file.write(bundle)
        sql_file.flush()
        _run(["supabase", "db", "query", "--linked", "--file", sql_file.name])
    after = _hr_fingerprint()
    if before != after:
        raise SharedBootstrapError("shared_hr_fingerprint_changed")

    state_rows = _linked_query(
        "select "
        "(to_regnamespace('edoc') is not null) as edoc_schema_exists, "
        "exists(select 1 from pg_roles where rolname = 'edoc_backend') "
        "as edoc_role_exists"
    )
    if len(state_rows) != 1:
        raise SharedBootstrapError("shared_post_apply_state_invalid")
    expected = bool(commit)
    if (
        state_rows[0].get("edoc_schema_exists") is not expected
        or state_rows[0].get("edoc_role_exists") is not expected
    ):
        raise SharedBootstrapError("shared_post_apply_state_invalid")


def _write_output(path: Path, content: str) -> None:
    path = path.resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as exc:
        raise SharedBootstrapError("shared_output_must_be_in_repository") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)

    render_parser = subparsers.add_parser("render")
    render_parser.add_argument("--output", type=Path, required=True)
    render_parser.add_argument("--commit", action="store_true")

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--project-ref", required=True)
    apply_parser.add_argument("--commit", action="store_true")
    apply_parser.add_argument(
        "--acknowledge-shared-project",
        action="store_true",
        help="Required with --commit after the rollback preflight succeeds.",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.action == "render":
        _write_output(args.output, render_bundle(commit=args.commit))
        print("Shared-project SQL bundle rendered without credentials.")
        return 0

    apply_bundle(
        args.project_ref.strip(),
        commit=bool(args.commit),
        acknowledge=bool(args.acknowledge_shared_project),
    )
    print(
        "Shared-project bootstrap committed; HR fingerprint unchanged."
        if args.commit
        else "Shared-project rollback preflight passed; HR fingerprint unchanged."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SharedBootstrapError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None
