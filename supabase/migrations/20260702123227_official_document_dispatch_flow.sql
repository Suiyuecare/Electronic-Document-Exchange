-- Extend official document workflow from approval + stamping to dispatch + archive.
-- Dispatch proof files are private official_document_files rows and must be
-- downloaded through backend APIs so permission checks and audit logs run.

alter table public.official_documents
  add column if not exists dispatch_method text not null default 'electronic_official_document_by_general_affairs';

alter table public.official_documents
  drop constraint if exists official_documents_status_check;

alter table public.official_documents
  add constraint official_documents_status_check check (
    current_status in (
      'draft',
      'pending_applicant_manager',
      'pending_department_head',
      'pending_admin_director',
      'pending_general_affairs_review',
      'pending_ceo',
      'approved',
      'stamping',
      'stamped',
      'pending_general_affairs_dispatch',
      'returned_to_applicant_for_send',
      'dispatched',
      'sent_by_applicant',
      'closed',
      'rejected',
      'cancelled',
      'stamping_failed'
    )
  );

alter table public.official_documents
  drop constraint if exists official_documents_dispatch_method_check;

alter table public.official_documents
  add constraint official_documents_dispatch_method_check check (
    dispatch_method in (
      'electronic_official_document_by_general_affairs',
      'return_to_applicant_for_manual_send',
      'email_by_general_affairs',
      'physical_mail_by_general_affairs',
      'no_dispatch_required'
    )
  );

alter table public.official_document_files
  drop constraint if exists official_document_files_type_check;

alter table public.official_document_files
  add constraint official_document_files_type_check check (
    file_type in ('original_pdf', 'generated_pdf', 'stamped_pdf', 'attachment', 'dispatch_proof')
  );

create table if not exists public.official_document_dispatch_records (
  id text primary key,
  document_id text not null references public.official_documents(id) on delete cascade,
  dispatch_method text not null,
  dispatch_owner_type text not null,
  dispatch_owner_user_id text,
  dispatch_status text not null default 'pending',
  external_official_document_number text,
  dispatch_date text,
  recipient text,
  recipient_contact text,
  dispatch_note text,
  proof_file_id text references public.official_document_files(id) on delete set null,
  created_by text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  completed_at text,
  constraint official_document_dispatch_records_method_check check (
    dispatch_method in (
      'electronic_official_document_by_general_affairs',
      'return_to_applicant_for_manual_send',
      'email_by_general_affairs',
      'physical_mail_by_general_affairs',
      'no_dispatch_required'
    )
  ),
  constraint official_document_dispatch_records_owner_check check (
    dispatch_owner_type in ('general_affairs', 'applicant', 'system')
  ),
  constraint official_document_dispatch_records_status_check check (
    dispatch_status in ('pending', 'dispatched', 'sent_by_applicant', 'failed', 'cancelled')
  )
);

comment on column public.official_documents.dispatch_method is 'Dispatch routing selected on the official document application before approval.';
comment on table public.official_document_dispatch_records is 'Application-level dispatch task/record after auto-stamping. Proof files remain private official_document_files rows.';
comment on column public.official_document_dispatch_records.proof_file_id is 'Private proof attachment metadata row, such as external eDoc screenshot, email proof, or postal receipt.';

create index if not exists idx_official_dispatch_records_document
  on public.official_document_dispatch_records(document_id, dispatch_status);

create index if not exists idx_official_dispatch_records_owner
  on public.official_document_dispatch_records(dispatch_owner_user_id, dispatch_status);

alter table public.official_document_dispatch_records enable row level security;

grant select, insert, update on public.official_document_dispatch_records to service_role;
grant select on public.official_document_dispatch_records to authenticated;

drop policy if exists "deny anon official document dispatch records" on public.official_document_dispatch_records;
create policy "deny anon official document dispatch records"
on public.official_document_dispatch_records for all
to anon
using (false)
with check (false);

drop policy if exists "service role manages official document dispatch records" on public.official_document_dispatch_records;
create policy "service role manages official document dispatch records"
on public.official_document_dispatch_records for all
to service_role
using (true)
with check (true);

drop policy if exists "participants read official document dispatch records" on public.official_document_dispatch_records;
create policy "participants read official document dispatch records"
on public.official_document_dispatch_records for select
to authenticated
using (
  edoc_private.has_permission('official_documents.all_records')
  or edoc_private.has_permission('official_documents.all_todo')
  or exists (
    select 1
    from public.official_documents d
    join public.users u on u.auth_user_id = auth.uid() and u.status = '啟用'
    left join public.official_document_approval_steps s on s.document_id = d.id and s.approver_user_id = u.id
    where d.id = official_document_dispatch_records.document_id
      and (
        d.applicant_id = u.id
        or s.id is not null
        or official_document_dispatch_records.dispatch_owner_user_id = u.id
        or (official_document_dispatch_records.dispatch_owner_type = 'general_affairs' and u.role = '總務')
      )
  )
);

update public.seal_reference_options
set status = 'inactive',
    updated_at = to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
where option_type in ('official_document_status', 'official_workflow_step')
  and code in ('pending_general_affairs', 'returned_to_applicant', 'applicant_confirm', 'general_affairs');

insert into public.seal_reference_options (id, option_type, code, name, description, sort_order)
values
  ('SREF-ODOC-STATUS-PGA-REVIEW', 'official_document_status', 'pending_general_affairs_review', '等待總務審核', '總務確認用印、附件、寄發方式與公文格式。', 50),
  ('SREF-ODOC-STATUS-PGA-DISPATCH', 'official_document_status', 'pending_general_affairs_dispatch', '等待總務寄發', '已用印，待總務完成電子公文、Email 或紙本寄發。', 95),
  ('SREF-ODOC-STATUS-RETURN-APPLICANT-SEND', 'official_document_status', 'returned_to_applicant_for_send', '回申請人自行寄發', '已用印，待申請人自行寄信或交付並回填紀錄。', 100),
  ('SREF-ODOC-STATUS-DISPATCHED', 'official_document_status', 'dispatched', '已由總務正式發文', '總務已完成寄發並回填發文資訊。', 105),
  ('SREF-ODOC-STATUS-SENT-BY-APPLICANT', 'official_document_status', 'sent_by_applicant', '已由申請人自行寄出', '申請人已完成寄送並回填紀錄。', 108),
  ('SREF-ODOC-STATUS-CLOSED', 'official_document_status', 'closed', '已結案歸檔', '發文、用印、寄發與留存已完成。', 109),
  ('SREF-ODOC-STEP-GA-REVIEW', 'official_workflow_step', 'general_affairs_review', '總務審核', '執行長前的總務審核，不等同用印後寄發任務。', 40),
  ('SREF-ODOC-DISPATCH-EGOV-GA', 'official_dispatch_method', 'electronic_official_document_by_general_affairs', '由總務透過電子公文系統正式發文', '自動用印後建立總務寄發任務。', 10),
  ('SREF-ODOC-DISPATCH-APPLICANT', 'official_dispatch_method', 'return_to_applicant_for_manual_send', '回申請人自行寄發', '自動用印後回到申請人自行寄信或交付。', 20),
  ('SREF-ODOC-DISPATCH-EMAIL-GA', 'official_dispatch_method', 'email_by_general_affairs', '由總務以 Email 寄出', '自動用印後建立總務 Email 寄發任務。', 30),
  ('SREF-ODOC-DISPATCH-MAIL-GA', 'official_dispatch_method', 'physical_mail_by_general_affairs', '由總務紙本郵寄', '自動用印後建立總務紙本郵寄任務。', 40),
  ('SREF-ODOC-DISPATCH-NONE', 'official_dispatch_method', 'no_dispatch_required', '僅用印歸檔，不需要寄發', '自動用印後直接結案歸檔。', 50)
on conflict (option_type, code) do update set
  name = excluded.name,
  description = excluded.description,
  sort_order = excluded.sort_order,
  status = 'active',
  updated_at = to_char(now(), 'YYYY-MM-DD HH24:MI:SS');
