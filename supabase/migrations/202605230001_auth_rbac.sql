alter table public.users add column if not exists auth_user_id uuid references auth.users(id) on delete set null;
alter table public.users add column if not exists password_hash text;

create table if not exists public.roles (
  id text primary key,
  name text not null unique,
  description text,
  data_scope text not null default 'assigned',
  status text not null default '啟用',
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.permissions (
  id text primary key,
  code text not null unique,
  name text not null,
  category text not null,
  description text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.role_permissions (
  role_id text not null references public.roles(id) on delete cascade,
  permission_id text not null references public.permissions(id) on delete cascade,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  primary key (role_id, permission_id)
);

create table if not exists public.auth_sessions (
  id text primary key,
  user_id text not null references public.users(id) on delete cascade,
  token_hash text not null unique,
  provider text not null,
  ip text,
  device text,
  expires_at text not null,
  revoked_at text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.login_events (
  id text primary key,
  user_id text references public.users(id) on delete set null,
  email text not null,
  provider text not null,
  ip text,
  device text,
  status text not null,
  reason text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.trusted_devices (
  id text primary key,
  user_id text not null references public.users(id) on delete cascade,
  name text not null,
  ip text,
  fingerprint text not null,
  status text not null default '待複核',
  last_seen_at text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.ip_allowlist (
  id text primary key,
  cidr text not null unique,
  purpose text not null,
  status text not null default '啟用',
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.sso_providers (
  id text primary key,
  provider text not null unique,
  domain text not null,
  tenant_id text,
  client_id text,
  status text not null default '未連線',
  require_mfa boolean not null default true,
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create index if not exists idx_users_email on public.users(email);
create index if not exists idx_users_auth_user_id on public.users(auth_user_id);
create index if not exists idx_auth_sessions_token on public.auth_sessions(token_hash);
create index if not exists idx_login_events_created on public.login_events(created_at);
create index if not exists idx_trusted_devices_user on public.trusted_devices(user_id);

alter table public.roles enable row level security;
alter table public.permissions enable row level security;
alter table public.role_permissions enable row level security;
alter table public.auth_sessions enable row level security;
alter table public.login_events enable row level security;
alter table public.trusted_devices enable row level security;
alter table public.ip_allowlist enable row level security;
alter table public.sso_providers enable row level security;

grant usage on schema public to authenticated;
grant select, insert, update on
  public.documents,
  public.recipients,
  public.attachments,
  public.exchange_tasks,
  public.exchange_events,
  public.audit_logs,
  public.users,
  public.roles,
  public.permissions,
  public.role_permissions,
  public.auth_sessions,
  public.login_events,
  public.trusted_devices,
  public.ip_allowlist,
  public.sso_providers,
  public.background_jobs,
  public.settings
to authenticated;

drop policy if exists "authenticated read own profile" on public.users;
create policy "authenticated read own profile" on public.users
for select to authenticated
using (auth.uid() = auth_user_id);

drop policy if exists "authenticated update own profile basics" on public.users;
create policy "authenticated update own profile basics" on public.users
for update to authenticated
using (auth.uid() = auth_user_id)
with check (auth.uid() = auth_user_id);

drop policy if exists "authenticated read roles" on public.roles;
create policy "authenticated read roles" on public.roles
for select to authenticated using (true);

drop policy if exists "authenticated read permissions" on public.permissions;
create policy "authenticated read permissions" on public.permissions
for select to authenticated using (true);

drop policy if exists "authenticated read role permissions" on public.role_permissions;
create policy "authenticated read role permissions" on public.role_permissions
for select to authenticated using (true);

drop policy if exists "authenticated read own sessions" on public.auth_sessions;
create policy "authenticated read own sessions" on public.auth_sessions
for select to authenticated
using (exists (select 1 from public.users u where u.id = auth_sessions.user_id and u.auth_user_id = auth.uid()));

drop policy if exists "authenticated read own login events" on public.login_events;
create policy "authenticated read own login events" on public.login_events
for select to authenticated
using (exists (select 1 from public.users u where u.id = login_events.user_id and u.auth_user_id = auth.uid()));

drop policy if exists "authenticated read own devices" on public.trusted_devices;
create policy "authenticated read own devices" on public.trusted_devices
for select to authenticated
using (exists (select 1 from public.users u where u.id = trusted_devices.user_id and u.auth_user_id = auth.uid()));

drop policy if exists "authenticated read active ip rules" on public.ip_allowlist;
create policy "authenticated read active ip rules" on public.ip_allowlist
for select to authenticated using (status = '啟用');

drop policy if exists "authenticated read sso providers" on public.sso_providers;
create policy "authenticated read sso providers" on public.sso_providers
for select to authenticated using (true);
