-- Finance-style PDF seal workflow for uploaded official documents and contracts.
-- Stores locked source PDF hashes, multi-page stamp positions, actor snapshots,
-- and applicant return notifications without embedding production credentials.

create table if not exists public.approval_step_actor_snapshots (
  id text primary key,
  workflow_task_id text,
  seal_application_id text,
  source_type text not null default 'seal_application',
  source_id text not null,
  step_no integer not null default 1,
  step_name text not null,
  approver_role text not null,
  approver_user_id text,
  approver_name text,
  approver_email text,
  status text not null default '待簽核',
  comment text,
  acted_at text,
  snapshot_json jsonb not null default '{}'::jsonb,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

alter table public.seal_applications add column if not exists application_type text not null default 'official_document';
alter table public.seal_applications add column if not exists company_name text not null default '歲悅股份有限公司';
alter table public.seal_applications add column if not exists department text;
alter table public.seal_applications add column if not exists title text;
alter table public.seal_applications add column if not exists source_pdf_file_object_id text;
alter table public.seal_applications add column if not exists source_pdf_sha256 text;
alter table public.seal_applications add column if not exists source_pdf_name text;
alter table public.seal_applications add column if not exists locked_pdf_sha256 text;
alter table public.seal_applications add column if not exists locked_positions_sha256 text;
alter table public.seal_applications add column if not exists stamp_positions_json jsonb not null default '[]'::jsonb;
alter table public.seal_applications add column if not exists approval_route_code text;
alter table public.seal_applications add column if not exists approval_route_name text;
alter table public.seal_applications add column if not exists approval_snapshot_json jsonb not null default '{}'::jsonb;
alter table public.seal_applications add column if not exists current_step_no integer not null default 1;
alter table public.seal_applications add column if not exists current_step_name text;
alter table public.seal_applications add column if not exists current_approver_role text;
alter table public.seal_applications add column if not exists applicant_user_id text;
alter table public.seal_applications add column if not exists applicant_name text;
alter table public.seal_applications add column if not exists applicant_email text;
alter table public.seal_applications add column if not exists reject_reason text;
alter table public.seal_applications add column if not exists returned_at text;
alter table public.seal_applications add column if not exists completed_at text;
alter table public.seal_applications add column if not exists notification_id text;

create index if not exists idx_approval_actor_snapshots_source
  on public.approval_step_actor_snapshots(source_type, source_id);
create index if not exists idx_approval_actor_snapshots_status
  on public.approval_step_actor_snapshots(approver_role, status);
create index if not exists idx_seal_applications_type_status
  on public.seal_applications(application_type, status);
create index if not exists idx_seal_applications_current_approver
  on public.seal_applications(current_approver_role, status);

alter table public.approval_step_actor_snapshots enable row level security;

grant select, insert, update on public.approval_step_actor_snapshots to authenticated;

drop policy if exists "authorized users read approval actor snapshots" on public.approval_step_actor_snapshots;
create policy "authorized users read approval actor snapshots"
on public.approval_step_actor_snapshots for select
to authenticated
using (
  auth.role() = 'service_role'
  or coalesce(auth.jwt() -> 'app_metadata' ->> 'edoc_role', '') in ('行政部主任','總務','執行長','會計','主管')
);

drop policy if exists "authorized users manage approval actor snapshots" on public.approval_step_actor_snapshots;
create policy "authorized users manage approval actor snapshots"
on public.approval_step_actor_snapshots for all
to authenticated
using (
  auth.role() = 'service_role'
  or coalesce(auth.jwt() -> 'app_metadata' ->> 'edoc_role', '') in ('行政部主任','總務','執行長')
)
with check (
  auth.role() = 'service_role'
  or coalesce(auth.jwt() -> 'app_metadata' ->> 'edoc_role', '') in ('行政部主任','總務','執行長')
);

insert into public.company_registry (id, name, tax_id, status, created_at, updated_at)
values
  ('CO-001', '歲悅股份有限公司', '60792234', '啟用', to_char(now(), 'YYYY-MM-DD HH24:MI:SS'), to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
  ('CO-002', '樂齡歲悅股份有限公司', '60541552', '啟用', to_char(now(), 'YYYY-MM-DD HH24:MI:SS'), to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
  ('CO-003', '移站式股份有限公司', '待設定', '啟用', to_char(now(), 'YYYY-MM-DD HH24:MI:SS'), to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
  ('CO-004', '大齡好好投資有限公司', '待設定', '啟用', to_char(now(), 'YYYY-MM-DD HH24:MI:SS'), to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
  ('CO-005', '歲悅股份有限公司附設臺北市私立歲悅居家長照機構', '00602175', '啟用', to_char(now(), 'YYYY-MM-DD HH24:MI:SS'), to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
  ('CO-006', '樂齡歲悅股份有限公司附設臺北市私立歲悅萬華社區長照機構', '00667423', '啟用', to_char(now(), 'YYYY-MM-DD HH24:MI:SS'), to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
  ('CO-007', '愛無限整合服務有限公司', '90691342', '啟用', to_char(now(), 'YYYY-MM-DD HH24:MI:SS'), to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
  ('CO-008', '愛無限整合有限公司附設新北市私立愛無限居家長照機構', '91254360', '啟用', to_char(now(), 'YYYY-MM-DD HH24:MI:SS'), to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
on conflict (id) do update
set name = excluded.name,
    tax_id = excluded.tax_id,
    status = excluded.status,
    updated_at = excluded.updated_at;
