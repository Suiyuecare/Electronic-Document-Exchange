-- Make Data API privileges deterministic on both legacy projects (where
-- public tables were auto-granted to all API roles) and new projects (where
-- exposure is opt-in). Application users always go through the authenticated
-- eDoc backend; only its server-side service_role can reach these tables.

alter default privileges for role postgres in schema public
  revoke all privileges on tables
  from public, anon, authenticated, service_role;
alter default privileges for role postgres in schema public
  revoke all privileges on sequences
  from public, anon, authenticated, service_role;
alter default privileges for role postgres in schema public
  revoke all privileges on functions
  from public, anon, authenticated, service_role;

-- Revoke every historical browser Data API grant, not only grants on tables
-- introduced by the V2 recovery migration. The web application talks to
-- PostgREST exclusively through the authenticated eDoc backend; the only
-- browser-side Supabase operation is a path-scoped, expiring Storage TUS
-- upload. This closes legacy grants on PDF versions, seal applications,
-- background-job payloads and any other table created by older migrations.
revoke all privileges on all tables in schema public
  from public, anon, authenticated, service_role;
revoke all privileges on all sequences in schema public
  from public, anon, authenticated, service_role;
revoke all privileges on all functions in schema public
  from public, anon, authenticated, service_role;

-- service_role is the backend's only Data API principal. Clear legacy
-- function ACLs in both exposed and private schemas as well; the exact direct
-- RPC allowlist is restored below. This makes old auto-grant projects and new
-- opt-in projects converge on the same privileges.
revoke all privileges on schema edoc_private
  from public, anon, authenticated, service_role;
revoke all privileges on all functions in schema edoc_private
  from public, anon, authenticated, service_role;

-- Policies are not privileges, but removing browser-role policies prevents a
-- later accidental GRANT from silently re-opening a historical access path.
do $remove_legacy_browser_policies$
declare
  v_policy record;
begin
  for v_policy in
    select schemaname, tablename, policyname
    from pg_catalog.pg_policies
    where schemaname = 'public'
      and roles && array['public', 'anon', 'authenticated']::name[]
    order by tablename, policyname
  loop
    execute pg_catalog.format(
      'drop policy if exists %I on %I.%I',
      v_policy.policyname,
      v_policy.schemaname,
      v_policy.tablename
    );
  end loop;
end
$remove_legacy_browser_policies$;

alter table public.inbound_document_attachments enable row level security;
alter table public.internal_dispatches enable row level security;
alter table public.internal_dispatch_recipients enable row level security;
alter table public.internal_dispatch_replies enable row level security;
alter table public.internal_dispatch_logs enable row level security;
alter table public.official_document_stamp_positions enable row level security;
alter table public.official_document_text_overlays enable row level security;
alter table public.official_document_editor_revisions enable row level security;
alter table public.official_document_editor_assets enable row level security;
alter table public.official_document_dispatch_events enable row level security;
alter table public.official_document_archive_exports enable row level security;
alter table public.official_workflow_delegations enable row level security;

-- Exact backend table allowlist. Every application table is readable because
-- the service-only compliance inventory samples all of them. Write privileges
-- are limited to operations that backend.py performs directly through
-- PostgREST. Tables written only inside SECURITY DEFINER RPCs remain SELECT
-- only here. No TRUNCATE, REFERENCES or TRIGGER privilege is granted.
grant usage on schema public to service_role;

-- The audit-chain verification view is security-invoker and calls one
-- side-effect-free SECURITY DEFINER hash helper in edoc_private. Restore only
-- those two runtime capabilities after the deterministic global reset; chain
-- head storage and every trigger/private mutation helper remain inaccessible.
grant usage on schema edoc_private to service_role;
grant execute on function edoc_private.audit_log_hash_payload(
  text, text, text, text, text, text, text, text, text, text
) to service_role;
grant select on public.audit_log_chain_check to service_role;

grant select on table
  public.approval_step_actor_snapshots,
  public.attachment_security,
  public.attachments,
  public.audit_logs,
  public.auth_sessions,
  public.background_jobs,
  public.certificate_authorities,
  public.certificate_validation_events,
  public.companies,
  public.company_registry,
  public.company_seal_files,
  public.company_seals,
  public.compliance_attestations,
  public.contract_approvals,
  public.contract_parties,
  public.contracts,
  public.department_registry,
  public.document_acl,
  public.document_acl_events,
  public.documents,
  public.electronic_signatures,
  public.exchange_attachment,
  public.exchange_events,
  public.exchange_inbox,
  public.exchange_log,
  public.exchange_outbox,
  public.exchange_status_history,
  public.exchange_tasks,
  public.file_access_logs,
  public.file_download_tokens,
  public.file_objects,
  public.inbound_document_attachments,
  public.inbound_documents,
  public.internal_dispatch_logs,
  public.internal_dispatch_recipients,
  public.internal_dispatch_replies,
  public.internal_dispatches,
  public.ip_allowlist,
  public.job_runs,
  public.login_events,
  public.module_account_links,
  public.notification_channel_credentials,
  public.notification_deliveries,
  public.notification_rules,
  public.notifications,
  public.official_document_approval_logs,
  public.official_document_approval_steps,
  public.official_document_archive_exports,
  public.official_document_dispatch_events,
  public.official_document_dispatch_records,
  public.official_document_editor_assets,
  public.official_document_editor_revisions,
  public.official_document_files,
  public.official_document_stamp_positions,
  public.official_document_stamp_requests,
  public.official_document_text_overlays,
  public.official_documents,
  public.official_workflow_delegations,
  public.pdf_versions,
  public.permissions,
  public.recipients,
  public.role_permissions,
  public.roles,
  public.seal_applications,
  public.seal_assets,
  public.seal_permissions,
  public.seal_reference_options,
  public.seal_type_registry,
  public.seal_usage_approvals,
  public.seal_usage_logs,
  public.seal_usage_requests,
  public.settings,
  public.signature_provider_events,
  public.signing_certificates,
  public.sso_providers,
  public.system_inbox,
  public.trusted_devices,
  public.tsa_timestamp_tokens,
  public.users,
  public.virus_scan_jobs,
  public.workflow_tasks,
  public.finance_member_sync_nonces,
  public.finance_member_sync_receipts,
  public.finance_organization_projection_state,
  public.finance_organization_units,
  public.official_document_rejection_jobs,
  public.portal_handoff_nonces
to service_role;

grant insert on table
  public.approval_step_actor_snapshots,
  public.audit_logs,
  public.auth_sessions,
  public.certificate_validation_events,
  public.companies,
  public.company_registry,
  public.company_seals,
  public.compliance_attestations,
  public.documents,
  public.exchange_events,
  public.exchange_inbox,
  public.exchange_log,
  public.exchange_outbox,
  public.exchange_status_history,
  public.file_access_logs,
  public.file_objects,
  public.inbound_document_attachments,
  public.inbound_documents,
  public.internal_dispatch_logs,
  public.internal_dispatch_recipients,
  public.internal_dispatch_replies,
  public.internal_dispatches,
  public.job_runs,
  public.login_events,
  public.module_account_links,
  public.notification_deliveries,
  public.notifications,
  public.official_document_approval_logs,
  public.official_document_approval_steps,
  public.official_document_editor_assets,
  public.official_document_editor_revisions,
  public.official_document_files,
  public.official_document_stamp_positions,
  public.official_document_stamp_requests,
  public.official_document_text_overlays,
  public.official_documents,
  public.pdf_versions,
  public.seal_permissions,
  public.seal_usage_approvals,
  public.seal_usage_logs,
  public.seal_usage_requests,
  public.settings,
  public.system_inbox,
  public.users,
  public.virus_scan_jobs,
  public.finance_member_sync_nonces,
  public.finance_member_sync_receipts,
  public.portal_handoff_nonces
to service_role;

grant update on table
  public.auth_sessions,
  public.background_jobs,
  public.companies,
  public.company_registry,
  public.company_seals,
  public.documents,
  public.exchange_inbox,
  public.exchange_outbox,
  public.exchange_tasks,
  public.file_objects,
  public.inbound_documents,
  public.internal_dispatch_recipients,
  public.internal_dispatches,
  public.module_account_links,
  public.notification_channel_credentials,
  public.notifications,
  public.official_document_approval_steps,
  public.official_document_dispatch_records,
  public.official_document_editor_assets,
  public.official_document_stamp_positions,
  public.official_document_stamp_requests,
  public.official_documents,
  public.seal_usage_approvals,
  public.seal_usage_requests,
  public.settings,
  public.system_inbox,
  public.users,
  public.finance_member_sync_receipts,
  public.official_document_rejection_jobs
to service_role;

grant delete on table
  public.finance_member_sync_nonces,
  public.file_objects,
  public.official_document_stamp_positions,
  public.official_document_text_overlays
to service_role;

-- Direct RPC allowlist used by backend.py. All older RPC versions and every
-- trigger-only/private helper remain non-executable through PostgREST.
grant execute on function public.edoc_apply_finance_organization_projection_v2(text, text, bigint, text, text, jsonb) to service_role;
grant execute on function public.edoc_apply_official_document_correction(text, text, text, jsonb, text, jsonb, jsonb, text, jsonb, jsonb, text, text, text, text, text, text, jsonb, text, text) to service_role;
grant execute on function public.edoc_cancel_official_document(text, text) to service_role;
grant execute on function public.edoc_claim_official_document_approval_v3(text, text, text, text, text, jsonb) to service_role;
grant execute on function public.edoc_claim_official_document_rejection_v3(text, text, text, text, text, jsonb) to service_role;
grant execute on function public.edoc_claim_official_document_stamp(text, text, text, text, integer) to service_role;
grant execute on function public.edoc_commit_official_document_submission(jsonb) to service_role;
grant execute on function public.edoc_complete_official_document_dispatch(text, text, text, text, text, text, text, text, text, text) to service_role;
grant execute on function public.edoc_complete_official_document_stamp(text, text, text, text) to service_role;
grant execute on function public.edoc_create_company_seal_file_version(text, text, text, text, text, text, bigint, text, integer, integer, numeric, numeric, numeric, text, text, text, text, text, text) to service_role;
grant execute on function public.edoc_create_finance_login_session_v2(text, text, text, text, text, text, text, text, text, text, text, text, text, text, text, text, text, text, text, text, text) to service_role;
grant execute on function public.edoc_create_official_document_dispatch_record(text, text) to service_role;
grant execute on function public.edoc_create_official_workflow_delegation(text, text, text, text, timestamp with time zone, timestamp with time zone, text, text) to service_role;
grant execute on function public.edoc_fail_official_document_stamp(text, text, text, text) to service_role;
grant execute on function public.edoc_finalize_editor_asset_v2(jsonb) to service_role;
grant execute on function public.edoc_finalize_official_document_resubmit(text, text, text, timestamp with time zone, text, text, text, text, text) to service_role;
grant execute on function public.edoc_mutate_inbound_document_v1(text, text, text, text, text, bigint, jsonb) to service_role;
grant execute on function public.edoc_register_official_archive_export(text, text, text, text, text, integer, bigint, text, text, text) to service_role;
grant execute on function public.edoc_resolve_finance_session_v1(text) to service_role;
grant execute on function public.edoc_resolve_portal_finance_user(uuid, text) to service_role;
grant execute on function public.edoc_revalidate_finance_session_v2(text, text, text, text, text, text, text, text, text, text, text, text, text, text, text, text) to service_role;
grant execute on function public.edoc_revoke_official_workflow_delegation(text, text) to service_role;
grant execute on function public.edoc_set_current_company_seal_file(text, text, text, text) to service_role;

-- This pure immutable validator is called by the seal-dimension trigger while
-- a service-role draft write is executing; it exposes no rows or side effects.
grant execute on function public.edoc_company_seal_dimensions_are_valid(text, integer, integer, numeric, numeric, numeric, text, boolean) to service_role;

-- Explicitly keep the retired unbound Finance login RPC closed after the
-- deterministic function reset above.
revoke all on function public.edoc_create_finance_login_session_v1(text, text, text, text, text, text, text, text, text) from service_role;

-- Archive exports are created only by the audited registration RPC.

comment on table public.official_document_archive_exports is
  'Immutable archive export metadata; insert only through edoc_register_official_archive_export.';

notify pgrst, 'reload schema';
