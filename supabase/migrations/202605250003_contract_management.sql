create table if not exists public.contracts (
  id text primary key,
  contract_no text not null unique,
  company_name text not null default '歲悅長照股份有限公司',
  contract_type text not null default '一般合約',
  title text not null,
  counterparty text not null,
  counterparty_tax_id text,
  owner text not null,
  department text not null,
  amount numeric not null default 0,
  currency text not null default 'TWD',
  start_date text,
  end_date text,
  renewal_alert_days integer not null default 60,
  confidentiality_level text not null default '普通',
  seal_requirement text not null default '一般章',
  storage_status text not null default '待歸檔',
  status text not null default '草稿',
  summary text,
  risk_note text,
  attachment_manifest_json text not null default '[]',
  metadata_json text not null default '{}',
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.contract_parties (
  id text primary key,
  contract_id text not null references public.contracts(id) on delete cascade,
  party_type text not null,
  name text not null,
  tax_id text,
  contact_name text,
  contact_email text,
  contact_phone text,
  address text,
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.contract_approvals (
  id text primary key,
  contract_id text not null references public.contracts(id) on delete cascade,
  step_no integer not null default 1,
  step_name text not null,
  role text not null,
  status text not null default '待簽核',
  approver text,
  comment text,
  signed_at text,
  non_repudiation_json text not null default '{}',
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create index if not exists idx_contracts_status on public.contracts(status);
create index if not exists idx_contracts_owner on public.contracts(owner);
create index if not exists idx_contracts_department on public.contracts(department);
create index if not exists idx_contracts_counterparty on public.contracts(counterparty);
create index if not exists idx_contracts_end_date on public.contracts(end_date);
create index if not exists idx_contract_parties_contract on public.contract_parties(contract_id);
create index if not exists idx_contract_approvals_contract on public.contract_approvals(contract_id);
create index if not exists idx_contract_approvals_role on public.contract_approvals(role);
create index if not exists idx_contract_approvals_status on public.contract_approvals(status);

alter table public.contracts enable row level security;
alter table public.contract_parties enable row level security;
alter table public.contract_approvals enable row level security;

drop policy if exists "service role manages contracts" on public.contracts;
create policy "service role manages contracts"
on public.contracts for all
using (true)
with check (true);

drop policy if exists "service role manages contract parties" on public.contract_parties;
create policy "service role manages contract parties"
on public.contract_parties for all
using (true)
with check (true);

drop policy if exists "service role manages contract approvals" on public.contract_approvals;
create policy "service role manages contract approvals"
on public.contract_approvals for all
using (true)
with check (true);

insert into public.contracts (
  id, contract_no, company_name, contract_type, title, counterparty, counterparty_tax_id,
  owner, department, amount, currency, start_date, end_date, renewal_alert_days,
  confidentiality_level, seal_requirement, storage_status, status, summary, risk_note,
  attachment_manifest_json, metadata_json
)
values
  (
    'CON-1140525-001', '合約字第1140525001號', '歲悅長照股份有限公司', '服務委託合約',
    '日間照顧中心資訊系統維護合約', '康照資訊股份有限公司', '24567890',
    '業務助理', '行政部', 180000, 'TWD', '2026-06-01', '2027-05-31', 60,
    '普通', '一般章', '待歸檔', '待主管審核',
    '年度資訊維護、客服支援、資安弱點修補與 SLA 回覆承諾。',
    '金額超過 10 萬，需會計複核與行政部主任清稿後送執行長核定。',
    '["合約草案.pdf","報價單.pdf","服務範圍清單.xlsx"]',
    '{"approvalTemplate":"amount_over_100k","renewalNotice":"到期前 60 天提醒"}'
  ),
  (
    'CON-1140524-002', '合約字第1140524002號', '歲悅長照股份有限公司', '租賃合約',
    '板橋據點辦公設備租賃合約', '新北設備租賃有限公司', '90345671',
    '總務', '總務', 72000, 'TWD', '2026-06-15', '2027-06-14', 45,
    '普通', '一般章', '待歸檔', '待用印簽署',
    '影印機、掃描設備與耗材保固租賃。',
    '用印前請確認租期、提前解約條款與維修回應時間。',
    '["租賃合約草案.pdf","設備明細.pdf"]',
    '{"approvalTemplate":"standard","renewalNotice":"到期前 45 天提醒"}'
  )
on conflict (id) do nothing;

insert into public.contract_parties (
  id, contract_id, party_type, name, tax_id, contact_name, contact_email, contact_phone, address
)
values
  ('CP-001', 'CON-1140525-001', '甲方', '歲悅長照股份有限公司', '待設定', '張行政', 'records@suiyuecare.com', '(02)2257-7155', '220205 新北市板橋區英士路192之1號'),
  ('CP-002', 'CON-1140525-001', '乙方', '康照資訊股份有限公司', '24567890', '林專員', 'service@example.com', '(02)2999-0000', '新北市板橋區文化路一段1號'),
  ('CP-003', 'CON-1140524-002', '甲方', '歲悅長照股份有限公司', '待設定', '林總務', 'edoc@suiyuecare.com', '(02)2257-7155', '220205 新北市板橋區英士路192之1號'),
  ('CP-004', 'CON-1140524-002', '乙方', '新北設備租賃有限公司', '90345671', '吳小姐', 'lease@example.com', '(02)2666-0000', '新北市新莊區中平路100號')
on conflict (id) do nothing;

insert into public.contract_approvals (
  id, contract_id, step_no, step_name, role, status, approver, comment, signed_at, non_repudiation_json
)
values
  ('CA-001', 'CON-1140525-001', 1, '起案完成', '業務助理', '完成', '周業助', '已上傳草案與報價單。', '2026-05-25 09:12', '{}'),
  ('CA-002', 'CON-1140525-001', 2, '部門主管審核', '主任', '待簽核', '', '請確認服務範圍與 SLA。', '', '{}'),
  ('CA-003', 'CON-1140525-001', 3, '會計複核', '會計', '待簽核', '', '金額超過 10 萬需複核預算。', '', '{}'),
  ('CA-004', 'CON-1140525-001', 4, '行政部主任清稿', '行政部主任', '待簽核', '', '確認合約條款與用印需求。', '', '{}'),
  ('CA-005', 'CON-1140525-001', 5, '執行長核定', '執行長', '待簽核', '', '重大金額合約最終核定。', '', '{}'),
  ('CA-006', 'CON-1140524-002', 1, '起案完成', '總務', '完成', '林總務', '設備租賃合約已完成草案。', '2026-05-24 15:20', '{}'),
  ('CA-007', 'CON-1140524-002', 2, '行政部主任清稿', '行政部主任', '完成', '張行政', '條款與租期已確認。', '2026-05-24 17:10', '{}'),
  ('CA-008', 'CON-1140524-002', 3, '總務用印簽署', '總務', '待簽核', '', '待確認用印與簽署後歸檔。', '', '{}')
on conflict (id) do nothing;

insert into public.audit_logs (id, actor, action, target_type, target_id, detail)
values (
  'AUD-CONTRACT-MGMT-202605250003',
  'system',
  '建立合約管理資料表',
  'contracts',
  'contract-management',
  '已建立合約主檔、合約相對人與合約簽核紀錄，支援合約起案、審核、用印簽署、續約提醒與歸檔。'
)
on conflict (id) do nothing;

insert into public.background_jobs (
  id, name, job_type, schedule_text, status, last_result, next_run_at, run_count, updated_at
)
values (
  'JOB-008',
  '合約到期與續約提醒',
  'contractRenewalCheck',
  '每日 09:30',
  '啟用',
  '尚未執行',
  '2026-05-23 09:30',
  0,
  to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
)
on conflict (id) do nothing;
