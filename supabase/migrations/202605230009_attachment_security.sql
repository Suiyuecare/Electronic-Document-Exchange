create table if not exists public.attachment_security (
  id text primary key,
  attachment_id text not null unique references public.attachments(id) on delete cascade,
  document_id text not null references public.documents(id) on delete cascade,
  file_name text not null,
  file_ext text,
  size_bytes bigint not null default 0,
  max_size_bytes bigint not null default 52428800,
  scan_status text not null default '待掃描',
  scan_engine text not null default 'ClamAV-compatible',
  scan_signature text,
  mask_status text not null default '未遮罩',
  sensitive_hits_json jsonb not null default '[]'::jsonb,
  confidential_level text not null default '普通',
  allowed_roles text,
  watermark_status text not null default '未下載',
  quarantine_reason text,
  backup_id text,
  last_accessed_by text,
  last_accessed_at timestamptz,
  updated_at timestamptz not null default now()
);

create table if not exists public.file_access_logs (
  id text primary key,
  attachment_id text references public.attachments(id) on delete set null,
  file_object_id text references public.file_objects(id) on delete set null,
  document_id text references public.documents(id) on delete set null,
  actor text not null,
  action text not null,
  ip text,
  device text,
  watermark_text text,
  result text not null,
  detail text,
  created_at timestamptz not null default now()
);

create index if not exists idx_attachment_security_document on public.attachment_security(document_id);
create index if not exists idx_attachment_security_scan on public.attachment_security(scan_status);
create index if not exists idx_file_access_logs_attachment on public.file_access_logs(attachment_id);
create index if not exists idx_file_access_logs_created on public.file_access_logs(created_at);

alter table public.attachment_security enable row level security;
alter table public.file_access_logs enable row level security;

drop policy if exists "authenticated read attachment security" on public.attachment_security;
create policy "authenticated read attachment security"
on public.attachment_security for select
to authenticated
using (true);

drop policy if exists "authenticated read file access logs" on public.file_access_logs;
create policy "authenticated read file access logs"
on public.file_access_logs for select
to authenticated
using (true);

drop policy if exists "service role manages attachment security" on public.attachment_security;
create policy "service role manages attachment security"
on public.attachment_security for all
using (true)
with check (true);

drop policy if exists "service role manages file access logs" on public.file_access_logs;
create policy "service role manages file access logs"
on public.file_access_logs for all
using (true)
with check (true);
