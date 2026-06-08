-- Add personnel job levels aligned with the eDoc login identity plan.
-- Role controls permissions; job_level records organizational seniority for account registration and audit review.

alter table public.users
  add column if not exists job_level text not null default '職員';

update public.users
set job_level = case role
  when '員工' then '職員'
  when '業務助理' then '職員'
  when '主管' then '課長'
  when '人資' then '課長'
  when '會計' then '課長'
  when '總務' then '課長'
  when '主任' then '部長'
  when '行政部主任' then '部長'
  when '執行長' then '執行長'
  else coalesce(nullif(job_level, ''), '職員')
end
where job_level is null
   or job_level = ''
   or role in ('員工', '業務助理', '主管', '人資', '會計', '總務', '主任', '行政部主任', '執行長');

create index if not exists idx_users_job_level on public.users(job_level);
