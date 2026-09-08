-- Persist numbers at first draft save. Never renumber historical cases.
BEGIN;
ALTER TABLE public.official_documents ADD COLUMN IF NOT EXISTS dispatch_no text;
CREATE UNIQUE INDEX IF NOT EXISTS ux_official_documents_dispatch_no
  ON public.official_documents(dispatch_no) WHERE dispatch_no IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.official_document_number_counters (
  date_key text PRIMARY KEY,
  last_serial bigint NOT NULL CHECK (last_serial > 0)
);
CREATE TABLE IF NOT EXISTS public.official_document_number_allocations (
  document_id text PRIMARY KEY REFERENCES public.official_documents(id) ON DELETE RESTRICT,
  company_id text NOT NULL REFERENCES public.companies(id) ON DELETE RESTRICT,
  applicant_id text NOT NULL,
  dispatch_no text NOT NULL UNIQUE,
  assigned_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.official_document_number_counters ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.official_document_number_allocations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.official_document_number_counters FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.official_document_number_allocations FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.official_document_number_counters TO service_role;
GRANT SELECT, INSERT ON public.official_document_number_allocations TO service_role;

CREATE OR REPLACE FUNCTION public.edoc_number_safe_metadata(p_value text)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  RETURN COALESCE(p_value::jsonb, '{}'::jsonb);
EXCEPTION WHEN invalid_text_representation THEN RETURN '{}'::jsonb;
END;
$$;

CREATE OR REPLACE FUNCTION public.edoc_allocate_official_number()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_today date := (statement_timestamp() AT TIME ZONE 'Asia/Taipei')::date;
  v_key text;
  v_prefix text;
  v_floor bigint;
  v_serial bigint;
BEGIN
  IF NEW.dispatch_no IS NOT NULL THEN
    RAISE EXCEPTION 'official_document_number_server_owned' USING ERRCODE = '23514';
  END IF;
  IF NEW.source_type <> 'blank_editor' THEN RETURN NEW; END IF;
  v_key := (extract(year FROM v_today)::integer - 1911)::text || to_char(v_today, 'MMDD');
  v_prefix := '歲悅字第' || v_key;
  -- A transaction-scoped lock includes the legacy floor lookup and upsert.
  -- Same-prefix callers serialize; unrelated transactions remain unblocked.
  PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('edoc.number.' || v_key, 0));
  SELECT COALESCE(max(serial::bigint), 0) INTO v_floor FROM (
    SELECT substring(value FROM char_length(v_prefix) + 1 FOR char_length(value) - char_length(v_prefix) - 1) AS serial
    FROM (
      SELECT d.doc_no AS value FROM public.documents d WHERE d.direction = '發文'
      UNION ALL SELECT d.dispatch_no FROM public.official_documents d
      UNION ALL SELECT public.edoc_number_safe_metadata(d.metadata_json)->>'dispatch_no' FROM public.official_documents d
      UNION ALL SELECT public.edoc_number_safe_metadata(d.metadata_json)#>>'{extra,dispatch_no}' FROM public.official_documents d
    ) existing
    WHERE value LIKE v_prefix || '%號'
  ) parts WHERE serial ~ '^[0-9]{1,12}$';
  INSERT INTO public.official_document_number_counters AS counters(date_key, last_serial)
  VALUES (v_key, v_floor + 1)
  ON CONFLICT (date_key) DO UPDATE
    SET last_serial = greatest(counters.last_serial, v_floor) + 1
  RETURNING last_serial INTO v_serial;
  NEW.dispatch_no := v_prefix || lpad(v_serial::text, greatest(3, char_length(v_serial::text)), '0') || '號';
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.edoc_record_official_number()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  IF NEW.dispatch_no IS NOT NULL THEN
    INSERT INTO public.official_document_number_allocations(document_id, company_id, applicant_id, dispatch_no)
    VALUES (NEW.id, NEW.company_id, NEW.applicant_id, NEW.dispatch_no);
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.edoc_guard_official_number()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  IF NEW.dispatch_no IS DISTINCT FROM OLD.dispatch_no OR
    (OLD.dispatch_no IS NOT NULL AND (
      NEW.company_id IS DISTINCT FROM OLD.company_id OR
      NEW.applicant_id IS DISTINCT FROM OLD.applicant_id OR
      NEW.source_type IS DISTINCT FROM OLD.source_type
    )) THEN
    RAISE EXCEPTION 'official_document_number_immutable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.edoc_guard_number_allocation()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  RAISE EXCEPTION 'official_document_number_immutable' USING ERRCODE = '23514';
END;
$$;

DROP TRIGGER IF EXISTS trg_official_number_allocate ON public.official_documents;
CREATE TRIGGER trg_official_number_allocate BEFORE INSERT ON public.official_documents
  FOR EACH ROW EXECUTE FUNCTION public.edoc_allocate_official_number();
DROP TRIGGER IF EXISTS trg_official_number_record ON public.official_documents;
CREATE TRIGGER trg_official_number_record AFTER INSERT ON public.official_documents
  FOR EACH ROW EXECUTE FUNCTION public.edoc_record_official_number();
DROP TRIGGER IF EXISTS trg_official_number_immutable ON public.official_documents;
CREATE TRIGGER trg_official_number_immutable BEFORE UPDATE OF dispatch_no, company_id, applicant_id, source_type
  ON public.official_documents FOR EACH ROW EXECUTE FUNCTION public.edoc_guard_official_number();
CREATE TRIGGER trg_official_number_allocation_immutable BEFORE UPDATE OR DELETE
  ON public.official_document_number_allocations FOR EACH ROW EXECUTE FUNCTION public.edoc_guard_number_allocation();

REVOKE ALL ON FUNCTION public.edoc_number_safe_metadata(text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.edoc_allocate_official_number() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.edoc_record_official_number() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.edoc_guard_official_number() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.edoc_guard_number_allocation() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.edoc_number_safe_metadata(text) TO service_role;
GRANT EXECUTE ON FUNCTION public.edoc_allocate_official_number() TO service_role;
GRANT EXECUTE ON FUNCTION public.edoc_record_official_number() TO service_role;
GRANT EXECUTE ON FUNCTION public.edoc_guard_official_number() TO service_role;
GRANT EXECUTE ON FUNCTION public.edoc_guard_number_allocation() TO service_role;
COMMIT;
