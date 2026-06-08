alter table public.electronic_signatures
  add column if not exists provider text,
  add column if not exists provider_key_id text,
  add column if not exists provider_request_id text,
  add column if not exists provider_receipt_json text,
  add column if not exists evidence_digest_sha256 text;

alter table public.seal_applications
  add column if not exists signature_id text,
  add column if not exists provider_status text,
  add column if not exists failure_reason text,
  add column if not exists evidence_json text,
  add column if not exists updated_at text;

create table if not exists public.signature_provider_events (
  id text primary key,
  document_id text,
  signature_id text,
  provider text not null,
  operation text not null,
  request_id text not null,
  endpoint text not null,
  request_digest_sha256 text not null,
  response_digest_sha256 text,
  status text not null,
  http_status integer,
  error text,
  attempt_count integer not null default 1,
  duration_ms integer,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create index if not exists idx_signature_provider_events_signature on public.signature_provider_events(signature_id);
create index if not exists idx_signature_provider_events_request on public.signature_provider_events(request_id);
create index if not exists idx_electronic_signatures_provider_request on public.electronic_signatures(provider_request_id);
create index if not exists idx_seal_applications_signature on public.seal_applications(signature_id);

alter table public.signature_provider_events enable row level security;

drop policy if exists "service role manages signature provider events" on public.signature_provider_events;
create policy "service role manages signature provider events"
on public.signature_provider_events for all
using (true)
with check (true);
