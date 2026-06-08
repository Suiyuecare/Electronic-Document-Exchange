alter table public.documents
  add column if not exists company_name text not null default '歲悅長照股份有限公司',
  add column if not exists seal_plan_json text not null default '{}',
  add column if not exists metadata_json text not null default '{}';

create table if not exists public.company_registry (
  id text primary key,
  name text not null unique,
  tax_id text not null default '待設定',
  status text not null default '啟用',
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.department_registry (
  id text primary key,
  company_name text not null,
  name text not null,
  manager_role text not null,
  status text not null default '啟用',
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  unique(company_name, name)
);

create table if not exists public.seal_type_registry (
  id text primary key,
  name text not null unique,
  scope text not null default '未設定使用範圍',
  status text not null default '啟用',
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists public.workflow_tasks (
  id text primary key,
  document_id text references public.documents(id) on delete cascade,
  title text not null,
  workflow_type text not null default '發文',
  step text not null,
  role text not null,
  status text not null,
  template text not null default 'standard',
  current_step_index integer not null default 0,
  requester text,
  submitted_at text,
  last_signed_at text,
  last_comment text,
  proof_json text not null default '{}',
  created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create index if not exists idx_company_registry_status on public.company_registry(status);
create index if not exists idx_department_registry_company on public.department_registry(company_name);
create index if not exists idx_seal_type_registry_status on public.seal_type_registry(status);
create index if not exists idx_workflow_tasks_document on public.workflow_tasks(document_id);
create index if not exists idx_workflow_tasks_status on public.workflow_tasks(status);
create index if not exists idx_workflow_tasks_role on public.workflow_tasks(role);

alter table public.company_registry enable row level security;
alter table public.department_registry enable row level security;
alter table public.seal_type_registry enable row level security;
alter table public.workflow_tasks enable row level security;

drop policy if exists "service role manages company registry" on public.company_registry;
create policy "service role manages company registry"
on public.company_registry for all
using (true)
with check (true);

drop policy if exists "service role manages department registry" on public.department_registry;
create policy "service role manages department registry"
on public.department_registry for all
using (true)
with check (true);

drop policy if exists "service role manages seal type registry" on public.seal_type_registry;
create policy "service role manages seal type registry"
on public.seal_type_registry for all
using (true)
with check (true);

drop policy if exists "service role manages workflow tasks" on public.workflow_tasks;
create policy "service role manages workflow tasks"
on public.workflow_tasks for all
using (true)
with check (true);

insert into public.company_registry (id, name, tax_id, status)
values ('CO-001', '歲悅長照股份有限公司', '待設定', '啟用')
on conflict (id) do nothing;

insert into public.department_registry (id, company_name, name, manager_role, status)
values
  ('DEP-001', '歲悅長照股份有限公司', '總管理處', '執行長', '啟用'),
  ('DEP-002', '歲悅長照股份有限公司', '行政部', '行政部主任', '啟用'),
  ('DEP-003', '歲悅長照股份有限公司', '總務', '總務', '啟用')
on conflict (id) do nothing;

insert into public.seal_type_registry (id, name, scope, status)
values
  ('ST-001', '一般章', '日常公文、一般函稿', '啟用'),
  ('ST-002', '公司設立章', '設立登記、公司變更、重大文件', '啟用'),
  ('ST-003', '銀行印鑑章', '銀行往來、帳戶、授權文件', '啟用'),
  ('ST-004', '圖記章', '政府機關登記圖記、正式用印', '啟用')
on conflict (id) do nothing;
