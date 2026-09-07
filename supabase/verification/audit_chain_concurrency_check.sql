-- Run after twenty concurrent AUD-CI-CONCURRENT-* inserts on a disposable
-- fresh-bootstrap database. The database is destroyed after CI; no business
-- or personal data is used here.

do $audit_concurrency_check$
declare
  v_count integer;
  v_distinct_hashes integer;
  v_walked integer;
  v_max_children integer;
begin
  select count(*), count(distinct entry_hash)
    into v_count, v_distinct_hashes
  from public.audit_logs
  where id like 'AUD-CI-CONCURRENT-%'
    and chain_version = 2;

  if v_count <> 20 or v_distinct_hashes <> 20 then
    raise exception 'audit_concurrency_row_or_hash_count_invalid:%/%',
      v_count, v_distinct_hashes;
  end if;

  if not exists (
    select 1
    from edoc_private.audit_log_chain_heads chain_head
    join public.audit_logs audit_row
      on audit_row.id = chain_head.last_audit_id
     and audit_row.entry_hash = chain_head.head_hash
    where chain_head.chain_version = 2
      and audit_row.id like 'AUD-CI-CONCURRENT-%'
  ) then
    raise exception 'audit_concurrency_head_not_stored';
  end if;

  with recursive walked as (
    select audit_row.id, audit_row.previous_hash, audit_row.entry_hash, 1 as depth
    from edoc_private.audit_log_chain_heads chain_head
    join public.audit_logs audit_row
      on audit_row.id = chain_head.last_audit_id
     and audit_row.entry_hash = chain_head.head_hash
    where chain_head.chain_version = 2
      and audit_row.id like 'AUD-CI-CONCURRENT-%'

    union all

    select audit_row.id, audit_row.previous_hash, audit_row.entry_hash, walked.depth + 1
    from walked
    join public.audit_logs audit_row
      on audit_row.entry_hash = walked.previous_hash
    where audit_row.id like 'AUD-CI-CONCURRENT-%'
      and walked.depth < 20
  )
  select count(*) into v_walked from walked;

  if v_walked <> 20 then
    raise exception 'audit_concurrency_chain_fork_or_gap:%', v_walked;
  end if;

  select coalesce(max(child_count), 0)
    into v_max_children
  from (
    select previous_hash, count(*) as child_count
    from public.audit_logs
    where id like 'AUD-CI-CONCURRENT-%'
      and chain_version = 2
    group by previous_hash
  ) child_counts;

  if v_max_children > 1 then
    raise exception 'audit_concurrency_chain_fork:%', v_max_children;
  end if;

  select count(*) into v_count
  from public.audit_log_chain_check chain_check
  where chain_check.id like 'AUD-CI-CONCURRENT-%'
    and chain_check.hash_valid is distinct from true;

  if v_count <> 0 then
    raise exception 'audit_concurrency_hash_invalid:%', v_count;
  end if;
end
$audit_concurrency_check$;

select 'audit_chain_concurrency_ok' as result;
