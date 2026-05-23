create table if not exists public.signing_certificates (
  id text primary key,
  owner text not null,
  subject text not null,
  issuer text not null,
  serial_no text not null unique,
  algorithm text not null,
  valid_from timestamptz not null,
  valid_to timestamptz not null,
  status text not null default '啟用',
  fingerprint_sha256 text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.electronic_signatures (
  id text primary key,
  document_id text not null references public.documents(id) on delete cascade,
  pdf_version_id text references public.pdf_versions(id) on delete set null,
  file_object_id text references public.file_objects(id) on delete set null,
  certificate_id text not null references public.signing_certificates(id) on delete restrict,
  signer text not null,
  signature_type text not null check (signature_type in ('approval', 'seal', 'timestamp', 'package')),
  algorithm text not null,
  digest_sha256 text not null,
  signature_value text not null,
  tsa_token text not null,
  previous_signature_id text references public.electronic_signatures(id) on delete set null,
  non_repudiation_json jsonb,
  verified_at timestamptz,
  status text not null default '有效',
  created_at timestamptz not null default now()
);

create index if not exists idx_signing_certificates_serial on public.signing_certificates(serial_no);
create index if not exists idx_electronic_signatures_document on public.electronic_signatures(document_id);
create index if not exists idx_electronic_signatures_file on public.electronic_signatures(file_object_id);

alter table public.signing_certificates enable row level security;
alter table public.electronic_signatures enable row level security;

drop policy if exists "authenticated read signing certificates" on public.signing_certificates;
create policy "authenticated read signing certificates"
on public.signing_certificates for select
to authenticated
using (true);

drop policy if exists "authenticated read electronic signatures" on public.electronic_signatures;
create policy "authenticated read electronic signatures"
on public.electronic_signatures for select
to authenticated
using (true);

drop policy if exists "service role manages signing certificates" on public.signing_certificates;
create policy "service role manages signing certificates"
on public.signing_certificates for all
using (true)
with check (true);

drop policy if exists "service role manages electronic signatures" on public.electronic_signatures;
create policy "service role manages electronic signatures"
on public.electronic_signatures for all
using (true)
with check (true);
