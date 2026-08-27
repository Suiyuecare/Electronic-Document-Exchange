-- Fresh local bootstrap smoke. This file contains no business/demo data. Its
-- audit writes are enclosed in a transaction that is always rolled back. It is
-- intended for CI after `db reset`.

begin;

-- Exercise effective privileges, not only catalog rows. PostgreSQL otherwise
-- gives every future function PUBLIC EXECUTE through its global default ACL.
-- This probe is transaction-local because the file always rolls back.
create function public.edoc_ci_default_acl_probe()
returns integer
language sql
stable
as $default_acl_probe$
  select 1
$default_acl_probe$;

do $$
declare
  v_count integer;
  v_message text;
  v_transition_commitment text;
  v_first_previous_hash text;
  v_first_hash text;
  v_head_before_replay text;
  v_head_after_replay text;
  v_second_previous_hash text;
  v_second_hash text;
  v_rpc_search_path text;
  v_dispatch_result jsonb;
  v_dispatch_replay jsonb;
  v_dispatch_record_id text;
  v_event_sequences bigint[];
  v_event_types text[];
  v_changed_fields text[];
begin
  if pg_catalog.to_regclass('public.official_document_editor_revisions') is null
     or pg_catalog.to_regclass('public.official_document_editor_assets') is null
     or pg_catalog.to_regclass('public.official_document_stamp_positions') is null then
    raise exception 'fresh_bootstrap_runtime_table_missing';
  end if;

  if exists (
    select 1
    from public.finance_organization_projection_state
    where finance_tenant_id = '__edoc_fresh_bootstrap_only__'
  ) then
    raise exception 'fresh_bootstrap_finance_sentinel_present';
  end if;

  if exists (
    select 1
    from information_schema.table_privileges
    where table_schema = 'public'
      and grantee in ('PUBLIC', 'anon', 'authenticated')
  ) or exists (
    select 1
    from information_schema.usage_privileges
    where object_schema = 'public'
      and object_type = 'SEQUENCE'
      and grantee in ('PUBLIC', 'anon', 'authenticated')
  ) or exists (
    select 1
    from information_schema.routine_privileges
    where routine_schema = 'public'
      and grantee in ('PUBLIC', 'anon', 'authenticated')
  ) or exists (
    select 1
    from pg_catalog.pg_policies
    where schemaname = 'public'
      and roles && array['public', 'anon', 'authenticated']::name[]
  ) or exists (
    select 1
    from pg_catalog.pg_default_acl default_acl
    join pg_catalog.pg_roles owner_role
      on owner_role.oid = default_acl.defaclrole
    join pg_catalog.pg_namespace namespace_row
      on namespace_row.oid = default_acl.defaclnamespace
    cross join lateral pg_catalog.aclexplode(default_acl.defaclacl) privilege_row
    where owner_role.rolname = 'postgres'
      and namespace_row.nspname = 'public'
      and (
        privilege_row.grantee = 0
        or pg_catalog.pg_get_userbyid(privilege_row.grantee)
          in ('anon', 'authenticated', 'service_role')
      )
  ) or exists (
    select 1
    from pg_catalog.aclexplode(
      coalesce(
        (
          select default_acl.defaclacl
          from pg_catalog.pg_default_acl default_acl
          where default_acl.defaclrole = 'postgres'::regrole
            and default_acl.defaclnamespace = 0
            and default_acl.defaclobjtype = 'f'
        ),
        pg_catalog.acldefault('f', 'postgres'::regrole)
      )
    ) privilege_row
    where privilege_row.grantee = 0
       or pg_catalog.pg_get_userbyid(privilege_row.grantee)
         in ('anon', 'authenticated', 'service_role')
  ) then
    raise exception 'fresh_bootstrap_browser_data_api_exposed';
  end if;

  if pg_catalog.has_function_privilege(
       'anon',
       'public.edoc_ci_default_acl_probe()',
       'EXECUTE'
     )
     or pg_catalog.has_function_privilege(
       'authenticated',
       'public.edoc_ci_default_acl_probe()',
       'EXECUTE'
     )
     or pg_catalog.has_function_privilege(
       'service_role',
       'public.edoc_ci_default_acl_probe()',
       'EXECUTE'
     ) then
    raise exception 'fresh_bootstrap_future_function_default_exposed';
  end if;

  select count(*) into v_count
  from information_schema.columns
  where table_schema = 'public'
    and (table_name, column_name) in (
      ('official_documents', 'requires_stamp'),
      ('official_documents', 'correction_missing_items_json'),
      ('official_document_files', 'stamp_request_id'),
      ('official_document_approval_steps', 'workflow_generation'),
      ('official_document_approval_steps', 'decision_evidence_json'),
      ('official_document_approval_logs', 'principal_actor_id'),
      ('official_document_stamp_requests', 'locked_editor_revision_id'),
      ('official_document_stamp_requests', 'prepared_file_id'),
      ('official_document_stamp_requests', 'claim_expires_at')
    );
  if v_count <> 9 then
    raise exception 'fresh_bootstrap_runtime_column_missing:%', v_count;
  end if;

  if pg_catalog.to_regprocedure('public.edoc_commit_official_document_submission(jsonb)') is null
     or pg_catalog.to_regprocedure('public.edoc_finalize_editor_asset_v2(jsonb)') is null
     or pg_catalog.to_regprocedure('public.edoc_resolve_portal_finance_user(uuid,text)') is null then
    raise exception 'fresh_bootstrap_runtime_rpc_missing';
  end if;

  if pg_catalog.to_regprocedure('extensions.digest(bytea,text)') is null
     or pg_catalog.to_regprocedure('extensions.gen_random_bytes(integer)') is null then
    raise exception 'fresh_bootstrap_pgcrypto_runtime_missing';
  end if;

  if pg_catalog.to_regclass('edoc_private.audit_log_chain_heads') is null
     or pg_catalog.to_regclass('edoc_private.audit_log_chain_transitions') is null
     or not exists (
       select 1
       from pg_catalog.pg_class relation_row
       join pg_catalog.pg_namespace namespace_row
         on namespace_row.oid = relation_row.relnamespace
       where namespace_row.nspname = 'edoc_private'
         and relation_row.relname in (
           'audit_log_chain_heads',
           'audit_log_chain_transitions'
         )
         and relation_row.relrowsecurity
         and relation_row.relforcerowsecurity
       group by namespace_row.nspname
       having pg_catalog.count(*) = 2
     ) then
    raise exception 'fresh_bootstrap_audit_chain_state_not_forced_rls';
  end if;

  if 2 <> (
    select pg_catalog.count(*)
    from pg_catalog.pg_trigger trigger_row
    where trigger_row.tgrelid =
      'edoc_private.audit_log_chain_transitions'::pg_catalog.regclass
      and trigger_row.tgname in (
        'trg_audit_log_chain_transitions_no_mutation',
        'trg_audit_log_chain_transitions_no_truncate'
      )
      and trigger_row.tgenabled = 'O'
      and not trigger_row.tgisinternal
  ) then
    raise exception 'fresh_bootstrap_audit_transition_not_immutable';
  end if;

  select transition_row.source_commitment
    into strict v_transition_commitment
  from edoc_private.audit_log_chain_transitions transition_row
  where transition_row.target_chain_version = 2
    and transition_row.source_chain_version = 1
    and transition_row.commitment_algorithm =
      'sha256-sorted-entry-hash-set-v1-c-collation'
    and transition_row.source_row_count = (
      select pg_catalog.count(*)
      from public.audit_logs
      where chain_version = 1
    )
    and transition_row.source_row_count = 7
    and transition_row.source_root_count = 1
    and transition_row.source_root_count = (
      select pg_catalog.count(*)
      from public.audit_logs
      where chain_version = 1
        and (previous_hash is null or previous_hash = 'GENESIS')
    )
    and transition_row.source_terminal_count = (
      select pg_catalog.count(*)
      from public.audit_logs terminal
      where terminal.chain_version = 1
        and not exists (
          select 1
          from public.audit_logs child
          where child.chain_version = 1
            and child.previous_hash = terminal.entry_hash
        )
    )
    and transition_row.source_fork_count = (
      select pg_catalog.count(*)
      from (
        select previous_hash
        from public.audit_logs
        where chain_version = 1
          and previous_hash is not null
          and previous_hash <> 'GENESIS'
        group by previous_hash
        having pg_catalog.count(*) > 1
      ) forked
    )
    and transition_row.source_commitment = (
      select pg_catalog.encode(
        extensions.digest(
          pg_catalog.convert_to(
            pg_catalog.concat_ws(
              '|',
              'EDOC-AUDIT-V1-SET-COMMITMENT-V1',
              pg_catalog.count(*)::text,
              coalesce(
                pg_catalog.string_agg(
                  entry_hash collate "C",
                  '|' order by entry_hash collate "C"
                ),
                ''
              )
            ),
            'UTF8'
          ),
          'sha256'
        ),
        'hex'
      )
      from public.audit_logs
      where chain_version = 1
    );

  if exists (
    select 1
    from public.audit_logs
    where chain_version is distinct from 1
      and chain_version is distinct from 2
  ) or exists (
    select 1
    from public.audit_logs
    where immutable is distinct from true
  ) then
    raise exception 'fresh_bootstrap_audit_version_or_immutability_invalid';
  end if;

  if pg_catalog.has_table_privilege(
       'service_role',
       'edoc_private.audit_log_chain_transitions',
       'SELECT'
     )
     or pg_catalog.has_table_privilege(
       'service_role',
       'edoc_private.audit_log_chain_transitions',
       'INSERT'
     )
     or pg_catalog.has_table_privilege(
       'service_role',
       'edoc_private.audit_log_chain_transitions',
       'UPDATE'
     )
     or pg_catalog.has_table_privilege(
       'service_role',
       'edoc_private.audit_log_chain_transitions',
       'DELETE'
     )
     or pg_catalog.has_table_privilege(
       'service_role',
       'edoc_private.audit_log_chain_transitions',
       'TRUNCATE'
     ) then
    raise exception 'fresh_bootstrap_audit_transition_service_accessible';
  end if;

  begin
    update edoc_private.audit_log_chain_transitions
    set source_row_count = source_row_count
    where target_chain_version = 2;
    raise exception 'fresh_bootstrap_audit_transition_update_accepted';
  exception
    when sqlstate '55000' then
      get stacked diagnostics v_message = message_text;
      if v_message <> 'audit_log_chain_transitions_immutable' then
        raise exception 'fresh_bootstrap_audit_transition_update_wrong_error:%',
          v_message;
      end if;
  end;

  begin
    delete from edoc_private.audit_log_chain_transitions
    where target_chain_version = 2;
    raise exception 'fresh_bootstrap_audit_transition_delete_accepted';
  exception
    when sqlstate '55000' then
      get stacked diagnostics v_message = message_text;
      if v_message <> 'audit_log_chain_transitions_immutable' then
        raise exception 'fresh_bootstrap_audit_transition_delete_wrong_error:%',
          v_message;
      end if;
  end;

  begin
    truncate table edoc_private.audit_log_chain_transitions;
    raise exception 'fresh_bootstrap_audit_transition_truncate_accepted';
  exception
    when sqlstate '55000' then
      get stacked diagnostics v_message = message_text;
      if v_message <> 'audit_log_chain_transitions_immutable' then
        raise exception 'fresh_bootstrap_audit_transition_truncate_wrong_error:%',
          v_message;
      end if;
  end;

  if not exists (
    select 1
    from edoc_private.audit_log_chain_heads chain_head
    where chain_head.chain_version = 2
      and chain_head.head_hash = v_transition_commitment
      and chain_head.last_audit_id is null
  ) then
    raise exception 'fresh_bootstrap_audit_transition_head_invalid';
  end if;

  if pg_catalog.has_table_privilege('authenticated', 'public.audit_log_chain_check', 'SELECT')
     or not pg_catalog.has_table_privilege('service_role', 'public.audit_log_chain_check', 'SELECT') then
    raise exception 'fresh_bootstrap_audit_chain_view_grant_invalid';
  end if;

  select pg_catalog.array_to_string(procedure_row.proconfig, ',')
    into v_rpc_search_path
  from pg_catalog.pg_proc procedure_row
  where procedure_row.oid = 'public.edoc_mutate_inbound_document_v1(text,text,text,text,text,bigint,jsonb)'::pg_catalog.regprocedure;

  if v_rpc_search_path is null
     or v_rpc_search_path not like '%pg_catalog%'
     or v_rpc_search_path not like '%extensions%'
     or v_rpc_search_path like '%public%' then
    raise exception 'fresh_bootstrap_inbound_rpc_search_path_invalid:%', v_rpc_search_path;
  end if;

  select count(*) into v_count
  from public.documents
  where id in (
    'DOC-IN-1140522-00018',
    'DOC-OUT-1140522-007',
    'DOC-OUT-1140519-006',
    'DOC-ADMIN-1140523-001'
  );
  if v_count <> 0 then
    raise exception 'fresh_bootstrap_demo_document_present:%', v_count;
  end if;

  select count(*) into v_count
  from public.users
  where id in (
    'USR-001',
    'USR-002',
    'USR-003',
    'USR-004',
    'USR-005',
    'USR-006',
    'USR-007'
  );
  if v_count <> 0 then
    raise exception 'fresh_bootstrap_demo_account_present:%', v_count;
  end if;

  if not pg_catalog.has_function_privilege(
       'service_role',
       'public.edoc_commit_official_document_submission(jsonb)',
       'EXECUTE'
     )
     or pg_catalog.has_function_privilege(
       'anon',
       'public.edoc_commit_official_document_submission(jsonb)',
       'EXECUTE'
     )
     or pg_catalog.has_function_privilege(
       'authenticated',
       'public.edoc_commit_official_document_submission(jsonb)',
       'EXECUTE'
     ) then
    raise exception 'fresh_bootstrap_atomic_rpc_grant_invalid';
  end if;

  -- Non-mutating successful RPC smoke: no matching Finance user means no row.
  select count(*) into v_count
  from public.edoc_resolve_portal_finance_user(
    '00000000-0000-0000-0000-000000000001'::uuid,
    'ci-fresh-bootstrap-missing@example.invalid'
  );
  if v_count <> 0 then
    raise exception 'fresh_bootstrap_identity_rpc_unexpected_row';
  end if;

  -- Exercise both atomic RPC bodies with deliberately invalid payloads. The
  -- exact validation errors prove the functions compile against the final row
  -- types while guaranteeing no document or file row is created.
  begin
    perform public.edoc_commit_official_document_submission('{}'::jsonb);
    raise exception 'fresh_bootstrap_submit_rpc_accepted_invalid_payload';
  exception
    when sqlstate '22023' then
      get stacked diagnostics v_message = message_text;
      if v_message <> 'official_submission_invalid_payload' then
        raise exception 'fresh_bootstrap_submit_rpc_wrong_error:%', v_message;
      end if;
  end;

  begin
    perform public.edoc_finalize_editor_asset_v2('{}'::jsonb);
    raise exception 'fresh_bootstrap_editor_rpc_accepted_invalid_payload';
  exception
    when sqlstate '22023' then
      get stacked diagnostics v_message = message_text;
      if v_message <> 'editor_finalize_invalid_payload' then
        raise exception 'fresh_bootstrap_editor_rpc_wrong_error:%', v_message;
      end if;
  end;

  -- Exercise database-owned dispatch evidence through the same RPCs used by
  -- the backend.  Every synthetic row is rolled back with this transaction.
  insert into public.companies (id, name, status)
  values (
    '__edoc_dispatch_event_smoke_company__',
    'Deidentified dispatch event smoke company',
    'inactive'
  );

  insert into public.users (
    id, name, email, role, status, company_id
  ) values (
    '__edoc_dispatch_event_smoke_user__',
    'Dispatch event smoke user',
    'dispatch-event-smoke@example.invalid',
    'employee',
    '啟用',
    '__edoc_dispatch_event_smoke_company__'
  );

  insert into public.official_documents (
    id,
    company_id,
    document_type,
    source_type,
    title,
    recipient,
    applicant_id,
    applicant_name,
    current_status,
    current_step,
    dispatch_method
  ) values (
    '__edoc_dispatch_event_smoke_document__',
    '__edoc_dispatch_event_smoke_company__',
    'official_document',
    'blank_editor',
    'Deidentified dispatch event smoke document',
    'Deidentified recipient',
    '__edoc_dispatch_event_smoke_user__',
    'Dispatch event smoke user',
    'returned_to_applicant_for_send',
    'applicant_dispatch',
    'return_to_applicant_for_manual_send'
  );

  v_dispatch_result := public.edoc_create_official_document_dispatch_record(
    '__edoc_dispatch_event_smoke_document__',
    '__edoc_dispatch_event_smoke_user__'
  );
  v_dispatch_record_id := v_dispatch_result->>'dispatch_record_id';

  if v_dispatch_result->>'created' <> 'true'
     or nullif(v_dispatch_record_id, '') is null
     or 1 <> (
       select pg_catalog.count(*)
       from public.official_document_dispatch_events as event
       where event.dispatch_record_id = v_dispatch_record_id
     )
     or not exists (
       select 1
       from public.official_document_dispatch_events as event
       where event.dispatch_record_id = v_dispatch_record_id
         and event.event_sequence = 1
         and event.event_type = 'created'
         and event.from_status is null
         and event.to_status = 'pending'
         and event.changed_fields @> array['dispatch_status']::text[]
         and event.record_snapshot_sha256 ~ '^[0-9a-f]{64}$'
         and nullif(event.database_actor, '') is not null
     ) then
    raise exception 'fresh_bootstrap_dispatch_created_event_invalid';
  end if;

  v_dispatch_replay := public.edoc_create_official_document_dispatch_record(
    '__edoc_dispatch_event_smoke_document__',
    '__edoc_dispatch_event_smoke_user__'
  );
  if v_dispatch_replay->>'created' <> 'false'
     or 1 <> (
       select pg_catalog.count(*)
       from public.official_document_dispatch_events as event
       where event.dispatch_record_id = v_dispatch_record_id
     ) then
    raise exception 'fresh_bootstrap_dispatch_create_replay_duplicated_event';
  end if;

  begin
    update public.official_document_dispatch_records
       set created_by = '__edoc_dispatch_identity_tamper__'
     where id = v_dispatch_record_id;
    raise exception 'fresh_bootstrap_dispatch_identity_mutation_accepted';
  exception
    when sqlstate '42501' then
      get stacked diagnostics v_message = message_text;
      if v_message <> 'official_dispatch_identity_immutable' then
        raise exception 'fresh_bootstrap_dispatch_identity_mutation_wrong_error:%',
          v_message;
      end if;
  end;

  if 1 <> (
    select pg_catalog.count(*)
    from public.official_document_dispatch_events as event
    where event.dispatch_record_id = v_dispatch_record_id
  ) or not exists (
    select 1
    from public.official_document_dispatch_records as record
    where record.id = v_dispatch_record_id
      and record.created_by = '__edoc_dispatch_event_smoke_user__'
  ) then
    raise exception 'fresh_bootstrap_dispatch_identity_mutation_left_state';
  end if;

  insert into public.file_objects (
    id,
    document_id,
    file_name,
    storage_key,
    mime_type,
    size_bytes,
    sha256,
    version_label,
    purpose,
    created_by,
    scan_status
  ) values (
    '__edoc_dispatch_event_smoke_file__',
    '__edoc_dispatch_event_smoke_document__',
    'dispatch-proof.pdf',
    'verification/dispatch-event-smoke/dispatch-proof.pdf',
    'application/pdf',
    1,
    pg_catalog.repeat('a', 64),
    'verification',
    'dispatch-proof',
    '__edoc_dispatch_event_smoke_user__',
    'passed'
  );

  insert into public.official_document_files (
    id,
    document_id,
    file_object_id,
    file_type,
    file_name,
    file_storage_key,
    file_mime_type,
    file_size,
    file_hash,
    uploaded_by
  ) values (
    '__edoc_dispatch_event_smoke_official_file__',
    '__edoc_dispatch_event_smoke_document__',
    '__edoc_dispatch_event_smoke_file__',
    'dispatch_proof',
    'dispatch-proof.pdf',
    'verification/dispatch-event-smoke/dispatch-proof.pdf',
    'application/pdf',
    1,
    pg_catalog.repeat('a', 64),
    '__edoc_dispatch_event_smoke_user__'
  );

  update public.official_document_dispatch_records
     set proof_file_id = '__edoc_dispatch_event_smoke_official_file__',
         recipient = 'Deidentified updated recipient',
         updated_at = '2099-01-01 00:00:01'
   where id = v_dispatch_record_id;

  select event.changed_fields
    into v_changed_fields
    from public.official_document_dispatch_events as event
   where event.dispatch_record_id = v_dispatch_record_id
     and event.event_sequence = 2;
  if v_changed_fields is distinct from array['recipient', 'proof_file_id']::text[]
     or not exists (
       select 1
       from public.official_document_dispatch_events as event
       where event.dispatch_record_id = v_dispatch_record_id
         and event.event_sequence = 2
         and event.event_type = 'metadata_updated'
         and event.from_status = 'pending'
         and event.to_status = 'pending'
     ) then
    raise exception 'fresh_bootstrap_dispatch_metadata_event_invalid:%',
      v_changed_fields;
  end if;

  v_dispatch_result := public.edoc_complete_official_document_dispatch(
    '__edoc_dispatch_event_smoke_document__',
    v_dispatch_record_id,
    '__edoc_dispatch_event_smoke_user__',
    null,
    '2099-01-02',
    null,
    'dispatch-event-smoke@example.invalid',
    'Deidentified dispatch event verification',
    '127.0.0.1',
    'fresh-bootstrap-smoke'
  );

  if v_dispatch_result->>'completed' <> 'true'
     or not exists (
       select 1
       from public.official_document_dispatch_events as event
       where event.dispatch_record_id = v_dispatch_record_id
         and event.event_sequence = 3
         and event.event_type = 'status_transition'
         and event.from_status = 'pending'
         and event.to_status = 'sent_by_applicant'
         and event.changed_fields @> array[
           'dispatch_status', 'dispatch_date', 'completed_at'
         ]::text[]
     ) then
    raise exception 'fresh_bootstrap_dispatch_completion_event_invalid';
  end if;

  v_dispatch_replay := public.edoc_complete_official_document_dispatch(
    '__edoc_dispatch_event_smoke_document__',
    v_dispatch_record_id,
    '__edoc_dispatch_event_smoke_user__',
    null,
    '2099-01-02',
    null,
    'dispatch-event-smoke@example.invalid',
    'Deidentified dispatch event verification',
    '127.0.0.1',
    'fresh-bootstrap-smoke'
  );

  update public.official_document_dispatch_records
     set updated_at = updated_at
   where id = v_dispatch_record_id;

  select
    pg_catalog.array_agg(event.event_sequence order by event.event_sequence),
    pg_catalog.array_agg(event.event_type order by event.event_sequence)
    into v_event_sequences, v_event_types
    from public.official_document_dispatch_events as event
   where event.dispatch_record_id = v_dispatch_record_id;

  if v_dispatch_replay->>'completed' <> 'false'
     or v_dispatch_replay->>'reason' <> 'official_dispatch_already_completed'
     or v_event_sequences is distinct from array[1, 2, 3]::bigint[]
     or v_event_types is distinct from array[
       'created', 'metadata_updated', 'status_transition'
     ]::text[] then
    raise exception 'fresh_bootstrap_dispatch_replay_or_sequence_invalid:%:%',
      v_event_sequences, v_event_types;
  end if;

  begin
    update public.official_document_dispatch_events
       set event_type = event_type
     where dispatch_record_id = v_dispatch_record_id
       and event_sequence = 1;
    raise exception 'fresh_bootstrap_dispatch_event_update_accepted';
  exception
    when sqlstate '42501' then
      get stacked diagnostics v_message = message_text;
      if v_message <> 'immutable_record_log' then
        raise exception 'fresh_bootstrap_dispatch_event_update_wrong_error:%',
          v_message;
      end if;
  end;

  begin
    delete from public.official_document_dispatch_events
     where dispatch_record_id = v_dispatch_record_id
       and event_sequence = 1;
    raise exception 'fresh_bootstrap_dispatch_event_delete_accepted';
  exception
    when sqlstate '42501' then
      get stacked diagnostics v_message = message_text;
      if v_message <> 'immutable_record_log' then
        raise exception 'fresh_bootstrap_dispatch_event_delete_wrong_error:%',
          v_message;
      end if;
  end;

  -- Prove the v2 trigger links sequential rows and that a duplicate ID with
  -- ON CONFLICT DO NOTHING cannot advance the singleton head.
  insert into public.audit_logs (
    id, actor, action, target_type, target_id, detail, created_at
  ) values (
    'AUD-CI-FRESH-CHAIN-001', 'ci', 'fresh bootstrap chain smoke',
    'verification', 'fresh-bootstrap', 'deidentified smoke row',
    '2099-01-01 00:00:00'
  );

  select previous_hash, entry_hash
    into v_first_previous_hash, v_first_hash
  from public.audit_logs
  where id = 'AUD-CI-FRESH-CHAIN-001' and chain_version = 2;

  select head_hash into v_head_before_replay
  from edoc_private.audit_log_chain_heads
  where chain_version = 2;

  insert into public.audit_logs (
    id, actor, action, target_type, target_id, detail, created_at
  ) values (
    'AUD-CI-FRESH-CHAIN-001', 'ci', 'duplicate replay',
    'verification', 'fresh-bootstrap', 'must not advance head',
    '2099-01-01 00:00:00'
  ) on conflict (id) do nothing;

  select head_hash into v_head_after_replay
  from edoc_private.audit_log_chain_heads
  where chain_version = 2;

  if v_first_previous_hash is distinct from v_transition_commitment
     or v_first_hash is null
     or v_head_before_replay is distinct from v_first_hash
     or v_head_after_replay is distinct from v_head_before_replay then
    raise exception 'fresh_bootstrap_audit_duplicate_advanced_head';
  end if;

  insert into public.audit_logs (
    id, actor, action, target_type, target_id, detail, created_at
  ) values (
    'AUD-CI-FRESH-CHAIN-002', 'ci', 'fresh bootstrap chain smoke',
    'verification', 'fresh-bootstrap', 'deidentified smoke row',
    '2099-01-01 00:00:00'
  );

  select previous_hash, entry_hash
    into v_second_previous_hash, v_second_hash
  from public.audit_logs
  where id = 'AUD-CI-FRESH-CHAIN-002' and chain_version = 2;

  if v_second_previous_hash is distinct from v_first_hash
     or v_second_hash is null
     or not exists (
       select 1
       from edoc_private.audit_log_chain_heads
       where chain_version = 2
         and head_hash = v_second_hash
         and last_audit_id = 'AUD-CI-FRESH-CHAIN-002'
     ) then
    raise exception 'fresh_bootstrap_audit_chain_link_invalid';
  end if;
end
$$;

rollback;

select 'fresh_bootstrap_smoke_ok' as result;
