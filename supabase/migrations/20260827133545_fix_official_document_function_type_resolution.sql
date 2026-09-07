-- PostgreSQL resolves jsonb ->> array indexes as integer, while
-- WITH ORDINALITY yields bigint.  Decision literals also need an explicit
-- text type when the private validator is not available while function body
-- validation is deferred.  Patch the effective definitions so environments
-- that already applied the schema-parity migration receive the same fix.
--
-- Exact legacy/fixed occurrence checks make the migration idempotent for a
-- fresh rebuild and fail closed if any target function has drifted. Function
-- signatures do not change, so CREATE OR REPLACE preserves owners and ACLs.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

-- This helper was referenced by the V3 decision RPCs but was missing from the
-- original schema-parity migration. Keep it private and callable only through
-- the locked service-only V3 wrappers.
CREATE OR REPLACE FUNCTION edoc_private.validate_official_document_decision_evidence(
  p_document_id text,
  p_expected_step_id text,
  p_approver_user_id text,
  p_decision_actor_user_id text,
  p_decision_type text,
  p_decision_evidence jsonb
)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_document public.official_documents%rowtype;
  v_step public.official_document_approval_steps%rowtype;
  v_source public.official_document_files%rowtype;
  v_prepared public.official_document_files%rowtype;
  v_request public.official_document_stamp_requests%rowtype;
  v_revision public.official_document_editor_revisions%rowtype;
  v_file_object public.file_objects%rowtype;
  v_access_log public.official_document_approval_logs%rowtype;
  v_attachment record;
  v_entry jsonb;
  v_ack jsonb;
  v_review_access jsonb;
  v_access_entries jsonb;
  v_required_entries jsonb;
  v_attachment_entries jsonb;
  v_missing jsonb;
  v_expected_source_type text;
  v_attachment_manifest_payload text := '';
  v_attachment_manifest_sha256 text;
  v_due_text text;
  v_due_date date;
  v_log_id text;
  v_count integer;
  v_distinct_count integer;
  v_attachment_ids text[] := array[]::text[];
  v_required_ids text[] := array[]::text[];
  v_expected_required_ids text[] := array[]::text[];
  v_supplied_required_ids text[] := array[]::text[];
  v_is_v2 boolean := false;
begin
  if nullif(pg_catalog.btrim(coalesce(p_document_id, '')), '') is null
     or nullif(pg_catalog.btrim(coalesce(p_expected_step_id, '')), '') is null
     or nullif(pg_catalog.btrim(coalesce(p_approver_user_id, '')), '') is null
     or nullif(pg_catalog.btrim(coalesce(p_decision_actor_user_id, '')), '') is null
     or p_decision_type not in ('approve', 'reject')
     or pg_catalog.jsonb_typeof(coalesce(p_decision_evidence, 'null'::jsonb)) <> 'object'
     or coalesce(p_decision_evidence->>'schema_version', '') <> '2'
     or coalesce(p_decision_evidence->>'decision_type', '') <> p_decision_type then
    raise exception using errcode = '22023', message = 'official_document_decision_evidence_invalid';
  end if;

  select document.* into v_document
    from public.official_documents as document
   where document.id = p_document_id
   for share;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_not_found';
  end if;

  select step.* into v_step
    from public.official_document_approval_steps as step
   where step.id = p_expected_step_id
     and step.document_id = p_document_id
   for share;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_approval_step_not_found';
  end if;
  if v_step.status <> 'pending'
     or v_document.current_step is distinct from v_step.step_key
     or v_step.approver_user_id is distinct from p_approver_user_id
     or coalesce(p_decision_evidence->>'expected_step_id', '') <> p_expected_step_id
     or coalesce(p_decision_evidence->>'principal_actor_id', '') <> p_approver_user_id
     or coalesce(p_decision_evidence->>'decision_actor_user_id', '') <> p_decision_actor_user_id then
    raise exception using errcode = '42501', message = 'official_document_decision_evidence_actor_mismatch';
  end if;
  if p_decision_actor_user_id = v_document.applicant_id
     and v_step.step_key <> 'applicant_confirm' then
    raise exception using errcode = '42501', message = 'applicant_cannot_self_approve';
  end if;
  perform edoc_private.assert_official_decision_actor(
    v_document.company_id,
    p_approver_user_id,
    p_decision_actor_user_id
  );

  v_ack := p_decision_evidence->'review_acknowledgements';
  if pg_catalog.jsonb_typeof(coalesce(v_ack, 'null'::jsonb)) <> 'object'
     or v_ack->'original_reviewed' is distinct from 'true'::jsonb
     or v_ack->'edited_version_reviewed' is distinct from 'true'::jsonb
     or v_ack->'attachments_reviewed' is distinct from 'true'::jsonb then
    raise exception using errcode = '22023', message = 'official_document_review_acknowledgements_required';
  end if;

  v_expected_source_type := case
    when v_document.source_type = 'uploaded_pdf' then 'original_pdf'
    else 'generated_pdf'
  end;
  select file.* into v_source
    from public.official_document_files as file
   where file.document_id = p_document_id
     and file.file_type = v_expected_source_type
   order by file.version desc, file.created_at desc, file.id desc
   limit 1
   for share;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_source_pdf_required';
  end if;
  v_entry := p_decision_evidence->'source_file';
  if pg_catalog.jsonb_typeof(coalesce(v_entry, 'null'::jsonb)) <> 'object'
     or coalesce(v_entry->>'id', '') <> v_source.id
     or coalesce(v_entry->>'type', '') <> v_source.file_type
     or pg_catalog.lower(coalesce(v_entry->>'sha256', ''))
          <> pg_catalog.lower(v_source.file_hash)
     or coalesce(v_entry->>'version', '') <> v_source.version::text
     or coalesce(v_entry->>'size', '') <> v_source.file_size::text then
    raise exception using errcode = '22023', message = 'official_document_source_evidence_mismatch';
  end if;
  select object.* into v_file_object
    from public.file_objects as object
   where object.id = v_source.file_object_id
   for share;
  if not found
     or v_file_object.document_id is distinct from p_document_id
     or pg_catalog.lower(v_file_object.sha256) is distinct from pg_catalog.lower(v_source.file_hash)
     or v_file_object.size_bytes is distinct from v_source.file_size
     or (
       v_source.file_type = 'original_pdf'
       and pg_catalog.lower(pg_catalog.btrim(coalesce(v_file_object.scan_status, '')))
         not in ('已通過', 'clean', 'passed')
     ) then
    raise exception using errcode = '22023', message = 'official_document_source_file_invalid';
  end if;

  select request.* into v_request
    from public.official_document_stamp_requests as request
   where request.document_id = p_document_id
   order by request.created_at desc, request.id desc
   limit 1
   for share;
  v_is_v2 := found and (
    nullif(pg_catalog.btrim(coalesce(v_request.locked_editor_revision_id, '')), '') is not null
    or nullif(pg_catalog.btrim(coalesce(v_request.locked_source_sha256, '')), '') is not null
    or nullif(pg_catalog.btrim(coalesce(v_request.prepared_file_id, '')), '') is not null
    or nullif(pg_catalog.btrim(coalesce(v_request.prepared_sha256, '')), '') is not null
    or nullif(pg_catalog.btrim(coalesce(v_request.editor_manifest_sha256, '')), '') is not null
    or coalesce(v_request.editor_schema_version, 0) <> 0
    or nullif(pg_catalog.btrim(coalesce(v_request.renderer_version, '')), '') is not null
  );

  if v_is_v2 then
    if nullif(pg_catalog.btrim(coalesce(v_request.locked_editor_revision_id, '')), '') is null
       or coalesce(v_request.locked_source_sha256, '') !~ '^[0-9A-Fa-f]{64}$'
       or nullif(pg_catalog.btrim(coalesce(v_request.prepared_file_id, '')), '') is null
       or coalesce(v_request.prepared_sha256, '') !~ '^[0-9A-Fa-f]{64}$'
       or coalesce(v_request.editor_manifest_sha256, '') !~ '^[0-9A-Fa-f]{64}$'
       or coalesce(v_request.editor_schema_version, 0) < 2
       or nullif(pg_catalog.btrim(coalesce(v_request.renderer_version, '')), '') is null
       or p_decision_evidence->'legacy_renderer' is distinct from 'false'::jsonb
       or pg_catalog.lower(coalesce(p_decision_evidence->>'source_bundle_sha256', ''))
            <> pg_catalog.lower(v_request.locked_source_sha256)
       or pg_catalog.lower(coalesce(p_decision_evidence->>'prepared_sha256', ''))
            <> pg_catalog.lower(v_request.prepared_sha256)
       or pg_catalog.lower(coalesce(p_decision_evidence->>'manifest_sha256', ''))
            <> pg_catalog.lower(v_request.editor_manifest_sha256)
       or coalesce(p_decision_evidence->>'editor_revision_id', '')
            <> v_request.locked_editor_revision_id
       or coalesce(p_decision_evidence->>'editor_schema_version', '')
            <> v_request.editor_schema_version::text
       or coalesce(p_decision_evidence->>'renderer_version', '')
            <> v_request.renderer_version then
      raise exception using errcode = '22023', message = 'official_document_editor_decision_lock_incomplete';
    end if;

    select revision.* into v_revision
      from public.official_document_editor_revisions as revision
     where revision.id = v_request.locked_editor_revision_id
       and revision.document_id = p_document_id
     for share;
    if not found
       or pg_catalog.lower(v_revision.manifest_sha256)
            is distinct from pg_catalog.lower(v_request.editor_manifest_sha256) then
      raise exception using errcode = '22023', message = 'editor_locked_revision_invalid';
    end if;

    select file.* into v_prepared
      from public.official_document_files as file
     where file.id = v_request.prepared_file_id
       and file.document_id = p_document_id
       and file.file_type = 'prepared_pdf'
     for share;
    if not found
       or pg_catalog.lower(v_prepared.file_hash)
            is distinct from pg_catalog.lower(v_request.prepared_sha256) then
      raise exception using errcode = '22023', message = 'official_document_prepared_file_missing';
    end if;
    select object.* into v_file_object
      from public.file_objects as object
     where object.id = v_prepared.file_object_id
     for share;
    if not found
       or v_file_object.document_id is distinct from p_document_id
       or pg_catalog.lower(v_file_object.sha256) is distinct from pg_catalog.lower(v_prepared.file_hash)
       or v_file_object.size_bytes is distinct from v_prepared.file_size then
      raise exception using errcode = '22023', message = 'official_document_prepared_file_invalid';
    end if;
    if not exists (
      select 1
        from public.official_document_editor_assets as asset
       where asset.document_id = p_document_id
         and asset.editor_revision_id = v_request.locked_editor_revision_id
         and asset.asset_kind = 'prepared_pdf'
         and asset.official_file_id = v_prepared.id
         and pg_catalog.lower(asset.sha256) = pg_catalog.lower(v_prepared.file_hash)
         and asset.preflight_status = 'passed'
    ) then
      raise exception using errcode = '22023', message = 'editor_preflight_not_completed';
    end if;
    v_entry := p_decision_evidence->'prepared_file';
    if pg_catalog.jsonb_typeof(coalesce(v_entry, 'null'::jsonb)) <> 'object'
       or coalesce(v_entry->>'id', '') <> v_prepared.id
       or coalesce(v_entry->>'type', '') <> v_prepared.file_type
       or pg_catalog.lower(coalesce(v_entry->>'sha256', ''))
            <> pg_catalog.lower(v_prepared.file_hash)
       or coalesce(v_entry->>'version', '') <> v_prepared.version::text
       or coalesce(v_entry->>'size', '') <> v_prepared.file_size::text then
      raise exception using errcode = '22023', message = 'official_document_prepared_evidence_mismatch';
    end if;
  else
    if p_decision_evidence->'legacy_renderer' is distinct from 'true'::jsonb
       or pg_catalog.jsonb_typeof(coalesce(p_decision_evidence->'prepared_file', 'null'::jsonb)) <> 'null'
       or coalesce(p_decision_evidence->>'source_bundle_sha256', '') <> ''
       or coalesce(p_decision_evidence->>'prepared_sha256', '') <> ''
       or coalesce(p_decision_evidence->>'manifest_sha256', '') <> ''
       or coalesce(p_decision_evidence->>'editor_revision_id', '') <> ''
       or coalesce(p_decision_evidence->>'editor_schema_version', '') not in ('', '0')
       or coalesce(p_decision_evidence->>'renderer_version', '') <> '' then
      raise exception using errcode = '22023', message = 'official_document_legacy_renderer_evidence_invalid';
    end if;
  end if;

  v_attachment_entries := p_decision_evidence->'attachments';
  if pg_catalog.jsonb_typeof(coalesce(v_attachment_entries, 'null'::jsonb)) <> 'array' then
    raise exception using errcode = '22023', message = 'official_document_attachment_evidence_invalid';
  end if;
  select
    coalesce(pg_catalog.string_agg(
      pg_catalog.char_length(file.id)::text || ':' || file.id || '|'
      || pg_catalog.char_length(file.file_type)::text || ':' || file.file_type || '|'
      || pg_catalog.upper(file.file_hash) || '|'
      || file.version::text || '|' || file.file_size::text,
      E'\n' order by file.id
    ), ''),
    coalesce(pg_catalog.array_agg(file.id order by file.id), array[]::text[])
    into v_attachment_manifest_payload, v_attachment_ids
    from public.official_document_files as file
   where file.document_id = p_document_id
     and file.file_type = 'attachment';
  if pg_catalog.jsonb_array_length(v_attachment_entries) <> pg_catalog.cardinality(v_attachment_ids) then
    raise exception using errcode = '22023', message = 'official_document_attachment_evidence_invalid';
  end if;
  v_attachment_manifest_sha256 := pg_catalog.encode(
    extensions.digest(pg_catalog.convert_to(v_attachment_manifest_payload, 'UTF8'), 'sha256'),
    'hex'
  );
  if pg_catalog.lower(coalesce(p_decision_evidence->>'attachments_manifest_sha256', ''))
       <> v_attachment_manifest_sha256 then
    raise exception using errcode = '22023', message = 'official_document_attachment_manifest_mismatch';
  end if;

  for v_attachment in
    select file.*
      from public.official_document_files as file
     where file.document_id = p_document_id
       and file.file_type = 'attachment'
     order by file.id
     for share
  loop
    select pg_catalog.count(*) into v_count
      from pg_catalog.jsonb_array_elements(v_attachment_entries) as item(value)
     where item.value->>'id' = v_attachment.id;
    if v_count <> 1 then
      raise exception using errcode = '22023', message = 'official_document_attachment_evidence_invalid';
    end if;
    select item.value into v_entry
      from pg_catalog.jsonb_array_elements(v_attachment_entries) as item(value)
     where item.value->>'id' = v_attachment.id;
    if pg_catalog.jsonb_typeof(v_entry) <> 'object'
       or coalesce(v_entry->>'type', '') <> v_attachment.file_type
       or pg_catalog.lower(coalesce(v_entry->>'sha256', ''))
            <> pg_catalog.lower(v_attachment.file_hash)
       or coalesce(v_entry->>'version', '') <> v_attachment.version::text
       or coalesce(v_entry->>'size', '') <> v_attachment.file_size::text then
      raise exception using errcode = '22023', message = 'official_document_attachment_evidence_invalid';
    end if;
    select object.* into v_file_object
      from public.file_objects as object
     where object.id = v_attachment.file_object_id
     for share;
    if not found
       or v_file_object.document_id is distinct from p_document_id
       or pg_catalog.lower(v_file_object.sha256) is distinct from pg_catalog.lower(v_attachment.file_hash)
       or v_file_object.size_bytes is distinct from v_attachment.file_size
       or pg_catalog.lower(pg_catalog.btrim(coalesce(v_file_object.scan_status, '')))
            not in ('已通過', 'clean', 'passed') then
      raise exception using errcode = '22023', message = 'official_document_attachment_file_invalid';
    end if;
  end loop;

  if nullif(pg_catalog.btrim(coalesce(v_step.review_started_at, '')), '') is null then
    raise exception using errcode = '22023', message = 'official_document_review_session_not_started';
  end if;
  v_review_access := p_decision_evidence->'review_access';
  v_required_entries := v_review_access->'required_file_ids';
  v_access_entries := v_review_access->'access_logs';
  if pg_catalog.jsonb_typeof(coalesce(v_review_access, 'null'::jsonb)) <> 'object'
     or v_review_access->'server_verified' is distinct from 'true'::jsonb
     or coalesce(v_review_access->>'step_started_at', '') <> v_step.review_started_at
     or pg_catalog.jsonb_typeof(coalesce(v_required_entries, 'null'::jsonb)) <> 'array'
     or pg_catalog.jsonb_typeof(coalesce(v_access_entries, 'null'::jsonb)) <> 'array' then
    raise exception using errcode = '22023', message = 'official_document_review_access_invalid';
  end if;
  v_required_ids := array[v_source.id];
  if v_is_v2 then
    v_required_ids := v_required_ids || v_prepared.id;
  end if;
  v_required_ids := v_required_ids || v_attachment_ids;
  select pg_catalog.array_agg(item order by item)
    into v_expected_required_ids
    from pg_catalog.unnest(v_required_ids) as item;
  if exists (
    select 1
      from pg_catalog.jsonb_array_elements(v_required_entries) as item(value)
     where pg_catalog.jsonb_typeof(item.value) <> 'string'
  ) then
    raise exception using errcode = '22023', message = 'official_document_review_access_invalid';
  end if;
  select
    coalesce(pg_catalog.array_agg(item.value order by item.value), array[]::text[]),
    pg_catalog.count(*),
    pg_catalog.count(distinct item.value)
    into v_supplied_required_ids, v_count, v_distinct_count
    from pg_catalog.jsonb_array_elements_text(v_required_entries) as item(value);
  if v_supplied_required_ids is distinct from v_expected_required_ids
     or v_count <> pg_catalog.cardinality(v_expected_required_ids)
     or v_distinct_count <> v_count
     or pg_catalog.jsonb_array_length(v_access_entries) <> v_count then
    raise exception using errcode = '22023', message = 'official_document_review_access_invalid';
  end if;

  foreach v_log_id in array v_expected_required_ids
  loop
    select pg_catalog.count(*) into v_count
      from pg_catalog.jsonb_array_elements(v_access_entries) as item(value)
     where item.value->>'file_id' = v_log_id;
    if v_count <> 1 then
      raise exception using errcode = '22023', message = 'official_document_review_access_invalid';
    end if;
    select item.value into v_entry
      from pg_catalog.jsonb_array_elements(v_access_entries) as item(value)
     where item.value->>'file_id' = v_log_id;
    if pg_catalog.jsonb_typeof(v_entry) <> 'object'
       or coalesce(v_entry->>'action', '') <> 'download_file'
       or nullif(pg_catalog.btrim(coalesce(v_entry->>'access_log_id', '')), '') is null then
      raise exception using errcode = '22023', message = 'official_document_review_access_invalid';
    end if;
    select log.* into v_access_log
      from public.official_document_approval_logs as log
     where log.id = v_entry->>'access_log_id'
     for share;
    if not found
       or v_access_log.document_id is distinct from p_document_id
       or v_access_log.actor_id is distinct from p_decision_actor_user_id
       or v_access_log.file_id is distinct from v_log_id
       or v_access_log.action <> 'download_file'
       or v_access_log.created_at < v_step.review_started_at
       or coalesce(v_entry->>'accessed_at', '') <> v_access_log.created_at then
      raise exception using errcode = '22023', message = 'official_document_review_access_required';
    end if;
  end loop;

  if p_decision_type = 'reject' then
    if nullif(pg_catalog.btrim(coalesce(p_decision_evidence->>'reason_category', '')), '') is null
       or pg_catalog.char_length(pg_catalog.btrim(p_decision_evidence->>'reason_category')) > 80 then
      raise exception using errcode = '22023', message = 'official_document_rejection_reason_category_required';
    end if;
    v_missing := coalesce(p_decision_evidence->'missing_items', 'null'::jsonb);
    if pg_catalog.jsonb_typeof(v_missing) <> 'array'
       or pg_catalog.jsonb_array_length(v_missing) > 50
       or exists (
         select 1
           from pg_catalog.jsonb_array_elements(v_missing) as item(value)
          where pg_catalog.jsonb_typeof(item.value) <> 'string'
             or nullif(pg_catalog.btrim(item.value #>> array[]::text[]), '') is null
             or pg_catalog.char_length(pg_catalog.btrim(item.value #>> array[]::text[])) > 240
       ) then
      raise exception using errcode = '22023', message = 'official_document_rejection_missing_items_invalid';
    end if;
    v_due_text := pg_catalog.btrim(coalesce(p_decision_evidence->>'correction_due_date', ''));
    if v_due_text <> '' then
      if v_due_text !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' then
        raise exception using errcode = '22023', message = 'official_document_correction_due_date_invalid';
      end if;
      begin
        v_due_date := v_due_text::date;
      exception when others then
        raise exception using errcode = '22023', message = 'official_document_correction_due_date_invalid';
      end;
      if pg_catalog.to_char(v_due_date, 'YYYY-MM-DD') <> v_due_text then
        raise exception using errcode = '22023', message = 'official_document_correction_due_date_invalid';
      end if;
      if v_due_date < current_date then
        raise exception using errcode = '22023', message = 'official_document_correction_due_date_in_past';
      end if;
    end if;
  end if;

  return p_decision_evidence;
end;
$function$;

alter function edoc_private.validate_official_document_decision_evidence(
  text, text, text, text, text, jsonb
) owner to postgres;
revoke all on function edoc_private.validate_official_document_decision_evidence(
  text, text, text, text, text, jsonb
) from public, anon, authenticated, service_role;

do $official_document_function_type_resolution$
declare
  v_oid oid;
  v_definition text;
  v_legacy_count integer;
  v_fixed_count integer;
  v_legacy_position constant text :=
    'p_position_ids->>(v_position_index - 1)';
  v_fixed_position constant text :=
    'p_position_ids->>((v_position_index - 1)::integer)';
  v_legacy_overlay constant text :=
    'p_overlay_ids->>(v_overlay_index - 1)';
  v_fixed_overlay constant text :=
    'p_overlay_ids->>((v_overlay_index - 1)::integer)';
  v_legacy_approve constant text := '''approve'',';
  v_fixed_approve constant text := '''approve''::text,';
  v_legacy_reject constant text := '''reject'',';
  v_fixed_reject constant text := '''reject''::text,';
begin
  v_oid := pg_catalog.to_regprocedure(
    'public.edoc_apply_official_document_correction(text,text,text,jsonb,text,jsonb,jsonb,text,jsonb,jsonb,text,text,text,text,text,text,jsonb,text,text)'
  );
  if v_oid is null then
    raise exception using
      errcode = '55000',
      message = 'edoc_function_type_resolution_rpc_missing:correction';
  end if;

  v_definition := pg_catalog.pg_get_functiondef(v_oid);
  v_legacy_count := (
    pg_catalog.length(v_definition)
    - pg_catalog.length(
        pg_catalog.replace(v_definition, v_legacy_position, '')
      )
  ) / pg_catalog.length(v_legacy_position);
  v_fixed_count := (
    pg_catalog.length(v_definition)
    - pg_catalog.length(
        pg_catalog.replace(v_definition, v_fixed_position, '')
      )
  ) / pg_catalog.length(v_fixed_position);
  if (v_legacy_count, v_fixed_count) not in ((1, 0), (0, 1)) then
    raise exception using
      errcode = '55000',
      message = 'edoc_function_type_resolution_definition_drift:position:'
        || v_legacy_count::text || ':' || v_fixed_count::text;
  end if;
  if v_legacy_count = 1 then
    v_definition := pg_catalog.replace(
      v_definition,
      v_legacy_position,
      v_fixed_position
    );
  end if;

  v_legacy_count := (
    pg_catalog.length(v_definition)
    - pg_catalog.length(
        pg_catalog.replace(v_definition, v_legacy_overlay, '')
      )
  ) / pg_catalog.length(v_legacy_overlay);
  v_fixed_count := (
    pg_catalog.length(v_definition)
    - pg_catalog.length(
        pg_catalog.replace(v_definition, v_fixed_overlay, '')
      )
  ) / pg_catalog.length(v_fixed_overlay);
  if (v_legacy_count, v_fixed_count) not in ((1, 0), (0, 1)) then
    raise exception using
      errcode = '55000',
      message = 'edoc_function_type_resolution_definition_drift:overlay:'
        || v_legacy_count::text || ':' || v_fixed_count::text;
  end if;
  if v_legacy_count = 1 then
    v_definition := pg_catalog.replace(
      v_definition,
      v_legacy_overlay,
      v_fixed_overlay
    );
  end if;
  execute v_definition;

  v_definition := pg_catalog.pg_get_functiondef(v_oid);
  if pg_catalog.strpos(v_definition, v_legacy_position) <> 0
     or pg_catalog.strpos(v_definition, v_fixed_position) = 0
     or pg_catalog.strpos(v_definition, v_legacy_overlay) <> 0
     or pg_catalog.strpos(v_definition, v_fixed_overlay) = 0 then
    raise exception using
      errcode = '55000',
      message = 'edoc_function_type_resolution_rewrite_failed:correction';
  end if;

  v_oid := pg_catalog.to_regprocedure(
    'public.edoc_claim_official_document_approval_v3(text,text,text,text,text,jsonb)'
  );
  if v_oid is null then
    raise exception using
      errcode = '55000',
      message = 'edoc_function_type_resolution_rpc_missing:approval';
  end if;
  v_definition := pg_catalog.pg_get_functiondef(v_oid);
  v_legacy_count := (
    pg_catalog.length(v_definition)
    - pg_catalog.length(
        pg_catalog.replace(v_definition, v_legacy_approve, '')
      )
  ) / pg_catalog.length(v_legacy_approve);
  v_fixed_count := (
    pg_catalog.length(v_definition)
    - pg_catalog.length(
        pg_catalog.replace(v_definition, v_fixed_approve, '')
      )
  ) / pg_catalog.length(v_fixed_approve);
  if (v_legacy_count, v_fixed_count) not in ((1, 0), (0, 1)) then
    raise exception using
      errcode = '55000',
      message = 'edoc_function_type_resolution_definition_drift:approval:'
        || v_legacy_count::text || ':' || v_fixed_count::text;
  end if;
  if v_legacy_count = 1 then
    execute pg_catalog.replace(
      v_definition,
      v_legacy_approve,
      v_fixed_approve
    );
  end if;

  v_definition := pg_catalog.pg_get_functiondef(v_oid);
  if pg_catalog.strpos(v_definition, v_legacy_approve) <> 0
     or pg_catalog.strpos(v_definition, v_fixed_approve) = 0 then
    raise exception using
      errcode = '55000',
      message = 'edoc_function_type_resolution_rewrite_failed:approval';
  end if;

  v_oid := pg_catalog.to_regprocedure(
    'public.edoc_claim_official_document_rejection_v3(text,text,text,text,text,jsonb)'
  );
  if v_oid is null then
    raise exception using
      errcode = '55000',
      message = 'edoc_function_type_resolution_rpc_missing:rejection';
  end if;
  v_definition := pg_catalog.pg_get_functiondef(v_oid);
  v_legacy_count := (
    pg_catalog.length(v_definition)
    - pg_catalog.length(
        pg_catalog.replace(v_definition, v_legacy_reject, '')
      )
  ) / pg_catalog.length(v_legacy_reject);
  v_fixed_count := (
    pg_catalog.length(v_definition)
    - pg_catalog.length(
        pg_catalog.replace(v_definition, v_fixed_reject, '')
      )
  ) / pg_catalog.length(v_fixed_reject);
  if (v_legacy_count, v_fixed_count) not in ((1, 0), (0, 1)) then
    raise exception using
      errcode = '55000',
      message = 'edoc_function_type_resolution_definition_drift:rejection:'
        || v_legacy_count::text || ':' || v_fixed_count::text;
  end if;
  if v_legacy_count = 1 then
    execute pg_catalog.replace(
      v_definition,
      v_legacy_reject,
      v_fixed_reject
    );
  end if;

  v_definition := pg_catalog.pg_get_functiondef(v_oid);
  if pg_catalog.strpos(v_definition, v_legacy_reject) <> 0
     or pg_catalog.strpos(v_definition, v_fixed_reject) = 0 then
    raise exception using
      errcode = '55000',
      message = 'edoc_function_type_resolution_rewrite_failed:rejection';
  end if;
end
$official_document_function_type_resolution$;

-- Re-emit the complete inbound mutation contract for projects that already
-- recorded the original migration. Keep the prior conflict-code and fixed
-- search-path hardening while changing database timestamps to timestamptz.
create or replace function public.edoc_mutate_inbound_document_v1(
  p_mutation_type text,
  p_idempotency_key text,
  p_request_sha256 text,
  p_actor_user_id text,
  p_document_id text,
  p_expected_version bigint,
  p_payload jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, extensions
as $$
declare
  v_actor public.users%rowtype;
  v_company public.companies%rowtype;
  v_assignee public.users%rowtype;
  v_document public.inbound_documents%rowtype;
  v_existing_mutation public.inbound_document_mutations%rowtype;
  v_profile jsonb := '{}'::jsonb;
  v_metadata jsonb := '{}'::jsonb;
  v_response jsonb;
  v_ledger_response jsonb;
  v_payload jsonb := coalesce(p_payload, '{}'::jsonb);
  v_mutation text := lower(btrim(coalesce(p_mutation_type, '')));
  v_document_id text := nullif(btrim(coalesce(p_document_id, '')), '');
  v_source_type text;
  v_unit_name text;
  v_unit_id text;
  v_requested_unit text;
  v_is_privileged boolean := false;
  v_current_version bigint;
  v_now timestamptz := clock_timestamp();
  v_action text;
  v_event_type text;
begin
  if v_mutation not in ('draft', 'register', 'assign', 'exception', 'close') then
    raise exception using message = 'inbound_mutation_type_invalid', errcode = '22023';
  end if;
  if coalesce(p_idempotency_key, '') !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$' then
    raise exception using message = 'inbound_idempotency_key_required', errcode = '22023';
  end if;
  if coalesce(p_request_sha256, '') !~ '^[0-9a-f]{64}$' then
    raise exception using message = 'inbound_request_hash_invalid', errcode = '22023';
  end if;
  if nullif(btrim(coalesce(p_actor_user_id, '')), '') is null then
    raise exception using message = 'authentication_required', errcode = '42501';
  end if;

  -- Serializes concurrent first-use/retry attempts for one idempotency key.
  perform pg_advisory_xact_lock(hashtextextended(p_idempotency_key, 0));
  select * into v_existing_mutation
  from public.inbound_document_mutations
  where idempotency_key = p_idempotency_key;
  if found then
    if v_existing_mutation.actor_user_id <> p_actor_user_id
       or v_existing_mutation.mutation_type <> v_mutation
       or v_existing_mutation.request_sha256 <> p_request_sha256 then
      raise exception using message = 'inbound_idempotency_conflict', errcode = 'PT409';
    end if;
    v_response := v_existing_mutation.response_json::jsonb;
    select * into v_document
    from public.inbound_documents
    where id = v_existing_mutation.inbound_document_id;
    if not found
       or v_document.company_id <> v_existing_mutation.company_id
       or v_document.finance_tenant_id <> v_existing_mutation.finance_tenant_id then
      raise exception using message = 'inbound_idempotency_item_scope_invalid', errcode = 'XX001';
    end if;
    if v_document.mutation_version = (v_response ->> 'version')::bigint then
      if encode(digest(to_jsonb(v_document)::text, 'sha256'), 'hex')
         <> coalesce(v_response ->> 'item_sha256', '') then
        raise exception using message = 'inbound_idempotency_item_hash_mismatch', errcode = 'XX001';
      end if;
      v_response := jsonb_set(v_response, '{item}', to_jsonb(v_document), true);
      v_response := jsonb_set(v_response, '{ledger_hash_verified}', 'true'::jsonb, true);
    else
      v_response := jsonb_set(v_response, '{ledger_hash_verified}', 'false'::jsonb, true);
    end if;
    return jsonb_set(v_response, '{replayed}', 'true'::jsonb, true);
  end if;

  select * into v_actor
  from public.users
  where id = p_actor_user_id
  for share;
  if not found
     or v_actor.status <> '啟用'
     or lower(btrim(coalesce(v_actor.account_source, ''))) <> 'finance' then
    raise exception using message = 'finance_identity_required', errcode = '42501';
  end if;
  if nullif(btrim(coalesce(v_actor.company_id, '')), '') is null
     or nullif(btrim(coalesce(v_actor.finance_tenant_id, '')), '') is null then
    raise exception using message = 'finance_scope_required', errcode = '42501';
  end if;

  select * into v_company
  from public.companies
  where id = v_actor.company_id
  for share;
  if not found
     or lower(btrim(coalesce(v_company.source_system, ''))) <> 'finance'
     or lower(btrim(coalesce(v_company.status, ''))) <> 'active'
     or nullif(btrim(coalesce(v_company.finance_tenant_id, '')), '') is null
     or v_company.finance_tenant_id <> v_actor.finance_tenant_id then
    raise exception using message = 'finance_company_scope_invalid', errcode = '42501';
  end if;

  v_unit_name := nullif(btrim(coalesce(v_actor.unit, '')), '');
  if v_unit_name is null then
    raise exception using message = 'finance_unit_required', errcode = '42501';
  end if;
  begin
    v_profile := coalesce(nullif(btrim(coalesce(v_actor.external_account_payload_json, '')), '')::jsonb, '{}'::jsonb);
  exception when others then
    raise exception using message = 'finance_unit_profile_invalid', errcode = '42501';
  end;
  v_unit_id := coalesce(
    nullif(btrim(v_profile #>> '{financeProfile,departmentCode}'), ''),
    nullif(btrim(v_profile ->> 'departmentCode'), ''),
    v_unit_name
  );

  select exists (
    select 1
    from public.roles role_row
    join public.role_permissions role_permission_row
      on role_permission_row.role_id = role_row.id
    join public.permissions permission_row
      on permission_row.id = role_permission_row.permission_id
    where role_row.name = v_actor.role
      and role_row.status = '啟用'
      and permission_row.code in ('official_documents.receive', 'official_documents.all_todo')
  ) or v_actor.role in ('總務', '行政部主任', '行政部門主任', '執行長')
  into v_is_privileged;

  if v_mutation in ('draft', 'register') then
    v_source_type := nullif(btrim(coalesce(v_payload ->> 'source_type', '')), '');
    if v_source_type is null and p_expected_version is null then
      v_source_type := 'local_unit_physical';
    end if;
    -- Local-unit physical mail is available to every Finance user.  The two
    -- General Affairs channels require the receive permission.  Manual/mock
    -- and formal exchange ingestion stay on their separate backend contracts.
    if v_source_type not in (
      'local_unit_physical',
      'general_affairs_email',
      'general_affairs_physical'
    ) then
      raise exception using message = 'inbound_source_type_forbidden', errcode = '42501';
    end if;
    if v_source_type in ('general_affairs_email', 'general_affairs_physical')
       and not v_is_privileged then
      raise exception using message = 'inbound_source_type_forbidden', errcode = '42501';
    end if;
    foreach v_requested_unit in array array[
      nullif(btrim(coalesce(v_payload ->> 'recipient_department_id', '')), ''),
      nullif(btrim(coalesce(v_payload ->> 'department_id', '')), ''),
      nullif(btrim(coalesce(v_payload ->> 'recipient_department_name', '')), ''),
      nullif(btrim(coalesce(v_payload ->> 'department', '')), '')
    ] loop
      if v_requested_unit is not null
         and v_requested_unit <> v_unit_id
         and v_requested_unit <> v_unit_name then
        raise exception using message = 'finance_unit_payload_mismatch', errcode = '42501';
      end if;
    end loop;

    if p_expected_version is null then
      if v_document_id is null then
        v_document_id := 'INB-' || to_char(clock_timestamp(), 'YYYYMMDDHH24MISSMS') || '-' || upper(encode(gen_random_bytes(4), 'hex'));
      end if;
      insert into public.inbound_documents (
        id, company_id, finance_tenant_id, receive_no, source_type,
        external_exchange_id, sender_name, sender_contact, subject, body,
        recipient_department_id, recipient_department_name, due_at, priority,
        security_level, status, metadata_json, mutation_version, created_by,
        created_at, updated_at
      ) values (
        v_document_id,
        v_actor.company_id,
        v_actor.finance_tenant_id,
        coalesce(nullif(btrim(v_payload ->> 'receive_no'), ''), '收文字第' || replace(v_document_id, 'INB-', '')),
        v_source_type,
        coalesce(v_payload ->> 'external_exchange_id', v_payload ->> 'exchange_id', ''),
        coalesce(nullif(btrim(coalesce(v_payload ->> 'sender_name', v_payload ->> 'agency_name')), ''), '未指定來文單位'),
        coalesce(v_payload ->> 'sender_contact', ''),
        coalesce(nullif(btrim(v_payload ->> 'subject'), ''), '未命名收文'),
        coalesce(v_payload ->> 'body', v_payload ->> 'description', ''),
        v_unit_id,
        v_unit_name,
        coalesce(v_payload ->> 'due_at', ''),
        coalesce(nullif(btrim(v_payload ->> 'priority'), ''), '普通件'),
        coalesce(nullif(btrim(v_payload ->> 'security_level'), ''), '普通'),
        case when v_mutation = 'draft' then 'draft' else 'registered' end,
        case when jsonb_typeof(v_payload -> 'metadata') = 'object'
          then (v_payload -> 'metadata')::text else '{}' end,
        1,
        v_actor.id,
        v_now,
        v_now
      )
      returning * into v_document;
    else
      select * into v_document
      from public.inbound_documents
      where id = v_document_id
      for update;
      if not found then
        raise exception using message = 'inbound_document_not_found', errcode = 'P0002';
      end if;
      if nullif(btrim(coalesce(v_document.company_id, '')), '') is null
         or nullif(btrim(coalesce(v_document.finance_tenant_id, '')), '') is null
         or v_document.company_id <> v_actor.company_id
         or v_document.finance_tenant_id <> v_actor.finance_tenant_id then
        raise exception using message = 'inbound_document_scope_forbidden', errcode = '42501';
      end if;
      if v_document.created_by <> v_actor.id and not v_is_privileged then
        raise exception using message = 'inbound_document_mutation_forbidden', errcode = '42501';
      end if;
      if v_document.status <> 'draft' then
        raise exception using message = 'inbound_registration_state_conflict', errcode = 'PT409';
      end if;
      if p_expected_version is null or p_expected_version <> v_document.mutation_version then
        raise exception using message = 'inbound_version_conflict', errcode = 'PT409';
      end if;
      v_source_type := coalesce(v_source_type, v_document.source_type);
      if v_document.source_type not in (
        'local_unit_physical',
        'general_affairs_email',
        'general_affairs_physical'
      ) or v_source_type <> v_document.source_type then
        raise exception using message = 'inbound_source_type_immutable', errcode = '42501';
      end if;
      begin
        v_metadata := coalesce(nullif(btrim(coalesce(v_document.metadata_json, '')), '')::jsonb, '{}'::jsonb);
      exception when others then
        raise exception using message = 'inbound_metadata_invalid', errcode = '22023';
      end;
      if jsonb_typeof(v_payload -> 'metadata') = 'object' then
        v_metadata := v_metadata || (v_payload -> 'metadata');
      end if;
      v_current_version := v_document.mutation_version;
      update public.inbound_documents
      set receive_no = coalesce(v_payload ->> 'receive_no', receive_no),
          sender_name = coalesce(v_payload ->> 'sender_name', v_payload ->> 'agency_name', sender_name),
          sender_contact = coalesce(v_payload ->> 'sender_contact', sender_contact),
          subject = coalesce(v_payload ->> 'subject', subject),
          body = coalesce(v_payload ->> 'body', v_payload ->> 'description', body),
          recipient_department_id = v_unit_id,
          recipient_department_name = v_unit_name,
          due_at = coalesce(v_payload ->> 'due_at', due_at),
          priority = coalesce(v_payload ->> 'priority', priority),
          security_level = coalesce(v_payload ->> 'security_level', security_level),
          status = case when v_mutation = 'draft' then 'draft' else 'registered' end,
          metadata_json = v_metadata::text,
          mutation_version = mutation_version + 1,
          updated_at = v_now
      where id = v_document_id
        and mutation_version = v_current_version
        and status = 'draft'
      returning * into v_document;
      if not found then
        raise exception using message = 'inbound_version_conflict', errcode = 'PT409';
      end if;
    end if;
  else
    if not v_is_privileged then
      raise exception using message = case
        when v_mutation = 'assign' then 'inbound_assignment_forbidden'
        when v_mutation = 'exception' then 'inbound_exception_forbidden'
        else 'inbound_close_forbidden'
      end, errcode = '42501';
    end if;
    if v_document_id is null then
      raise exception using message = 'inbound_document_not_found', errcode = 'P0002';
    end if;
    select * into v_document
    from public.inbound_documents
    where id = v_document_id
    for update;
    if not found then
      raise exception using message = 'inbound_document_not_found', errcode = 'P0002';
    end if;
    if nullif(btrim(coalesce(v_document.company_id, '')), '') is null
       or nullif(btrim(coalesce(v_document.finance_tenant_id, '')), '') is null
       or v_document.company_id <> v_actor.company_id
       or v_document.finance_tenant_id <> v_actor.finance_tenant_id then
      raise exception using message = 'inbound_document_scope_forbidden', errcode = '42501';
    end if;
    if p_expected_version is null or p_expected_version <> v_document.mutation_version then
      raise exception using message = 'inbound_version_conflict', errcode = 'PT409';
    end if;
    if v_document.status in ('draft', 'closed', 'archived', 'cancelled') then
      raise exception using message = 'inbound_mutation_state_conflict', errcode = 'PT409';
    end if;
    v_current_version := v_document.mutation_version;

    if v_mutation = 'assign' then
      if nullif(btrim(coalesce(v_payload ->> 'assignee_user_id', v_payload ->> 'user_id')), '') is null then
        raise exception using message = 'inbound_assignee_required', errcode = '22023';
      end if;
      select * into v_assignee
      from public.users
      where id = coalesce(v_payload ->> 'assignee_user_id', v_payload ->> 'user_id')
      for share;
      if not found
         or v_assignee.status <> '啟用'
         or lower(btrim(coalesce(v_assignee.account_source, ''))) <> 'finance'
         or nullif(btrim(coalesce(v_assignee.company_id, '')), '') is null
         or nullif(btrim(coalesce(v_assignee.finance_tenant_id, '')), '') is null
         or v_assignee.company_id <> v_actor.company_id
         or v_assignee.finance_tenant_id <> v_actor.finance_tenant_id
         or nullif(btrim(coalesce(v_assignee.unit, '')), '') is null then
        raise exception using message = 'inbound_assignee_scope_forbidden', errcode = '42501';
      end if;
      update public.inbound_documents
      set recipient_department_id = v_assignee.unit,
          recipient_department_name = v_assignee.unit,
          assignee_user_id = v_assignee.id,
          assignee_name = v_assignee.name,
          due_at = coalesce(v_payload ->> 'due_at', due_at),
          status = 'assigned',
          mutation_version = mutation_version + 1,
          updated_at = v_now
      where id = v_document_id
        and mutation_version = v_current_version
      returning * into v_document;
    elsif v_mutation = 'exception' then
      if nullif(btrim(coalesce(v_payload ->> 'exception_type', v_payload ->> 'exceptionType')), '') is null
         or nullif(btrim(coalesce(v_payload ->> 'note', v_payload ->> 'comment')), '') is null then
        raise exception using message = 'inbound_exception_detail_required', errcode = '22023';
      end if;
      begin
        v_metadata := coalesce(nullif(btrim(coalesce(v_document.metadata_json, '')), '')::jsonb, '{}'::jsonb);
      exception when others then
        raise exception using message = 'inbound_metadata_invalid', errcode = '22023';
      end;
      v_metadata := jsonb_set(
        v_metadata,
        '{exception}',
        jsonb_build_object(
          'type', left(coalesce(v_payload ->> 'exception_type', v_payload ->> 'exceptionType'), 120),
          'note', left(coalesce(v_payload ->> 'note', v_payload ->> 'comment'), 1000),
          'reported_by', v_actor.id,
          'reported_at', to_char(v_now, 'YYYY-MM-DD HH24:MI:SS')
        ),
        true
      );
      update public.inbound_documents
      set status = 'exception',
          metadata_json = v_metadata::text,
          mutation_version = mutation_version + 1,
          updated_at = v_now
      where id = v_document_id
        and mutation_version = v_current_version
      returning * into v_document;
    else
      update public.inbound_documents
      set status = 'closed',
          closed_at = v_now,
          mutation_version = mutation_version + 1,
          updated_at = v_now
      where id = v_document_id
        and mutation_version = v_current_version
      returning * into v_document;
    end if;
    if not found then
      raise exception using message = 'inbound_version_conflict', errcode = 'PT409';
    end if;
  end if;

  v_action := case v_mutation
    when 'draft' then 'save_inbound_draft'
    when 'register' then 'register_inbound_document'
    when 'assign' then 'assign_inbound_document'
    when 'exception' then 'report_inbound_exception'
    else 'close_inbound_document'
  end;
  v_event_type := case v_mutation
    when 'draft' then 'draft'
    when 'register' then 'submit'
    when 'assign' then 'assign'
    when 'exception' then 'exception'
    else 'approve'
  end;

  insert into public.audit_logs (
    id, actor, action, target_type, target_id, detail, event_type, severity,
    result, module_code, resource_type, resource_id, data_scope,
    actor_user_id, actor_email, actor_roles_json, request_id, metadata_json,
    created_at
  ) values (
    'AUD-INB-' || upper(encode(gen_random_bytes(10), 'hex')),
    v_actor.name,
    v_action,
    'inbound_documents',
    v_document.id,
    'version=' || v_document.mutation_version::text,
    v_event_type,
    'info',
    'success',
    'official_documents',
    'inbound_documents',
    v_document.id,
    'company',
    v_actor.id,
    v_actor.email,
    jsonb_build_array(v_actor.role)::text,
    p_idempotency_key,
    jsonb_build_object(
      'mutation', v_mutation,
      'version', v_document.mutation_version,
      'company_id', v_document.company_id,
      'finance_tenant_id', v_document.finance_tenant_id
    )::text,
    to_char(v_now, 'YYYY-MM-DD HH24:MI:SS')
  );

  v_response := jsonb_build_object(
    'ok', true,
    'mutation', v_mutation,
    'replayed', false,
    'version', v_document.mutation_version,
    'item', to_jsonb(v_document),
    'item_sha256', encode(digest(to_jsonb(v_document)::text, 'sha256'), 'hex'),
    'ledger_hash_verified', true
  );
  v_ledger_response := jsonb_build_object(
    'ok', true,
    'mutation', v_mutation,
    'replayed', false,
    'version', v_document.mutation_version,
    'item', jsonb_build_object(
      'id', v_document.id,
      'company_id', v_document.company_id,
      'finance_tenant_id', v_document.finance_tenant_id,
      'mutation_version', v_document.mutation_version
    ),
    'item_sha256', v_response ->> 'item_sha256'
  );
  insert into public.inbound_document_mutations (
    idempotency_key, inbound_document_id, company_id, finance_tenant_id,
    actor_user_id, mutation_type, request_sha256, response_json
  ) values (
    p_idempotency_key, v_document.id, v_document.company_id,
    v_document.finance_tenant_id, v_actor.id, v_mutation,
    p_request_sha256, v_ledger_response::text
  );
  return v_response;
end;
$$;

revoke all on function public.edoc_mutate_inbound_document_v1(
  text, text, text, text, text, bigint, jsonb
) from public, anon, authenticated;
grant execute on function public.edoc_mutate_inbound_document_v1(
  text, text, text, text, text, bigint, jsonb
) to service_role;

notify pgrst, 'reload schema';

commit;
