-- Forward-only shared-schema monitoring counterpart. This replays the exact
-- transformed source before recording its hashes; it does not enable the job.
begin;
select pg_catalog.pg_advisory_xact_lock(1788103601, 20260907);

do $preflight$
declare
  monitoring_job_active boolean := false;
begin
  if pg_catalog.to_regclass('edoc_private.shared_project_migration_ledger') is null
     or not exists (
       select 1 from edoc_private.shared_project_migration_ledger
       where file_name = '20260907130400_retire_unmapped_legacy_company_projection.sql'
     )
     or exists (
       select 1 from edoc_private.shared_project_migration_ledger
       where file_name = '20260907131606_edoc_private_monitoring_schedule.sql'
         and (source_sha256 <> '32ee2435869b3d78f29c717b97be3f97f2dd9a38807c95f413fe3d79458b2aeb'
           or transformed_sha256 <> '32ee2435869b3d78f29c717b97be3f97f2dd9a38807c95f413fe3d79458b2aeb')
     ) then
    raise exception 'shared_monitoring_schedule_preflight_failed';
  end if;
  if pg_catalog.to_regclass('cron.job') is not null then
    execute 'select exists (select 1 from cron.job where jobname = ''edoc-production-monitoring-15min'' and active)'
      into monitoring_job_active;
  end if;
  if monitoring_job_active then
    raise exception 'shared_monitoring_job_already_active';
  end if;
end
$preflight$;

-- eDoc-only monitoring scheduler. No URL or credential value belongs here.
-- Operators populate named Vault secrets through a private parameterized
-- connection, verify the endpoint, and then activate this specific job.
create extension if not exists pg_cron with schema pg_catalog;
create extension if not exists pg_net with schema extensions;

do $edoc_monitor$
declare
  monitor_job_id bigint;
begin
  if not exists (select 1 from vault.secrets where name = 'edoc_monitor_base_url')
     or not exists (select 1 from vault.secrets where name = 'edoc_monitor_cron_secret') then
    return;
  end if;

  select cron.schedule(
    'edoc-production-monitoring-15min',
    '*/15 * * * *',
    $job$
      select net.http_get(
        url := rtrim((select decrypted_secret from vault.decrypted_secrets where name = 'edoc_monitor_base_url'), '/') || '/api/cron/monitoring',
        headers := jsonb_build_object('Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'edoc_monitor_cron_secret')),
        timeout_milliseconds := 120000
      );
    $job$
  ) into monitor_job_id;
  perform cron.alter_job(monitor_job_id, active := false);
end;
$edoc_monitor$;

-- Do not change any other module's scheduled jobs, Vault secrets, or grants.

insert into edoc_private.shared_project_migration_ledger (
  file_name, source_sha256, transformed_sha256, bundle_version
) values (
  '20260907131606_edoc_private_monitoring_schedule.sql',
  '32ee2435869b3d78f29c717b97be3f97f2dd9a38807c95f413fe3d79458b2aeb',
  '32ee2435869b3d78f29c717b97be3f97f2dd9a38807c95f413fe3d79458b2aeb',
  'shared-project-schema-v1'
) on conflict (file_name) do nothing;

commit;
