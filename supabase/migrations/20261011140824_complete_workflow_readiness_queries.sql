-- Read-only candidate RPCs: authoritative Finance scope and ACL precede paging.
create index if not exists idx_inbound_scope_keyset on public.inbound_documents(company_id,finance_tenant_id,created_at desc,id desc);
create index if not exists idx_inbound_status_keyset on public.inbound_documents(company_id,finance_tenant_id,status,created_at desc,id desc);
create index if not exists idx_inbound_assignee_keyset on public.inbound_documents(assignee_user_id,company_id,finance_tenant_id,created_at desc,id desc);
create index if not exists idx_dispatch_inbound_acl on public.internal_dispatches(inbound_document_id,id);
create index if not exists idx_dispatch_recipient_acl on public.internal_dispatch_recipients(recipient_user_id,dispatch_id);

create or replace function public.edoc_list_inbound_candidates(p_request jsonb)
returns jsonb language plpgsql stable security invoker set search_path='' as $function$
declare
 v_actor text:=nullif(p_request->>'actor_id',''); v_company text; v_tenant text;
 v_limit integer:=coalesce((p_request->>'limit')::integer,51);
 v_after_created text:=nullif(p_request->>'after_created_at','');
 v_after_id text:=nullif(p_request->>'after_id',''); v_result jsonb;
begin
 if v_actor is null or v_limit not between 1 and 101 or (v_after_created is null)<>(v_after_id is null)
 then raise exception using errcode='22023',message='inbound_list_filter_invalid'; end if;
 select u.company_id,u.finance_tenant_id into v_company,v_tenant
 from public.users u join public.companies c on c.id=u.company_id
 where u.id=v_actor and u.status='啟用' and u.account_source='finance' and c.status='active' and c.source_system='finance'
 and nullif(u.finance_tenant_id,'') is not null and c.finance_tenant_id=u.finance_tenant_id;
 if not found or v_company is distinct from p_request->>'company_id' or v_tenant is distinct from p_request->>'finance_tenant_id'
 then raise exception using errcode='42501',message='inbound_list_scope_forbidden'; end if;
 with filtered as materialized (
  select d.* from public.inbound_documents d
  where d.company_id=v_company and d.finance_tenant_id=v_tenant
  and (nullif(p_request->>'status','') is null or d.status=p_request->>'status')
  and (nullif(p_request->>'assignee_user_id','') is null or d.assignee_user_id=p_request->>'assignee_user_id')
  and (nullif(p_request->>'q','') is null or pg_catalog.strpos(pg_catalog.lower(coalesce(d.subject,'')||' '||coalesce(d.receive_no,'')||' '||coalesce(d.sender_name,'')),pg_catalog.lower(p_request->>'q'))>0)
  and (coalesce((p_request->>'company_wide')::boolean,false) or d.assignee_user_id=v_actor or d.created_by=v_actor
   or exists(select 1 from public.internal_dispatches x join public.internal_dispatch_recipients r on r.dispatch_id=x.id
    where x.inbound_document_id=d.id and r.recipient_user_id=v_actor))
 ), candidates as (
  select d.* from filtered d where v_after_created is null or (d.created_at,d.id)<(v_after_created::timestamptz,v_after_id)
  order by d.created_at desc,d.id desc limit v_limit
 ) select pg_catalog.jsonb_build_object('count',(select count(*) from filtered),
  'items',coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(d) order by d.created_at desc,d.id desc),'[]'::jsonb))
 into v_result from candidates d;
 return v_result;
end $function$;
revoke all on function public.edoc_list_inbound_candidates(jsonb) from public,anon,authenticated;
grant execute on function public.edoc_list_inbound_candidates(jsonb) to service_role;

create or replace function public.edoc_timeliness_candidates(p_request jsonb)
returns jsonb language plpgsql stable security invoker set search_path='' as $function$
declare
 v_actor text:=nullif(p_request->>'actor_id',''); v_company text; v_tenant text;
 v_limit integer:=coalesce((p_request->>'limit')::integer,501);
 v_after_source text:=nullif(p_request->>'after_source',''); v_after_id text:=nullif(p_request->>'after_id',''); v_result jsonb;
begin
 if v_actor is null or v_limit not between 1 and 501 or (v_after_source is null)<>(v_after_id is null)
 then raise exception using errcode='22023',message='timeliness_filter_invalid'; end if;
 select u.company_id,u.finance_tenant_id into v_company,v_tenant from public.users u
 join public.companies c on c.id=u.company_id where u.id=v_actor and u.status='啟用' and u.account_source='finance'
 and c.status='active' and c.source_system='finance' and nullif(u.finance_tenant_id,'') is not null
 and c.finance_tenant_id=u.finance_tenant_id;
 if not found or v_company is distinct from p_request->>'company_id' or v_tenant is distinct from p_request->>'finance_tenant_id'
 then raise exception using errcode='42501',message='timeliness_scope_forbidden'; end if;
 with metrics as (
  select 'inbound'::text as source,d.id,d.created_at::text as entered_at,d.due_at
  from public.inbound_documents d where d.company_id=v_company and d.finance_tenant_id=v_tenant
  and d.closed_at is null and d.status not in ('closed','archived','cancelled')
  union all
  select 'reply',r.id,r.created_at,x.due_at from public.internal_dispatch_recipients r
  join public.internal_dispatches x on x.id=r.dispatch_id
  left join public.inbound_documents i on i.id=x.inbound_document_id
  left join public.official_documents o on o.id=x.official_document_id
  left join public.companies c on c.id=o.company_id
  left join public.users sender on sender.id=x.sender_user_id
  where r.action_required=true and nullif(r.replied_at,'') is null and nullif(x.closed_at,'') is null
  and x.status not in ('closed','archived','cancelled')
  and (case when nullif(x.inbound_document_id,'') is not null then i.company_id=v_company and i.finance_tenant_id=v_tenant
   when nullif(x.official_document_id,'') is not null then o.company_id=v_company and c.finance_tenant_id=v_tenant
   else sender.company_id=v_company and sender.finance_tenant_id=v_tenant and sender.status='啟用' end)
  union all
  select 'approval',s.id,case when s.step_order=1 then s.created_at
   when previous.approved_at is null then '' else greatest(s.created_at,previous.approved_at) end,''::text
  from public.official_documents o join public.companies c on c.id=o.company_id
  join public.official_document_approval_steps s on s.document_id=o.id and s.step_key=o.current_step and s.status='pending'
  left join lateral(select p.approved_at from public.official_document_approval_steps p
   where p.document_id=o.id and p.workflow_generation=s.workflow_generation and p.step_order<s.step_order
   order by p.step_order desc limit 1) previous on true
  where o.company_id=v_company and c.finance_tenant_id=v_tenant and s.step_key<>'applicant_confirm'
  and pg_catalog.substr(o.current_status,1,8)='pending_'
  and s.workflow_generation=(select max(g.workflow_generation) from public.official_document_approval_steps g where g.document_id=o.id)
 ), candidates as (
  select * from metrics m where v_after_source is null or (m.source,m.id)>(v_after_source,v_after_id)
  order by m.source,m.id limit v_limit
 ) select pg_catalog.jsonb_build_object('items',coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(m) order by m.source,m.id),'[]'::jsonb))
 into v_result from candidates m;
 return v_result;
end $function$;
revoke all on function public.edoc_timeliness_candidates(jsonb) from public,anon,authenticated;
grant execute on function public.edoc_timeliness_candidates(jsonb) to service_role;
