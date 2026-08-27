-- Dedicated eDoc Storage project only. Keep this out of the main website/CMS
-- migration chain because that project has unrelated bucket policies.

update storage.buckets
set public = false,
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
    updated_at = now()
where id = 'edoc-private';

update storage.buckets
set public = false,
    file_size_limit = 3145728,
    allowed_mime_types = array['image/png', 'image/jpeg', 'image/webp']::text[],
    updated_at = now()
where id = 'edoc-seal-vault';

-- The browser receives only short-lived signed upload/download capabilities.
-- Remove legacy authenticated direct-object access while service_role keeps its
-- built-in Storage bypass for backend validation and archival operations.
drop policy if exists "private bucket document scoped read" on storage.objects;
drop policy if exists "private bucket authorized upload" on storage.objects;
drop policy if exists "private bucket authorized replace" on storage.objects;

-- Defensive cleanup for any older SVG-enabled bucket definition.
update storage.buckets
set allowed_mime_types = array_remove(allowed_mime_types, 'image/svg+xml'),
    updated_at = now()
where id in ('edoc-private', 'edoc-seal-vault');
