-- Align EDOC roles with the employee roster / Logging job-level plan.
-- The uploaded roster has blank module-permission and data-scope columns, so
-- default EDOC access is derived from job level, title, department and explicit
-- special-role titles. No employee names or emails are stored in this migration.

alter table public.users
  alter column job_level set default '職員';

update public.users
set job_level = case job_level
  when 'L1 員工' then '職員'
  when 'L2 專員' then '職員'
  when 'L3 主管' then '課長'
  when 'L4 部門主管' then '部長'
  when 'L5 高階主管' then '區經理'
  when 'L6 執行長' then '執行長'
  else coalesce(nullif(job_level, ''), '職員')
end
where job_level is null
   or job_level = ''
   or job_level in ('L1 員工', 'L2 專員', 'L3 主管', 'L4 部門主管', 'L5 高階主管', 'L6 執行長');

insert into public.roles (id, name, description, data_scope, status) values
  ('ROLE-EMPLOYEE', '員工', 'edoc_employee：撰寫公文、處理個人待辦並查詢所屬部門公文紀錄。', 'department', '啟用'),
  ('ROLE-SUPERVISOR', '主管', 'edoc_supervisor：承接所屬部門簽核、退回補正與部門公文紀錄。', 'department', '啟用'),
  ('ROLE-BOARD', '董事會', 'edoc_board：查閱全公司治理層級公文、合約與稽核紀錄，不處理日常收發。', 'group', '啟用'),
  ('ROLE-SHAREHOLDER', '股東', 'edoc_shareholder：查閱經授權的全公司彙總紀錄與治理報表，不處理日常收發。', 'group', '啟用'),
  ('ROLE-EXTERNAL-AUDITOR', '外部檢核單位', 'edoc_external_auditor：僅查閱被授權的檢核資料與 audit log。', 'custom', '啟用')
on conflict (id) do update set
  name = excluded.name,
  description = excluded.description,
  data_scope = excluded.data_scope,
  status = excluded.status,
  updated_at = to_char(now(), 'YYYY-MM-DD HH24:MI:SS');

update public.roles
set status = '啟用', updated_at = to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
where name in ('員工', '主管', '主任', '執行長', '行政部主任', '人資', '會計', '總務', '業務助理', '董事會', '股東', '外部檢核單位');

insert into public.role_permissions (role_id, permission_id) values
  ('ROLE-EMPLOYEE', 'PERM-EDOC-COMPOSE'),
  ('ROLE-EMPLOYEE', 'PERM-EDOC-TODO'),
  ('ROLE-EMPLOYEE', 'PERM-EDOC-RECORDS'),
  ('ROLE-EMPLOYEE', 'PERM-EXCHANGE-VIEW'),
  ('ROLE-EMPLOYEE', 'PERM-FILES-MANAGE'),
  ('ROLE-EMPLOYEE', 'PERM-DISPATCH'),
  ('ROLE-EMPLOYEE', 'PERM-WORKFLOW'),
  ('ROLE-SUPERVISOR', 'PERM-EDOC-COMPOSE'),
  ('ROLE-SUPERVISOR', 'PERM-EDOC-TODO'),
  ('ROLE-SUPERVISOR', 'PERM-EDOC-RECORDS'),
  ('ROLE-SUPERVISOR', 'PERM-EXCHANGE-VIEW'),
  ('ROLE-SUPERVISOR', 'PERM-FILES-MANAGE'),
  ('ROLE-SUPERVISOR', 'PERM-REPORTS-VIEW'),
  ('ROLE-SUPERVISOR', 'PERM-DISPATCH'),
  ('ROLE-SUPERVISOR', 'PERM-WORKFLOW'),
  ('ROLE-SUPERVISOR', 'PERM-REPORT'),
  ('ROLE-BOARD', 'PERM-EDOC-ALL-RECORDS'),
  ('ROLE-BOARD', 'PERM-CONTRACTS-VIEW'),
  ('ROLE-BOARD', 'PERM-REPORTS-VIEW'),
  ('ROLE-BOARD', 'PERM-AUDIT-VIEW'),
  ('ROLE-BOARD', 'PERM-SYSTEM-PERMISSIONS-VIEW'),
  ('ROLE-BOARD', 'PERM-AUDIT'),
  ('ROLE-BOARD', 'PERM-REPORT'),
  ('ROLE-SHAREHOLDER', 'PERM-EDOC-ALL-RECORDS'),
  ('ROLE-SHAREHOLDER', 'PERM-CONTRACTS-VIEW'),
  ('ROLE-SHAREHOLDER', 'PERM-REPORTS-VIEW'),
  ('ROLE-SHAREHOLDER', 'PERM-AUDIT-VIEW'),
  ('ROLE-SHAREHOLDER', 'PERM-REPORT'),
  ('ROLE-EXTERNAL-AUDITOR', 'PERM-EDOC-RECORDS'),
  ('ROLE-EXTERNAL-AUDITOR', 'PERM-AUDIT-VIEW'),
  ('ROLE-EXTERNAL-AUDITOR', 'PERM-REPORTS-VIEW'),
  ('ROLE-EXTERNAL-AUDITOR', 'PERM-AUDIT'),
  ('ROLE-EXTERNAL-AUDITOR', 'PERM-REPORT')
on conflict (role_id, permission_id) do nothing;
