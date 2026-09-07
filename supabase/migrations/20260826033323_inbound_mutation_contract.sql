begin;

-- Some early deployments created the inbound tables directly before the
-- migration directory became authoritative.  Keep a clean install and those
-- existing projects on one contract without replacing any stored rows.
create table if not exists public.inbound_documents (
  id text primary key,
  company_id text,
  finance_tenant_id text,
  receive_no text not null unique,
  source_type text not null default 'manual',
  external_exchange_id text,
  sender_name text not null,
  sender_contact text,
  subject text not null,
  body text,
  recipient_department_id text,
  recipient_department_name text,
  assignee_user_id text,
  assignee_name text,
  due_at text,
  priority text not null default '普通件',
  security_level text not null default '普通',
  status text not null default 'registered',
  retention_until timestamptz not null default (now() + interval '10 years'),
  retention_policy_version text not null default 'EDOC-RETENTION-2026-10Y',
  legal_hold boolean not null default false,
  legal_hold_reason text,
  disposition_status text not null default 'retained',
  disposition_approved_by text,
  disposition_approved_at timestamptz,
  metadata_json text not null default '{}',
  mutation_version bigint not null default 1,
  created_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  closed_at timestamptz
);

alter table public.inbound_documents
  add column if not exists mutation_version bigint not null default 1,
  add column if not exists company_id text,
  add column if not exists finance_tenant_id text;

update public.inbound_documents inbound_row
set company_id = user_row.company_id,
    finance_tenant_id = user_row.finance_tenant_id
from public.users user_row
where inbound_row.created_by = user_row.id
  and (
    nullif(btrim(coalesce(inbound_row.company_id, '')), '') is null
    or nullif(btrim(coalesce(inbound_row.finance_tenant_id, '')), '') is null
  );

-- Legacy rows that cannot be tied back to one Finance tenant remain readable
-- only to database operators for remediation.  NOT VALID deliberately avoids
-- blessing or deleting them, while every new/updated row must be fully scoped.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.inbound_documents'::regclass
      and conname = 'inbound_documents_finance_scope_required'
  ) then
    alter table public.inbound_documents
      add constraint inbound_documents_finance_scope_required
      check (
        nullif(btrim(company_id), '') is not null
        and nullif(btrim(finance_tenant_id), '') is not null
      ) not valid;
  end if;
end
$$;

create table if not exists public.inbound_document_mutations (
  idempotency_key text primary key,
  inbound_document_id text not null references public.inbound_documents(id) on delete restrict,
  company_id text not null,
  finance_tenant_id text not null,
  actor_user_id text not null,
  mutation_type text not null,
  request_sha256 text not null,
  response_json text not null,
  created_at timestamptz not null default now(),
  constraint inbound_document_mutations_key_check
    check (idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$'),
  constraint inbound_document_mutations_type_check
    check (mutation_type in ('draft', 'register', 'assign', 'exception', 'close')),
  constraint inbound_document_mutations_hash_check
    check (request_sha256 ~ '^[0-9a-f]{64}$')
);

alter table public.inbound_document_mutations
  add column if not exists company_id text,
  add column if not exists finance_tenant_id text;

alter table public.inbound_document_mutations
  drop constraint if exists inbound_document_mutations_type_check;
alter table public.inbound_document_mutations
  add constraint inbound_document_mutations_type_check
  check (mutation_type in ('draft', 'register', 'assign', 'exception', 'close'));

update public.inbound_document_mutations mutation_row
set company_id = inbound_row.company_id,
    finance_tenant_id = inbound_row.finance_tenant_id
from public.inbound_documents inbound_row
where mutation_row.inbound_document_id = inbound_row.id
  and (
    nullif(btrim(coalesce(mutation_row.company_id, '')), '') is null
    or nullif(btrim(coalesce(mutation_row.finance_tenant_id, '')), '') is null
  );

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.inbound_document_mutations'::regclass
      and conname = 'inbound_document_mutations_finance_scope_required'
  ) then
    alter table public.inbound_document_mutations
      add constraint inbound_document_mutations_finance_scope_required
      check (
        nullif(btrim(company_id), '') is not null
        and nullif(btrim(finance_tenant_id), '') is not null
      ) not valid;
  end if;
end
$$;

create index if not exists inbound_documents_status_due_idx
  on public.inbound_documents (status, due_at);
create index if not exists inbound_documents_assignee_status_idx
  on public.inbound_documents (assignee_user_id, status);
create index if not exists inbound_document_mutations_document_created_idx
  on public.inbound_document_mutations (inbound_document_id, created_at);

alter table public.inbound_document_mutations enable row level security;
alter table public.inbound_document_mutations force row level security;
revoke all on public.inbound_document_mutations from public, anon, authenticated;
grant select on public.inbound_document_mutations to service_role;

drop policy if exists "service role reads inbound mutation ledger"
  on public.inbound_document_mutations;
create policy "service role reads inbound mutation ledger"
  on public.inbound_document_mutations
  for select to service_role
  using (true);

alter table public.inbound_documents enable row level security;
alter table public.inbound_documents force row level security;
revoke all on public.inbound_documents from public, anon, authenticated;
grant select, insert, update on public.inbound_documents to service_role;

drop policy if exists "service role manages inbound documents"
  on public.inbound_documents;
create policy "service role manages inbound documents"
  on public.inbound_documents
  for all to service_role
  using (true)
  with check (true);

-- One server-owned transaction performs the document CAS update, append-only
-- audit event and idempotency ledger insert.  The browser can never execute it:
-- the backend calls it with the service-role credential after validating the
-- eDoc session, and this function independently revalidates the Finance tenant,
-- company, unit, role and assignee projection in the database.
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
set search_path = pg_catalog, public
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
      raise exception using message = 'inbound_idempotency_conflict', errcode = '40001';
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
        raise exception using message = 'inbound_registration_state_conflict', errcode = '40001';
      end if;
      if p_expected_version is null or p_expected_version <> v_document.mutation_version then
        raise exception using message = 'inbound_version_conflict', errcode = '40001';
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
        raise exception using message = 'inbound_version_conflict', errcode = '40001';
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
      raise exception using message = 'inbound_version_conflict', errcode = '40001';
    end if;
    if v_document.status in ('draft', 'closed', 'archived', 'cancelled') then
      raise exception using message = 'inbound_mutation_state_conflict', errcode = '40001';
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
      raise exception using message = 'inbound_version_conflict', errcode = '40001';
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

alter function public.edoc_mutate_inbound_document_v1(
  text, text, text, text, text, bigint, jsonb
) owner to postgres;
revoke all on function public.edoc_mutate_inbound_document_v1(
  text, text, text, text, text, bigint, jsonb
) from public, anon, authenticated;
grant execute on function public.edoc_mutate_inbound_document_v1(
  text, text, text, text, text, bigint, jsonb
) to service_role;

comment on function public.edoc_mutate_inbound_document_v1(
  text, text, text, text, text, bigint, jsonb
) is 'Atomic service-only inbound draft/register/assign/exception/close mutation with Finance scope, CAS and idempotency checks.';

comment on column public.inbound_documents.mutation_version is
  'Server-owned optimistic lock. Every dedicated inbound mutation increments it exactly once.';
comment on table public.inbound_document_mutations is
  'Service-only immutable idempotency ledger. Response JSON is limited to id, scope, version and hash; it never stores document body, subject, contact, metadata or attachments.';

commit;
