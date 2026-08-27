-- Dedicated eDoc Storage project cutover checks (read-only metadata only).
--
-- Run this file only against the dedicated Storage project.  The main eDoc
-- database also hosts CMS storage policies and must not satisfy this project's
-- empty browser-policy allowlist.

-- 1. Both required buckets must exist and be private. edoc-private must accept
-- archive ZIP output, and neither bucket may accept SVG.
with required_buckets(id) as (
  values ('edoc-private'), ('edoc-seal-vault')
)
select
  required.id,
  bucket.id is not null as bucket_exists,
  case when bucket.id is null then false else not bucket.public end as is_private,
  bucket.file_size_limit,
  case when bucket.id is null then false
       else 'application/zip' = any(coalesce(bucket.allowed_mime_types, array[]::text[]))
  end as allows_zip,
  case when bucket.id is null then true
       else 'image/svg+xml' = any(coalesce(bucket.allowed_mime_types, array[]::text[]))
  end as allows_svg
from required_buckets required
left join storage.buckets bucket on bucket.id = required.id
order by required.id;

-- Pass condition: edoc-private has bucket_exists/is_private/allows_zip=true and
-- allows_svg=false; edoc-seal-vault has bucket_exists/is_private=true and
-- allows_svg=false (allows_zip is not required for the vault).

-- 2. Browser roles must have no direct storage.objects policies in this
-- dedicated project. Uploads/downloads are short-lived backend capabilities.
select policyname, roles, cmd, qual, with_check
from pg_catalog.pg_policies
where schemaname = 'storage'
  and tablename = 'objects'
  and roles && array['public', 'anon', 'authenticated']::name[]
order by policyname;
-- Pass condition: zero rows.
