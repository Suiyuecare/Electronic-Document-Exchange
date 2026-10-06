-- Terminal rejection is distinct from the legacy correction/resubmit action.
-- Backend-only SECURITY DEFINER: needs private review/delegation validators;
-- no browser role may execute it. Locks match approval/withdraw ordering.
begin;
alter table public.official_documents drop constraint if exists official_documents_status_check;
alter table public.official_documents add constraint official_documents_status_check check (
  current_status in ('draft','pending_applicant_manager','pending_department_head',
    'pending_admin_director','pending_general_affairs_review','pending_ceo','pending_approval',
    'approved','stamping','stamped','pending_general_affairs_dispatch','returned_to_applicant_for_send',
    'dispatched','sent_by_applicant','closed','rejected','cancelled','stamping_failed','declined')
);
create or replace function public.edoc_decline_official_document(p_request jsonb)
returns jsonb language plpgsql security definer set search_path='' set lock_timeout='5s' as $function$
declare
  v_id text := p_request->>'document_id';
  v_actor text := p_request->>'actor_id';
  v_principal text := p_request->>'principal_actor_id';
  v_operation text := p_request->>'operation_id';
  v_hash text := p_request->>'request_sha256';
  v_time text := p_request->>'timestamp';
  v_comment text := pg_catalog.btrim(p_request#>>'{approval_log,comment}');
  v_document public.official_documents%rowtype;
  v_step public.official_document_approval_steps%rowtype;
  v_stamp public.official_document_stamp_requests%rowtype;
  v_log public.official_document_approval_logs%rowtype;
  v_evidence jsonb;
  v_result jsonb;
begin
  if coalesce(p_request->>'action','') <> 'decline'
     or coalesce(v_operation,'') !~ '^[a-zA-Z0-9_-]{8,120}$'
     or coalesce(v_hash,'') !~ '^[a-fA-F0-9]{64}$'
     or coalesce(pg_catalog.char_length(v_comment),0) not between 6 and 2000
     or nullif(v_time,'') is null then
    raise exception using errcode='22023',message='official_workflow_action_invalid';
  end if;
  select * into v_document from public.official_documents where id=v_id for update;
  if not found then raise exception using errcode='P0002',message='official_document_not_found'; end if;
  if v_document.company_id is distinct from p_request->>'company_id' or not exists (
    select 1 from public.users u where u.id=v_actor and u.status='啟用' and
      (u.company_id=v_document.company_id or edoc_private.editor_v2_actor_in_company_scope(v_id,v_actor))
  ) then raise exception using errcode='42501',message='official_document_company_forbidden'; end if;
  select * into v_log from public.official_document_approval_logs where id=v_operation;
  if found then
    if v_log.document_id is distinct from v_id or v_log.actor_id is distinct from v_actor
       or v_log.action is distinct from 'decline' or v_log.decision_evidence_json->>'request_sha256' is distinct from v_hash then
      raise exception using errcode='PT409',message='official_workflow_operation_conflict';
    end if;
    return pg_catalog.jsonb_build_object('ok',true,'committed',true,'idempotent',true,
      'document_id',v_id,'operation_id',v_operation,'action_result',v_log.decision_evidence_json->'action_result');
  end if;
  select * into v_step from public.official_document_approval_steps
    where id=p_request->>'expected_step_id' and document_id=v_id for update;
  if not found or v_document.current_status is distinct from p_request->>'expected_status'
     or v_document.current_step is distinct from p_request->>'expected_current_step'
     or v_document.content_revision is distinct from (p_request->>'expected_content_revision')::integer
     or v_document.updated_at is distinct from p_request->>'expected_updated_at'
     or v_step.status is distinct from 'pending' or v_step.step_key is distinct from v_document.current_step
     or v_step.step_key='applicant_confirm'
     or v_step.workflow_generation is distinct from (p_request->>'expected_generation')::integer
     or v_step.workflow_generation is distinct from (select max(workflow_generation) from public.official_document_approval_steps where document_id=v_id)
     or v_document.current_status is distinct from edoc_private.official_workflow_step_status(v_step.step_key)
     or exists(select 1 from public.official_document_approval_steps where document_id=v_id
       and workflow_generation=v_step.workflow_generation and status='pending' and step_order<v_step.step_order) then
    raise exception using errcode='PT409',message='official_workflow_step_conflict';
  end if;
  select * into v_stamp from public.official_document_stamp_requests where document_id=v_id order by created_at desc,id desc limit 1 for update;
  if nullif(v_document.stamped_file_id,'') is not null or v_stamp.status in ('stamping','stamped','completed')
     or nullif(v_stamp.stamped_file_id,'') is not null or nullif(v_stamp.claim_token,'') is not null then
    raise exception using errcode='PT409',message='official_workflow_irreversible';
  end if;
  if v_principal is distinct from v_step.approver_user_id or v_actor=v_document.applicant_id
     or v_principal=v_document.applicant_id then
    raise exception using errcode='42501',message='not_current_official_document_approver';
  end if;
  perform edoc_private.assert_official_document_decision_actor(v_id,v_document.company_id,v_principal,v_actor);
  if p_request#>>'{decision_evidence,decision_type}' is distinct from 'decline' then
    raise exception using errcode='22023',message='official_document_decision_evidence_invalid';
  end if;
  -- Reuse the complete, authoritative file-review validator without changing
  -- historical migrations. Persist the actual terminal decision, not approve.
  v_evidence := edoc_private.validate_official_document_decision_evidence(v_id,v_step.id,v_principal,v_actor,'approve',
    pg_catalog.jsonb_set(p_request->'decision_evidence','{decision_type}','"approve"'::jsonb));
  v_evidence := pg_catalog.jsonb_set(v_evidence,'{decision_type}','"decline"'::jsonb)
    || pg_catalog.jsonb_build_object('workflow_action','decline');
  v_result := pg_catalog.jsonb_build_object('action','decline','workflow_generation',v_step.workflow_generation,
    'current_step_id','','approval_restart_required',false,'editor_revision_id','','cloning',false);
  v_log := pg_catalog.jsonb_populate_record(null::public.official_document_approval_logs,p_request->'approval_log');
  if v_log.id is distinct from v_operation or v_log.document_id is distinct from v_id
     or v_log.step_id is distinct from v_step.id or v_log.actor_id is distinct from v_actor
     or v_log.principal_actor_id is distinct from v_principal or v_log.action is distinct from 'decline' then
    raise exception using errcode='22023',message='official_workflow_log_invalid';
  end if;
  update public.official_document_approval_steps set status='rejected',comment=v_comment,approved_at=v_time,
    decision_actor_user_id=v_actor,decision_evidence_json=v_evidence,updated_at=v_time where id=v_step.id;
  update public.official_document_approval_steps set status='skipped',updated_at=v_time
    where document_id=v_id and workflow_generation=v_step.workflow_generation and status='pending';
  update public.official_document_stamp_requests set status='cancelled',updated_at=v_time where document_id=v_id;
  update public.official_documents set current_status='declined',current_step='',updated_at=v_time where id=v_id;
  v_log.comment := v_comment;
  v_log.created_at := v_time;
  v_log.decision_evidence_json := v_evidence || pg_catalog.jsonb_build_object(
    'operation_id',v_operation,'request_sha256',v_hash,'action_result',v_result,'workflow_generation',v_step.workflow_generation);
  insert into public.official_document_approval_logs select (v_log).*;
  insert into public.audit_logs(id,actor,actor_user_id,action,target_type,target_id,detail,
    event_type,result,module_code,resource_type,resource_id,metadata_json,created_at)
  values('AUD-DECLINE-'||v_operation,v_actor,v_actor,'decline','official_documents',v_id,'step_id='||v_step.id,
    'decline','success','official_documents','official_documents',v_id,
    pg_catalog.jsonb_build_object('operation_id',v_operation,'request_sha256',v_hash)::text,v_time);
  insert into public.notifications(id,type,title,target_role,target_user_id,target_company_id,target_email,
    channel,status,priority,source,action_url,body,created_at)
  select 'NOTIF-DECLINE-'||pg_catalog.md5(v_operation),'簽核結果','案件不通過，已終止',
    u.role,u.id,u.company_id,u.email,'Email + 系統通知','未讀','高',v_id,'/#approvalLog?document='||v_id,
    v_comment,pg_catalog.clock_timestamp()
  from public.users u where u.id=v_document.applicant_id and u.status='啟用'
    and (u.company_id=v_document.company_id or edoc_private.editor_v2_actor_in_company_scope(v_id,u.id));
  if not found then raise exception using errcode='42501',message='notification_exact_target_required'; end if;
  return pg_catalog.jsonb_build_object('ok',true,'committed',true,'idempotent',false,
    'document_id',v_id,'operation_id',v_operation,'action_result',v_result);
end $function$;
revoke all on function public.edoc_decline_official_document(jsonb) from public,anon,authenticated;
grant execute on function public.edoc_decline_official_document(jsonb) to service_role;

-- Defense in depth: legacy cancel/edit RPCs cannot reopen a declined document.
create or replace function edoc_private.guard_declined_official_document()
returns trigger language plpgsql security invoker set search_path='' as $function$
begin
  if old.current_status='declined' and new is distinct from old then
    raise exception using errcode='PT409',message='official_document_terminal';
  end if;
  return new;
end $function$;
revoke all on function edoc_private.guard_declined_official_document() from public,anon,authenticated,service_role;
drop trigger if exists official_document_declined_immutable on public.official_documents;
create trigger official_document_declined_immutable before update on public.official_documents
  for each row execute function edoc_private.guard_declined_official_document();
notify pgrst,'reload schema';
commit;
