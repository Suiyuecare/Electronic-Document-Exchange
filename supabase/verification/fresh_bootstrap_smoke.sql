-- Fresh local bootstrap smoke. This file contains no business/demo data and
-- performs no successful mutation. It is intended for CI after `db reset`.

do $$
declare
  v_count integer;
  v_message text;
begin
  if pg_catalog.to_regclass('public.official_document_editor_revisions') is null
     or pg_catalog.to_regclass('public.official_document_editor_assets') is null
     or pg_catalog.to_regclass('public.official_document_stamp_positions') is null then
    raise exception 'fresh_bootstrap_runtime_table_missing';
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
end
$$;

select 'fresh_bootstrap_smoke_ok' as result;
