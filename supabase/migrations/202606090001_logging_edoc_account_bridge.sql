-- Link Logging/HR platform accounts to EDOC users without storing platform secrets.
-- The bridge keeps EDOC RBAC as the local enforcement layer while recording the
-- source account, source role key and sync history for auditability.

alter table public.users
  add column if not exists auth_user_id text,
  add column if not exists account_source text not null default 'edoc',
  add column if not exists logging_account_id text,
  add column if not exists logging_role_key text,
  add column if not exists external_account_payload_json text not null default '{}',
  add column if not exists last_synced_from_logging_at text,
  add column if not exists password_hash text,
  add column if not exists job_level text not null default '職員';

create table if not exists public.module_account_links (
  id text primary key,
  user_id text not null references public.users(id) on delete cascade,
  source_system text not null,
  source_account_id text not null,
  source_role_key text,
  source_email text,
  target_module text not null default 'edoc',
  target_role_key text,
  sync_status text not null default 'active',
  metadata_json text not null default '{}',
  last_synced_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  unique(source_system, source_account_id, target_module)
);

create index if not exists idx_users_logging_account
  on public.users(logging_account_id);

create index if not exists idx_users_account_source
  on public.users(account_source, logging_role_key);

create index if not exists idx_module_account_links_source
  on public.module_account_links(source_system, source_account_id, target_module);

alter table public.module_account_links enable row level security;
