-- Incomplete cloud snapshots are private to their applicant and company.
create table if not exists public.official_document_compose_drafts (
  id text primary key,
  company_id text not null references public.companies(id),
  applicant_id text not null references public.users(id),
  revision integer not null default 1 check (revision > 0),
  snapshot_json jsonb not null check (jsonb_typeof(snapshot_json) = 'object'),
  snapshot_hash text not null,
  archived boolean not null default false,
  created_at text not null,
  updated_at text not null
);
create index if not exists idx_compose_draft_owner on public.official_document_compose_drafts(applicant_id, company_id, archived, updated_at desc);
alter table public.official_document_compose_drafts enable row level security;
revoke all on public.official_document_compose_drafts from public, anon, authenticated;
grant select, insert, update, delete on public.official_document_compose_drafts to service_role;

create or replace function public.edoc_save_compose_draft(
  p_id text, p_applicant_id text, p_company_id text, p_expected_revision integer,
  p_snapshot jsonb, p_hash text, p_archived boolean default false
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  v_row public.official_document_compose_drafts%rowtype;
  v_time text := pg_catalog.to_char(pg_catalog.clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS.US');
begin
  if p_expected_revision < 0 or p_expected_revision is null or pg_catalog.jsonb_typeof(p_snapshot) <> 'object'
     or pg_catalog.octet_length(p_snapshot::text) > 250000
     or p_snapshot->>'userId' is distinct from p_applicant_id
     or p_snapshot->>'companyId' is distinct from p_company_id then
    raise exception using errcode = '22023', message = 'compose_draft_snapshot_invalid';
  end if;
  if not exists(select 1 from public.users where id=p_applicant_id and company_id=p_company_id) then
    raise exception using errcode = '42501', message = 'compose_draft_scope_forbidden';
  end if;
  if p_expected_revision = 0 then
    insert into public.official_document_compose_drafts values(p_id, p_company_id, p_applicant_id, 1, p_snapshot, p_hash, p_archived, v_time, v_time)
    on conflict(id) do nothing;
  end if;
  select * into v_row from public.official_document_compose_drafts where id=p_id for update;
  if not found then
    raise exception using errcode = 'PT409', message = 'compose_draft_revision_conflict';
  end if;
  if v_row.applicant_id is distinct from p_applicant_id or v_row.company_id is distinct from p_company_id then
    raise exception using errcode = '42501', message = 'compose_draft_scope_forbidden';
  end if;
  if v_row.snapshot_hash = p_hash and v_row.snapshot_json = p_snapshot and v_row.archived = p_archived then
    return pg_catalog.to_jsonb(v_row);
  end if;
  if v_row.revision <> p_expected_revision then
    raise exception using errcode = 'PT409', message = 'compose_draft_revision_conflict';
  end if;
  update public.official_document_compose_drafts set snapshot_json=p_snapshot, snapshot_hash=p_hash,
    revision=revision+1, archived=p_archived, updated_at=v_time where id=p_id returning * into v_row;
  return pg_catalog.to_jsonb(v_row);
end $$;
revoke all on function public.edoc_save_compose_draft(text,text,text,integer,jsonb,text,boolean) from public, anon, authenticated;
grant execute on function public.edoc_save_compose_draft(text,text,text,integer,jsonb,text,boolean) to service_role;

alter table public.official_documents add column if not exists content_revision integer not null default 0;
-- Extend the existing atomic correction RPC, preserving its actor, state, file,
-- number, stamp and audit transaction. The version check runs under its row lock.
do $migration$
declare
  v_proc regprocedure := 'public.edoc_apply_official_document_correction(text,text,text,jsonb,text,jsonb,jsonb,text,jsonb,jsonb,text,text,text,text,text,text,jsonb,text,text)'::regprocedure;
  v_sql text;
  v_old text;
begin
  v_sql := pg_catalog.pg_get_functiondef(v_proc);
  v_old := '''workflow_template_key'', ''metadata_json''';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_revision_allowed_keys_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old, '''workflow_template_key'', ''metadata_json'', ''_expected_content_revision''');
  v_old := '  select actor.*';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_revision_lock_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old, $snippet$
  if p_patch ? '_expected_content_revision' and (p_patch->>'_expected_content_revision')::integer <> v_document.content_revision then
    raise exception using errcode = 'PT409', message = 'compose_content_revision_conflict';
  end if;
  select actor.*
$snippet$);
  v_old := '         workflow_template_key = p_patch->>''workflow_template_key'',';
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_revision_write_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old, '         content_revision = content_revision + 1,' || chr(10) || v_old);
  execute v_sql;
end $migration$;

do $migration$
declare
  v_sql text := pg_catalog.pg_get_functiondef('public.edoc_commit_official_document_submission(jsonb)'::regprocedure);
  v_old text := '  if v_document.updated_at is distinct from v_expected_updated_at then';
begin
  if pg_catalog.strpos(v_sql, v_old) = 0 then raise exception 'compose_submit_revision_lock_drift'; end if;
  v_sql := pg_catalog.replace(v_sql, v_old, $snippet$
  if p_request ? 'expected_content_revision' and (p_request->>'expected_content_revision')::integer <> v_document.content_revision then
    raise exception using errcode = 'PT409', message = 'compose_content_revision_conflict';
  end if;
  if v_document.updated_at is distinct from v_expected_updated_at then
$snippet$);
  execute v_sql;
end $migration$;
