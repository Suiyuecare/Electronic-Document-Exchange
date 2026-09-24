-- Atomic applicant receipt with an explicit, immutable actual-actor witness.
-- Runs with the existing backend table/RLS privileges, never as a definer.
create or replace function public.edoc_confirm_official_document(p_request jsonb)
returns jsonb language plpgsql security invoker set search_path='' set lock_timeout='5s' as $function$
declare
  v_document public.official_documents%rowtype;
  v_step public.official_document_approval_steps%rowtype;
  v_actor public.users%rowtype;
  v_dispatch public.official_document_dispatch_records%rowtype;
  v_dispatch_result jsonb;
  v_generation integer;
  v_actor_id text := nullif(pg_catalog.btrim(p_request->>'actor_id'),'');
  v_expected_step text := nullif(pg_catalog.btrim(p_request->>'expected_step_id'),'');
  v_log_id text;
  v_time text := pg_catalog.to_char(pg_catalog.clock_timestamp(),'YYYY-MM-DD HH24:MI:SS');
  v_comment text := coalesce(nullif(p_request->>'comment',''),'申請人確認已用印版本');
  v_evidence jsonb;
begin
  if v_actor_id is null or v_expected_step is null or p_request->>'workflow_generation' is null then
    raise exception using errcode='22023',message='official_document_receipt_step_conflict';
  end if;
  -- Match dispatch's lock order before taking the document row lock.
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('edoc:official-dispatch:' || (p_request->>'document_id'),0));
  select * into v_document from public.official_documents where id=p_request->>'document_id' for update;
  if not found then raise exception using errcode='P0002',message='official_document_not_found'; end if;
  select * into v_actor from public.users where id=v_actor_id and status='啟用';
  if not found or v_document.applicant_id is distinct from v_actor_id then
    raise exception using errcode='42501',message='only_applicant_can_confirm';
  end if;
  select max(workflow_generation) into v_generation from public.official_document_approval_steps where document_id=v_document.id;
  select * into v_step from public.official_document_approval_steps
    where id=v_expected_step and document_id=v_document.id and workflow_generation=v_generation
      and step_key='applicant_confirm' for update;
  if not found or v_step.approver_user_id is distinct from v_actor_id
     or v_generation is distinct from (p_request->>'workflow_generation')::integer
     or (select count(*) from public.official_document_approval_steps where document_id=v_document.id
         and workflow_generation=v_generation and step_key='applicant_confirm') <> 1 then
    raise exception using errcode='22023',message='official_document_receipt_step_conflict';
  end if;
  v_log_id := 'ODLOG-CONFIRM-' || pg_catalog.md5(v_step.id);
  if v_document.current_status='closed' and v_step.status='approved'
     and v_step.decision_actor_user_id=v_actor_id and exists (
       select 1 from public.official_document_approval_logs
       where id=v_log_id and document_id=v_document.id and step_id=v_step.id and action='confirm' and actor_id=v_actor_id
     ) and exists (
       select 1 from public.audit_logs where id='AUD-' || v_log_id and action='confirm'
         and target_id=v_document.id and actor_user_id=v_actor_id
     ) then
    return pg_catalog.jsonb_build_object('confirmed',true,'idempotent',true,'document_id',v_document.id,
      'step_id',v_step.id,'actor_id',v_actor_id,'approval_log_id',v_log_id);
  end if;
  if v_document.current_status not in ('returned_to_applicant_for_send','stamped','dispatched','sent_by_applicant')
     or v_step.status is distinct from 'pending' or exists (
       select 1 from public.official_document_approval_steps where document_id=v_document.id
       and workflow_generation=v_generation and id<>v_step.id and status is distinct from 'approved'
     ) then
    raise exception using errcode='22023',message='official_document_not_ready_for_applicant_confirm';
  end if;
  if v_document.current_status='returned_to_applicant_for_send' then
    select * into v_dispatch from public.official_document_dispatch_records
      where document_id=v_document.id order by created_at desc,id desc limit 1 for update;
    if not found then
      v_dispatch_result := public.edoc_create_official_document_dispatch_record(v_document.id,v_actor_id);
      select * into v_dispatch from public.official_document_dispatch_records
        where id=v_dispatch_result->>'dispatch_record_id' and document_id=v_document.id for update;
    end if;
    if v_dispatch.id is null or v_dispatch.dispatch_owner_type is distinct from 'applicant'
       or v_dispatch.dispatch_owner_user_id is distinct from v_actor_id then
      raise exception using errcode='42501',message='official_dispatch_complete_forbidden';
    end if;
    -- Existing dispatch guards validate proof, dates, and the current owner.
    -- This nested database call shares the receipt transaction and never sends
    -- to an external exchange provider.
    v_dispatch_result := public.edoc_complete_official_document_dispatch(
      v_document.id,v_dispatch.id,v_actor_id,
      p_request#>>'{dispatch,external_official_document_number}',p_request#>>'{dispatch,dispatch_date}',
      p_request#>>'{dispatch,recipient}',p_request#>>'{dispatch,recipient_contact}',p_request#>>'{dispatch,dispatch_note}',
      coalesce(p_request->>'ip_address',''),pg_catalog.left(coalesce(p_request->>'user_agent',''),180));
    if (v_dispatch_result->>'completed')::boolean is distinct from true then
      raise exception using errcode='22023',message='official_dispatch_completion_conflict';
    end if;
    select * into v_document from public.official_documents where id=v_document.id;
  end if;
  if v_document.current_step is distinct from 'applicant_confirm' then
    raise exception using errcode='22023',message='official_document_receipt_step_conflict';
  end if;
  v_evidence := pg_catalog.jsonb_build_object('schema_version',1,'decision_type','confirm',
    'expected_step_id',v_step.id,'workflow_generation',v_generation,'decision_actor_user_id',v_actor_id,
    'principal_actor_id',v_actor_id,'confirmed_at',v_time,'confirmation_log_id',v_log_id);
  update public.official_document_approval_steps set status='approved',comment=v_comment,approved_at=v_time,
    updated_at=v_time,decision_actor_user_id=v_actor_id,
    decision_evidence_json=coalesce(decision_evidence_json,'{}'::jsonb)||v_evidence where id=v_step.id;
  update public.official_documents set current_status='closed',current_step='',updated_at=v_time where id=v_document.id;
  insert into public.official_document_approval_logs(id,document_id,step_id,actor_id,actor_name,principal_actor_id,
    action,comment,decision_evidence_json,ip_address,user_agent,created_at)
  values(v_log_id,v_document.id,v_step.id,v_actor_id,coalesce(nullif(v_actor.name,''),v_actor_id),v_actor_id,
    'confirm',v_comment,v_evidence,coalesce(p_request->>'ip_address',''),pg_catalog.left(coalesce(p_request->>'user_agent',''),180),v_time);
  insert into public.audit_logs(id,actor,action,target_type,target_id,detail,event_type,module_code,resource_type,resource_id,
    result,severity,actor_user_id,metadata_json,created_at)
  values('AUD-'||v_log_id,coalesce(nullif(v_actor.name,''),v_actor_id),'confirm','official_documents',v_document.id,
    v_comment,'submit','official_documents','official_documents',v_document.id,'success','info',v_actor_id,
    pg_catalog.jsonb_build_object('principal_actor_id',v_actor_id,'approval_log_id',v_log_id,'decision_evidence',v_evidence),v_time);
  return pg_catalog.jsonb_build_object('confirmed',true,'idempotent',false,'document_id',v_document.id,
    'step_id',v_step.id,'actor_id',v_actor_id,'approval_log_id',v_log_id);
end $function$;
revoke all on function public.edoc_confirm_official_document(jsonb) from public,anon,authenticated;
grant execute on function public.edoc_confirm_official_document(jsonb) to service_role;
