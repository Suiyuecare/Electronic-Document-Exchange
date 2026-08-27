-- Forward-only hardening for the append-only audit chain.
--
-- Historical migrations needed a narrow public.digest compatibility wrapper
-- while replaying, but runtime functions must bind directly to pgcrypto in the
-- managed ``extensions`` schema. Existing audit rows are never rewritten.

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

-- Freeze v1 writers for the remainder of this migration. The lock waits for
-- already-running INSERT transactions and conflicts with every later INSERT,
-- so no old-trigger row can appear after the transition head is selected.
lock table public.audit_logs in share row exclusive mode;

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

-- Never choose a v1 anchor by timestamp. First prove that every historical
-- row is hash-valid and that the graph is one complete linear chain with one
-- root and one terminal. Historical evidence is not rewritten; any fork, gap,
-- duplicate hash or invalid payload stops deployment for manual investigation.
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
  v_terminal_id text;
  v_terminal_hash text;
begin
  select pg_catalog.count(*) into v_total
  from public.audit_logs
  where chain_version = 1;

  if v_total = 0 then
    return;
  end if;

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

  if v_invalid <> 0
     or v_duplicate_hashes <> 0
     or v_roots <> 1
     or v_missing_parents <> 0
     or v_forks <> 0
     or v_terminals <> 1
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

  select terminal.id, terminal.entry_hash
    into strict v_terminal_id, v_terminal_hash
  from public.audit_logs terminal
  where terminal.chain_version = 1
    and not exists (
      select 1
      from public.audit_logs child
      where child.chain_version = 1
        and child.previous_hash = terminal.entry_hash
    );

  insert into edoc_private.audit_log_chain_heads (
    chain_version, head_hash, last_audit_id, updated_at
  ) values (
    2, v_terminal_hash, v_terminal_id, pg_catalog.clock_timestamp()
  )
  on conflict (chain_version) do nothing;
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
  'Backend-only singleton head that serializes the v2 append-only audit hash chain; historical v1 rows are not rewritten.';
comment on function edoc_private.audit_log_hash_payload(
  text, text, text, text, text, text, text, text, text, text
) is 'Fixed-search-path SHA-256 payload helper used by the audit trigger and security-invoker verification view.';

notify pgrst, 'reload schema';

commit;
