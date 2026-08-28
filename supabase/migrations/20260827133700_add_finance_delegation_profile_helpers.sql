-- Restore the private Finance identity checks required by the workflow
-- delegation triggers and RPCs.  Delegation may substitute an approver, so a
-- company id alone is insufficient: the durable Finance identity, canonical
-- role, EDOC role and organizational level must all agree.

create or replace function edoc_private.assert_finance_delegation_profile(
  p_user_id text
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $function$
declare
  v_user public.users%rowtype;
  v_role_key text;
  v_expected_role text;
  v_expected_job_level text;
  v_job_level text;
begin
  if nullif(pg_catalog.btrim(coalesce(p_user_id, '')), '') is null then
    raise exception using
      errcode = '42501',
      message = 'official_workflow_delegation_finance_actor_ineligible';
  end if;

  select candidate.*
    into v_user
    from public.users as candidate
   where candidate.id = p_user_id
   limit 1;
  if not found then
    raise exception using
      errcode = '42501',
      message = 'official_workflow_delegation_finance_actor_ineligible';
  end if;

  v_role_key := case pg_catalog.btrim(coalesce(v_user.logging_role_key, ''))
    when 'team_member' then 'staff'
    when 'staff' then 'staff'
    when 'employee' then 'staff'
    when 'supervisor' then 'section_chief'
    when 'section_chief' then 'section_chief'
    when 'dept_manager' then 'department_head'
    when 'hr' then 'hr_chief'
    when 'super_admin' then 'ceo'
    when 'company_admin' then 'admin_director'
    when 'hr_manager' then 'hr_chief'
    when 'accounting' then 'accounting_chief'
    when 'accountant' then 'accounting_chief'
    when 'cashier' then 'accounting_chief'
    when 'general_affairs' then 'ga_chief'
    when 'department_manager' then 'department_head'
    when 'homecare_supervisor' then 'section_chief'
    when 'homecare_worker' then 'staff'
    when 'daycare_staff' then 'staff'
    when 'system' then 'system_department'
    when 'system_admin' then 'system_department'
    when 'it' then 'system_department'
    when 'it_admin' then 'system_department'
    when '系統處' then 'system_department'
    when '資訊' then 'system_department'
    when 'admin-director' then 'admin_director'
    when 'hr-chief' then 'hr_chief'
    when 'hr-staff' then 'hr_staff'
    when 'accounting-chief' then 'accounting_chief'
    when 'cashier-chief' then 'accounting_chief'
    when 'ga-chief' then 'ga_chief'
    when 'business-director' then 'department_head'
    when 'department-head' then 'department_head'
    when 'section-chief' then 'section_chief'
    when '課長' then 'section_chief'
    when '主任' then 'department_head'
    when '部門主任' then 'department_head'
    when 'team-lead' then 'team_lead'
    when 'region-manager' then 'district_manager'
    when 'external-audit' then 'external_auditor'
    when 'external-auditor' then 'external_auditor'
    else pg_catalog.btrim(coalesce(v_user.logging_role_key, ''))
  end;

  select expected.role_name, expected.job_level
    into v_expected_role, v_expected_job_level
    from (
      values
        ('board', '董事會', '董事會'),
        ('shareholder', '股東', '股東'),
        ('ceo', '執行長', '執行長'),
        ('district_manager', '主管', '區經理'),
        ('department_head', '主任', '部長'),
        ('section_chief', '主管', '課長'),
        ('team_lead', '主管', '組長'),
        ('staff', '員工', '職員'),
        ('external_auditor', '外部檢核單位', '外部檢核單位'),
        ('system_department', '行政部主任', '部長'),
        ('admin_director', '行政部主任', '部長'),
        ('hr_chief', '人資', '課長'),
        ('hr_staff', '人資', '職員'),
        ('accounting_chief', '會計', '課長'),
        ('ga_chief', '總務', '課長')
    ) as expected(role_key, role_name, job_level)
   where expected.role_key = v_role_key;

  v_job_level := case pg_catalog.btrim(coalesce(v_user.job_level, ''))
    when 'L1 員工' then '職員'
    when 'L2 專員' then '職員'
    when 'L3 主管' then '課長'
    when 'L4 部門主管' then '部長'
    when 'L5 高階主管' then '區經理'
    when 'L6 執行長' then '執行長'
    when '職員' then '職員'
    when '組長' then '組長'
    when '課長' then '課長'
    when '部長' then '部長'
    when '區經理' then '區經理'
    when '執行長' then '執行長'
    when '董事會' then '董事會'
    when '股東' then '股東'
    when '外部檢核單位' then '外部檢核單位'
    else '職員'
  end;

  if v_user.status is distinct from '啟用'
     or pg_catalog.lower(pg_catalog.btrim(coalesce(v_user.account_source, ''))) <> 'finance'
     or nullif(pg_catalog.btrim(coalesce(v_user.auth_user_id::text, '')), '') is null
     or nullif(pg_catalog.btrim(coalesce(v_user.finance_employee_id, '')), '') is null
     or nullif(pg_catalog.btrim(coalesce(v_user.company_id, '')), '') is null
     or nullif(pg_catalog.btrim(coalesce(v_user.title, '')), '') is null
     or v_expected_role is null
     or pg_catalog.btrim(coalesce(v_user.role, '')) is distinct from v_expected_role
     or v_job_level is distinct from v_expected_job_level then
    raise exception using
      errcode = '42501',
      message = 'official_workflow_delegation_finance_actor_ineligible';
  end if;

  return pg_catalog.jsonb_build_object(
    'company_id', pg_catalog.btrim(v_user.company_id),
    'logging_role_key', v_role_key,
    'role', v_expected_role,
    'job_level', v_expected_job_level,
    'title', pg_catalog.btrim(v_user.title)
  );
end;
$function$;

create or replace function edoc_private.finance_actor_has_delegation_manage(
  p_profile jsonb
)
returns boolean
language sql
immutable
set search_path = ''
as $function$
  select coalesce(p_profile->>'logging_role_key', '') = 'admin_director';
$function$;

alter function edoc_private.assert_finance_delegation_profile(text) owner to postgres;
alter function edoc_private.finance_actor_has_delegation_manage(jsonb) owner to postgres;

revoke all on function edoc_private.assert_finance_delegation_profile(text)
  from public, anon, authenticated, service_role;
revoke all on function edoc_private.finance_actor_has_delegation_manage(jsonb)
  from public, anon, authenticated, service_role;

notify pgrst, 'reload schema';
