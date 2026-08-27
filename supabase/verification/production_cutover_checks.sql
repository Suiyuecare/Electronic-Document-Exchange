-- eDoc production cutover checks (read-only metadata and aggregate counts).
-- Never select document content, attachment/storage paths, seal originals,
-- credentials, session tokens, notification bodies or personal data here.

-- 1. Required runtime tables: every row must report table_exists=true and
-- rls_enabled=true.
with required_tables(table_name) as (
  values
    ('audit_logs'), ('auth_sessions'), ('companies'), ('company_seal_files'),
    ('company_seals'), ('file_download_tokens'), ('file_objects'),
    ('finance_member_sync_nonces'), ('finance_member_sync_receipts'),
    ('inbound_document_attachments'), ('inbound_documents'),
    ('internal_dispatch_logs'), ('internal_dispatch_recipients'),
    ('internal_dispatch_replies'), ('internal_dispatches'), ('login_events'),
    ('official_document_approval_logs'), ('official_document_approval_steps'),
    ('official_document_archive_exports'), ('official_document_dispatch_events'),
    ('official_document_dispatch_records'), ('official_document_editor_assets'),
    ('official_document_editor_revisions'), ('official_document_files'),
    ('official_document_rejection_jobs'),
    ('official_document_stamp_positions'), ('official_document_stamp_requests'),
    ('official_document_text_overlays'), ('official_documents'),
    ('official_workflow_delegations'), ('seal_permissions'),
    ('seal_reference_options'), ('seal_usage_approvals'), ('seal_usage_logs'),
    ('seal_usage_requests'), ('users'), ('virus_scan_jobs')
)
select
  r.table_name,
  c.oid is not null as table_exists,
  coalesce(c.relrowsecurity, false) as rls_enabled
from required_tables r
left join pg_catalog.pg_class c
  on c.relname = r.table_name
 and c.relkind in ('r', 'p')
 and c.relnamespace = 'public'::pg_catalog.regnamespace
order by r.table_name;

-- 2. Browser Data API access to sensitive runtime tables: pass condition is
-- zero rows. All application access is mediated by the eDoc backend.
select table_name, grantee, privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and table_name in (
    'audit_logs', 'auth_sessions', 'company_seal_files', 'file_download_tokens',
    'file_objects', 'finance_member_sync_nonces', 'finance_member_sync_receipts',
    'inbound_document_attachments', 'internal_dispatch_logs',
    'internal_dispatch_recipients', 'internal_dispatch_replies',
    'internal_dispatches', 'notification_channel_credentials',
    'notification_deliveries', 'notifications', 'official_document_approval_logs',
    'official_document_approval_steps', 'official_document_archive_exports',
    'official_document_dispatch_events', 'official_document_editor_assets',
    'official_document_editor_revisions', 'official_document_files',
    'official_document_rejection_jobs',
    'official_document_stamp_positions', 'official_document_stamp_requests',
    'official_document_text_overlays', 'official_workflow_delegations',
    'system_inbox'
  )
  and grantee in ('PUBLIC', 'anon', 'authenticated')
order by table_name, grantee, privilege_type;

-- 3. Required backend RPC inventory. Pass condition: missing=false for every
-- row. Signatures are intentionally checked to detect incompatible overloads.
with required_rpcs(signature) as (
  values
    ('public.edoc_create_official_workflow_delegation(text,text,text,text,timestamp with time zone,timestamp with time zone,text,text)'),
    ('public.edoc_revoke_official_workflow_delegation(text,text)'),
    ('public.edoc_create_company_seal_file_version(text,text,text,text,text,text,bigint,text,integer,integer,numeric,numeric,numeric,text,text,text,text,text,text)'),
    ('public.edoc_set_current_company_seal_file(text,text,text,text)'),
    ('public.edoc_create_official_document_dispatch_record(text,text)'),
    ('public.edoc_complete_official_document_dispatch(text,text,text,text,text,text,text,text,text,text)'),
    ('public.edoc_apply_official_document_correction(text,text,text,jsonb,text,jsonb,jsonb,text,jsonb,jsonb,text,text,text,text,text,text,jsonb,text,text)'),
    ('public.edoc_finalize_official_document_resubmit(text,text,text,timestamp with time zone,text,text,text,text,text)'),
    ('public.edoc_claim_official_document_approval_v3(text,text,text,text,text,jsonb)'),
    ('public.edoc_claim_official_document_rejection_v3(text,text,text,text,text,jsonb)'),
    ('public.edoc_cancel_official_document(text,text)'),
    ('public.edoc_complete_official_document_stamp(text,text,text,text)'),
    ('public.edoc_fail_official_document_stamp(text,text,text,text)'),
    ('public.edoc_resolve_portal_finance_user(uuid,text)'),
    ('public.edoc_register_official_archive_export(text,text,text,text,text,integer,bigint,text,text,text)'),
    ('public.edoc_commit_official_document_submission(jsonb)'),
    ('public.edoc_finalize_editor_asset_v2(jsonb)')
)
select signature, pg_catalog.to_regprocedure(signature) is null as missing
from required_rpcs
order by signature;

-- 4. Privileged RPC grants. service_role=true and anon/authenticated=false are
-- required for each row. PUBLIC execution is separately detected from ACL.
with required_rpcs(signature) as (
  values
    ('public.edoc_create_official_workflow_delegation(text,text,text,text,timestamp with time zone,timestamp with time zone,text,text)'),
    ('public.edoc_revoke_official_workflow_delegation(text,text)'),
    ('public.edoc_create_company_seal_file_version(text,text,text,text,text,text,bigint,text,integer,integer,numeric,numeric,numeric,text,text,text,text,text,text)'),
    ('public.edoc_set_current_company_seal_file(text,text,text,text)'),
    ('public.edoc_create_official_document_dispatch_record(text,text)'),
    ('public.edoc_complete_official_document_dispatch(text,text,text,text,text,text,text,text,text,text)'),
    ('public.edoc_apply_official_document_correction(text,text,text,jsonb,text,jsonb,jsonb,text,jsonb,jsonb,text,text,text,text,text,text,jsonb,text,text)'),
    ('public.edoc_finalize_official_document_resubmit(text,text,text,timestamp with time zone,text,text,text,text,text)'),
    ('public.edoc_claim_official_document_approval_v3(text,text,text,text,text,jsonb)'),
    ('public.edoc_claim_official_document_rejection_v3(text,text,text,text,text,jsonb)'),
    ('public.edoc_cancel_official_document(text,text)'),
    ('public.edoc_complete_official_document_stamp(text,text,text,text)'),
    ('public.edoc_fail_official_document_stamp(text,text,text,text)'),
    ('public.edoc_resolve_portal_finance_user(uuid,text)'),
    ('public.edoc_register_official_archive_export(text,text,text,text,text,integer,bigint,text,text,text)'),
    ('public.edoc_commit_official_document_submission(jsonb)'),
    ('public.edoc_finalize_editor_asset_v2(jsonb)')
), resolved as (
  select signature, pg_catalog.to_regprocedure(signature) as oid
  from required_rpcs
)
select
  signature,
  case when oid is null then false else pg_catalog.has_function_privilege('service_role', oid, 'EXECUTE') end as service_role_execute,
  case when oid is null then true else pg_catalog.has_function_privilege('anon', oid, 'EXECUTE') end as anon_execute,
  case when oid is null then true else pg_catalog.has_function_privilege('authenticated', oid, 'EXECUTE') end as authenticated_execute,
  case when oid is null then true else exists (
    select 1
    from pg_catalog.pg_proc p,
         lateral pg_catalog.aclexplode(coalesce(p.proacl, pg_catalog.acldefault('f', p.proowner))) acl
    where p.oid = resolved.oid and acl.grantee = 0 and acl.privilege_type = 'EXECUTE'
  ) end as public_execute
from resolved
order by signature;

-- 5. Runtime column parity. Pass condition: column_matches=true for every row.
-- This inventory deliberately includes the fields that used to exist only in
-- the live catalog and are now restored by the forward schema-parity migration.
with required_columns(table_name, column_name, data_type, nullable) as (
  values
    ('official_documents', 'workflow_template_key', 'text', false),
    ('official_documents', 'stamped_file_id', 'text', true),
    ('official_documents', 'requires_stamp', 'boolean', false),
    ('official_documents', 'correction_reason_category', 'text', true),
    ('official_documents', 'correction_missing_items_json', 'jsonb', false),
    ('official_documents', 'correction_due_at', 'timestamp with time zone', true),
    ('official_documents', 'correction_requested_at', 'timestamp with time zone', true),
    ('official_documents', 'correction_resubmitted_at', 'timestamp with time zone', true),
    ('official_documents', 'retention_until', 'timestamp with time zone', false),
    ('official_documents', 'retention_policy_version', 'text', false),
    ('official_documents', 'legal_hold', 'boolean', false),
    ('official_documents', 'disposition_status', 'text', false),
    ('official_document_files', 'stamp_request_id', 'text', true),
    ('official_document_files', 'stamp_claim_token', 'text', true),
    ('official_document_approval_steps', 'workflow_generation', 'integer', false),
    ('official_document_approval_steps', 'decision_actor_user_id', 'text', true),
    ('official_document_approval_steps', 'decision_evidence_json', 'jsonb', false),
    ('official_document_approval_steps', 'review_started_at', 'text', true),
    ('official_document_approval_logs', 'principal_actor_id', 'text', true),
    ('official_document_approval_logs', 'decision_evidence_json', 'jsonb', false),
    ('official_document_stamp_requests', 'locked_editor_revision_id', 'text', true),
    ('official_document_stamp_requests', 'locked_source_sha256', 'text', true),
    ('official_document_stamp_requests', 'prepared_file_id', 'text', true),
    ('official_document_stamp_requests', 'prepared_sha256', 'text', true),
    ('official_document_stamp_requests', 'editor_manifest_sha256', 'text', true),
    ('official_document_stamp_requests', 'editor_schema_version', 'integer', true),
    ('official_document_stamp_requests', 'renderer_version', 'text', true),
    ('official_document_stamp_requests', 'editor_locked_at', 'text', true),
    ('official_document_stamp_requests', 'claim_token', 'text', true),
    ('official_document_stamp_requests', 'claim_owner_id', 'text', true),
    ('official_document_stamp_requests', 'claim_started_at', 'timestamp with time zone', true),
    ('official_document_stamp_requests', 'claim_expires_at', 'timestamp with time zone', true),
    ('official_document_stamp_requests', 'claim_attempt_count', 'integer', false),
    ('official_document_editor_revisions', 'schema_version', 'integer', false),
    ('official_document_editor_revisions', 'editor_state_json', 'text', false),
    ('official_document_editor_revisions', 'manifest_sha256', 'text', false),
    ('official_document_editor_revisions', 'renderer_version', 'text', false),
    ('official_document_editor_assets', 'expected_sha256', 'text', false),
    ('official_document_editor_assets', 'upload_status', 'text', false),
    ('official_document_editor_assets', 'scan_status', 'text', false),
    ('official_document_editor_assets', 'preflight_status', 'text', false),
    ('official_document_stamp_positions', 'page_ref', 'text', true),
    ('official_document_stamp_positions', 'locked_seal_file_id', 'text', true),
    ('official_document_stamp_positions', 'locked_seal_sha256', 'text', true)
)
select
  r.table_name,
  r.column_name,
  c.column_name is not null
    and c.data_type = r.data_type
    and (c.is_nullable = 'YES') = r.nullable as column_matches,
  c.data_type as actual_data_type,
  c.is_nullable as actual_is_nullable
from required_columns r
left join information_schema.columns c
  on c.table_schema = 'public'
 and c.table_name = r.table_name
 and c.column_name = r.column_name
order by r.table_name, r.column_name;

-- 6. Runtime constraint parity. Pass condition: constraint_exists=true for
-- every row. The definition is returned for human comparison without values.
with required_constraints(table_name, constraint_name) as (
  values
    ('official_documents', 'official_documents_status_check'),
    ('official_documents', 'official_documents_disposition_status_check'),
    ('official_documents', 'official_documents_stamped_file_id_fkey'),
    ('official_document_files', 'official_document_files_type_check'),
    ('official_document_files', 'official_document_files_stamp_request_id_fkey'),
    ('official_document_approval_steps', 'official_document_steps_generation_order_key'),
    ('official_document_approval_steps', 'official_document_steps_generation_step_key'),
    ('official_document_approval_steps', 'official_document_steps_decision_actor_fk'),
    ('official_document_approval_logs', 'official_document_logs_principal_actor_fk'),
    ('official_document_stamp_requests', 'official_document_stamp_requests_locked_editor_revision_id_fkey'),
    ('official_document_stamp_requests', 'official_document_stamp_requests_prepared_file_id_fkey'),
    ('official_document_stamp_requests', 'official_document_stamp_requests_claim_attempt_count_check'),
    ('official_document_dispatch_records', 'official_document_dispatch_records_document_key')
)
select
  r.table_name,
  r.constraint_name,
  con.oid is not null as constraint_exists,
  case when con.oid is null then null else pg_catalog.pg_get_constraintdef(con.oid, true) end as definition
from required_constraints r
left join pg_catalog.pg_class rel
  on rel.relname = r.table_name
 and rel.relnamespace = 'public'::pg_catalog.regnamespace
left join pg_catalog.pg_constraint con
  on con.conrelid = rel.oid
 and con.conname = r.constraint_name
order by r.table_name, r.constraint_name;

-- 7. Finance projection fields required for automatic roster/company/org sync.
with required_columns(table_name, column_name) as (
  values
    ('users', 'finance_source_revision'), ('users', 'finance_source_event_id'),
    ('users', 'finance_source_status'), ('users', 'finance_source_updated_at'),
    ('companies', 'finance_source_revision'), ('companies', 'finance_source_event_id'),
    ('companies', 'finance_source_updated_at')
)
select r.table_name, r.column_name, c.column_name is not null as column_exists,
       c.data_type, c.is_nullable
from required_columns r
left join information_schema.columns c
  on c.table_schema = 'public' and c.table_name = r.table_name
 and c.column_name = r.column_name
order by r.table_name, r.column_name;

-- Dedicated Storage checks intentionally live in
-- supabase/verification/dedicated_storage_cutover_checks.sql. Do not apply the
-- dedicated project's empty browser-policy allowlist to this shared main/CMS
-- project.

-- 8. Retired demo identifiers. Every count must be zero. Exact identifiers
-- only; no user names, emails or business document content are returned.
select 'users' as object_type, count(*) as demo_identifier_count
from public.users where id in ('USR-001','USR-002','USR-003','USR-004','USR-005','USR-006','USR-007')
union all
select 'documents', count(*) from public.documents
where id in ('DOC-IN-1140522-00018','DOC-OUT-1140522-007','DOC-OUT-1140519-006')
union all
select 'trusted_devices', count(*) from public.trusted_devices
where id in ('ACC-DEV-001','ACC-DEV-002','ACC-DEV-003','ACC-DEV-004','ACC-DEV-005','ACC-DEV-006','ACC-DEV-007')
union all
select 'signing_certificates', count(*) from public.signing_certificates
where id in ('CERT-SEAL-001','CERT-SEAL-002','CERT-TSA-001')
union all
select 'notifications', count(*) from public.notifications
where id in ('NTF-001','NTF-002','NTF-003','NTF-004','NTF-005');

-- 9. Notification readiness. Internal inbox is the launch baseline; external
-- credentials may legitimately remain pending. No credential values are read.
select
  count(*) filter (where channel = '系統通知' and status = '啟用') as enabled_inbox_rules,
  count(*) filter (where (channel ilike '%email%' or channel ilike '%line%') and status = '啟用') as enabled_external_rules
from public.notification_rules
where id like 'NRULE-%';

select channel, status,
       coalesce((validation_report_json->>'configured')::boolean, false) as configured,
       coalesce((validation_report_json->>'verified')::boolean, false) as verified
from public.notification_channel_credentials
where id in ('NCRED-EMAIL-SMTP', 'NCRED-LINE-WEBHOOK', 'NCRED-INBOX-SIGNING')
order by id;

select
  key,
  coalesce((value_json::jsonb #>> '{system_inbox,enabled}')::boolean, false) as system_inbox_ready,
  value_json::jsonb #>> '{external,email}' as email_readiness,
  value_json::jsonb #>> '{external,line}' as line_readiness
from public.settings
where key = 'notification_readiness';

-- 10. Upload hygiene. Pass condition is zero; rows older than two hours should
-- be finalized, quarantined or failed by the scheduled backend cleanup.
select count(*) as stale_pending_editor_assets
from public.official_document_editor_assets
where upload_status in ('pending', 'uploading', 'uploaded')
  and created_at < to_char(now() - interval '2 hours', 'YYYY-MM-DD HH24:MI:SS');

-- 11. Confirmed eDoc foreign-key indexes. Every row must report
-- index_exists=true after the forward migration.
with required_indexes(index_name) as (
  values
    ('idx_inbound_attachments_file_object'),
    ('idx_internal_dispatches_official_document'),
    ('idx_internal_dispatch_replies_recipient'),
    ('idx_internal_dispatch_replies_attachment'),
    ('idx_official_archive_exports_requested_by'),
    ('idx_official_stamp_positions_seal'),
    ('idx_official_rejection_jobs_expected_step'),
    ('idx_official_rejection_jobs_source_revision'),
    ('idx_official_rejection_jobs_target_revision'),
    ('idx_auth_sessions_user_fk'),
    ('idx_login_events_user_fk'),
    ('idx_document_retention_events_policy_fk'),
    ('idx_electronic_signatures_pdf_version_fk'),
    ('idx_electronic_signatures_certificate_fk'),
    ('idx_electronic_signatures_previous_fk'),
    ('idx_exchange_attachment_document_fk'),
    ('idx_exchange_events_task_fk'),
    ('idx_file_access_logs_file_object_fk'),
    ('idx_file_access_logs_document_fk'),
    ('idx_official_approval_logs_step_fk'),
    ('idx_official_approval_logs_file_fk'),
    ('idx_official_dispatch_records_proof_file_fk'),
    ('idx_official_document_files_file_object_fk'),
    ('idx_official_stamp_requests_company_fk'),
    ('idx_official_stamp_requests_seal_fk'),
    ('idx_official_stamp_requests_stamped_file_fk'),
    ('idx_official_documents_stamped_file_fk'),
    ('idx_official_workflow_delegations_created_by'),
    ('idx_official_workflow_delegations_delegate'),
    ('idx_official_workflow_delegations_principal'),
    ('idx_official_workflow_delegations_revoked_by'),
    ('idx_pdf_versions_file_object_fk'),
    ('idx_role_permissions_permission_fk'),
    ('idx_seal_assets_file_object_fk'),
    ('idx_seal_usage_logs_document_fk'),
    ('idx_seal_usage_logs_seal_fk'),
    ('idx_seal_usage_requests_seal_fk'),
    ('idx_seal_usage_requests_stamped_pdf_fk'),
    ('idx_virus_scan_jobs_attachment_fk'),
    ('idx_virus_scan_jobs_document_fk')
)
select index_name, pg_catalog.to_regclass('public.' || index_name) is not null as index_exists
from required_indexes
order by index_name;

-- 12. Safe index review: duplicate definitions should return zero rows. This
-- reports names only, never indexed values.
select schemaname, tablename, array_agg(indexname order by indexname) as duplicate_indexes
from pg_catalog.pg_indexes
where schemaname = 'public'
group by schemaname, tablename, indexdef
having count(*) > 1
order by tablename;
