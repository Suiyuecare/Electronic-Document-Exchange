-- Forward-only hardening for the append-only audit chain.
--
-- Historical migrations needed a narrow public.digest compatibility wrapper
-- while replaying, but runtime functions must bind directly to pgcrypto in the
-- managed ``extensions`` schema. Existing audit rows are never rewritten. A
-- canonical commitment seals every valid v1 row before the serialized v2
-- chain begins, including legacy histories that contain concurrent forks.

do $migration$
begin
  if pg_catalog.to_regprocedure('extensions.digest(bytea,text)') is null
     or pg_catalog.to_regprocedure('extensions.gen_random_bytes(integer)') is null then
    raise exception using
      errcode = '55000',
      message = 'edoc_pgcrypto_digest_missing';
  end if;
end
$migration$;

begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

-- Freeze v1 writers for the remainder of this migration. The lock waits for
-- already-running INSERT transactions and conflicts with every later INSERT,
-- so no old-trigger row can appear after the transition head is selected.
lock table public.audit_logs in share row exclusive mode;

-- Recursive graph validation follows children by version + parent hash. The
-- historical schema indexed only entry_hash, which makes a long chain rescan
-- the table once per level and can exhaust the bounded cutover timeout.
create index if not exists idx_audit_logs_chain_parent
  on public.audit_logs (chain_version, previous_hash);

create table if not exists edoc_private.audit_log_chain_heads (
  chain_version integer primary key,
  head_hash text,
  last_audit_id text,
  updated_at timestamptz not null default pg_catalog.clock_timestamp(),
  constraint audit_log_chain_heads_version_check check (chain_version = 2),
  constraint audit_log_chain_heads_hash_check check (
    head_hash is null or head_hash ~ '^[0-9a-f]{64}$'
  )
);

alter table edoc_private.audit_log_chain_heads owner to postgres;
alter table edoc_private.audit_log_chain_heads enable row level security;
alter table edoc_private.audit_log_chain_heads force row level security;
grant usage on schema edoc_private to service_role;
revoke all on table edoc_private.audit_log_chain_heads
  from public, anon, authenticated, service_role;

create table if not exists edoc_private.audit_log_chain_transitions (
  target_chain_version integer primary key,
  source_chain_version integer not null,
  source_row_count bigint not null,
  commitment_algorithm text not null,
  source_commitment text not null,
  source_root_count bigint not null,
  source_terminal_count bigint not null,
  source_fork_count bigint not null,
  committed_at timestamptz not null default pg_catalog.clock_timestamp(),
  constraint audit_log_chain_transitions_versions_check check (
    source_chain_version = 1 and target_chain_version = 2
  ),
  constraint audit_log_chain_transitions_algorithm_check check (
    commitment_algorithm = 'sha256-sorted-entry-hash-set-v1-c-collation'
  ),
  constraint audit_log_chain_transitions_count_check check (
    source_row_count >= 0
    and source_root_count between 0 and 1
    and source_terminal_count between 0 and source_row_count
    and source_fork_count between 0 and source_row_count
  ),
  constraint audit_log_chain_transitions_commitment_check check (
    source_commitment ~ '^[0-9a-f]{64}$'
  )
);

alter table edoc_private.audit_log_chain_transitions owner to postgres;
alter table edoc_private.audit_log_chain_transitions enable row level security;
alter table edoc_private.audit_log_chain_transitions force row level security;
revoke all on table edoc_private.audit_log_chain_transitions
  from public, anon, authenticated, service_role;

create or replace function edoc_private.prevent_audit_chain_transition_mutation()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  raise exception using
    errcode = '55000',
    message = 'audit_log_chain_transitions_immutable';
end
$function$;

alter function edoc_private.prevent_audit_chain_transition_mutation()
  owner to postgres;
revoke all on function edoc_private.prevent_audit_chain_transition_mutation()
  from public, anon, authenticated, service_role;

drop trigger if exists trg_audit_log_chain_transitions_no_mutation
  on edoc_private.audit_log_chain_transitions;
create trigger trg_audit_log_chain_transitions_no_mutation
before update or delete on edoc_private.audit_log_chain_transitions
for each row execute function edoc_private.prevent_audit_chain_transition_mutation();

drop trigger if exists trg_audit_log_chain_transitions_no_truncate
  on edoc_private.audit_log_chain_transitions;
create trigger trg_audit_log_chain_transitions_no_truncate
before truncate on edoc_private.audit_log_chain_transitions
for each statement execute function edoc_private.prevent_audit_chain_transition_mutation();

-- Never choose a v1 anchor by timestamp and never rewrite historical rows.
-- First prove that every v1 payload hash is valid and that all rows belong to
-- one rooted, parent-complete graph. Older writers could fork when several
-- inserts shared the same second; those immutable branches are preserved and
-- sealed as a deterministic set commitment. The first v2 row then points to
-- that commitment, so every v1 branch is covered without selecting or
-- inventing a preferred terminal.
do $audit_v1_transition$
declare
  v_total integer;
  v_invalid integer;
  v_duplicate_hashes integer;
  v_roots integer;
  v_missing_parents integer;
  v_forks integer;
  v_terminals integer;
  v_walked integer;
  v_commitment_count bigint;
  v_commitment text;
  v_exact_fresh_rows integer;
  v_exact_fresh_sentinel boolean;
begin
  if exists (
    select 1
    from public.audit_logs
    where chain_version is distinct from 1
  ) then
    raise exception using
      errcode = '55000',
      message = 'edoc_audit_pretransition_version_invalid';
  end if;

  select pg_catalog.count(*) into v_total
  from public.audit_logs
  where chain_version = 1;

  select pg_catalog.count(*) into v_invalid
  from public.audit_logs audit_row
  where audit_row.chain_version = 1
    and (
      not audit_row.immutable
      or audit_row.entry_hash is null
      or audit_row.entry_hash !~ '^[0-9a-f]{64}$'
      or audit_row.entry_hash is distinct from pg_catalog.encode(
        extensions.digest(
          pg_catalog.convert_to(
            pg_catalog.concat_ws(
              '|',
              coalesce(audit_row.previous_hash, ''),
              coalesce(audit_row.id, ''),
              coalesce(audit_row.actor, ''),
              coalesce(audit_row.action, ''),
              coalesce(audit_row.target_type, ''),
              coalesce(audit_row.target_id, ''),
              coalesce(audit_row.ip, ''),
              coalesce(audit_row.device, ''),
              coalesce(audit_row.detail, ''),
              coalesce(audit_row.created_at, '')
            ),
            'UTF8'
          ),
          'sha256'
        ),
        'hex'
      )
    );

  select pg_catalog.count(*) into v_duplicate_hashes
  from (
    select entry_hash
    from public.audit_logs
    where chain_version = 1
    group by entry_hash
    having pg_catalog.count(*) <> 1
  ) duplicates;

  select pg_catalog.count(*) into v_roots
  from public.audit_logs
  where chain_version = 1
    and (previous_hash is null or previous_hash = 'GENESIS');

  select pg_catalog.count(*) into v_missing_parents
  from public.audit_logs child
  where child.chain_version = 1
    and child.previous_hash is not null
    and child.previous_hash <> 'GENESIS'
    and not exists (
      select 1
      from public.audit_logs parent
      where parent.chain_version = 1
        and parent.entry_hash = child.previous_hash
    );

  select pg_catalog.count(*) into v_forks
  from (
    select previous_hash
    from public.audit_logs
    where chain_version = 1
      and previous_hash is not null
      and previous_hash <> 'GENESIS'
    group by previous_hash
    having pg_catalog.count(*) > 1
  ) forks;

  select pg_catalog.count(*) into v_terminals
  from public.audit_logs terminal
  where terminal.chain_version = 1
    and not exists (
      select 1
      from public.audit_logs child
      where child.chain_version = 1
        and child.previous_hash = terminal.entry_hash
    );

  with recursive walked as (
    select audit_row.id, audit_row.entry_hash
    from public.audit_logs audit_row
    where audit_row.chain_version = 1
      and (audit_row.previous_hash is null or audit_row.previous_hash = 'GENESIS')

    union all

    select child.id, child.entry_hash
    from walked parent
    join public.audit_logs child
      on child.chain_version = 1
     and child.previous_hash = parent.entry_hash
  )
  select pg_catalog.count(*) into v_walked from walked;

  -- A fork is auto-attested only for the exact, disposable roles.sql replay:
  -- its sentinel must be byte-for-byte unchanged, no identity, document,
  -- file-object or Storage object state may exist, and all seven rows must be
  -- the fixed migration audit payloads. Static company/directory lookup rows
  -- created by earlier schema migrations are intentionally not business use.
  -- Any fork on a linked or production database remains a fail-closed manual
  -- investigation; a syntactically valid hash alone is not authorization.
  if v_forks > 0 then
    select exists (
      select 1
      from public.finance_organization_projection_state sentinel
      where sentinel.finance_tenant_id = '__edoc_fresh_bootstrap_only__'
        and sentinel.version_no = 1
        and sentinel.version_id = 'EDOC-FRESH-BOOTSTRAP-COMPAT-V1'
        and sentinel.etag = pg_catalog.repeat('0', 64)
        and sentinel.schema_version = 2
        and sentinel.source_event_id = 'EDOC-FRESH-BOOTSTRAP-COMPAT-V1'
        and sentinel.source_occurred_at = '1970-01-01T00:00:00Z'
        and sentinel.payload_sha256 = pg_catalog.repeat('0', 64)
        and sentinel.unit_count = 0
        and sentinel.assignment_count = 0
        and sentinel.last_synced_from_finance_at =
          '1970-01-01 00:00:00+00'::timestamptz
        and sentinel.updated_at = '1970-01-01 00:00:00+00'::timestamptz
    )
    and not exists (
      select 1
      from public.finance_organization_projection_state sentinel
      where sentinel.finance_tenant_id = '__edoc_fresh_bootstrap_only__'
        and not (
          sentinel.version_no = 1
          and sentinel.version_id = 'EDOC-FRESH-BOOTSTRAP-COMPAT-V1'
          and sentinel.etag = pg_catalog.repeat('0', 64)
          and sentinel.schema_version = 2
          and sentinel.source_event_id = 'EDOC-FRESH-BOOTSTRAP-COMPAT-V1'
          and sentinel.source_occurred_at = '1970-01-01T00:00:00Z'
          and sentinel.payload_sha256 = pg_catalog.repeat('0', 64)
          and sentinel.unit_count = 0
          and sentinel.assignment_count = 0
          and sentinel.last_synced_from_finance_at =
            '1970-01-01 00:00:00+00'::timestamptz
          and sentinel.updated_at =
            '1970-01-01 00:00:00+00'::timestamptz
        )
    )
    and not exists (
      select 1 from public.users
    )
    and not exists (
      select 1 from public.finance_member_sync_receipts
      where finance_tenant_id = '__edoc_fresh_bootstrap_only__'
    )
    and not exists (
      select 1 from public.finance_organization_revisions
      where finance_tenant_id = '__edoc_fresh_bootstrap_only__'
    )
    and not exists (
      select 1 from public.finance_organization_units
      where finance_tenant_id = '__edoc_fresh_bootstrap_only__'
    )
    and not exists (
      select 1 from public.module_account_links
      where finance_tenant_id = '__edoc_fresh_bootstrap_only__'
    )
    and not exists (select 1 from auth.users)
    and not exists (select 1 from public.documents)
    and not exists (select 1 from public.official_documents)
    and not exists (select 1 from public.file_objects)
    and not exists (select 1 from storage.objects)
      into v_exact_fresh_sentinel;

    with expected_rows(
      id, actor, action, target_type, target_id, detail
    ) as (
      values
        (
          'AUD-202605230006',
          'migration',
          '啟用部門公文隔離',
          'rbac',
          'department-document-isolation',
          '總務與行政部主任的公文清單依 owner / department / session role 隔離；跨部門需留下分派、會辦或簽核紀錄。'
        ),
        (
          'AUD-DBSEC-20260523-001',
          'Migration',
          '正式資料庫權限政策',
          'database',
          '202605230010_formal_database_security_policy',
          '已建立 RLS、密件 row-level 隔離、保留年限政策、audit log hash chain 與 append-only trigger。'
        ),
        (
          'AUD-FILESEC-20260523-001',
          'Migration',
          '正式檔案儲存與病毒掃描服務',
          'storage',
          '202605230011_formal_file_storage_scanning',
          '已建立 private bucket、檔案加密 metadata、防毒掃描任務、短效下載 token 與隔離下載控制。'
        ),
        (
          'AUD-MIG-202605240001-COMPLIANCE-ATTEST',
          'migration',
          '法遵驗收與內控制度簽核資料表',
          'migration',
          '202605240001_compliance_attestations',
          '已建立 compliance_attestations，用於留存法遵驗收、內控制度簽核、報告雜湊與不可否認紀錄。'
        ),
        (
          'AUD-CONTRACT-MGMT-202605250003',
          'system',
          '建立合約管理資料表',
          'contracts',
          'contract-management',
          '已建立合約主檔、合約相對人與合約簽核紀錄，支援合約起案、審核、用印簽署、續約提醒與歸檔。'
        ),
        (
          'AUD-COMPANY-SEAL-MODULE-20260702-001',
          'Migration',
          '公司印章與用印管理模組',
          'schema',
          '20260702113334_company_seal_usage_module',
          '已建立公司印章庫、印章版本、用印申請、簽核、用印紀錄、Seal Vault private bucket 與直連阻擋政策。'
        ),
        (
          'AUD-COMPANY-SEAL-UPLOAD-SLOTS-20260823-001',
          'Migration',
          '建立公司印章上傳欄位',
          'schema',
          '20260823191041_backfill_company_seal_upload_slots',
          '已為所有 Finance 啟用公司建立八種 Seal Vault metadata 欄位；未建立任何印章檔案或版本。'
        )
    )
    select pg_catalog.count(*) into v_exact_fresh_rows
    from expected_rows expected
    join public.audit_logs audit_row
      on audit_row.id = expected.id
     and audit_row.actor = expected.actor
     and audit_row.action = expected.action
     and audit_row.target_type = expected.target_type
     and audit_row.target_id = expected.target_id
     and audit_row.detail = expected.detail
     and audit_row.ip is null
     and audit_row.device is null
     and audit_row.chain_version = 1;

    if not coalesce(v_exact_fresh_sentinel, false)
       or v_total <> 7
       or v_exact_fresh_rows <> 7
       or v_roots <> 1 then
      raise exception using
        errcode = '55000',
        message = 'edoc_audit_v1_fork_requires_manual_attestation',
        detail = pg_catalog.format(
          'total=%s exact_fresh_rows=%s roots=%s forks=%s terminals=%s',
          v_total,
          v_exact_fresh_rows,
          v_roots,
          v_forks,
          v_terminals
        );
    end if;
  end if;

  if v_invalid <> 0
     or v_duplicate_hashes <> 0
     or v_roots <> case when v_total = 0 then 0 else 1 end
     or v_missing_parents <> 0
     or (
       v_terminals <> 0
       and v_total = 0
     )
     or (
       v_terminals < 1
       and v_total > 0
     )
     or v_walked <> v_total then
    raise exception using
      errcode = '55000',
      message = 'edoc_audit_v1_chain_invalid',
      detail = pg_catalog.format(
        'total=%s invalid=%s duplicate_hashes=%s roots=%s missing_parents=%s forks=%s terminals=%s walked=%s',
        v_total,
        v_invalid,
        v_duplicate_hashes,
        v_roots,
        v_missing_parents,
        v_forks,
        v_terminals,
        v_walked
      );
  end if;

  select
    pg_catalog.count(*),
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
    )
    into v_commitment_count, v_commitment
  from public.audit_logs
  where chain_version = 1;

  if v_commitment_count <> v_total then
    raise exception using
      errcode = '55000',
      message = 'edoc_audit_v1_commitment_count_mismatch';
  end if;

  insert into edoc_private.audit_log_chain_transitions (
    target_chain_version,
    source_chain_version,
    source_row_count,
    commitment_algorithm,
    source_commitment,
    source_root_count,
    source_terminal_count,
    source_fork_count,
    committed_at
  ) values (
    2,
    1,
    v_total,
    'sha256-sorted-entry-hash-set-v1-c-collation',
    v_commitment,
    v_roots,
    v_terminals,
    v_forks,
    pg_catalog.clock_timestamp()
  )
  on conflict (target_chain_version) do nothing;

  if not exists (
    select 1
    from edoc_private.audit_log_chain_transitions transition_row
    where transition_row.target_chain_version = 2
      and transition_row.source_chain_version = 1
      and transition_row.source_row_count = v_total
      and transition_row.commitment_algorithm =
        'sha256-sorted-entry-hash-set-v1-c-collation'
      and transition_row.source_commitment = v_commitment
      and transition_row.source_root_count = v_roots
      and transition_row.source_terminal_count = v_terminals
      and transition_row.source_fork_count = v_forks
  ) then
    raise exception using
      errcode = '55000',
      message = 'edoc_audit_v1_transition_state_mismatch';
  end if;

  insert into edoc_private.audit_log_chain_heads (
    chain_version, head_hash, last_audit_id, updated_at
  ) values (
    2, v_commitment, null, pg_catalog.clock_timestamp()
  )
  on conflict (chain_version) do nothing;

  if not exists (
    select 1
    from edoc_private.audit_log_chain_heads chain_head
    where chain_head.chain_version = 2
      and chain_head.head_hash = v_commitment
      and chain_head.last_audit_id is null
  ) then
    raise exception using
      errcode = '55000',
      message = 'edoc_audit_v2_initial_head_mismatch';
  end if;
end
$audit_v1_transition$;

create or replace function edoc_private.audit_log_hash_payload(
  audit_id text,
  actor text,
  action text,
  target_type text,
  target_id text,
  ip text,
  device text,
  detail text,
  created_at text,
  previous_hash text
)
returns text
language sql
immutable
security definer
set search_path = ''
as $function$
  select pg_catalog.encode(
    extensions.digest(
      pg_catalog.convert_to(
        pg_catalog.concat_ws(
          '|',
          coalesce(previous_hash, ''),
          coalesce(audit_id, ''),
          coalesce(actor, ''),
          coalesce(action, ''),
          coalesce(target_type, ''),
          coalesce(target_id, ''),
          coalesce(ip, ''),
          coalesce(device, ''),
          coalesce(detail, ''),
          coalesce(created_at, '')
        ),
        'UTF8'
      ),
      'sha256'
    ),
    'hex'
  )
$function$;

alter function edoc_private.audit_log_hash_payload(
  text, text, text, text, text, text, text, text, text, text
) owner to postgres;
revoke all on function edoc_private.audit_log_hash_payload(
  text, text, text, text, text, text, text, text, text, text
) from public, anon, authenticated;
grant execute on function edoc_private.audit_log_hash_payload(
  text, text, text, text, text, text, text, text, text, text
) to service_role;

-- All application reads are mediated by the backend. The historical view
-- grant was both inconsistent with that boundary and unusable after the
-- private schema was locked down, so keep the security-invoker view backend
-- only while preserving RLS as defense in depth.
revoke all on public.audit_log_chain_check from public, anon, authenticated;
grant select on public.audit_log_chain_check to service_role;

create or replace function edoc_private.prepare_audit_log_hash()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_previous_hash text;
begin
  -- The advisory lock protects the empty-head bootstrap; the singleton row
  -- lock then serializes every writer. A failed insert rolls both locks and the
  -- head update back in the same transaction.
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('edoc.audit_logs.chain.v2', 0)
  );

  -- BEFORE INSERT triggers still run for INSERT ... ON CONFLICT DO NOTHING.
  -- A replayed audit ID therefore must return before it advances the private
  -- chain head, otherwise the head could point at a row that was never stored.
  if exists (
    select 1
    from public.audit_logs audit_row
    where audit_row.id = new.id
  ) then
    return new;
  end if;

  insert into edoc_private.audit_log_chain_heads (
    chain_version, head_hash, last_audit_id, updated_at
  ) values (2, null, null, pg_catalog.clock_timestamp())
  on conflict (chain_version) do nothing;

  select chain_head.head_hash
    into v_previous_hash
  from edoc_private.audit_log_chain_heads chain_head
  where chain_head.chain_version = 2
  for update;

  new.chain_version := 2;
  new.previous_hash := coalesce(v_previous_hash, 'GENESIS');
  new.entry_hash := edoc_private.audit_log_hash_payload(
    new.id,
    new.actor,
    new.action,
    new.target_type,
    new.target_id,
    new.ip,
    new.device,
    new.detail,
    new.created_at,
    new.previous_hash
  );
  new.immutable := true;

  update edoc_private.audit_log_chain_heads
  set head_hash = new.entry_hash,
      last_audit_id = new.id,
      updated_at = pg_catalog.clock_timestamp()
  where chain_version = 2;

  return new;
end
$function$;

alter function edoc_private.prepare_audit_log_hash() owner to postgres;
revoke all on function edoc_private.prepare_audit_log_hash()
  from public, anon, authenticated, service_role;

-- The inbound mutation RPC is service-only and every relation it touches is
-- schema-qualified. Bind its two pgcrypto calls directly to ``extensions`` so
-- runtime execution no longer depends on the replay-only public wrappers.
alter function public.edoc_mutate_inbound_document_v1(
  text, text, text, text, text, bigint, jsonb
) set search_path = pg_catalog, extensions;

comment on table edoc_private.audit_log_chain_heads is
  'Backend-only singleton head that serializes the v2 append-only audit hash chain; its initial value is the immutable v1 set commitment.';
comment on table edoc_private.audit_log_chain_transitions is
  'Immutable private commitment that seals every hash-valid v1 audit branch before the serialized v2 chain begins.';
comment on function edoc_private.audit_log_hash_payload(
  text, text, text, text, text, text, text, text, text, text
) is 'Fixed-search-path SHA-256 payload helper used by the audit trigger and security-invoker verification view.';

notify pgrst, 'reload schema';

commit;
