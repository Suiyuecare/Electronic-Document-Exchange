create table if not exists public.exchange_outbox (
  id text primary key,
  document_id text not null references public.documents(id) on delete cascade,
  doc_no text not null,
  target_agency text not null,
  target_agency_code text,
  status text not null check (status in ('待發文','已送出','已送達','失敗','退文','已達重送上限')),
  provider text not null default 'mock',
  environment text not null default 'sandbox',
  package_id text,
  external_id text,
  idempotency_key text not null unique,
  retry_count integer not null default 0,
  max_retries integer not null default 3,
  last_error_code text,
  last_error_message text,
  next_retry_at text,
  sent_at text,
  returned_at text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.exchange_inbox (
  id text primary key,
  document_id text references public.documents(id) on delete set null,
  external_id text not null unique,
  source_agency text not null,
  source_agency_code text,
  doc_no text not null,
  subject text not null,
  status text not null check (status in ('已收文','待確認','已入案')),
  provider text not null default 'mock',
  environment text not null default 'sandbox',
  received_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  acknowledged_at text,
  raw_summary_json text not null default '{}',
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.exchange_log (
  id text primary key,
  exchange_ref_type text not null check (exchange_ref_type in ('outbox','inbox','status','system')),
  exchange_ref_id text not null,
  provider text not null,
  environment text not null,
  operation text not null,
  direction text not null check (direction in ('outbound','inbound','system')),
  request_summary_json text not null default '{}',
  response_summary_json text not null default '{}',
  status text not null,
  error_code text,
  error_message text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.exchange_attachment (
  id text primary key,
  exchange_ref_type text not null check (exchange_ref_type in ('outbox','inbox')),
  exchange_ref_id text not null,
  document_id text references public.documents(id) on delete set null,
  file_name text not null,
  mime_type text,
  size_bytes bigint not null default 0,
  sha256 text,
  storage_key text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.exchange_status_history (
  id text primary key,
  exchange_ref_type text not null check (exchange_ref_type in ('outbox','inbox')),
  exchange_ref_id text not null,
  from_status text,
  to_status text not null,
  message text,
  provider_status_code text,
  payload_summary_json text not null default '{}',
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create index if not exists idx_exchange_outbox_document on public.exchange_outbox(document_id);
create index if not exists idx_exchange_outbox_status on public.exchange_outbox(status);
create index if not exists idx_exchange_outbox_external on public.exchange_outbox(external_id);
create index if not exists idx_exchange_inbox_document on public.exchange_inbox(document_id);
create index if not exists idx_exchange_inbox_status on public.exchange_inbox(status);
create index if not exists idx_exchange_log_ref on public.exchange_log(exchange_ref_type, exchange_ref_id);
create index if not exists idx_exchange_attachment_ref on public.exchange_attachment(exchange_ref_type, exchange_ref_id);
create index if not exists idx_exchange_status_history_ref on public.exchange_status_history(exchange_ref_type, exchange_ref_id);

alter table public.exchange_outbox enable row level security;
alter table public.exchange_inbox enable row level security;
alter table public.exchange_log enable row level security;
alter table public.exchange_attachment enable row level security;
alter table public.exchange_status_history enable row level security;

grant select, insert, update on public.exchange_outbox to authenticated;
grant select, insert, update on public.exchange_inbox to authenticated;
grant select, insert on public.exchange_log to authenticated;
grant select, insert on public.exchange_attachment to authenticated;
grant select, insert on public.exchange_status_history to authenticated;

drop policy if exists "deny anon exchange outbox" on public.exchange_outbox;
create policy "deny anon exchange outbox" on public.exchange_outbox for all to anon using (false) with check (false);

drop policy if exists "deny anon exchange inbox" on public.exchange_inbox;
create policy "deny anon exchange inbox" on public.exchange_inbox for all to anon using (false) with check (false);

drop policy if exists "deny anon exchange log" on public.exchange_log;
create policy "deny anon exchange log" on public.exchange_log for all to anon using (false) with check (false);

drop policy if exists "deny anon exchange attachment" on public.exchange_attachment;
create policy "deny anon exchange attachment" on public.exchange_attachment for all to anon using (false) with check (false);

drop policy if exists "deny anon exchange status history" on public.exchange_status_history;
create policy "deny anon exchange status history" on public.exchange_status_history for all to anon using (false) with check (false);

insert into public.background_jobs (id, name, job_type, schedule_text, status, last_result, next_run_at, run_count)
values
  ('JOB-009', '交換待發公文送出', 'exchangeSendPending', '每 5 分鐘', '啟用', '尚未執行', '2026-05-23 09:05', 0),
  ('JOB-010', '交換失敗重送', 'exchangeRetryFailed', '每 15 分鐘', '啟用', '尚未執行', '2026-05-23 09:15', 0)
on conflict (id) do nothing;
