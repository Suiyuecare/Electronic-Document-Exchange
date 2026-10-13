-- Only structurally decoded PNG/JPEG editor assets may use not_scanned.
-- Attachment, Seal Vault, approval, RLS and immutable promotion rules stay intact.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

DO $migration$
DECLARE
  definition text;
  old_guard text := $old$v_asset.asset_kind not in ('source_pdf', 'import_pdf')$old$;
  new_guard text := $new$v_asset.asset_kind not in ('source_pdf', 'import_pdf', 'image')
         or (v_asset.asset_kind = 'image' and (
           coalesce(v_asset.mime_type, '') not in ('image/png', 'image/jpeg')
           or v_file.mime_type is distinct from v_asset.mime_type
           or v_file.purpose is distinct from 'official-editor'
           or v_file.version_label is distinct from 'editor-asset-image'
           or coalesce(v_file.scan_engine, '') <> ''
           or v_file.last_scan_at is not null
         ))$new$;
BEGIN
  SELECT pg_catalog.pg_get_functiondef('public.edoc_finalize_editor_asset_v2(jsonb)'::regprocedure) INTO definition;
  IF pg_catalog.strpos(definition, new_guard) = 0 THEN
    IF pg_catalog.strpos(definition, old_guard) = 0 THEN
      RAISE EXCEPTION 'editor_image_preflight_definition_drift: finalize';
    END IF;
    EXECUTE pg_catalog.replace(definition, old_guard, new_guard);
  END IF;
END;
$migration$;

DO $migration$
DECLARE
  definition text;
  old_guard text := $old$AND v_row->>'asset_kind' IN ('source_pdf', 'import_pdf')$old$;
  new_guard text := $new$AND v_row->>'asset_kind' IN ('source_pdf', 'import_pdf', 'image')
          AND (v_row->>'asset_kind' <> 'image' OR (
            v_row->>'mime_type' IN ('image/png', 'image/jpeg')
            AND EXISTS (
              SELECT 1 FROM public.file_objects image_file
              WHERE image_file.id = v_row->>'file_object_id'
                AND image_file.document_id = v_id
                AND image_file.mime_type = v_row->>'mime_type'
                AND image_file.scan_status = 'not_scanned'
                AND image_file.purpose = 'official-editor'
                AND image_file.version_label = 'editor-asset-image'
                AND coalesce(image_file.scan_engine, '') = ''
                AND image_file.last_scan_at IS NULL
                AND pg_catalog.lower(image_file.sha256) = pg_catalog.lower(v_row->>'sha256')
                AND image_file.size_bytes = (v_row->>'size_bytes')::bigint
            )
          ))$new$;
BEGIN
  SELECT pg_catalog.pg_get_functiondef('public.edoc_copy_editor_conflict(jsonb)'::regprocedure) INTO definition;
  IF pg_catalog.strpos(definition, new_guard) = 0 THEN
    IF pg_catalog.strpos(definition, old_guard) = 0 THEN
      RAISE EXCEPTION 'editor_image_preflight_definition_drift: conflict copy';
    END IF;
    EXECUTE pg_catalog.replace(definition, old_guard, new_guard);
  END IF;
END;
$migration$;

COMMENT ON CONSTRAINT official_editor_asset_scan_status_check ON public.official_document_editor_assets IS
  'not_scanned is limited to finalized structural-preflight editor PDFs and decoded PNG/JPEG images; never denotes an antivirus result.';

-- Repair conflict-copy's staging lifecycle to obey the existing real storage
-- constraints. Never relax a trigger, a hash binding, a lease or a path check.
DO $migration$
DECLARE
  definition text;
  old_staging text := $old$'editor-copy-staging/' || v_id || '/' || (v_row->>'id')$old$;
  old_insert text := $old$INSERT INTO public.official_document_editor_assets SELECT * FROM jsonb_populate_record$old$;
  new_insert text := $new$v_staging_path := 'editor/' || v_id || '/' || (v_row->>'id') ||
      CASE WHEN (v_row->>'metadata_json')::jsonb->'storage_key_version' = '2'::jsonb
        THEN CASE v_row->>'mime_type' WHEN 'application/pdf' THEN '.pdf' WHEN 'image/png' THEN '.png' WHEN 'image/jpeg' THEN '.jpg' ELSE NULL END
        ELSE '-' || pg_catalog.regexp_replace(v_row->>'file_name', '^.*/', '') END;
    INSERT INTO public.official_document_editor_assets SELECT * FROM jsonb_populate_record$new$;
BEGIN
  SELECT pg_catalog.pg_get_functiondef('public.edoc_copy_editor_conflict(jsonb)'::regprocedure) INTO definition;
  IF pg_catalog.strpos(definition, 'v_staging_path text;') = 0 THEN
    IF pg_catalog.strpos(definition, old_staging) = 0
       OR pg_catalog.strpos(definition, old_insert) = 0
       OR pg_catalog.strpos(definition, $old$lease_token='copy-' || v_id$old$) = 0 THEN
      RAISE EXCEPTION 'editor_image_preflight_definition_drift: copy storage';
    END IF;
    definition := pg_catalog.replace(definition, 'v_row jsonb;', 'v_row jsonb; v_staging_path text;');
    definition := pg_catalog.replace(definition, old_staging, 'v_staging_path');
    definition := pg_catalog.replace(definition, old_insert, new_insert);
    definition := pg_catalog.replace(definition, $old$to_char(now(), 'YYYY-MM-DD HH24:MI:SS'), 'pending'$old$,
      $new$to_char(now(), 'YYYY-MM-DD"T"HH24:MI:SS'), 'pending'$new$);
    definition := pg_catalog.replace(definition, $old$lease_token='copy-' || v_id$old$,
      $new$lease_token=pg_catalog.upper(pg_catalog.md5(v_id || (v_row->>'id')))$new$);
    definition := pg_catalog.replace(definition, $old$to_char(now() + interval '10 minutes', 'YYYY-MM-DD HH24:MI:SS')$old$,
      $new$to_char(now() + interval '10 minutes', 'YYYY-MM-DD"T"HH24:MI:SS')$new$);
    EXECUTE definition;
  END IF;
END;
$migration$;
COMMIT;
