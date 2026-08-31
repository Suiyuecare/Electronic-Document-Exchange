-- Read-only verification for the approved eDoc shared-project isolation mode.
-- This file never reads HR row contents and performs no writes.

with expected_storage_policies(policy_name, table_name) as (
  values
    ('edoc backend reads private buckets', 'buckets'),
    ('edoc backend reads private objects', 'objects'),
    ('edoc backend inserts private objects', 'objects'),
    ('edoc backend updates private objects', 'objects'),
    ('edoc backend deletes private objects', 'objects')
),
backend_role as (
  select
    not rolsuper
      and not rolcreatedb
      and not rolcreaterole
      and not rolinherit
      and not rolbypassrls
      and not rolcanlogin as least_privilege
  from pg_catalog.pg_roles
  where rolname = 'edoc_backend'
),
edoc_relations as (
  select class_row.oid, class_row.relname, class_row.relrowsecurity
  from pg_catalog.pg_class class_row
  join pg_catalog.pg_namespace namespace_row
    on namespace_row.oid = class_row.relnamespace
  where namespace_row.nspname = 'edoc'
    and class_row.relkind in ('r', 'p')
),
backend_policies as (
  select
    policy_row.schemaname,
    policy_row.tablename,
    policy_row.policyname,
    policy_row.roles,
    coalesce(policy_row.qual, '') || ' ' || coalesce(policy_row.with_check, '')
      as predicate_text
  from pg_catalog.pg_policies policy_row
  where 'edoc_backend' = any(policy_row.roles)
),
checks(check_name, passed, observed) as (
  values
    (
      'edoc_schema_exists',
      pg_catalog.to_regnamespace('edoc') is not null,
      (pg_catalog.to_regnamespace('edoc') is not null)::text
    ),
    (
      'edoc_private_schema_exists',
      pg_catalog.to_regnamespace('edoc_private') is not null,
      (pg_catalog.to_regnamespace('edoc_private') is not null)::text
    ),
    (
      'edoc_backend_is_least_privilege',
      (select count(*) = 1 and bool_and(least_privilege) from backend_role),
      coalesce((select bool_and(least_privilege)::text from backend_role), 'missing')
    ),
    (
      'authenticator_can_set_edoc_backend',
      pg_catalog.pg_has_role('authenticator', 'edoc_backend', 'MEMBER'),
      pg_catalog.pg_has_role('authenticator', 'edoc_backend', 'MEMBER')::text
    ),
    (
      'backend_can_use_edoc_schema',
      pg_catalog.has_schema_privilege('edoc_backend', 'edoc', 'USAGE'),
      pg_catalog.has_schema_privilege('edoc_backend', 'edoc', 'USAGE')::text
    ),
    (
      'browser_and_service_roles_cannot_use_edoc_schema',
      not pg_catalog.has_schema_privilege('anon', 'edoc', 'USAGE')
        and not pg_catalog.has_schema_privilege('authenticated', 'edoc', 'USAGE')
        and not pg_catalog.has_schema_privilege('service_role', 'edoc', 'USAGE'),
      pg_catalog.json_build_object(
        'anon', pg_catalog.has_schema_privilege('anon', 'edoc', 'USAGE'),
        'authenticated', pg_catalog.has_schema_privilege('authenticated', 'edoc', 'USAGE'),
        'service_role', pg_catalog.has_schema_privilege('service_role', 'edoc', 'USAGE')
      )::text
    ),
    (
      'expected_relation_inventory',
      (select count(*) from pg_catalog.pg_class class_row
       join pg_catalog.pg_namespace namespace_row on namespace_row.oid = class_row.relnamespace
       where namespace_row.nspname = 'edoc'
         and class_row.relkind in ('r','p','v','m')) = 93,
      (select count(*)::text from pg_catalog.pg_class class_row
       join pg_catalog.pg_namespace namespace_row on namespace_row.oid = class_row.relnamespace
       where namespace_row.nspname = 'edoc'
         and class_row.relkind in ('r','p','v','m'))
    ),
    (
      'migration_ledger_complete',
      (select count(*) from edoc_private.shared_project_migration_ledger) = 52,
      (select count(*)::text from edoc_private.shared_project_migration_ledger)
    ),
    (
      'all_edoc_tables_have_rls',
      (select count(*) > 0 and bool_and(relrowsecurity) from edoc_relations),
      (select pg_catalog.json_build_object(
        'tables', count(*),
        'withoutRls', count(*) filter (where not relrowsecurity)
      )::text from edoc_relations)
    ),
    (
      'all_edoc_tables_have_backend_policy',
      not exists (
        select 1 from edoc_relations relation_row
        where not exists (
          select 1 from pg_catalog.pg_policy policy_row
          where policy_row.polrelid = relation_row.oid
            and pg_catalog.to_regrole('edoc_backend')::oid = any(policy_row.polroles)
        )
      ),
      (select count(*)::text from edoc_relations relation_row
       where not exists (
         select 1 from pg_catalog.pg_policy policy_row
         where policy_row.polrelid = relation_row.oid
           and pg_catalog.to_regrole('edoc_backend')::oid = any(policy_row.polroles)
       ))
    ),
    (
      'backend_has_no_public_table_grants',
      not exists (
        select 1 from information_schema.role_table_grants
        where grantee = 'edoc_backend' and table_schema = 'public'
      ),
      (select count(*)::text from information_schema.role_table_grants
       where grantee = 'edoc_backend' and table_schema = 'public')
    ),
    (
      'runtime_identity_rpc_is_backend_only',
      pg_catalog.to_regprocedure('edoc.edoc_runtime_identity()') is not null
        and pg_catalog.has_function_privilege(
          'edoc_backend', 'edoc.edoc_runtime_identity()', 'EXECUTE'
        )
        and not pg_catalog.has_function_privilege(
          'anon', 'edoc.edoc_runtime_identity()', 'EXECUTE'
        )
        and not pg_catalog.has_function_privilege(
          'authenticated', 'edoc.edoc_runtime_identity()', 'EXECUTE'
        )
        and not pg_catalog.has_function_privilege(
          'service_role', 'edoc.edoc_runtime_identity()', 'EXECUTE'
        ),
      (pg_catalog.to_regprocedure('edoc.edoc_runtime_identity()') is not null)::text
    ),
    (
      'edoc_buckets_are_private_and_bounded',
      (select count(*) = 2
         and bool_and(public is false)
         and bool_and(
           case id
             when 'edoc-private' then
               file_size_limit = 104857600
               and not ('image/svg+xml' = any(allowed_mime_types))
             when 'edoc-seal-vault' then
               file_size_limit = 3145728
               and allowed_mime_types = array[
                 'image/png', 'image/jpeg', 'image/webp'
               ]::text[]
             else false
           end
         )
       from storage.buckets
       where id in ('edoc-private', 'edoc-seal-vault')),
      (select count(*)::text from storage.buckets
       where id in ('edoc-private', 'edoc-seal-vault') and public is false)
    ),
    (
      'storage_policy_allowlist_is_exact',
      not exists (
        select 1 from expected_storage_policies expected
        where not exists (
          select 1 from backend_policies actual
          where actual.schemaname = 'storage'
            and actual.tablename = expected.table_name
            and actual.policyname = expected.policy_name
        )
      )
      and not exists (
        select 1 from backend_policies actual
        where actual.schemaname = 'storage'
          and not exists (
            select 1 from expected_storage_policies expected
            where expected.table_name = actual.tablename
              and expected.policy_name = actual.policyname
          )
      ),
      (select count(*)::text from backend_policies where schemaname = 'storage')
    ),
    (
      'storage_policies_never_reference_hr_documents',
      not exists (
        select 1 from backend_policies
        where schemaname = 'storage'
          and predicate_text like '%hr-documents%'
      ),
      (select count(*)::text from backend_policies
       where schemaname = 'storage' and predicate_text like '%hr-documents%')
    ),
    (
      'legacy_direct_browser_storage_policies_removed',
      not exists (
        select 1 from pg_catalog.pg_policies
        where schemaname = 'storage'
          and tablename = 'objects'
          and policyname in (
            'private bucket document scoped read',
            'private bucket authorized upload',
            'private bucket authorized replace'
          )
      ),
      (select count(*)::text from pg_catalog.pg_policies
       where schemaname = 'storage'
         and tablename = 'objects'
         and policyname in (
           'private bucket document scoped read',
           'private bucket authorized upload',
           'private bucket authorized replace'
         ))
    ),
    (
      'postgrest_exposes_edoc_schema',
      exists (
        select 1
        from pg_catalog.pg_roles role_row,
             pg_catalog.unnest(coalesce(role_row.rolconfig, array[]::text[])) config_item
        where role_row.rolname = 'authenticator'
          and config_item like 'pgrst.db_schemas=%'
          and 'edoc' = any(
            pg_catalog.regexp_split_to_array(
              substring(config_item from '^[^=]+=(.*)$'),
              '\s*,\s*'
            )
          )
      ),
      coalesce((
        select config_item
        from pg_catalog.pg_roles role_row,
             pg_catalog.unnest(coalesce(role_row.rolconfig, array[]::text[])) config_item
        where role_row.rolname = 'authenticator'
          and config_item like 'pgrst.db_schemas=%'
        limit 1
      ), 'missing')
    )
)
select check_name, passed, observed
from checks
union all
select
  '__all_shared_project_checks__' as check_name,
  bool_and(passed) as passed,
  pg_catalog.json_build_object(
    'passed', count(*) filter (where passed),
    'failed', count(*) filter (where not passed),
    'total', count(*)
  )::text as observed
from checks
order by check_name;
