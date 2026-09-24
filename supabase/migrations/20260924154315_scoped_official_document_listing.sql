-- Bound candidate pages before hydration; no global 300-row cutoff or HTTP N+1.
create index if not exists idx_official_list_keyset on public.official_documents(created_at desc,id desc);
create index if not exists idx_official_list_applicant_keyset on public.official_documents(applicant_id,created_at desc,id desc);
create index if not exists idx_official_list_company_keyset on public.official_documents(company_id,created_at desc,id desc);
create index if not exists idx_official_list_step_actor on public.official_document_approval_steps(document_id,approver_user_id);
create index if not exists idx_official_list_decision_actor on public.official_document_approval_steps(document_id,decision_actor_user_id) where decision_actor_user_id is not null;
create index if not exists idx_official_list_snapshot_actor on public.approval_step_actor_snapshots(source_id,source_type,approver_user_id);
create index if not exists idx_official_list_dispatch_latest on public.official_document_dispatch_records(document_id,created_at desc,id desc);
create index if not exists idx_official_list_stamp_latest on public.official_document_stamp_requests(document_id,created_at desc,id desc);
create index if not exists idx_official_list_decision_logs on public.official_document_approval_logs(document_id,created_at,id) where action in ('approve','add_sign','reject','confirm');

create or replace function public.edoc_list_official_document_candidates(p_request jsonb)
returns jsonb language plpgsql stable security invoker set search_path='' as $function$
declare
  v_actor_id text := nullif(pg_catalog.btrim(p_request->>'actor_id'),'');
  v_actor_company text;
  v_limit integer := coalesce((p_request->>'limit')::integer,100);
  v_scope text := coalesce(p_request->>'scope','');
  v_company_wide boolean := coalesce((p_request->>'company_wide')::boolean,false);
  v_after_created text := nullif(p_request->>'after_created_at','');
  v_after_id text := nullif(p_request->>'after_id','');
  v_result jsonb;
begin
  if v_actor_id is null or v_limit not between 1 and 100
     or (v_after_created is null) <> (v_after_id is null) then
    raise exception using errcode='22023',message='official_list_filter_invalid';
  end if;
  select u.company_id into v_actor_company from public.users u where u.id=v_actor_id and u.status='啟用';
  if not found then raise exception using errcode='42501',message='official_list_actor_inactive'; end if;

  with candidates as materialized (
    select d.* from public.official_documents d
    where (nullif(p_request->>'status','') is null or d.current_status=p_request->>'status')
      and (nullif(p_request->>'company_id','') is null or d.company_id=p_request->>'company_id')
      and (nullif(p_request->>'applicant_id','') is null or d.applicant_id=p_request->>'applicant_id')
      and (v_scope<>'mine' or d.applicant_id=v_actor_id)
      and (v_after_created is null or (d.created_at,d.id)<(v_after_created,v_after_id))
      and (
        d.applicant_id=v_actor_id
        or (v_company_wide and nullif(v_actor_company,'') is not null and d.company_id=v_actor_company)
        or exists(select 1 from public.official_document_approval_steps s where s.document_id=d.id
          and (s.approver_user_id=v_actor_id or s.decision_actor_user_id=v_actor_id))
        or exists(select 1 from public.approval_step_actor_snapshots a where a.source_id=d.id
          and a.source_type in ('official_document','official_documents','official_document_application')
          and a.approver_user_id=v_actor_id)
        or exists(
          select 1 from public.official_workflow_delegations x
          join public.official_document_approval_steps s on s.document_id=d.id
            and s.approver_user_id=x.principal_user_id and s.step_key=d.current_step and s.status='pending'
            and s.step_key<>'applicant_confirm'
          where x.company_id=d.company_id and x.delegate_user_id=v_actor_id and x.status='active'
            and x.starts_at::timestamp<=localtimestamp and x.ends_at::timestamp>localtimestamp
            and s.workflow_generation=(select max(g.workflow_generation) from public.official_document_approval_steps g where g.document_id=d.id)
        )
      )
    order by d.created_at desc,d.id desc limit v_limit
  ), bundles as (
    select d.created_at,d.id,pg_catalog.jsonb_build_object(
      'document',pg_catalog.to_jsonb(d),
      'steps',coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(s) order by s.workflow_generation,s.step_order,s.id)
        from public.official_document_approval_steps s where s.document_id=d.id),'[]'::jsonb),
      'snapshots',coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(a) order by a.created_at,a.id)
        from public.approval_step_actor_snapshots a where a.source_id=d.id
          and a.source_type in ('official_document','official_documents','official_document_application')),'[]'::jsonb),
      'dispatch_record',pg_catalog.to_jsonb(dispatch),
      'stamp_request',pg_catalog.to_jsonb(stamp),
      'decision_logs',coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(l) order by l.created_at,l.id)
        from public.official_document_approval_logs l where l.document_id=d.id
          and l.action in ('approve','add_sign','reject','confirm')),'[]'::jsonb),
      'delegations',coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(x) order by x.starts_at,x.id)
        from public.official_workflow_delegations x where x.company_id=d.company_id
          and x.delegate_user_id=v_actor_id and x.status='active'),'[]'::jsonb),
      -- Only current Finance qualification fields are needed, never passwords,
      -- session material, email, or a complete users-table record.
      'delegation_users',coalesce((select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id',u.id,'name',u.name,'status',u.status,'company_id',u.company_id,'account_source',u.account_source,
          'auth_user_id',u.auth_user_id,'finance_employee_id',u.finance_employee_id,'title',u.title,
          'logging_role_key',u.logging_role_key,'role',u.role,'job_level',u.job_level) order by u.id)
        from public.users u where u.id=v_actor_id or exists(
          select 1 from public.official_workflow_delegations x where x.company_id=d.company_id
            and x.delegate_user_id=v_actor_id and x.status='active' and x.principal_user_id=u.id)),'[]'::jsonb),
      'dispatch_owner_name',(select u.name from public.users u where u.id=dispatch.dispatch_owner_user_id),
      'dispatch_proof',(select pg_catalog.to_jsonb(f) from public.official_document_files f
        where f.document_id=d.id and f.id=dispatch.proof_file_id)
    ) as item
    from candidates d
    left join lateral (select r.* from public.official_document_dispatch_records r where r.document_id=d.id
      order by r.created_at desc,r.id desc limit 1) dispatch on true
    left join lateral (select r.* from public.official_document_stamp_requests r where r.document_id=d.id
      order by r.created_at desc,r.id desc limit 1) stamp on true
  )
  select pg_catalog.jsonb_build_object('items',coalesce(pg_catalog.jsonb_agg(item order by created_at desc,id desc),'[]'::jsonb))
    into v_result from bundles;
  return v_result;
end $function$;
revoke all on function public.edoc_list_official_document_candidates(jsonb) from public,anon,authenticated;
grant execute on function public.edoc_list_official_document_candidates(jsonb) to service_role;
