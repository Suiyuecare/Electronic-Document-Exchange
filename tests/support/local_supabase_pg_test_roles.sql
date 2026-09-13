-- CI fixture setup only: executed against the disposable 127.0.0.1 cluster.
-- Supabase's postgres role can create roles but is not a true superuser.
-- PG16+ creation grants ADMIN, not SET, so explicitly enable the test session
-- to switch to the backend role. Production migrations/privileges are unchanged.
do $ci_fixture$
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'edoc_backend') then
    create role edoc_backend nologin;
  end if;
end
$ci_fixture$;

grant edoc_backend to current_user with set true;
