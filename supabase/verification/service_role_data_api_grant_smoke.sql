-- Deterministic service-role Data API grant smoke for a freshly rebuilt
-- Supabase project. No business rows are selected and no data is committed.

begin;

do $service_role_table_matrix$
declare
  v_row record;
  v_table regclass;
  v_expected boolean;
begin
  for v_row in
    select * from (values
      ('approval_step_actor_snapshots', 'SI'),
      ('attachment_security', 'S'),
      ('attachments', 'S'),
      ('audit_logs', 'SI'),
      ('auth_sessions', 'SIU'),
      ('background_jobs', 'SU'),
      ('certificate_authorities', 'S'),
      ('certificate_validation_events', 'SI'),
      ('companies', 'SIU'),
      ('company_registry', 'SIU'),
      ('company_seal_files', 'S'),
      ('company_seals', 'SIU'),
      ('compliance_attestations', 'SI'),
      ('contract_approvals', 'S'),
      ('contract_parties', 'S'),
      ('contracts', 'S'),
      ('department_registry', 'S'),
      ('document_acl', 'S'),
      ('document_acl_events', 'S'),
      ('documents', 'SIU'),
      ('electronic_signatures', 'S'),
      ('exchange_attachment', 'S'),
      ('exchange_events', 'SI'),
      ('exchange_inbox', 'SIU'),
      ('exchange_log', 'SI'),
      ('exchange_outbox', 'SIU'),
      ('exchange_status_history', 'SI'),
      ('exchange_tasks', 'SU'),
      ('file_access_logs', 'SI'),
      ('file_download_tokens', 'S'),
      ('file_objects', 'SIUD'),
      ('inbound_document_attachments', 'SI'),
      ('inbound_documents', 'SIU'),
      ('internal_dispatch_logs', 'SI'),
      ('internal_dispatch_recipients', 'SIU'),
      ('internal_dispatch_replies', 'SI'),
      ('internal_dispatches', 'SIU'),
      ('ip_allowlist', 'S'),
      ('job_runs', 'SI'),
      ('login_events', 'SI'),
      ('module_account_links', 'SIU'),
      ('notification_channel_credentials', 'SU'),
      ('notification_deliveries', 'SI'),
      ('notification_rules', 'S'),
      ('notifications', 'SIU'),
      ('official_document_approval_logs', 'SI'),
      ('official_document_approval_steps', 'SIU'),
      ('official_document_archive_exports', 'S'),
      ('official_document_dispatch_events', 'S'),
      ('official_document_dispatch_records', 'SU'),
      ('official_document_editor_assets', 'SIU'),
      ('official_document_editor_revisions', 'SI'),
      ('official_document_files', 'SI'),
      ('official_document_stamp_positions', 'SIUD'),
      ('official_document_stamp_requests', 'SIU'),
      ('official_document_text_overlays', 'SID'),
      ('official_documents', 'SIU'),
      ('official_workflow_delegations', 'S'),
      ('pdf_versions', 'SI'),
      ('permissions', 'S'),
      ('recipients', 'S'),
      ('role_permissions', 'S'),
      ('roles', 'S'),
      ('seal_applications', 'S'),
      ('seal_assets', 'S'),
      ('seal_permissions', 'SI'),
      ('seal_reference_options', 'S'),
      ('seal_type_registry', 'S'),
      ('seal_usage_approvals', 'SIU'),
      ('seal_usage_logs', 'SI'),
      ('seal_usage_requests', 'SIU'),
      ('settings', 'SIU'),
      ('signature_provider_events', 'S'),
      ('signing_certificates', 'S'),
      ('sso_providers', 'S'),
      ('system_inbox', 'SIU'),
      ('trusted_devices', 'S'),
      ('tsa_timestamp_tokens', 'S'),
      ('users', 'SIU'),
      ('virus_scan_jobs', 'SI'),
      ('workflow_tasks', 'S'),
      ('finance_member_sync_nonces', 'SID'),
      ('finance_member_sync_receipts', 'SIU'),
      ('finance_organization_projection_state', 'S'),
      ('finance_organization_units', 'S'),
      ('official_document_rejection_jobs', 'SU'),
      ('portal_handoff_nonces', 'SI')
    ) as expected(table_name, operations)
  loop
    v_table := pg_catalog.to_regclass(
      pg_catalog.format('%I.%I', 'public', v_row.table_name)
    );
    if v_table is null then
      raise exception 'service_role_table_missing:%', v_row.table_name;
    end if;

    if not exists (
      select 1
      from pg_catalog.pg_class relation_row
      where relation_row.oid = v_table
        and pg_catalog.pg_get_userbyid(relation_row.relowner) = 'postgres'
    ) then
      raise exception 'service_role_table_owner_mismatch:%', v_row.table_name;
    end if;

    v_expected := position('S' in v_row.operations) > 0;
    if pg_catalog.has_table_privilege('service_role', v_table, 'SELECT') is distinct from v_expected then
      raise exception 'service_role_table_grant_mismatch:%:SELECT', v_row.table_name;
    end if;
    v_expected := position('I' in v_row.operations) > 0;
    if pg_catalog.has_table_privilege('service_role', v_table, 'INSERT') is distinct from v_expected then
      raise exception 'service_role_table_grant_mismatch:%:INSERT', v_row.table_name;
    end if;
    v_expected := position('U' in v_row.operations) > 0;
    if pg_catalog.has_table_privilege('service_role', v_table, 'UPDATE') is distinct from v_expected then
      raise exception 'service_role_table_grant_mismatch:%:UPDATE', v_row.table_name;
    end if;
    v_expected := position('D' in v_row.operations) > 0;
    if pg_catalog.has_table_privilege('service_role', v_table, 'DELETE') is distinct from v_expected then
      raise exception 'service_role_table_grant_mismatch:%:DELETE', v_row.table_name;
    end if;
    if pg_catalog.has_table_privilege('service_role', v_table, 'TRUNCATE')
       or pg_catalog.has_table_privilege('service_role', v_table, 'REFERENCES')
       or pg_catalog.has_table_privilege('service_role', v_table, 'TRIGGER') then
      raise exception 'service_role_table_extra_privilege:%', v_row.table_name;
    end if;
  end loop;

  if exists (
    select 1
    from information_schema.table_privileges privilege_row
    where privilege_row.table_schema = 'public'
      and privilege_row.grantee = 'service_role'
      and not (
        privilege_row.table_name = 'audit_log_chain_check'
        and privilege_row.privilege_type = 'SELECT'
      )
      and not exists (
        select 1
        from (values
          ('approval_step_actor_snapshots'), ('attachment_security'), ('attachments'),
          ('audit_logs'), ('auth_sessions'), ('background_jobs'),
          ('certificate_authorities'), ('certificate_validation_events'),
          ('companies'), ('company_registry'), ('company_seal_files'),
          ('company_seals'), ('compliance_attestations'), ('contract_approvals'),
          ('contract_parties'), ('contracts'), ('department_registry'),
          ('document_acl'), ('document_acl_events'), ('documents'),
          ('electronic_signatures'), ('exchange_attachment'), ('exchange_events'),
          ('exchange_inbox'), ('exchange_log'), ('exchange_outbox'),
          ('exchange_status_history'), ('exchange_tasks'), ('file_access_logs'),
          ('file_download_tokens'), ('file_objects'),
          ('inbound_document_attachments'), ('inbound_documents'),
          ('internal_dispatch_logs'), ('internal_dispatch_recipients'),
          ('internal_dispatch_replies'), ('internal_dispatches'), ('ip_allowlist'),
          ('job_runs'), ('login_events'), ('module_account_links'),
          ('notification_channel_credentials'), ('notification_deliveries'),
          ('notification_rules'), ('notifications'),
          ('official_document_approval_logs'), ('official_document_approval_steps'),
          ('official_document_archive_exports'), ('official_document_dispatch_events'),
          ('official_document_dispatch_records'), ('official_document_editor_assets'),
          ('official_document_editor_revisions'), ('official_document_files'),
          ('official_document_stamp_positions'), ('official_document_stamp_requests'),
          ('official_document_text_overlays'), ('official_documents'),
          ('official_workflow_delegations'), ('pdf_versions'), ('permissions'),
          ('recipients'), ('role_permissions'), ('roles'), ('seal_applications'),
          ('seal_assets'), ('seal_permissions'), ('seal_reference_options'),
          ('seal_type_registry'), ('seal_usage_approvals'), ('seal_usage_logs'),
          ('seal_usage_requests'), ('settings'), ('signature_provider_events'),
          ('signing_certificates'), ('sso_providers'), ('system_inbox'),
          ('trusted_devices'), ('tsa_timestamp_tokens'), ('users'),
          ('virus_scan_jobs'), ('workflow_tasks'), ('finance_member_sync_nonces'),
          ('finance_member_sync_receipts'), ('finance_organization_projection_state'),
          ('finance_organization_units'), ('official_document_rejection_jobs'),
          ('portal_handoff_nonces')
        ) allowed(table_name)
        where allowed.table_name = privilege_row.table_name
      )
  ) then
    raise exception 'service_role_unexpected_public_table_grant';
  end if;
end
$service_role_table_matrix$;

do $service_role_default_acl_matrix$
begin
  if exists (
    select 1
    from pg_catalog.pg_default_acl default_acl
    join pg_catalog.pg_roles owner_role
      on owner_role.oid = default_acl.defaclrole
    join pg_catalog.pg_namespace namespace_row
      on namespace_row.oid = default_acl.defaclnamespace
    cross join lateral pg_catalog.aclexplode(default_acl.defaclacl) privilege_row
    where owner_role.rolname = 'postgres'
      and namespace_row.nspname = 'public'
      and (
        privilege_row.grantee = 0
        or pg_catalog.pg_get_userbyid(privilege_row.grantee)
          in ('anon', 'authenticated', 'service_role')
      )
  ) or exists (
    select 1
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
  ) then
    raise exception 'service_role_unexpected_public_default_acl';
  end if;
end
$service_role_default_acl_matrix$;

do $service_role_function_matrix$
declare
  v_signature text;
  v_oid regprocedure;
  v_unexpected integer;
begin
  for v_signature in
    select signature from (values
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
    ) allowed(signature)
  loop
    v_oid := pg_catalog.to_regprocedure(v_signature);
    if v_oid is null
       or not exists (
         select 1
         from pg_catalog.pg_proc procedure_row
         where procedure_row.oid = v_oid
           and pg_catalog.pg_get_userbyid(procedure_row.proowner) = 'postgres'
       )
       or not pg_catalog.has_function_privilege('service_role', v_oid, 'EXECUTE')
       or pg_catalog.has_function_privilege('anon', v_oid, 'EXECUTE')
       or pg_catalog.has_function_privilege('authenticated', v_oid, 'EXECUTE') then
      raise exception 'service_role_function_grant_mismatch:%', v_signature;
    end if;
  end loop;

  select pg_catalog.count(*) into v_unexpected
  from pg_catalog.pg_proc procedure_row
  join pg_catalog.pg_namespace namespace_row
    on namespace_row.oid = procedure_row.pronamespace
  where namespace_row.nspname = 'public'
    and pg_catalog.has_function_privilege('service_role', procedure_row.oid, 'EXECUTE')
    and procedure_row.oid not in (
      select pg_catalog.to_regprocedure(signature)
      from (values
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
      ) allowed(signature)
    );
  if v_unexpected <> 0 then
    raise exception 'service_role_unexpected_public_function_grant:%', v_unexpected;
  end if;

  if not pg_catalog.has_schema_privilege('service_role', 'edoc_private', 'USAGE')
     or not pg_catalog.has_function_privilege(
       'service_role',
       'edoc_private.audit_log_hash_payload(text,text,text,text,text,text,text,text,text,text)',
       'EXECUTE'
     ) then
    raise exception 'service_role_audit_view_helper_grant_missing';
  end if;

  select pg_catalog.count(*) into v_unexpected
  from pg_catalog.pg_proc procedure_row
  join pg_catalog.pg_namespace namespace_row
    on namespace_row.oid = procedure_row.pronamespace
  where namespace_row.nspname = 'edoc_private'
    and pg_catalog.has_function_privilege('service_role', procedure_row.oid, 'EXECUTE')
    and procedure_row.oid <> 'edoc_private.audit_log_hash_payload(text,text,text,text,text,text,text,text,text,text)'::pg_catalog.regprocedure;
  if v_unexpected <> 0 then
    raise exception 'service_role_unexpected_private_function_grant:%', v_unexpected;
  end if;
end
$service_role_function_matrix$;

-- These queries execute under the actual runtime role rather than merely
-- inspecting ACL metadata. The audit view call proves its private hash helper
-- remains reachable after the global function reset.
set local role service_role;
select id from public.users order by id limit 1;
select id, hash_valid from public.audit_log_chain_check order by id limit 1;
reset role;

rollback;
