-- Finance remains the sole writable master for companies, people and the
-- published organization graph.  eDoc stores a service-only, revisioned
-- projection used by forms; submitted document snapshots remain immutable.

begin;

set local lock_timeout = '5s';
set local statement_timeout = '60s';

create table if not exists public.portal_handoff_nonces (
  jti_hash text primary key,
  issued_at bigint not null,
  expires_at bigint not null,
  consumed_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  constraint portal_handoff_nonces_hash_check
    check (jti_hash ~ '^[0-9a-f]{64}$'),
  constraint portal_handoff_nonces_window_check
    check (expires_at >= issued_at)
);

create index if not exists portal_handoff_nonces_expiry_idx
  on public.portal_handoff_nonces (expires_at);

alter table public.companies
  add column if not exists finance_tenant_id text;

alter table public.users
  add column if not exists finance_tenant_id text;

create table if not exists public.finance_organization_revisions (
  finance_tenant_id text not null,
  version_no bigint not null,
  version_id text not null,
  etag text not null,
  schema_version integer not null,
  source_event_id text not null,
  source_occurred_at text not null,
  payload_sha256 text not null,
  units_json jsonb not null,
  assignments_json jsonb not null,
  reporting_overrides_json jsonb not null,
  created_at timestamptz not null default now(),
  primary key (finance_tenant_id, version_no),
  constraint finance_organization_revisions_tenant_check
    check (char_length(btrim(finance_tenant_id)) between 1 and 128),
  constraint finance_organization_revisions_version_check
    check (version_no > 0),
  constraint finance_organization_revisions_etag_check
    check (etag ~ '^[0-9a-f]{64}$'),
  constraint finance_organization_revisions_payload_hash_check
    check (payload_sha256 ~ '^[0-9a-f]{64}$'),
  constraint finance_organization_revisions_schema_check
    check (schema_version = 2),
  constraint finance_organization_revisions_units_check
    check (jsonb_typeof(units_json) = 'array'),
  constraint finance_organization_revisions_assignments_check
    check (jsonb_typeof(assignments_json) = 'array'),
  constraint finance_organization_revisions_overrides_check
    check (jsonb_typeof(reporting_overrides_json) = 'array')
);

create table if not exists public.finance_organization_projection_state (
  finance_tenant_id text primary key,
  version_no bigint not null,
  version_id text not null,
  etag text not null,
  schema_version integer not null,
  source_event_id text not null,
  source_occurred_at text not null,
  payload_sha256 text not null,
  unit_count integer not null default 0,
  assignment_count integer not null default 0,
  last_synced_from_finance_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint finance_organization_projection_state_tenant_check
    check (char_length(btrim(finance_tenant_id)) between 1 and 128),
  constraint finance_organization_projection_state_version_check
    check (version_no > 0),
  constraint finance_organization_projection_state_etag_check
    check (etag ~ '^[0-9a-f]{64}$'),
  constraint finance_organization_projection_state_hash_check
    check (payload_sha256 ~ '^[0-9a-f]{64}$'),
  constraint finance_organization_projection_state_schema_check
    check (schema_version = 2),
  constraint finance_organization_projection_state_counts_check
    check (unit_count between 0 and 500 and assignment_count between 0 and 2000)
);

create table if not exists public.finance_organization_units (
  id text primary key,
  finance_tenant_id text not null,
  finance_unit_id text not null,
  code text not null,
  name text not null,
  unit_type text not null,
  parent_finance_unit_id text,
  sort_order integer not null default 0,
  is_posting_unit boolean not null default false,
  entity_scope_mode text not null default 'inherit',
  entity_codes jsonb not null default '[]'::jsonb,
  status text not null default 'active',
  finance_source_revision bigint not null,
  finance_source_event_id text not null,
  finance_source_updated_at text not null,
  last_synced_from_finance_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint finance_organization_units_tenant_unit_uq
    unique (finance_tenant_id, finance_unit_id),
  constraint finance_organization_units_tenant_check
    check (char_length(btrim(finance_tenant_id)) between 1 and 128),
  constraint finance_organization_units_id_check
    check (char_length(btrim(finance_unit_id)) between 1 and 160),
  constraint finance_organization_units_code_check
    check (char_length(btrim(code)) between 1 and 64),
  constraint finance_organization_units_name_check
    check (char_length(btrim(name)) between 1 and 300),
  constraint finance_organization_units_type_check
    check (unit_type in ('shareholders', 'board', 'executive', 'division', 'department', 'section', 'team')),
  constraint finance_organization_units_scope_check
    check (entity_scope_mode in ('inherit', 'all', 'explicit')),
  constraint finance_organization_units_entities_check
    check (jsonb_typeof(entity_codes) = 'array' and jsonb_array_length(entity_codes) <= 100),
  constraint finance_organization_units_status_check
    check (status in ('active', 'inactive')),
  constraint finance_organization_units_revision_check
    check (finance_source_revision > 0)
);

create index if not exists finance_organization_units_active_order_idx
  on public.finance_organization_units (
    finance_tenant_id,
    status,
    sort_order,
    code
  );

create index if not exists finance_organization_units_parent_idx
  on public.finance_organization_units (
    finance_tenant_id,
    parent_finance_unit_id
  );

create index if not exists finance_organization_units_entity_codes_idx
  on public.finance_organization_units using gin (entity_codes);

alter table public.finance_member_sync_receipts
  add column if not exists finance_tenant_id text,
  add column if not exists aggregate_type text,
  add column if not exists aggregate_id text,
  add column if not exists projected_organization_version bigint;

alter table public.finance_member_sync_receipts
  drop constraint if exists finance_member_sync_receipts_event_type_check;

alter table public.finance_member_sync_receipts
  add constraint finance_member_sync_receipts_event_type_check
  check (event_type in ('member.changed', 'company.changed', 'organization.published'));

create index if not exists finance_member_sync_receipts_organization_idx
  on public.finance_member_sync_receipts (
    finance_tenant_id,
    aggregate_type,
    aggregate_id,
    source_revision desc
  )
  where aggregate_type = 'organization';

-- Apply the complete published graph and its receipt in one transaction.  The
-- Python receiver validates the wire contract first; this RPC repeats the
-- important revision/hash/shape checks at the database trust boundary.
create or replace function public.edoc_apply_finance_organization_projection_v2(
  p_event_id text,
  p_tenant_id text,
  p_source_revision bigint,
  p_payload_sha256 text,
  p_occurred_at text,
  p_organization jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_existing_receipt public.finance_member_sync_receipts%rowtype;
  v_state public.finance_organization_projection_state%rowtype;
  v_version_id text;
  v_version_no bigint;
  v_etag text;
  v_schema_version integer;
  v_units jsonb;
  v_assignments jsonb;
  v_overrides jsonb;
  v_unit_count integer;
  v_assignment_count integer;
  v_status text := 'applied';
begin
  perform pg_catalog.set_config('statement_timeout', '5000', true);

  if p_event_id is null or char_length(btrim(p_event_id)) not between 1 and 160
     or p_tenant_id is null or char_length(btrim(p_tenant_id)) not between 1 and 128
     or p_source_revision is null or p_source_revision <= 0
     or p_payload_sha256 is null or p_payload_sha256 !~ '^[0-9a-f]{64}$'
     or p_occurred_at is null or char_length(btrim(p_occurred_at)) not between 1 and 64
     or jsonb_typeof(p_organization) is distinct from 'object' then
    raise exception using errcode = '22023', message = 'finance_organization_projection_input_invalid';
  end if;

  v_version_id := btrim(coalesce(p_organization ->> 'versionId', ''));
  v_version_no := coalesce((p_organization ->> 'versionNo')::bigint, 0);
  v_etag := lower(btrim(coalesce(p_organization ->> 'etag', '')));
  v_schema_version := coalesce((p_organization ->> 'schemaVersion')::integer, 0);
  v_units := coalesce(p_organization -> 'units', '[]'::jsonb);
  v_assignments := coalesce(p_organization -> 'assignments', '[]'::jsonb);
  v_overrides := coalesce(p_organization -> 'reportingOverrides', '[]'::jsonb);

  if v_version_id = ''
     or v_version_no <> p_source_revision
     or v_etag !~ '^[0-9a-f]{64}$'
     or v_schema_version <> 2
     or jsonb_typeof(v_units) is distinct from 'array'
     or jsonb_typeof(v_assignments) is distinct from 'array'
     or jsonb_typeof(v_overrides) is distinct from 'array' then
    raise exception using errcode = '22023', message = 'finance_organization_projection_contract_invalid';
  end if;

  v_unit_count := jsonb_array_length(v_units);
  v_assignment_count := jsonb_array_length(v_assignments);
  if v_unit_count > 500 or v_assignment_count > 2000
     or v_unit_count <> (
       select count(distinct unit_item ->> 'id')
       from jsonb_array_elements(v_units) unit_item
     ) then
    raise exception using errcode = '22023', message = 'finance_organization_projection_contract_invalid';
  end if;

  select receipt_row.*
  into v_existing_receipt
  from public.finance_member_sync_receipts receipt_row
  where receipt_row.event_id = p_event_id
  for update;

  if found then
    if v_existing_receipt.event_type <> 'organization.published'
       or v_existing_receipt.source_revision <> p_source_revision
       or v_existing_receipt.payload_sha256 <> p_payload_sha256 then
      raise exception using errcode = '23505', message = 'finance_member_sync_event_id_conflict';
    end if;
    if v_existing_receipt.apply_status in ('applied', 'stale') then
      return jsonb_build_object(
        'status', 'replayed',
        'organizationVersion', coalesce((
          select state_row.version_no
          from public.finance_organization_projection_state state_row
          where state_row.finance_tenant_id = p_tenant_id
        ), p_source_revision),
        'organizationUnitCount', coalesce((
          select state_row.unit_count
          from public.finance_organization_projection_state state_row
          where state_row.finance_tenant_id = p_tenant_id
        ), v_unit_count),
        'organizationAssignmentCount', coalesce((
          select state_row.assignment_count
          from public.finance_organization_projection_state state_row
          where state_row.finance_tenant_id = p_tenant_id
        ), v_assignment_count),
        'originalStatus', v_existing_receipt.apply_status
      );
    end if;
    -- A prior transport/backend failure receipt is retryable. The matching
    -- event id/revision/hash has already been checked above.
    delete from public.finance_member_sync_receipts
    where event_id = p_event_id;
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('edoc-finance-organization:' || p_tenant_id, 20260825)
  );

  select state_row.*
  into v_state
  from public.finance_organization_projection_state state_row
  where state_row.finance_tenant_id = p_tenant_id
  for update;

  if found and p_source_revision < v_state.version_no then
    v_status := 'stale';
  elsif found and p_source_revision = v_state.version_no then
    if v_state.etag <> v_etag or v_state.payload_sha256 <> p_payload_sha256 then
      raise exception using errcode = '23505', message = 'finance_organization_revision_conflict';
    end if;
    v_status := 'stale';
  end if;

  if v_status = 'applied' then
    insert into public.finance_organization_revisions (
      finance_tenant_id,
      version_no,
      version_id,
      etag,
      schema_version,
      source_event_id,
      source_occurred_at,
      payload_sha256,
      units_json,
      assignments_json,
      reporting_overrides_json
    ) values (
      p_tenant_id,
      p_source_revision,
      v_version_id,
      v_etag,
      v_schema_version,
      p_event_id,
      p_occurred_at,
      p_payload_sha256,
      v_units,
      v_assignments,
      v_overrides
    )
    on conflict (finance_tenant_id, version_no) do nothing;

    insert into public.finance_organization_units (
      id,
      finance_tenant_id,
      finance_unit_id,
      code,
      name,
      unit_type,
      parent_finance_unit_id,
      sort_order,
      is_posting_unit,
      entity_scope_mode,
      entity_codes,
      status,
      finance_source_revision,
      finance_source_event_id,
      finance_source_updated_at,
      last_synced_from_finance_at,
      updated_at
    )
    select
      'FINORG-' || upper(substr(md5(p_tenant_id || ':' || (unit_item ->> 'id')), 1, 20)),
      p_tenant_id,
      unit_item ->> 'id',
      upper(btrim(unit_item ->> 'code')),
      btrim(unit_item ->> 'name'),
      lower(btrim(unit_item ->> 'unitType')),
      nullif(btrim(unit_item ->> 'parentOrgUnitId'), ''),
      coalesce((unit_item ->> 'sortOrder')::integer, 0),
      coalesce((unit_item ->> 'isPostingUnit')::boolean, false),
      lower(btrim(coalesce(unit_item ->> 'entityScopeMode', 'inherit'))),
      coalesce(unit_item -> 'entityCodes', '[]'::jsonb),
      case when coalesce((unit_item ->> 'active')::boolean, true) then 'active' else 'inactive' end,
      p_source_revision,
      p_event_id,
      p_occurred_at,
      now(),
      now()
    from jsonb_array_elements(v_units) unit_item
    on conflict (finance_tenant_id, finance_unit_id) do update set
      id = excluded.id,
      code = excluded.code,
      name = excluded.name,
      unit_type = excluded.unit_type,
      parent_finance_unit_id = excluded.parent_finance_unit_id,
      sort_order = excluded.sort_order,
      is_posting_unit = excluded.is_posting_unit,
      entity_scope_mode = excluded.entity_scope_mode,
      entity_codes = excluded.entity_codes,
      status = excluded.status,
      finance_source_revision = excluded.finance_source_revision,
      finance_source_event_id = excluded.finance_source_event_id,
      finance_source_updated_at = excluded.finance_source_updated_at,
      last_synced_from_finance_at = excluded.last_synced_from_finance_at,
      updated_at = excluded.updated_at;

    update public.finance_organization_units unit_row
    set status = 'inactive',
        finance_source_revision = p_source_revision,
        finance_source_event_id = p_event_id,
        finance_source_updated_at = p_occurred_at,
        last_synced_from_finance_at = now(),
        updated_at = now()
    where unit_row.finance_tenant_id = p_tenant_id
      and unit_row.status <> 'inactive'
      and not exists (
        select 1
        from jsonb_array_elements(v_units) unit_item
        where unit_item ->> 'id' = unit_row.finance_unit_id
      );

    insert into public.finance_organization_projection_state (
      finance_tenant_id,
      version_no,
      version_id,
      etag,
      schema_version,
      source_event_id,
      source_occurred_at,
      payload_sha256,
      unit_count,
      assignment_count,
      last_synced_from_finance_at,
      updated_at
    ) values (
      p_tenant_id,
      p_source_revision,
      v_version_id,
      v_etag,
      v_schema_version,
      p_event_id,
      p_occurred_at,
      p_payload_sha256,
      v_unit_count,
      v_assignment_count,
      now(),
      now()
    )
    on conflict (finance_tenant_id) do update set
      version_no = excluded.version_no,
      version_id = excluded.version_id,
      etag = excluded.etag,
      schema_version = excluded.schema_version,
      source_event_id = excluded.source_event_id,
      source_occurred_at = excluded.source_occurred_at,
      payload_sha256 = excluded.payload_sha256,
      unit_count = excluded.unit_count,
      assignment_count = excluded.assignment_count,
      last_synced_from_finance_at = excluded.last_synced_from_finance_at,
      updated_at = excluded.updated_at;
  end if;

  -- Refresh v_state after an applied upsert so stale and applied receipts both
  -- identify the organization version that eDoc is actually serving.
  select state_row.*
  into v_state
  from public.finance_organization_projection_state state_row
  where state_row.finance_tenant_id = p_tenant_id;

  insert into public.finance_member_sync_receipts (
    event_id,
    event_type,
    source_revision,
    finance_tenant_id,
    aggregate_type,
    aggregate_id,
    projected_organization_version,
    payload_sha256,
    apply_status,
    result_code,
    received_at,
    completed_at
  ) values (
    p_event_id,
    'organization.published',
    p_source_revision,
    p_tenant_id,
    'organization',
    p_tenant_id,
    coalesce(v_state.version_no, p_source_revision),
    p_payload_sha256,
    v_status,
    'finance_organization_sync_' || v_status,
    now(),
    now()
  );

  return jsonb_build_object(
    'status', v_status,
    'organizationVersion', coalesce(v_state.version_no, p_source_revision),
    'organizationUnitCount', coalesce(v_state.unit_count, v_unit_count),
    'organizationAssignmentCount', coalesce(v_state.assignment_count, v_assignment_count)
  );
end
$$;

alter function public.edoc_apply_finance_organization_projection_v2(
  text, text, bigint, text, text, jsonb
) owner to postgres;

revoke all on function public.edoc_apply_finance_organization_projection_v2(
  text, text, bigint, text, text, jsonb
) from public, anon, authenticated;

grant execute on function public.edoc_apply_finance_organization_projection_v2(
  text, text, bigint, text, text, jsonb
) to service_role;

alter table public.portal_handoff_nonces enable row level security;
alter table public.finance_organization_revisions enable row level security;
alter table public.finance_organization_revisions force row level security;
alter table public.finance_organization_projection_state enable row level security;
alter table public.finance_organization_projection_state force row level security;
alter table public.finance_organization_units enable row level security;
alter table public.finance_organization_units force row level security;

revoke all on public.portal_handoff_nonces from public, anon, authenticated;
revoke all on public.finance_organization_revisions from public, anon, authenticated;
revoke all on public.finance_organization_projection_state from public, anon, authenticated;
revoke all on public.finance_organization_units from public, anon, authenticated;

grant select, insert, delete on public.portal_handoff_nonces to service_role;
grant select, insert on public.finance_organization_revisions to service_role;
grant select, insert, update on public.finance_organization_projection_state to service_role;
grant select, insert, update on public.finance_organization_units to service_role;

drop policy if exists "service role manages portal handoff nonces" on public.portal_handoff_nonces;
create policy "service role manages portal handoff nonces"
  on public.portal_handoff_nonces for all to service_role
  using (true) with check (true);

drop policy if exists "service role reads finance organization revisions" on public.finance_organization_revisions;
create policy "service role reads finance organization revisions"
  on public.finance_organization_revisions for select to service_role using (true);
drop policy if exists "service role inserts finance organization revisions" on public.finance_organization_revisions;
create policy "service role inserts finance organization revisions"
  on public.finance_organization_revisions for insert to service_role with check (true);

drop policy if exists "service role manages finance organization state" on public.finance_organization_projection_state;
create policy "service role manages finance organization state"
  on public.finance_organization_projection_state for all to service_role
  using (true) with check (true);

drop policy if exists "service role manages finance organization units" on public.finance_organization_units;
create policy "service role manages finance organization units"
  on public.finance_organization_units for all to service_role
  using (true) with check (true);

-- eDoc must not retain a second writable company/department/person master.
revoke insert, update, delete on public.users from anon, authenticated;
revoke insert, update, delete on public.companies from anon, authenticated;
revoke all on public.company_registry from public, anon, authenticated;
revoke all on public.department_registry from public, anon, authenticated;
revoke all on public.module_account_links from public, anon, authenticated;

grant select, insert, update, delete on public.company_registry to service_role;
grant select, insert, update, delete on public.department_registry to service_role;
grant select, insert, update, delete on public.module_account_links to service_role;

drop policy if exists "service role manages company registry" on public.company_registry;
create policy "service role manages company registry"
  on public.company_registry for all to service_role
  using (true) with check (true);

drop policy if exists "service role manages department registry" on public.department_registry;
create policy "service role manages department registry"
  on public.department_registry for all to service_role
  using (true) with check (true);

comment on table public.finance_organization_revisions is
  'Immutable service-only Finance published organization manifests; contains identifiers and relationships, not names/emails of people.';
comment on table public.finance_organization_units is
  'Read-only eDoc projection of Finance-published organization units. Browsers access a scoped backend directory, never this table directly.';
comment on function public.edoc_apply_finance_organization_projection_v2(text,text,bigint,text,text,jsonb) is
  'Service-only atomic organization projection and receipt application with revision/hash conflict protection.';

notify pgrst, 'reload schema';

commit;
