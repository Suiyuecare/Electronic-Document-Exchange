-- Dedicated Storage project only.
--
-- This project intentionally has an empty client-policy allowlist for
-- storage.objects: browser access to eDoc objects must use short-lived signed
-- upload/download capabilities only.  Drop every policy that grants PUBLIC,
-- anon or authenticated access, regardless of its historical name.
-- service_role keeps Supabase Storage's built-in backend bypass.
--
-- Do not apply this file to the main website/CMS Supabase project: that project
-- has unrelated, explicitly reviewed CMS bucket policies.
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
