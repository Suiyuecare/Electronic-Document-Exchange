-- Official outgoing document workflow with Seal Vault backed auto-stamping.
-- File storage keys remain server-side metadata. Frontend download/preview must
-- call backend APIs so permission checks and audit logs run before file access.

create table if not exists public.official_documents (
  id text primary key,
  company_id text not null references public.companies(id) on delete restrict,
  document_type text not null,
  source_type text not null,
  title text not null,
  subject text,
  description text,
  method text,
  recipient text,
  dispatch_unit text,
  handler_name text,
  applicant_id text not null,
  applicant_name text,
  applicant_department_id text,
  applicant_department_name text,
  current_status text not null default 'draft',
  current_step text,
  request_reason text,
  metadata_json text not null default '{}',
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  constraint official_documents_source_type_check check (source_type in ('blank_editor', 'uploaded_pdf')),
  constraint official_documents_status_check check (
    current_status in (
      'draft',
      'pending_applicant_manager',
      'pending_department_head',
      'pending_admin_director',
      'pending_general_affairs',
      'pending_ceo',
      'approved',
      'stamping',
      'stamped',
      'returned_to_applicant',
      'rejected',
      'cancelled',
      'stamping_failed'
    )
  )
);

create table if not exists public.official_document_files (
  id text primary key,
  document_id text not null references public.official_documents(id) on delete cascade,
  file_object_id text references public.file_objects(id) on delete set null,
  file_type text not null,
  file_name text not null,
  file_storage_key text not null,
  file_mime_type text not null,
  file_size bigint not null default 0,
  file_hash text not null,
  version integer not null default 1,
  uploaded_by text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  constraint official_document_files_type_check check (file_type in ('original_pdf', 'generated_pdf', 'stamped_pdf', 'attachment'))
);

create table if not exists public.official_document_approval_steps (
  id text primary key,
  document_id text not null references public.official_documents(id) on delete cascade,
  step_order integer not null,
  step_key text not null,
  step_name text not null,
  approver_user_id text,
  approver_name text,
  approver_role text,
  status text not null default 'pending',
  comment text,
  approved_at text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  constraint official_document_approval_steps_status_check check (status in ('pending', 'approved', 'rejected', 'skipped')),
  unique(document_id, step_order),
  unique(document_id, step_key)
);

create table if not exists public.official_document_approval_logs (
  id text primary key,
  document_id text not null references public.official_documents(id) on delete cascade,
  step_id text references public.official_document_approval_steps(id) on delete set null,
  file_id text references public.official_document_files(id) on delete set null,
  actor_id text,
  actor_name text,
  action text not null,
  comment text,
  ip_address text,
  user_agent text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.official_document_stamp_requests (
  id text primary key,
  document_id text not null references public.official_documents(id) on delete cascade,
  company_id text not null references public.companies(id) on delete restrict,
  seal_id text not null references public.company_seals(id) on delete restrict,
  requested_by text not null,
  stamp_page integer not null default 1,
  stamp_x numeric not null default 420,
  stamp_y numeric not null default 130,
  stamp_width numeric not null default 85,
  stamp_height numeric not null default 85,
  status text not null default 'pending',
  stamped_file_id text references public.official_document_files(id) on delete set null,
  error_message text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  stamped_at text,
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  constraint official_document_stamp_requests_status_check check (status in ('pending', 'approved', 'stamping', 'stamped', 'failed'))
);

comment on table public.official_documents is 'Outgoing official document application header. PDF versions, stamped files, attachments, approvals, stamp requests, downloads, and audit logs hang under this application.';
comment on table public.official_document_files is 'Private document version and attachment metadata for an official document application. file_storage_key must never be exposed to frontend clients.';
comment on column public.official_document_files.file_storage_key is 'Private storage object key. Access only through backend APIs with audit logs.';
comment on table public.official_document_approval_logs is 'Application-level approval, stamping, download, and audit trail for official document applications.';
comment on table public.official_document_stamp_requests is 'Application-level approved workflow triggers backend-only Seal Vault read and stamped PDF generation.';

create index if not exists idx_official_documents_status on public.official_documents(current_status, current_step);
create index if not exists idx_official_documents_applicant on public.official_documents(applicant_id, created_at);
create index if not exists idx_official_documents_company on public.official_documents(company_id, created_at);
create index if not exists idx_official_document_files_document on public.official_document_files(document_id, file_type, version);
create index if not exists idx_official_document_steps_document on public.official_document_approval_steps(document_id, step_order);
create index if not exists idx_official_document_steps_approver on public.official_document_approval_steps(approver_user_id, status);
create index if not exists idx_official_document_logs_document on public.official_document_approval_logs(document_id, created_at);
create index if not exists idx_official_document_stamp_requests_document on public.official_document_stamp_requests(document_id);
create index if not exists idx_official_document_stamp_requests_status on public.official_document_stamp_requests(status, created_at);

alter table public.official_documents enable row level security;
alter table public.official_document_files enable row level security;
alter table public.official_document_approval_steps enable row level security;
alter table public.official_document_approval_logs enable row level security;
alter table public.official_document_stamp_requests enable row level security;

grant select, insert, update on
  public.official_documents,
  public.official_document_files,
  public.official_document_approval_steps,
  public.official_document_approval_logs,
  public.official_document_stamp_requests
to service_role;

grant select on
  public.official_documents,
  public.official_document_approval_steps,
  public.official_document_stamp_requests
to authenticated;

drop policy if exists "deny anon official documents" on public.official_documents;
create policy "deny anon official documents" on public.official_documents for all to anon using (false) with check (false);
drop policy if exists "deny anon official document files" on public.official_document_files;
create policy "deny anon official document files" on public.official_document_files for all to anon using (false) with check (false);
drop policy if exists "deny anon official document steps" on public.official_document_approval_steps;
create policy "deny anon official document steps" on public.official_document_approval_steps for all to anon using (false) with check (false);
drop policy if exists "deny anon official document logs" on public.official_document_approval_logs;
create policy "deny anon official document logs" on public.official_document_approval_logs for all to anon using (false) with check (false);
drop policy if exists "deny anon official document stamp requests" on public.official_document_stamp_requests;
create policy "deny anon official document stamp requests" on public.official_document_stamp_requests for all to anon using (false) with check (false);

drop policy if exists "service role manages official documents" on public.official_documents;
create policy "service role manages official documents" on public.official_documents for all to service_role using (true) with check (true);
drop policy if exists "service role manages official document files" on public.official_document_files;
create policy "service role manages official document files" on public.official_document_files for all to service_role using (true) with check (true);
drop policy if exists "service role manages official document steps" on public.official_document_approval_steps;
create policy "service role manages official document steps" on public.official_document_approval_steps for all to service_role using (true) with check (true);
drop policy if exists "service role manages official document logs" on public.official_document_approval_logs;
create policy "service role manages official document logs" on public.official_document_approval_logs for all to service_role using (true) with check (true);
drop policy if exists "service role manages official document stamp requests" on public.official_document_stamp_requests;
create policy "service role manages official document stamp requests" on public.official_document_stamp_requests for all to service_role using (true) with check (true);

drop policy if exists "participants read official documents" on public.official_documents;
create policy "participants read official documents"
on public.official_documents for select
to authenticated
using (
  edoc_private.has_permission('official_documents.all_records')
  or edoc_private.has_permission('official_documents.all_todo')
  or exists (
    select 1
    from public.users u
    where u.auth_user_id = auth.uid()
      and u.status = '啟用'
      and u.id = official_documents.applicant_id
  )
  or exists (
    select 1
    from public.official_document_approval_steps s
    join public.users u on u.auth_user_id = auth.uid() and u.status = '啟用'
    where s.document_id = official_documents.id
      and s.approver_user_id = u.id
  )
);

drop policy if exists "participants read official document steps" on public.official_document_approval_steps;
create policy "participants read official document steps"
on public.official_document_approval_steps for select
to authenticated
using (
  edoc_private.has_permission('official_documents.all_records')
  or edoc_private.has_permission('official_documents.all_todo')
  or exists (
    select 1
    from public.official_documents d
    join public.users u on u.auth_user_id = auth.uid() and u.status = '啟用'
    where d.id = official_document_approval_steps.document_id
      and (d.applicant_id = u.id or official_document_approval_steps.approver_user_id = u.id)
  )
);

drop policy if exists "participants read official stamp requests" on public.official_document_stamp_requests;
create policy "participants read official stamp requests"
on public.official_document_stamp_requests for select
to authenticated
using (
  edoc_private.has_permission('official_documents.all_records')
  or edoc_private.has_permission('official_documents.all_todo')
  or exists (
    select 1
    from public.official_documents d
    join public.users u on u.auth_user_id = auth.uid() and u.status = '啟用'
    left join public.official_document_approval_steps s on s.document_id = d.id and s.approver_user_id = u.id
    where d.id = official_document_stamp_requests.document_id
      and (d.applicant_id = u.id or s.id is not null)
  )
);

drop policy if exists "backend only official document files" on public.official_document_files;
create policy "backend only official document files"
on public.official_document_files for all
to authenticated
using (false)
with check (false);

drop policy if exists "backend only official document logs" on public.official_document_approval_logs;
create policy "backend only official document logs"
on public.official_document_approval_logs for all
to authenticated
using (false)
with check (false);

insert into public.seal_reference_options (id, option_type, code, name, description, sort_order)
values
  ('SREF-ODOC-TYPE-OUTGOING', 'official_document_type', 'outgoing_official_document', '發文公文', '空白公文撰寫後送簽用印。', 10),
  ('SREF-ODOC-TYPE-UPLOAD', 'official_document_type', 'uploaded_pdf_for_stamp', '上傳 PDF 用印', '既有 PDF 上傳後送簽用印。', 20),
  ('SREF-ODOC-SOURCE-BLANK', 'official_source_type', 'blank_editor', '空白公文撰寫', '由系統產生公文 PDF。', 10),
  ('SREF-ODOC-SOURCE-UPLOAD', 'official_source_type', 'uploaded_pdf', '上傳既有 PDF', '核准後在上傳 PDF 產生已用印版本。', 20),
  ('SREF-ODOC-STATUS-DRAFT', 'official_document_status', 'draft', '草稿', '尚未送出。', 10),
  ('SREF-ODOC-STATUS-PAM', 'official_document_status', 'pending_applicant_manager', '等待申請人主管簽核', '第一關簽核。', 20),
  ('SREF-ODOC-STATUS-PDH', 'official_document_status', 'pending_department_head', '等待部門主管簽核', '第二關簽核。', 30),
  ('SREF-ODOC-STATUS-PAD', 'official_document_status', 'pending_admin_director', '等待行政部門主任簽核', '第三關簽核。', 40),
  ('SREF-ODOC-STATUS-PGA', 'official_document_status', 'pending_general_affairs', '等待總務簽核', '第四關簽核。', 50),
  ('SREF-ODOC-STATUS-CEO', 'official_document_status', 'pending_ceo', '等待執行長簽核', '第五關簽核。', 60),
  ('SREF-ODOC-STATUS-APPROVED', 'official_document_status', 'approved', '已全部核准', '準備進入自動用印。', 70),
  ('SREF-ODOC-STATUS-STAMPING', 'official_document_status', 'stamping', '系統用印中', '後端正在讀取 private storage 並產出已用印 PDF。', 80),
  ('SREF-ODOC-STATUS-STAMPED', 'official_document_status', 'stamped', '已完成用印', '申請人已確認或流程結束。', 90),
  ('SREF-ODOC-STATUS-RETURNED', 'official_document_status', 'returned_to_applicant', '已回到申請人', '已用印 PDF 可由申請人確認與下載。', 100),
  ('SREF-ODOC-STATUS-REJECTED', 'official_document_status', 'rejected', '已駁回', '任一關駁回後回到申請人。', 110),
  ('SREF-ODOC-STATUS-CANCELLED', 'official_document_status', 'cancelled', '已取消', '申請人取消。', 120),
  ('SREF-ODOC-STATUS-STAMPING-FAILED', 'official_document_status', 'stamping_failed', '自動用印失敗', '需通知總務與系統管理員。', 130),
  ('SREF-ODOC-STEP-AM', 'official_workflow_step', 'applicant_manager', '申請人主管', '申請人主管簽核。', 10),
  ('SREF-ODOC-STEP-DH', 'official_workflow_step', 'department_head', '部門主管', '部門主管簽核。', 20),
  ('SREF-ODOC-STEP-AD', 'official_workflow_step', 'admin_director', '行政部門主任', '行政部門主任簽核。', 30),
  ('SREF-ODOC-STEP-GA', 'official_workflow_step', 'general_affairs', '總務', '總務簽核。', 40),
  ('SREF-ODOC-STEP-CEO', 'official_workflow_step', 'ceo', '執行長', '執行長核准後觸發自動用印。', 50),
  ('SREF-ODOC-STEP-AC', 'official_workflow_step', 'applicant_confirm', '申請人確認', '已用印版本回到申請人確認。', 60)
on conflict (option_type, code) do update set
  name = excluded.name,
  description = excluded.description,
  sort_order = excluded.sort_order,
  status = 'active',
  updated_at = to_char(now(), 'YYYY-MM-DD HH24:MI:SS');
