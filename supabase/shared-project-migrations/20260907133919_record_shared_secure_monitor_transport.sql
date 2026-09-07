-- Shared-schema counterpart of the secure monitoring transport.
-- Replay the exact transformed DDL, preserve activation, then record hashes.
begin;
select pg_catalog.pg_advisory_xact_lock(1788103601, 20260907);

do $preflight$
begin
  if pg_catalog.to_regclass('edoc_private.shared_project_migration_ledger') is null
     or not exists (
       select 1 from edoc_private.shared_project_migration_ledger
       where file_name = '20260907131606_edoc_private_monitoring_schedule.sql'
     )
     or exists (
       select 1 from edoc_private.shared_project_migration_ledger
       where file_name = '20260907132959_edoc_monitor_secure_http_transport.sql'
         and (source_sha256 <> '3edac4ad805a74984426cec2827558cc01d38b1dca64c7076e1e8cde833b893e'
           or transformed_sha256 <> '7fa173db1c49d65c064bc9afb5101c50cb8c7023ef3c61c4740d4d3350aa2389')
     ) then
    raise exception 'shared_monitoring_transport_preflight_failed';
  end if;
end
$preflight$;

-- The managed pg_net owner grants PUBLIC access to its queue, and postgres
-- cannot revoke that grant. Never persist the eDoc bearer in that queue.
-- Use synchronous http 1.6 (no redirect following) and return status only.
-- No URL, secret value, response body, or response headers belong in history.
create extension if not exists http with schema extensions version '1.6';

create or replace function edoc_private.run_monitoring_http()
returns integer
language plpgsql
security invoker
set search_path = pg_catalog, extensions
as $monitor_http$
declare
  base_url text;
  bearer text;
  response_status integer;
begin
  select decrypted_secret into base_url
  from vault.decrypted_secrets where name = 'edoc_monitor_base_url';
  select decrypted_secret into bearer
  from vault.decrypted_secrets where name = 'edoc_monitor_cron_secret';
  if base_url is null or base_url !~ '^https://[a-zA-Z0-9.-]+/?$'
     or bearer is null or length(bearer) < 32 then
    raise exception 'edoc_monitor_configuration_invalid';
  end if;

  -- Dedicated cron connections only; never alter a global database/role option.
  perform extensions.http_reset_curlopt();
  perform extensions.http_set_curlopt('CURLOPT_TIMEOUT_MS', '120000');
  perform extensions.http_set_curlopt('CURLOPT_CONNECTTIMEOUT', '10');
  select status into response_status
  from extensions.http((
    'GET',
    rtrim(base_url, '/') || '/api/cron/monitoring',
    array[('Authorization', 'Bearer ' || bearer)::extensions.http_header],
    null,
    null
  )::extensions.http_request);
  perform extensions.http_reset_curlopt();
  if response_status < 200 or response_status >= 300 then
    raise exception 'edoc_monitor_http_status_%', response_status;
  end if;
  return response_status;
exception when others then
  -- Never forward a libcurl/SQL message that might carry a URL or header.
  raise exception 'edoc_monitor_request_failed';
end;
$monitor_http$;

alter function edoc_private.run_monitoring_http() owner to postgres;
revoke all on function edoc_private.run_monitoring_http()
from public, anon, authenticated, edoc_backend;
-- cron schema has a grant option for postgres; keep client roles excluded.
revoke usage on schema cron from public, anon, authenticated;

do $monitor_transport$
declare monitor_job_id bigint;
begin
  select jobid into monitor_job_id from cron.job
  where jobname = 'edoc-production-monitoring-15min';
  if monitor_job_id is not null then
    -- Preserve the existing active flag, so replay never silently activates
    -- a staged job or disables an already accepted deployment.
    perform cron.alter_job(
      monitor_job_id,
      command := 'select edoc_private.run_monitoring_http();'
    );
  end if;
end;
$monitor_transport$;

-- Preserve the shared bootstrap's final private-function boundary, including
-- legacy service_role as well as the transformed edoc_backend role.
revoke all on function edoc_private.run_monitoring_http()
from public, anon, authenticated, service_role, authenticator, edoc_backend;

insert into edoc_private.shared_project_migration_ledger (
  file_name, source_sha256, transformed_sha256, bundle_version
) values (
  '20260907132959_edoc_monitor_secure_http_transport.sql',
  '3edac4ad805a74984426cec2827558cc01d38b1dca64c7076e1e8cde833b893e',
  '7fa173db1c49d65c064bc9afb5101c50cb8c7023ef3c61c4740d4d3350aa2389',
  'shared-project-schema-v1'
) on conflict (file_name) do nothing;

commit;
