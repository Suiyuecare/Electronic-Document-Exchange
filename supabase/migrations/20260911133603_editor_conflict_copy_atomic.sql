-- Only the authenticated application backend may request this transaction.
-- Source rows stay immutable and new files are document-bound private copies.
CREATE OR REPLACE FUNCTION public.edoc_copy_editor_conflict(p_bundle jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_source public.official_documents%ROWTYPE;
  v_existing public.official_documents%ROWTYPE;
  v_document public.official_documents%ROWTYPE;
  v_meta jsonb;
  v_row jsonb;
  v_id text := p_bundle->'document'->>'id';
  v_actor text := p_bundle->>'actor_id';
BEGIN
  IF current_user <> 'service_role' THEN
    RAISE EXCEPTION 'editor_conflict_copy_backend_only' USING ERRCODE = '42501';
  END IF;
  SELECT * INTO v_source FROM public.official_documents
    WHERE id = p_bundle->>'source_document_id' FOR UPDATE;
  IF NOT FOUND OR v_source.applicant_id IS DISTINCT FROM v_actor THEN
    RAISE EXCEPTION 'official_editor_write_forbidden' USING ERRCODE = '42501';
  END IF;
  IF v_source.current_status NOT IN ('draft', 'rejected') THEN
    RAISE EXCEPTION 'editor_locked_after_submit' USING ERRCODE = 'PT409';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.users WHERE id = v_actor AND company_id = v_source.company_id AND status = '啟用') THEN
    RAISE EXCEPTION 'official_editor_company_forbidden' USING ERRCODE = '42501';
  END IF;
  SELECT * INTO v_existing FROM public.official_documents WHERE id = v_id;
  IF FOUND THEN
    v_meta := v_existing.metadata_json::jsonb->'conflict_recovery';
    IF v_existing.applicant_id IS DISTINCT FROM v_actor
      OR v_meta->>'source_document_id' IS DISTINCT FROM v_source.id
      OR v_meta->>'request_hash' IS DISTINCT FROM p_bundle->>'request_hash' THEN
      RAISE EXCEPTION 'editor_conflict_copy_request_conflict' USING ERRCODE = 'PT409';
    END IF;
    RETURN jsonb_build_object('document_id', v_id, 'idempotent', true);
  END IF;
  v_document := jsonb_populate_record(NULL::public.official_documents, p_bundle->'document');
  IF v_document.applicant_id IS DISTINCT FROM v_actor OR v_document.company_id IS DISTINCT FROM v_source.company_id
    OR v_document.current_status <> 'draft' OR v_document.source_type <> 'uploaded_pdf'
    OR coalesce((v_source.metadata_json::jsonb->>'pdf_editor_v2')::boolean, false) IS NOT TRUE THEN
    RAISE EXCEPTION 'editor_conflict_copy_invalid_document' USING ERRCODE = '42501';
  END IF;
  INSERT INTO public.official_documents SELECT v_document.*;
  IF p_bundle->'revision'->>'document_id' IS DISTINCT FROM v_id OR (p_bundle->'revision'->>'revision_no')::int <> 1 THEN
    RAISE EXCEPTION 'editor_conflict_copy_invalid_revision';
  END IF;
  INSERT INTO public.official_document_editor_revisions
    SELECT * FROM jsonb_populate_record(NULL::public.official_document_editor_revisions, p_bundle->'revision');
  FOR v_row IN SELECT value FROM jsonb_array_elements(p_bundle->'file_objects') LOOP
    IF v_row->>'document_id' IS DISTINCT FROM v_id THEN RAISE EXCEPTION 'editor_conflict_copy_invalid_asset'; END IF;
    INSERT INTO public.file_objects SELECT * FROM jsonb_populate_record(NULL::public.file_objects, v_row);
  END LOOP;
  FOR v_row IN SELECT value FROM jsonb_array_elements(p_bundle->'files') LOOP
    IF v_row->>'document_id' IS DISTINCT FROM v_id OR v_row->>'file_type' NOT IN ('original_pdf', 'attachment') THEN RAISE EXCEPTION 'editor_conflict_copy_invalid_asset'; END IF;
    INSERT INTO public.official_document_files SELECT * FROM jsonb_populate_record(NULL::public.official_document_files, v_row);
  END LOOP;
  FOR v_row IN SELECT value FROM jsonb_array_elements(p_bundle->'assets') LOOP
    IF v_row->>'document_id' IS DISTINCT FROM v_id OR v_row->>'asset_kind' NOT IN ('source_pdf', 'import_pdf', 'image')
      OR v_row->>'upload_status' <> 'finalized' OR v_row->>'scan_status' <> 'passed' OR v_row->>'preflight_status' <> 'passed' THEN
      RAISE EXCEPTION 'editor_conflict_copy_invalid_asset';
    END IF;
    -- Follow the same pending -> promoting -> finalized invariant as direct
    -- uploads. No trigger is disabled and no finalized source is overwritten.
    INSERT INTO public.official_document_editor_assets SELECT * FROM jsonb_populate_record(NULL::public.official_document_editor_assets,
      v_row || jsonb_build_object('upload_status', 'uploaded', 'storage_path', 'editor-copy-staging/' || v_id || '/' || (v_row->>'id')));
    INSERT INTO public.official_document_editor_storage_jobs
      (id, asset_id, document_id, staging_bucket, staging_path, final_bucket, final_path, expected_sha256, expected_size_bytes,
       token_expires_at, status, lease_token, lease_expires_at, final_file_object_id, attempt_count, last_error_code, created_at, updated_at)
    VALUES ('ODJOB-' || (v_row->>'id'), v_row->>'id', v_id, v_row->>'storage_bucket', 'editor-copy-staging/' || v_id || '/' || (v_row->>'id'),
      v_row->>'storage_bucket', v_row->>'storage_path', v_row->>'sha256', (v_row->>'size_bytes')::bigint,
      to_char(now(), 'YYYY-MM-DD HH24:MI:SS'), 'pending', '', '',
      NULL, 0, '', to_char(now(), 'YYYY-MM-DD HH24:MI:SS'), to_char(now(), 'YYYY-MM-DD HH24:MI:SS'));
    UPDATE public.official_document_editor_storage_jobs SET status='promoting', lease_token='copy-' || v_id,
      lease_expires_at=to_char(now() + interval '10 minutes', 'YYYY-MM-DD HH24:MI:SS'), attempt_count=1
      WHERE asset_id=v_row->>'id';
    UPDATE public.official_document_editor_assets SET upload_status = 'finalized' WHERE id = v_row->>'id';
  END LOOP;
  INSERT INTO public.official_document_approval_logs(id, document_id, actor_id, actor_name, action, comment, decision_evidence_json, created_at)
    VALUES ('ODLOG-' || v_id, v_id, v_actor, v_actor, 'editor_conflict_copy',
      'source_document_id=' || v_source.id || ';manifest=' || (p_bundle->'revision'->>'manifest_sha256'), '{}', now());
  RETURN jsonb_build_object('document_id', v_id, 'idempotent', false);
END;
$$;
REVOKE ALL ON FUNCTION public.edoc_copy_editor_conflict(jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.edoc_copy_editor_conflict(jsonb) TO service_role;
