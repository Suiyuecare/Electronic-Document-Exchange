-- Formal file storage and virus scanning policy.
-- Uses a private Supabase Storage bucket, short-lived signed URLs, encryption metadata,
-- scan jobs, and quarantine-aware download controls.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'edoc-private',
  'edoc-private',
  false,
  104857600,
  array[
    'application/pdf',
    'application/xml',
    'text/xml',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/pkcs7-mime',
    'application/octet-stream'
  ]
)
on conflict (id) do update set
  public = false,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

alter table public.file_objects add column if not exists bucket text not null default 'edoc-private';
alter table public.file_objects add column if not exists storage_provider text not null default 'supabase';
alter table public.file_objects add column if not exists encrypted_sha256 text;
alter table public.file_objects add column if not exists encryption_status text not null default '未加密';
alter table public.file_objects add column if not exists encryption_alg text;
alter table public.file_objects add column if not exists encryption_key_id text;
alter table public.file_objects add column if not exists scan_status text not null default '待掃描';
alter table public.file_objects add column if not exists scan_engine text;
alter table public.file_objects add column if not exists quarantine_reason text;
alter table public.file_objects add column if not exists signed_url_expires_at timestamptz;
alter table public.file_objects add column if not exists last_scan_at timestamptz;
alter table public.file_objects add column if not exists last_download_at timestamptz;

create table if not exists public.file_download_tokens (
  id text primary key,
  file_object_id text not null references public.file_objects(id) on delete cascade,
  token_hash text not null unique,
  actor text not null,
  purpose text not null default 'download',
  expires_at timestamptz not null,
  used_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.virus_scan_jobs (
  id text primary key,
  file_object_id text references public.file_objects(id) on delete set null,
  attachment_id text references public.attachments(id) on delete set null,
  document_id text references public.documents(id) on delete set null,
  engine text not null default 'ClamAV-compatible',
  status text not null default 'queued',
  signature text,
  result text,
  detail text,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists idx_file_objects_bucket_storage_key on public.file_objects(bucket, storage_key);
create index if not exists idx_file_objects_scan_status on public.file_objects(scan_status);
create index if not exists idx_file_download_tokens_file on public.file_download_tokens(file_object_id);
create index if not exists idx_file_download_tokens_expires on public.file_download_tokens(expires_at);
create index if not exists idx_virus_scan_jobs_file on public.virus_scan_jobs(file_object_id);
create index if not exists idx_virus_scan_jobs_status on public.virus_scan_jobs(status);

alter table public.file_download_tokens enable row level security;
alter table public.virus_scan_jobs enable row level security;

grant select, insert, update on public.file_download_tokens to authenticated;
grant select, insert, update on public.virus_scan_jobs to authenticated;

drop policy if exists "authenticated read own active file tokens" on public.file_download_tokens;
create policy "authenticated read own active file tokens"
on public.file_download_tokens for select
to authenticated
using (
  actor in (edoc_private.current_user_name(), edoc_private.current_user_email(), edoc_private.current_user_role())
  and revoked_at is null
  and expires_at > now()
);

drop policy if exists "authenticated insert own file tokens" on public.file_download_tokens;
create policy "authenticated insert own file tokens"
on public.file_download_tokens for insert
to authenticated
with check (
  actor in (edoc_private.current_user_name(), edoc_private.current_user_email(), edoc_private.current_user_role())
  or edoc_private.current_user_role() in ('主任', '執行長', '行政部主任', '總務')
);

drop policy if exists "authenticated read virus scan jobs by document scope" on public.virus_scan_jobs;
create policy "authenticated read virus scan jobs by document scope"
on public.virus_scan_jobs for select
to authenticated
using (
  document_id is null
  or exists (
    select 1
    from public.documents d
    where d.id = virus_scan_jobs.document_id
      and edoc_private.document_can_view(d.id, d.owner, d.department, d.direction, d.status, d.security_level)
  )
);

drop policy if exists "authenticated insert virus scan jobs" on public.virus_scan_jobs;
create policy "authenticated insert virus scan jobs"
on public.virus_scan_jobs for insert
to authenticated
with check (
  edoc_private.current_user_role() in ('主任', '執行長', '行政部主任', '總務')
  or edoc_private.has_permission('upload_attachment')
);

drop policy if exists "private bucket document scoped read" on storage.objects;
create policy "private bucket document scoped read"
on storage.objects for select
to authenticated
using (
  bucket_id = 'edoc-private'
  and exists (
    select 1
    from public.file_objects fo
    join public.documents d on d.id = fo.document_id
    where fo.bucket = storage.objects.bucket_id
      and fo.storage_key = storage.objects.name
      and fo.scan_status <> '已隔離'
      and edoc_private.document_can_view(d.id, d.owner, d.department, d.direction, d.status, d.security_level)
  )
);

drop policy if exists "private bucket authorized upload" on storage.objects;
create policy "private bucket authorized upload"
on storage.objects for insert
to authenticated
with check (
  bucket_id = 'edoc-private'
  and (
    edoc_private.current_user_role() in ('主任', '執行長', '行政部主任', '總務')
    or edoc_private.has_permission('upload_attachment')
  )
);

drop policy if exists "private bucket authorized replace" on storage.objects;
create policy "private bucket authorized replace"
on storage.objects for update
to authenticated
using (
  bucket_id = 'edoc-private'
  and (
    edoc_private.current_user_role() in ('主任', '執行長', '行政部主任', '總務')
    or edoc_private.has_permission('upload_attachment')
  )
)
with check (bucket_id = 'edoc-private');

create or replace function edoc_private.prevent_quarantined_file_download()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.scan_status = '已隔離' then
    new.signed_url_expires_at := null;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_file_objects_clear_signed_url_on_quarantine on public.file_objects;
create trigger trg_file_objects_clear_signed_url_on_quarantine
before update of scan_status on public.file_objects
for each row execute function edoc_private.prevent_quarantined_file_download();

insert into public.audit_logs (id, actor, action, target_type, target_id, detail)
values (
  'AUD-FILESEC-20260523-001',
  'Migration',
  '正式檔案儲存與病毒掃描服務',
  'storage',
  '202605230011_formal_file_storage_scanning',
  '已建立 private bucket、檔案加密 metadata、防毒掃描任務、短效下載 token 與隔離下載控制。'
)
on conflict (id) do nothing;
