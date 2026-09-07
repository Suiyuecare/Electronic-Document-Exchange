-- Shared-project forward correction after the immutable public-targeted chain
-- temporarily restored its historical 5 MB/SVG Seal Vault definition.
-- Scope is limited to the two eDoc buckets; HR buckets and objects are untouched.

begin;

select pg_catalog.pg_advisory_xact_lock(1788103601, 20260831);

do $preflight$
begin
  if pg_catalog.to_regnamespace('edoc') is null
     or not exists (select 1 from pg_catalog.pg_roles where rolname = 'edoc_backend')
     or (select count(*) from storage.buckets
         where id in ('edoc-private', 'edoc-seal-vault')) <> 2 then
    raise exception using
      errcode = '55000',
      message = 'shared_edoc_bucket_hardening_preflight_failed';
  end if;
end
$preflight$;

update storage.buckets
set public = false,
    avif_autodetection = false,
    file_size_limit = 104857600,
    allowed_mime_types = array[
      'application/pdf',
      'application/xml',
      'text/xml',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'application/pkcs7-mime',
      'application/octet-stream',
      'application/zip',
      'image/png',
      'image/jpeg',
      'image/webp'
    ]::text[],
    updated_at = pg_catalog.now()
where id = 'edoc-private';

update storage.buckets
set public = false,
    avif_autodetection = false,
    file_size_limit = 3145728,
    allowed_mime_types = array['image/png', 'image/jpeg', 'image/webp']::text[],
    updated_at = pg_catalog.now()
where id = 'edoc-seal-vault';

-- Browser access uses short-lived signed upload/download capabilities issued
-- by the eDoc backend. Remove historical direct authenticated policies.
drop policy if exists "private bucket document scoped read" on storage.objects;
drop policy if exists "private bucket authorized upload" on storage.objects;
drop policy if exists "private bucket authorized replace" on storage.objects;

do $assertions$
begin
  if (select count(*) from storage.buckets
      where id = 'edoc-private'
        and public is false
        and file_size_limit = 104857600
        and not ('image/svg+xml' = any(allowed_mime_types))) <> 1
     or (select count(*) from storage.buckets
         where id = 'edoc-seal-vault'
           and public is false
           and file_size_limit = 3145728
           and allowed_mime_types = array[
             'image/png', 'image/jpeg', 'image/webp'
           ]::text[]) <> 1
     or exists (
       select 1 from pg_catalog.pg_policies
       where schemaname = 'storage'
         and tablename = 'objects'
         and policyname in (
           'private bucket document scoped read',
           'private bucket authorized upload',
           'private bucket authorized replace'
         )
     ) then
    raise exception using
      errcode = '55000',
      message = 'shared_edoc_bucket_hardening_assertion_failed';
  end if;
end
$assertions$;

commit;
