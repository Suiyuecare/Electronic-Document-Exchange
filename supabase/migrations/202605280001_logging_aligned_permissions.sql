-- Align eDoc RBAC and permission audit metadata with the Logging module plan.
-- Logging plan uses module.action permission codes and permission_change audit events
-- with before/after snapshots. Existing legacy permission ids are kept for UI
-- compatibility, while new EDOC permissions use module-scoped codes.

alter table public.audit_logs
  add column if not exists event_type text not null default 'submit',
  add column if not exists severity text not null default 'info',
  add column if not exists result text not null default 'success',
  add column if not exists module_code text,
  add column if not exists resource_type text,
  add column if not exists resource_id text,
  add column if not exists data_scope text,
  add column if not exists actor_user_id text,
  add column if not exists actor_email text,
  add column if not exists actor_roles_json text not null default '[]',
  add column if not exists target_user_id text,
  add column if not exists target_email text,
  add column if not exists reason text,
  add column if not exists request_id text,
  add column if not exists before_snapshot_json text not null default '{}',
  add column if not exists after_snapshot_json text not null default '{}',
  add column if not exists metadata_json text not null default '{}';

create index if not exists idx_audit_logs_event_type on public.audit_logs(event_type, created_at);
create index if not exists idx_audit_logs_module on public.audit_logs(module_code, created_at);
create index if not exists idx_audit_logs_resource on public.audit_logs(resource_type, resource_id);
create index if not exists idx_audit_logs_request on public.audit_logs(request_id);

insert into public.roles (id, name, description, data_scope, status) values
  ('ROLE-DIRECTOR', '主任', 'edoc_director：承接所屬部門公文、核准部門分派與追蹤處理時限。', 'department', '啟用'),
  ('ROLE-CEO', '執行長', 'edoc_ceo：核定重大、密件或跨部門高風險公文並查閱全公司資料。', 'company', '啟用'),
  ('ROLE-ADMIN-CHIEF', '行政部主任', 'edoc_admin_chief：管理流程、清稿、角色權限、交換參數、資安與營運維護。', 'company', '啟用'),
  ('ROLE-HR', '人資', 'edoc_hr：處理人資相關來文、發文、附件補正與部門公文紀錄。', 'department', '啟用'),
  ('ROLE-ACCOUNTING', '會計', 'edoc_accounting：處理會計、補助款、核銷相關來文與發文。', 'department', '啟用'),
  ('ROLE-GA', '總務', 'edoc_general_affairs：唯一收文入口；拉取、登錄來文後分發給各部門主管。', 'company', '啟用'),
  ('ROLE-SALES-ASSISTANT', '業務助理', 'edoc_sales_assistant：建立函稿、補附件、協助發文與查詢被分派案件。', 'assigned', '啟用')
on conflict (id) do update set
  name = excluded.name,
  description = excluded.description,
  data_scope = excluded.data_scope,
  status = excluded.status,
  updated_at = to_char(now(), 'YYYY-MM-DD HH24:MI:SS');

update public.roles
set status = '停用', updated_at = to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
where name not in ('主任', '執行長', '行政部主任', '人資', '會計', '總務', '業務助理');

insert into public.permissions (id, code, name, category, description) values
  ('PERM-EDOC-COMPOSE', 'official_documents.compose', '撰寫公文', 'official_documents', '建立函稿、預覽、送簽與補正。'),
  ('PERM-EDOC-TODO', 'official_documents.todo', '公文待辦', 'official_documents', '查看並處理個人或角色待辦。'),
  ('PERM-EDOC-RECORDS', 'official_documents.records', '公文紀錄', 'official_documents', '查詢可見範圍內的收發文紀錄。'),
  ('PERM-EDOC-RECEIVE', 'official_documents.receive', '公文收發', 'official_documents', '總務或授權角色執行收文、登錄、分派與交換處理。'),
  ('PERM-EDOC-ALL-TODO', 'official_documents.all_todo', '全公司公文待辦', 'official_documents', '查看全公司待辦與風險。'),
  ('PERM-EDOC-ALL-RECORDS', 'official_documents.all_records', '全公司公文紀錄', 'official_documents', '查看全公司收發文紀錄。'),
  ('PERM-EXCHANGE-VIEW', 'exchange.view', '交換查詢', 'exchange', '查詢交換狀態、地址簿與交換事件。'),
  ('PERM-EXCHANGE-MANAGE', 'exchange.manage', '交換管理', 'exchange', '管理交換設定、送出、重送、退文與收文確認。'),
  ('PERM-CONTRACTS-VIEW', 'contracts.view', '合約檢視', 'contracts', '查看可見範圍內合約。'),
  ('PERM-CONTRACTS-MANAGE', 'contracts.manage', '合約管理', 'contracts', '建立、簽核、退回、續約與歸檔合約。'),
  ('PERM-CONTRACTS-SEAL', 'contracts.seal', '合約用印', 'contracts', '處理合約用印與留存。'),
  ('PERM-FILES-MANAGE', 'files.manage', '附件管理', 'files', '上傳附件、補正、安全檢查與下載控管。'),
  ('PERM-SEALS-MANAGE', 'seals.manage', '印鑑管理', 'seals', '管理印章、校準尺寸、用印申請與押章設定。'),
  ('PERM-REPORTS-VIEW', 'reports.operational_view', '營運報表檢視', 'reports', '查看營運報表、交換成功率與逾期件。'),
  ('PERM-AUDIT-VIEW', 'audit_logs.view', '稽核檢視', 'audit_logs', '查看 audit log、交換歷程與操作軌跡。'),
  ('PERM-AUDIT-EXPORT', 'audit_logs.export', '稽核匯出', 'audit_logs', '匯出稽核紀錄，並留下 export 事件。'),
  ('PERM-SYSTEM-PERMISSIONS-VIEW', 'system_permissions.view', '權限檢視', 'system_permissions', '查看角色、權限、帳號與授權紀錄。'),
  ('PERM-SYSTEM-PERMISSIONS-MANAGE', 'system_permissions.manage', '權限管理', 'system_permissions', '管理角色、權限、帳號與授權。'),
  ('PERM-SETTINGS-MANAGE', 'settings.system_manage', '系統設定管理', 'settings', '管理環境、參數、通知、備份與維運設定。')
on conflict (id) do update set
  code = excluded.code,
  name = excluded.name,
  category = excluded.category,
  description = excluded.description;

insert into public.role_permissions (role_id, permission_id) values
  ('ROLE-DIRECTOR', 'PERM-EDOC-COMPOSE'), ('ROLE-DIRECTOR', 'PERM-EDOC-TODO'), ('ROLE-DIRECTOR', 'PERM-EDOC-RECORDS'), ('ROLE-DIRECTOR', 'PERM-EXCHANGE-VIEW'), ('ROLE-DIRECTOR', 'PERM-CONTRACTS-VIEW'), ('ROLE-DIRECTOR', 'PERM-CONTRACTS-MANAGE'), ('ROLE-DIRECTOR', 'PERM-FILES-MANAGE'), ('ROLE-DIRECTOR', 'PERM-REPORTS-VIEW'),
  ('ROLE-CEO', 'PERM-EDOC-COMPOSE'), ('ROLE-CEO', 'PERM-EDOC-RECEIVE'), ('ROLE-CEO', 'PERM-EDOC-ALL-TODO'), ('ROLE-CEO', 'PERM-EDOC-ALL-RECORDS'), ('ROLE-CEO', 'PERM-EXCHANGE-VIEW'), ('ROLE-CEO', 'PERM-EXCHANGE-MANAGE'), ('ROLE-CEO', 'PERM-CONTRACTS-VIEW'), ('ROLE-CEO', 'PERM-CONTRACTS-MANAGE'), ('ROLE-CEO', 'PERM-CONTRACTS-SEAL'), ('ROLE-CEO', 'PERM-SEALS-MANAGE'), ('ROLE-CEO', 'PERM-REPORTS-VIEW'), ('ROLE-CEO', 'PERM-AUDIT-VIEW'), ('ROLE-CEO', 'PERM-AUDIT-EXPORT'), ('ROLE-CEO', 'PERM-SYSTEM-PERMISSIONS-VIEW'),
  ('ROLE-ADMIN-CHIEF', 'PERM-EDOC-COMPOSE'), ('ROLE-ADMIN-CHIEF', 'PERM-EDOC-RECEIVE'), ('ROLE-ADMIN-CHIEF', 'PERM-EDOC-ALL-TODO'), ('ROLE-ADMIN-CHIEF', 'PERM-EDOC-ALL-RECORDS'), ('ROLE-ADMIN-CHIEF', 'PERM-EXCHANGE-VIEW'), ('ROLE-ADMIN-CHIEF', 'PERM-EXCHANGE-MANAGE'), ('ROLE-ADMIN-CHIEF', 'PERM-CONTRACTS-VIEW'), ('ROLE-ADMIN-CHIEF', 'PERM-CONTRACTS-MANAGE'), ('ROLE-ADMIN-CHIEF', 'PERM-CONTRACTS-SEAL'), ('ROLE-ADMIN-CHIEF', 'PERM-FILES-MANAGE'), ('ROLE-ADMIN-CHIEF', 'PERM-SEALS-MANAGE'), ('ROLE-ADMIN-CHIEF', 'PERM-REPORTS-VIEW'), ('ROLE-ADMIN-CHIEF', 'PERM-AUDIT-VIEW'), ('ROLE-ADMIN-CHIEF', 'PERM-AUDIT-EXPORT'), ('ROLE-ADMIN-CHIEF', 'PERM-SYSTEM-PERMISSIONS-VIEW'), ('ROLE-ADMIN-CHIEF', 'PERM-SYSTEM-PERMISSIONS-MANAGE'), ('ROLE-ADMIN-CHIEF', 'PERM-SETTINGS-MANAGE'),
  ('ROLE-HR', 'PERM-EDOC-COMPOSE'), ('ROLE-HR', 'PERM-EDOC-TODO'), ('ROLE-HR', 'PERM-EDOC-RECORDS'), ('ROLE-HR', 'PERM-EXCHANGE-VIEW'), ('ROLE-HR', 'PERM-CONTRACTS-VIEW'), ('ROLE-HR', 'PERM-CONTRACTS-MANAGE'), ('ROLE-HR', 'PERM-FILES-MANAGE'), ('ROLE-HR', 'PERM-REPORTS-VIEW'),
  ('ROLE-ACCOUNTING', 'PERM-EDOC-COMPOSE'), ('ROLE-ACCOUNTING', 'PERM-EDOC-TODO'), ('ROLE-ACCOUNTING', 'PERM-EDOC-RECORDS'), ('ROLE-ACCOUNTING', 'PERM-EXCHANGE-VIEW'), ('ROLE-ACCOUNTING', 'PERM-CONTRACTS-VIEW'), ('ROLE-ACCOUNTING', 'PERM-CONTRACTS-MANAGE'), ('ROLE-ACCOUNTING', 'PERM-FILES-MANAGE'), ('ROLE-ACCOUNTING', 'PERM-REPORTS-VIEW'),
  ('ROLE-GA', 'PERM-EDOC-COMPOSE'), ('ROLE-GA', 'PERM-EDOC-RECEIVE'), ('ROLE-GA', 'PERM-EDOC-ALL-TODO'), ('ROLE-GA', 'PERM-EDOC-ALL-RECORDS'), ('ROLE-GA', 'PERM-EXCHANGE-VIEW'), ('ROLE-GA', 'PERM-EXCHANGE-MANAGE'), ('ROLE-GA', 'PERM-CONTRACTS-VIEW'), ('ROLE-GA', 'PERM-CONTRACTS-MANAGE'), ('ROLE-GA', 'PERM-CONTRACTS-SEAL'), ('ROLE-GA', 'PERM-FILES-MANAGE'), ('ROLE-GA', 'PERM-SEALS-MANAGE'), ('ROLE-GA', 'PERM-REPORTS-VIEW'),
  ('ROLE-SALES-ASSISTANT', 'PERM-EDOC-COMPOSE'), ('ROLE-SALES-ASSISTANT', 'PERM-EDOC-TODO'), ('ROLE-SALES-ASSISTANT', 'PERM-EDOC-RECORDS'), ('ROLE-SALES-ASSISTANT', 'PERM-EXCHANGE-VIEW'), ('ROLE-SALES-ASSISTANT', 'PERM-CONTRACTS-VIEW'), ('ROLE-SALES-ASSISTANT', 'PERM-CONTRACTS-MANAGE'), ('ROLE-SALES-ASSISTANT', 'PERM-FILES-MANAGE'), ('ROLE-SALES-ASSISTANT', 'PERM-REPORTS-VIEW')
on conflict (role_id, permission_id) do nothing;
