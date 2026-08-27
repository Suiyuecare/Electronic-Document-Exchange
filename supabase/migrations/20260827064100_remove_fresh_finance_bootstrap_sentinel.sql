-- Remove the roles.sql-only Finance projection sentinel after the immutable
-- historical tenant backfill has completed. Existing linked databases never
-- receive this row; the migration is an exact no-op there.

begin;

set local lock_timeout = '5s';
set local statement_timeout = '30s';

do $remove_fresh_finance_bootstrap_sentinel$
begin
  perform 1
  from public.finance_organization_projection_state
  where finance_tenant_id = '__edoc_fresh_bootstrap_only__'
  for update;

  if exists (
    select 1
    from public.finance_organization_projection_state
    where finance_tenant_id = '__edoc_fresh_bootstrap_only__'
      and not (
        version_no = 1
        and version_id = 'EDOC-FRESH-BOOTSTRAP-COMPAT-V1'
        and etag = repeat('0', 64)
        and schema_version = 2
        and source_event_id = 'EDOC-FRESH-BOOTSTRAP-COMPAT-V1'
        and source_occurred_at = '1970-01-01T00:00:00Z'
        and payload_sha256 = repeat('0', 64)
        and unit_count = 0
        and assignment_count = 0
        and last_synced_from_finance_at = '1970-01-01 00:00:00+00'::timestamptz
        and updated_at = '1970-01-01 00:00:00+00'::timestamptz
      )
  ) then
    raise exception using
      errcode = '55000',
      message = 'fresh_finance_bootstrap_sentinel_signature_mismatch';
  end if;

  if exists (
    select 1 from public.companies
    where finance_tenant_id = '__edoc_fresh_bootstrap_only__'
  ) or exists (
    select 1 from public.users
    where finance_tenant_id = '__edoc_fresh_bootstrap_only__'
  ) or exists (
    select 1 from public.finance_member_sync_receipts
    where finance_tenant_id = '__edoc_fresh_bootstrap_only__'
  ) or exists (
    select 1 from public.finance_organization_revisions
    where finance_tenant_id = '__edoc_fresh_bootstrap_only__'
  ) or exists (
    select 1 from public.finance_organization_units
    where finance_tenant_id = '__edoc_fresh_bootstrap_only__'
  ) or exists (
    select 1 from public.module_account_links
    where finance_tenant_id = '__edoc_fresh_bootstrap_only__'
  ) then
    raise exception using
      errcode = '55000',
      message = 'fresh_finance_bootstrap_sentinel_has_reference';
  end if;

  delete from public.finance_organization_projection_state
  where finance_tenant_id = '__edoc_fresh_bootstrap_only__';

  if exists (
    select 1
    from public.finance_organization_projection_state
    where finance_tenant_id = '__edoc_fresh_bootstrap_only__'
  ) then
    raise exception using
      errcode = '55000',
      message = 'fresh_finance_bootstrap_sentinel_delete_failed';
  end if;
end
$remove_fresh_finance_bootstrap_sentinel$;

commit;
