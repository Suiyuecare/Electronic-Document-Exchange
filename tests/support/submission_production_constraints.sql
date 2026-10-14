-- Narrow, production-faithful column contract for the tables written by the
-- atomic submit RPC. The historical SQLite projection omits these NOT NULL
-- constraints; ADD COLUMN IF NOT EXISTS migrations cannot restore them.
-- Sources: 20260702121520_official_document_workflow.sql,
-- 202606130001_seal_application_pdf_workflow.sql,
-- 20260827050436_complete_edoc_runtime_schema_parity.sql and their forwards.
-- Synthetic loopback databases only; no live data or identities are embedded.
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS chain_version integer NOT NULL DEFAULT 1;
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS immutable boolean NOT NULL DEFAULT true;
DO $submission_fixture$
DECLARE
  item record;
  pair text;
  table_name text;
  column_name text;
BEGIN
  FOR item IN SELECT * FROM (VALUES
    ('official_documents', 'company_id,document_type,source_type,title,applicant_id,current_status,metadata_json,created_at,updated_at'),
    ('official_document_approval_steps', 'document_id,step_order,step_key,step_name,status,created_at,updated_at,workflow_generation,decision_evidence_json'),
    ('official_document_approval_logs', 'document_id,action,created_at,decision_evidence_json'),
    ('official_document_stamp_requests', 'document_id,company_id,seal_id,requested_by,stamp_page,stamp_x,stamp_y,stamp_width,stamp_height,status,created_at,updated_at,claim_attempt_count'),
    ('official_document_stamp_positions', 'request_id,seal_id,page,x,y,width,height,order_index,created_at,updated_at,rotation,opacity,z_index'),
    ('approval_step_actor_snapshots', 'source_type,source_id,step_no,step_name,approver_role,status,snapshot_json,created_at,updated_at'),
    ('audit_logs', 'actor,action,created_at,chain_version,immutable,event_type,severity,result,actor_roles_json,before_snapshot_json,after_snapshot_json,metadata_json')
  ) AS required(table_name,columns)
  LOOP
    FOREACH column_name IN ARRAY string_to_array(item.columns, ',') LOOP
      EXECUTE format('ALTER TABLE %I ALTER COLUMN %I SET NOT NULL', item.table_name, column_name);
    END LOOP;
  END LOOP;
  FOREACH pair IN ARRAY ARRAY[
    'official_documents.created_at','official_documents.updated_at',
    'official_document_approval_steps.created_at','official_document_approval_steps.updated_at',
    'official_document_approval_logs.created_at',
    'official_document_stamp_requests.created_at','official_document_stamp_requests.updated_at',
    'official_document_stamp_positions.created_at','official_document_stamp_positions.updated_at',
    'approval_step_actor_snapshots.created_at','approval_step_actor_snapshots.updated_at',
    'audit_logs.created_at'
  ] LOOP
    table_name := split_part(pair,'.',1); column_name := split_part(pair,'.',2);
    EXECUTE format('ALTER TABLE %I ALTER COLUMN %I SET DEFAULT to_char(now(),''YYYY-MM-DD HH24:MI:SS'')',table_name,column_name);
  END LOOP;
END;
$submission_fixture$;

ALTER TABLE official_document_approval_steps ALTER COLUMN decision_evidence_json SET DEFAULT '{}'::jsonb;
ALTER TABLE official_document_approval_logs ALTER COLUMN decision_evidence_json SET DEFAULT '{}'::jsonb;
ALTER TABLE approval_step_actor_snapshots ALTER COLUMN snapshot_json SET DEFAULT '{}'::jsonb;
ALTER TABLE official_document_approval_steps ADD CONSTRAINT faithful_submission_step_status
  CHECK (status IN ('pending','approved','rejected','skipped'));
ALTER TABLE official_document_stamp_requests ADD CONSTRAINT faithful_submission_stamp_status
  CHECK (status IN ('pending','approved','stamping','stamped','failed'));
ALTER TABLE official_documents ADD CONSTRAINT faithful_submission_source_type
  CHECK (source_type IN ('blank_editor','uploaded_pdf'));
