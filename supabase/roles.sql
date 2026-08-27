-- Fresh-bootstrap prerequisite for the historical RBAC chain.
--
-- Supabase loads roles.sql before timestamped migrations. The legacy
-- 202605230005 migration assigns these permission IDs, while the original
-- repository never inserted them first. Define only the missing reference
-- table/rows here so a new or disaster-recovery database can replay the
-- immutable applied migrations without rewriting their history.
--
-- Supabase installs pgcrypto in the extensions schema, while an early applied
-- migration called digest() from a function whose search_path is only public.
-- The narrow compatibility overloads below preserve that historical function
-- body during a fresh replay.  They expose only pgcrypto's one-way digest
-- primitive and use an empty search_path with fully-qualified dependencies.
--
-- This file contains no accounts, credentials, documents or company data.
-- The only privilege statements scope these compatibility overloads to
-- postgres/service_role; later migrations keep RLS and module permissions
-- authoritative.

create extension if not exists pgcrypto with schema extensions;

-- The compatibility functions below must never bind to an unexpected schema.
-- Fail the reset immediately if the managed project installed/moved pgcrypto
-- somewhere other than the backend-only ``extensions`` namespace.
do $bootstrap$
declare
  v_pgcrypto_schema text;
begin
  select namespace_row.nspname
    into v_pgcrypto_schema
  from pg_catalog.pg_extension extension_row
  join pg_catalog.pg_namespace namespace_row
    on namespace_row.oid = extension_row.extnamespace
  where extension_row.extname = 'pgcrypto';

  if v_pgcrypto_schema is distinct from 'extensions'
     or pg_catalog.to_regprocedure('extensions.digest(bytea,text)') is null
     or pg_catalog.to_regprocedure('extensions.gen_random_bytes(integer)') is null then
    raise exception using
      errcode = '55000',
      message = 'edoc_pgcrypto_extensions_schema_required';
  end if;
end
$bootstrap$;

create or replace function public.digest(data text, digest_type text)
returns bytea
language sql
immutable
strict
parallel safe
set search_path = ''
as $$
  select extensions.digest(pg_catalog.convert_to(data, 'UTF8'), digest_type)
$$;

create or replace function public.digest(data bytea, digest_type text)
returns bytea
language sql
immutable
strict
parallel safe
set search_path = ''
as $$
  select extensions.digest(data, digest_type)
$$;

revoke all on function public.digest(text, text) from public, anon, authenticated;
revoke all on function public.digest(bytea, text) from public, anon, authenticated;
grant execute on function public.digest(text, text) to postgres, service_role;
grant execute on function public.digest(bytea, text) to postgres, service_role;

-- One later historical migration stores trigger-only seal provisioning helpers
-- in ``private`` and intentionally refuses to create that schema itself.  Keep
-- the schema backend-only so a fresh replay matches the production topology.
create schema if not exists private authorization postgres;
revoke all on schema private from public, anon, authenticated;
grant usage on schema private to service_role;

-- Immutable-migration compatibility for a completely empty database.
--
-- Historical migration 20260825143558 intentionally fails closed unless one
-- authoritative Finance tenant exists. That migration may already be applied
-- remotely and must not be rewritten merely to make a disaster-recovery reset
-- pass. Fresh resets therefore receive one unmistakable structural sentinel
-- before the immutable migration chain runs. A later forward migration removes
-- it only after verifying its complete signature and the absence of references.
-- It is not an account, company, organization unit or usable Finance record.
create table if not exists public.finance_organization_projection_state (
  finance_tenant_id text primary key,
  version_no bigint not null,
  version_id text not null,
  etag text not null,
  schema_version integer not null,
  source_event_id text not null,
  source_occurred_at text not null,
  payload_sha256 text not null,
  unit_count integer not null default 0,
  assignment_count integer not null default 0,
  last_synced_from_finance_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint finance_organization_projection_state_tenant_check
    check (char_length(btrim(finance_tenant_id)) between 1 and 128),
  constraint finance_organization_projection_state_version_check
    check (version_no > 0),
  constraint finance_organization_projection_state_etag_check
    check (etag ~ '^[0-9a-f]{64}$'),
  constraint finance_organization_projection_state_hash_check
    check (payload_sha256 ~ '^[0-9a-f]{64}$'),
  constraint finance_organization_projection_state_schema_check
    check (schema_version = 2),
  constraint finance_organization_projection_state_counts_check
    check (unit_count between 0 and 500 and assignment_count between 0 and 2000)
);

insert into public.finance_organization_projection_state (
  finance_tenant_id,
  version_no,
  version_id,
  etag,
  schema_version,
  source_event_id,
  source_occurred_at,
  payload_sha256,
  unit_count,
  assignment_count,
  last_synced_from_finance_at,
  updated_at
) values (
  '__edoc_fresh_bootstrap_only__',
  1,
  'EDOC-FRESH-BOOTSTRAP-COMPAT-V1',
  repeat('0', 64),
  2,
  'EDOC-FRESH-BOOTSTRAP-COMPAT-V1',
  '1970-01-01T00:00:00Z',
  repeat('0', 64),
  0,
  0,
  '1970-01-01 00:00:00+00',
  '1970-01-01 00:00:00+00'
)
on conflict (finance_tenant_id) do nothing;

create table if not exists public.permissions (
  id text primary key,
  code text not null unique,
  name text not null,
  category text not null,
  description text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

insert into public.permissions (id, code, name, category, description) values
  ('PERM-INBOUND', 'inbound.manage', '收文管理', '公文', '拉取、登錄、分派與誤送漏送處理。'),
  ('PERM-DISPATCH', 'dispatch.manage', '發文管理', '公文', '建立函稿、清稿、封裝、送交與重送。'),
  ('PERM-JAGENT', 'jagent.manage', 'jAgent 介接', '系統', '憑證登入、Token、交換中心與地址簿。'),
  ('PERM-WORKFLOW', 'workflow.approve', '簽核流程', '流程', '簽核、退回、抽回、加簽、會辦與改派。'),
  ('PERM-SEAL', 'seal.apply', '自動用印', '印鑑', 'PDF 套版、押章與用印紀錄。'),
  ('PERM-AUDIT', 'audit.view', '稽核查閱', '稽核', 'Audit log、交換事件與不可否認紀錄。'),
  ('PERM-SECURITY', 'security.manage', '資安管理', '資安', 'RBAC、IP/裝置限制、MFA 與 Token 過期。'),
  ('PERM-REPORT', 'reports.view', '報表統計', '報表', '收發量、成功率、異常、承辦量與逾期件。'),
  ('PERM-SETTINGS', 'settings.manage', '系統設定', '系統', '機關代碼、API URL、防火牆、憑證與角色。')
on conflict (id) do update set
  code = excluded.code,
  name = excluded.name,
  category = excluded.category,
  description = excluded.description;
