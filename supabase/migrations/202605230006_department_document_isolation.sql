-- Department document isolation policy.
-- 總務與行政部主任不可直接檢視彼此部門公文；跨部門公文需透過分派、會辦、簽核或授權紀錄。

update public.roles
set description = '唯一收文入口；只能處理 jAgent 來文拉取、收文登錄與待分發池，不直接檢視行政部主任部門公文。',
    data_scope = 'general_affairs_inbox',
    updated_at = now()
where id = 'ROLE-GA';

update public.roles
set description = '管理行政部清稿、簽核、維運與授權案件，不直接檢視總務收發池。',
    data_scope = 'admin_department',
    updated_at = now()
where id = 'ROLE-ADMIN-CHIEF';

insert into public.audit_logs (id, actor, action, target_type, target_id, detail)
values (
  'AUD-202605230006',
  'migration',
  '啟用部門公文隔離',
  'rbac',
  'department-document-isolation',
  '總務與行政部主任的公文清單依 owner / department / session role 隔離；跨部門需留下分派、會辦或簽核紀錄。'
)
on conflict (id) do nothing;

update public.documents
set owner = '總務'
where owner in ('總收發', '總收發人員');

update public.documents
set owner = '行政部主任'
where owner in ('文書主管', '資訊管理員');

update public.documents
set owner = '主任'
where owner = '稽核人員';

update public.documents
set owner = '業務助理'
where owner = '承辦人';

update public.documents
set department = '總務'
where owner = '總務' and department = '總管理處';

update public.documents
set department = '行政部'
where owner = '行政部主任' and department = '總管理處';

insert into public.documents (
  id, doc_no, direction, doc_type, priority, security_level, agency_name, agency_code,
  subject, body, status, owner, department, due_date, received_at
) values (
  'DOC-ADMIN-1140523-001',
  '行管字第1140523001號',
  '發文',
  '函',
  '普通件',
  '普通',
  '臺北市政府社會局',
  'A63000000J',
  '檢送行政部內部流程控管與清稿規則修訂資料。',
  '本件屬行政部主任工作區範例，用於驗證總務與行政部門公文隔離。',
  '待清稿',
  '行政部主任',
  '行政部',
  '2026-05-30',
  null
)
on conflict (id) do nothing;
