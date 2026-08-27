-- Fresh local bootstrap smoke. This file contains no business/demo data. Its
-- audit writes are enclosed in a transaction that is always rolled back. It is
-- intended for CI after `db reset`.

begin;

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
    join pg_catalog.pg_namespace namespace_row
      on namespace_row.oid = default_acl.defaclnamespace
    cross join lateral pg_catalog.aclexplode(default_acl.defaclacl) privilege_row
    where namespace_row.nspname = 'public'
      and (
        privilege_row.grantee = 0
        or pg_catalog.pg_get_userbyid(privilege_row.grantee)
          in ('anon', 'authenticated', 'service_role')
      )
  ) then
    raise exception 'fresh_bootstrap_browser_data_api_exposed';
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
    where not immutable
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
