create table if not exists public.documents (
  id text primary key,
  doc_no text not null,
  direction text not null check (direction in ('收文', '發文')),
  doc_type text not null default '函',
  priority text not null default '普通件',
  security_level text not null default '普通',
  agency_name text not null,
  agency_code text,
  subject text not null,
  body text,
  status text not null,
  owner text,
  department text,
  due_date text,
  received_at text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.recipients (
  id text primary key,
  name text not null,
  code text not null unique,
  exchange_center text not null,
  status text not null,
  contact text,
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.attachments (
  id text primary key,
  document_id text not null references public.documents(id) on delete cascade,
  file_name text not null,
  version text not null default 'v1',
  mime_type text,
  size_bytes bigint not null default 0,
  sha256 text not null,
  scan_status text not null default '待掃描',
  storage_key text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.exchange_tasks (
  id text primary key,
  document_id text not null references public.documents(id) on delete cascade,
  direction text not null,
  target_agency text not null,
  status text not null,
  package_id text,
  retry_count integer not null default 0,
  next_check_at text,
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.exchange_events (
  id text primary key,
  task_id text references public.exchange_tasks(id) on delete set null,
  document_id text references public.documents(id) on delete cascade,
  event_type text not null,
  message text not null,
  payload_json text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.audit_logs (
  id text primary key,
  actor text not null,
  action text not null,
  target_type text,
  target_id text,
  ip text,
  device text,
  detail text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.users (
  id text primary key,
  name text not null,
  email text not null unique,
  unit text,
  title text,
  role text not null,
  provider text not null default '本機帳號',
  mfa_status text not null default '待設定',
  status text not null default '啟用',
  last_login_at text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.background_jobs (
  id text primary key,
  name text not null,
  job_type text not null,
  schedule_text text not null,
  status text not null default '啟用',
  last_result text not null default '尚未執行',
  next_run_at text,
  run_count integer not null default 0,
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.settings (
  key text primary key,
  value_json text not null,
  version integer not null default 1,
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create index if not exists idx_documents_status on public.documents(status);
create index if not exists idx_documents_direction on public.documents(direction);
create index if not exists idx_attachments_document on public.attachments(document_id);
create index if not exists idx_exchange_tasks_document on public.exchange_tasks(document_id);
create index if not exists idx_exchange_events_document on public.exchange_events(document_id);
create index if not exists idx_audit_logs_created on public.audit_logs(created_at);

alter table public.documents enable row level security;
alter table public.recipients enable row level security;
alter table public.attachments enable row level security;
alter table public.exchange_tasks enable row level security;
alter table public.exchange_events enable row level security;
alter table public.audit_logs enable row level security;
alter table public.users enable row level security;
alter table public.background_jobs enable row level security;
alter table public.settings enable row level security;

-- Server-side API uses the service role key. Browser clients are intentionally
-- denied by default until a real Auth/RBAC model is wired.
drop policy if exists "deny anon documents" on public.documents;
create policy "deny anon documents" on public.documents for all to anon using (false) with check (false);

drop policy if exists "deny anon recipients" on public.recipients;
create policy "deny anon recipients" on public.recipients for all to anon using (false) with check (false);

drop policy if exists "deny anon attachments" on public.attachments;
create policy "deny anon attachments" on public.attachments for all to anon using (false) with check (false);

drop policy if exists "deny anon exchange_tasks" on public.exchange_tasks;
create policy "deny anon exchange_tasks" on public.exchange_tasks for all to anon using (false) with check (false);

drop policy if exists "deny anon exchange_events" on public.exchange_events;
create policy "deny anon exchange_events" on public.exchange_events for all to anon using (false) with check (false);

drop policy if exists "deny anon audit_logs" on public.audit_logs;
create policy "deny anon audit_logs" on public.audit_logs for all to anon using (false) with check (false);

drop policy if exists "deny anon users" on public.users;
create policy "deny anon users" on public.users for all to anon using (false) with check (false);

drop policy if exists "deny anon background_jobs" on public.background_jobs;
create policy "deny anon background_jobs" on public.background_jobs for all to anon using (false) with check (false);

drop policy if exists "deny anon settings" on public.settings;
create policy "deny anon settings" on public.settings for all to anon using (false) with check (false);
