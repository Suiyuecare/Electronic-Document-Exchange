-- Read-only verification for the approved eDoc shared-project isolation mode.
-- This file never reads HR row contents and performs no writes.

-- Exact original-scan maintenance gate: read-only permit and reviewed code.
-- Six native120 assets: exact-source, role and trigger gate; read-only.
do $approved_native120_scan_import_gate$
declare
  v_table regclass := pg_catalog.to_regclass('edoc.approved_native120_scan_import_batches');
  v_backend text := 'edoc_backend';
  v_denied text[] := array['anon','authenticated','service_role','authenticator'];
  v_role text; v_expected record; v_proc record;
begin
  if v_table is null or not exists(select 1 from pg_catalog.pg_class where oid=v_table
      and relrowsecurity and relforcerowsecurity and pg_catalog.pg_get_userbyid(relowner)='postgres') then
    raise exception 'native120_scan_import_table_security_mismatch';
  end if;
  if not pg_catalog.has_table_privilege(v_backend,v_table,'SELECT')
     or pg_catalog.has_table_privilege(v_backend,v_table,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') then
    raise exception 'native120_scan_import_table_grant_mismatch';
  end if;
  foreach v_role in array v_denied loop
    if pg_catalog.has_table_privilege(v_role,v_table,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') then
      raise exception 'native120_scan_import_browser_table_grant';
    end if;
  end loop;
  if exists(select 1 from pg_catalog.pg_class c, lateral pg_catalog.aclexplode(
      coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a where c.oid=v_table and a.grantee=0)
     or (select count(*) from pg_catalog.pg_policy where polrelid=v_table)<>1
     or not exists(select 1 from pg_catalog.pg_policy where polrelid=v_table and polcmd='r'
       and polroles=array[pg_catalog.to_regrole(v_backend)::oid]
       and pg_catalog.pg_get_expr(polqual,polrelid)='true' and polwithcheck is null) then
    raise exception 'native120_scan_import_table_policy_mismatch';
  end if;
  if (select pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(
       pg_catalog.string_agg(conname||':'||pg_catalog.pg_get_constraintdef(oid,true),'|' order by conname),'UTF8')),'hex')
       from pg_catalog.pg_constraint where conrelid=v_table)
     is distinct from '75e64288b64d1637b85dda9be1b70df1c03544610188d0ed4e26ffa403927e4e' then
    raise exception 'native120_scan_import_exact_constraints_mismatch';
  end if;
  for v_expected in select * from (values
    ('edoc.edoc_approved_native120_scan_dimensions_are_valid(text,text,text,text,text,integer,integer,numeric,numeric,numeric,text,boolean)',false,'i',true,'1a8bdc48e527c9c75fe01ccd9900ef979a7c1493ad97b8d69f7ad1b25b87ff03'),
    ('edoc.edoc_company_seal_file_dimensions_are_valid(text,text,text,text,text,integer,integer,numeric,numeric,numeric,text,boolean)',false,'i',true,'6c876ebf3bc4aad4a43c4e0e318b3a281ff658e5f5549f4c346217460a474b24'),
    ('edoc.edoc_import_approved_native120_scan_file(text,text,text,text,text,bigint,text,integer,integer,numeric,numeric,numeric,text,text,text,text)',true,'v',true,'d3e8ca6085c256f3246b573425f4d7ad26583bbc408104cf08baa529d6e95454'),
    ('edoc.edoc_create_company_seal_file_version(text,text,text,text,text,text,bigint,text,integer,integer,numeric,numeric,numeric,text,text,text,text,text,text)',true,'v',true,'185ed92981126047f1678d0793293461dbf55b767c606f1ffb7e4a48182f218b'),
    ('edoc.edoc_set_current_company_seal_file(text,text,text,text)',true,'v',true,'299df406fef15e6d978621ad184ce40b7f882b5da606f5e95f28c4393325ded7'),
    ('edoc.edoc_enforce_approved_native120_scan_file()',false,'v',false,'57035cba03195c3032754c24731497af1ed0848ca23b5af5504d76ee21060ec4'),
    ('edoc.edoc_enforce_company_seal_position_dimensions()',false,'v',false,'23ab030e8010253e054a368f73945de0592c05eab5b6d6d358414c909a839b3d')
  ) expected(signature,is_definer,volatility,backend_execute,body_sha256) loop
    select * into v_proc from pg_catalog.pg_proc where oid=pg_catalog.to_regprocedure(v_expected.signature);
    if not found then raise exception 'native120_scan_import_rpc_missing'; end if;
    if v_proc.prosecdef is distinct from v_expected.is_definer
       or v_proc.provolatile::text is distinct from v_expected.volatility
       or pg_catalog.pg_get_userbyid(v_proc.proowner)<>'postgres'
       or not coalesce(v_proc.proconfig @> array['search_path=""'],false)
       or pg_catalog.has_function_privilege(v_backend,v_proc.oid,'EXECUTE') is distinct from v_expected.backend_execute
       or pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(v_proc.prosrc,'UTF8')),'hex')<>v_expected.body_sha256 then
      raise exception 'native120_scan_import_rpc_security_or_source_mismatch';
    end if;
    if v_expected.is_definer and not coalesce(v_proc.proconfig @> array['lock_timeout=5s'],false) then
      raise exception 'native120_scan_import_rpc_lock_timeout_missing';
    end if;
    foreach v_role in array v_denied loop
      if pg_catalog.has_function_privilege(v_role,v_proc.oid,'EXECUTE') then
        raise exception 'native120_scan_import_browser_rpc_grant';
      end if;
    end loop;
    if exists(select 1 from pg_catalog.aclexplode(coalesce(v_proc.proacl,
        pg_catalog.acldefault('f',v_proc.proowner))) a where a.grantee=0 and a.privilege_type='EXECUTE') then
      raise exception 'native120_scan_import_public_rpc_grant';
    end if;
  end loop;
  if not exists(select 1 from pg_catalog.pg_trigger where tgrelid='edoc.company_seal_files'::regclass
       and tgname='edoc_approved_native120_scan_file' and not tgisinternal and tgenabled='O' and tgtype=23
       and tgfoid='edoc.edoc_enforce_approved_native120_scan_file()'::regprocedure and tgnargs=0 and tgattr=''::int2vector) then
    raise exception 'native120_scan_import_attestation_trigger_mismatch';
  end if;
end;
$approved_native120_scan_import_gate$;

do $approved_original_scan_import_gate$
declare
  v_table regclass := pg_catalog.to_regclass('edoc.approved_original_scan_import_batches');
  v_backend text := 'edoc_backend';
  v_denied text[] := array['anon','authenticated','service_role','authenticator'];
  v_role text;
  v_expected record;
  v_proc record;
begin
  if v_table is null or not exists (
    select 1 from pg_catalog.pg_class where oid=v_table and relrowsecurity and relforcerowsecurity
      and pg_catalog.pg_get_userbyid(relowner)='postgres'
  ) then raise exception 'approved_scan_import_table_security_mismatch'; end if;
  if not pg_catalog.has_table_privilege(v_backend,v_table,'SELECT')
     or pg_catalog.has_table_privilege(v_backend,v_table,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') then
    raise exception 'approved_scan_import_table_grant_mismatch';
  end if;
  foreach v_role in array v_denied loop
    if pg_catalog.has_table_privilege(v_role,v_table,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') then
      raise exception 'approved_scan_import_browser_table_grant';
    end if;
  end loop;
  if exists(select 1 from pg_catalog.pg_class c, lateral pg_catalog.aclexplode(
      coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a where c.oid=v_table and a.grantee=0)
     or (select count(*) from pg_catalog.pg_policy where polrelid=v_table)<>1
     or not exists(select 1 from pg_catalog.pg_policy where polrelid=v_table and polcmd='r'
       and polroles=array[pg_catalog.to_regrole(v_backend)::oid]
       and pg_catalog.pg_get_expr(polqual,polrelid)='true' and polwithcheck is null) then
    raise exception 'approved_scan_import_table_policy_mismatch';
  end if;
  for v_expected in select * from (values
    ('edoc.edoc_approved_original_scan_dimensions_are_valid(text,text,text,text,text,integer,integer,numeric,numeric,numeric,text,boolean)',false,'i','54e012d678441ef84bd399625a6d7895d011fe4e328dc2d1093f09e9197528dd'),
    ('edoc.edoc_company_seal_file_dimensions_are_valid(text,text,text,text,text,integer,integer,numeric,numeric,numeric,text,boolean)',false,'i','6c876ebf3bc4aad4a43c4e0e318b3a281ff658e5f5549f4c346217460a474b24'),
    ('edoc.edoc_import_approved_original_scan_file(text,text,text,text,text,bigint,text,integer,integer,numeric,numeric,numeric,text,text,text,text)',true,'v','b0639ceadd5765b95d33bfd64d8cf9c0ee4b2f1e57d3a7a64b7b5b76f3d283ed')
  ) expected(signature,is_definer,volatility,body_sha256) loop
    select * into v_proc from pg_catalog.pg_proc where oid=pg_catalog.to_regprocedure(v_expected.signature);
    if not found then raise exception 'approved_scan_import_rpc_missing'; end if;
    if v_proc.prosecdef is distinct from v_expected.is_definer
       or v_proc.provolatile::text is distinct from v_expected.volatility
       or pg_catalog.pg_get_userbyid(v_proc.proowner)<>'postgres'
       or not coalesce(v_proc.proconfig @> array['search_path=""'],false)
       or not pg_catalog.has_function_privilege(v_backend,v_proc.oid,'EXECUTE')
       or pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(v_proc.prosrc,'UTF8')),'hex')<>v_expected.body_sha256 then
      raise exception 'approved_scan_import_rpc_security_or_source_mismatch';
    end if;
    if v_expected.is_definer and not coalesce(v_proc.proconfig @> array['lock_timeout=5s'],false) then
      raise exception 'approved_scan_import_rpc_lock_timeout_missing';
    end if;
    foreach v_role in array v_denied loop
      if pg_catalog.has_function_privilege(v_role,v_proc.oid,'EXECUTE') then
        raise exception 'approved_scan_import_browser_rpc_grant';
      end if;
    end loop;
    if exists(select 1 from pg_catalog.aclexplode(coalesce(v_proc.proacl,
        pg_catalog.acldefault('f',v_proc.proowner))) a where a.grantee=0 and a.privilege_type='EXECUTE') then
      raise exception 'approved_scan_import_public_rpc_grant';
    end if;
  end loop;
end;
$approved_original_scan_import_gate$;

do $editor_application_seal_policy_gate$
declare
  v_table regclass := pg_catalog.to_regclass('edoc.company_seal_policies');
  v_proc record;
  v_rpc text;
  v_role text;
begin
  if v_table is null or not exists (
    select 1 from pg_catalog.pg_class where oid=v_table and relrowsecurity
      and pg_catalog.pg_get_userbyid(relowner)='postgres'
  ) then raise exception 'editor_application_seal_policy_table_security_missing'; end if;
  foreach v_role in array array['SELECT','INSERT','UPDATE'] loop
    if not pg_catalog.has_table_privilege('edoc_backend',v_table,v_role) then
      raise exception 'editor_application_seal_policy_table_grant_missing';
    end if;
  end loop;
  if pg_catalog.has_table_privilege('edoc_backend',v_table,'DELETE,TRUNCATE,REFERENCES,TRIGGER') then
    raise exception 'editor_application_seal_policy_table_extra_grant';
  end if;
  foreach v_role in array array['anon','authenticated','service_role','authenticator'] loop
    if pg_catalog.has_table_privilege(v_role,v_table,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') then
      raise exception 'editor_application_seal_policy_browser_table_grant';
    end if;
  end loop;
  if exists(select 1 from pg_catalog.aclexplode(coalesce(
      (select relacl from pg_catalog.pg_class where oid=v_table),
      pg_catalog.acldefault('r','postgres'::regrole))) a where a.grantee=0) then
    raise exception 'editor_application_seal_policy_public_table_grant';
  end if;
  foreach v_rpc in array array[
    'edoc.edoc_set_company_seal_policy(text,text,text)',
    'edoc.edoc_update_editor_application(jsonb)',
    'edoc.edoc_save_editor_revision(jsonb)',
    'edoc.edoc_commit_editor_preflight(jsonb)',
    'edoc_private.assert_editor_application_scope(text,text,text,text,text)'
  ] loop
    select * into v_proc from pg_catalog.pg_proc where oid=pg_catalog.to_regprocedure(v_rpc);
    if not found then raise exception 'editor_application_seal_policy_rpc_missing'; end if;
    if v_proc.prosecdef or pg_catalog.pg_get_userbyid(v_proc.proowner)<>'postgres'
       or not coalesce(v_proc.proconfig @> array['search_path=""'],false)
       or not pg_catalog.has_function_privilege('edoc_backend',v_proc.oid,'EXECUTE') then
      raise exception 'editor_application_seal_policy_rpc_security_mismatch';
    end if;
    if v_rpc not like '%edoc_set_company_seal_policy(%'
       and v_rpc not like '%assert_editor_application_scope(%'
       and not coalesce(v_proc.proconfig @> array['lock_timeout=5s'],false) then
      raise exception 'editor_application_rpc_lock_timeout_missing';
    end if;
    foreach v_role in array array['anon','authenticated','service_role','authenticator'] loop
      if pg_catalog.has_function_privilege(v_role,v_proc.oid,'EXECUTE') then
        raise exception 'editor_application_seal_policy_browser_rpc_grant';
      end if;
    end loop;
    if exists(select 1 from pg_catalog.aclexplode(coalesce(v_proc.proacl,
        pg_catalog.acldefault('f',v_proc.proowner))) a where a.grantee=0 and a.privilege_type='EXECUTE') then
      raise exception 'editor_application_seal_policy_public_rpc_grant';
    end if;
  end loop;
end;
$editor_application_seal_policy_gate$;

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
  foreach v_rpc in array array['edoc_confirm_official_document(jsonb)','edoc_list_official_document_candidates(jsonb)','edoc_list_inbound_candidates(jsonb)','edoc_timeliness_candidates(jsonb)'] loop
    select * into v_proc from pg_catalog.pg_proc where oid=pg_catalog.to_regprocedure('edoc.' || v_rpc);
    if not found then raise exception 'worklist_receipt_rpc_missing'; end if;
    if v_proc.prosecdef or pg_catalog.pg_get_userbyid(v_proc.proowner)<>'postgres'
       or not coalesce(v_proc.proconfig @> array['search_path=""'],false)
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
  foreach v_rpc in array array['edoc_save_official_workflow_config(jsonb)','edoc_mutate_official_workflow(jsonb)','edoc_decline_official_document(jsonb)'] loop
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
         and class_row.relkind in ('r','p','v','m')) = 99,
      (select count(*)::text from pg_catalog.pg_class class_row
       join pg_catalog.pg_namespace namespace_row on namespace_row.oid = class_row.relnamespace
       where namespace_row.nspname = 'edoc'
         and class_row.relkind in ('r','p','v','m'))
    ),
    (
      'migration_ledger_complete',
      (select count(*) from edoc_private.shared_project_migration_ledger) = 74
      and exists(select 1 from edoc_private.shared_project_migration_ledger
        where file_name='20261013125111_approved_native120_scan_exception.sql'
          and source_sha256='6aabdb1587e82eb2e6c8124e1b18157c296662e84f58c10497b400585dd216c9'
          and transformed_sha256='68e48b22e1374218d6351c6e9454eb7a8ffd30e049fe6440cef8e612e8a11a19')
      and exists(select 1 from edoc_private.shared_project_migration_ledger
        where file_name='20261013070841_approved_original_scan_exception.sql'
          and source_sha256='ce8c72275232d689afdeee7376a2d69ce6fd67282cfdfd4477da8bb9d2205565'
          and transformed_sha256='f85521c9a4a187d1135124441647e8535b0e402f1e0edcc7d3e93517720087d9')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20261012114854_explicit_seal_owner_policy_and_continuous_geometry.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20261012115431_editor_application_final_snapshot.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260911133144_compose_resilience_drafts_revision.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260911133603_editor_conflict_copy_atomic.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260913055452_editor_applicant_selection_scope.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260913060040_editor_cross_company_workflow_scope.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260913130517_editor_storage_v2_opaque_paths.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260922074613_configurable_official_workflows.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260924154226_atomic_official_receipt_confirmation.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260924154315_scoped_official_document_listing.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260924155456_latest_generation_dispatch_owner.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20260925044708_editor_pdf_uploads_skip_antivirus_preflight_required.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='20261006154028_terminal_official_decline.sql')
      and exists(select 1 from edoc_private.shared_project_migration_ledger
        where file_name='20261011140824_complete_workflow_readiness_queries.sql'
          and source_sha256='40efe371be67265a846c1a67c8c9a7ff874beb14541c767fcc06a31c89867ad2'
          and transformed_sha256='ad0c1917f457b30815ee0d42e5be30c051518ecca824be0eb83b16a7aa3e8425'),
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
