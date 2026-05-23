alter table public.signing_certificates
  add column if not exists certificate_type text not null default 'organization',
  add column if not exists key_usage text,
  add column if not exists extended_key_usage text,
  add column if not exists chain_status text not null default '待驗證',
  add column if not exists ocsp_status text not null default '待查詢',
  add column if not exists crl_status text not null default '待查詢',
  add column if not exists tsa_url text,
  add column if not exists ocsp_url text,
  add column if not exists crl_url text,
  add column if not exists root_ca_fingerprint text,
  add column if not exists last_validated_at timestamptz,
  add column if not exists validation_report_json jsonb;

alter table public.electronic_signatures
  add column if not exists certificate_validation_id text,
  add column if not exists tsa_status text not null default '待驗證',
  add column if not exists ocsp_status text not null default '待查詢',
  add column if not exists crl_status text not null default '待查詢',
  add column if not exists chain_status text not null default '待驗證';

create table if not exists public.certificate_authorities (
  id text primary key,
  name text not null,
  ca_type text not null check (ca_type in ('natural_person', 'business', 'organization', 'tsa')),
  subject text not null,
  issuer text not null,
  fingerprint_sha256 text not null,
  valid_from timestamptz not null,
  valid_to timestamptz not null,
  trust_status text not null default 'trusted' check (trust_status in ('trusted', 'blocked', 'expired')),
  ocsp_url text,
  crl_url text,
  created_at timestamptz not null default now()
);

create table if not exists public.certificate_validation_events (
  id text primary key,
  certificate_id text not null references public.signing_certificates(id) on delete cascade,
  signature_id text references public.electronic_signatures(id) on delete set null,
  validator text not null,
  validation_type text not null,
  chain_status text not null,
  ocsp_status text not null,
  crl_status text not null,
  tsa_status text not null,
  result text not null check (result in ('通過', '不通過')),
  report_json jsonb,
  checked_at timestamptz not null default now()
);

create table if not exists public.tsa_timestamp_tokens (
  id text primary key,
  signature_id text not null references public.electronic_signatures(id) on delete cascade,
  tsa_name text not null,
  tsa_url text,
  imprint_sha256 text not null,
  token_value text not null,
  policy_oid text,
  status text not null,
  issued_at timestamptz not null,
  verified_at timestamptz
);

create index if not exists idx_certificate_validation_events_certificate on public.certificate_validation_events(certificate_id);
create index if not exists idx_certificate_validation_events_signature on public.certificate_validation_events(signature_id);
create index if not exists idx_tsa_timestamp_tokens_signature on public.tsa_timestamp_tokens(signature_id);

alter table public.certificate_authorities enable row level security;
alter table public.certificate_validation_events enable row level security;
alter table public.tsa_timestamp_tokens enable row level security;

grant select on public.certificate_authorities to authenticated;
grant select, insert on public.certificate_validation_events to authenticated;
grant select on public.tsa_timestamp_tokens to authenticated;

drop policy if exists "authenticated read trusted certificate authorities" on public.certificate_authorities;
create policy "authenticated read trusted certificate authorities"
on public.certificate_authorities for select
to authenticated
using (trust_status = 'trusted');

drop policy if exists "certificate admins manage authorities" on public.certificate_authorities;
create policy "certificate admins manage authorities"
on public.certificate_authorities for all
to authenticated
using (edoc_private.current_user_role() in ('主任', '執行長', '行政部主任'))
with check (edoc_private.current_user_role() in ('主任', '執行長', '行政部主任'));

drop policy if exists "authorized users read certificate validation events" on public.certificate_validation_events;
create policy "authorized users read certificate validation events"
on public.certificate_validation_events for select
to authenticated
using (
  edoc_private.current_user_role() in ('主任', '執行長', '行政部主任', '總務', '稽核人員')
  or exists (
    select 1
    from public.electronic_signatures es
    join public.documents d on d.id = es.document_id
    where es.id = certificate_validation_events.signature_id
      and edoc_private.document_can_view(d.id, d.owner, d.department, d.direction, d.status, d.security_level)
  )
);

drop policy if exists "authorized users create certificate validation events" on public.certificate_validation_events;
create policy "authorized users create certificate validation events"
on public.certificate_validation_events for insert
to authenticated
with check (edoc_private.current_user_role() in ('主任', '執行長', '行政部主任', '總務'));

drop policy if exists "authorized users read tsa tokens by signature scope" on public.tsa_timestamp_tokens;
create policy "authorized users read tsa tokens by signature scope"
on public.tsa_timestamp_tokens for select
to authenticated
using (
  exists (
    select 1
    from public.electronic_signatures es
    join public.documents d on d.id = es.document_id
    where es.id = tsa_timestamp_tokens.signature_id
      and edoc_private.document_can_view(d.id, d.owner, d.department, d.direction, d.status, d.security_level)
  )
);

insert into public.certificate_authorities (
  id, name, ca_type, subject, issuer, fingerprint_sha256, valid_from, valid_to, trust_status, ocsp_url, crl_url
) values
  ('CA-SYC-ROOT-001', 'Suiyuecare Internal Root CA', 'organization', 'CN=Suiyuecare Internal Root CA,O=Suiyuecare', 'CN=Suiyuecare Internal Root CA,O=Suiyuecare', 'SHA256-SYC-ROOT-001', '2026-01-01', '2036-12-31', 'trusted', 'https://ocsp.suiyuecare.local', 'https://crl.suiyuecare.local/root.crl'),
  ('CA-SYC-TSA-001', 'Suiyuecare TSA CA', 'tsa', 'CN=Suiyuecare TSA CA,O=Suiyuecare', 'CN=Suiyuecare Internal Root CA,O=Suiyuecare', 'SHA256-SYC-TSA-001', '2026-01-01', '2036-12-31', 'trusted', 'https://ocsp.suiyuecare.local', 'https://crl.suiyuecare.local/tsa.crl')
on conflict (id) do nothing;

update public.signing_certificates
set certificate_type = case
    when owner = '系統時間戳' then 'tsa'
    when owner = '總務' then 'business'
    else 'organization'
  end,
  key_usage = coalesce(key_usage, 'digitalSignature,nonRepudiation'),
  extended_key_usage = coalesce(extended_key_usage, 'documentSigning,clientAuth'),
  ocsp_url = coalesce(ocsp_url, 'https://ocsp.suiyuecare.local'),
  crl_url = coalesce(crl_url, 'https://crl.suiyuecare.local/root.crl'),
  tsa_url = coalesce(tsa_url, 'https://tsa.suiyuecare.local/rfc3161'),
  root_ca_fingerprint = coalesce(root_ca_fingerprint, 'SHA256-SYC-ROOT-001');
