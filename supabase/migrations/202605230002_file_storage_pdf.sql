create table if not exists public.file_objects (
  id text primary key,
  document_id text,
  file_name text not null,
  storage_key text not null unique,
  mime_type text not null,
  size_bytes bigint not null,
  sha256 text not null,
  version_label text not null,
  purpose text not null,
  created_by text not null,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.pdf_versions (
  id text primary key,
  document_id text not null,
  file_object_id text not null references public.file_objects(id) on delete cascade,
  version_type text not null check (version_type in ('before_seal', 'after_seal', 'application')),
  template_name text not null,
  stamp_no text,
  coordinates_json text,
  previous_version_id text,
  sha256 text not null,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.seal_applications (
  id text primary key,
  document_id text not null,
  seal_id text not null,
  applicant text not null,
  approver text,
  status text not null,
  reason text,
  stamp_no text,
  pdf_before_version_id text,
  pdf_after_version_id text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  approved_at text
);

create index if not exists idx_file_objects_document on public.file_objects(document_id);
create index if not exists idx_pdf_versions_document on public.pdf_versions(document_id);
create index if not exists idx_seal_applications_document on public.seal_applications(document_id);

alter table public.file_objects enable row level security;
alter table public.pdf_versions enable row level security;
alter table public.seal_applications enable row level security;

grant select, insert, update on public.file_objects, public.pdf_versions, public.seal_applications to authenticated;

drop policy if exists "authenticated read file objects" on public.file_objects;
create policy "authenticated read file objects" on public.file_objects
for select to authenticated using (true);

drop policy if exists "authenticated read pdf versions" on public.pdf_versions;
create policy "authenticated read pdf versions" on public.pdf_versions
for select to authenticated using (true);

drop policy if exists "authenticated read seal applications" on public.seal_applications;
create policy "authenticated read seal applications" on public.seal_applications
for select to authenticated using (true);

drop policy if exists "deny anon file objects" on public.file_objects;
create policy "deny anon file objects" on public.file_objects for all to anon using (false) with check (false);

drop policy if exists "deny anon pdf versions" on public.pdf_versions;
create policy "deny anon pdf versions" on public.pdf_versions for all to anon using (false) with check (false);

drop policy if exists "deny anon seal applications" on public.seal_applications;
create policy "deny anon seal applications" on public.seal_applications for all to anon using (false) with check (false);
