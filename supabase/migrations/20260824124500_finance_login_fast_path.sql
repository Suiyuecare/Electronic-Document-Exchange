-- Collapse the latency-sensitive Finance login writes and session reads into
-- one short transaction / one Data API round trip.  Both functions remain
-- service-role only; browsers never receive execute permission.

do $$
begin
  if to_regclass('public.users') is null
     or to_regclass('public.auth_sessions') is null
     or to_regclass('public.login_events') is null
     or to_regclass('public.roles') is null
     or to_regclass('public.role_permissions') is null
     or to_regclass('public.permissions') is null then
    raise exception 'finance login fast path prerequisites are missing';
  end if;
end
$$;

create or replace function public.edoc_create_finance_login_session_v1(
  p_user_id text,
  p_session_id text,
  p_token_hash text,
  p_provider text,
  p_ip text,
  p_device text,
  p_expires_at text,
  p_created_at text,
  p_login_event_id text
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_user public.users%rowtype;
  v_session public.auth_sessions%rowtype;
  v_permissions jsonb := '[]'::jsonb;
begin
  perform pg_catalog.set_config('statement_timeout', '3000', true);

  if p_user_id is null or btrim(p_user_id) = ''
     or p_session_id is null or btrim(p_session_id) = ''
     or p_login_event_id is null or btrim(p_login_event_id) = ''
     or p_token_hash is null or p_token_hash !~ '^[0-9a-f]{64}$'
     or p_expires_at is null or p_expires_at !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$'
     or p_created_at is null or p_created_at !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$' then
    raise exception using errcode = '22023', message = 'finance_login_session_input_invalid';
  end if;

  select user_row.*
  into v_user
  from public.users user_row
  where user_row.id = p_user_id
  for update;

  if not found
     or lower(btrim(coalesce(v_user.account_source, ''))) <> 'finance'
     or v_user.status <> '啟用'
     or v_user.role not in (
       '員工', '業務助理', '主管', '主任', '行政部主任', '總務',
       '執行長', '人資', '會計', '董事會', '股東', '外部檢核單位'
     )
     or nullif(btrim(coalesce(v_user.company_id, '')), '') is null
     or not exists (
       select 1
       from public.companies company_row
       where company_row.id = v_user.company_id
         and company_row.status = 'active'
     ) then
    raise exception using errcode = '28000', message = 'finance_login_identity_ineligible';
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
    '沿用已佈建的 Finance Google 帳號進入公文收發電子用印系統',
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

create or replace function public.edoc_resolve_finance_session_v1(
  p_token_hash text
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_user public.users%rowtype;
  v_session public.auth_sessions%rowtype;
  v_permissions jsonb := '[]'::jsonb;
begin
  perform pg_catalog.set_config('statement_timeout', '3000', true);

  if p_token_hash is null or p_token_hash !~ '^[0-9a-f]{64}$' then
    return null;
  end if;

  select session_row.*
  into v_session
  from public.auth_sessions session_row
  where session_row.token_hash = p_token_hash
    and session_row.revoked_at is null
    and session_row.expires_at > to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS')
  limit 1;

  if not found then
    return null;
  end if;

  select user_row.*
  into v_user
  from public.users user_row
  where user_row.id = v_session.user_id
  limit 1;

  if not found then
    return null;
  end if;

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

alter function public.edoc_create_finance_login_session_v1(
  text, text, text, text, text, text, text, text, text
) owner to postgres;
alter function public.edoc_resolve_finance_session_v1(text) owner to postgres;

revoke all on function public.edoc_create_finance_login_session_v1(
  text, text, text, text, text, text, text, text, text
) from public, anon, authenticated;
revoke all on function public.edoc_resolve_finance_session_v1(text)
  from public, anon, authenticated;

grant execute on function public.edoc_create_finance_login_session_v1(
  text, text, text, text, text, text, text, text, text
) to service_role;
grant execute on function public.edoc_resolve_finance_session_v1(text)
  to service_role;

comment on function public.edoc_create_finance_login_session_v1(
  text, text, text, text, text, text, text, text, text
) is 'Service-only atomic Finance eDoc login session creation; never exposed to browsers.';
comment on function public.edoc_resolve_finance_session_v1(text)
is 'Service-only one-round-trip eDoc session, user and RBAC resolver.';
