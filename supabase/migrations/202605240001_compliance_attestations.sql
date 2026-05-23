create table if not exists public.compliance_attestations (
  id text primary key,
  attestation_type text not null,
  period text not null,
  signer_name text not null,
  signer_role text not null,
  reviewer_name text,
  reviewer_role text,
  status text not null,
  score integer not null default 0,
  report_hash text not null,
  report_json jsonb not null,
  signed_at timestamptz not null default now(),
  non_repudiation_json jsonb
);

create index if not exists idx_compliance_attestations_period on public.compliance_attestations(period);
create index if not exists idx_compliance_attestations_signed_at on public.compliance_attestations(signed_at desc);

alter table public.compliance_attestations enable row level security;

grant select, insert on public.compliance_attestations to authenticated;

drop policy if exists "authorized users read compliance attestations" on public.compliance_attestations;
create policy "authorized users read compliance attestations"
on public.compliance_attestations for select
to authenticated
using (true);

drop policy if exists "authorized users create compliance attestations" on public.compliance_attestations;
create policy "authorized users create compliance attestations"
on public.compliance_attestations for insert
to authenticated
with check (true);

insert into public.audit_logs (id, actor, action, target_type, target_id, detail)
values (
  'AUD-MIG-202605240001-COMPLIANCE-ATTEST',
  'migration',
  '法遵驗收與內控制度簽核資料表',
  'migration',
  '202605240001_compliance_attestations',
  '已建立 compliance_attestations，用於留存法遵驗收、內控制度簽核、報告雜湊與不可否認紀錄。'
)
on conflict (id) do nothing;
