create table if not exists public.job_runs (
  id text primary key,
  job_id text not null references public.background_jobs(id) on delete cascade,
  job_type text not null,
  status text not null,
  result text not null,
  started_at text not null,
  finished_at text not null,
  duration_ms integer not null default 0,
  payload_json text
);

create index if not exists idx_job_runs_job on public.job_runs(job_id);
create index if not exists idx_job_runs_finished on public.job_runs(finished_at);

alter table public.job_runs enable row level security;

grant select, insert, update on public.job_runs to authenticated;

drop policy if exists "authenticated read job runs" on public.job_runs;
create policy "authenticated read job runs" on public.job_runs
for select to authenticated using (true);

drop policy if exists "deny anon job runs" on public.job_runs;
create policy "deny anon job runs" on public.job_runs for all to anon using (false) with check (false);

insert into public.background_jobs (id, name, job_type, schedule_text, status, last_result, next_run_at, run_count) values
('JOB-004', '逾期稽催', 'overdueReminder', '每小時', '啟用', '尚未執行', '2026-05-23 10:00', 0),
('JOB-005', '交換狀態同步', 'exchangeSync', '每 15 分鐘', '啟用', '尚未執行', '2026-05-23 09:15', 0),
('JOB-006', '歸檔封存', 'archiveSeal', '每日 18:00', '啟用', '尚未執行', '2026-05-23 18:00', 0),
('JOB-007', '報表產生', 'reportGenerate', '每日 18:00', '啟用', '尚未執行', '2026-05-23 18:00', 0)
on conflict (id) do nothing;
