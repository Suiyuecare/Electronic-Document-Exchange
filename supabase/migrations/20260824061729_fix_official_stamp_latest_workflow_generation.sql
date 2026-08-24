-- A rejected approval generation is immutable audit history.  Automatic
-- stamping must validate only the newest workflow generation, otherwise any
-- superseded skipped/rejected step permanently blocks a corrected resubmission.
create or replace function public.edoc_claim_official_document_stamp(
  p_document_id text,
  p_stamp_request_id text,
  p_claim_token text,
  p_claim_owner_id text,
  p_lease_seconds integer default 300
)
returns jsonb
language plpgsql
security definer
set search_path to ''
set lock_timeout to '5s'
as $function$
declare
  v_document public.official_documents%rowtype;
  v_request public.official_document_stamp_requests%rowtype;
  v_workflow_generation integer;
  v_now timestamptz := clock_timestamp();
  v_expires_at timestamptz;
  v_same_owner boolean := false;
  v_recoverable boolean := false;
begin
  if nullif(btrim(p_document_id), '') is null
     or nullif(btrim(p_stamp_request_id), '') is null
     or nullif(btrim(p_claim_token), '') is null
     or length(p_claim_token) < 32
     or nullif(btrim(p_claim_owner_id), '') is null
     or p_lease_seconds < 60
     or p_lease_seconds > 1800 then
    raise exception using
      errcode = '22023',
      message = 'official_stamp_claim_invalid';
  end if;

  select document.*
    into v_document
    from public.official_documents as document
   where document.id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_not_found';
  end if;

  select request.*
    into v_request
    from public.official_document_stamp_requests as request
   where request.id = p_stamp_request_id
     and request.document_id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_stamp_request_required';
  end if;

  if exists (
    select 1
      from public.official_document_stamp_requests as newer
     where newer.document_id = p_document_id
       and (newer.created_at, newer.id) > (v_request.created_at, v_request.id)
  ) then
    raise exception using errcode = '22023', message = 'official_stamp_request_not_latest';
  end if;

  if v_document.requires_stamp is distinct from true then
    raise exception using errcode = '42501', message = 'official_document_stamp_required';
  end if;

  select max(step.workflow_generation)
    into v_workflow_generation
    from public.official_document_approval_steps as step
   where step.document_id = p_document_id;
  if v_workflow_generation is null then
    raise exception using
      errcode = 'P0001',
      message = 'official_document_not_fully_approved_for_stamp_retry';
  end if;

  if exists (
    select 1
      from public.official_document_approval_steps as step
     where step.document_id = p_document_id
       and step.workflow_generation = v_workflow_generation
       and step.step_key <> 'applicant_confirm'
       and step.status <> 'approved'
  ) then
    raise exception using
      errcode = 'P0001',
      message = 'official_document_not_fully_approved_for_stamp_retry';
  end if;

  if not exists (
    select 1
      from public.official_document_approval_steps as final_step
     where final_step.document_id = p_document_id
       and final_step.workflow_generation = v_workflow_generation
       and final_step.step_key = 'general_affairs_review'
       and final_step.status = 'approved'
  ) then
    raise exception using
      errcode = 'P0001',
      message = 'official_document_not_fully_approved_for_stamp_retry';
  end if;

  if p_claim_owner_id <> 'system'
     and not exists (
       select 1
         from public.official_document_approval_steps as owner_step
        where owner_step.document_id = p_document_id
          and owner_step.workflow_generation = v_workflow_generation
          and owner_step.step_key = 'general_affairs_review'
          and owner_step.status = 'approved'
          and owner_step.approver_user_id = p_claim_owner_id
     ) then
    raise exception using
      errcode = '42501',
      message = 'official_stamp_retry_forbidden';
  end if;

  if v_request.status = 'stamped'
     or v_request.stamped_file_id is not null
     or v_document.stamped_file_id is not null then
    return jsonb_build_object(
      'claimed', false,
      'reason', 'official_document_already_stamped',
      'document_id', v_document.id,
      'stamp_request_id', v_request.id
    );
  end if;

  v_same_owner := v_document.current_status = 'stamping'
    and v_document.current_step = 'auto_stamp'
    and v_request.status = 'stamping'
    and v_request.claim_token = p_claim_token;

  if not v_same_owner
     and v_request.status = 'stamping'
     and v_request.claim_token is not null
     and v_request.claim_expires_at is not null
     and v_request.claim_expires_at > v_now then
    return jsonb_build_object(
      'claimed', false,
      'reason', 'official_stamp_claim_busy',
      'document_id', v_document.id,
      'stamp_request_id', v_request.id,
      'claim_expires_at', v_request.claim_expires_at
    );
  end if;

  v_recoverable := (
    v_document.current_status = 'approved'
    and v_document.current_step = 'auto_stamp'
    and v_request.status in ('pending', 'approved', 'failed', 'stamping')
  ) or (
    v_document.current_status = 'stamping_failed'
    and v_document.current_step = 'general_affairs_review'
    and v_request.status in ('pending', 'failed', 'stamping')
  ) or (
    v_document.current_status = 'stamping'
    and v_document.current_step = 'auto_stamp'
    and v_request.status in ('pending', 'failed', 'stamping')
    and (
      v_request.claim_token is null
      or v_request.claim_expires_at is null
      or v_request.claim_expires_at <= v_now
    )
  );

  if not v_same_owner and not v_recoverable then
    return jsonb_build_object(
      'claimed', false,
      'reason', 'official_document_not_recoverable_for_stamp',
      'document_id', v_document.id,
      'stamp_request_id', v_request.id,
      'current_status', v_document.current_status,
      'request_status', v_request.status
    );
  end if;

  v_expires_at := v_now + make_interval(secs => p_lease_seconds);

  update public.official_documents
     set current_status = 'stamping',
         current_step = 'auto_stamp',
         updated_at = to_char(v_now, 'YYYY-MM-DD HH24:MI:SS')
   where id = v_document.id;

  update public.official_document_stamp_requests
     set status = 'stamping',
         claim_token = p_claim_token,
         claim_owner_id = p_claim_owner_id,
         claim_started_at = case when v_same_owner then claim_started_at else v_now end,
         claim_expires_at = v_expires_at,
         claim_attempt_count = claim_attempt_count + case when v_same_owner then 0 else 1 end,
         error_message = '',
         updated_at = to_char(v_now, 'YYYY-MM-DD HH24:MI:SS')
   where id = v_request.id;

  return jsonb_build_object(
    'claimed', true,
    'renewed', v_same_owner,
    'document_id', v_document.id,
    'stamp_request_id', v_request.id,
    'claim_token', p_claim_token,
    'claim_expires_at', v_expires_at,
    'attempt_count', v_request.claim_attempt_count + case when v_same_owner then 0 else 1 end
  );
end;
$function$;

comment on function public.edoc_claim_official_document_stamp(text, text, text, text, integer)
  is 'Service-role-only replay-safe stamp worker claim/renewal. Locks document then stamp request, validates only the latest workflow generation, rejects live competing leases, and recovers approved, failed, or stale stamping work.';

revoke all on function public.edoc_claim_official_document_stamp(text, text, text, text, integer) from public, anon, authenticated;
grant execute on function public.edoc_claim_official_document_stamp(text, text, text, text, integer) to service_role;
