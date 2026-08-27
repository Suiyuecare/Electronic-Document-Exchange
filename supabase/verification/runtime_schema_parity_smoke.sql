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
  v_dispatch_capture_qual text :=
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
    || 'old.completed_atisdistinctfromnew.completed_at';
  v_dispatch_identity_qual text :=
    'old.idisdistinctfromnew.idor'
    || 'old.document_idisdistinctfromnew.document_idor'
    || 'old.created_byisdistinctfromnew.created_byor'
    || 'old.created_atisdistinctfromnew.created_at';
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
    'official_document_editor_assets'
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
    'official_document_editor_revisions'
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

  -- These records are created or mutated only inside allowlisted
  -- SECURITY DEFINER RPCs (or are read-only archive evidence). Direct
  -- PostgREST access is SELECT-only.
  foreach v_table_name in array array[
    'official_document_dispatch_events',
    'official_document_archive_exports',
    'official_workflow_delegations'
  ]
  loop
    v_table_oid := pg_catalog.to_regclass(
      pg_catalog.format('%I.%I', 'public', v_table_name)
    );
    if pg_catalog.has_table_privilege('service_role', v_table_oid, 'INSERT')
       or pg_catalog.has_table_privilege('service_role', v_table_oid, 'UPDATE')
       or pg_catalog.has_table_privilege('service_role', v_table_oid, 'DELETE') then
      raise exception 'runtime_schema_rpc_owned_grant_invalid:%', v_table_name;
    end if;
  end loop;

  -- Dispatch event evidence is populated only by a private database trigger.
  -- The trigger function must not become a callable Data API surface.
  if pg_catalog.to_regprocedure(
       'edoc_private.capture_official_dispatch_event_v1()'
     ) is null then
    raise exception 'runtime_schema_dispatch_event_capture_function_missing';
  end if;

  if not exists (
    select 1
    from pg_catalog.pg_proc procedure_row
    join pg_catalog.pg_roles owner_role
      on owner_role.oid = procedure_row.proowner
    where procedure_row.oid =
      'edoc_private.capture_official_dispatch_event_v1()'::pg_catalog.regprocedure
      and owner_role.rolname = 'postgres'
      and procedure_row.prosecdef
      and procedure_row.proconfig @> array['search_path=""']::text[]
  ) then
    raise exception 'runtime_schema_dispatch_event_capture_function_invalid';
  end if;

  if exists (
    select 1
    from pg_catalog.pg_proc procedure_row
    cross join lateral pg_catalog.aclexplode(
      coalesce(
        procedure_row.proacl,
        pg_catalog.acldefault('f', procedure_row.proowner)
      )
    ) privilege_row
    where procedure_row.oid =
      'edoc_private.capture_official_dispatch_event_v1()'::pg_catalog.regprocedure
      and privilege_row.grantee = 0
      and privilege_row.privilege_type = 'EXECUTE'
  ) then
    raise exception 'runtime_schema_dispatch_event_capture_execute_exposed:PUBLIC';
  end if;

  foreach v_role_name in array array['anon', 'authenticated', 'service_role']
  loop
    if pg_catalog.has_function_privilege(
      v_role_name,
      'edoc_private.capture_official_dispatch_event_v1()'::pg_catalog.regprocedure,
      'EXECUTE'
    ) then
      raise exception 'runtime_schema_dispatch_event_capture_execute_exposed:%',
        v_role_name;
    end if;
  end loop;

  if pg_catalog.to_regprocedure(
       'edoc_private.guard_official_dispatch_identity_v1()'
     ) is null then
    raise exception 'runtime_schema_dispatch_identity_guard_function_missing';
  end if;

  if not exists (
    select 1
    from pg_catalog.pg_proc procedure_row
    join pg_catalog.pg_roles owner_role
      on owner_role.oid = procedure_row.proowner
    where procedure_row.oid =
      'edoc_private.guard_official_dispatch_identity_v1()'::pg_catalog.regprocedure
      and owner_role.rolname = 'postgres'
      and procedure_row.prosecdef
      and procedure_row.proconfig @> array['search_path=""']::text[]
  ) then
    raise exception 'runtime_schema_dispatch_identity_guard_function_invalid';
  end if;

  if exists (
    select 1
    from pg_catalog.pg_proc procedure_row
    cross join lateral pg_catalog.aclexplode(
      coalesce(
        procedure_row.proacl,
        pg_catalog.acldefault('f', procedure_row.proowner)
      )
    ) privilege_row
    where procedure_row.oid =
      'edoc_private.guard_official_dispatch_identity_v1()'::pg_catalog.regprocedure
      and privilege_row.grantee = 0
      and privilege_row.privilege_type = 'EXECUTE'
  ) then
    raise exception 'runtime_schema_dispatch_identity_guard_execute_exposed:PUBLIC';
  end if;

  foreach v_role_name in array array['anon', 'authenticated', 'service_role']
  loop
    if pg_catalog.has_function_privilege(
      v_role_name,
      'edoc_private.guard_official_dispatch_identity_v1()'::pg_catalog.regprocedure,
      'EXECUTE'
    ) then
      raise exception 'runtime_schema_dispatch_identity_guard_execute_exposed:%',
        v_role_name;
    end if;
  end loop;

  if 1 <> (
    select pg_catalog.count(*)
    from pg_catalog.pg_trigger trigger_row
    where trigger_row.tgrelid =
      'public.official_document_dispatch_records'::pg_catalog.regclass
      and trigger_row.tgfoid =
        'edoc_private.guard_official_dispatch_identity_v1()'::pg_catalog.regprocedure
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
      and pg_catalog.split_part(
        pg_catalog.split_part(
          pg_catalog.regexp_replace(
            pg_catalog.lower(
              pg_catalog.pg_get_triggerdef(trigger_row.oid, false)
            ),
            '[[:space:]()]',
            '',
            'g'
          ),
          'when',
          2
        ),
        'executefunction',
        1
      ) = v_dispatch_identity_qual
  ) or 1 <> (
    select pg_catalog.count(*)
    from pg_catalog.pg_trigger trigger_row
    where trigger_row.tgrelid =
      'public.official_document_dispatch_records'::pg_catalog.regclass
      and trigger_row.tgfoid =
        'edoc_private.guard_official_dispatch_identity_v1()'::pg_catalog.regprocedure
      and trigger_row.tgenabled <> 'D'
      and not trigger_row.tgisinternal
  ) then
    raise exception 'runtime_schema_dispatch_identity_guard_trigger_invalid';
  end if;

  if 2 <> (
    select pg_catalog.count(*)
    from pg_catalog.pg_trigger trigger_row
    where trigger_row.tgrelid =
      'public.official_document_dispatch_records'::pg_catalog.regclass
      and trigger_row.tgfoid =
        'edoc_private.capture_official_dispatch_event_v1()'::pg_catalog.regprocedure
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
          and pg_catalog.split_part(
            pg_catalog.split_part(
              pg_catalog.regexp_replace(
                pg_catalog.lower(
                  pg_catalog.pg_get_triggerdef(trigger_row.oid, false)
                ),
                '[[:space:]()]',
                '',
                'g'
              ),
              'when',
              2
            ),
            'executefunction',
            1
          ) = v_dispatch_capture_qual
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
  ) or 2 <> (
    select pg_catalog.count(*)
    from pg_catalog.pg_trigger trigger_row
    where trigger_row.tgrelid =
      'public.official_document_dispatch_records'::pg_catalog.regclass
      and trigger_row.tgfoid =
        'edoc_private.capture_official_dispatch_event_v1()'::pg_catalog.regprocedure
      and trigger_row.tgenabled <> 'D'
      and not trigger_row.tgisinternal
  ) then
    raise exception 'runtime_schema_dispatch_event_capture_trigger_invalid';
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
