-- Apply the forward user company-name cache migration to an already-created
-- shared eDoc namespace and extend its immutable source ledger.

begin;

select pg_catalog.pg_advisory_xact_lock(1788103601, 20260831);

do $preflight$
begin
  if pg_catalog.to_regclass('edoc.users') is null
     or pg_catalog.to_regclass('edoc.companies') is null
     or not exists (
       select 1 from pg_catalog.pg_roles where rolname = 'edoc_backend'
     )
     or (select count(*) from edoc_private.shared_project_migration_ledger) <> 52
     or exists (
       select 1
       from edoc_private.shared_project_migration_ledger
       where file_name = '20260831102000_add_user_company_name_cache.sql'
     ) then
    raise exception using
      errcode = '55000',
      message = 'shared_edoc_user_company_cache_preflight_failed';
  end if;
end
$preflight$;

alter table edoc.users
  add column if not exists company_name text not null default '';

update edoc.users user_row
set company_name = company_row.name
from edoc.companies company_row
where company_row.id = user_row.company_id
  and user_row.company_name is distinct from company_row.name;

comment on column edoc.users.company_name is
  'Finance-owned company display-name cache; canonical identity remains users.company_id.';

insert into edoc_private.shared_project_migration_ledger (
  file_name,
  source_sha256,
  transformed_sha256,
  bundle_version
) values (
  '20260831102000_add_user_company_name_cache.sql',
  '336a3c5c4899b3663f813972698258a3db97ba7920ae76521c6605ed2cf4ac5d',
  'd77c4f04dd41284af2db612bf491c9443ee15d32c3e0abddf87ca889b696038c',
  'shared-project-schema-v1'
);

notify pgrst, 'reload schema';

do $assertions$
begin
  if not exists (
       select 1
       from information_schema.columns
       where table_schema = 'edoc'
         and table_name = 'users'
         and column_name = 'company_name'
         and data_type = 'text'
         and is_nullable = 'NO'
     )
     or exists (
       select 1
       from edoc.users user_row
       join edoc.companies company_row on company_row.id = user_row.company_id
       where user_row.company_name is distinct from company_row.name
     )
     or (select count(*) from edoc_private.shared_project_migration_ledger) <> 53
     or not exists (
       select 1
       from edoc_private.shared_project_migration_ledger
       where file_name = '20260831102000_add_user_company_name_cache.sql'
         and source_sha256 = '336a3c5c4899b3663f813972698258a3db97ba7920ae76521c6605ed2cf4ac5d'
         and transformed_sha256 = 'd77c4f04dd41284af2db612bf491c9443ee15d32c3e0abddf87ca889b696038c'
     )
     or exists (
       select 1
       from information_schema.role_table_grants
       where grantee = 'edoc_backend'
         and table_schema = 'public'
     ) then
    raise exception using
      errcode = '55000',
      message = 'shared_edoc_user_company_cache_assertion_failed';
  end if;
end
$assertions$;

commit;
