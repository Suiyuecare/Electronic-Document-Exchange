create table if not exists public.document_acl (
  id text primary key,
  document_id text not null references public.documents(id) on delete cascade,
  principal_type text not null check (principal_type in ('role', 'user', 'unit')),
  principal_id text not null,
  can_view boolean not null default true,
  can_sign boolean not null default false,
  can_download boolean not null default false,
  can_seal boolean not null default false,
  can_delegate boolean not null default false,
  reason text,
  granted_by text,
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.document_acl_events (
  id text primary key,
  document_id text not null references public.documents(id) on delete cascade,
  actor text not null,
  action text not null,
  detail text,
  created_at timestamptz not null default now()
);

create index if not exists idx_document_acl_document on public.document_acl(document_id);
create index if not exists idx_document_acl_principal on public.document_acl(principal_type, principal_id);
create index if not exists idx_document_acl_events_document on public.document_acl_events(document_id);

alter table public.document_acl enable row level security;
alter table public.document_acl_events enable row level security;

drop policy if exists "service role manages document acl" on public.document_acl;
create policy "service role manages document acl"
on public.document_acl
for all
using (true)
with check (true);

drop policy if exists "service role manages document acl events" on public.document_acl_events;
create policy "service role manages document acl events"
on public.document_acl_events
for all
using (true)
with check (true);
