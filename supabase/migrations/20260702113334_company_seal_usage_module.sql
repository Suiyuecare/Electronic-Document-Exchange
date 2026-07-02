-- Company seal and seal-usage management module.
-- Seal originals are high-sensitive assets: keep them in Seal Vault/private storage,
-- block direct browser access, and expose only backend-checked metadata/actions.

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
    'application/octet-stream',
    'image/png',
    'image/jpeg',
    'image/webp',
    'image/svg+xml'
  ]
)
on conflict (id) do update set
  public = false,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'edoc-seal-vault',
  'edoc-seal-vault',
  false,
  5242880,
  array[
    'image/png',
    'image/jpeg',
    'image/webp',
    'image/svg+xml'
  ]
)
on conflict (id) do update set
  public = false,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "seal vault objects backend only" on storage.objects;
create policy "seal vault objects backend only"
on storage.objects
as restrictive
for all
to anon, authenticated
using (
  not (
    bucket_id = 'edoc-seal-vault'
    or (
      bucket_id = 'edoc-private'
      and (name like 'seal-vault/%' or name like 'private/seals/%')
    )
  )
)
with check (
  not (
    bucket_id = 'edoc-seal-vault'
    or (
      bucket_id = 'edoc-private'
      and (name like 'seal-vault/%' or name like 'private/seals/%')
    )
  )
);

drop policy if exists "seal vault file objects backend only" on public.file_objects;
create policy "seal vault file objects backend only"
on public.file_objects
as restrictive
for all
to anon, authenticated
using (
  not (
    coalesce(document_id, '') = 'SEAL-VAULT'
    or coalesce(storage_provider, '') = 'seal-vault'
    or coalesce(purpose, '') like 'seal-vault%'
    or coalesce(storage_key, '') like 'seal-vault/%'
    or coalesce(storage_key, '') like 'private/seals/%'
  )
)
with check (
  not (
    coalesce(document_id, '') = 'SEAL-VAULT'
    or coalesce(storage_provider, '') = 'seal-vault'
    or coalesce(purpose, '') like 'seal-vault%'
    or coalesce(storage_key, '') like 'seal-vault/%'
    or coalesce(storage_key, '') like 'private/seals/%'
  )
);

create table if not exists public.companies (
  id text primary key,
  name text not null,
  tax_id text,
  status text not null default 'active',
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.seal_reference_options (
  id text primary key,
  option_type text not null,
  code text not null,
  name text not null,
  description text,
  sort_order integer not null default 0,
  status text not null default 'active',
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  unique(option_type, code)
);

create table if not exists public.company_seals (
  id text primary key,
  company_id text not null references public.companies(id) on delete restrict,
  seal_name text not null,
  seal_category text not null,
  seal_size_type text not null,
  purpose_description text,
  is_active boolean not null default true,
  created_by text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  deactivated_at text
);

create table if not exists public.company_seal_files (
  id text primary key,
  seal_id text not null references public.company_seals(id) on delete cascade,
  file_object_id text references public.file_objects(id) on delete set null,
  file_storage_key text not null,
  file_name text not null,
  file_mime_type text not null,
  file_size bigint not null,
  file_hash text not null,
  version integer not null default 1,
  is_current boolean not null default true,
  uploaded_by text,
  uploaded_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.seal_permissions (
  id text primary key,
  seal_id text not null references public.company_seals(id) on delete cascade,
  user_id text,
  role text not null,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.seal_usage_requests (
  id text primary key,
  document_id text not null references public.documents(id) on delete cascade,
  company_id text not null references public.companies(id) on delete restrict,
  seal_id text not null references public.company_seals(id) on delete restrict,
  requested_by text,
  request_reason text,
  usage_type text not null,
  status text not null default 'draft',
  stamp_positions_json text not null default '[]',
  stamped_pdf_version_id text references public.pdf_versions(id) on delete set null,
  metadata_json text not null default '{}',
  requested_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  approved_at text,
  stamped_at text,
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.seal_usage_approvals (
  id text primary key,
  usage_request_id text not null references public.seal_usage_requests(id) on delete cascade,
  approver_id text,
  approval_order integer not null default 1,
  status text not null default 'pending',
  comment text,
  approved_at text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.seal_usage_logs (
  id text primary key,
  usage_request_id text references public.seal_usage_requests(id) on delete set null,
  seal_id text references public.company_seals(id) on delete set null,
  document_id text references public.documents(id) on delete set null,
  action text not null,
  actor_id text,
  ip_address text,
  user_agent text,
  detail text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create index if not exists idx_companies_status on public.companies(status);
create index if not exists idx_seal_reference_options_type on public.seal_reference_options(option_type, status, sort_order);
create index if not exists idx_company_seals_company on public.company_seals(company_id, is_active);
create index if not exists idx_company_seals_category on public.company_seals(seal_category, seal_size_type);
create index if not exists idx_company_seal_files_seal on public.company_seal_files(seal_id, is_current);
create index if not exists idx_seal_permissions_seal on public.seal_permissions(seal_id, role);
create index if not exists idx_seal_usage_requests_document on public.seal_usage_requests(document_id);
create index if not exists idx_seal_usage_requests_status on public.seal_usage_requests(status);
create index if not exists idx_seal_usage_requests_company on public.seal_usage_requests(company_id);
create index if not exists idx_seal_usage_approvals_request on public.seal_usage_approvals(usage_request_id, approval_order);
create index if not exists idx_seal_usage_logs_request on public.seal_usage_logs(usage_request_id, created_at);

alter table public.companies enable row level security;
alter table public.seal_reference_options enable row level security;
alter table public.company_seals enable row level security;
alter table public.company_seal_files enable row level security;
alter table public.seal_permissions enable row level security;
alter table public.seal_usage_requests enable row level security;
alter table public.seal_usage_approvals enable row level security;
alter table public.seal_usage_logs enable row level security;

grant select, insert, update on
  public.companies,
  public.seal_reference_options,
  public.company_seals,
  public.company_seal_files,
  public.seal_permissions,
  public.seal_usage_requests,
  public.seal_usage_approvals,
  public.seal_usage_logs
to service_role;

grant select on public.companies, public.seal_reference_options, public.company_seals, public.seal_usage_requests, public.seal_usage_approvals, public.seal_usage_logs to authenticated;
grant insert, update on public.seal_usage_requests, public.seal_usage_approvals to authenticated;

drop policy if exists "deny anon companies" on public.companies;
create policy "deny anon companies" on public.companies for all to anon using (false) with check (false);
drop policy if exists "deny anon seal reference options" on public.seal_reference_options;
create policy "deny anon seal reference options" on public.seal_reference_options for all to anon using (false) with check (false);
drop policy if exists "deny anon company seals" on public.company_seals;
create policy "deny anon company seals" on public.company_seals for all to anon using (false) with check (false);
drop policy if exists "deny anon company seal files" on public.company_seal_files;
create policy "deny anon company seal files" on public.company_seal_files for all to anon using (false) with check (false);
drop policy if exists "deny anon seal permissions" on public.seal_permissions;
create policy "deny anon seal permissions" on public.seal_permissions for all to anon using (false) with check (false);
drop policy if exists "deny anon seal usage requests" on public.seal_usage_requests;
create policy "deny anon seal usage requests" on public.seal_usage_requests for all to anon using (false) with check (false);
drop policy if exists "deny anon seal usage approvals" on public.seal_usage_approvals;
create policy "deny anon seal usage approvals" on public.seal_usage_approvals for all to anon using (false) with check (false);
drop policy if exists "deny anon seal usage logs" on public.seal_usage_logs;
create policy "deny anon seal usage logs" on public.seal_usage_logs for all to anon using (false) with check (false);

drop policy if exists "authorized users read companies" on public.companies;
create policy "authorized users read companies"
on public.companies for select
to authenticated
using (edoc_private.has_permission('seals.manage') or edoc_private.has_permission('contracts.seal') or edoc_private.has_permission('official_documents.compose'));

drop policy if exists "authorized users read seal reference options" on public.seal_reference_options;
create policy "authorized users read seal reference options"
on public.seal_reference_options for select
to authenticated
using (status = 'active' and (edoc_private.has_permission('seals.manage') or edoc_private.has_permission('contracts.seal') or edoc_private.has_permission('official_documents.compose')));

drop policy if exists "authorized users read company seals" on public.company_seals;
create policy "authorized users read company seals"
on public.company_seals for select
to authenticated
using (edoc_private.has_permission('seals.manage') or edoc_private.has_permission('contracts.seal') or edoc_private.has_permission('official_documents.compose'));

drop policy if exists "seal admins manage company seals" on public.company_seals;
create policy "seal admins manage company seals"
on public.company_seals for all
to authenticated
using (edoc_private.has_permission('seals.manage'))
with check (edoc_private.has_permission('seals.manage'));

drop policy if exists "seal admins manage seal permissions" on public.seal_permissions;
create policy "seal admins manage seal permissions"
on public.seal_permissions for all
to authenticated
using (edoc_private.has_permission('seals.manage') or edoc_private.has_permission('system_permissions.manage'))
with check (edoc_private.has_permission('seals.manage') or edoc_private.has_permission('system_permissions.manage'));

drop policy if exists "backend only company seal files" on public.company_seal_files;
create policy "backend only company seal files"
on public.company_seal_files for all
to service_role
using (true)
with check (true);

drop policy if exists "authorized users read seal usage requests" on public.seal_usage_requests;
create policy "authorized users read seal usage requests"
on public.seal_usage_requests for select
to authenticated
using (
  edoc_private.has_permission('seals.manage')
  or edoc_private.has_permission('contracts.seal')
  or edoc_private.has_permission('official_documents.todo')
  or requested_by in (edoc_private.current_user_name(), edoc_private.current_user_email())
);

drop policy if exists "authorized users create seal usage requests" on public.seal_usage_requests;
create policy "authorized users create seal usage requests"
on public.seal_usage_requests for insert
to authenticated
with check (edoc_private.has_permission('seals.manage') or edoc_private.has_permission('contracts.seal') or edoc_private.has_permission('official_documents.compose'));

drop policy if exists "authorized users update seal usage requests" on public.seal_usage_requests;
create policy "authorized users update seal usage requests"
on public.seal_usage_requests for update
to authenticated
using (edoc_private.has_permission('seals.manage') or edoc_private.has_permission('contracts.seal') or edoc_private.has_permission('official_documents.todo'))
with check (edoc_private.has_permission('seals.manage') or edoc_private.has_permission('contracts.seal') or edoc_private.has_permission('official_documents.todo'));

drop policy if exists "authorized users read seal usage approvals" on public.seal_usage_approvals;
create policy "authorized users read seal usage approvals"
on public.seal_usage_approvals for select
to authenticated
using (
  edoc_private.has_permission('seals.manage')
  or edoc_private.has_permission('contracts.seal')
  or edoc_private.has_permission('official_documents.todo')
);

drop policy if exists "authorized approvers update seal usage approvals" on public.seal_usage_approvals;
create policy "authorized approvers update seal usage approvals"
on public.seal_usage_approvals for update
to authenticated
using (edoc_private.has_permission('seals.manage') or edoc_private.has_permission('contracts.seal') or edoc_private.has_permission('official_documents.todo'))
with check (edoc_private.has_permission('seals.manage') or edoc_private.has_permission('contracts.seal') or edoc_private.has_permission('official_documents.todo'));

drop policy if exists "authorized users read seal usage logs" on public.seal_usage_logs;
create policy "authorized users read seal usage logs"
on public.seal_usage_logs for select
to authenticated
using (edoc_private.has_permission('seals.manage') or edoc_private.has_permission('audit_logs.view'));

insert into public.seal_reference_options (id, option_type, code, name, description, sort_order)
values
  ('SREF-CAT-ESTABLISHMENT', 'category', 'establishment_seal', '公司設立印鑑', '公司設立、變更與重要公司登記文件使用。', 10),
  ('SREF-CAT-BANK', 'category', 'bank_seal', '銀行印鑑章', '銀行開戶、往來、授權與金融文件使用。', 20),
  ('SREF-CAT-GENERAL', 'category', 'general_seal', '便章', '一般行政、公文與合約例行用印。', 30),
  ('SREF-CAT-OTHER', 'category', 'other', '其他章', '使用者自訂章別。', 99),
  ('SREF-SIZE-LARGE', 'size', 'large_seal', '大章', '公司大章或單位章。', 10),
  ('SREF-SIZE-SMALL', 'size', 'small_seal', '小章', '負責人章、職章或小章。', 20),
  ('SREF-USAGE-OFFICIAL', 'usage_type', 'official_document', '公文', '電子公文發文、收文補正與附件用印。', 10),
  ('SREF-USAGE-CONTRACT', 'usage_type', 'contract', '合約', '電子合約用印。', 20),
  ('SREF-USAGE-BANK', 'usage_type', 'bank_document', '銀行文件', '銀行往來文件。', 30),
  ('SREF-USAGE-GOV', 'usage_type', 'government_application', '政府申請文件', '政府機關申請、登記與申報。', 40),
  ('SREF-USAGE-INTERNAL', 'usage_type', 'internal_document', '內部文件', '內部稽核、會議或行政文件。', 50),
  ('SREF-STATUS-DRAFT', 'request_status', 'draft', '草稿', '尚未送出。', 10),
  ('SREF-STATUS-PENDING', 'request_status', 'pending', '待簽核', '等待主管或權責人核准。', 20),
  ('SREF-STATUS-APPROVED', 'request_status', 'approved', '已核准', '可執行套印。', 30),
  ('SREF-STATUS-REJECTED', 'request_status', 'rejected', '已駁回', '不得用印。', 40),
  ('SREF-STATUS-STAMPED', 'request_status', 'stamped', '已用印', '已產出用印版本。', 50),
  ('SREF-STATUS-CANCELLED', 'request_status', 'cancelled', '已取消', '申請已取消。', 60),
  ('SREF-PERM-VIEWER', 'permission_role', 'viewer', '檢視者', '僅可查看授權紀錄。', 10),
  ('SREF-PERM-REQUESTER', 'permission_role', 'requester', '申請人', '可提出用印申請。', 20),
  ('SREF-PERM-APPROVER', 'permission_role', 'approver', '簽核者', '可核准或駁回用印申請。', 30),
  ('SREF-PERM-ADMIN', 'permission_role', 'seal_admin', '印章管理員', '可管理印章與版本。', 40)
on conflict (option_type, code) do update set
  name = excluded.name,
  description = excluded.description,
  sort_order = excluded.sort_order,
  status = 'active',
  updated_at = to_char(now(), 'YYYY-MM-DD HH24:MI:SS');

insert into public.companies (id, name, tax_id, status, created_at, updated_at)
select
  id,
  name,
  tax_id,
  case when status in ('啟用', 'active') then 'active' else 'inactive' end,
  created_at,
  updated_at
from public.company_registry
on conflict (id) do update set
  name = excluded.name,
  tax_id = excluded.tax_id,
  status = excluded.status,
  updated_at = excluded.updated_at;

with default_seals(label, category, size_type, purpose, sort_code) as (
  values
    ('公司設立印鑑－大章', 'establishment_seal', 'large_seal', '公司設立、變更登記、重大文件。', 'EST-L'),
    ('公司設立印鑑－小章', 'establishment_seal', 'small_seal', '公司設立、變更登記、負責人小章。', 'EST-S'),
    ('銀行印鑑章－大章', 'bank_seal', 'large_seal', '銀行往來與金融文件。', 'BANK-L'),
    ('銀行印鑑章－小章', 'bank_seal', 'small_seal', '銀行往來負責人小章。', 'BANK-S'),
    ('便章－大章', 'general_seal', 'large_seal', '一般公文、合約與行政文件。', 'GEN-L'),
    ('便章－小章', 'general_seal', 'small_seal', '一般公文、合約與行政文件小章。', 'GEN-S'),
    ('其他章', 'other', 'large_seal', '預留自訂章別。', 'OTHER')
)
insert into public.company_seals (
  id, company_id, seal_name, seal_category, seal_size_type, purpose_description,
  is_active, created_by, created_at, updated_at
)
select
  'CSEAL-' || c.id || '-' || d.sort_code,
  c.id,
  c.name || d.label,
  d.category,
  d.size_type,
  d.purpose,
  true,
  'Migration',
  to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
from public.companies c
cross join default_seals d
where c.status = 'active'
on conflict (id) do nothing;

insert into public.seal_permissions (id, seal_id, user_id, role, created_at)
select
  'SPERM-' || s.id || '-' || r.role,
  s.id,
  '',
  r.role,
  to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
from public.company_seals s
cross join (values ('viewer'), ('requester'), ('approver'), ('seal_admin')) as r(role)
on conflict (id) do nothing;

insert into public.audit_logs (id, actor, action, target_type, target_id, detail)
values (
  'AUD-COMPANY-SEAL-MODULE-20260702-001',
  'Migration',
  '公司印章與用印管理模組',
  'schema',
  '20260702113334_company_seal_usage_module',
  '已建立公司印章庫、印章版本、用印申請、簽核、用印紀錄、Seal Vault private bucket 與直連阻擋政策。'
)
on conflict (id) do nothing;
