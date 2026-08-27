-- Business/optimistic-concurrency conflicts are terminal for the submitted
-- payload.  They must not use PostgreSQL's 40001 serialization_failure code:
-- PostgREST versions before 16 automatically retry that SQLSTATE and can keep
-- an RPC request open indefinitely.  PT409 is supported by PostgREST 11+ and
-- returns the intended HTTP 409 without changing genuine database-generated
-- serialization failure handling.  Caller-generated 23505 business conflicts
-- are normalized for the same reason; native unique-constraint violations are
-- not rewritten.
--
-- Read the effective definitions instead of duplicating several large RPCs.
-- The exact occurrence counts make this migration fail closed if an earlier
-- function definition drifts. CREATE OR REPLACE preserves owners and ACLs.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $business_conflict_retry_hardening$
declare
  v_target record;
  v_oid oid;
  v_definition text;
  v_occurrences integer;
  v_retry_code constant text := '''40001''';
  v_unique_code constant text := '''23505''';
  v_conflict_code constant text := '''PT409''';
begin
  for v_target in
    select *
    from (values
      ('public.edoc_mutate_inbound_document_v1(text,text,text,text,text,bigint,jsonb)', 7),
      ('public.edoc_claim_official_document_approval(text,text,text,text)', 1),
      ('public.edoc_claim_official_document_rejection(text,text,text,text)', 1),
      ('public.edoc_claim_official_document_approval_v2(text,text,text,text,text,jsonb)', 1),
      ('public.edoc_claim_official_document_rejection_v2(text,text,text,text,text,jsonb)', 2),
      ('public.edoc_revoke_official_workflow_delegation(text,text)', 1),
      ('public.edoc_complete_official_document_dispatch(text,text,text,text,text,text,text,text,text,text)', 2),
      ('public.edoc_claim_official_document_approval_v3(text,text,text,text,text,jsonb)', 1),
      ('public.edoc_commit_official_document_submission(jsonb)', 2),
      ('public.edoc_finalize_editor_asset_v2(jsonb)', 3)
    ) as target(signature, expected_occurrences)
  loop
    v_oid := pg_catalog.to_regprocedure(v_target.signature);
    if v_oid is null then
      raise exception using
        errcode = '55000',
        message = 'edoc_business_conflict_rpc_missing:' || v_target.signature;
    end if;

    v_definition := pg_catalog.pg_get_functiondef(v_oid);
    v_occurrences := (
      pg_catalog.length(v_definition)
      - pg_catalog.length(pg_catalog.replace(v_definition, v_retry_code, ''))
    ) / pg_catalog.length(v_retry_code);

    if v_occurrences <> v_target.expected_occurrences then
      raise exception using
        errcode = '55000',
        message = 'edoc_business_conflict_rpc_definition_drift:'
          || v_target.signature || ':' || v_occurrences::text;
    end if;

    execute pg_catalog.replace(v_definition, v_retry_code, v_conflict_code);

    v_definition := pg_catalog.pg_get_functiondef(v_oid);
    if pg_catalog.strpos(v_definition, v_retry_code) <> 0
       or pg_catalog.strpos(v_definition, v_conflict_code) = 0 then
      raise exception using
        errcode = '55000',
        message = 'edoc_business_conflict_rpc_rewrite_failed:' || v_target.signature;
    end if;
  end loop;

  for v_target in
    select *
    from (values
      ('public.edoc_apply_finance_organization_projection_v2(text,text,bigint,text,text,jsonb)', 2),
      ('public.edoc_create_official_document_dispatch_record(text,text)', 1),
      ('public.edoc_finalize_official_document_resubmit(text,text,text,timestamp with time zone,text,text,text,text,text)', 2),
      ('public.edoc_commit_official_document_submission(jsonb)', 2),
      ('public.edoc_finalize_editor_asset_v2(jsonb)', 5)
    ) as target(signature, expected_occurrences)
  loop
    v_oid := pg_catalog.to_regprocedure(v_target.signature);
    if v_oid is null then
      raise exception using
        errcode = '55000',
        message = 'edoc_business_conflict_rpc_missing:' || v_target.signature;
    end if;

    v_definition := pg_catalog.pg_get_functiondef(v_oid);
    v_occurrences := (
      pg_catalog.length(v_definition)
      - pg_catalog.length(pg_catalog.replace(v_definition, v_unique_code, ''))
    ) / pg_catalog.length(v_unique_code);

    if v_occurrences <> v_target.expected_occurrences then
      raise exception using
        errcode = '55000',
        message = 'edoc_business_conflict_unique_definition_drift:'
          || v_target.signature || ':' || v_occurrences::text;
    end if;

    execute pg_catalog.replace(v_definition, v_unique_code, v_conflict_code);

    v_definition := pg_catalog.pg_get_functiondef(v_oid);
    if pg_catalog.strpos(v_definition, v_unique_code) <> 0
       or pg_catalog.strpos(v_definition, v_conflict_code) = 0 then
      raise exception using
        errcode = '55000',
        message = 'edoc_business_conflict_unique_rewrite_failed:'
          || v_target.signature;
    end if;
  end loop;
end
$business_conflict_retry_hardening$;

notify pgrst, 'reload schema';

commit;
