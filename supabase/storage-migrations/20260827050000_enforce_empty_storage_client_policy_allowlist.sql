-- Dedicated Storage project only.
--
-- This project intentionally has an empty client-policy allowlist for
-- storage.objects: browser access to eDoc objects must use short-lived signed
-- upload/download capabilities only.  Drop every policy that grants PUBLIC,
-- anon or authenticated access, regardless of its historical name.
-- service_role keeps Supabase Storage's built-in backend bypass.
--
-- Do not apply this file to the independent main eDoc, legacy website/CMS or
-- Finance Supabase projects; their schemas and policies have different owners.
do $policy_cleanup$
declare
  candidate record;
begin
  for candidate in
    select policyname
    from pg_catalog.pg_policies
    where schemaname = 'storage'
      and tablename = 'objects'
      and roles && array['public', 'anon', 'authenticated']::name[]
  loop
    execute format('drop policy if exists %I on storage.objects', candidate.policyname);
  end loop;
end
$policy_cleanup$;
