-- Production forward migration: atomic official-document submission and editor finalize.
--
-- This intentionally contains no table recovery or seed behavior. It can be reviewed
-- and applied independently to an existing eDoc database whose base schema is present.
-- Commit submission, workflow creation, evidence locking, and audit writes as one transaction.
create or replace function public.edoc_commit_official_document_submission(p_request jsonb)
returns jsonb
language plpgsql
security definer
set search_path to ''
set lock_timeout to '5s'
as $function$
declare
  v_document public.official_documents%rowtype;
  v_stamp public.official_document_stamp_requests%rowtype;
  v_position public.official_document_stamp_positions%rowtype;
  v_step public.official_document_approval_steps%rowtype;
  v_first_step public.official_document_approval_steps%rowtype;
  v_snapshot public.approval_step_actor_snapshots%rowtype;
  v_submit_log public.official_document_approval_logs%rowtype;
  v_submit_audit public.audit_logs%rowtype;
  v_resubmit_log public.official_document_approval_logs%rowtype;
  v_resubmit_audit public.audit_logs%rowtype;
  v_operation_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'operation_id', '')), '');
  v_document_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'document_id', '')), '');
  v_applicant_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'applicant_id', '')), '');
  v_company_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'company_id', '')), '');
  v_expected_status text := nullif(pg_catalog.btrim(coalesce(p_request->>'expected_status', '')), '');
  -- Current production stores these workflow timestamps as canonical TEXT.
  -- Keep the compare/write variables textual so the forward RPC matches live schema.
  v_expected_updated_at text := coalesce(p_request->>'expected_updated_at', '');
  v_submitted_at text := nullif(pg_catalog.btrim(coalesce(p_request->>'submitted_at', '')), '');
  v_first_step_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'first_step_id', '')), '');
  v_first_step_key text := nullif(pg_catalog.btrim(coalesce(p_request->>'first_step_key', '')), '');
  v_first_status text := nullif(pg_catalog.btrim(coalesce(p_request->>'first_status', '')), '');
  v_workflow_generation integer;
  v_supersede_generation integer := 0;
  v_resubmit_enabled boolean := false;
  v_step_count integer;
  v_step_id_count integer;
  v_step_order_count integer;
  v_position_count integer;
  v_existing_log public.official_document_approval_logs%rowtype;
  v_patch jsonb := coalesce(p_request->'document_patch', '{}'::jsonb);
  v_resubmit jsonb := coalesce(p_request->'resubmit', '{}'::jsonb);
begin
  if pg_catalog.jsonb_typeof(p_request) is distinct from 'object'
     or v_operation_id is null or v_document_id is null or v_applicant_id is null
     or v_company_id is null or v_expected_updated_at = '' or v_submitted_at is null
     or v_first_step_id is null
     or v_first_step_key is null or v_first_status is null
     or v_expected_status not in ('draft', 'rejected')
     or pg_catalog.jsonb_typeof(p_request->'stamp_request') is distinct from 'object'
     or pg_catalog.jsonb_typeof(p_request->'stamp_positions') is distinct from 'array'
     or pg_catalog.jsonb_typeof(p_request->'steps') is distinct from 'array'
     or pg_catalog.jsonb_typeof(p_request->'actor_snapshots') is distinct from 'array'
     or pg_catalog.jsonb_typeof(p_request->'submit_log') is distinct from 'object'
     or pg_catalog.jsonb_typeof(p_request->'submit_audit') is distinct from 'object' then
    raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
  end if;

  begin
    v_workflow_generation := (p_request->>'workflow_generation')::integer;
    v_supersede_generation := coalesce((p_request->>'supersede_generation')::integer, 0);
    v_resubmit_enabled := coalesce((v_resubmit->>'enabled')::boolean, false);
  exception when others then
    raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
  end;
  if v_workflow_generation < 1 or v_supersede_generation < 0
     or (v_expected_status = 'rejected') is distinct from v_resubmit_enabled then
    raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
  end if;

  -- Serialize retries that reuse a caller-owned operation id. Without this
  -- lock, two concurrent identical submissions could both miss the witness
  -- row before one of them commits.
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('edoc:official-submit:' || v_operation_id, 0)
  );

  if exists (
    select 1 from pg_catalog.jsonb_object_keys(v_patch) as key
    where key not in ('metadata_json','correction_reason_category','correction_missing_items_json',
                      'correction_due_at','correction_requested_at','correction_resubmitted_at')
  ) then
    raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
  end if;

  select log.* into v_existing_log
  from public.official_document_approval_logs as log
  where log.id = v_operation_id;
  if found then
    select document.* into v_document
    from public.official_documents as document where document.id = v_document_id;
    if found and v_existing_log.document_id = v_document_id
       and v_existing_log.actor_id = v_applicant_id
       and v_existing_log.decision_evidence_json->>'operation_id' = v_operation_id
       and v_existing_log.decision_evidence_json->>'stamp_request_id' = p_request#>>'{stamp_request,id}'
       and coalesce((v_existing_log.decision_evidence_json->>'workflow_generation')::integer, 0) = v_workflow_generation
       and v_document.company_id = v_company_id
       and v_document.current_status = v_first_status
       and v_document.current_step = v_first_step_key
       and exists (
         select 1 from public.official_document_stamp_requests request
         where request.id = p_request#>>'{stamp_request,id}'
           and request.document_id = v_document_id
           and request.company_id = v_company_id
           and request.requested_by = v_applicant_id
       )
       and exists (
         select 1 from public.official_document_approval_steps step
         where step.id = v_first_step_id and step.document_id = v_document_id
           and step.workflow_generation = v_workflow_generation
       ) then
      return pg_catalog.jsonb_build_object(
        'ok', true, 'committed', true, 'idempotent', true,
        'document_id', v_document_id, 'operation_id', v_operation_id,
        'current_status', v_document.current_status, 'current_step', v_document.current_step,
        'first_step_id', v_first_step_id, 'workflow_generation', v_workflow_generation,
        'resubmitted', v_resubmit_enabled
      );
    end if;
    raise exception using errcode = '23505', message = 'official_submission_operation_conflict';
  end if;

  select document.* into v_document
  from public.official_documents as document
  where document.id = v_document_id
  for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_not_found';
  end if;
  if v_document.applicant_id is distinct from v_applicant_id
     or v_document.company_id is distinct from v_company_id then
    raise exception using errcode = '42501', message = 'official_document_submit_forbidden';
  end if;
  if v_document.current_status is distinct from v_expected_status then
    raise exception using errcode = '55000', message = 'official_document_not_submittable';
  end if;
  if v_document.updated_at is distinct from v_expected_updated_at then
    raise exception using errcode = '40001', message = 'official_document_submit_stale';
  end if;

  v_stamp := pg_catalog.jsonb_populate_record(null::public.official_document_stamp_requests, p_request->'stamp_request');
  v_submit_log := pg_catalog.jsonb_populate_record(null::public.official_document_approval_logs, p_request->'submit_log');
  v_submit_audit := pg_catalog.jsonb_populate_record(null::public.audit_logs, p_request->'submit_audit');
  if v_stamp.id is null or v_stamp.document_id is distinct from v_document_id
     or v_stamp.company_id is distinct from v_company_id
     or v_stamp.requested_by is distinct from v_applicant_id
     or not (
       (
         nullif(v_stamp.locked_editor_revision_id, '') is not null
         and nullif(v_stamp.locked_source_sha256, '') is not null
         and nullif(v_stamp.prepared_file_id, '') is not null
         and nullif(v_stamp.prepared_sha256, '') is not null
         and nullif(v_stamp.editor_manifest_sha256, '') is not null
         and v_stamp.editor_schema_version is not null
         and nullif(v_stamp.renderer_version, '') is not null
         and v_stamp.editor_locked_at is not null
       )
       or
       (
         nullif(v_stamp.locked_editor_revision_id, '') is null
         and nullif(v_stamp.locked_source_sha256, '') is null
         and nullif(v_stamp.prepared_file_id, '') is null
         and nullif(v_stamp.prepared_sha256, '') is null
         and nullif(v_stamp.editor_manifest_sha256, '') is null
         and v_stamp.editor_schema_version is null
         and nullif(v_stamp.renderer_version, '') is null
         and v_stamp.editor_locked_at is null
       )
     )
     or v_submit_log.id is distinct from v_operation_id
     or v_submit_log.document_id is distinct from v_document_id
     or v_submit_log.actor_id is distinct from v_applicant_id
     or v_submit_audit.id is null or v_submit_audit.target_id is distinct from v_document_id then
    raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
  end if;

  select pg_catalog.count(*), pg_catalog.count(distinct elem->>'id'),
         pg_catalog.count(distinct (elem->>'step_order')::integer)
    into v_step_count, v_step_id_count, v_step_order_count
  from pg_catalog.jsonb_array_elements(p_request->'steps') elem;
  if v_step_count < 1 or v_step_count <> v_step_id_count or v_step_count <> v_step_order_count then
    raise exception using errcode = '22023', message = 'official_workflow_existing_steps_invalid';
  end if;
  select step.* into v_first_step
  from pg_catalog.jsonb_populate_recordset(null::public.official_document_approval_steps, p_request->'steps') step
  where step.id = v_first_step_id;
  if not found or v_first_step.document_id is distinct from v_document_id
     or v_first_step.workflow_generation is distinct from v_workflow_generation
     or v_first_step.step_key is distinct from v_first_step_key
     or v_first_step.status is distinct from 'pending'
     or v_first_step.step_order is distinct from (
       select pg_catalog.min((elem->>'step_order')::integer)
       from pg_catalog.jsonb_array_elements(p_request->'steps') elem
     ) then
    raise exception using errcode = '22023', message = 'official_workflow_existing_steps_invalid';
  end if;
  if exists (
    select 1 from pg_catalog.jsonb_populate_recordset(null::public.official_document_approval_steps, p_request->'steps') step
    where step.document_id is distinct from v_document_id
       or step.workflow_generation is distinct from v_workflow_generation
       or step.step_order < 1 or step.id is null or step.step_key is null
  ) or exists (
    select 1 from public.official_document_approval_steps step
    where step.document_id = v_document_id and step.workflow_generation = v_workflow_generation
  ) then
    raise exception using errcode = '23505', message = 'official_workflow_existing_steps_invalid';
  end if;

  select pg_catalog.count(*) into v_position_count
  from pg_catalog.jsonb_array_elements(p_request->'stamp_positions');
  if v_position_count < 1 or exists (
    select 1 from pg_catalog.jsonb_populate_recordset(null::public.official_document_stamp_positions, p_request->'stamp_positions') position
    where position.request_id is distinct from v_stamp.id
       or position.id is null or position.seal_id is null
       or position.locked_seal_file_id is null or nullif(position.locked_seal_sha256, '') is null
       or position.locked_render_width_pt is null or position.locked_render_height_pt is null
       or nullif(position.locked_dimension_policy_version, '') is null
  ) then
    raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
  end if;

  if v_resubmit_enabled then
    if v_supersede_generation < 1
       or v_workflow_generation <= v_supersede_generation
       or v_document.correction_requested_at is distinct from (v_resubmit->>'expected_correction_requested_at')::timestamptz
       or v_supersede_generation is distinct from (
         select pg_catalog.max(step.workflow_generation)
         from public.official_document_approval_steps step where step.document_id = v_document_id
       ) then
      raise exception using errcode = '40001', message = 'official_document_resubmit_generation_conflict';
    end if;
    if pg_catalog.jsonb_typeof(v_resubmit->'log') is distinct from 'object'
       or pg_catalog.jsonb_typeof(v_resubmit->'audit') is distinct from 'object' then
      raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
    end if;
    v_resubmit_log := pg_catalog.jsonb_populate_record(null::public.official_document_approval_logs, v_resubmit->'log');
    v_resubmit_audit := pg_catalog.jsonb_populate_record(null::public.audit_logs, v_resubmit->'audit');
    if v_resubmit_log.id is null or v_resubmit_log.document_id is distinct from v_document_id
       or v_resubmit_log.actor_id is distinct from v_applicant_id
       or v_resubmit_audit.id is null or v_resubmit_audit.target_id is distinct from v_document_id then
      raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
    end if;
    update public.official_document_approval_steps
       set status = 'skipped', updated_at = v_submitted_at
     where document_id = v_document_id and workflow_generation = v_supersede_generation
       and status = 'pending';
  elsif exists (
    select 1 from public.official_document_approval_steps step
    where step.document_id = v_document_id and step.status = 'pending'
  ) then
    raise exception using errcode = '55000', message = 'official_workflow_existing_steps_invalid';
  end if;

  insert into public.official_document_stamp_requests
  select (v_stamp).*
  on conflict (id) do update set
    document_id = excluded.document_id, company_id = excluded.company_id, seal_id = excluded.seal_id,
    requested_by = excluded.requested_by, stamp_page = excluded.stamp_page, stamp_x = excluded.stamp_x,
    stamp_y = excluded.stamp_y, stamp_width = excluded.stamp_width, stamp_height = excluded.stamp_height,
    status = excluded.status, stamped_file_id = excluded.stamped_file_id,
    locked_editor_revision_id = excluded.locked_editor_revision_id,
    locked_source_sha256 = excluded.locked_source_sha256, prepared_file_id = excluded.prepared_file_id,
    prepared_sha256 = excluded.prepared_sha256, editor_manifest_sha256 = excluded.editor_manifest_sha256,
    editor_schema_version = excluded.editor_schema_version, renderer_version = excluded.renderer_version,
    editor_locked_at = excluded.editor_locked_at, error_message = excluded.error_message,
    updated_at = excluded.updated_at;
  delete from public.official_document_stamp_positions where request_id = v_stamp.id;
  for v_position in
    select * from pg_catalog.jsonb_populate_recordset(null::public.official_document_stamp_positions, p_request->'stamp_positions')
  loop
    insert into public.official_document_stamp_positions select (v_position).*;
  end loop;

  for v_step in
    select * from pg_catalog.jsonb_populate_recordset(null::public.official_document_approval_steps, p_request->'steps')
  loop
    insert into public.official_document_approval_steps select (v_step).*;
  end loop;
  for v_snapshot in
    select * from pg_catalog.jsonb_populate_recordset(null::public.approval_step_actor_snapshots, p_request->'actor_snapshots')
  loop
    if v_snapshot.source_type not in (
         'official_document', 'official_documents', 'official_document_application'
       )
       or v_snapshot.source_id is distinct from v_document_id
       or nullif(v_snapshot.snapshot_json->>'step_id', '') is null then
      raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
    end if;
    select step.* into v_step
    from public.official_document_approval_steps step
    where step.id = v_snapshot.snapshot_json->>'step_id'
      and step.document_id = v_document_id
      and step.workflow_generation = v_workflow_generation;
    if not found
       or v_snapshot.approver_user_id is distinct from v_step.approver_user_id
       or v_snapshot.step_no is distinct from v_step.step_order then
      raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
    end if;
    insert into public.approval_step_actor_snapshots select (v_snapshot).*;
  end loop;

  update public.official_documents set
    metadata_json = case when v_patch ? 'metadata_json' then v_patch->>'metadata_json' else metadata_json end,
    correction_reason_category = case when v_patch ? 'correction_reason_category' then v_patch->>'correction_reason_category' else correction_reason_category end,
    correction_missing_items_json = case when v_patch ? 'correction_missing_items_json' then v_patch->'correction_missing_items_json' else correction_missing_items_json end,
    correction_due_at = case when v_patch ? 'correction_due_at' then nullif(v_patch->>'correction_due_at','')::timestamptz else correction_due_at end,
    correction_requested_at = case when v_patch ? 'correction_requested_at' then nullif(v_patch->>'correction_requested_at','')::timestamptz else correction_requested_at end,
    correction_resubmitted_at = case when v_resubmit_enabled then nullif(v_resubmit->>'correction_resubmitted_at','')::timestamptz
                                     when v_patch ? 'correction_resubmitted_at' then nullif(v_patch->>'correction_resubmitted_at','')::timestamptz
                                     else correction_resubmitted_at end,
    current_status = v_first_status,
    current_step = v_first_step_key,
    updated_at = v_submitted_at
  where id = v_document_id;
  if v_resubmit_enabled then
    update public.official_documents set correction_reason_category = null,
      correction_missing_items_json = '[]'::jsonb, correction_due_at = null,
      correction_requested_at = null
    where id = v_document_id;
  end if;
  update public.official_document_approval_steps
     set review_started_at = v_submitted_at, updated_at = v_submitted_at
   where id = v_first_step_id and document_id = v_document_id;

  insert into public.official_document_approval_logs select (v_submit_log).*;
  insert into public.audit_logs (
    id, actor, action, target_type, target_id, ip, device, detail, created_at,
    event_type, severity, result, module_code, resource_type, resource_id, data_scope,
    actor_user_id, actor_email, actor_roles_json, target_user_id, target_email, reason,
    request_id, before_snapshot_json, after_snapshot_json, metadata_json
  ) values (
    v_submit_audit.id, v_submit_audit.actor, v_submit_audit.action, v_submit_audit.target_type,
    v_submit_audit.target_id, v_submit_audit.ip, v_submit_audit.device, v_submit_audit.detail,
    v_submit_audit.created_at, v_submit_audit.event_type, v_submit_audit.severity,
    v_submit_audit.result, v_submit_audit.module_code, v_submit_audit.resource_type,
    v_submit_audit.resource_id, v_submit_audit.data_scope, v_submit_audit.actor_user_id,
    v_submit_audit.actor_email, coalesce(v_submit_audit.actor_roles_json, '[]'),
    v_submit_audit.target_user_id, v_submit_audit.target_email, v_submit_audit.reason,
    v_submit_audit.request_id, coalesce(v_submit_audit.before_snapshot_json, '{}'),
    coalesce(v_submit_audit.after_snapshot_json, '{}'), coalesce(v_submit_audit.metadata_json, '{}')
  );
  if v_resubmit_enabled then
    insert into public.official_document_approval_logs select (v_resubmit_log).*;
    insert into public.audit_logs (
      id, actor, action, target_type, target_id, ip, device, detail, created_at,
      event_type, severity, result, module_code, resource_type, resource_id, data_scope,
      actor_user_id, actor_email, actor_roles_json, target_user_id, target_email, reason,
      request_id, before_snapshot_json, after_snapshot_json, metadata_json
    ) values (
      v_resubmit_audit.id, v_resubmit_audit.actor, v_resubmit_audit.action,
      v_resubmit_audit.target_type, v_resubmit_audit.target_id, v_resubmit_audit.ip,
      v_resubmit_audit.device, v_resubmit_audit.detail, v_resubmit_audit.created_at,
      v_resubmit_audit.event_type, v_resubmit_audit.severity, v_resubmit_audit.result,
      v_resubmit_audit.module_code, v_resubmit_audit.resource_type, v_resubmit_audit.resource_id,
      v_resubmit_audit.data_scope, v_resubmit_audit.actor_user_id, v_resubmit_audit.actor_email,
      coalesce(v_resubmit_audit.actor_roles_json, '[]'), v_resubmit_audit.target_user_id,
      v_resubmit_audit.target_email, v_resubmit_audit.reason, v_resubmit_audit.request_id,
      coalesce(v_resubmit_audit.before_snapshot_json, '{}'),
      coalesce(v_resubmit_audit.after_snapshot_json, '{}'), coalesce(v_resubmit_audit.metadata_json, '{}')
    );
  end if;

  return pg_catalog.jsonb_build_object(
    'ok', true, 'committed', true, 'idempotent', false,
    'document_id', v_document_id, 'operation_id', v_operation_id,
    'current_status', v_first_status, 'current_step', v_first_step_key,
    'first_step_id', v_first_step_id, 'workflow_generation', v_workflow_generation,
    'resubmitted', v_resubmit_enabled
  );
exception
  when invalid_text_representation or numeric_value_out_of_range or not_null_violation or check_violation then
    raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
end;
$function$;

revoke all on function public.edoc_commit_official_document_submission(jsonb) from public, anon, authenticated;
grant execute on function public.edoc_commit_official_document_submission(jsonb) to service_role;

-- Finalize a direct-uploaded editor asset and create its immutable revision atomically.
create or replace function public.edoc_finalize_editor_asset_v2(p_request jsonb)
returns jsonb
language plpgsql
security definer
set search_path to ''
set lock_timeout to '5s'
as $function$
declare
  v_document public.official_documents%rowtype;
  v_asset public.official_document_editor_assets%rowtype;
  v_latest public.official_document_editor_revisions%rowtype;
  v_revision public.official_document_editor_revisions%rowtype;
  v_file public.file_objects%rowtype;
  v_official_file public.official_document_files%rowtype;
  v_log public.official_document_approval_logs%rowtype;
  v_audit public.audit_logs%rowtype;
  v_operation_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'operation_id','')), '');
  v_document_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'document_id','')), '');
  v_applicant_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'applicant_id','')), '');
  v_company_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'company_id','')), '');
  v_asset_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'asset_id','')), '');
  v_expected_status text := nullif(pg_catalog.btrim(coalesce(p_request->>'expected_asset_status','')), '');
  v_expected_sha text := pg_catalog.lower(coalesce(p_request->>'expected_asset_sha256',''));
  v_expected_size bigint;
  v_expected_base_id text := nullif(coalesce(p_request->>'expected_base_revision_id',''), '');
  v_expected_base_no integer;
  v_has_official_file boolean := false;
  v_asset_patch jsonb := coalesce(p_request->'asset_patch', '{}'::jsonb);
begin
  if pg_catalog.jsonb_typeof(p_request) is distinct from 'object'
     or v_operation_id is null or v_document_id is null or v_applicant_id is null
     or v_company_id is null or v_asset_id is null
     or v_expected_status not in ('pending','uploaded')
     or v_expected_sha !~ '^[0-9a-f]{64}$'
     or pg_catalog.jsonb_typeof(p_request->'file_object') is distinct from 'object'
     or pg_catalog.jsonb_typeof(p_request->'asset_patch') is distinct from 'object'
     or pg_catalog.jsonb_typeof(p_request->'revision') is distinct from 'object'
     or pg_catalog.jsonb_typeof(p_request->'approval_log') is distinct from 'object'
     or pg_catalog.jsonb_typeof(p_request->'audit_log') is distinct from 'object' then
    raise exception using errcode = '22023', message = 'editor_finalize_invalid_payload';
  end if;
  begin
    v_expected_size := (p_request->>'expected_asset_size_bytes')::bigint;
    v_expected_base_no := coalesce((p_request->>'expected_base_revision_no')::integer, 0);
  exception when others then
    raise exception using errcode = '22023', message = 'editor_finalize_invalid_payload';
  end;
  if v_expected_size < 1 or v_expected_base_no < 0 then
    raise exception using errcode = '22023', message = 'editor_finalize_invalid_payload';
  end if;

  select document.* into v_document from public.official_documents document
  where document.id = v_document_id for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'editor_upload_not_found';
  end if;
  if v_document.applicant_id is distinct from v_applicant_id
     or v_document.company_id is distinct from v_company_id then
    raise exception using errcode = '42501', message = 'official_editor_write_forbidden';
  end if;
  if v_document.current_status not in ('draft','rejected') then
    raise exception using errcode = '55000', message = 'editor_locked_after_submit';
  end if;

  select asset.* into v_asset from public.official_document_editor_assets asset
  where asset.id = v_asset_id and asset.document_id = v_document_id for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'editor_upload_not_found';
  end if;
  v_revision := pg_catalog.jsonb_populate_record(null::public.official_document_editor_revisions, p_request->'revision');
  v_file := pg_catalog.jsonb_populate_record(null::public.file_objects, p_request->'file_object');
  v_log := pg_catalog.jsonb_populate_record(null::public.official_document_approval_logs, p_request->'approval_log');
  v_audit := pg_catalog.jsonb_populate_record(null::public.audit_logs, p_request->'audit_log');
  v_has_official_file := pg_catalog.jsonb_typeof(p_request->'official_file') = 'object'
                         and p_request->'official_file' <> '{}'::jsonb;
  if v_has_official_file then
    v_official_file := pg_catalog.jsonb_populate_record(null::public.official_document_files, p_request->'official_file');
  end if;

  if v_asset.upload_status = 'finalized' then
    if v_log.id = v_operation_id
       and v_log.document_id = v_document_id
       and v_log.actor_id = v_applicant_id
       and v_audit.id is not null
       and v_audit.target_id = v_document_id
       and v_asset.editor_revision_id = v_revision.id and v_asset.file_object_id = v_file.id
       and pg_catalog.lower(v_asset.sha256) = v_expected_sha and v_asset.size_bytes = v_expected_size
       and (not v_has_official_file or v_asset.official_file_id = v_official_file.id)
       and exists (select 1 from public.file_objects f
                   where f.id = v_file.id and f.document_id = v_document_id
                     and pg_catalog.lower(f.sha256) = v_expected_sha
                     and f.size_bytes = v_expected_size)
       and (not v_has_official_file or exists (
         select 1 from public.official_document_files f
         where f.id = v_official_file.id and f.document_id = v_document_id
           and f.file_object_id = v_file.id
           and pg_catalog.lower(f.file_hash) = v_expected_sha
           and f.file_size = v_expected_size
       ))
       and exists (select 1 from public.official_document_editor_revisions r
                   where r.id = v_revision.id and r.document_id = v_document_id
                     and r.manifest_sha256 = v_revision.manifest_sha256)
       and exists (select 1 from public.official_document_approval_logs l
                   where l.id = v_operation_id and l.document_id = v_document_id
                     and l.actor_id = v_applicant_id)
       and exists (select 1 from public.audit_logs a
                   where a.id = v_audit.id and a.target_id = v_document_id
                     and a.request_id = v_operation_id) then
      return pg_catalog.jsonb_build_object(
        'ok', true, 'committed', true, 'idempotent', true,
        'document_id', v_document_id, 'asset_id', v_asset_id,
        'operation_id', v_operation_id, 'revision_id', v_revision.id,
        'revision_no', v_revision.revision_no, 'manifest_sha256', v_revision.manifest_sha256,
        'file_object_id', v_file.id,
        'official_file_id', case when v_has_official_file then v_official_file.id else null end
      );
    end if;
    raise exception using errcode = '23505', message = 'editor_finalize_operation_conflict';
  end if;
  if exists (select 1 from public.official_document_approval_logs l where l.id = v_operation_id)
     or exists (select 1 from public.audit_logs a where a.id = v_audit.id) then
    raise exception using errcode = '23505', message = 'editor_finalize_operation_conflict';
  end if;
  if v_asset.upload_status is distinct from v_expected_status
     or pg_catalog.lower(v_asset.expected_sha256) is distinct from v_expected_sha
     or v_asset.size_bytes is distinct from v_expected_size then
    raise exception using errcode = '40001', message = 'editor_upload_new_intent_required';
  end if;

  select revision.* into v_latest
  from public.official_document_editor_revisions revision
  where revision.document_id = v_document_id
  order by revision.revision_no desc limit 1 for update;
  if found then
    if v_latest.id is distinct from v_expected_base_id
       or v_latest.revision_no is distinct from v_expected_base_no
       or v_revision.parent_revision_id is distinct from v_latest.id
       or v_revision.revision_no is distinct from v_latest.revision_no + 1 then
      raise exception using errcode = '40001', message = 'editor_revision_conflict';
    end if;
  elsif v_expected_base_id is not null or v_expected_base_no <> 0
        or v_revision.parent_revision_id is not null or v_revision.revision_no <> 1 then
    raise exception using errcode = '40001', message = 'editor_revision_conflict';
  end if;

  if v_revision.id is null or v_revision.document_id is distinct from v_document_id
     or v_revision.created_by is distinct from v_applicant_id
     or v_file.id is null or v_file.document_id is distinct from v_document_id
     or v_file.created_by is distinct from v_applicant_id
     or pg_catalog.lower(v_file.sha256) is distinct from v_expected_sha
     or v_file.size_bytes is distinct from v_expected_size
     or v_log.id is distinct from v_operation_id or v_log.document_id is distinct from v_document_id
     or v_log.actor_id is distinct from v_applicant_id
     or v_audit.id is null or v_audit.target_id is distinct from v_document_id
     or v_asset_patch->>'file_object_id' is distinct from v_file.id
     or pg_catalog.lower(coalesce(v_asset_patch->>'sha256','')) is distinct from v_expected_sha
     or v_asset_patch->>'upload_status' is distinct from 'finalized'
     or v_asset_patch->>'scan_status' is distinct from 'passed' then
    raise exception using errcode = '22023', message = 'editor_finalize_invalid_payload';
  end if;
  if v_has_official_file and (
       v_official_file.id is null or v_official_file.document_id is distinct from v_document_id
       or v_official_file.file_object_id is distinct from v_file.id
       or v_official_file.file_type is distinct from 'original_pdf'
       or pg_catalog.lower(v_official_file.file_hash) is distinct from v_expected_sha
       or v_official_file.file_size is distinct from v_expected_size
       or v_asset_patch->>'official_file_id' is distinct from v_official_file.id
     ) then
    raise exception using errcode = '22023', message = 'editor_finalize_invalid_payload';
  end if;

  if exists (select 1 from public.file_objects f where f.id = v_file.id or f.storage_key = v_file.storage_key) then
    raise exception using errcode = '23505', message = 'editor_file_object_conflict';
  end if;
  if v_has_official_file and exists (select 1 from public.official_document_files f where f.id = v_official_file.id) then
    raise exception using errcode = '23505', message = 'editor_official_file_conflict';
  end if;
  if exists (select 1 from public.official_document_editor_revisions r
             where r.id = v_revision.id
                or (r.document_id = v_document_id and r.revision_no = v_revision.revision_no)
                or (v_revision.parent_revision_id is not null and r.document_id = v_document_id
                    and r.parent_revision_id = v_revision.parent_revision_id)) then
    raise exception using errcode = '23505', message = 'editor_revision_conflict';
  end if;

  insert into public.file_objects select (v_file).*;
  if v_has_official_file then
    insert into public.official_document_files select (v_official_file).*;
  end if;
  insert into public.official_document_editor_revisions select (v_revision).*;
  update public.official_document_editor_assets set
    file_object_id = v_file.id,
    official_file_id = case when v_has_official_file then v_official_file.id else null end,
    sha256 = pg_catalog.upper(v_expected_sha),
    upload_status = 'finalized', scan_status = 'passed',
    preflight_status = coalesce(nullif(v_asset_patch->>'preflight_status',''), preflight_status),
    page_count = coalesce((v_asset_patch->>'page_count')::integer, page_count),
    metadata_json = coalesce(v_asset_patch->>'metadata_json', metadata_json),
    finalized_at = v_asset_patch->>'finalized_at',
    editor_revision_id = v_revision.id
  where id = v_asset_id and document_id = v_document_id;
  insert into public.official_document_approval_logs select (v_log).*;
  insert into public.audit_logs (
    id, actor, action, target_type, target_id, ip, device, detail, created_at,
    event_type, severity, result, module_code, resource_type, resource_id, data_scope,
    actor_user_id, actor_email, actor_roles_json, target_user_id, target_email, reason,
    request_id, before_snapshot_json, after_snapshot_json, metadata_json
  ) values (
    v_audit.id, v_audit.actor, v_audit.action, v_audit.target_type, v_audit.target_id,
    v_audit.ip, v_audit.device, v_audit.detail, v_audit.created_at, v_audit.event_type,
    v_audit.severity, v_audit.result, v_audit.module_code, v_audit.resource_type,
    v_audit.resource_id, v_audit.data_scope, v_audit.actor_user_id, v_audit.actor_email,
    coalesce(v_audit.actor_roles_json, '[]'), v_audit.target_user_id, v_audit.target_email,
    v_audit.reason, v_audit.request_id, coalesce(v_audit.before_snapshot_json, '{}'),
    coalesce(v_audit.after_snapshot_json, '{}'), coalesce(v_audit.metadata_json, '{}')
  );

  return pg_catalog.jsonb_build_object(
    'ok', true, 'committed', true, 'idempotent', false,
    'document_id', v_document_id, 'asset_id', v_asset_id, 'operation_id', v_operation_id,
    'revision_id', v_revision.id, 'revision_no', v_revision.revision_no,
    'manifest_sha256', v_revision.manifest_sha256, 'file_object_id', v_file.id,
    'official_file_id', case when v_has_official_file then v_official_file.id else null end
  );
exception
  when invalid_text_representation or numeric_value_out_of_range or not_null_violation or check_violation then
    raise exception using errcode = '22023', message = 'editor_finalize_invalid_payload';
end;
$function$;

revoke all on function public.edoc_finalize_editor_asset_v2(jsonb) from public, anon, authenticated;
grant execute on function public.edoc_finalize_editor_asset_v2(jsonb) to service_role;

notify pgrst, 'reload schema';
