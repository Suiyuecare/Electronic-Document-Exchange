-- CI-only assertions for the isolated local Supabase Storage/TUS gate.
--
-- This file is intentionally read-only. It may run before and after the
-- five-account transport test: the first run validates the private bucket
-- posture, while the second also proves the synthetic editor objects were
-- removed. No production project or credential is referenced here.

do $local_storage_tus_gate$
declare
  private_bucket storage.buckets%rowtype;
  seal_bucket storage.buckets%rowtype;
  browser_policy_count bigint;
  synthetic_object_count bigint;
begin
  select * into private_bucket
  from storage.buckets
  where id = 'edoc-private';

  if not found then
    raise exception 'local_storage_tus_private_bucket_missing';
  end if;
  if private_bucket.public then
    raise exception 'local_storage_tus_private_bucket_public';
  end if;
  if coalesce(private_bucket.file_size_limit, 0) < 50 * 1024 * 1024 then
    raise exception 'local_storage_tus_private_bucket_size_too_small';
  end if;
  if not ('application/pdf' = any(coalesce(private_bucket.allowed_mime_types, array[]::text[]))) then
    raise exception 'local_storage_tus_pdf_mime_missing';
  end if;
  if not ('application/zip' = any(coalesce(private_bucket.allowed_mime_types, array[]::text[]))) then
    raise exception 'local_storage_tus_zip_mime_missing';
  end if;
  if 'image/svg+xml' = any(coalesce(private_bucket.allowed_mime_types, array[]::text[])) then
    raise exception 'local_storage_tus_svg_mime_forbidden';
  end if;

  select * into seal_bucket
  from storage.buckets
  where id = 'edoc-seal-vault';

  if not found then
    raise exception 'local_storage_tus_seal_bucket_missing';
  end if;
  if seal_bucket.public then
    raise exception 'local_storage_tus_seal_bucket_public';
  end if;
  if 'image/svg+xml' = any(coalesce(seal_bucket.allowed_mime_types, array[]::text[])) then
    raise exception 'local_storage_tus_seal_svg_mime_forbidden';
  end if;

  select count(*) into browser_policy_count
  from pg_catalog.pg_policies
  where schemaname = 'storage'
    and tablename = 'objects'
    and roles && array['public', 'anon', 'authenticated']::name[];

  if browser_policy_count <> 0 then
    raise exception 'local_storage_tus_browser_policy_exposed:%', browser_policy_count;
  end if;

  select count(*) into synthetic_object_count
  from storage.objects
  where bucket_id in ('edoc-private', 'edoc-seal-vault')
    and (
      name like 'editor/OD-%'
      or name like 'seal-vault/seals/isolated-%'
    );

  if synthetic_object_count <> 0 then
    raise exception 'local_storage_tus_synthetic_object_cleanup_failed:%', synthetic_object_count;
  end if;
end
$local_storage_tus_gate$;
