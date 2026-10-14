-- Missing optional decision metadata must not become SQL NULL during a
-- whole-record INSERT. Pending steps have no decision yet: {} is the only
-- compatibility default. Explicit JSON null or non-object evidence is invalid.
-- Preserve the existing RPC's grants, security mode, locks, authorization,
-- revision/prepared-file checks, idempotency witnesses, and atomic transaction.
do $migration$
declare
  v_sql text := pg_catalog.pg_get_functiondef(
    'public.edoc_commit_official_document_submission(jsonb)'::regprocedure
  );
  v_guard_anchor text := E'  begin\n    v_workflow_generation := (p_request->>''workflow_generation'')::integer;';
  v_guard text := $guard$
  -- official_submission_step_evidence_defaults_v1
  -- Validate before the idempotent-return branch as well as before any write.
  if exists (
    select 1 from pg_catalog.jsonb_array_elements(p_request->'steps') as item(value)
    where pg_catalog.jsonb_typeof(item.value) is distinct from 'object'
       or (item.value ? 'decision_evidence_json'
           and pg_catalog.jsonb_typeof(item.value->'decision_evidence_json') is distinct from 'object')
  ) then
    raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
  end if;
$guard$;
  v_old text := '    insert into public.official_document_approval_steps select (v_step).*;';
  v_new text := $insert$    insert into public.official_document_approval_steps (
      id, document_id, workflow_generation, step_order, step_key, step_name,
      approver_user_id, approver_name, approver_role, status, comment,
      approved_at, decision_actor_user_id, decision_evidence_json,
      review_started_at, created_at, updated_at
    ) values (
      v_step.id, v_step.document_id, v_step.workflow_generation, v_step.step_order,
      v_step.step_key, v_step.step_name, v_step.approver_user_id,
      v_step.approver_name, v_step.approver_role, v_step.status, v_step.comment,
      v_step.approved_at, v_step.decision_actor_user_id,
      coalesce(v_step.decision_evidence_json, '{}'::jsonb),
      v_step.review_started_at, v_step.created_at, v_step.updated_at
    );$insert$;
begin
  if pg_catalog.strpos(v_sql, 'official_submission_step_evidence_defaults_v1') > 0 then
    -- Safe replay is allowed only for this exact replacement, not an unknown
    -- function that happens to carry the version marker.
    if pg_catalog.strpos(v_sql, v_guard) = 0
       or pg_catalog.strpos(v_sql, v_new) = 0
       or pg_catalog.strpos(v_sql, v_old) > 0 then
      raise exception 'official_submission_step_evidence_migration_drift';
    end if;
  else
    if (pg_catalog.length(v_sql) - pg_catalog.length(pg_catalog.replace(v_sql, v_guard_anchor, '')))
         <> pg_catalog.length(v_guard_anchor)
       or (pg_catalog.length(v_sql) - pg_catalog.length(pg_catalog.replace(v_sql, v_old, '')))
         <> pg_catalog.length(v_old) then
      raise exception 'official_submission_step_evidence_migration_drift';
    end if;
    v_sql := pg_catalog.replace(v_sql, v_guard_anchor, v_guard || v_guard_anchor);
    v_sql := pg_catalog.replace(v_sql, v_old, v_new);
    execute v_sql;
  end if;
end $migration$;

notify pgrst, 'reload schema';
