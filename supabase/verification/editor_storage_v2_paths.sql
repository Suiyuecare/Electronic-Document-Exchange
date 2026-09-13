-- Read-only deployment contract. Real insert/finalize behavior is exercised by
-- the PostgreSQL + PostgREST/Storage CI gates, not inferred from this check.
do $editor_storage_v2_path_gate$
declare
  v_definition text;
  v_proc record;
  v_name text;
begin
  select pg_catalog.pg_get_constraintdef(oid) into v_definition
  from pg_catalog.pg_constraint
  where conrelid = 'public.official_document_editor_storage_jobs'::regclass
    and conname = 'official_editor_storage_job_path_check' and convalidated;
  if v_definition is null or v_definition not like '%pdf%'
     or v_definition not like '%png%' or v_definition not like '%jpg%' then
    raise exception 'editor_storage_v2_path_constraint_missing';
  end if;
  foreach v_name in array array['edoc_guard_editor_storage_job','edoc_bind_finalized_editor_asset_storage'] loop
    select * into v_proc from pg_catalog.pg_proc
    where oid=pg_catalog.to_regprocedure('public.' || v_name || '()');
    if not found or v_proc.prosrc not like '%storage_key_version%'
       or v_proc.prosrc not like '%image/jpeg%'
       or v_proc.prosrc not like '%editor-final/%'
       or not coalesce(v_proc.proconfig @> array['search_path=""'],false) then
      raise exception 'editor_storage_v2_trigger_missing';
    end if;
    if exists(select 1 from pg_catalog.aclexplode(coalesce(v_proc.proacl,pg_catalog.acldefault('f',v_proc.proowner))) a
      where a.grantee=0 and a.privilege_type='EXECUTE')
      or pg_catalog.has_function_privilege('anon',v_proc.oid,'EXECUTE')
      or pg_catalog.has_function_privilege('authenticated',v_proc.oid,'EXECUTE') then
      raise exception 'editor_storage_v2_trigger_browser_grant';
    end if;
  end loop;
end;
$editor_storage_v2_path_gate$;
