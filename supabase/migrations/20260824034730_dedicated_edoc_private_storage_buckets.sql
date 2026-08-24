-- Dedicated eDoc Storage buckets.  Both buckets remain private and have no
-- anon/authenticated object policies; browser uploads use short-lived signed
-- upload tokens issued by the eDoc backend.

insert into storage.buckets (
    id,
    name,
    public,
    avif_autodetection,
    file_size_limit,
    allowed_mime_types,
    updated_at
)
values
(
    'edoc-private',
    'edoc-private',
    false,
    false,
    104857600,
    array[
        'application/pdf',
        'application/xml',
        'text/xml',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/pkcs7-mime',
        'application/octet-stream',
        'image/png',
        'image/jpeg',
        'image/webp'
    ]::text[],
    now()
),
(
    'edoc-seal-vault',
    'edoc-seal-vault',
    false,
    false,
    3145728,
    array[
        'image/png',
        'image/jpeg',
        'image/webp'
    ]::text[],
    now()
)
on conflict (id) do update
set
    name = excluded.name,
    public = false,
    avif_autodetection = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types,
    updated_at = now();
