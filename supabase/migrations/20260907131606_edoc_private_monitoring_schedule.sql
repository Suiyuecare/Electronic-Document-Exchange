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
