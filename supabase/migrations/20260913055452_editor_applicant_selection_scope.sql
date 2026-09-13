-- Creation-only V2 application scope. The real actor/Finance role stays intact;
-- no company-record access, browser grants, company mutation or file reparenting.
do $migration$
declare
  v_proc regprocedure;
  v_sql text;
  v_old text;
  v_new text;
begin
  v_proc := 'public.edoc_apply_official_document_correction(text,text,text,jsonb,text,jsonb,jsonb,text,jsonb,jsonb,text,text,text,text,text,text,jsonb,text,text)'::regprocedure;
  v_sql := pg_catalog.pg_get_functiondef(v_proc);
  v_old := '''dispatch_unit'', ''handler_name'', ''request_reason'',';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'editor_applicant_patch_keys_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old, v_old || ' ''applicant_department_id'', ''applicant_department_name'',');
  v_old := '         dispatch_unit = case when p_patch ? ''dispatch_unit'' then p_patch->>''dispatch_unit'' else dispatch_unit end,';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'editor_applicant_patch_write_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old, v_old || $snippet$
         applicant_department_id = case when p_patch ? 'applicant_department_id' then p_patch->>'applicant_department_id' else applicant_department_id end,
         applicant_department_name = case when p_patch ? 'applicant_department_name' then p_patch->>'applicant_department_name' else applicant_department_name end,
$snippet$);
  v_old := '  select actor.*';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'editor_applicant_patch_validation_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old, $snippet$
  if p_patch ? 'applicant_department_id' or p_patch ? 'applicant_department_name' then
    if v_document.source_type <> 'uploaded_pdf'
       or coalesce(v_document.metadata_json::jsonb->>'pdf_editor_v2', 'false') <> 'true'
       or nullif(btrim(p_patch->>'applicant_department_id'), '') is null
       or nullif(btrim(p_patch->>'applicant_department_name'), '') is null
       or p_patch->>'dispatch_unit' is distinct from p_patch->>'applicant_department_name' then
      raise exception using errcode = '42501', message = 'finance_unit_payload_mismatch';
    end if;
    if (select count(*) from public.finance_organization_units as unit
          join public.companies as company on company.id = v_document.company_id
         where unit.finance_tenant_id = company.finance_tenant_id
           and upper(unit.code) = upper(p_patch->>'applicant_department_id')
           and unit.status = 'active') <> 1
       or not exists (select 1 from public.finance_organization_units as unit
          join public.companies as company on company.id = v_document.company_id
         where unit.finance_tenant_id = company.finance_tenant_id
           and upper(unit.code) = upper(p_patch->>'applicant_department_id')
           and unit.name = p_patch->>'applicant_department_name' and unit.status = 'active') then
      raise exception using errcode = '42501', message = 'finance_unit_projection_unavailable';
    end if;
  end if;
  select actor.*
$snippet$);
  execute v_sql;

  -- Both functions already lock the document and require its actual applicant.
  -- Retain the old path for every non-V2 case and add only same-tenant V2 scope.
  for v_proc in select unnest(array[
    'public.edoc_apply_official_document_correction(text,text,text,jsonb,text,jsonb,jsonb,text,jsonb,jsonb,text,text,text,text,text,text,jsonb,text,text)'::regprocedure,
    'public.edoc_finalize_official_document_resubmit(text,text,text,timestamp with time zone,text,text,text,text,text)'::regprocedure
  ]) loop
    v_sql := pg_catalog.pg_get_functiondef(v_proc);
    v_old := '     and actor.company_id = p_company_id';
    if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'editor_applicant_actor_scope_drift'; end if;
    v_new := $snippet$
     and (actor.company_id = p_company_id or (
       v_document.source_type = 'uploaded_pdf'
       and coalesce(v_document.metadata_json::jsonb->>'pdf_editor_v2', 'false') = 'true'
       and nullif(btrim(actor.finance_tenant_id::text), '') is not null
       and exists (select 1 from public.companies as company
         where company.id = p_company_id and company.finance_tenant_id = actor.finance_tenant_id
           and company.source_system = 'finance' and company.status in ('active', '啟用')
           and nullif(btrim(company.finance_entity_id), '') is not null)
     ))
$snippet$;
    execute pg_catalog.replace(v_sql, v_old, v_new);
  end loop;

  v_proc := 'public.edoc_copy_editor_conflict(jsonb)'::regprocedure;
  v_sql := pg_catalog.pg_get_functiondef(v_proc);
  v_old := 'SELECT 1 FROM public.users WHERE id = v_actor AND company_id = v_source.company_id AND status = ''啟用''';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'editor_applicant_copy_scope_drift'; end if;
  v_new := $snippet$SELECT 1 FROM public.users as actor WHERE actor.id = v_actor AND actor.status = '啟用'
    AND (actor.company_id = v_source.company_id OR (
      v_source.source_type = 'uploaded_pdf'
      AND coalesce(v_source.metadata_json::jsonb->>'pdf_editor_v2', 'false') = 'true'
      AND nullif(btrim(actor.finance_tenant_id::text), '') IS NOT NULL
      AND EXISTS (SELECT 1 FROM public.companies as company WHERE company.id = v_source.company_id
        AND company.finance_tenant_id = actor.finance_tenant_id AND company.source_system = 'finance'
        AND company.status IN ('active', '啟用') AND nullif(btrim(company.finance_entity_id), '') IS NOT NULL)
    ))$snippet$;
  execute pg_catalog.replace(v_sql, v_old, v_new);
end $migration$;
