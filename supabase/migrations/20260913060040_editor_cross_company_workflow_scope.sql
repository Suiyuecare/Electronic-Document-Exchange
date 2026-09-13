-- V2 selected-company cases keep their real Finance applicant/approvers.
-- These private predicates add only a same-verified-tenant exception to the
-- existing exact actor/step/owner checks. Generic company access is unchanged.
create or replace function edoc_private.editor_v2_actor_in_company_scope(p_document_id text, p_actor_id text)
returns boolean language sql stable security invoker set search_path = '' as $function$
  select exists (
    select 1 from public.official_documents as document
    join public.companies as company on company.id = document.company_id
    join public.users as applicant on applicant.id = document.applicant_id
    join public.users as actor on actor.id = p_actor_id
    where document.id = p_document_id and document.source_type = 'uploaded_pdf'
      and coalesce(document.metadata_json::jsonb->>'pdf_editor_v2', 'false') = 'true'
      and company.source_system = 'finance' and company.status in ('active', '啟用')
      and nullif(btrim(company.finance_entity_id), '') is not null
      and nullif(btrim(company.finance_tenant_id::text), '') is not null
      and applicant.finance_tenant_id = company.finance_tenant_id and applicant.status = '啟用'
      and actor.finance_tenant_id = company.finance_tenant_id and actor.status = '啟用'
  )
$function$;

create or replace function edoc_private.editor_v2_case_participant(p_document_id text, p_actor_id text)
returns boolean language sql stable security invoker set search_path = '' as $function$
  select edoc_private.editor_v2_actor_in_company_scope(p_document_id, p_actor_id) and (
    exists (select 1 from public.official_documents where id = p_document_id and applicant_id = p_actor_id)
    or exists (select 1 from public.official_document_approval_steps
      where document_id = p_document_id and (approver_user_id = p_actor_id or decision_actor_user_id = p_actor_id))
    or exists (select 1 from public.approval_step_actor_snapshots
      where source_type in ('official_document','official_documents','official_document_application')
        and source_id = p_document_id and approver_user_id = p_actor_id)
  )
$function$;

create or replace function edoc_private.assert_official_document_decision_actor(
  p_document_id text, p_company_id text, p_principal_user_id text, p_decision_actor_user_id text
) returns void language plpgsql security invoker set search_path = '' as $function$
declare v_now timestamptz := pg_catalog.clock_timestamp();
begin
  if not exists (select 1 from public.official_documents where id = p_document_id and company_id = p_company_id) then
    raise exception using errcode = '42501', message = 'official_document_company_forbidden';
  end if;
  if not edoc_private.editor_v2_actor_in_company_scope(p_document_id, p_principal_user_id)
     or not edoc_private.editor_v2_actor_in_company_scope(p_document_id, p_decision_actor_user_id) then
    -- Retain precisely the old boundary for non-V2 or non-qualified actors.
    perform edoc_private.assert_official_decision_actor(p_company_id, p_principal_user_id, p_decision_actor_user_id);
    return;
  end if;
  if not exists (select 1 from public.official_document_approval_steps
      where document_id = p_document_id and approver_user_id = p_principal_user_id) then
    raise exception using errcode = '42501', message = 'not_current_official_document_approver';
  end if;
  if p_decision_actor_user_id <> p_principal_user_id and not exists (
    select 1 from public.official_workflow_delegations as delegation
    where delegation.company_id = p_company_id and delegation.principal_user_id = p_principal_user_id
      and delegation.delegate_user_id = p_decision_actor_user_id and delegation.status = 'active'
      and delegation.starts_at <= v_now and delegation.ends_at > v_now
  ) then
    raise exception using errcode = '42501', message = 'official_workflow_delegation_not_active';
  end if;
end
$function$;

revoke all on function edoc_private.editor_v2_actor_in_company_scope(text,text) from public,anon,authenticated,service_role;
revoke all on function edoc_private.editor_v2_case_participant(text,text) from public,anon,authenticated,service_role;
revoke all on function edoc_private.assert_official_document_decision_actor(text,text,text,text) from public,anon,authenticated,service_role;

do $migration$
declare v_proc regprocedure; v_sql text; v_old text; v_new text;
begin
  -- The callers still prove the exact requested step/principal, self-approval
  -- prohibition, immutable review hashes and lock order. Pass document context
  -- to a new wrapper; never broaden the old three-argument helper globally.
  for v_proc in select unnest(array[
    'public.edoc_claim_official_document_approval_v2(text,text,text,text,text,jsonb)'::regprocedure,
    'public.edoc_claim_official_document_rejection_v2(text,text,text,text,text,jsonb)'::regprocedure,
    'edoc_private.validate_official_document_decision_evidence(text,text,text,text,text,jsonb)'::regprocedure
  ]) loop
    v_sql := pg_catalog.pg_get_functiondef(v_proc);
    v_old := E'perform edoc_private.assert_official_decision_actor(\n    v_document.company_id,';
    v_new := E'perform edoc_private.assert_official_document_decision_actor(\n    v_document.id, v_document.company_id,';
    if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'editor_decision_scope_call_drift'; end if;
    execute pg_catalog.replace(v_sql, v_old, v_new);
  end loop;

  v_proc := 'public.edoc_claim_official_document_approval_v2(text,text,text,text,text,jsonb)'::regprocedure;
  v_sql := pg_catalog.pg_get_functiondef(v_proc);
  v_old := 'and next_actor.company_id = v_document.company_id';
  v_new := 'and (next_actor.company_id = v_document.company_id or edoc_private.editor_v2_actor_in_company_scope(v_document.id,next_actor.id))';
  if pg_catalog.strpos(v_sql,v_old)=0 then raise exception 'editor_next_actor_scope_drift'; end if;
  v_sql := pg_catalog.replace(v_sql,v_old,v_new);
  v_old := E'v_document.company_id,\n        (select u.email';
  v_new := E'(select u.company_id from public.users as u where u.id = v_result#>>''{next_step,approver_user_id}''),\n        (select u.email';
  if pg_catalog.strpos(v_sql,v_old)=0 then raise exception 'editor_next_notification_scope_drift'; end if;
  execute pg_catalog.replace(v_sql,v_old,v_new);

  v_proc := 'public.edoc_claim_official_document_rejection_v2(text,text,text,text,text,jsonb)'::regprocedure;
  v_sql := pg_catalog.pg_get_functiondef(v_proc);
  v_old := 'and applicant.company_id = v_document.company_id';
  v_new := 'and (applicant.company_id = v_document.company_id or edoc_private.editor_v2_actor_in_company_scope(v_document.id,applicant.id))';
  if pg_catalog.strpos(v_sql,v_old)=0 then raise exception 'editor_return_actor_scope_drift'; end if;
  v_sql := pg_catalog.replace(v_sql,v_old,v_new);
  v_old := E'v_document.company_id,\n      (select u.email';
  v_new := E'(select u.company_id from public.users as u where u.id = v_document.applicant_id),\n      (select u.email';
  if pg_catalog.strpos(v_sql,v_old)=0 then raise exception 'editor_return_notification_scope_drift'; end if;
  execute pg_catalog.replace(v_sql,v_old,v_new);

  v_proc := 'public.edoc_create_official_document_dispatch_record(text,text)'::regprocedure;
  v_sql := pg_catalog.pg_get_functiondef(v_proc);
  v_old := 'and actor.company_id = v_document.company_id';
  v_new := 'and (actor.company_id = v_document.company_id or edoc_private.editor_v2_case_participant(v_document.id,actor.id))';
  if pg_catalog.strpos(v_sql,v_old)=0 then raise exception 'editor_dispatch_actor_scope_drift'; end if;
  execute pg_catalog.replace(v_sql,v_old,v_new);

  v_proc := 'public.edoc_complete_official_document_dispatch(text,text,text,text,text,text,text,text,text,text)'::regprocedure;
  v_sql := pg_catalog.pg_get_functiondef(v_proc);
  v_old := 'and app_user.company_id = v_document.company_id';
  v_new := 'and (app_user.company_id = v_document.company_id or edoc_private.editor_v2_case_participant(v_document.id,app_user.id))';
  if (pg_catalog.length(v_sql)-pg_catalog.length(pg_catalog.replace(v_sql,v_old,''))) / pg_catalog.length(v_old) <> 2 then
    raise exception 'editor_dispatch_complete_scope_drift';
  end if;
  execute pg_catalog.replace(v_sql,v_old,v_new);

  v_proc := 'public.edoc_register_official_archive_export(text,text,text,text,text,integer,bigint,text,text,text)'::regprocedure;
  v_sql := pg_catalog.pg_get_functiondef(v_proc);
  v_old := 'if v_user.company_id is distinct from v_document.company_id then';
  v_new := 'if v_user.company_id is distinct from v_document.company_id and not edoc_private.editor_v2_case_participant(v_document.id,v_user.id) then';
  if pg_catalog.strpos(v_sql,v_old)=0 then raise exception 'editor_archive_actor_scope_drift'; end if;
  execute pg_catalog.replace(v_sql,v_old,v_new);
end
$migration$;
