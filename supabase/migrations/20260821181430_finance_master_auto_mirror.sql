-- Finance is the sole personnel/company master.  EDOC stores a service-only,
-- revisioned projection so roster changes are made once in Finance and are
-- mirrored without exposing an administrative write surface to browsers.

alter table public.users
  add column if not exists finance_employee_id text,
  add column if not exists company_id text,
  add column if not exists company_address text,
  add column if not exists manager_employee_id text,
  add column if not exists manager_name text,
  add column if not exists manager_email text,
  add column if not exists manager_role_key text,
  add column if not exists approval_manager_employee_id text,
  add column if not exists approval_manager_name text,
  add column if not exists approval_manager_email text,
  add column if not exists approval_manager_role_key text,
  add column if not exists finance_source_revision bigint not null default 0,
  add column if not exists finance_source_event_id text,
  add column if not exists finance_source_status text not null default 'legacy',
  add column if not exists finance_source_updated_at text;

alter table public.companies
  add column if not exists address text,
  add column if not exists finance_entity_id text,
  add column if not exists source_system text,
  add column if not exists last_synced_from_finance_at text,
  add column if not exists finance_source_revision bigint not null default 0,
  add column if not exists finance_source_event_id text,
  add column if not exists finance_source_updated_at text;

-- Three production rows were once overwritten with legacy employee numbers.
-- This is intentionally fail-closed: a partially matching production state is
-- not safe to repair automatically, while a fresh database (zero rows) is.
do $$
declare
  v_present integer;
  v_valid integer;
begin
  with mapping(user_id, old_id, new_id) as (
    values
      ('LOG-A7706D66E5', '40', 'u_1779419271785'),
      ('LOG-D4735E3A26', '2',  'u_entrepreneur'),
      ('LOG-F7F8E13BCD', '8',  'u_1779426092633')
  )
  select count(*) into v_present
  from mapping m
  join public.users u on u.id = m.user_id;

  if v_present not in (0, 3) then
    raise exception 'finance legacy alias preflight failed: expected 0 or 3 rows, got %', v_present;
  end if;

  if v_present = 3 then
    with mapping(user_id, old_id, new_id) as (
      values
        ('LOG-A7706D66E5', '40', 'u_1779419271785'),
        ('LOG-D4735E3A26', '2',  'u_entrepreneur'),
        ('LOG-F7F8E13BCD', '8',  'u_1779426092633')
    )
    select count(*) into v_valid
    from mapping m
    join public.users u on u.id = m.user_id
    where lower(btrim(coalesce(u.account_source, ''))) = 'finance'
      and u.logging_account_id in (m.old_id, m.new_id)
      and u.finance_employee_id in (m.old_id, m.new_id)
      and exists (
        select 1
        from public.module_account_links l
        where l.user_id = u.id
          and lower(btrim(l.source_system)) = 'finance'
          and l.target_module = 'edoc'
          and l.source_account_id = m.new_id
      );

    if v_valid <> 3 then
      raise exception 'finance legacy alias preflight failed: expected 3 verified rows, got %', v_valid;
    end if;
  end if;
end
$$;

with mapping(user_id, old_id) as (
  values
    ('LOG-A7706D66E5', '40'),
    ('LOG-D4735E3A26', '2'),
    ('LOG-F7F8E13BCD', '8')
)
update public.module_account_links l
set sync_status = 'superseded',
    updated_at = to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
from mapping m
where l.user_id = m.user_id
  and lower(btrim(l.source_system)) = 'finance'
  and l.target_module = 'edoc'
  and l.source_account_id = m.old_id;

with mapping(user_id, new_id) as (
  values
    ('LOG-A7706D66E5', 'u_1779419271785'),
    ('LOG-D4735E3A26', 'u_entrepreneur'),
    ('LOG-F7F8E13BCD', 'u_1779426092633')
)
update public.users u
set logging_account_id = m.new_id,
    finance_employee_id = m.new_id,
    finance_source_status = case when u.status = '啟用' then 'active' else 'inactive' end,
    last_synced_from_logging_at = to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
from mapping m
where u.id = m.user_id
  and lower(btrim(coalesce(u.account_source, ''))) = 'finance';

with mapping(user_id, new_id) as (
  values
    ('LOG-A7706D66E5', 'u_1779419271785'),
    ('LOG-D4735E3A26', 'u_entrepreneur'),
    ('LOG-F7F8E13BCD', 'u_1779426092633')
)
update public.module_account_links l
set sync_status = 'active',
    updated_at = to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
from mapping m
where l.user_id = m.user_id
  and lower(btrim(l.source_system)) = 'finance'
  and l.target_module = 'edoc'
  and l.source_account_id = m.new_id;

-- Four Finance rows are intentionally excluded from the usable roster because
-- Finance classifies them as org_status=system_account.  They were previously
-- projected as enabled EDOC users.  Preserve their historical foreign keys,
-- but fail closed before disabling them so a changed production state can
-- never be acted on by a broad or name-based predicate.
do $$
declare
  v_present integer;
  v_valid integer;
begin
  with expected(user_id, finance_id, email_md5, link_id) as (
    values
      ('LOG-71EA5F5B96', 'u6',              '7208a0599aa3cba75983521024125506', 'LINK-FINANCE-EDOC-71EA5F5B96'),
      ('LOG-748CCCF0BE', 'u_1779426174933', '6a8ef82e2db372d5bb7b43c6a68533c9', 'LINK-FINANCE-EDOC-748CCCF0BE'),
      ('LOG-88B71ACA68', 'u_1779419312618', '41859051f964452e55c8fc7427b957eb', 'LINK-FINANCE-EDOC-88B71ACA68'),
      ('LOG-A0DD7667AA', 'u_1779426065699', 'b185535045a8478fbf59510308a80823', 'LINK-FINANCE-EDOC-A0DD7667AA')
  )
  select count(*) into v_present
  from expected e
  join public.users u on u.id = e.user_id;

  if v_present not in (0, 4) then
    raise exception 'finance system-account preflight failed: expected 0 or 4 rows, got %', v_present;
  end if;

  if v_present = 4 then
    with expected(user_id, finance_id, email_md5, link_id) as (
      values
        ('LOG-71EA5F5B96', 'u6',              '7208a0599aa3cba75983521024125506', 'LINK-FINANCE-EDOC-71EA5F5B96'),
        ('LOG-748CCCF0BE', 'u_1779426174933', '6a8ef82e2db372d5bb7b43c6a68533c9', 'LINK-FINANCE-EDOC-748CCCF0BE'),
        ('LOG-88B71ACA68', 'u_1779419312618', '41859051f964452e55c8fc7427b957eb', 'LINK-FINANCE-EDOC-88B71ACA68'),
        ('LOG-A0DD7667AA', 'u_1779426065699', 'b185535045a8478fbf59510308a80823', 'LINK-FINANCE-EDOC-A0DD7667AA')
    )
    select count(*) into v_valid
    from expected e
    join public.users u on u.id = e.user_id
    where lower(btrim(coalesce(u.account_source, ''))) = 'finance'
      and u.status = '啟用'
      and u.logging_account_id = e.finance_id
      and u.finance_employee_id = e.finance_id
      and md5(lower(btrim(coalesce(u.email, '')))) = e.email_md5
      and u.auth_user_id is null
      and 1 = (
        select count(*)
        from public.module_account_links l
        where l.user_id = e.user_id
          and lower(btrim(l.source_system)) = 'finance'
          and l.target_module = 'edoc'
          and l.sync_status = 'active'
      )
      and exists (
        select 1
        from public.module_account_links l
        where l.id = e.link_id
          and l.user_id = e.user_id
          and lower(btrim(l.source_system)) = 'finance'
          and l.source_account_id = e.finance_id
          and l.target_module = 'edoc'
          and l.sync_status = 'active'
          and md5(lower(btrim(coalesce(l.source_email, '')))) = e.email_md5
      )
      and not exists (
        select 1
        from public.auth_sessions s
        where s.user_id = e.user_id
          and s.revoked_at is null
          and s.expires_at > to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
      );

    if v_valid <> 4 then
      raise exception 'finance system-account preflight failed: expected 4 verified rows, got %', v_valid;
    end if;
  end if;
end
$$;

with expected(user_id) as (
  values
    ('LOG-71EA5F5B96'),
    ('LOG-748CCCF0BE'),
    ('LOG-88B71ACA68'),
    ('LOG-A0DD7667AA')
)
update public.users u
set status = '停用',
    finance_source_status = 'inactive',
    last_synced_from_logging_at = to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
from expected e
where u.id = e.user_id;

with expected(link_id) as (
  values
    ('LINK-FINANCE-EDOC-71EA5F5B96'),
    ('LINK-FINANCE-EDOC-748CCCF0BE'),
    ('LINK-FINANCE-EDOC-88B71ACA68'),
    ('LINK-FINANCE-EDOC-A0DD7667AA')
)
update public.module_account_links l
set sync_status = 'inactive',
    last_synced_at = to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    updated_at = to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
from expected e
where l.id = e.link_id;

-- Defensive only: the preflight requires no currently active session, but an
-- expired, unrevoked row must not become usable through later clock/skew bugs.
with expected(user_id) as (
  values
    ('LOG-71EA5F5B96'),
    ('LOG-748CCCF0BE'),
    ('LOG-88B71ACA68'),
    ('LOG-A0DD7667AA')
)
update public.auth_sessions s
set revoked_at = to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
from expected e
where s.user_id = e.user_id
  and s.revoked_at is null;

create unique index if not exists users_email_normalized_uq
  on public.users ((lower(btrim(email))));

create unique index if not exists users_auth_user_id_uq
  on public.users (auth_user_id)
  where auth_user_id is not null;

create unique index if not exists users_finance_logging_account_uq
  on public.users (logging_account_id)
  where lower(btrim(account_source)) = 'finance'
    and nullif(btrim(logging_account_id), '') is not null;

create unique index if not exists users_finance_employee_uq
  on public.users (finance_employee_id)
  where lower(btrim(account_source)) = 'finance'
    and nullif(btrim(finance_employee_id), '') is not null;

create unique index if not exists module_account_links_one_active_finance_link_uq
  on public.module_account_links (user_id, (lower(btrim(source_system))), target_module)
  where lower(btrim(source_system)) = 'finance'
    and target_module = 'edoc'
    and sync_status = 'active';

create unique index if not exists companies_finance_entity_id_uq
  on public.companies (finance_entity_id)
  where nullif(btrim(finance_entity_id), '') is not null;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.users'::regclass
      and conname = 'users_finance_identity_fields_match'
  ) then
    alter table public.users
      add constraint users_finance_identity_fields_match
      check (
        lower(btrim(account_source)) <> 'finance'
        or (
          nullif(btrim(logging_account_id), '') is not null
          and logging_account_id = finance_employee_id
        )
      ) not valid;
  end if;
end
$$;

alter table public.users
  validate constraint users_finance_identity_fields_match;

create table if not exists public.finance_member_sync_nonces (
  nonce_hash text primary key,
  issued_at bigint not null,
  expires_at bigint not null,
  consumed_at timestamptz not null default now(),
  constraint finance_member_sync_nonce_hash_check
    check (nonce_hash ~ '^[0-9a-f]{64}$'),
  constraint finance_member_sync_nonce_window_check
    check (expires_at >= issued_at)
);

create index if not exists finance_member_sync_nonces_expiry_idx
  on public.finance_member_sync_nonces (expires_at);

create table if not exists public.finance_member_sync_receipts (
  event_id text primary key,
  event_type text not null,
  source_revision bigint not null,
  finance_user_id text,
  finance_entity_id text,
  projected_user_id text,
  projected_company_id text,
  payload_sha256 text not null,
  apply_status text not null,
  result_code text not null,
  received_at timestamptz not null default now(),
  completed_at timestamptz not null default now(),
  constraint finance_member_sync_receipts_event_type_check
    check (event_type in ('member.changed', 'company.changed')),
  constraint finance_member_sync_receipts_revision_check
    check (source_revision >= 1),
  constraint finance_member_sync_receipts_hash_check
    check (payload_sha256 ~ '^[0-9a-f]{64}$'),
  constraint finance_member_sync_receipts_status_check
    check (apply_status in ('applied', 'stale', 'failed'))
);

create index if not exists finance_member_sync_receipts_member_idx
  on public.finance_member_sync_receipts (finance_user_id, source_revision desc)
  where finance_user_id is not null;

create index if not exists finance_member_sync_receipts_company_idx
  on public.finance_member_sync_receipts (finance_entity_id, source_revision desc)
  where finance_entity_id is not null;

alter table public.finance_member_sync_nonces enable row level security;
alter table public.finance_member_sync_receipts enable row level security;

revoke all on public.finance_member_sync_nonces from public, anon, authenticated;
revoke all on public.finance_member_sync_receipts from public, anon, authenticated;

grant select, insert, delete on public.finance_member_sync_nonces to service_role;
grant select, insert, update on public.finance_member_sync_receipts to service_role;

drop policy if exists "service role manages finance sync nonces"
  on public.finance_member_sync_nonces;
create policy "service role manages finance sync nonces"
  on public.finance_member_sync_nonces
  for all to service_role
  using (true)
  with check (true);

drop policy if exists "service role manages finance sync receipts"
  on public.finance_member_sync_receipts;
create policy "service role manages finance sync receipts"
  on public.finance_member_sync_receipts
  for all to service_role
  using (true)
  with check (true);

comment on table public.finance_member_sync_nonces is
  'Server-only replay protection for HMAC-authenticated Finance roster projection events.';
comment on table public.finance_member_sync_receipts is
  'Server-only idempotency/audit receipt. Stores identifiers, revisions and hashes only; never PDF/document content.';
