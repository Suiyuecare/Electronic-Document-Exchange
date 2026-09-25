-- The eSeal editor keeps its structural PDF preflight but no longer queues a
-- malware scan for source/import PDFs. Preserve the distinction in storage and
-- allow the state only through the exact finalized editor-asset lineage.
BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

ALTER TABLE public.official_document_editor_assets
  DROP CONSTRAINT IF EXISTS official_editor_asset_scan_status_check;
ALTER TABLE public.official_document_editor_assets
  ADD CONSTRAINT official_editor_asset_scan_status_check
  CHECK (scan_status = ANY (ARRAY['pending'::text, 'passed'::text, 'failed'::text, 'not_scanned'::text]));

DO $migration$
DECLARE
  v_definition text;
  v_old text := $old$
     or (
       v_source.file_type = 'original_pdf'
       and pg_catalog.lower(pg_catalog.btrim(coalesce(v_file_object.scan_status, '')))
         not in ('已通過', 'clean', 'passed')
     ) then
$old$;
  v_new text := $new$
     or (
       v_source.file_type = 'original_pdf'
       and not (
         pg_catalog.lower(pg_catalog.btrim(coalesce(v_file_object.scan_status, '')))
           in ('已通過', 'clean', 'passed')
         or (
           pg_catalog.lower(pg_catalog.btrim(coalesce(v_file_object.scan_status, ''))) = 'not_scanned'
           and exists (
             select 1
               from public.official_document_editor_assets as asset
              where asset.document_id = p_document_id
                and asset.official_file_id = v_source.id
                and asset.file_object_id = v_file_object.id
                and asset.asset_kind = 'source_pdf'
                and asset.upload_status = 'finalized'
                and asset.scan_status = 'not_scanned'
                and asset.preflight_status = 'passed'
                and pg_catalog.lower(asset.sha256) = pg_catalog.lower(v_source.file_hash)
                and asset.size_bytes = v_source.file_size
                and asset.storage_bucket = v_file_object.bucket
                and v_file_object.document_id = p_document_id
                and v_file_object.purpose = 'official-editor'
                and v_file_object.version_label = 'editor-asset-source_pdf'
                and pg_catalog.lower(v_file_object.sha256) = pg_catalog.lower(v_source.file_hash)
                and v_file_object.size_bytes = v_source.file_size
           )
         )
       )
     ) then
$new$;
BEGIN
  SELECT pg_catalog.pg_get_functiondef(
    'edoc_private.validate_official_document_decision_evidence(text,text,text,text,text,jsonb)'::regprocedure
  ) INTO v_definition;
  IF pg_catalog.strpos(v_definition, v_new) > 0 THEN
    NULL;
  ELSIF pg_catalog.strpos(v_definition, v_old) > 0 THEN
    EXECUTE pg_catalog.replace(v_definition, v_old, v_new);
  ELSE
    RAISE EXCEPTION 'editor_pdf_upload_migration_definition_drift: decision evidence';
  END IF;
END;
$migration$;

DO $migration$
DECLARE
  v_definition text;
  v_old_guard text := $old$or v_asset_patch->>'scan_status' is distinct from 'passed' then$old$;
  v_new_guard text := $new$
     or (
       v_asset_patch->>'scan_status' is distinct from 'passed'
       and v_asset_patch->>'scan_status' is distinct from 'not_scanned'
     )
     or (
       v_asset_patch->>'scan_status' = 'not_scanned'
       and (
         v_asset.asset_kind not in ('source_pdf', 'import_pdf')
         or v_asset_patch->>'preflight_status' is distinct from 'passed'
         or pg_catalog.lower(pg_catalog.btrim(coalesce(v_file.scan_status, ''))) <> 'not_scanned'
       )
     )
     or (
       v_asset_patch->>'scan_status' = 'passed'
       and pg_catalog.lower(pg_catalog.btrim(coalesce(v_file.scan_status, '')))
         not in ('已通過', 'clean', 'passed')
     ) then
$new$;
  v_old_idempotency text := $old$and v_asset.editor_revision_id = v_revision.id and v_asset.file_object_id = v_file.id$old$;
  v_new_idempotency text := $new$and v_asset.editor_revision_id = v_revision.id and v_asset.file_object_id = v_file.id
       and v_asset.scan_status = v_asset_patch->>'scan_status'$new$;
  v_old_update text := $old$upload_status = 'finalized', scan_status = 'passed',$old$;
  v_new_update text := $new$upload_status = 'finalized', scan_status = v_asset_patch->>'scan_status',$new$;
BEGIN
  SELECT pg_catalog.pg_get_functiondef('public.edoc_finalize_editor_asset_v2(jsonb)'::regprocedure)
    INTO v_definition;
  IF pg_catalog.strpos(v_definition, v_new_guard) = 0 THEN
    IF pg_catalog.strpos(v_definition, v_old_guard) = 0 THEN
      RAISE EXCEPTION 'editor_pdf_upload_migration_definition_drift: finalize guard';
    END IF;
    v_definition := pg_catalog.replace(v_definition, v_old_guard, v_new_guard);
  END IF;
  IF pg_catalog.strpos(v_definition, v_new_idempotency) = 0 THEN
    IF pg_catalog.strpos(v_definition, v_old_idempotency) = 0 THEN
      RAISE EXCEPTION 'editor_pdf_upload_migration_definition_drift: finalize idempotency';
    END IF;
    v_definition := pg_catalog.replace(v_definition, v_old_idempotency, v_new_idempotency);
  END IF;
  IF pg_catalog.strpos(v_definition, v_new_update) = 0 THEN
    IF pg_catalog.strpos(v_definition, v_old_update) = 0 THEN
      RAISE EXCEPTION 'editor_pdf_upload_migration_definition_drift: finalize update';
    END IF;
    v_definition := pg_catalog.replace(v_definition, v_old_update, v_new_update);
  END IF;
  EXECUTE v_definition;
END;
$migration$;

DO $migration$
DECLARE
  v_definition text;
  v_old text := $old$OR v_row->>'upload_status' <> 'finalized' OR v_row->>'scan_status' <> 'passed' OR v_row->>'preflight_status' <> 'passed' THEN$old$;
  v_new text := $new$
      OR v_row->>'upload_status' <> 'finalized'
      OR v_row->>'preflight_status' <> 'passed'
      OR (
        v_row->>'scan_status' IS DISTINCT FROM 'passed'
        AND NOT (
          v_row->>'scan_status' = 'not_scanned'
          AND v_row->>'asset_kind' IN ('source_pdf', 'import_pdf')
        )
      ) THEN
$new$;
BEGIN
  SELECT pg_catalog.pg_get_functiondef('public.edoc_copy_editor_conflict(jsonb)'::regprocedure)
    INTO v_definition;
  IF pg_catalog.strpos(v_definition, v_new) > 0 THEN
    NULL;
  ELSIF pg_catalog.strpos(v_definition, v_old) > 0 THEN
    EXECUTE pg_catalog.replace(v_definition, v_old, v_new);
  ELSE
    RAISE EXCEPTION 'editor_pdf_upload_migration_definition_drift: conflict copy';
  END IF;
END;
$migration$;

COMMENT ON CONSTRAINT official_editor_asset_scan_status_check ON public.official_document_editor_assets IS
  'not_scanned is permitted only for structurally preflighted editor PDFs; images still require scanning.';

COMMIT;
