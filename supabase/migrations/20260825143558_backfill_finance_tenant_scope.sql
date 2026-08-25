-- Bind Finance projections created before tenant-aware columns existed to the
-- sole published Finance tenant. Fail closed if more than one tenant is ever
-- present so this repair can never guess across organizations.

begin;

set local lock_timeout = '5s';
set local statement_timeout = '30s';

do $backfill$
declare
  v_tenant_id text;
  v_tenant_count integer;
begin
  select count(*), min(finance_tenant_id)
    into v_tenant_count, v_tenant_id
  from public.finance_organization_projection_state;

  if v_tenant_count <> 1 or nullif(btrim(v_tenant_id), '') is null then
    raise exception using
      errcode = '55000',
      message = 'finance_tenant_backfill_requires_exactly_one_projection_tenant';
  end if;

  if exists (
    select 1 from public.companies
    where source_system = 'finance'
      and nullif(btrim(finance_tenant_id), '') is not null
      and finance_tenant_id <> v_tenant_id
  ) or exists (
    select 1 from public.users
    where account_source = 'finance'
      and nullif(btrim(finance_tenant_id), '') is not null
      and finance_tenant_id <> v_tenant_id
  ) then
    raise exception using
      errcode = '55000',
      message = 'finance_tenant_backfill_existing_scope_conflict';
  end if;

  update public.companies
  set finance_tenant_id = v_tenant_id
  where source_system = 'finance'
    and nullif(btrim(finance_tenant_id), '') is null;

  update public.users
  set finance_tenant_id = v_tenant_id
  where account_source = 'finance'
    and nullif(btrim(finance_tenant_id), '') is null;

  update public.finance_member_sync_receipts
  set finance_tenant_id = v_tenant_id,
      aggregate_type = case event_type
        when 'member.changed' then 'member'
        when 'company.changed' then 'company'
        else aggregate_type
      end,
      aggregate_id = case event_type
        when 'member.changed' then finance_user_id
        when 'company.changed' then finance_entity_id
        else aggregate_id
      end
  where event_type in ('member.changed', 'company.changed')
    and nullif(btrim(finance_tenant_id), '') is null;

  if exists (
    select 1 from public.companies
    where source_system = 'finance'
      and finance_tenant_id is distinct from v_tenant_id
  ) or exists (
    select 1 from public.users
    where account_source = 'finance'
      and finance_tenant_id is distinct from v_tenant_id
  ) or exists (
    select 1 from public.finance_member_sync_receipts
    where event_type in ('member.changed', 'company.changed')
      and finance_tenant_id is distinct from v_tenant_id
  ) then
    raise exception using
      errcode = '55000',
      message = 'finance_tenant_backfill_incomplete';
  end if;
end;
$backfill$;

notify pgrst, 'reload schema';

commit;
