-- Production forward migration: indexes for confirmed eDoc foreign-key gaps.
--
-- Supabase Performance Advisor reported these relationships on 2026-08-27.
-- Every statement is additive and idempotent. This migration deliberately does
-- not touch shared CMS tables and does not remove any "unused" indexes.

create index if not exists idx_inbound_attachments_file_object
  on public.inbound_document_attachments(file_object_id);
create index if not exists idx_internal_dispatches_official_document
  on public.internal_dispatches(official_document_id);
create index if not exists idx_internal_dispatch_replies_recipient
  on public.internal_dispatch_replies(recipient_id);
create index if not exists idx_internal_dispatch_replies_attachment
  on public.internal_dispatch_replies(attachment_file_id);
create index if not exists idx_official_archive_exports_requested_by
  on public.official_document_archive_exports(requested_by);
create index if not exists idx_official_stamp_positions_seal
  on public.official_document_stamp_positions(seal_id);
create index if not exists idx_official_rejection_jobs_expected_step
  on public.official_document_rejection_jobs(expected_step_id);
create index if not exists idx_official_rejection_jobs_source_revision
  on public.official_document_rejection_jobs(source_revision_id);
create index if not exists idx_official_rejection_jobs_target_revision
  on public.official_document_rejection_jobs(target_revision_id)
  where target_revision_id is not null;

create index if not exists idx_auth_sessions_user_fk
  on public.auth_sessions(user_id);
create index if not exists idx_login_events_user_fk
  on public.login_events(user_id);
create index if not exists idx_document_retention_events_policy_fk
  on public.document_retention_events(policy_code);
create index if not exists idx_electronic_signatures_pdf_version_fk
  on public.electronic_signatures(pdf_version_id);
create index if not exists idx_electronic_signatures_certificate_fk
  on public.electronic_signatures(certificate_id);
create index if not exists idx_electronic_signatures_previous_fk
  on public.electronic_signatures(previous_signature_id)
  where previous_signature_id is not null;
create index if not exists idx_exchange_attachment_document_fk
  on public.exchange_attachment(document_id);
create index if not exists idx_exchange_events_task_fk
  on public.exchange_events(task_id);
create index if not exists idx_file_access_logs_file_object_fk
  on public.file_access_logs(file_object_id);
create index if not exists idx_file_access_logs_document_fk
  on public.file_access_logs(document_id);
create index if not exists idx_official_approval_logs_step_fk
  on public.official_document_approval_logs(step_id)
  where step_id is not null;
create index if not exists idx_official_approval_logs_file_fk
  on public.official_document_approval_logs(file_id)
  where file_id is not null;
create index if not exists idx_official_dispatch_records_proof_file_fk
  on public.official_document_dispatch_records(proof_file_id)
  where proof_file_id is not null;
create index if not exists idx_official_document_files_file_object_fk
  on public.official_document_files(file_object_id)
  where file_object_id is not null;
create index if not exists idx_official_stamp_requests_company_fk
  on public.official_document_stamp_requests(company_id);
create index if not exists idx_official_stamp_requests_seal_fk
  on public.official_document_stamp_requests(seal_id);
create index if not exists idx_official_stamp_requests_stamped_file_fk
  on public.official_document_stamp_requests(stamped_file_id)
  where stamped_file_id is not null;
create index if not exists idx_official_documents_stamped_file_fk
  on public.official_documents(stamped_file_id)
  where stamped_file_id is not null;
create index if not exists idx_official_workflow_delegations_created_by
  on public.official_workflow_delegations(created_by);
create index if not exists idx_official_workflow_delegations_delegate
  on public.official_workflow_delegations(delegate_user_id);
create index if not exists idx_official_workflow_delegations_principal
  on public.official_workflow_delegations(principal_user_id);
create index if not exists idx_official_workflow_delegations_revoked_by
  on public.official_workflow_delegations(revoked_by)
  where revoked_by is not null;
create index if not exists idx_pdf_versions_file_object_fk
  on public.pdf_versions(file_object_id);
create index if not exists idx_role_permissions_permission_fk
  on public.role_permissions(permission_id);
create index if not exists idx_seal_assets_file_object_fk
  on public.seal_assets(file_object_id);
create index if not exists idx_seal_usage_logs_document_fk
  on public.seal_usage_logs(document_id)
  where document_id is not null;
create index if not exists idx_seal_usage_logs_seal_fk
  on public.seal_usage_logs(seal_id);
create index if not exists idx_seal_usage_requests_seal_fk
  on public.seal_usage_requests(seal_id);
create index if not exists idx_seal_usage_requests_stamped_pdf_fk
  on public.seal_usage_requests(stamped_pdf_version_id)
  where stamped_pdf_version_id is not null;
create index if not exists idx_virus_scan_jobs_attachment_fk
  on public.virus_scan_jobs(attachment_id)
  where attachment_id is not null;
create index if not exists idx_virus_scan_jobs_document_fk
  on public.virus_scan_jobs(document_id)
  where document_id is not null;
