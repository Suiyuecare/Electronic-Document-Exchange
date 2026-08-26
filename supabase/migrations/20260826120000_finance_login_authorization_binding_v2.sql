-- Bind the signed Finance authorization snapshot to the exact eDoc projection
-- in the same transaction that creates the login session. This closes the
-- final-read -> session-RPC race and intentionally has no legacy RPC fallback.

do $$
begin
  if to_regclass('public.users') is null
     or to_regclass('public.companies') is null
     or to_regclass('public.auth_sessions') is null
     or to_regclass('public.login_events') is null
     or to_regclass('public.roles') is null
     or to_regclass('public.role_permissions') is null
     or to_regclass('public.permissions') is null then
    raise exception 'finance login authorization binding prerequisites are missing';
  end if;
end
$$;

create or replace function public.edoc_create_finance_login_session_v2(
  p_user_id text,
  p_session_id text,
  p_token_hash text,
  p_provider text,
  p_ip text,
  p_device text,
  p_expires_at text,
  p_created_at text,
  p_login_event_id text,
  p_expected_tenant_id text,
  p_expected_company_id text,
  p_expected_entity_id text,
  p_expected_finance_user_id text,
  p_expected_email text,
  p_expected_role text,
  p_expected_logging_role_key text,
  p_expected_job_level text,
  p_expected_unit text,
  p_expected_title text,
  p_expected_status text,
  p_expected_projection_state text
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_user public.users%rowtype;
  v_company public.companies%rowtype;
  v_session public.auth_sessions%rowtype;
  v_permissions jsonb := '[]'::jsonb;
begin
  perform pg_catalog.set_config('statement_timeout', '3000', true);

  if p_user_id is null or btrim(p_user_id) = ''
     or p_session_id is null or btrim(p_session_id) = ''
     or p_login_event_id is null or btrim(p_login_event_id) = ''
     or p_token_hash is null or p_token_hash !~ '^[0-9a-f]{64}$'
     or p_expires_at is null or p_expires_at !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$'
     or p_created_at is null or p_created_at !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$'
     or nullif(btrim(coalesce(p_expected_tenant_id, '')), '') is null
     or nullif(btrim(coalesce(p_expected_company_id, '')), '') is null
     or nullif(btrim(coalesce(p_expected_entity_id, '')), '') is null
     or nullif(btrim(coalesce(p_expected_finance_user_id, '')), '') is null
     or nullif(btrim(coalesce(p_expected_email, '')), '') is null
     or nullif(btrim(coalesce(p_expected_role, '')), '') is null
     or nullif(btrim(coalesce(p_expected_logging_role_key, '')), '') is null
     or nullif(btrim(coalesce(p_expected_job_level, '')), '') is null
     or nullif(btrim(coalesce(p_expected_unit, '')), '') is null
     or nullif(btrim(coalesce(p_expected_title, '')), '') is null
     or p_expected_status <> '啟用'
     or p_expected_projection_state <> 'active' then
    raise exception using errcode = '22023', message = 'finance_login_session_input_invalid';
  end if;

  -- Lock parent then child in one fixed order so authorization bindings cannot
  -- change between validation and session creation.
  select company_row.*
  into v_company
  from public.companies company_row
  where company_row.id = p_expected_company_id
  for update;

  if not found then
    raise exception using errcode = '28000', message = 'finance_login_authorization_binding_mismatch';
  end if;

  select user_row.*
  into v_user
  from public.users user_row
  where user_row.id = p_user_id
  for update;

  if not found then
    raise exception using errcode = '28000', message = 'finance_login_authorization_binding_mismatch';
  end if;

  if lower(btrim(coalesce(v_user.account_source, ''))) <> 'finance'
     or lower(btrim(coalesce(v_user.email, ''))) <> lower(btrim(p_expected_email))
     or btrim(coalesce(v_user.logging_account_id, '')) <> btrim(p_expected_finance_user_id)
     or btrim(coalesce(v_user.finance_employee_id, '')) <> btrim(p_expected_finance_user_id)
     or btrim(coalesce(v_user.finance_tenant_id, '')) <> btrim(p_expected_tenant_id)
     or btrim(coalesce(v_user.company_id, '')) <> btrim(p_expected_company_id)
     or btrim(coalesce(v_user.role, '')) <> btrim(p_expected_role)
     or btrim(coalesce(v_user.logging_role_key, '')) <> btrim(p_expected_logging_role_key)
     or btrim(coalesce(v_user.job_level, '')) <> btrim(p_expected_job_level)
     or btrim(coalesce(v_user.unit, '')) <> btrim(p_expected_unit)
     or btrim(coalesce(v_user.title, '')) <> btrim(p_expected_title)
     or btrim(coalesce(v_user.status, '')) <> p_expected_status
     or btrim(coalesce(v_user.finance_source_status, '')) <> p_expected_projection_state
     or btrim(coalesce(v_company.finance_entity_id, '')) <> btrim(p_expected_entity_id)
     or btrim(coalesce(v_company.finance_tenant_id, '')) <> btrim(p_expected_tenant_id)
     or lower(btrim(coalesce(v_company.source_system, ''))) <> 'finance'
     or lower(btrim(coalesce(v_company.status, ''))) <> 'active'
     or v_user.role not in (
       '員工', '業務助理', '主管', '主任', '行政部主任', '總務',
       '執行長', '人資', '會計', '董事會', '股東', '外部檢核單位'
     ) then
    raise exception using errcode = '28000', message = 'finance_login_authorization_binding_mismatch';
  end if;

  insert into public.auth_sessions (
    id, user_id, token_hash, provider, ip, device, expires_at, created_at
  ) values (
    p_session_id,
    v_user.id,
    p_token_hash,
    left(coalesce(nullif(btrim(p_provider), ''), 'Finance Google SSO'), 120),
    left(coalesce(p_ip, ''), 120),
    left(coalesce(p_device, ''), 500),
    p_expires_at,
    p_created_at
  )
  returning * into v_session;

  update public.users
  set last_login_at = p_created_at,
      last_synced_from_logging_at = p_created_at
  where id = v_user.id
  returning * into v_user;

  insert into public.login_events (
    id, user_id, email, provider, ip, device, status, reason, created_at
  ) values (
    p_login_event_id,
    v_user.id,
    v_user.email,
    left(coalesce(nullif(btrim(p_provider), ''), 'Finance Google SSO'), 120),
    left(coalesce(p_ip, ''), 120),
    left(coalesce(p_device, ''), 500),
    '成功',
    'Finance 授權快照與既有投影原子比對後進入公文收發電子用印系統',
    p_created_at
  );

  select coalesce(jsonb_agg(permission_code.code order by permission_code.code), '[]'::jsonb)
  into v_permissions
  from (
    select distinct permission_row.code
    from public.roles role_row
    join public.role_permissions role_permission_row
      on role_permission_row.role_id = role_row.id
    join public.permissions permission_row
      on permission_row.id = role_permission_row.permission_id
    where role_row.name = v_user.role
      and role_row.status = '啟用'
  ) permission_code;

  return jsonb_build_object(
    'session', jsonb_build_object(
      'id', v_session.id,
      'user_id', v_session.user_id,
      'provider', v_session.provider,
      'expires_at', v_session.expires_at,
      'created_at', v_session.created_at
    ),
    'user', to_jsonb(v_user) - 'password_hash',
    'permissions', v_permissions
  );
end
$$;

create or replace function public.edoc_revalidate_finance_session_v2(
  p_session_id text,
  p_user_id text,
  p_token_hash text,
  p_verified_at text,
  p_expected_tenant_id text,
  p_expected_company_id text,
  p_expected_entity_id text,
  p_expected_finance_user_id text,
  p_expected_email text,
  p_expected_role text,
  p_expected_logging_role_key text,
  p_expected_job_level text,
  p_expected_unit text,
  p_expected_title text,
  p_expected_status text,
  p_expected_projection_state text
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_session public.auth_sessions%rowtype;
  v_company public.companies%rowtype;
  v_user public.users%rowtype;
  v_permissions jsonb := '[]'::jsonb;
begin
  perform pg_catalog.set_config('statement_timeout', '3000', true);

  if p_session_id is null or btrim(p_session_id) = ''
     or p_user_id is null or btrim(p_user_id) = ''
     or p_token_hash is null or p_token_hash !~ '^[0-9a-f]{64}$'
     or p_verified_at is null or p_verified_at !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$'
     or nullif(btrim(coalesce(p_expected_tenant_id, '')), '') is null
     or nullif(btrim(coalesce(p_expected_company_id, '')), '') is null
     or nullif(btrim(coalesce(p_expected_entity_id, '')), '') is null
     or nullif(btrim(coalesce(p_expected_finance_user_id, '')), '') is null
     or nullif(btrim(coalesce(p_expected_email, '')), '') is null
     or nullif(btrim(coalesce(p_expected_role, '')), '') is null
     or nullif(btrim(coalesce(p_expected_logging_role_key, '')), '') is null
     or nullif(btrim(coalesce(p_expected_job_level, '')), '') is null
     or nullif(btrim(coalesce(p_expected_unit, '')), '') is null
     or nullif(btrim(coalesce(p_expected_title, '')), '') is null
     or p_expected_status <> '啟用'
     or p_expected_projection_state <> 'active' then
    raise exception using errcode = '22023', message = 'finance_session_revalidation_input_invalid';
  end if;

  -- Revalidation uses one fixed lock order: session -> company -> user.
  -- Login creation locks company -> user but operates on a new session id, so
  -- it cannot form a cycle with this existing-session lock.
  select session_row.*
  into v_session
  from public.auth_sessions session_row
  where session_row.id = p_session_id
  for update;

  if not found
     or v_session.user_id is distinct from p_user_id
     or v_session.token_hash is distinct from p_token_hash
     or v_session.revoked_at is not null
     or v_session.expires_at is null
     or v_session.expires_at !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$'
     or v_session.expires_at <= to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS') then
    raise exception using errcode = '28000', message = 'finance_session_authorization_binding_mismatch';
  end if;

  select company_row.*
  into v_company
  from public.companies company_row
  where company_row.id = p_expected_company_id
  for update;

  if not found then
    raise exception using errcode = '28000', message = 'finance_session_authorization_binding_mismatch';
  end if;

  select user_row.*
  into v_user
  from public.users user_row
  where user_row.id = p_user_id
  for update;

  if not found
     or lower(btrim(coalesce(v_user.account_source, ''))) <> 'finance'
     or lower(btrim(coalesce(v_user.email, ''))) <> lower(btrim(p_expected_email))
     or btrim(coalesce(v_user.logging_account_id, '')) <> btrim(p_expected_finance_user_id)
     or btrim(coalesce(v_user.finance_employee_id, '')) <> btrim(p_expected_finance_user_id)
     or btrim(coalesce(v_user.finance_tenant_id, '')) <> btrim(p_expected_tenant_id)
     or btrim(coalesce(v_user.company_id, '')) <> btrim(p_expected_company_id)
     or btrim(coalesce(v_user.role, '')) <> btrim(p_expected_role)
     or btrim(coalesce(v_user.logging_role_key, '')) <> btrim(p_expected_logging_role_key)
     or btrim(coalesce(v_user.job_level, '')) <> btrim(p_expected_job_level)
     or btrim(coalesce(v_user.unit, '')) <> btrim(p_expected_unit)
     or btrim(coalesce(v_user.title, '')) <> btrim(p_expected_title)
     or btrim(coalesce(v_user.status, '')) <> p_expected_status
     or btrim(coalesce(v_user.finance_source_status, '')) <> p_expected_projection_state
     or btrim(coalesce(v_company.finance_entity_id, '')) <> btrim(p_expected_entity_id)
     or btrim(coalesce(v_company.finance_tenant_id, '')) <> btrim(p_expected_tenant_id)
     or lower(btrim(coalesce(v_company.source_system, ''))) <> 'finance'
     or lower(btrim(coalesce(v_company.status, ''))) <> 'active'
     or v_user.role not in (
       '員工', '業務助理', '主管', '主任', '行政部主任', '總務',
       '執行長', '人資', '會計', '董事會', '股東', '外部檢核單位'
     ) then
    raise exception using errcode = '28000', message = 'finance_session_authorization_binding_mismatch';
  end if;

  update public.users
  set last_synced_from_logging_at = p_verified_at
  where id = v_user.id
  returning * into v_user;

  select coalesce(jsonb_agg(permission_code.code order by permission_code.code), '[]'::jsonb)
  into v_permissions
  from (
    select distinct permission_row.code
    from public.roles role_row
    join public.role_permissions role_permission_row
      on role_permission_row.role_id = role_row.id
    join public.permissions permission_row
      on permission_row.id = role_permission_row.permission_id
    where role_row.name = v_user.role
      and role_row.status = '啟用'
  ) permission_code;

  return jsonb_build_object(
    'session', jsonb_build_object(
      'id', v_session.id,
      'user_id', v_session.user_id,
      'provider', v_session.provider,
      'expires_at', v_session.expires_at,
      'created_at', v_session.created_at
    ),
    'user', to_jsonb(v_user) - 'password_hash',
    'permissions', v_permissions
  );
end
$$;

alter function public.edoc_create_finance_login_session_v2(
  text, text, text, text, text, text, text, text, text,
  text, text, text, text, text, text, text, text, text, text,
  text, text
) owner to postgres;

alter function public.edoc_revalidate_finance_session_v2(
  text, text, text, text, text, text, text, text,
  text, text, text, text, text, text, text, text
) owner to postgres;

revoke all on function public.edoc_create_finance_login_session_v2(
  text, text, text, text, text, text, text, text, text,
  text, text, text, text, text, text, text, text, text, text,
  text, text
) from public, anon, authenticated;

revoke all on function public.edoc_revalidate_finance_session_v2(
  text, text, text, text, text, text, text, text,
  text, text, text, text, text, text, text, text
) from public, anon, authenticated;

-- The unbound v1 entry point must not remain callable after v2 is installed.
revoke all on function public.edoc_create_finance_login_session_v1(
  text, text, text, text, text, text, text, text, text
) from service_role;

grant execute on function public.edoc_create_finance_login_session_v2(
  text, text, text, text, text, text, text, text, text,
  text, text, text, text, text, text, text, text, text, text,
  text, text
) to service_role;

grant execute on function public.edoc_revalidate_finance_session_v2(
  text, text, text, text, text, text, text, text,
  text, text, text, text, text, text, text, text
) to service_role;

comment on function public.edoc_create_finance_login_session_v2(
  text, text, text, text, text, text, text, text, text,
  text, text, text, text, text, text, text, text, text, text,
  text, text
) is 'Service-only atomic Finance authorization binding verification and eDoc session creation.';

comment on function public.edoc_revalidate_finance_session_v2(
  text, text, text, text, text, text, text, text,
  text, text, text, text, text, text, text, text
) is 'Service-only atomic Finance authorization binding verification for an existing eDoc session.';

notify pgrst, 'reload schema';
