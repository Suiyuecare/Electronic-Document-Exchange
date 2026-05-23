-- Align eDoc production RBAC with the operating rule:
-- General Affairs is the only inbound receiving desk, then dispatches to department heads.
-- Only these roles may use the eDoc module: 主任、執行長、行政部主任、人資、會計、總務、業務助理.

insert into public.roles (id, name, description, data_scope, status) values
('ROLE-DIRECTOR', '主任', '承接所屬部門公文、核准部門分派與追蹤處理時限。', 'department', '啟用'),
('ROLE-CEO', '執行長', '核定重大、密件或跨部門高風險公文並查閱全域報表。', 'all', '啟用'),
('ROLE-ADMIN-CHIEF', '行政部主任', '管理流程、清稿、角色、jAgent 參數、資安與營運維護。', 'all', '啟用'),
('ROLE-HR', '人資', '處理人資相關來文、發文與附件補正。', 'department', '啟用'),
('ROLE-ACCOUNTING', '會計', '處理會計、補助款、核銷相關來文與發文。', 'department', '啟用'),
('ROLE-GA', '總務', '唯一收文入口；拉取、登錄來文後分發給各部門主管。', 'all', '啟用'),
('ROLE-SALES-ASSISTANT', '業務助理', '建立函稿、補附件、協助發文與查詢被分派案件。', 'assigned', '啟用')
on conflict (id) do update set
  name = excluded.name,
  description = excluded.description,
  data_scope = excluded.data_scope,
  status = excluded.status,
  updated_at = now();

update public.roles
set status = '停用', updated_at = now()
where name not in ('主任', '執行長', '行政部主任', '人資', '會計', '總務', '業務助理');

insert into public.role_permissions (role_id, permission_id) values
('ROLE-DIRECTOR', 'PERM-INBOUND'), ('ROLE-DIRECTOR', 'PERM-DISPATCH'), ('ROLE-DIRECTOR', 'PERM-WORKFLOW'), ('ROLE-DIRECTOR', 'PERM-REPORT'),
('ROLE-CEO', 'PERM-INBOUND'), ('ROLE-CEO', 'PERM-DISPATCH'), ('ROLE-CEO', 'PERM-WORKFLOW'), ('ROLE-CEO', 'PERM-AUDIT'), ('ROLE-CEO', 'PERM-REPORT'),
('ROLE-ADMIN-CHIEF', 'PERM-INBOUND'), ('ROLE-ADMIN-CHIEF', 'PERM-DISPATCH'), ('ROLE-ADMIN-CHIEF', 'PERM-JAGENT'), ('ROLE-ADMIN-CHIEF', 'PERM-WORKFLOW'), ('ROLE-ADMIN-CHIEF', 'PERM-SEAL'), ('ROLE-ADMIN-CHIEF', 'PERM-AUDIT'), ('ROLE-ADMIN-CHIEF', 'PERM-SECURITY'), ('ROLE-ADMIN-CHIEF', 'PERM-REPORT'), ('ROLE-ADMIN-CHIEF', 'PERM-SETTINGS'),
('ROLE-HR', 'PERM-INBOUND'), ('ROLE-HR', 'PERM-DISPATCH'), ('ROLE-HR', 'PERM-WORKFLOW'), ('ROLE-HR', 'PERM-REPORT'),
('ROLE-ACCOUNTING', 'PERM-INBOUND'), ('ROLE-ACCOUNTING', 'PERM-DISPATCH'), ('ROLE-ACCOUNTING', 'PERM-WORKFLOW'), ('ROLE-ACCOUNTING', 'PERM-REPORT'),
('ROLE-GA', 'PERM-INBOUND'), ('ROLE-GA', 'PERM-DISPATCH'), ('ROLE-GA', 'PERM-JAGENT'), ('ROLE-GA', 'PERM-WORKFLOW'), ('ROLE-GA', 'PERM-REPORT'),
('ROLE-SALES-ASSISTANT', 'PERM-DISPATCH'), ('ROLE-SALES-ASSISTANT', 'PERM-WORKFLOW'), ('ROLE-SALES-ASSISTANT', 'PERM-REPORT')
on conflict (role_id, permission_id) do nothing;

insert into public.users (id, name, email, password_hash, unit, title, role, provider, mfa_status, status) values
('USR-001', '林總務', 'edoc@suiyuecare.com', 'pbkdf2_sha256$622057556f08af8493df12e74ad7983b$017349cb0c360d23daa17e3baeb64776915f73758a1845d064d5211a356745b7', '總管理處', '總務', '總務', 'Google Workspace', '已啟用', '啟用'),
('USR-002', '張行政', 'records@suiyuecare.com', 'pbkdf2_sha256$84869515ca7759d72177dce8d4c2ca68$3baecf2b36ff55f0e19b92604f77bd030f88ec36c15e2c10e12ef9b815063262', '行政部', '行政部主任', '行政部主任', 'Microsoft Entra', '已啟用', '啟用'),
('USR-003', '王主任', 'director@suiyuecare.com', 'pbkdf2_sha256$8be7da483b04cbf4e06adf98fd4f287c$79e7c06ee0f8032a4b3f8c816f8638a81d0d6f213a7f7c4363d819722e0fe800', '營運管理處', '主任', '主任', 'Google Workspace', '已啟用', '啟用'),
('USR-004', '陳執行長', 'ceo@suiyuecare.com', 'pbkdf2_sha256$622057556f08af8493df12e74ad7983b$017349cb0c360d23daa17e3baeb64776915f73758a1845d064d5211a356745b7', '經營管理', '執行長', '執行長', 'Google Workspace', '已啟用', '啟用'),
('USR-005', '何人資', 'hr@suiyuecare.com', 'pbkdf2_sha256$622057556f08af8493df12e74ad7983b$017349cb0c360d23daa17e3baeb64776915f73758a1845d064d5211a356745b7', '人資', '人資', '人資', 'Microsoft Entra', '已啟用', '啟用'),
('USR-006', '許會計', 'accounting@suiyuecare.com', 'pbkdf2_sha256$622057556f08af8493df12e74ad7983b$017349cb0c360d23daa17e3baeb64776915f73758a1845d064d5211a356745b7', '會計', '會計', '會計', 'Microsoft Entra', '已啟用', '啟用'),
('USR-007', '周業助', 'sales-assistant@suiyuecare.com', 'pbkdf2_sha256$622057556f08af8493df12e74ad7983b$017349cb0c360d23daa17e3baeb64776915f73758a1845d064d5211a356745b7', '業務部', '業務助理', '業務助理', 'Google Workspace', '待設定', '啟用')
on conflict (id) do update set
  name = excluded.name,
  unit = excluded.unit,
  title = excluded.title,
  role = excluded.role,
  provider = excluded.provider,
  mfa_status = excluded.mfa_status,
  status = excluded.status;

update public.users
set status = '停用'
where role not in ('主任', '執行長', '行政部主任', '人資', '會計', '總務', '業務助理');

update public.notification_rules
set target_role = '總務', rule_text = 'jAgent 拉取來文後立即通知總務。'
where type = '收文';
