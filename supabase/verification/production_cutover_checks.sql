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

-- 2. Browser Data API access to public relations: pass condition is zero rows
-- for every query in this section. All database and RPC access is mediated by
-- the eDoc backend; browsers receive only path-scoped Storage TUS credentials.
select table_name, grantee, privilege_type
from information_schema.table_privileges
where table_schema = 'public'
  and grantee in ('PUBLIC', 'anon', 'authenticated')
order by table_name, grantee, privilege_type;

select object_name as sequence_name, grantee, privilege_type
from information_schema.usage_privileges
where object_schema = 'public'
  and object_type = 'SEQUENCE'
  and grantee in ('PUBLIC', 'anon', 'authenticated')
order by object_name, grantee, privilege_type;

select routine_name, grantee, privilege_type
from information_schema.routine_privileges
where routine_schema = 'public'
  and grantee in ('PUBLIC', 'anon', 'authenticated')
order by routine_name, grantee, privilege_type;

select
  owner_role.rolname as owner_role,
  default_acl.defaclobjtype as object_type,
  case
    when privilege_row.grantee = 0 then 'PUBLIC'
    else pg_catalog.pg_get_userbyid(privilege_row.grantee)
  end as grantee,
  privilege_row.privilege_type
from pg_catalog.pg_default_acl default_acl
join pg_catalog.pg_roles owner_role on owner_role.oid = default_acl.defaclrole
join pg_catalog.pg_namespace namespace_row
  on namespace_row.oid = default_acl.defaclnamespace
cross join lateral pg_catalog.aclexplode(default_acl.defaclacl) privilege_row
where namespace_row.nspname = 'public'
  and owner_role.rolname = 'postgres'
  and (
    privilege_row.grantee = 0
    or pg_catalog.pg_get_userbyid(privilege_row.grantee)
      in ('anon', 'authenticated', 'service_role')
  )
order by owner_role, object_type, grantee, privilege_row.privilege_type;

-- Application migrations create functions as postgres. PostgreSQL's built-in
-- global default grants EXECUTE to PUBLIC unless it is explicitly revoked;
-- pass condition is zero rows. Reserved Supabase platform-role defaults are
-- managed by Supabase and are not alterable by the hosted postgres role.
select
  'postgres' as owner_role,
  'global-functions' as object_type,
  case
    when privilege_row.grantee = 0 then 'PUBLIC'
    else pg_catalog.pg_get_userbyid(privilege_row.grantee)
  end as grantee,
  privilege_row.privilege_type
from pg_catalog.aclexplode(
  coalesce(
    (
      select default_acl.defaclacl
      from pg_catalog.pg_default_acl default_acl
      where default_acl.defaclrole = 'postgres'::regrole
        and default_acl.defaclnamespace = 0
        and default_acl.defaclobjtype = 'f'
    ),
    pg_catalog.acldefault('f', 'postgres'::regrole)
  )
) privilege_row
where privilege_row.grantee = 0
   or pg_catalog.pg_get_userbyid(privilege_row.grantee)
     in ('anon', 'authenticated', 'service_role')
order by grantee, privilege_row.privilege_type;

select tablename, policyname, roles
from pg_catalog.pg_policies
where schemaname = 'public'
  and roles && array['public', 'anon', 'authenticated']::name[]
order by tablename, policyname;

-- 2b. Exact backend grant parity for all 87 direct PostgREST tables.
-- Pass condition: table_exists, owner_matches, no_unexpected_table_grants and
-- grant_matches must all be true for every row, in addition to the zero-row
-- browser-grant checks in section 2. The first 81 are backend.TABLES and the
-- final six are dedicated Finance/SSO/rejection workflow tables. Write arrays
-- are the direct backend.py call matrix, not a blanket CRUD grant.
with backend_tables(table_name) as (
  select unnest(array[
    'approval_step_actor_snapshots', 'attachment_security', 'attachments',
    'audit_logs', 'auth_sessions', 'background_jobs',
    'certificate_authorities', 'certificate_validation_events', 'companies',
    'company_registry', 'company_seal_files', 'company_seals',
    'compliance_attestations', 'contract_approvals', 'contract_parties',
    'contracts', 'department_registry', 'document_acl', 'document_acl_events',
    'documents', 'electronic_signatures', 'exchange_attachment',
    'exchange_events', 'exchange_inbox', 'exchange_log', 'exchange_outbox',
    'exchange_status_history', 'exchange_tasks', 'file_access_logs',
    'file_download_tokens', 'file_objects', 'inbound_document_attachments',
    'inbound_documents', 'internal_dispatch_logs',
    'internal_dispatch_recipients', 'internal_dispatch_replies',
    'internal_dispatches', 'ip_allowlist', 'job_runs', 'login_events',
    'module_account_links', 'notification_channel_credentials',
    'notification_deliveries', 'notification_rules', 'notifications',
    'official_document_approval_logs', 'official_document_approval_steps',
    'official_document_archive_exports', 'official_document_dispatch_events',
    'official_document_dispatch_records', 'official_document_editor_assets',
    'official_document_editor_revisions', 'official_document_files',
    'official_document_stamp_positions', 'official_document_stamp_requests',
    'official_document_text_overlays', 'official_documents',
    'official_workflow_delegations', 'pdf_versions', 'permissions',
    'recipients', 'role_permissions', 'roles', 'seal_applications',
    'seal_assets', 'seal_permissions', 'seal_reference_options',
    'seal_type_registry', 'seal_usage_approvals', 'seal_usage_logs',
    'seal_usage_requests', 'settings', 'signature_provider_events',
    'signing_certificates', 'sso_providers', 'system_inbox',
    'trusted_devices', 'tsa_timestamp_tokens', 'users', 'virus_scan_jobs',
    'workflow_tasks', 'finance_member_sync_nonces',
    'finance_member_sync_receipts', 'finance_organization_projection_state',
    'finance_organization_units', 'official_document_rejection_jobs',
    'portal_handoff_nonces'
  ]::text[])
), insert_tables(table_name) as (
  select unnest(array[
    'approval_step_actor_snapshots', 'audit_logs', 'auth_sessions',
    'certificate_validation_events', 'companies', 'company_registry',
    'company_seals', 'compliance_attestations', 'documents', 'exchange_events',
    'exchange_inbox', 'exchange_log', 'exchange_outbox',
    'exchange_status_history', 'file_access_logs', 'file_objects',
    'inbound_document_attachments', 'inbound_documents',
    'internal_dispatch_logs', 'internal_dispatch_recipients',
    'internal_dispatch_replies', 'internal_dispatches', 'job_runs',
    'login_events', 'module_account_links', 'notification_deliveries',
    'notifications', 'official_document_approval_logs',
    'official_document_approval_steps', 'official_document_editor_assets',
    'official_document_editor_revisions', 'official_document_files',
    'official_document_stamp_positions', 'official_document_stamp_requests',
    'official_document_text_overlays', 'official_documents', 'pdf_versions',
    'seal_permissions', 'seal_usage_approvals', 'seal_usage_logs',
    'seal_usage_requests', 'settings', 'system_inbox', 'users',
    'virus_scan_jobs', 'finance_member_sync_nonces',
    'finance_member_sync_receipts', 'portal_handoff_nonces'
  ]::text[])
), update_tables(table_name) as (
  select unnest(array[
    'auth_sessions', 'background_jobs', 'companies', 'company_registry',
    'company_seals', 'documents', 'exchange_inbox', 'exchange_outbox',
    'exchange_tasks', 'file_objects', 'inbound_documents',
    'internal_dispatch_recipients', 'internal_dispatches',
    'module_account_links', 'notification_channel_credentials',
    'notifications', 'official_document_approval_steps',
    'official_document_dispatch_records', 'official_document_editor_assets',
    'official_document_stamp_positions', 'official_document_stamp_requests',
    'official_documents', 'seal_usage_approvals', 'seal_usage_requests',
    'settings', 'system_inbox', 'users', 'finance_member_sync_receipts',
    'official_document_rejection_jobs'
  ]::text[])
), delete_tables(table_name) as (
  select unnest(array[
    'file_objects', 'finance_member_sync_nonces',
    'official_document_stamp_positions', 'official_document_text_overlays'
  ]::text[])
), expected_grants as (
  select
    backend.table_name,
    true as can_select,
    exists (select 1 from insert_tables item where item.table_name = backend.table_name) as can_insert,
    exists (select 1 from update_tables item where item.table_name = backend.table_name) as can_update,
    exists (select 1 from delete_tables item where item.table_name = backend.table_name) as can_delete
  from backend_tables backend
), actual_grants as (
  select
    expected.*,
    pg_catalog.to_regclass(
      pg_catalog.format('%I.%I', 'public', expected.table_name)
    ) as table_oid
  from expected_grants expected
)
select
  table_name,
  table_oid is not null as table_exists,
  case when table_oid is null then false else exists (
    select 1
    from pg_catalog.pg_class relation_row
    where relation_row.oid = table_oid
      and pg_catalog.pg_get_userbyid(relation_row.relowner) = 'postgres'
  ) end as owner_matches,
  not exists (
    select 1
    from information_schema.table_privileges privilege_row
    where privilege_row.table_schema = 'public'
      and privilege_row.grantee = 'service_role'
      and not exists (
        select 1 from backend_tables allowed
        where allowed.table_name = privilege_row.table_name
      )
      and not (
        privilege_row.table_name = 'audit_log_chain_check'
        and privilege_row.privilege_type = 'SELECT'
      )
  ) as no_unexpected_table_grants,
  case when table_oid is null then false else
    pg_catalog.has_table_privilege('service_role', table_oid, 'SELECT') = can_select
    and pg_catalog.has_table_privilege('service_role', table_oid, 'IN' || 'SERT') = can_insert
    and pg_catalog.has_table_privilege('service_role', table_oid, 'UP' || 'DATE') = can_update
    and pg_catalog.has_table_privilege('service_role', table_oid, 'DE' || 'LETE') = can_delete
    and not pg_catalog.has_table_privilege('service_role', table_oid, 'TRUN' || 'CATE')
    and not pg_catalog.has_table_privilege('service_role', table_oid, 'REFERENCES')
    and not pg_catalog.has_table_privilege('service_role', table_oid, 'TRIGGER')
  end as grant_matches
from actual_grants
order by table_name;

-- 3. Required backend RPC inventory. Pass condition: missing=false for every
-- row. Signatures are intentionally checked to detect incompatible overloads.
with required_rpcs(signature) as (
  values
    ('public.edoc_apply_finance_organization_projection_v2(text,text,bigint,text,text,jsonb)'),
    ('public.edoc_claim_official_document_stamp(text,text,text,text,integer)'),
    ('public.edoc_create_finance_login_session_v2(text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text)'),
    ('public.edoc_mutate_inbound_document_v1(text,text,text,text,text,bigint,jsonb)'),
    ('public.edoc_resolve_finance_session_v1(text)'),
    ('public.edoc_revalidate_finance_session_v2(text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text)'),
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
  oid is null as missing,
  case when oid is null then false else exists (
    select 1
    from pg_catalog.pg_proc procedure_row
    where procedure_row.oid = resolved.oid
      and pg_catalog.pg_get_userbyid(procedure_row.proowner) = 'postgres'
  ) end as owner_matches
from resolved
order by signature;

-- 4. Privileged RPC grants. service_role=true and anon/authenticated=false are
-- required for each row. PUBLIC execution is separately detected from ACL.
with required_rpcs(signature) as (
  values
    ('public.edoc_apply_finance_organization_projection_v2(text,text,bigint,text,text,jsonb)'),
    ('public.edoc_claim_official_document_stamp(text,text,text,text,integer)'),
    ('public.edoc_create_finance_login_session_v2(text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text)'),
    ('public.edoc_mutate_inbound_document_v1(text,text,text,text,text,bigint,jsonb)'),
    ('public.edoc_resolve_finance_session_v1(text)'),
    ('public.edoc_revalidate_finance_session_v2(text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text)'),
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

-- 4b. No other public function may be executable by service_role. The only
-- non-RPC exception is the pure immutable seal-dimension validator required
-- by a draft-position trigger. Pass condition: zero rows.
with allowed(signature) as (
  values
    ('public.edoc_apply_finance_organization_projection_v2(text,text,bigint,text,text,jsonb)'),
    ('public.edoc_apply_official_document_correction(text,text,text,jsonb,text,jsonb,jsonb,text,jsonb,jsonb,text,text,text,text,text,text,jsonb,text,text)'),
    ('public.edoc_cancel_official_document(text,text)'),
    ('public.edoc_claim_official_document_approval_v3(text,text,text,text,text,jsonb)'),
    ('public.edoc_claim_official_document_rejection_v3(text,text,text,text,text,jsonb)'),
    ('public.edoc_claim_official_document_stamp(text,text,text,text,integer)'),
    ('public.edoc_commit_official_document_submission(jsonb)'),
    ('public.edoc_complete_official_document_dispatch(text,text,text,text,text,text,text,text,text,text)'),
    ('public.edoc_complete_official_document_stamp(text,text,text,text)'),
    ('public.edoc_create_company_seal_file_version(text,text,text,text,text,text,bigint,text,integer,integer,numeric,numeric,numeric,text,text,text,text,text,text)'),
    ('public.edoc_create_finance_login_session_v2(text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text)'),
    ('public.edoc_create_official_document_dispatch_record(text,text)'),
    ('public.edoc_create_official_workflow_delegation(text,text,text,text,timestamp with time zone,timestamp with time zone,text,text)'),
    ('public.edoc_fail_official_document_stamp(text,text,text,text)'),
    ('public.edoc_finalize_editor_asset_v2(jsonb)'),
    ('public.edoc_finalize_official_document_resubmit(text,text,text,timestamp with time zone,text,text,text,text,text)'),
    ('public.edoc_mutate_inbound_document_v1(text,text,text,text,text,bigint,jsonb)'),
    ('public.edoc_register_official_archive_export(text,text,text,text,text,integer,bigint,text,text,text)'),
    ('public.edoc_resolve_finance_session_v1(text)'),
    ('public.edoc_resolve_portal_finance_user(uuid,text)'),
    ('public.edoc_revalidate_finance_session_v2(text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text)'),
    ('public.edoc_revoke_official_workflow_delegation(text,text)'),
    ('public.edoc_set_current_company_seal_file(text,text,text,text)'),
    ('public.edoc_company_seal_dimensions_are_valid(text,integer,integer,numeric,numeric,numeric,text,boolean)')
), allowed_oids as (
  select pg_catalog.to_regprocedure(signature) as oid from allowed
)
select p.oid::pg_catalog.regprocedure::text as unexpected_service_role_function
from pg_catalog.pg_proc p
join pg_catalog.pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public'
  and pg_catalog.has_function_privilege('service_role', p.oid, 'EXECUTE')
  and p.oid not in (select oid from allowed_oids where oid is not null)
order by 1;

-- 4c. Database-owned dispatch evidence. Every boolean must be true. This only
-- inspects metadata and aggregate existence/sequence properties; it does not
-- select recipient, contact, note, document text, or attachment information.
with capture_function as (
  select pg_catalog.to_regprocedure(
    'edoc_private.capture_official_dispatch_event_v1()'
  ) as oid
), identity_function as (
  select pg_catalog.to_regprocedure(
    'edoc_private.guard_official_dispatch_identity_v1()'
  ) as oid
), expected_quals as (
  select
    'old.dispatch_methodisdistinctfromnew.dispatch_methodor'
      || 'old.dispatch_owner_typeisdistinctfromnew.dispatch_owner_typeor'
      || 'old.dispatch_owner_user_idisdistinctfromnew.dispatch_owner_user_idor'
      || 'old.dispatch_statusisdistinctfromnew.dispatch_statusor'
      || 'old.external_official_document_numberisdistinctfromnew.external_official_document_numberor'
      || 'old.dispatch_dateisdistinctfromnew.dispatch_dateor'
      || 'old.recipientisdistinctfromnew.recipientor'
      || 'old.recipient_contactisdistinctfromnew.recipient_contactor'
      || 'old.dispatch_noteisdistinctfromnew.dispatch_noteor'
      || 'old.proof_file_idisdistinctfromnew.proof_file_idor'
      || 'old.completed_atisdistinctfromnew.completed_at'
      as capture_qual,
    'old.idisdistinctfromnew.idor'
      || 'old.document_idisdistinctfromnew.document_idor'
      || 'old.created_byisdistinctfromnew.created_byor'
      || 'old.created_atisdistinctfromnew.created_at'
      as identity_qual
), public_execute as (
  select exists (
    select 1
    from capture_function capture
    join pg_catalog.pg_proc procedure_row on procedure_row.oid = capture.oid
    cross join lateral pg_catalog.aclexplode(
      coalesce(
        procedure_row.proacl,
        pg_catalog.acldefault('f', procedure_row.proowner)
      )
    ) privilege_row
    where privilege_row.grantee = 0
      and privilege_row.privilege_type = 'EXECUTE'
  ) as exposed
), identity_public_execute as (
  select exists (
    select 1
    from identity_function identity_guard
    join pg_catalog.pg_proc procedure_row
      on procedure_row.oid = identity_guard.oid
    cross join lateral pg_catalog.aclexplode(
      coalesce(
        procedure_row.proacl,
        pg_catalog.acldefault('f', procedure_row.proowner)
      )
    ) privilege_row
    where privilege_row.grantee = 0
      and privilege_row.privilege_type = 'EXECUTE'
  ) as exposed
)
select
  capture.oid is not null as dispatch_capture_function_exists,
  coalesce((
    select owner_role.rolname = 'postgres'
      and procedure_row.prosecdef
      and procedure_row.proconfig @> array['search_path=""']::text[]
    from pg_catalog.pg_proc procedure_row
    join pg_catalog.pg_roles owner_role
      on owner_role.oid = procedure_row.proowner
    where procedure_row.oid = capture.oid
  ), false) as dispatch_capture_function_hardened,
  not public_execute.exposed
    and case when capture.oid is null then false else
      not pg_catalog.has_function_privilege('anon', capture.oid, 'EXECUTE')
      and not pg_catalog.has_function_privilege('authenticated', capture.oid, 'EXECUTE')
      and not pg_catalog.has_function_privilege('service_role', capture.oid, 'EXECUTE')
    end as dispatch_capture_function_private,
  identity_guard.oid is not null as dispatch_identity_guard_function_exists,
  coalesce((
    select owner_role.rolname = 'postgres'
      and procedure_row.prosecdef
      and procedure_row.proconfig @> array['search_path=""']::text[]
    from pg_catalog.pg_proc procedure_row
    join pg_catalog.pg_roles owner_role
      on owner_role.oid = procedure_row.proowner
    where procedure_row.oid = identity_guard.oid
  ), false) as dispatch_identity_guard_function_hardened,
  not identity_public_execute.exposed
    and case when identity_guard.oid is null then false else
      not pg_catalog.has_function_privilege('anon', identity_guard.oid, 'EXECUTE')
      and not pg_catalog.has_function_privilege('authenticated', identity_guard.oid, 'EXECUTE')
      and not pg_catalog.has_function_privilege('service_role', identity_guard.oid, 'EXECUTE')
    end as dispatch_identity_guard_function_private,
  1 = (
    select pg_catalog.count(*)
    from pg_catalog.pg_trigger trigger_row
    where trigger_row.tgrelid =
      'public.official_document_dispatch_records'::pg_catalog.regclass
      and trigger_row.tgfoid = identity_guard.oid
      and trigger_row.tgenabled = 'O'
      and not trigger_row.tgisinternal
      and trigger_row.tgname = 'trg_official_dispatch_record_identity_guard'
      and trigger_row.tgtype = 19
      and (
        select pg_catalog.array_agg(attribute_row.attname::text order by attribute_item.ordinality)
        from pg_catalog.unnest(trigger_row.tgattr::smallint[])
          with ordinality as attribute_item(attnum, ordinality)
        join pg_catalog.pg_attribute attribute_row
          on attribute_row.attrelid = trigger_row.tgrelid
         and attribute_row.attnum = attribute_item.attnum
      ) = array['id', 'document_id', 'created_by', 'created_at']::text[]
      and pg_catalog.regexp_replace(
        pg_catalog.lower(
          pg_catalog.pg_get_expr(trigger_row.tgqual, trigger_row.tgrelid, true)
        ),
        '[[:space:]()]',
        '',
        'g'
      ) = expected.identity_qual
  )
    and 1 = (
      select pg_catalog.count(*)
      from pg_catalog.pg_trigger trigger_row
      where trigger_row.tgrelid =
        'public.official_document_dispatch_records'::pg_catalog.regclass
        and trigger_row.tgfoid = identity_guard.oid
        and trigger_row.tgenabled <> 'D'
        and not trigger_row.tgisinternal
    ) as dispatch_identity_guard_trigger_enabled,
  2 = (
    select pg_catalog.count(*)
    from pg_catalog.pg_trigger trigger_row
    where trigger_row.tgrelid =
      'public.official_document_dispatch_records'::pg_catalog.regclass
      and trigger_row.tgfoid = capture.oid
      and trigger_row.tgenabled = 'O'
      and not trigger_row.tgisinternal
      and (
        (
          trigger_row.tgname = 'trg_official_dispatch_record_capture_insert'
          and trigger_row.tgtype = 5
          and trigger_row.tgqual is null
          and pg_catalog.cardinality(trigger_row.tgattr::smallint[]) = 0
        )
        or (
          trigger_row.tgname = 'trg_official_dispatch_record_capture_update'
          and trigger_row.tgtype = 17
          and pg_catalog.regexp_replace(
            pg_catalog.lower(
              pg_catalog.pg_get_expr(trigger_row.tgqual, trigger_row.tgrelid, true)
            ),
            '[[:space:]()]',
            '',
            'g'
          ) = expected.capture_qual
          and (
            select pg_catalog.array_agg(attribute_row.attname::text order by attribute_item.ordinality)
            from pg_catalog.unnest(trigger_row.tgattr::smallint[])
              with ordinality as attribute_item(attnum, ordinality)
            join pg_catalog.pg_attribute attribute_row
              on attribute_row.attrelid = trigger_row.tgrelid
             and attribute_row.attnum = attribute_item.attnum
          ) = array[
            'dispatch_method',
            'dispatch_owner_type',
            'dispatch_owner_user_id',
            'dispatch_status',
            'external_official_document_number',
            'dispatch_date',
            'recipient',
            'recipient_contact',
            'dispatch_note',
            'proof_file_id',
            'completed_at'
          ]::text[]
        )
      )
  )
    and 2 = (
      select pg_catalog.count(*)
      from pg_catalog.pg_trigger trigger_row
      where trigger_row.tgrelid =
        'public.official_document_dispatch_records'::pg_catalog.regclass
        and trigger_row.tgfoid = capture.oid
        and trigger_row.tgenabled <> 'D'
        and not trigger_row.tgisinternal
    ) as dispatch_capture_triggers_enabled,
  pg_catalog.has_table_privilege(
    'service_role', 'public.official_document_dispatch_events', 'SELECT'
  )
    and not pg_catalog.has_table_privilege(
      'service_role', 'public.official_document_dispatch_events', 'IN' || 'SERT'
    )
    and not pg_catalog.has_table_privilege(
      'service_role', 'public.official_document_dispatch_events', 'UP' || 'DATE'
    )
    and not pg_catalog.has_table_privilege(
      'service_role', 'public.official_document_dispatch_events', 'DE' || 'LETE'
    ) as dispatch_events_api_read_only,
  not exists (
    select 1
    from public.official_document_dispatch_records record
    where not exists (
      select 1
      from public.official_document_dispatch_events event
      where event.dispatch_record_id = record.id
    )
  ) as every_dispatch_record_has_evidence,
  not exists (
    select event.dispatch_record_id
    from public.official_document_dispatch_events event
    group by event.dispatch_record_id
    having pg_catalog.min(event.event_sequence) <> 1
       or pg_catalog.max(event.event_sequence) <> pg_catalog.count(*)
       or pg_catalog.count(*) <> pg_catalog.count(distinct event.event_sequence)
  ) as dispatch_event_sequences_contiguous
from capture_function capture
cross join public_execute
cross join identity_function identity_guard
cross join identity_public_execute
cross join expected_quals expected;

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
    ('official_document_dispatch_records', 'official_document_dispatch_records_document_key'),
    ('inbound_document_attachments', 'inbound_document_attachments_pkey'),
    ('inbound_document_attachments', 'inbound_document_attachments_inbound_document_id_fkey'),
    ('inbound_document_attachments', 'inbound_document_attachments_file_object_id_fkey'),
    ('internal_dispatches', 'internal_dispatches_pkey'),
    ('internal_dispatches', 'internal_dispatches_inbound_document_id_fkey'),
    ('internal_dispatches', 'internal_dispatches_official_document_id_fkey'),
    ('internal_dispatches', 'internal_dispatches_disposition_status_check'),
    ('internal_dispatch_recipients', 'internal_dispatch_recipients_pkey'),
    ('internal_dispatch_recipients', 'internal_dispatch_recipients_dispatch_id_fkey'),
    ('internal_dispatch_replies', 'internal_dispatch_replies_pkey'),
    ('internal_dispatch_replies', 'internal_dispatch_replies_dispatch_id_fkey'),
    ('internal_dispatch_replies', 'internal_dispatch_replies_recipient_id_fkey'),
    ('internal_dispatch_replies', 'internal_dispatch_replies_attachment_file_id_fkey'),
    ('internal_dispatch_logs', 'internal_dispatch_logs_pkey'),
    ('internal_dispatch_logs', 'internal_dispatch_logs_dispatch_id_fkey'),
    ('official_workflow_delegations', 'official_workflow_delegations_pkey'),
    ('official_workflow_delegations', 'official_workflow_delegations_company_id_fkey'),
    ('official_workflow_delegations', 'official_workflow_delegations_principal_user_id_fkey'),
    ('official_workflow_delegations', 'official_workflow_delegations_delegate_user_id_fkey'),
    ('official_workflow_delegations', 'official_workflow_delegations_created_by_fkey'),
    ('official_workflow_delegations', 'official_workflow_delegations_revoked_by_fkey'),
    ('official_workflow_delegations', 'official_workflow_delegations_distinct_users'),
    ('official_workflow_delegations', 'official_workflow_delegations_status'),
    ('official_workflow_delegations', 'official_workflow_delegations_valid_period'),
    ('official_document_stamp_positions', 'official_document_stamp_positions_pkey'),
    ('official_document_stamp_positions', 'official_document_stamp_positions_request_id_fkey'),
    ('official_document_stamp_positions', 'official_document_stamp_positions_seal_id_fkey'),
    ('official_document_stamp_positions', 'official_document_stamp_positions_locked_seal_file_id_fkey'),
    ('official_document_text_overlays', 'official_document_text_overlays_pkey'),
    ('official_document_text_overlays', 'official_document_text_overlays_request_id_fkey'),
    ('official_document_text_overlays', 'official_document_text_overlays_font_family_check'),
    ('official_document_text_overlays', 'official_document_text_overlays_font_size_check'),
    ('official_document_text_overlays', 'official_document_text_overlays_page_check'),
    ('official_document_text_overlays', 'official_document_text_overlays_text_content_check'),
    ('official_document_text_overlays', 'official_document_text_overlays_x_check'),
    ('official_document_text_overlays', 'official_document_text_overlays_y_check'),
    ('official_document_editor_revisions', 'official_document_editor_revisions_pkey'),
    ('official_document_editor_revisions', 'official_document_editor_revisions_document_id_fkey'),
    ('official_document_editor_revisions', 'official_document_editor_revisions_parent_revision_id_fkey'),
    ('official_document_editor_revisions', 'official_editor_document_revision_unique'),
    ('official_document_editor_revisions', 'official_editor_manifest_sha256_check'),
    ('official_document_editor_revisions', 'official_editor_revision_no_check'),
    ('official_document_editor_revisions', 'official_editor_schema_version_check'),
    ('official_document_editor_assets', 'official_document_editor_assets_pkey'),
    ('official_document_editor_assets', 'official_document_editor_assets_document_id_fkey'),
    ('official_document_editor_assets', 'official_document_editor_assets_editor_revision_id_fkey'),
    ('official_document_editor_assets', 'official_document_editor_assets_file_object_id_fkey'),
    ('official_document_editor_assets', 'official_document_editor_assets_official_file_id_fkey'),
    ('official_document_editor_assets', 'official_editor_asset_expected_sha256_check'),
    ('official_document_editor_assets', 'official_editor_asset_kind_check'),
    ('official_document_editor_assets', 'official_editor_asset_page_count_check'),
    ('official_document_editor_assets', 'official_editor_asset_preflight_status_check'),
    ('official_document_editor_assets', 'official_editor_asset_scan_status_check'),
    ('official_document_editor_assets', 'official_editor_asset_sha256_check'),
    ('official_document_editor_assets', 'official_editor_asset_size_check'),
    ('official_document_editor_assets', 'official_editor_asset_upload_status_check'),
    ('official_document_dispatch_events', 'official_document_dispatch_events_pkey'),
    ('official_document_dispatch_events', 'official_document_dispatch_events_dispatch_record_id_fkey'),
    ('official_document_dispatch_events', 'official_document_dispatch_events_document_id_fkey'),
    ('official_document_dispatch_events', 'official_document_dispatch_ev_dispatch_record_id_event_sequ_key'),
    ('official_document_dispatch_events', 'official_document_dispatch_events_event_sequence_check'),
    ('official_document_dispatch_events', 'official_document_dispatch_events_record_snapshot_sha256_check'),
    ('official_document_archive_exports', 'official_document_archive_exports_pkey'),
    ('official_document_archive_exports', 'official_document_archive_exports_document_id_fkey'),
    ('official_document_archive_exports', 'official_document_archive_exports_requested_by_fkey')
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
where id in (
  'DOC-IN-1140522-00018','DOC-OUT-1140522-007','DOC-OUT-1140519-006',
  'DOC-ADMIN-1140523-001'
)
union all
select 'trusted_devices', count(*) from public.trusted_devices
where id in ('ACC-DEV-001','ACC-DEV-002','ACC-DEV-003','ACC-DEV-004','ACC-DEV-005','ACC-DEV-006','ACC-DEV-007')
union all
select 'signing_certificates', count(*) from public.signing_certificates
where id in ('CERT-SEAL-001','CERT-SEAL-002','CERT-TSA-001')
union all
select 'notifications', count(*) from public.notifications
where id in ('NTF-001','NTF-002','NTF-003','NTF-004','NTF-005')
union all
select 'attachments', count(*) from public.attachments
where id in ('ATT-001','ATT-002','ATT-003')
union all
select 'attachment_security', count(*) from public.attachment_security
where id in ('ASEC-ATT-001','ASEC-ATT-002','ASEC-ATT-003')
union all
select 'exchange_tasks', count(*) from public.exchange_tasks
where id in ('TASK-001','TASK-002')
union all
select 'document_acl', count(*) from public.document_acl
where id in ('ACL-001','ACL-002','ACL-003','ACL-004','ACL-005','ACL-006','ACL-007')
union all
select 'document_acl_events', count(*) from public.document_acl_events
where id in ('ACLEVT-001','ACLEVT-002','ACLEVT-003')
union all
select 'seal_applications', count(*) from public.seal_applications
where id = 'USEAL-SEED-001'
union all
select 'recipients', count(*) from public.recipients
where id in ('REC-001','REC-002','REC-003','REC-004')
union all
select 'notification_rules', count(*) from public.notification_rules
where id in ('NRULE-001','NRULE-002','NRULE-003','NRULE-004','NRULE-005')
union all
select 'fresh_finance_bootstrap_sentinel', count(*)
from public.finance_organization_projection_state
where finance_tenant_id = '__edoc_fresh_bootstrap_only__';

-- 8b. Runtime audit-chain hardening. Pass condition: private chain and
-- transition state are forced-RLS, the transition row is immutable, browser
-- view access is false, backend view access is true and the single private
-- helper grant is exact.
select
  pg_catalog.to_regclass('edoc_private.audit_log_chain_heads') is not null
    and exists (
      select 1
      from pg_catalog.pg_class relation_row
      join pg_catalog.pg_namespace namespace_row
        on namespace_row.oid = relation_row.relnamespace
      where namespace_row.nspname = 'edoc_private'
        and relation_row.relname = 'audit_log_chain_heads'
        and relation_row.relrowsecurity
        and relation_row.relforcerowsecurity
    )
    and pg_catalog.to_regclass('edoc_private.audit_log_chain_transitions') is not null
    and exists (
      select 1
      from pg_catalog.pg_class relation_row
      join pg_catalog.pg_namespace namespace_row
        on namespace_row.oid = relation_row.relnamespace
      where namespace_row.nspname = 'edoc_private'
        and relation_row.relname = 'audit_log_chain_transitions'
        and relation_row.relrowsecurity
        and relation_row.relforcerowsecurity
    ) as forced_private_chain_state,
  2 = (
    select pg_catalog.count(*)
    from pg_catalog.pg_trigger trigger_row
    where trigger_row.tgrelid =
      'edoc_private.audit_log_chain_transitions'::pg_catalog.regclass
      and trigger_row.tgname in (
        'trg_audit_log_chain_transitions_no_mutation',
        'trg_audit_log_chain_transitions_no_truncate'
      )
      and trigger_row.tgenabled = 'O'
      and not trigger_row.tgisinternal
  )
    and not pg_catalog.has_table_privilege(
      'service_role',
      'edoc_private.audit_log_chain_transitions',
      'SELECT'
    )
    and not pg_catalog.has_table_privilege(
      'service_role',
      'edoc_private.audit_log_chain_transitions',
      'IN' || 'SERT'
    )
    and not pg_catalog.has_table_privilege(
      'service_role',
      'edoc_private.audit_log_chain_transitions',
      'UP' || 'DATE'
    )
    and not pg_catalog.has_table_privilege(
      'service_role',
      'edoc_private.audit_log_chain_transitions',
      'DE' || 'LETE'
    )
    and not pg_catalog.has_table_privilege(
      'service_role',
      'edoc_private.audit_log_chain_transitions',
      'TRUN' || 'CATE'
    ) as immutable_private_transition_state,
  pg_catalog.to_regprocedure('extensions.digest(bytea,text)') is not null
    and pg_catalog.to_regprocedure('extensions.gen_random_bytes(integer)') is not null
    as pgcrypto_runtime_bound,
  pg_catalog.has_table_privilege('authenticated', 'public.audit_log_chain_check', 'SELECT')
    as browser_view_access,
  pg_catalog.has_table_privilege('service_role', 'public.audit_log_chain_check', 'SELECT')
    as backend_view_access,
  pg_catalog.has_schema_privilege('service_role', 'edoc_private', 'USAGE')
    and pg_catalog.has_function_privilege(
      'service_role',
      'edoc_private.audit_log_hash_payload(text,text,text,text,text,text,text,text,text,text)',
      'EXECUTE'
    ) as backend_private_hash_helper_access,
  not exists (
    select 1
    from pg_catalog.pg_proc procedure_row
    join pg_catalog.pg_namespace namespace_row
      on namespace_row.oid = procedure_row.pronamespace
    where namespace_row.nspname = 'edoc_private'
      and pg_catalog.has_function_privilege('service_role', procedure_row.oid, 'EXECUTE')
      and procedure_row.oid <>
        'edoc_private.audit_log_hash_payload(text,text,text,text,text,text,text,text,text,text)'::pg_catalog.regprocedure
  ) as no_unexpected_private_function_access;

-- 8c. End-to-end audit continuity. Pass condition:
-- chain_continuity_valid=true. Historical v1 rows may contain immutable forks
-- from the legacy second-resolution writer. Every v1 payload and parent edge
-- must still be valid and reachable from one root; a canonical set commitment
-- seals all branches. The v2 segment must be a single line beginning at that
-- commitment and ending at the current private head.
with recursive computed_v1 as (
  select
    pg_catalog.count(*)::bigint as source_row_count,
    pg_catalog.encode(
      extensions.digest(
        pg_catalog.convert_to(
          pg_catalog.concat_ws(
            '|',
            'EDOC-AUDIT-V1-SET-COMMITMENT-V1',
            pg_catalog.count(*)::text,
            coalesce(
              pg_catalog.string_agg(
                entry_hash collate "C",
                '|' order by entry_hash collate "C"
              ),
              ''
            )
          ),
          'UTF8'
        ),
        'sha256'
      ),
      'hex'
    ) as source_commitment
  from public.audit_logs
  where chain_version = 1
), transition_state as (
  select transition_row.*
  from edoc_private.audit_log_chain_transitions transition_row
  where transition_row.target_chain_version = 2
    and transition_row.source_chain_version = 1
), v1_walked as (
  select audit_row.id, audit_row.entry_hash, 1 as depth
  from public.audit_logs audit_row
  where audit_row.chain_version = 1
    and (
      audit_row.previous_hash is null
      or audit_row.previous_hash = 'GENESIS'
    )

  union all

  select child.id, child.entry_hash, parent.depth + 1
  from v1_walked parent
  join public.audit_logs child
    on child.chain_version = 1
   and child.previous_hash = parent.entry_hash
  where parent.depth < (
    select pg_catalog.count(*) from public.audit_logs where chain_version = 1
  )
), v2_walked as (
  select audit_row.id, audit_row.entry_hash, 1 as depth
  from transition_state transition_row
  join public.audit_logs audit_row
    on audit_row.chain_version = 2
   and audit_row.previous_hash = transition_row.source_commitment

  union all

  select child.id, child.entry_hash, parent.depth + 1
  from v2_walked parent
  join public.audit_logs child
    on child.chain_version = 2
   and child.previous_hash = parent.entry_hash
  where parent.depth < (
    select pg_catalog.count(*) from public.audit_logs where chain_version = 2
  )
), v1_stats as (
  select
    (
      select pg_catalog.count(*)
      from public.audit_logs
      where chain_version = 1
    ) as total_rows,
    (select pg_catalog.count(*) from v1_walked) as walked_rows,
    (
      select pg_catalog.count(*)
      from public.audit_logs
      where chain_version = 1
        and (previous_hash is null or previous_hash = 'GENESIS')
    ) as root_count,
    (
      select pg_catalog.count(*)
      from public.audit_logs terminal
      where terminal.chain_version = 1
        and not exists (
          select 1 from public.audit_logs child
          where child.chain_version = 1
            and child.previous_hash = terminal.entry_hash
        )
    ) as terminal_count,
    (
      select pg_catalog.count(*)
      from public.audit_logs child
      where child.chain_version = 1
        and child.previous_hash is not null
        and child.previous_hash <> 'GENESIS'
        and not exists (
          select 1 from public.audit_logs parent
          where parent.chain_version = 1
            and parent.entry_hash = child.previous_hash
        )
    ) as missing_parent_count,
    (
      select pg_catalog.count(*)
      from (
        select previous_hash
        from public.audit_logs
        where chain_version = 1
          and previous_hash is not null
          and previous_hash <> 'GENESIS'
        group by previous_hash
        having pg_catalog.count(*) > 1
      ) forked
    ) as fork_count,
    (
      select pg_catalog.count(*)
      from public.audit_log_chain_check chain_check
      join public.audit_logs audit_row on audit_row.id = chain_check.id
      where audit_row.chain_version = 1
        and chain_check.hash_valid is distinct from true
    ) as invalid_hash_count,
    (
      select pg_catalog.count(*)
      from public.audit_logs
      where chain_version = 1
        and immutable is distinct from true
    ) as mutable_row_count,
    (
      select pg_catalog.count(*)
      from (
        select entry_hash
        from public.audit_logs
        where chain_version = 1
        group by entry_hash
        having pg_catalog.count(*) <> 1
      ) duplicate_hashes
    ) as duplicate_hash_count
), v2_stats as (
  select
    (
      select pg_catalog.count(*)
      from public.audit_logs
      where chain_version = 2
    ) as total_rows,
    (select pg_catalog.count(*) from v2_walked) as walked_rows,
    (
      select pg_catalog.count(*)
      from transition_state transition_row
      join public.audit_logs audit_row
        on audit_row.chain_version = 2
       and audit_row.previous_hash = transition_row.source_commitment
    ) as root_count,
    (
      select pg_catalog.count(*)
      from public.audit_logs terminal
      where terminal.chain_version = 2
        and not exists (
          select 1 from public.audit_logs child
          where child.chain_version = 2
            and child.previous_hash = terminal.entry_hash
        )
    ) as terminal_count,
    (
      select pg_catalog.count(*)
      from public.audit_logs child
      where child.chain_version = 2
        and not exists (
          select 1
          from transition_state transition_row
          where child.previous_hash = transition_row.source_commitment
        )
        and not exists (
          select 1 from public.audit_logs parent
          where parent.chain_version = 2
            and parent.entry_hash = child.previous_hash
        )
    ) as missing_parent_count,
    (
      select pg_catalog.count(*)
      from (
        select previous_hash
        from public.audit_logs
        where chain_version = 2
        group by previous_hash
        having pg_catalog.count(*) > 1
      ) forked
    ) as fork_count,
    (
      select pg_catalog.count(*)
      from public.audit_log_chain_check chain_check
      join public.audit_logs audit_row on audit_row.id = chain_check.id
      where audit_row.chain_version = 2
        and chain_check.hash_valid is distinct from true
    ) as invalid_hash_count,
    (
      select pg_catalog.count(*)
      from public.audit_logs
      where chain_version = 2
        and immutable is distinct from true
    ) as mutable_row_count,
    (
      select pg_catalog.count(*)
      from (
        select entry_hash
        from public.audit_logs
        where chain_version = 2
        group by entry_hash
        having pg_catalog.count(*) <> 1
      ) duplicate_hashes
    ) as duplicate_hash_count,
    (
      select pg_catalog.count(*)
      from public.audit_logs
      where chain_version = 2
        and (previous_hash is null or previous_hash = 'GENESIS')
    ) as legacy_root_count
), v2_terminal as (
  select terminal.id, terminal.entry_hash
  from public.audit_logs terminal
  where terminal.chain_version = 2
    and not exists (
      select 1 from public.audit_logs child
      where child.chain_version = 2
        and child.previous_hash = terminal.entry_hash
    )
), version_stats as (
  select
    (
      select pg_catalog.count(*)
      from public.audit_logs child
      join public.audit_logs parent on parent.entry_hash = child.previous_hash
      where child.chain_version < parent.chain_version
    ) as version_order_violation_count,
    (
      select pg_catalog.count(*)
      from public.audit_logs
      where chain_version is distinct from 1
        and chain_version is distinct from 2
    ) as unsupported_version_count
)
select
  v1_stats.total_rows as v1_total_rows,
  v1_stats.walked_rows as v1_walked_rows,
  v1_stats.root_count as v1_root_count,
  v1_stats.terminal_count as v1_terminal_count,
  v1_stats.missing_parent_count as v1_missing_parent_count,
  v1_stats.fork_count as v1_fork_count,
  v1_stats.invalid_hash_count as v1_invalid_hash_count,
  v1_stats.mutable_row_count as v1_mutable_row_count,
  v1_stats.duplicate_hash_count as v1_duplicate_hash_count,
  v2_stats.total_rows as v2_total_rows,
  v2_stats.walked_rows as v2_walked_rows,
  v2_stats.root_count as v2_root_count,
  v2_stats.terminal_count as v2_terminal_count,
  v2_stats.missing_parent_count as v2_missing_parent_count,
  v2_stats.fork_count as v2_fork_count,
  v2_stats.invalid_hash_count as v2_invalid_hash_count,
  v2_stats.mutable_row_count as v2_mutable_row_count,
  v2_stats.duplicate_hash_count as v2_duplicate_hash_count,
  version_stats.version_order_violation_count,
  version_stats.unsupported_version_count,
  (
    (select pg_catalog.count(*) from transition_state) = 1
    and exists (
      select 1
      from transition_state transition_row
      cross join computed_v1 commitment
      where transition_row.source_row_count = commitment.source_row_count
        and transition_row.commitment_algorithm =
          'sha256-sorted-entry-hash-set-v1-c-collation'
        and transition_row.source_commitment = commitment.source_commitment
        and transition_row.source_root_count = v1_stats.root_count
        and transition_row.source_terminal_count = v1_stats.terminal_count
        and transition_row.source_fork_count = v1_stats.fork_count
    )
  ) as source_transition_valid,
  (
    (
      v2_stats.total_rows = 0
      and exists (
        select 1
        from edoc_private.audit_log_chain_heads chain_head
        cross join transition_state transition_row
        where chain_head.chain_version = 2
          and chain_head.head_hash = transition_row.source_commitment
          and chain_head.last_audit_id is null
      )
    )
    or (
      v2_stats.total_rows > 0
      and exists (
        select 1
        from v2_terminal terminal
        join edoc_private.audit_log_chain_heads chain_head
          on chain_head.chain_version = 2
         and chain_head.last_audit_id = terminal.id
         and chain_head.head_hash = terminal.entry_hash
      )
    )
  ) as private_head_matches_terminal,
  (
    v1_stats.total_rows = v1_stats.walked_rows
    and v1_stats.root_count = case when v1_stats.total_rows = 0 then 0 else 1 end
    and (
      (v1_stats.total_rows = 0 and v1_stats.terminal_count = 0)
      or (v1_stats.total_rows > 0 and v1_stats.terminal_count >= 1)
    )
    and v1_stats.missing_parent_count = 0
    and v1_stats.invalid_hash_count = 0
    and v1_stats.mutable_row_count = 0
    and v1_stats.duplicate_hash_count = 0
    and (select pg_catalog.count(*) from transition_state) = 1
    and exists (
      select 1
      from transition_state transition_row
      cross join computed_v1 commitment
      where transition_row.source_row_count = commitment.source_row_count
        and transition_row.commitment_algorithm =
          'sha256-sorted-entry-hash-set-v1-c-collation'
        and transition_row.source_commitment = commitment.source_commitment
        and transition_row.source_root_count = v1_stats.root_count
        and transition_row.source_terminal_count = v1_stats.terminal_count
        and transition_row.source_fork_count = v1_stats.fork_count
    )
    and v2_stats.total_rows = v2_stats.walked_rows
    and v2_stats.root_count = case when v2_stats.total_rows = 0 then 0 else 1 end
    and v2_stats.terminal_count = case when v2_stats.total_rows = 0 then 0 else 1 end
    and v2_stats.missing_parent_count = 0
    and v2_stats.fork_count = 0
    and v2_stats.invalid_hash_count = 0
    and v2_stats.mutable_row_count = 0
    and v2_stats.duplicate_hash_count = 0
    and v2_stats.legacy_root_count = 0
    and version_stats.version_order_violation_count = 0
    and version_stats.unsupported_version_count = 0
    and (
      (
        v2_stats.total_rows = 0
        and exists (
          select 1
          from edoc_private.audit_log_chain_heads chain_head
          cross join transition_state transition_row
          where chain_head.chain_version = 2
            and chain_head.head_hash = transition_row.source_commitment
            and chain_head.last_audit_id is null
        )
      )
      or (
        v2_stats.total_rows > 0
        and exists (
          select 1
          from v2_terminal terminal
          join edoc_private.audit_log_chain_heads chain_head
            on chain_head.chain_version = 2
           and chain_head.last_audit_id = terminal.id
           and chain_head.head_hash = terminal.entry_hash
        )
      )
    )
  ) as chain_continuity_valid
from v1_stats
cross join v2_stats
cross join version_stats;

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
select exists (
  select 1
  from pg_catalog.pg_index index_row
  where index_row.indexrelid =
    pg_catalog.to_regclass('public.idx_audit_logs_chain_parent')
    and index_row.indrelid = 'public.audit_logs'::pg_catalog.regclass
    and index_row.indisvalid
    and index_row.indisready
    and not index_row.indisunique
    and index_row.indpred is null
    and index_row.indexprs is null
    and index_row.indnkeyatts = 2
    and index_row.indnatts = 2
    and index_row.indkey[0] = (
      select attribute_row.attnum
      from pg_catalog.pg_attribute attribute_row
      where attribute_row.attrelid = 'public.audit_logs'::pg_catalog.regclass
        and attribute_row.attname = 'chain_version'
        and not attribute_row.attisdropped
    )
    and index_row.indkey[1] = (
      select attribute_row.attnum
      from pg_catalog.pg_attribute attribute_row
      where attribute_row.attrelid = 'public.audit_logs'::pg_catalog.regclass
        and attribute_row.attname = 'previous_hash'
        and not attribute_row.attisdropped
    )
) as audit_chain_parent_index_valid;

with required_indexes(index_name) as (
  values
    ('idx_audit_logs_chain_parent'),
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
