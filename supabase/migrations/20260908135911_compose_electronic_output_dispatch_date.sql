-- Explicit compose output mode; an uploaded PDF must still use Seal Vault.
begin;
alter table public.official_documents
  add column if not exists output_mode text not null default 'physical',
  add column if not exists dispatch_date text;
grant usage on schema edoc_private to service_role;

create or replace function edoc_private.is_electronic_compose(p_document public.official_documents)
returns boolean language sql immutable security invoker set search_path = ''
as $$
  select coalesce(p_document.output_mode = 'electronic'
    and p_document.source_type = 'blank_editor'
    and p_document.document_type = 'outgoing_official_document'
    and p_document.requires_stamp is false, false)
$$;
revoke all on function edoc_private.is_electronic_compose(public.official_documents) from public, anon, authenticated;
grant execute on function edoc_private.is_electronic_compose(public.official_documents) to service_role;

create or replace function edoc_private.guard_compose_output_fields()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  if new.output_mode not in ('physical', 'electronic')
     or (new.output_mode = 'electronic' and not edoc_private.is_electronic_compose(new))
     or (new.output_mode = 'physical' and new.requires_stamp is not true) then
    raise exception using errcode = '42501', message = 'official_document_output_mode_invalid';
  end if;
  if new.dispatch_date is not null and (
    new.dispatch_date !~ '^\d{4}-\d{2}-\d{2}$'
    or pg_catalog.to_char(new.dispatch_date::date, 'YYYY-MM-DD') <> new.dispatch_date
  ) then
    raise exception using errcode = '22023', message = 'official_dispatch_date_invalid';
  end if;
  if tg_op = 'UPDATE' then
    if old.current_status <> 'draft' and (
      old.output_mode is distinct from new.output_mode
      or old.requires_stamp is distinct from new.requires_stamp
    ) then
      raise exception using errcode = '55000', message = 'official_document_output_mode_locked';
    end if;
    if old.current_status not in ('draft', 'rejected') and old.dispatch_date is distinct from new.dispatch_date then
      raise exception using errcode = '55000', message = 'official_document_dispatch_date_locked';
    end if;
  end if;
  return new;
end;
$$;
revoke all on function edoc_private.guard_compose_output_fields() from public, anon, authenticated;
drop trigger if exists trg_guard_compose_output_fields on public.official_documents;
create trigger trg_guard_compose_output_fields before insert or update of output_mode, requires_stamp, dispatch_date
on public.official_documents for each row execute function edoc_private.guard_compose_output_fields();

-- Preserve the established atomic RPCs and their authorization/audit logic.
-- These exact, checked replacements fail the migration if the expected prior
-- definitions have drifted instead of silently installing a partial workflow.
do $migration$
declare
  v_sql text;
  v_old text;
  v_new text;
  v_proc regprocedure;
begin
  v_proc := 'public.edoc_commit_official_document_submission(jsonb)'::regprocedure;
  v_sql := pg_catalog.pg_get_functiondef(v_proc);
  v_old := '  v_position_count integer;';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_migration_submit_declaration_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old, v_old || E'\n  v_electronic boolean := false;');
  v_old := '  v_stamp := pg_catalog.jsonb_populate_record(null::public.official_document_stamp_requests, p_request->''stamp_request'');';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_migration_submit_source_drift'; end if;
  v_new := $snippet$
  v_electronic := edoc_private.is_electronic_compose(v_document);
  if not v_document.requires_stamp and not v_electronic then
    raise exception using errcode = '42501', message = 'official_document_stamp_required';
  end if;
  if v_electronic and not exists (
    select 1 from public.official_document_files f join public.file_objects o on o.id = f.file_object_id
    where f.document_id = v_document.id and f.file_type = 'generated_pdf'
      and f.id = p_request#>>'{submit_log,decision_evidence_json,source_file_id}'
      and f.file_hash = p_request#>>'{submit_log,decision_evidence_json,source_sha256}'
      and o.document_id = v_document.id and o.sha256 = f.file_hash and o.mime_type = 'application/pdf'
  ) then
    raise exception using errcode = '22023', message = 'official_document_electronic_source_invalid';
  end if;
$snippet$;
  v_sql := pg_catalog.replace(v_sql, v_old, v_new || v_old);
  v_old := '  if v_stamp.id is null or v_stamp.document_id is distinct from v_document_id';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_migration_submit_stamp_guard_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old, '  if (not v_electronic and (v_stamp.id is null or v_stamp.document_id is distinct from v_document_id');
  v_old := '     or v_submit_log.id is distinct from v_operation_id';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_migration_submit_log_guard_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old, '     )) or v_submit_log.id is distinct from v_operation_id');
  v_old := '  if v_position_count < 1 or exists (';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_migration_submit_position_guard_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old, '  if (not v_electronic and v_position_count < 1) or (v_electronic and v_position_count <> 0) or exists (');
  v_old := '       and v_existing_log.decision_evidence_json->>''stamp_request_id'' = p_request#>>''{stamp_request,id}''';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_migration_submit_retry_id_drift'; end if;
  v_sql := pg_catalog.replace(v_sql,
    v_old,
    '       and coalesce(v_existing_log.decision_evidence_json->>''stamp_request_id'', '''') = coalesce(p_request#>>''{stamp_request,id}'', '''')');
  v_old := E'       and exists (\n         select 1 from public.official_document_stamp_requests request';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_migration_submit_retry_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old, E'       and (edoc_private.is_electronic_compose(v_document) or exists (\n         select 1 from public.official_document_stamp_requests request');
  v_old := E'           and request.requested_by = v_applicant_id\n       )';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_migration_submit_retry_owner_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old, E'           and request.requested_by = v_applicant_id\n       ))');
  v_old := '  insert into public.official_document_stamp_requests';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_migration_submit_write_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old, E'  if not v_electronic then\n' || v_old);
  v_old := E'  for v_step in\n    select * from pg_catalog.jsonb_populate_recordset';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_migration_submit_steps_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old, E'  end if;\n' || v_old);
  execute v_sql;

  v_proc := 'public.edoc_claim_official_document_approval(text,text,text,text)'::regprocedure;
  v_sql := pg_catalog.pg_get_functiondef(v_proc);
  v_old := '  if v_document.requires_stamp is distinct from true then';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_migration_approval_guard_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old,
    '  if v_document.requires_stamp is distinct from true and not edoc_private.is_electronic_compose(v_document) then');
  v_old := E'    v_transition := ''auto_stamp'';\n    v_next_status := ''approved'';\n    v_next_key := ''auto_stamp'';';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_migration_approval_transition_drift'; end if;
  v_new := $snippet$
    v_transition := case when edoc_private.is_electronic_compose(v_document) then 'electronic_dispatch' else 'auto_stamp' end;
    v_next_status := 'approved';
    v_next_key := v_transition;
$snippet$;
  v_sql := pg_catalog.replace(v_sql, v_old, v_new);
  execute v_sql;

  v_proc := 'public.edoc_apply_official_document_correction(text,text,text,jsonb,text,jsonb,jsonb,text,jsonb,jsonb,text,text,text,text,text,text,jsonb,text,text)'::regprocedure;
  v_sql := pg_catalog.pg_get_functiondef(v_proc);
  v_old := '       ''workflow_template_key'', ''metadata_json''';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_migration_correction_allowlist_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old, '       ''workflow_template_key'', ''metadata_json'', ''dispatch_date'', ''output_mode'', ''requires_stamp''');
  v_old := '         workflow_template_key = p_patch->>''workflow_template_key'',';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_migration_correction_write_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old, $snippet$
         dispatch_date = case when p_patch ? 'dispatch_date' then p_patch->>'dispatch_date' else dispatch_date end,
         output_mode = case when p_patch ? 'output_mode' then p_patch->>'output_mode' else output_mode end,
         requires_stamp = case when p_patch ? 'requires_stamp' then (p_patch->>'requires_stamp')::boolean else requires_stamp end,
         workflow_template_key = p_patch->>'workflow_template_key',
$snippet$);
  execute v_sql;
end;
$migration$;

create or replace function edoc_private.complete_electronic_compose(p_document_id text, p_actor_user_id text)
returns void language plpgsql security definer set search_path = '' as $$
declare
  v_document public.official_documents%rowtype;
  v_file public.official_document_files%rowtype;
  v_record jsonb;
  v_generation integer;
  v_submit_evidence jsonb;
  v_timestamp text := pg_catalog.to_char(pg_catalog.clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS');
begin
  select * into v_document from public.official_documents where id = p_document_id for update;
  if not found or not edoc_private.is_electronic_compose(v_document)
     or v_document.current_status <> 'approved' or v_document.current_step <> 'electronic_dispatch' then
    raise exception using errcode = '42501', message = 'official_document_electronic_output_forbidden';
  end if;
  select max(workflow_generation) into v_generation from public.official_document_approval_steps where document_id = p_document_id;
  if v_generation is null or exists (
    select 1 from public.official_document_approval_steps where document_id = p_document_id
      and workflow_generation = v_generation and step_key <> 'applicant_confirm' and status <> 'approved'
  ) then
    raise exception using errcode = '55000', message = 'official_document_not_fully_approved';
  end if;
  select decision_evidence_json into v_submit_evidence from public.official_document_approval_logs
    where document_id = p_document_id and action = 'submit'
      and (decision_evidence_json->>'workflow_generation')::integer = v_generation
    order by created_at desc limit 1;
  select f.* into v_file from public.official_document_files f join public.file_objects o on o.id = f.file_object_id
    where f.document_id = p_document_id and f.file_type = 'generated_pdf'
      and f.id = v_submit_evidence->>'source_file_id'
      and f.file_hash = v_submit_evidence->>'source_sha256'
      and o.document_id = p_document_id and o.sha256 = f.file_hash and o.mime_type = 'application/pdf';
  if not found then raise exception using errcode = '22023', message = 'official_document_electronic_source_invalid'; end if;
  v_record := public.edoc_create_official_document_dispatch_record(p_document_id, p_actor_user_id);
  update public.official_documents set stamped_file_id = v_file.id,
    current_status = 'pending_general_affairs_dispatch', current_step = 'general_affairs_dispatch', updated_at = v_timestamp
    where id = p_document_id;
  insert into public.official_document_approval_logs
    (id, document_id, file_id, actor_id, actor_name, action, comment, created_at)
    values ('ODLOG-ELECTRONIC-' || pg_catalog.md5(p_document_id || ':' || v_generation),
      p_document_id, v_file.id, p_actor_user_id, coalesce((select name from public.users where id = p_actor_user_id), p_actor_user_id),
      'electronic_output_approved', 'file_hash=' || v_file.file_hash, v_timestamp);
  insert into public.notifications
    (id, type, title, target_role, target_user_id, target_company_id, target_email, channel, status, priority, source, action_url, body, created_at)
    select 'NTF-ELECTRONIC-' || pg_catalog.md5(p_document_id || ':' || v_generation), '發文寄發待辦',
      v_document.title || ' 待總務寄發', coalesce(u.role, ''), u.id, v_document.company_id,
      coalesce(u.email, ''), 'Email + 系統通知', '未讀', '高', p_document_id,
      '/#officialDispatch?document=' || p_document_id, '電子公文已核准，請完成寄發並回填寄送日期與證明。', pg_catalog.clock_timestamp()
    from public.users u where u.id = v_record#>>'{record,dispatch_owner_user_id}'
      and u.status = '啟用' and nullif(pg_catalog.btrim(u.email), '') is not null;
  if not found then raise exception using errcode = '22023', message = 'notification_exact_target_required'; end if;
end;
$$;
revoke all on function edoc_private.complete_electronic_compose(text, text) from public, anon, authenticated, service_role;

do $migration$
declare v_sql text; v_old text;
begin
  v_sql := pg_catalog.pg_get_functiondef('public.edoc_claim_official_document_approval_v3(text,text,text,text,text,jsonb)'::regprocedure);
  v_old := '  return v_result;';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_migration_approval_finalize_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old, $snippet$
  if coalesce((v_result->>'claimed')::boolean, false) and v_result->>'transition' = 'electronic_dispatch' then
    perform edoc_private.complete_electronic_compose(p_document_id, p_decision_actor_user_id);
    v_result := v_result || pg_catalog.jsonb_build_object('document_status', 'pending_general_affairs_dispatch', 'document_step', 'general_affairs_dispatch');
  end if;
  return v_result;
$snippet$);
  execute v_sql;
end;
$migration$;
commit;
