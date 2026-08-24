-- Keep Finance as the company source of truth while ensuring every active
-- company has the same eight Seal Vault upload slots.  This migration creates
-- metadata only: it never fabricates a seal file, hash, storage key or version.

do $$
begin
  if to_regclass('public.companies') is null
     or to_regclass('public.company_seals') is null
     or to_regclass('public.seal_permissions') is null then
    raise exception 'required company seal tables are missing';
  end if;
  if to_regnamespace('private') is null then
    raise exception 'private schema is missing';
  end if;
end
$$;

create or replace function private.edoc_ensure_company_seal_slots_v1(
  p_company_id text
)
returns integer
language plpgsql
security definer
set search_path = pg_catalog, public, private
as $$
declare
  v_created integer := 0;
begin
  if p_company_id is null or btrim(p_company_id) = '' then
    raise exception 'company id is required';
  end if;

  if not exists (
    select 1
    from public.companies company_row
    where company_row.id = p_company_id
      and company_row.status = 'active'
  ) then
    return 0;
  end if;

  with default_slots(
    seal_category,
    seal_size_type,
    seal_name,
    purpose_description
  ) as (
    values
      ('establishment_seal', 'large_seal', '公司設立印鑑－大章', '設立登記、公司變更、重大申請'),
      ('establishment_seal', 'small_seal', '公司設立印鑑－小章', '設立登記、負責人或授權小章'),
      ('bank_seal', 'large_seal', '銀行印鑑章－大章', '銀行往來、帳戶與付款授權'),
      ('bank_seal', 'small_seal', '銀行印鑑章－小章', '銀行往來小章或負責人小章'),
      ('general_seal', 'large_seal', '便章－大章', '日常公文、一般函稿'),
      ('general_seal', 'small_seal', '便章－小章', '一般函稿、內部文件'),
      ('official_seal', 'large_seal', '關防印', '正式公文、機關往來與高敏感文件'),
      ('other', 'large_seal', '其他章', '特殊用途，可由印章管理者調整')
  ),
  inserted as (
    insert into public.company_seals (
      id,
      company_id,
      seal_name,
      seal_category,
      seal_size_type,
      purpose_description,
      is_active,
      created_by,
      created_at,
      updated_at
    )
    select
      concat('CSEAL-', p_company_id, '-', slot.seal_category, '-', slot.seal_size_type),
      p_company_id,
      slot.seal_name,
      slot.seal_category,
      slot.seal_size_type,
      slot.purpose_description,
      true,
      'finance-company-auto-provision',
      to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
      to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
    from default_slots slot
    where not exists (
      select 1
      from public.company_seals existing
      where existing.company_id = p_company_id
        and existing.seal_category = slot.seal_category
        and existing.seal_size_type = slot.seal_size_type
    )
    on conflict (id) do nothing
    returning id
  )
  select count(*) into v_created from inserted;

  insert into public.seal_permissions (
    id,
    seal_id,
    user_id,
    role,
    created_at
  )
  select
    concat('SPERM-', seal_row.id, '-', role_row.role),
    seal_row.id,
    '',
    role_row.role,
    to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
  from public.company_seals seal_row
  cross join (
    values ('viewer'), ('requester'), ('approver'), ('seal_admin')
  ) as role_row(role)
  where seal_row.company_id = p_company_id
    and seal_row.is_active is true
  on conflict (id) do nothing;

  return v_created;
end
$$;

create or replace function private.edoc_company_seal_slots_trigger_v1()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public, private
as $$
begin
  if new.status = 'active' then
    perform private.edoc_ensure_company_seal_slots_v1(new.id);
  end if;
  return new;
end
$$;

alter function private.edoc_ensure_company_seal_slots_v1(text) owner to postgres;
alter function private.edoc_company_seal_slots_trigger_v1() owner to postgres;

revoke all on function private.edoc_ensure_company_seal_slots_v1(text)
  from public, anon, authenticated;
revoke all on function private.edoc_company_seal_slots_trigger_v1()
  from public, anon, authenticated;
grant execute on function private.edoc_ensure_company_seal_slots_v1(text)
  to service_role;

drop trigger if exists companies_edoc_seal_slots_v1 on public.companies;
create trigger companies_edoc_seal_slots_v1
after insert or update of status on public.companies
for each row
when (new.status = 'active')
execute function private.edoc_company_seal_slots_trigger_v1();

select private.edoc_ensure_company_seal_slots_v1(company_row.id)
from public.companies company_row
where company_row.status = 'active';

do $$
declare
  v_missing integer;
begin
  with required_slots(seal_category, seal_size_type) as (
    values
      ('establishment_seal', 'large_seal'),
      ('establishment_seal', 'small_seal'),
      ('bank_seal', 'large_seal'),
      ('bank_seal', 'small_seal'),
      ('general_seal', 'large_seal'),
      ('general_seal', 'small_seal'),
      ('official_seal', 'large_seal'),
      ('other', 'large_seal')
  )
  select count(*)
  into v_missing
  from public.companies company_row
  cross join required_slots required
  where company_row.status = 'active'
    and not exists (
      select 1
      from public.company_seals seal_row
      where seal_row.company_id = company_row.id
        and seal_row.seal_category = required.seal_category
        and seal_row.seal_size_type = required.seal_size_type
        and seal_row.is_active is true
    );

  if v_missing <> 0 then
    raise exception 'active companies are missing % required seal upload slots', v_missing;
  end if;
end
$$;

insert into public.audit_logs (
  id,
  actor,
  action,
  target_type,
  target_id,
  detail
)
values (
  'AUD-COMPANY-SEAL-UPLOAD-SLOTS-20260823-001',
  'Migration',
  '建立公司印章上傳欄位',
  'schema',
  '20260823191041_backfill_company_seal_upload_slots',
  '已為所有 Finance 啟用公司建立八種 Seal Vault metadata 欄位；未建立任何印章檔案或版本。'
)
on conflict (id) do nothing;
