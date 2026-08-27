-- Dedicated eDoc Storage project cutover checks (read-only metadata only).
--
-- Run this file only against the dedicated Storage project.  The main eDoc
-- database also hosts CMS storage policies and must not satisfy this project's
-- empty browser-policy allowlist.

-- 1. Fail closed unless both bucket definitions exactly match the reviewed
-- limits and MIME allowlists.  A permissive extra MIME type is drift, not a
-- warning, because browsers must never be able to turn this project into a
-- general-purpose file host.
do $dedicated_storage_cutover_gate$
declare
  private_bucket storage.buckets%rowtype;
  seal_bucket storage.buckets%rowtype;
  private_mimes constant text[] := array[
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
  ]::text[];
  seal_mimes constant text[] := array[
    'image/png', 'image/jpeg', 'image/webp'
  ]::text[];
  browser_policy_count bigint;
begin
  select * into private_bucket
  from storage.buckets
  where id = 'edoc-private';

  if not found
     or private_bucket.name is distinct from 'edoc-private'
     or private_bucket.public is distinct from false
     or private_bucket.avif_autodetection is distinct from false
     or private_bucket.file_size_limit is distinct from 104857600
     or not (
       coalesce(private_bucket.allowed_mime_types, array[]::text[]) @> private_mimes
       and private_mimes @> coalesce(private_bucket.allowed_mime_types, array[]::text[])
       and pg_catalog.cardinality(private_bucket.allowed_mime_types) =
           pg_catalog.cardinality(private_mimes)
     ) then
    raise exception 'dedicated_storage_private_bucket_definition_invalid';
  end if;

  select * into seal_bucket
  from storage.buckets
  where id = 'edoc-seal-vault';

  if not found
     or seal_bucket.name is distinct from 'edoc-seal-vault'
     or seal_bucket.public is distinct from false
     or seal_bucket.avif_autodetection is distinct from false
     or seal_bucket.file_size_limit is distinct from 3145728
     or not (
       coalesce(seal_bucket.allowed_mime_types, array[]::text[]) @> seal_mimes
       and seal_mimes @> coalesce(seal_bucket.allowed_mime_types, array[]::text[])
       and pg_catalog.cardinality(seal_bucket.allowed_mime_types) =
           pg_catalog.cardinality(seal_mimes)
     ) then
    raise exception 'dedicated_storage_seal_bucket_definition_invalid';
  end if;

  select pg_catalog.count(*) into browser_policy_count
  from pg_catalog.pg_policies
  where schemaname = 'storage'
    and tablename = 'objects'
    and roles && array['public', 'anon', 'authenticated']::name[];

  if browser_policy_count <> 0 then
    raise exception 'dedicated_storage_browser_policy_exposed:%',
      browser_policy_count;
  end if;
end
$dedicated_storage_cutover_gate$;

-- Emit bounded metadata evidence after the hard gate succeeds.
with required_buckets(id) as (
  values ('edoc-private'), ('edoc-seal-vault')
)
select
  required.id,
  bucket.id is not null as bucket_exists,
  case when bucket.id is null then false else not bucket.public end as is_private,
  bucket.file_size_limit,
  bucket.file_size_limit = case required.id
    when 'edoc-private' then 104857600
    else 3145728
  end as size_limit_exact,
  case when bucket.id is null then false
       else 'application/zip' = any(coalesce(bucket.allowed_mime_types, array[]::text[]))
  end as allows_zip,
  case when bucket.id is null then true
       else 'image/svg+xml' = any(coalesce(bucket.allowed_mime_types, array[]::text[]))
  end as allows_svg
from required_buckets required
left join storage.buckets bucket on bucket.id = required.id
order by required.id;

-- The query is evidence only; the DO block above already aborts on any drift.

-- 2. Browser roles must have no direct storage.objects policies in this
-- dedicated project. Uploads/downloads are short-lived backend capabilities.
select policyname, roles, cmd, qual, with_check
from pg_catalog.pg_policies
where schemaname = 'storage'
  and tablename = 'objects'
  and roles && array['public', 'anon', 'authenticated']::name[]
order by policyname;
-- The DO block above already aborts unless this query returns zero rows.
