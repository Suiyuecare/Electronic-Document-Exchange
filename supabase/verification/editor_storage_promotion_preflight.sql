-- Read-only pre-migration inventory for
-- 20260827194500_promote_editor_tus_staging_to_immutable.sql.
-- Run against the main eDoc database during an upload maintenance window.
-- This file returns aggregate counts only; it never selects paths, names,
-- document content, hashes, identities or credentials.

do $postgres_version_check$
begin
  if pg_catalog.current_setting('server_version_num')::integer < 160000 then
    raise exception 'editor_storage_preflight_postgres_16_required';
  end if;
end;
$postgres_version_check$;

do $version_gate$
begin
  if pg_catalog.current_setting('server_version_num')::integer < 160000 then
    raise exception using
      errcode = '0A000',
      message = 'editor_storage_migration_requires_postgresql_16';
  end if;
end;
$version_gate$;

select
  count(*) filter (
    where asset_kind in ('source_pdf', 'import_pdf', 'image')
      and upload_status in ('pending', 'uploading', 'uploaded')
  ) as active_editor_upload_count,
  count(*) filter (
    where asset_kind in ('source_pdf', 'import_pdf', 'image')
      and upload_status = 'finalized'
  ) as finalized_editor_asset_count
from public.official_document_editor_assets;

select count(*) as finalized_assets_requiring_byte_promotion
from public.official_document_editor_assets asset
left join public.file_objects file_object on file_object.id = asset.file_object_id
where asset.asset_kind in ('source_pdf', 'import_pdf', 'image')
  and asset.upload_status = 'finalized'
  and (
    asset.sha256 !~ '^[A-Fa-f0-9]{64}$'
    or pg_catalog.lower(asset.expected_sha256)
         is distinct from pg_catalog.lower(asset.sha256)
    or asset.size_bytes <= 0
    or asset.created_at !~
         '^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}'
    or not pg_catalog.pg_input_is_valid(
         asset.created_at,
         'timestamp without time zone'
       )
    or file_object.id is null
    or file_object.document_id is distinct from asset.document_id
    or file_object.bucket is distinct from 'edoc-private'
    or file_object.storage_provider is distinct from 'supabase'
    or pg_catalog.left(
         file_object.storage_key,
         pg_catalog.length(
           'editor-final/' || asset.document_id || '/' || asset.id || '/' ||
           pg_catalog.upper(asset.sha256) || '-'
         )
       ) is distinct from
       'editor-final/' || asset.document_id || '/' || asset.id || '/' ||
       pg_catalog.upper(asset.sha256) || '-'
    or pg_catalog.lower(file_object.sha256) is distinct from pg_catalog.lower(asset.sha256)
    or file_object.size_bytes is distinct from asset.size_bytes
  );

select count(*) as nonfinalized_assets_without_durable_job_input
from public.official_document_editor_assets asset
where asset.asset_kind in ('source_pdf', 'import_pdf', 'image')
  and asset.upload_status <> 'finalized'
  and (
    asset.expected_sha256 !~ '^[A-Fa-f0-9]{64}$'
    or asset.size_bytes <= 0
    or asset.created_at !~
         '^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}'
    or not pg_catalog.pg_input_is_valid(
         asset.created_at,
         'timestamp without time zone'
       )
    or asset.storage_bucket is distinct from 'edoc-private'
    or pg_catalog.left(
         asset.storage_path,
         pg_catalog.length('editor/' || asset.document_id || '/' || asset.id || '-')
       ) is distinct from
       'editor/' || asset.document_id || '/' || asset.id || '-'
  );

do $preflight$
begin
  if exists (
    select 1
    from public.official_document_editor_assets asset
    where asset.asset_kind in ('source_pdf', 'import_pdf', 'image')
      and asset.upload_status in ('pending', 'uploading', 'uploaded')
  ) then
    raise exception using
      errcode = '55000',
      message = 'editor_upload_maintenance_window_not_empty';
  end if;

  if exists (
    select 1
    from public.official_document_editor_assets asset
    left join public.file_objects file_object on file_object.id = asset.file_object_id
    where asset.asset_kind in ('source_pdf', 'import_pdf', 'image')
      and asset.upload_status = 'finalized'
      and (
        asset.sha256 !~ '^[A-Fa-f0-9]{64}$'
        or pg_catalog.lower(asset.expected_sha256)
             is distinct from pg_catalog.lower(asset.sha256)
        or asset.size_bytes <= 0
        or asset.created_at !~
             '^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}'
        or not pg_catalog.pg_input_is_valid(
             asset.created_at,
             'timestamp without time zone'
           )
        or file_object.id is null
        or file_object.document_id is distinct from asset.document_id
        or file_object.bucket is distinct from 'edoc-private'
        or file_object.storage_provider is distinct from 'supabase'
        or pg_catalog.left(
             file_object.storage_key,
             pg_catalog.length(
               'editor-final/' || asset.document_id || '/' || asset.id || '/' ||
               pg_catalog.upper(asset.sha256) || '-'
             )
           ) is distinct from
           'editor-final/' || asset.document_id || '/' || asset.id || '/' ||
           pg_catalog.upper(asset.sha256) || '-'
        or pg_catalog.lower(file_object.sha256) is distinct from pg_catalog.lower(asset.sha256)
        or file_object.size_bytes is distinct from asset.size_bytes
      )
  ) then
    raise exception using
      errcode = '55000',
      message = 'existing_editor_assets_require_audited_byte_promotion';
  end if;

  if exists (
    select 1
    from public.official_document_editor_assets asset
    where asset.asset_kind in ('source_pdf', 'import_pdf', 'image')
      and asset.upload_status <> 'finalized'
      and (
        asset.expected_sha256 !~ '^[A-Fa-f0-9]{64}$'
        or asset.size_bytes <= 0
        or asset.created_at !~
             '^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}'
        or not pg_catalog.pg_input_is_valid(
             asset.created_at,
             'timestamp without time zone'
           )
        or asset.storage_bucket is distinct from 'edoc-private'
        or pg_catalog.left(
             asset.storage_path,
             pg_catalog.length(
               'editor/' || asset.document_id || '/' || asset.id || '-'
             )
           ) is distinct from
           'editor/' || asset.document_id || '/' || asset.id || '-'
      )
  ) then
    raise exception using
      errcode = '55000',
      message = 'existing_editor_uploads_require_audited_cleanup';
  end if;
end;
$preflight$;

select 'editor_storage_promotion_preflight_ok' as result;
