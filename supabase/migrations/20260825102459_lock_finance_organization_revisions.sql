-- Published Finance organization revisions are an append-only audit source.
-- Keep service_role INSERT/SELECT for the atomic projection RPC, but make a
-- later accidental grant or direct service call unable to rewrite history.

begin;

set local lock_timeout = '5s';
set local statement_timeout = '30s';

revoke update, delete, truncate
  on public.finance_organization_revisions
  from public, anon, authenticated, service_role;

create or replace function public.edoc_reject_finance_organization_revision_mutation()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
  raise exception using
    errcode = '55000',
    message = 'finance_organization_revision_immutable';
end
$$;

alter function public.edoc_reject_finance_organization_revision_mutation()
  owner to postgres;

revoke all on function public.edoc_reject_finance_organization_revision_mutation()
  from public, anon, authenticated, service_role;

drop trigger if exists finance_organization_revisions_reject_update_delete
  on public.finance_organization_revisions;
create trigger finance_organization_revisions_reject_update_delete
  before update or delete on public.finance_organization_revisions
  for each row execute function public.edoc_reject_finance_organization_revision_mutation();

drop trigger if exists finance_organization_revisions_reject_truncate
  on public.finance_organization_revisions;
create trigger finance_organization_revisions_reject_truncate
  before truncate on public.finance_organization_revisions
  for each statement execute function public.edoc_reject_finance_organization_revision_mutation();

comment on function public.edoc_reject_finance_organization_revision_mutation() is
  'Rejects UPDATE, DELETE and TRUNCATE against immutable Finance organization revision history.';

commit;
