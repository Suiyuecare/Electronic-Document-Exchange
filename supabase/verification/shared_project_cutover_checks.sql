-- Read-only verification for the approved eDoc shared-project isolation mode.
-- This file never reads HR row contents and performs no writes.

do $compose_editor_resilience_gate$
declare
  v_schema text := 'edoc';
  v_backend text := 'edoc_backend';
  v_denied text[] := array['anon','authenticated','service_role','authenticator'];
  v_table regclass;
  v_proc record;
  v_rpc text;
  v_role text;
  v_signature text;
begin
  v_table := pg_catalog.to_regclass(pg_catalog.format('%I.official_document_compose_drafts', v_schema));
  if v_table is null or not exists (
    select 1 from pg_catalog.pg_class where oid=v_table and relrowsecurity
      and pg_catalog.pg_get_userbyid(relowner)='postgres'
  ) then raise exception 'compose_editor_draft_table_security_missing'; end if;
  if not exists (
    select 1 from pg_catalog.pg_attribute where attrelid=pg_catalog.to_regclass(pg_catalog.format('%I.official_documents',v_schema))
      and attname='content_revision' and atttypid='integer'::regtype and attnotnull and not attisdropped
  ) then raise exception 'compose_editor_content_revision_missing'; end if;
  if (select count(*) from pg_catalog.pg_constraint where conrelid=v_table and contype='f' and convalidated
       and confrelid in (pg_catalog.to_regclass(pg_catalog.format('%I.users',v_schema)),pg_catalog.to_regclass(pg_catalog.format('%I.companies',v_schema)))) <> 2
     or pg_catalog.to_regclass(pg_catalog.format('%I.idx_compose_draft_owner',v_schema)) is null then
    raise exception 'compose_editor_draft_relationships_missing';
  end if;
  foreach v_role in array array['SELECT','INSERT','UPDATE','DELETE'] loop
    if not pg_catalog.has_table_privilege(v_backend,v_table,v_role) then
      raise exception 'compose_editor_backend_table_grant_missing';
    end if;
  end loop;
  if pg_catalog.has_table_privilege(v_backend,v_table,'TRUNCATE,REFERENCES,TRIGGER') then
    raise exception 'compose_editor_backend_table_extra_grant';
  end if;
  foreach v_role in array v_denied loop
    if pg_catalog.has_table_privilege(v_role,v_table,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') then
      raise exception 'compose_editor_browser_table_grant';
    end if;
  end loop;
  if exists (select 1 from pg_catalog.pg_class c, lateral pg_catalog.aclexplode(coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a where c.oid=v_table and a.grantee=0) then
    raise exception 'compose_editor_public_table_grant';
  end if;
  if v_backend <> 'service_role' and not exists (
    select 1 from pg_catalog.pg_policies where schemaname=v_schema and tablename='official_document_compose_drafts'
      and v_backend::name=any(roles) and qual='true' and with_check='true'
  ) then raise exception 'compose_editor_backend_row_policy_missing'; end if;
  foreach v_rpc in array array['edoc_save_compose_draft(text,text,text,integer,jsonb,text,boolean)','edoc_copy_editor_conflict(jsonb)'] loop
    v_signature := v_schema || '.' || v_rpc;
    select * into v_proc from pg_catalog.pg_proc where oid=pg_catalog.to_regprocedure(v_signature);
    if not found then raise exception 'compose_editor_rpc_missing'; end if;
    if v_proc.prosecdef or pg_catalog.pg_get_userbyid(v_proc.proowner)<>'postgres'
       or not coalesce(v_proc.proconfig @> array[case when v_rpc like 'edoc_save_%' then 'search_path=""' else 'search_path=pg_catalog, ' || v_schema end],false)
       or not pg_catalog.has_function_privilege(v_backend,v_proc.oid,'EXECUTE') then
      raise exception 'compose_editor_rpc_security_mismatch';
    end if;
    foreach v_role in array v_denied loop
      if pg_catalog.has_function_privilege(v_role,v_proc.oid,'EXECUTE') then
        raise exception 'compose_editor_browser_rpc_grant';
      end if;
    end loop;
    if exists(select 1 from pg_catalog.aclexplode(coalesce(v_proc.proacl,pg_catalog.acldefault('f',v_proc.proowner))) a where a.grantee=0 and a.privilege_type='EXECUTE') then
      raise exception 'compose_editor_public_rpc_grant';
    end if;
  end loop;
end;
$compose_editor_resilience_gate$;

do $worklist_receipt_rpc_gate$
declare
  v_proc record;
  v_rpc text;
  v_role text;
begin
  foreach v_rpc in array array['edoc_confirm_official_document(jsonb)','edoc_list_official_document_candidates(jsonb)'] loop
    select * into v_proc from pg_catalog.pg_proc where oid=pg_catalog.to_regprocedure('edoc.' || v_rpc);
    if not found then raise exception 'worklist_receipt_rpc_missing'; end if;
    if v_proc.prosecdef or not coalesce(v_proc.proconfig @> array['search_path=""'],false)
       or not pg_catalog.has_function_privilege('edoc_backend',v_proc.oid,'EXECUTE') then
      raise exception 'worklist_receipt_rpc_security_mismatch';
    end if;
    foreach v_role in array array['anon','authenticated','service_role','authenticator'] loop
      if pg_catalog.has_function_privilege(v_role,v_proc.oid,'EXECUTE') then
        raise exception 'worklist_receipt_rpc_browser_grant';
      end if;
    end loop;
    if exists(select 1 from pg_catalog.aclexplode(coalesce(v_proc.proacl,pg_catalog.acldefault('f',v_proc.proowner))) a where a.grantee=0 and a.privilege_type='EXECUTE') then
      raise exception 'worklist_receipt_rpc_public_grant';
    end if;
  end loop;
end;
$worklist_receipt_rpc_gate$;

do $configurable_workflow_gate$
declare
  v_schema text := 'edoc';
  v_backend text := 'edoc_backend';
  v_denied text[] := array['anon','authenticated','service_role','authenticator'];
  v_proc record;
  v_rpc text;
  v_role text;
begin
  foreach v_rpc in array array['edoc_save_official_workflow_config(jsonb)','edoc_mutate_official_workflow(jsonb)'] loop
    select * into v_proc from pg_catalog.pg_proc
      where oid=pg_catalog.to_regprocedure(v_schema || '.' || v_rpc);
    if not found then raise exception 'configurable_workflow_rpc_missing'; end if;
    if not v_proc.prosecdef or pg_catalog.pg_get_userbyid(v_proc.proowner)<>'postgres'
       or not coalesce(v_proc.proconfig @> array['search_path=""','lock_timeout=5s'],false)
       or not pg_catalog.has_function_privilege(v_backend,v_proc.oid,'EXECUTE') then
      raise exception 'configurable_workflow_rpc_security_mismatch';
    end if;
    foreach v_role in array v_denied loop
      if pg_catalog.has_function_privilege(v_role,v_proc.oid,'EXECUTE') then
        raise exception 'configurable_workflow_browser_rpc_grant';
      end if;
    end loop;
    if exists(select 1 from pg_catalog.aclexplode(coalesce(v_proc.proacl,pg_catalog.acldefault('f',v_proc.proowner))) a where a.grantee=0 and a.privilege_type='EXECUTE') then
      raise exception 'configurable_workflow_public_rpc_grant';
    end if;
  end loop;
  if not exists (
    select 1 from pg_catalog.pg_trigger where tgrelid=pg_catalog.to_regclass(v_schema || '.official_document_approval_steps')
      and tgname='preserve_official_decision_evidence' and tgenabled='O' and not tgisinternal
  ) then raise exception 'configurable_workflow_evidence_trigger_missing'; end if;
  if not exists (
    select 1 from pg_catalog.pg_constraint where conrelid=pg_catalog.to_regclass(v_schema || '.official_documents')
      and conname='official_documents_status_check' and convalidated
      and pg_catalog.pg_get_constraintdef(oid) like '%pending_approval%'
  ) then raise exception 'configurable_workflow_custom_status_missing'; end if;
end;
$configurable_workflow_gate$;


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
         and class_row.relkind in ('r','p','v','m')) = 96,
      (select count(*)::text from pg_catalog.pg_class class_row
       join pg_catalog.pg_namespace namespace_row on namespace_row.oid = class_row.relnamespace
       where namespace_row.nspname = 'edoc'
         and class_row.relkind in ('r','p','v','m'))
    ),
    (
      'migration_ledger_complete',
      (select count(*) from edoc_private.shared_project_migration_ledger) = 68
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260911133144_compose_resilience_drafts_revision.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260911133603_editor_conflict_copy_atomic.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260913055452_editor_applicant_selection_scope.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260913060040_editor_cross_company_workflow_scope.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260913130517_editor_storage_v2_opaque_paths.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260922074613_configurable_official_workflows.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260924154226_atomic_official_receipt_confirmation.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260924154315_scoped_official_document_listing.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260924155456_latest_generation_dispatch_owner.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260925044708_editor_pdf_uploads_skip_antivirus_preflight_required.sql'),
      (select count(*)::text from edoc_private.shared_project_migration_ledger)
    ),
    (
      'editor_pdf_preflight_status_guard',
      exists (
        select 1 from pg_catalog.pg_constraint constraint_row
        where constraint_row.conrelid = pg_catalog.to_regclass('edoc.official_document_editor_assets')
          and constraint_row.conname = 'official_editor_asset_scan_status_check'
          and pg_catalog.pg_get_constraintdef(constraint_row.oid) like '%not_scanned%'
      )
      and not exists (
        select 1
        from edoc.official_document_editor_assets asset
        left join edoc.file_objects file_object on file_object.id = asset.file_object_id
        left join edoc.official_document_files official_file on official_file.id = asset.official_file_id
        where asset.scan_status = 'not_scanned'
          and (
            asset.asset_kind not in ('source_pdf', 'import_pdf')
            or asset.upload_status <> 'finalized'
            or asset.preflight_status <> 'passed'
            or file_object.id is null
            or file_object.scan_status <> 'not_scanned'
            or file_object.document_id <> asset.document_id
            or file_object.purpose <> 'official-editor'
            or file_object.version_label <> 'editor-asset-' || asset.asset_kind
            or file_object.sha256 <> asset.sha256
            or file_object.size_bytes <> asset.size_bytes
            or file_object.bucket <> asset.storage_bucket
            or (asset.asset_kind = 'source_pdf' and (
              official_file.id is null
              or official_file.document_id <> asset.document_id
              or official_file.file_type <> 'original_pdf'
              or official_file.file_object_id <> file_object.id
              or official_file.file_hash <> asset.sha256
              or official_file.file_size <> asset.size_bytes
            ))
          )
      ),
      (select count(*)::text from edoc.official_document_editor_assets where scan_status='not_scanned')
    ),
    (
      'finance_user_company_cache_ready',
      exists (
        select 1
        from information_schema.columns
        where table_schema = 'edoc'
          and table_name = 'users'
          and column_name = 'company_name'
          and data_type = 'text'
          and is_nullable = 'NO'
      )
      and not exists (
        select 1
        from edoc.users user_row
        join edoc.companies company_row on company_row.id = user_row.company_id
        where user_row.company_name is distinct from company_row.name
      ),
      pg_catalog.json_build_object(
        'columnExists', exists (
          select 1
          from information_schema.columns
          where table_schema = 'edoc'
            and table_name = 'users'
            and column_name = 'company_name'
            and data_type = 'text'
            and is_nullable = 'NO'
        ),
        'mismatchedRows', (
          select count(*)
          from edoc.users user_row
          join edoc.companies company_row on company_row.id = user_row.company_id
          where user_row.company_name is distinct from company_row.name
        )
      )::text
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
