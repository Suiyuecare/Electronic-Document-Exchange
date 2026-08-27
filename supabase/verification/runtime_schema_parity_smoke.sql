-- Fresh-bootstrap runtime schema parity smoke.
--
-- This is a read-only structural check: it contains no business/demo data and
-- never selects application rows. Run it after `supabase db reset --local`.

do $runtime_schema_smoke$
declare
  v_table_name text;
  v_table_oid regclass;
  v_role_name text;
  v_privilege_name text;
begin
  foreach v_table_name in array array[
    'inbound_document_attachments',
    'internal_dispatches',
    'internal_dispatch_recipients',
    'internal_dispatch_replies',
    'internal_dispatch_logs',
    'official_document_stamp_positions',
    'official_document_text_overlays',
    'official_document_editor_revisions',
    'official_document_editor_assets',
    'official_document_dispatch_events',
    'official_document_archive_exports',
    'official_workflow_delegations'
  ]
  loop
    v_table_oid := pg_catalog.to_regclass(
      pg_catalog.format('%I.%I', 'public', v_table_name)
    );
    if v_table_oid is null then
      raise exception 'runtime_schema_table_missing:%', v_table_name;
    end if;

    if not exists (
      select 1
      from pg_catalog.pg_class relation
      where relation.oid = v_table_oid
        and relation.relkind in ('r', 'p')
        and relation.relrowsecurity
    ) then
      raise exception 'runtime_schema_rls_disabled:%', v_table_name;
    end if;

    if not exists (
      select 1
      from pg_catalog.pg_constraint constraint_row
      where constraint_row.conrelid = v_table_oid
        and constraint_row.contype = 'p'
    ) then
      raise exception 'runtime_schema_primary_key_missing:%', v_table_name;
    end if;

    -- Backend mediation is mandatory. A PUBLIC grant is inherited by both
    -- browser roles, so has_table_privilege catches explicit and inherited
    -- browser access without relying on policy names.
    foreach v_role_name in array array['anon', 'authenticated']
    loop
      foreach v_privilege_name in array array[
        'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'
      ]
      loop
        if pg_catalog.has_table_privilege(
          v_role_name,
          v_table_oid,
          v_privilege_name
        ) then
          raise exception 'runtime_schema_browser_grant_present:%:%:%',
            v_table_name, v_role_name, v_privilege_name;
        end if;
      end loop;
    end loop;

    if not pg_catalog.has_table_privilege(
      'service_role',
      v_table_oid,
      'SELECT'
    ) then
      raise exception 'runtime_schema_service_select_missing:%', v_table_name;
    end if;
  end loop;

  -- Legacy seal locking updates existing placements before submission, while
  -- draft replacement deletes and recreates the placement set.
  v_table_oid := 'public.official_document_stamp_positions'::regclass;
  foreach v_privilege_name in array array['INSERT', 'UPDATE', 'DELETE']
  loop
    if not pg_catalog.has_table_privilege(
      'service_role',
      v_table_oid,
      v_privilege_name
    ) then
      raise exception 'runtime_schema_service_write_missing:%:%',
        'official_document_stamp_positions', v_privilege_name;
    end if;
  end loop;

  -- Text overlays are replace-all records. The backend reads, deletes and
  -- recreates them; direct UPDATE is intentionally absent by least privilege.
  v_table_oid := 'public.official_document_text_overlays'::regclass;
  if not pg_catalog.has_table_privilege('service_role', v_table_oid, 'INSERT')
     or pg_catalog.has_table_privilege('service_role', v_table_oid, 'UPDATE')
     or not pg_catalog.has_table_privilege('service_role', v_table_oid, 'DELETE') then
    raise exception 'runtime_schema_text_overlay_grant_invalid';
  end if;

  -- Mutable headers and asset state are never directly deleted.
  foreach v_table_name in array array[
    'internal_dispatches',
    'internal_dispatch_recipients',
    'official_document_editor_assets',
    'official_workflow_delegations'
  ]
  loop
    v_table_oid := pg_catalog.to_regclass(
      pg_catalog.format('%I.%I', 'public', v_table_name)
    );
    if not pg_catalog.has_table_privilege('service_role', v_table_oid, 'INSERT')
       or not pg_catalog.has_table_privilege('service_role', v_table_oid, 'UPDATE')
       or pg_catalog.has_table_privilege('service_role', v_table_oid, 'DELETE') then
      raise exception 'runtime_schema_update_only_grant_invalid:%', v_table_name;
    end if;
  end loop;

  -- Immutable evidence and append-only reply/log tables expose only the
  -- operations used by the backend.
  foreach v_table_name in array array[
    'inbound_document_attachments',
    'internal_dispatch_replies',
    'internal_dispatch_logs',
    'official_document_editor_revisions',
    'official_document_dispatch_events'
  ]
  loop
    v_table_oid := pg_catalog.to_regclass(
      pg_catalog.format('%I.%I', 'public', v_table_name)
    );
    if not pg_catalog.has_table_privilege('service_role', v_table_oid, 'INSERT')
       or pg_catalog.has_table_privilege('service_role', v_table_oid, 'UPDATE')
       or pg_catalog.has_table_privilege('service_role', v_table_oid, 'DELETE') then
      raise exception 'runtime_schema_immutable_grant_invalid:%', v_table_name;
    end if;
  end loop;

  v_table_oid := 'public.official_document_archive_exports'::regclass;
  if pg_catalog.has_table_privilege('service_role', v_table_oid, 'INSERT')
     or pg_catalog.has_table_privilege('service_role', v_table_oid, 'UPDATE')
     or pg_catalog.has_table_privilege('service_role', v_table_oid, 'DELETE') then
    raise exception 'runtime_schema_archive_grant_invalid';
  end if;

  if exists (
    select required.index_name
    from (
      values
        ('idx_inbound_attachments_document'),
        ('idx_inbound_attachments_file_object'),
        ('idx_internal_dispatches_status'),
        ('idx_internal_dispatches_inbound_document'),
        ('idx_internal_dispatches_official_document'),
        ('idx_internal_dispatch_recipients_action'),
        ('idx_internal_dispatch_recipients_user'),
        ('idx_internal_dispatch_replies_dispatch'),
        ('idx_internal_dispatch_replies_recipient'),
        ('idx_internal_dispatch_replies_attachment'),
        ('idx_internal_dispatch_logs_dispatch'),
        ('idx_official_workflow_delegations_lookup'),
        ('idx_official_stamp_positions_request'),
        ('idx_official_stamp_positions_seal'),
        ('idx_official_text_overlays_request'),
        ('idx_official_editor_revisions_parent'),
        ('idx_official_editor_assets_document'),
        ('idx_official_editor_assets_revision'),
        ('idx_official_dispatch_events_document_created'),
        ('idx_official_archive_exports_document_created'),
        ('idx_official_archive_exports_requested_by')
    ) as required(index_name)
    where pg_catalog.to_regclass(
      pg_catalog.format('%I.%I', 'public', required.index_name)
    ) is null
  ) then
    raise exception 'runtime_schema_required_index_missing';
  end if;
end
$runtime_schema_smoke$;

select 'runtime_schema_parity_smoke_ok' as result;
