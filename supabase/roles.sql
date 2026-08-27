-- Fresh-bootstrap prerequisite for the historical RBAC chain.
--
-- Supabase loads roles.sql before timestamped migrations. The legacy
-- 202605230005 migration assigns these permission IDs, while the original
-- repository never inserted them first. Define only the missing reference
-- table/rows here so a new or disaster-recovery database can replay the
-- immutable applied migrations without rewriting their history.
--
-- This file contains no accounts, credentials, documents, company data or
-- privilege statements. Later migrations keep ownership, RLS and current module-scoped
-- permissions authoritative.

create table if not exists public.permissions (
  id text primary key,
  code text not null unique,
  name text not null,
  category text not null,
  description text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

insert into public.permissions (id, code, name, category, description) values
  ('PERM-INBOUND', 'inbound.manage', '收文管理', '公文', '拉取、登錄、分派與誤送漏送處理。'),
  ('PERM-DISPATCH', 'dispatch.manage', '發文管理', '公文', '建立函稿、清稿、封裝、送交與重送。'),
  ('PERM-JAGENT', 'jagent.manage', 'jAgent 介接', '系統', '憑證登入、Token、交換中心與地址簿。'),
  ('PERM-WORKFLOW', 'workflow.approve', '簽核流程', '流程', '簽核、退回、抽回、加簽、會辦與改派。'),
  ('PERM-SEAL', 'seal.apply', '自動用印', '印鑑', 'PDF 套版、押章與用印紀錄。'),
  ('PERM-AUDIT', 'audit.view', '稽核查閱', '稽核', 'Audit log、交換事件與不可否認紀錄。'),
  ('PERM-SECURITY', 'security.manage', '資安管理', '資安', 'RBAC、IP/裝置限制、MFA 與 Token 過期。'),
  ('PERM-REPORT', 'reports.view', '報表統計', '報表', '收發量、成功率、異常、承辦量與逾期件。'),
  ('PERM-SETTINGS', 'settings.manage', '系統設定', '系統', '機關代碼、API URL、防火牆、憑證與角色。')
on conflict (id) do update set
  code = excluded.code,
  name = excluded.name,
  category = excluded.category,
  description = excluded.description;
