-- Forward-only runtime schema parity for the eDoc application.
--
-- The table, constraint, trigger, and RPC definitions were compared with the
-- main Supabase catalog on 2026-08-27.  This file is safe to apply to an
-- existing eDoc database and also completes a fresh migration-chain rebuild.
-- It intentionally does not enable or contact a formal exchange provider.

create schema if not exists edoc_private;
revoke all on schema edoc_private from public, anon, authenticated;

-- Early repository migrations created the workflow header tables before the
-- correction, Editor V2, immutable approval-evidence, retention, and worker
-- lease fields were introduced in production.  Add every runtime field before
-- defining functions that use %rowtype so a clean database and an upgraded
-- database expose the same record shape.
alter table public.official_documents
  add column if not exists workflow_template_key text not null default 'internal_official_dispatch_v1',
  add column if not exists stamped_file_id text,
  add column if not exists requires_stamp boolean not null default true,
  add column if not exists correction_reason_category text,
  add column if not exists correction_missing_items_json jsonb not null default '[]'::jsonb,
  add column if not exists correction_due_at timestamptz,
  add column if not exists correction_requested_at timestamptz,
  add column if not exists correction_resubmitted_at timestamptz,
  add column if not exists retention_until timestamptz not null default (now() + interval '10 years'),
  add column if not exists retention_policy_version text not null default 'EDOC-RETENTION-2026-10Y',
  add column if not exists legal_hold boolean not null default false,
  add column if not exists legal_hold_reason text,
  add column if not exists disposition_status text not null default 'retained',
  add column if not exists disposition_approved_by text,
  add column if not exists disposition_approved_at timestamptz;

alter table public.official_document_files
  add column if not exists stamp_request_id text,
  add column if not exists stamp_claim_token text;

alter table public.official_document_approval_steps
  add column if not exists workflow_generation integer not null default 1,
  add column if not exists decision_actor_user_id text,
  add column if not exists decision_evidence_json jsonb not null default '{}'::jsonb,
  add column if not exists review_started_at text;

alter table public.official_document_approval_logs
  add column if not exists principal_actor_id text,
  add column if not exists decision_evidence_json jsonb not null default '{}'::jsonb;

alter table public.official_document_stamp_requests
  add column if not exists locked_editor_revision_id text,
  add column if not exists locked_source_sha256 text,
  add column if not exists prepared_file_id text,
  add column if not exists prepared_sha256 text,
  add column if not exists editor_manifest_sha256 text,
  add column if not exists editor_schema_version integer,
  add column if not exists renderer_version text,
  add column if not exists editor_locked_at text,
  add column if not exists claim_token text,
  add column if not exists claim_owner_id text,
  add column if not exists claim_started_at timestamptz,
  add column if not exists claim_expires_at timestamptz,
  add column if not exists claim_attempt_count integer not null default 0;

-- Notification workflow functions below target one exact Finance user and
-- company and return an in-app action URL. These columns existed in the live
-- catalog but were absent from the historical migration chain.
alter table public.notifications
  add column if not exists target_user_id text,
  add column if not exists target_company_id text,
  add column if not exists action_url text;

-- Keep accepted values aligned with the current backend contract.  Replacing
-- these CHECK constraints is deliberate: ADD CONSTRAINT has no IF NOT EXISTS,
-- and the earlier file/file-status lists did not include Editor V2 output.
alter table public.official_documents
  drop constraint if exists official_documents_status_check;
alter table public.official_documents
  add constraint official_documents_status_check check (
    current_status in (
      'draft', 'pending_applicant_manager', 'pending_department_head',
      'pending_admin_director', 'pending_general_affairs_review', 'pending_ceo',
      'approved', 'stamping', 'stamped', 'pending_general_affairs_dispatch',
      'returned_to_applicant_for_send', 'dispatched', 'sent_by_applicant',
      'closed', 'rejected', 'cancelled', 'stamping_failed'
    )
  );

alter table public.official_document_files
  drop constraint if exists official_document_files_type_check;
alter table public.official_document_files
  add constraint official_document_files_type_check check (
    file_type in (
      'original_pdf', 'generated_pdf', 'prepared_pdf', 'stamped_pdf',
      'attachment', 'dispatch_proof'
    )
  );

alter table public.official_document_approval_steps
  drop constraint if exists official_document_approval_steps_document_id_step_order_key,
  drop constraint if exists official_document_approval_steps_document_id_step_key_key;

do $$
begin
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.official_documents'::regclass
      and conname = 'official_documents_disposition_status_check'
  ) then
    alter table public.official_documents
      add constraint official_documents_disposition_status_check check (
        disposition_status in (
          'retained', 'pending_review', 'approved_for_destruction', 'destroyed'
        )
      );
  end if;

  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.official_document_approval_steps'::regclass
      and conname = 'official_document_steps_generation_order_key'
  ) then
    alter table public.official_document_approval_steps
      add constraint official_document_steps_generation_order_key
      unique (document_id, workflow_generation, step_order);
  end if;

  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.official_document_approval_steps'::regclass
      and conname = 'official_document_steps_generation_step_key'
  ) then
    alter table public.official_document_approval_steps
      add constraint official_document_steps_generation_step_key
      unique (document_id, workflow_generation, step_key);
  end if;

  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.official_document_stamp_requests'::regclass
      and conname = 'official_document_stamp_requests_claim_attempt_count_check'
  ) then
    alter table public.official_document_stamp_requests
      add constraint official_document_stamp_requests_claim_attempt_count_check
      check (claim_attempt_count >= 0);
  end if;
end
$$;

CREATE TABLE IF NOT EXISTS public.inbound_document_attachments (
  id text NOT NULL,
  inbound_document_id text NOT NULL,
  file_object_id text,
  file_name text NOT NULL,
  file_mime_type text NOT NULL,
  file_size bigint DEFAULT 0 NOT NULL,
  file_hash text NOT NULL,
  attachment_type text DEFAULT 'inbound_attachment'::text NOT NULL,
  uploaded_by text,
  created_at text DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'::text) NOT NULL,
  CONSTRAINT inbound_document_attachments_file_object_id_fkey FOREIGN KEY (file_object_id) REFERENCES file_objects(id) ON DELETE SET NULL,
  CONSTRAINT inbound_document_attachments_inbound_document_id_fkey FOREIGN KEY (inbound_document_id) REFERENCES inbound_documents(id) ON DELETE CASCADE,
  CONSTRAINT inbound_document_attachments_pkey PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.internal_dispatches (
  id text NOT NULL,
  official_document_id text,
  title text NOT NULL,
  subject text NOT NULL,
  body text,
  sender_user_id text,
  sender_name text,
  sender_department text,
  reply_required boolean DEFAULT false NOT NULL,
  reply_due_days integer,
  due_at text,
  reply_status text DEFAULT 'not_required'::text NOT NULL,
  status text DEFAULT 'sent'::text NOT NULL,
  metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
  created_at text DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'::text) NOT NULL,
  updated_at text DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'::text) NOT NULL,
  closed_at text,
  inbound_document_id text,
  retention_until timestamp with time zone DEFAULT (now() + '10 years'::interval) NOT NULL,
  retention_policy_version text DEFAULT 'EDOC-RETENTION-2026-10Y'::text NOT NULL,
  legal_hold boolean DEFAULT false NOT NULL,
  legal_hold_reason text,
  disposition_status text DEFAULT 'retained'::text NOT NULL,
  disposition_approved_by text,
  disposition_approved_at timestamp with time zone,
  CONSTRAINT internal_dispatches_disposition_status_check CHECK (disposition_status = ANY (ARRAY['retained'::text, 'pending_review'::text, 'approved_for_destruction'::text, 'destroyed'::text])),
  CONSTRAINT internal_dispatches_inbound_document_id_fkey FOREIGN KEY (inbound_document_id) REFERENCES inbound_documents(id) ON DELETE SET NULL,
  CONSTRAINT internal_dispatches_official_document_id_fkey FOREIGN KEY (official_document_id) REFERENCES official_documents(id) ON DELETE SET NULL,
  CONSTRAINT internal_dispatches_pkey PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.internal_dispatch_recipients (
  id text NOT NULL,
  dispatch_id text NOT NULL,
  recipient_type text DEFAULT 'user'::text NOT NULL,
  recipient_user_id text,
  recipient_department_id text,
  recipient_name text,
  status text DEFAULT 'pending'::text NOT NULL,
  read_at text,
  replied_at text,
  created_at text DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'::text) NOT NULL,
  updated_at text DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'::text) NOT NULL,
  action_required boolean DEFAULT false NOT NULL,
  CONSTRAINT internal_dispatch_recipients_dispatch_id_fkey FOREIGN KEY (dispatch_id) REFERENCES internal_dispatches(id) ON DELETE CASCADE,
  CONSTRAINT internal_dispatch_recipients_pkey PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.internal_dispatch_replies (
  id text NOT NULL,
  dispatch_id text NOT NULL,
  recipient_id text,
  replier_user_id text,
  replier_name text,
  reply_text text,
  attachment_file_id text,
  status text DEFAULT 'submitted'::text NOT NULL,
  created_at text DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'::text) NOT NULL,
  CONSTRAINT internal_dispatch_replies_attachment_file_id_fkey FOREIGN KEY (attachment_file_id) REFERENCES file_objects(id) ON DELETE SET NULL,
  CONSTRAINT internal_dispatch_replies_dispatch_id_fkey FOREIGN KEY (dispatch_id) REFERENCES internal_dispatches(id) ON DELETE CASCADE,
  CONSTRAINT internal_dispatch_replies_pkey PRIMARY KEY (id),
  CONSTRAINT internal_dispatch_replies_recipient_id_fkey FOREIGN KEY (recipient_id) REFERENCES internal_dispatch_recipients(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS public.internal_dispatch_logs (
  id text NOT NULL,
  dispatch_id text NOT NULL,
  actor_id text,
  action text NOT NULL,
  detail text,
  ip_address text,
  user_agent text,
  created_at text DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'::text) NOT NULL,
  CONSTRAINT internal_dispatch_logs_dispatch_id_fkey FOREIGN KEY (dispatch_id) REFERENCES internal_dispatches(id) ON DELETE CASCADE,
  CONSTRAINT internal_dispatch_logs_pkey PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.official_workflow_delegations (
  id text NOT NULL,
  company_id text NOT NULL,
  principal_user_id text NOT NULL,
  delegate_user_id text NOT NULL,
  starts_at timestamp with time zone NOT NULL,
  ends_at timestamp with time zone NOT NULL,
  status text DEFAULT 'active'::text NOT NULL,
  reason text NOT NULL,
  created_by text NOT NULL,
  revoked_by text,
  revoked_at timestamp with time zone,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  updated_at timestamp with time zone DEFAULT now() NOT NULL,
  CONSTRAINT official_workflow_delegations_company_id_fkey FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE RESTRICT,
  CONSTRAINT official_workflow_delegations_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT,
  CONSTRAINT official_workflow_delegations_delegate_user_id_fkey FOREIGN KEY (delegate_user_id) REFERENCES users(id) ON DELETE RESTRICT,
  CONSTRAINT official_workflow_delegations_distinct_users CHECK (principal_user_id <> delegate_user_id),
  CONSTRAINT official_workflow_delegations_pkey PRIMARY KEY (id),
  CONSTRAINT official_workflow_delegations_principal_user_id_fkey FOREIGN KEY (principal_user_id) REFERENCES users(id) ON DELETE RESTRICT,
  CONSTRAINT official_workflow_delegations_revoked_by_fkey FOREIGN KEY (revoked_by) REFERENCES users(id) ON DELETE RESTRICT,
  CONSTRAINT official_workflow_delegations_status CHECK (status = ANY (ARRAY['active'::text, 'revoked'::text, 'expired'::text])),
  CONSTRAINT official_workflow_delegations_valid_period CHECK (ends_at > starts_at)
);

CREATE TABLE IF NOT EXISTS public.official_document_stamp_positions (
  id text NOT NULL,
  request_id text NOT NULL,
  seal_id text NOT NULL,
  page integer DEFAULT 1 NOT NULL,
  x numeric DEFAULT 420 NOT NULL,
  y numeric DEFAULT 130 NOT NULL,
  width numeric DEFAULT 85 NOT NULL,
  height numeric DEFAULT 85 NOT NULL,
  order_index integer DEFAULT 1 NOT NULL,
  created_at text DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'::text) NOT NULL,
  updated_at text DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'::text) NOT NULL,
  page_ref text,
  rotation numeric DEFAULT 0 NOT NULL,
  opacity numeric DEFAULT 1 NOT NULL,
  z_index integer DEFAULT 1 NOT NULL,
  locked_seal_file_id text,
  locked_seal_sha256 text,
  locked_render_width_pt numeric,
  locked_render_height_pt numeric,
  locked_dimension_policy_version text,
  CONSTRAINT official_document_stamp_positions_locked_seal_file_id_fkey FOREIGN KEY (locked_seal_file_id) REFERENCES company_seal_files(id) ON DELETE RESTRICT,
  CONSTRAINT official_document_stamp_positions_pkey PRIMARY KEY (id),
  CONSTRAINT official_document_stamp_positions_request_id_fkey FOREIGN KEY (request_id) REFERENCES official_document_stamp_requests(id) ON DELETE CASCADE,
  CONSTRAINT official_document_stamp_positions_seal_id_fkey FOREIGN KEY (seal_id) REFERENCES company_seals(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS public.official_document_text_overlays (
  id text NOT NULL,
  request_id text NOT NULL,
  page integer DEFAULT 1 NOT NULL,
  x numeric DEFAULT 72 NOT NULL,
  y numeric DEFAULT 72 NOT NULL,
  text_content text NOT NULL,
  font_size numeric DEFAULT 14 NOT NULL,
  font_family text DEFAULT 'biau_kai'::text NOT NULL,
  order_index integer DEFAULT 1 NOT NULL,
  created_at text DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'::text) NOT NULL,
  updated_at text DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'::text) NOT NULL,
  CONSTRAINT official_document_text_overlays_font_family_check CHECK (font_family = 'biau_kai'::text),
  CONSTRAINT official_document_text_overlays_font_size_check CHECK (font_size >= 8::numeric AND font_size <= 72::numeric),
  CONSTRAINT official_document_text_overlays_page_check CHECK (page >= 1),
  CONSTRAINT official_document_text_overlays_pkey PRIMARY KEY (id),
  CONSTRAINT official_document_text_overlays_request_id_fkey FOREIGN KEY (request_id) REFERENCES official_document_stamp_requests(id) ON DELETE CASCADE,
  CONSTRAINT official_document_text_overlays_text_content_check CHECK (char_length(btrim(text_content)) >= 1 AND char_length(btrim(text_content)) <= 500),
  CONSTRAINT official_document_text_overlays_x_check CHECK (x >= 0::numeric),
  CONSTRAINT official_document_text_overlays_y_check CHECK (y >= 0::numeric)
);

CREATE TABLE IF NOT EXISTS public.official_document_editor_revisions (
  id text NOT NULL,
  document_id text NOT NULL,
  revision_no integer NOT NULL,
  parent_revision_id text,
  schema_version integer DEFAULT 2 NOT NULL,
  editor_state_json text NOT NULL,
  manifest_sha256 text NOT NULL,
  renderer_version text NOT NULL,
  created_by text NOT NULL,
  created_at text DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'::text) NOT NULL,
  CONSTRAINT official_document_editor_revisions_document_id_fkey FOREIGN KEY (document_id) REFERENCES official_documents(id) ON DELETE CASCADE,
  CONSTRAINT official_document_editor_revisions_parent_revision_id_fkey FOREIGN KEY (parent_revision_id) REFERENCES official_document_editor_revisions(id) ON DELETE RESTRICT,
  CONSTRAINT official_document_editor_revisions_pkey PRIMARY KEY (id),
  CONSTRAINT official_editor_document_revision_unique UNIQUE (document_id, revision_no),
  CONSTRAINT official_editor_manifest_sha256_check CHECK (manifest_sha256 ~ '^[A-Fa-f0-9]{64}$'::text),
  CONSTRAINT official_editor_revision_no_check CHECK (revision_no > 0),
  CONSTRAINT official_editor_schema_version_check CHECK (schema_version >= 2)
);

CREATE TABLE IF NOT EXISTS public.official_document_editor_assets (
  id text NOT NULL,
  document_id text NOT NULL,
  editor_revision_id text,
  asset_kind text NOT NULL,
  file_object_id text,
  official_file_id text,
  file_name text NOT NULL,
  mime_type text NOT NULL,
  size_bytes bigint DEFAULT 0 NOT NULL,
  sha256 text DEFAULT ''::text NOT NULL,
  expected_sha256 text DEFAULT ''::text NOT NULL,
  storage_bucket text DEFAULT ''::text NOT NULL,
  storage_path text DEFAULT ''::text NOT NULL,
  upload_status text DEFAULT 'pending'::text NOT NULL,
  scan_status text DEFAULT 'pending'::text NOT NULL,
  preflight_status text DEFAULT 'pending'::text NOT NULL,
  page_count integer DEFAULT 0 NOT NULL,
  metadata_json text DEFAULT '{}'::text NOT NULL,
  created_by text NOT NULL,
  created_at text DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'::text) NOT NULL,
  finalized_at text,
  CONSTRAINT official_document_editor_assets_document_id_fkey FOREIGN KEY (document_id) REFERENCES official_documents(id) ON DELETE CASCADE,
  CONSTRAINT official_document_editor_assets_editor_revision_id_fkey FOREIGN KEY (editor_revision_id) REFERENCES official_document_editor_revisions(id) ON DELETE RESTRICT,
  CONSTRAINT official_document_editor_assets_file_object_id_fkey FOREIGN KEY (file_object_id) REFERENCES file_objects(id) ON DELETE SET NULL,
  CONSTRAINT official_document_editor_assets_official_file_id_fkey FOREIGN KEY (official_file_id) REFERENCES official_document_files(id) ON DELETE SET NULL,
  CONSTRAINT official_document_editor_assets_pkey PRIMARY KEY (id),
  CONSTRAINT official_editor_asset_expected_sha256_check CHECK (expected_sha256 = ''::text OR expected_sha256 ~ '^[A-Fa-f0-9]{64}$'::text),
  CONSTRAINT official_editor_asset_kind_check CHECK (asset_kind = ANY (ARRAY['source_pdf'::text, 'import_pdf'::text, 'image'::text, 'prepared_pdf'::text])),
  CONSTRAINT official_editor_asset_page_count_check CHECK (page_count >= 0),
  CONSTRAINT official_editor_asset_preflight_status_check CHECK (preflight_status = ANY (ARRAY['pending'::text, 'processing'::text, 'passed'::text, 'blocked'::text, 'failed'::text])),
  CONSTRAINT official_editor_asset_scan_status_check CHECK (scan_status = ANY (ARRAY['pending'::text, 'passed'::text, 'failed'::text])),
  CONSTRAINT official_editor_asset_sha256_check CHECK (sha256 = ''::text OR sha256 ~ '^[A-Fa-f0-9]{64}$'::text),
  CONSTRAINT official_editor_asset_size_check CHECK (size_bytes >= 0),
  CONSTRAINT official_editor_asset_upload_status_check CHECK (upload_status = ANY (ARRAY['pending'::text, 'uploading'::text, 'uploaded'::text, 'finalized'::text, 'quarantined'::text, 'failed'::text]))
);

CREATE TABLE IF NOT EXISTS public.official_document_rejection_jobs (
  id text NOT NULL,
  document_id text NOT NULL,
  expected_step_id text NOT NULL,
  source_revision_id text NOT NULL,
  target_revision_id text,
  status text DEFAULT 'pending'::text NOT NULL,
  attempt_count integer DEFAULT 0 NOT NULL,
  last_error_code text,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  completed_at timestamp with time zone,
  CONSTRAINT official_document_rejection_jobs_document_id_fkey FOREIGN KEY (document_id) REFERENCES official_documents(id) ON DELETE RESTRICT,
  CONSTRAINT official_document_rejection_jobs_expected_step_id_fkey FOREIGN KEY (expected_step_id) REFERENCES official_document_approval_steps(id) ON DELETE RESTRICT,
  CONSTRAINT official_document_rejection_jobs_pkey PRIMARY KEY (id),
  CONSTRAINT official_document_rejection_jobs_source_revision_id_fkey FOREIGN KEY (source_revision_id) REFERENCES official_document_editor_revisions(id) ON DELETE RESTRICT,
  CONSTRAINT official_document_rejection_jobs_status_check CHECK (status = ANY (ARRAY['pending'::text, 'completed'::text, 'failed'::text])),
  CONSTRAINT official_document_rejection_jobs_target_revision_id_fkey FOREIGN KEY (target_revision_id) REFERENCES official_document_editor_revisions(id) ON DELETE RESTRICT,
  CONSTRAINT official_document_rejection_jo_document_id_expected_step_id_key UNIQUE (document_id, expected_step_id)
);

CREATE TABLE IF NOT EXISTS public.official_document_dispatch_events (
  id text NOT NULL,
  dispatch_record_id text NOT NULL,
  document_id text NOT NULL,
  event_sequence bigint NOT NULL,
  event_type text NOT NULL,
  from_status text,
  to_status text NOT NULL,
  changed_fields text[] DEFAULT ARRAY[]::text[] NOT NULL,
  record_snapshot_sha256 text NOT NULL,
  database_actor text NOT NULL,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  CONSTRAINT official_document_dispatch_ev_dispatch_record_id_event_sequ_key UNIQUE (dispatch_record_id, event_sequence),
  CONSTRAINT official_document_dispatch_events_dispatch_record_id_fkey FOREIGN KEY (dispatch_record_id) REFERENCES official_document_dispatch_records(id) ON DELETE RESTRICT,
  CONSTRAINT official_document_dispatch_events_document_id_fkey FOREIGN KEY (document_id) REFERENCES official_documents(id) ON DELETE RESTRICT,
  CONSTRAINT official_document_dispatch_events_event_sequence_check CHECK (event_sequence > 0),
  CONSTRAINT official_document_dispatch_events_pkey PRIMARY KEY (id),
  CONSTRAINT official_document_dispatch_events_record_snapshot_sha256_check CHECK (record_snapshot_sha256 ~ '^[0-9a-f]{64}$'::text)
);

CREATE TABLE IF NOT EXISTS public.official_document_archive_exports (
  id text NOT NULL,
  document_id text NOT NULL,
  requested_by text NOT NULL,
  manifest_sha256 text NOT NULL,
  package_sha256 text NOT NULL,
  entry_count integer NOT NULL,
  package_size_bytes bigint NOT NULL,
  renderer_version text NOT NULL,
  storage_bucket text,
  storage_path text,
  status text DEFAULT 'ready'::text NOT NULL,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  CONSTRAINT official_document_archive_exports_document_id_fkey FOREIGN KEY (document_id) REFERENCES official_documents(id) ON DELETE RESTRICT,
  CONSTRAINT official_document_archive_exports_pkey PRIMARY KEY (id),
  CONSTRAINT official_document_archive_exports_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES users(id) ON DELETE RESTRICT
);

-- Add cross-table references only after all Editor V2 tables exist.  Each
-- constraint is checked by table and name because PostgreSQL does not support
-- ADD CONSTRAINT IF NOT EXISTS.
do $$
begin
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.official_documents'::regclass
      and conname = 'official_documents_stamped_file_id_fkey'
  ) then
    alter table public.official_documents
      add constraint official_documents_stamped_file_id_fkey
      foreign key (stamped_file_id)
      references public.official_document_files(id) on delete set null;
  end if;

  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.official_document_files'::regclass
      and conname = 'official_document_files_stamp_request_id_fkey'
  ) then
    alter table public.official_document_files
      add constraint official_document_files_stamp_request_id_fkey
      foreign key (stamp_request_id)
      references public.official_document_stamp_requests(id) on delete set null;
  end if;

  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.official_document_approval_steps'::regclass
      and conname = 'official_document_steps_decision_actor_fk'
  ) then
    alter table public.official_document_approval_steps
      add constraint official_document_steps_decision_actor_fk
      foreign key (decision_actor_user_id)
      references public.users(id) on delete restrict;
  end if;

  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.official_document_approval_logs'::regclass
      and conname = 'official_document_logs_principal_actor_fk'
  ) then
    alter table public.official_document_approval_logs
      add constraint official_document_logs_principal_actor_fk
      foreign key (principal_actor_id)
      references public.users(id) on delete restrict;
  end if;

  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.official_document_stamp_requests'::regclass
      and conname = 'official_document_stamp_requests_locked_editor_revision_id_fkey'
  ) then
    alter table public.official_document_stamp_requests
      add constraint official_document_stamp_requests_locked_editor_revision_id_fkey
      foreign key (locked_editor_revision_id)
      references public.official_document_editor_revisions(id) on delete restrict;
  end if;

  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.official_document_stamp_requests'::regclass
      and conname = 'official_document_stamp_requests_prepared_file_id_fkey'
  ) then
    alter table public.official_document_stamp_requests
      add constraint official_document_stamp_requests_prepared_file_id_fkey
      foreign key (prepared_file_id)
      references public.official_document_files(id) on delete restrict;
  end if;

  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.official_document_dispatch_records'::regclass
      and conname = 'official_document_dispatch_records_document_key'
  ) then
    alter table public.official_document_dispatch_records
      add constraint official_document_dispatch_records_document_key
      unique (document_id);
  end if;
end
$$;

-- Runtime and foreign-key lookup indexes.
create index if not exists idx_inbound_attachments_document on public.inbound_document_attachments(inbound_document_id, created_at);
create index if not exists idx_inbound_attachments_file_object on public.inbound_document_attachments(file_object_id);
create index if not exists idx_internal_dispatches_status on public.internal_dispatches(status, due_at);
create index if not exists idx_internal_dispatches_inbound_document on public.internal_dispatches(inbound_document_id, created_at desc);
create index if not exists idx_internal_dispatches_official_document on public.internal_dispatches(official_document_id);
create index if not exists idx_internal_dispatch_recipients_action on public.internal_dispatch_recipients(dispatch_id, action_required, status);
create index if not exists idx_internal_dispatch_recipients_user on public.internal_dispatch_recipients(recipient_user_id, status);
create index if not exists idx_internal_dispatch_replies_dispatch on public.internal_dispatch_replies(dispatch_id, created_at);
create index if not exists idx_internal_dispatch_replies_recipient on public.internal_dispatch_replies(recipient_id);
create index if not exists idx_internal_dispatch_replies_attachment on public.internal_dispatch_replies(attachment_file_id);
create index if not exists idx_internal_dispatch_logs_dispatch on public.internal_dispatch_logs(dispatch_id, created_at);
create index if not exists idx_official_workflow_delegations_lookup on public.official_workflow_delegations(company_id, principal_user_id, delegate_user_id, status, starts_at, ends_at);
create index if not exists idx_official_workflow_delegations_principal on public.official_workflow_delegations(principal_user_id);
create index if not exists idx_official_workflow_delegations_delegate on public.official_workflow_delegations(delegate_user_id);
create index if not exists idx_official_workflow_delegations_created_by on public.official_workflow_delegations(created_by);
create index if not exists idx_official_workflow_delegations_revoked_by on public.official_workflow_delegations(revoked_by) where revoked_by is not null;
create index if not exists idx_official_stamp_positions_request on public.official_document_stamp_positions(request_id, order_index);
create index if not exists idx_official_stamp_positions_seal on public.official_document_stamp_positions(seal_id);
create index if not exists idx_official_stamp_positions_locked_seal_file on public.official_document_stamp_positions(locked_seal_file_id);
create index if not exists idx_official_text_overlays_request on public.official_document_text_overlays(request_id, order_index);
create index if not exists idx_official_editor_revisions_parent on public.official_document_editor_revisions(parent_revision_id);
create unique index if not exists idx_official_editor_single_child_revision on public.official_document_editor_revisions(document_id, parent_revision_id) where parent_revision_id is not null;
create index if not exists idx_official_editor_assets_document on public.official_document_editor_assets(document_id, created_at);
create index if not exists idx_official_editor_assets_revision on public.official_document_editor_assets(editor_revision_id, asset_kind);
create index if not exists idx_official_editor_assets_file_object on public.official_document_editor_assets(file_object_id);
create index if not exists idx_official_editor_assets_official_file on public.official_document_editor_assets(official_file_id);
create index if not exists idx_official_rejection_jobs_expected_step on public.official_document_rejection_jobs(expected_step_id);
create index if not exists idx_official_rejection_jobs_source_revision on public.official_document_rejection_jobs(source_revision_id);
create index if not exists idx_official_rejection_jobs_target_revision on public.official_document_rejection_jobs(target_revision_id) where target_revision_id is not null;
create index if not exists idx_official_dispatch_events_document_created on public.official_document_dispatch_events(document_id, created_at, event_sequence);
create index if not exists idx_official_archive_exports_document_created on public.official_document_archive_exports(document_id, created_at desc);
create index if not exists idx_official_archive_exports_requested_by on public.official_document_archive_exports(requested_by);
create unique index if not exists idx_official_archive_exports_storage_object on public.official_document_archive_exports(storage_bucket, storage_path)
  where storage_bucket is not null and storage_path is not null;

-- Confirmed eDoc foreign-key indexes reported by the Supabase performance
-- advisor on 2026-08-27. These are lookup/delete-integrity indexes only; no
-- speculative unused-index removal is performed here.
create index if not exists idx_auth_sessions_user_fk on public.auth_sessions(user_id);
create index if not exists idx_login_events_user_fk on public.login_events(user_id);
create index if not exists idx_document_retention_events_policy_fk on public.document_retention_events(policy_code);
create index if not exists idx_electronic_signatures_pdf_version_fk on public.electronic_signatures(pdf_version_id);
create index if not exists idx_electronic_signatures_certificate_fk on public.electronic_signatures(certificate_id);
create index if not exists idx_electronic_signatures_previous_fk on public.electronic_signatures(previous_signature_id)
  where previous_signature_id is not null;
create index if not exists idx_exchange_attachment_document_fk on public.exchange_attachment(document_id);
create index if not exists idx_exchange_events_task_fk on public.exchange_events(task_id);
create index if not exists idx_file_access_logs_file_object_fk on public.file_access_logs(file_object_id);
create index if not exists idx_file_access_logs_document_fk on public.file_access_logs(document_id);
create index if not exists idx_official_approval_logs_step_fk on public.official_document_approval_logs(step_id)
  where step_id is not null;
create index if not exists idx_official_approval_logs_file_fk on public.official_document_approval_logs(file_id)
  where file_id is not null;
create index if not exists idx_official_dispatch_records_proof_file_fk on public.official_document_dispatch_records(proof_file_id)
  where proof_file_id is not null;
create index if not exists idx_official_document_files_file_object_fk on public.official_document_files(file_object_id)
  where file_object_id is not null;
create index if not exists idx_official_stamp_requests_company_fk on public.official_document_stamp_requests(company_id);
create index if not exists idx_official_stamp_requests_seal_fk on public.official_document_stamp_requests(seal_id);
create index if not exists idx_official_stamp_requests_stamped_file_fk on public.official_document_stamp_requests(stamped_file_id)
  where stamped_file_id is not null;
create index if not exists idx_official_documents_stamped_file_fk on public.official_documents(stamped_file_id)
  where stamped_file_id is not null;
create index if not exists idx_pdf_versions_file_object_fk on public.pdf_versions(file_object_id);
create index if not exists idx_role_permissions_permission_fk on public.role_permissions(permission_id);
create index if not exists idx_seal_assets_file_object_fk on public.seal_assets(file_object_id);
create index if not exists idx_seal_usage_logs_document_fk on public.seal_usage_logs(document_id)
  where document_id is not null;
create index if not exists idx_seal_usage_logs_seal_fk on public.seal_usage_logs(seal_id);
create index if not exists idx_seal_usage_requests_seal_fk on public.seal_usage_requests(seal_id);
create index if not exists idx_seal_usage_requests_stamped_pdf_fk on public.seal_usage_requests(stamped_pdf_version_id)
  where stamped_pdf_version_id is not null;
create index if not exists idx_virus_scan_jobs_attachment_fk on public.virus_scan_jobs(attachment_id)
  where attachment_id is not null;
create index if not exists idx_virus_scan_jobs_document_fk on public.virus_scan_jobs(document_id)
  where document_id is not null;

-- Service-only Data API posture for every recovered runtime table.
alter table public.inbound_document_attachments enable row level security;
revoke all on table public.inbound_document_attachments from public, anon, authenticated;
alter table public.internal_dispatches enable row level security;
revoke all on table public.internal_dispatches from public, anon, authenticated;
alter table public.internal_dispatch_recipients enable row level security;
revoke all on table public.internal_dispatch_recipients from public, anon, authenticated;
alter table public.internal_dispatch_replies enable row level security;
revoke all on table public.internal_dispatch_replies from public, anon, authenticated;
alter table public.internal_dispatch_logs enable row level security;
revoke all on table public.internal_dispatch_logs from public, anon, authenticated;
alter table public.official_workflow_delegations enable row level security;
revoke all on table public.official_workflow_delegations from public, anon, authenticated;
alter table public.official_document_stamp_positions enable row level security;
revoke all on table public.official_document_stamp_positions from public, anon, authenticated;
alter table public.official_document_text_overlays enable row level security;
revoke all on table public.official_document_text_overlays from public, anon, authenticated;
alter table public.official_document_editor_revisions enable row level security;
alter table public.official_document_editor_revisions force row level security;
revoke all on table public.official_document_editor_revisions from public, anon, authenticated;
alter table public.official_document_editor_assets enable row level security;
alter table public.official_document_editor_assets force row level security;
revoke all on table public.official_document_editor_assets from public, anon, authenticated;
alter table public.official_document_rejection_jobs enable row level security;
revoke all on table public.official_document_rejection_jobs from public, anon, authenticated;
alter table public.official_document_dispatch_events enable row level security;
revoke all on table public.official_document_dispatch_events from public, anon, authenticated;
alter table public.official_document_archive_exports enable row level security;
revoke all on table public.official_document_archive_exports from public, anon, authenticated;
grant select, insert, update, delete on table public.inbound_document_attachments to service_role;
grant select, insert, update, delete on table public.internal_dispatches to service_role;
grant select, insert, update, delete on table public.internal_dispatch_recipients to service_role;
grant select, insert, update, delete on table public.internal_dispatch_replies to service_role;
grant select, insert, update, delete on table public.internal_dispatch_logs to service_role;
grant select, insert, update, delete on table public.official_document_stamp_positions to service_role;
grant select, insert, delete on table public.official_document_text_overlays to service_role;
grant select, insert, update, delete on table public.official_document_editor_assets to service_role;
grant select, insert, update, delete on table public.official_document_rejection_jobs to service_role;
grant select, insert on table public.official_document_editor_revisions to service_role;
grant select on table public.official_document_dispatch_events to service_role;
grant select on table public.official_document_archive_exports to service_role;
grant select on table public.official_workflow_delegations to service_role;

drop policy if exists "backend_only_deny_api_roles" on public.official_document_rejection_jobs;
create policy "backend_only_deny_api_roles" on public.official_document_rejection_jobs
  for all to anon, authenticated using (false) with check (false);
drop policy if exists "service_role_manages_rejection_jobs" on public.official_document_rejection_jobs;
create policy "service_role_manages_rejection_jobs" on public.official_document_rejection_jobs
  for all to service_role using (true) with check (true);

-- Reproduce the current backend-only posture for pre-existing workflow tables.
-- Older migrations granted browser roles direct table access; the production
-- architecture now routes these operations through the authenticated backend.
alter table public.audit_logs enable row level security;
alter table public.auth_sessions enable row level security;
alter table public.company_seal_files enable row level security;
alter table public.file_download_tokens enable row level security;
alter table public.file_objects enable row level security;
alter table public.finance_member_sync_nonces enable row level security;
alter table public.finance_member_sync_receipts enable row level security;
alter table public.official_document_approval_logs enable row level security;
alter table public.official_document_approval_steps enable row level security;
alter table public.official_document_files enable row level security;
alter table public.official_document_stamp_requests enable row level security;

revoke all on table public.audit_logs from public, anon, authenticated;
revoke all on table public.auth_sessions from public, anon, authenticated;
revoke all on table public.company_seal_files from public, anon, authenticated;
revoke all on table public.file_download_tokens from public, anon, authenticated;
revoke all on table public.file_objects from public, anon, authenticated;
revoke all on table public.finance_member_sync_nonces from public, anon, authenticated;
revoke all on table public.finance_member_sync_receipts from public, anon, authenticated;
revoke all on table public.official_document_approval_logs from public, anon, authenticated;
revoke all on table public.official_document_approval_steps from public, anon, authenticated;
revoke all on table public.official_document_files from public, anon, authenticated;
revoke all on table public.official_document_stamp_requests from public, anon, authenticated;

grant select, insert, update, delete on table public.audit_logs to service_role;
grant select, insert, update, delete on table public.auth_sessions to service_role;
grant select on table public.company_seal_files to service_role;
grant select, insert, update, delete on table public.file_download_tokens to service_role;
grant select, insert, update, delete on table public.file_objects to service_role;
grant select, insert, update, delete on table public.finance_member_sync_nonces to service_role;
grant select, insert, update, delete on table public.finance_member_sync_receipts to service_role;
grant select, insert, update, delete on table public.official_document_approval_logs to service_role;
grant select, insert, update, delete on table public.official_document_approval_steps to service_role;
grant select, insert, update, delete on table public.official_document_files to service_role;
grant select, insert, update, delete on table public.official_document_stamp_requests to service_role;

CREATE OR REPLACE FUNCTION public.edoc_company_seal_dimensions_are_valid(p_size_type text, p_pixel_width integer, p_pixel_height integer, p_source_aspect_ratio numeric, p_render_width_mm numeric, p_render_height_mm numeric, p_policy_version text, p_dimension_validated boolean)
 RETURNS boolean
 LANGUAGE sql
 IMMUTABLE
 SET search_path TO ''
AS $function$
  select coalesce(p_dimension_validated, false)
    and p_pixel_width > 0
    and p_pixel_height > 0
    and p_source_aspect_ratio > 0
    and p_render_width_mm > 0
    and p_render_height_mm > 0
    and abs(p_render_width_mm - p_render_height_mm) <= 0.01
    and least(p_pixel_width, p_pixel_height) >=
        ceil(greatest(p_render_width_mm, p_render_height_mm) / 25.4 * 250)
    and abs(p_source_aspect_ratio - p_pixel_width::numeric / p_pixel_height::numeric) <= 0.000001
    and abs(
      (p_pixel_width::numeric / p_pixel_height::numeric) /
      (p_render_width_mm / p_render_height_mm) - 1.0
    ) <= 0.01
    and (
      (
        p_policy_version = 'institution-seal-v1'
        and (
          (p_size_type = 'large_seal'
           and abs(p_render_width_mm - 30.0) <= 0.000001
           and abs(p_render_height_mm - 30.0) <= 0.000001)
          or
          (p_size_type = 'small_seal'
           and abs(p_render_width_mm - 18.0) <= 0.000001
           and abs(p_render_height_mm - 18.0) <= 0.000001)
        )
      )
      or
      (
        p_policy_version = 'institution-seal-v2-calibrated'
        and (
          (p_size_type = 'large_seal'
           and p_render_width_mm between 25.0 and 35.0
           and p_render_height_mm between 25.0 and 35.0)
          or
          (p_size_type = 'small_seal'
           and p_render_width_mm between 15.0 and 22.0
           and p_render_height_mm between 15.0 and 22.0)
        )
      )
    );
$function$;

CREATE OR REPLACE FUNCTION public.edoc_enforce_company_seal_position_dimensions()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare
  v_size_type text;
  v_file public.company_seal_files%rowtype;
  v_expected_width_pt numeric;
  v_expected_height_pt numeric;
begin
  select seal.seal_size_type into v_size_type
    from public.company_seals as seal
   where seal.id = new.seal_id;
  if not found then
    raise exception using errcode = 'P0002', message = 'seal_not_found';
  end if;

  if nullif(new.locked_seal_file_id, '') is null then
    if nullif(new.locked_seal_sha256, '') is not null
       or new.locked_render_width_pt is not null
       or new.locked_render_height_pt is not null
       or nullif(new.locked_dimension_policy_version, '') is not null then
      raise exception using errcode = '22023', message = 'seal_size_locked';
    end if;
    if not exists (
      select 1
        from public.official_document_stamp_requests as request
        join public.official_documents as document
          on document.id = request.document_id
        join public.company_seals as seal
          on seal.id = new.seal_id
         and seal.company_id = request.company_id
       where request.id = new.request_id
         and request.company_id = document.company_id
         and document.current_status = 'draft'
         and request.status = 'draft'
    ) then
      raise exception using errcode = '55000', message = 'official_seal_unbound_draft_only';
    end if;
    v_expected_width_pt := (
      case v_size_type when 'large_seal' then 30.0 when 'small_seal' then 18.0 else -1.0 end
    ) * 72.0 / 25.4;
    v_expected_height_pt := v_expected_width_pt;
    if abs(new.width - v_expected_width_pt) > 0.25
       or abs(new.height - v_expected_height_pt) > 0.25 then
      raise exception using errcode = '22023', message = 'seal_size_locked';
    end if;
    new.width := v_expected_width_pt;
    new.height := v_expected_height_pt;
    return new;
  end if;

  select file.* into v_file
    from public.company_seal_files as file
   where file.id = new.locked_seal_file_id
     and file.seal_id = new.seal_id;
  if not found
     or not public.edoc_company_seal_dimensions_are_valid(
       v_size_type, v_file.pixel_width, v_file.pixel_height,
       v_file.source_aspect_ratio, v_file.render_width_mm,
       v_file.render_height_mm, v_file.dimension_policy_version,
       v_file.dimension_validated
     )
     or not exists (
       select 1 from public.file_objects as object
       where object.id = v_file.file_object_id
         and lower(coalesce(object.scan_status, '')) in ('已通過', 'clean', 'passed')
     ) then
    raise exception using errcode = '55000', message = 'seal_file_dimension_validation_required';
  end if;

  v_expected_width_pt := v_file.render_width_mm * 72.0 / 25.4;
  v_expected_height_pt := v_file.render_height_mm * 72.0 / 25.4;
  if abs(new.width - v_expected_width_pt) > 0.25
     or abs(new.height - v_expected_height_pt) > 0.25
     or new.locked_seal_sha256 is distinct from v_file.file_hash
     or new.locked_render_width_pt is null
     or new.locked_render_height_pt is null
     or abs(new.locked_render_width_pt - v_expected_width_pt) > 0.25
     or abs(new.locked_render_height_pt - v_expected_height_pt) > 0.25
     or new.locked_dimension_policy_version is distinct from v_file.dimension_policy_version then
    raise exception using errcode = '22023', message = 'seal_size_locked';
  end if;
  new.width := v_expected_width_pt;
  new.height := v_expected_height_pt;
  new.locked_render_width_pt := v_expected_width_pt;
  new.locked_render_height_pt := v_expected_height_pt;
  new.locked_dimension_policy_version := v_file.dimension_policy_version;
  return new;
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_block_immutable_record_log_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog'
AS $function$
begin
  raise exception 'immutable_record_log' using errcode = '42501';
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_guard_canonical_record_delete()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog', 'public'
AS $function$
begin
  if old.legal_hold then
    raise exception 'record_delete_blocked_legal_hold' using errcode = '42501';
  end if;
  if old.retention_until is null or old.retention_until > now() then
    raise exception 'record_delete_blocked_retention' using errcode = '42501';
  end if;
  if old.disposition_status <> 'approved_for_destruction'
     or old.disposition_approved_by is null
     or old.disposition_approved_at is null then
    raise exception 'record_delete_blocked_disposition' using errcode = '42501';
  end if;
  return old;
end;
$function$;

CREATE OR REPLACE FUNCTION edoc_private.reject_official_editor_revision_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog', 'public'
AS $function$
begin
  raise exception 'editor_revision_immutable' using errcode = '55000';
end;
$function$;

CREATE OR REPLACE FUNCTION edoc_private.guard_official_workflow_delegation_insert()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_principal jsonb;
  v_delegate jsonb;
  v_creator jsonb;
begin
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'edoc:workflow-delegation:' || coalesce(new.company_id, '') || ':' || coalesce(new.principal_user_id, ''),
      0
    )
  );
  if nullif(pg_catalog.btrim(new.id), '') is null
     or nullif(pg_catalog.btrim(new.company_id), '') is null
     or nullif(pg_catalog.btrim(new.principal_user_id), '') is null
     or nullif(pg_catalog.btrim(new.delegate_user_id), '') is null
     or nullif(pg_catalog.btrim(new.created_by), '') is null then
    raise exception using errcode = '22023', message = 'official_workflow_delegation_invalid';
  end if;
  if new.principal_user_id = new.delegate_user_id then
    raise exception using errcode = '22023', message = 'official_workflow_delegation_self_forbidden';
  end if;
  if new.starts_at is null or new.ends_at is null or new.ends_at <= new.starts_at then
    raise exception using errcode = '22023', message = 'official_workflow_delegation_period_invalid';
  end if;
  if new.ends_at <= pg_catalog.clock_timestamp() then
    raise exception using errcode = '22023', message = 'official_workflow_delegation_period_expired';
  end if;
  if new.ends_at - new.starts_at > interval '180 days' then
    raise exception using errcode = '22023', message = 'official_workflow_delegation_period_too_long';
  end if;
  if pg_catalog.length(pg_catalog.btrim(coalesce(new.reason, ''))) < 2 then
    raise exception using errcode = '22023', message = 'official_workflow_delegation_reason_required';
  end if;

  v_principal := edoc_private.assert_finance_delegation_profile(new.principal_user_id);
  v_delegate := edoc_private.assert_finance_delegation_profile(new.delegate_user_id);
  v_creator := edoc_private.assert_finance_delegation_profile(new.created_by);
  if coalesce(v_principal->>'company_id', '') <> new.company_id
     or coalesce(v_delegate->>'company_id', '') <> new.company_id
     or coalesce(v_creator->>'company_id', '') <> new.company_id then
    raise exception using errcode = '42501', message = 'official_workflow_delegation_company_forbidden';
  end if;
  if (v_principal->>'logging_role_key', v_principal->>'role', v_principal->>'job_level')
       is distinct from
     (v_delegate->>'logging_role_key', v_delegate->>'role', v_delegate->>'job_level') then
    raise exception using errcode = '42501', message = 'official_workflow_delegation_role_qualification_mismatch';
  end if;
  if new.created_by <> new.principal_user_id then
    if new.created_by = new.delegate_user_id then
      raise exception using errcode = '42501', message = 'official_workflow_delegation_manager_self_assignment_forbidden';
    end if;
    if not edoc_private.finance_actor_has_delegation_manage(v_creator) then
      raise exception using errcode = '42501', message = 'official_workflow_delegation_manage_forbidden';
    end if;
  end if;
  if exists (
    select 1
      from public.official_workflow_delegations as delegation
     where delegation.company_id = new.company_id
       and delegation.principal_user_id = new.principal_user_id
       and delegation.status = 'active'
       and pg_catalog.tstzrange(delegation.starts_at, delegation.ends_at, '[)')
           && pg_catalog.tstzrange(new.starts_at, new.ends_at, '[)')
  ) then
    raise exception using errcode = '23P01', message = 'official_workflow_delegation_overlap';
  end if;

  new.status := 'active';
  new.reason := pg_catalog.left(pg_catalog.btrim(new.reason), 500);
  new.revoked_by := null;
  new.revoked_at := null;
  new.created_at := coalesce(new.created_at, pg_catalog.clock_timestamp());
  new.updated_at := pg_catalog.clock_timestamp();
  return new;
end;
$function$;

CREATE OR REPLACE FUNCTION edoc_private.guard_official_workflow_delegation_update()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_actor jsonb;
begin
  if new.id is distinct from old.id
     or new.company_id is distinct from old.company_id
     or new.principal_user_id is distinct from old.principal_user_id
     or new.delegate_user_id is distinct from old.delegate_user_id
     or new.starts_at is distinct from old.starts_at
     or new.ends_at is distinct from old.ends_at
     or new.reason is distinct from old.reason
     or new.created_by is distinct from old.created_by
     or new.created_at is distinct from old.created_at then
    raise exception using errcode = '42501', message = 'official_workflow_delegation_identity_immutable';
  end if;
  if old.status <> 'active' and new is distinct from old then
    raise exception using errcode = '42501', message = 'official_workflow_delegation_terminal';
  end if;
  if old.status = 'active' and new.status not in ('active', 'revoked', 'expired') then
    raise exception using errcode = '22023', message = 'official_workflow_delegation_status_invalid';
  end if;
  if new.status = 'revoked' then
    if new.revoked_by is null or new.revoked_at is null then
      raise exception using errcode = '22023', message = 'official_workflow_delegation_revocation_evidence_required';
    end if;
    v_actor := edoc_private.assert_finance_delegation_profile(new.revoked_by);
    if coalesce(v_actor->>'company_id', '') <> old.company_id then
      raise exception using errcode = '42501', message = 'official_workflow_delegation_company_forbidden';
    end if;
    if new.revoked_by <> old.principal_user_id
       and not edoc_private.finance_actor_has_delegation_manage(v_actor) then
      raise exception using errcode = '42501', message = 'official_workflow_delegation_manage_forbidden';
    end if;
  elsif new.revoked_by is not null or new.revoked_at is not null then
    raise exception using errcode = '22023', message = 'official_workflow_delegation_revocation_evidence_invalid';
  end if;
  return new;
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_claim_official_document_approval(p_document_id text, p_expected_step_id text, p_approver_user_id text, p_comment text DEFAULT '核准'::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_document public.official_documents%rowtype;
  v_step public.official_document_approval_steps%rowtype;
  v_next_step public.official_document_approval_steps%rowtype;
  v_expected_status text;
  v_next_status text;
  v_next_key text;
  v_transition text;
  v_approved_at text;
  v_updated_count integer;
begin
  if nullif(btrim(p_document_id), '') is null
     or nullif(btrim(p_expected_step_id), '') is null
     or nullif(btrim(p_approver_user_id), '') is null then
    raise exception using
      errcode = '22023',
      message = 'official_document_approval_claim_invalid';
  end if;

  -- Lock the document first and the expected step second.  Every invocation
  -- follows this order so concurrent retries serialize without deadlocking.
  select document.*
    into v_document
    from public.official_documents as document
   where document.id = p_document_id
   for update;

  if not found then
    raise exception using
      errcode = 'P0002',
      message = 'official_document_not_found';
  end if;

  select step.*
    into v_step
    from public.official_document_approval_steps as step
   where step.id = p_expected_step_id
     and step.document_id = p_document_id
   for update;

  if not found then
    raise exception using
      errcode = 'P0002',
      message = 'official_document_approval_step_not_found';
  end if;

  -- Authorization is checked again inside the privileged transaction.  The
  -- service-role caller cannot substitute a broad role or a different user.
  if v_step.approver_user_id is distinct from p_approver_user_id then
    raise exception using
      errcode = '42501',
      message = 'not_current_official_document_approver';
  end if;

  if v_step.step_key = 'applicant_manager'
     and v_document.applicant_id = p_approver_user_id then
    raise exception using
      errcode = '42501',
      message = 'applicant_cannot_self_approve_manager_step';
  end if;

  -- Monday launch has no caller-controlled no-stamp route.  Keeping this gate
  -- in the database prevents legacy or forged rows from bypassing Seal Vault.
  if v_document.requires_stamp is distinct from true then
    raise exception using
      errcode = '42501',
      message = 'official_document_stamp_required';
  end if;

  v_expected_status := case v_step.step_key
    when 'applicant_manager' then 'pending_applicant_manager'
    when 'department_head' then 'pending_department_head'
    when 'accounting_review' then 'pending_department_head'
    when 'ceo' then 'pending_ceo'
    when 'admin_director' then 'pending_admin_director'
    when 'general_affairs_review' then 'pending_general_affairs_review'
    else null
  end;

  -- The expected step id is the idempotency boundary.  A second caller that
  -- waited on the row lock sees the advanced document/approved step and gets a
  -- no-op response; it must not emit another notification or stamp.
  if v_step.status <> 'pending'
     or v_document.current_step is distinct from v_step.step_key
     or v_expected_status is null
     or v_document.current_status is distinct from v_expected_status
     or v_step.workflow_generation is distinct from (
       select pg_catalog.max(current_step.workflow_generation)
         from public.official_document_approval_steps as current_step
        where current_step.document_id = p_document_id
     ) then
    return jsonb_build_object(
      'claimed', false,
      'reason', 'official_document_approval_already_claimed',
      'document_id', v_document.id,
      'expected_step_id', v_step.id,
      'current_status', v_document.current_status,
      'current_step', coalesce(v_document.current_step, '')
    );
  end if;

  select next_step.*
    into v_next_step
    from public.official_document_approval_steps as next_step
   where next_step.document_id = p_document_id
     and next_step.workflow_generation = v_step.workflow_generation
     and next_step.step_order > v_step.step_order
     and next_step.status = 'pending'
   order by next_step.step_order
   limit 1;

  if not found then
    raise exception using
      errcode = 'P0001',
      message = 'official_document_next_step_missing';
  end if;

  if v_next_step.step_key = 'applicant_confirm' then
    if v_step.step_key not in ('general_affairs_review', 'ceo') then
      raise exception using
        errcode = 'P0001',
        message = 'official_document_invalid_final_approval_step';
    end if;
    v_transition := 'auto_stamp';
    v_next_status := 'approved';
    v_next_key := 'auto_stamp';
  else
    v_transition := 'next_step';
    v_next_status := case v_next_step.step_key
      when 'applicant_manager' then 'pending_applicant_manager'
      when 'department_head' then 'pending_department_head'
      when 'accounting_review' then 'pending_department_head'
      when 'ceo' then 'pending_ceo'
      when 'admin_director' then 'pending_admin_director'
      when 'general_affairs_review' then 'pending_general_affairs_review'
      else null
    end;
    v_next_key := v_next_step.step_key;
    if v_next_status is null then
      raise exception using
        errcode = 'P0001',
        message = 'official_document_next_step_invalid';
    end if;
  end if;

  v_approved_at := to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS');

  update public.official_document_approval_steps
     set status = 'approved',
         comment = coalesce(nullif(btrim(p_comment), ''), '核准'),
         approved_at = v_approved_at,
         updated_at = v_approved_at
   where id = v_step.id
     and document_id = v_document.id
     and status = 'pending'
     and approver_user_id = p_approver_user_id;
  get diagnostics v_updated_count = row_count;

  if v_updated_count <> 1 then
    return jsonb_build_object(
      'claimed', false,
      'reason', 'official_document_approval_already_claimed',
      'document_id', v_document.id,
      'expected_step_id', v_step.id,
      'current_status', v_document.current_status,
      'current_step', coalesce(v_document.current_step, '')
    );
  end if;

  update public.official_documents
     set current_status = v_next_status,
         current_step = v_next_key,
         updated_at = v_approved_at
   where id = v_document.id
     and current_status = v_expected_status
     and current_step = v_step.step_key;
  get diagnostics v_updated_count = row_count;

  if v_updated_count <> 1 then
    -- Raising rolls back the step update as part of this function call.
    raise exception using
      errcode = '40001',
      message = 'official_document_approval_claim_conflict';
  end if;

  return jsonb_build_object(
    'claimed', true,
    'document_id', v_document.id,
    'step_id', v_step.id,
    'step_key', v_step.step_key,
    'step_name', v_step.step_name,
    'approved_at', v_approved_at,
    'transition', v_transition,
    'document_status', v_next_status,
    'document_step', v_next_key,
    'next_step', jsonb_build_object(
      'id', v_next_step.id,
      'step_order', v_next_step.step_order,
      'step_key', v_next_step.step_key,
      'step_name', v_next_step.step_name,
      'approver_user_id', coalesce(v_next_step.approver_user_id, ''),
      'approver_name', coalesce(v_next_step.approver_name, ''),
      'approver_role', coalesce(v_next_step.approver_role, ''),
      'status', v_next_step.status
    )
  );
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_claim_official_document_rejection(p_document_id text, p_expected_step_id text, p_approver_user_id text, p_comment text DEFAULT '駁回'::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_document public.official_documents%rowtype;
  v_step public.official_document_approval_steps%rowtype;
  v_expected_status text;
  v_rejected_at text;
  v_updated_count integer;
  v_voided_step_count integer;
begin
  if nullif(btrim(p_document_id), '') is null
     or nullif(btrim(p_expected_step_id), '') is null
     or nullif(btrim(p_approver_user_id), '') is null then
    raise exception using
      errcode = '22023',
      message = 'official_document_rejection_claim_invalid';
  end if;

  -- Approval and rejection both lock document -> expected step.  Keeping this
  -- order identical serializes the two actions and avoids a lock-order cycle.
  select document.*
    into v_document
    from public.official_documents as document
   where document.id = p_document_id
   for update;

  if not found then
    raise exception using
      errcode = 'P0002',
      message = 'official_document_not_found';
  end if;

  select step.*
    into v_step
    from public.official_document_approval_steps as step
   where step.id = p_expected_step_id
     and step.document_id = p_document_id
   for update;

  if not found then
    raise exception using
      errcode = 'P0002',
      message = 'official_document_approval_step_not_found';
  end if;

  -- Authorization is repeated inside the privileged transaction.  Only the
  -- exact assigned Finance workflow actor may reject this expected step.
  if v_step.approver_user_id is distinct from p_approver_user_id then
    raise exception using
      errcode = '42501',
      message = 'not_current_official_document_approver';
  end if;

  if v_step.step_key = 'applicant_manager'
     and v_document.applicant_id = p_approver_user_id then
    raise exception using
      errcode = '42501',
      message = 'applicant_cannot_self_approve_manager_step';
  end if;

  v_expected_status := case v_step.step_key
    when 'applicant_manager' then 'pending_applicant_manager'
    when 'department_head' then 'pending_department_head'
    when 'accounting_review' then 'pending_department_head'
    when 'ceo' then 'pending_ceo'
    when 'admin_director' then 'pending_admin_director'
    when 'general_affairs_review' then 'pending_general_affairs_review'
    else null
  end;

  -- A caller that waited behind a successful approval/rejection receives a
  -- replay-safe no-op.  It must not emit a second log, notification, or clone.
  if v_step.status <> 'pending'
     or v_document.current_step is distinct from v_step.step_key
     or v_expected_status is null
     or v_document.current_status is distinct from v_expected_status
     or v_step.workflow_generation is distinct from (
       select pg_catalog.max(current_step.workflow_generation)
         from public.official_document_approval_steps as current_step
        where current_step.document_id = p_document_id
     ) then
    return jsonb_build_object(
      'claimed', false,
      'reason', 'official_document_approval_already_claimed',
      'document_id', v_document.id,
      'expected_step_id', v_step.id,
      'current_status', v_document.current_status,
      'current_step', coalesce(v_document.current_step, '')
    );
  end if;

  v_rejected_at := to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS');

  -- First compare-and-set the exact expected step.  There is one mutable
  -- generation in this table at a time; historical actor assignments and
  -- decisions remain in their original generations and immutable logs.
  update public.official_document_approval_steps
     set status = 'skipped',
         comment = '駁回：'
           || coalesce(nullif(btrim(p_comment), ''), '駁回')
           || '；舊簽核已作廢，重新送簽必須從第一關開始。',
         approved_at = v_rejected_at,
         updated_at = v_rejected_at
   where id = v_step.id
     and document_id = v_document.id
     and status = 'pending'
     and approver_user_id = p_approver_user_id;
  get diagnostics v_updated_count = row_count;

  if v_updated_count <> 1 then
    return jsonb_build_object(
      'claimed', false,
      'reason', 'official_document_approval_already_claimed',
      'document_id', v_document.id,
      'expected_step_id', v_step.id,
      'current_status', v_document.current_status,
      'current_step', coalesce(v_document.current_step, '')
    );
  end if;

  -- Explicitly void every other mutable step in the same generation.  A later
  -- resubmission deletes this all-skipped set and constructs fresh step ids.
  update public.official_document_approval_steps
     set status = 'skipped',
         comment = '舊簽核已因退回作廢；重新送簽必須從第一關開始。',
         updated_at = v_rejected_at
   where document_id = v_document.id
     and workflow_generation = v_step.workflow_generation
     and id <> v_step.id
     and status <> 'skipped';
  get diagnostics v_voided_step_count = row_count;
  v_voided_step_count := v_voided_step_count + 1;

  update public.official_documents
     set current_status = 'rejected',
         current_step = 'applicant',
         updated_at = v_rejected_at
   where id = v_document.id
     and current_status = v_expected_status
     and current_step = v_step.step_key;
  get diagnostics v_updated_count = row_count;

  if v_updated_count <> 1 then
    -- Raising rolls back the whole generation update in this function call.
    raise exception using
      errcode = '40001',
      message = 'official_document_rejection_claim_conflict';
  end if;

  return jsonb_build_object(
    'claimed', true,
    'document_id', v_document.id,
    'step_id', v_step.id,
    'step_key', v_step.step_key,
    'step_name', v_step.step_name,
    'rejected_at', v_rejected_at,
    'document_status', 'rejected',
    'document_step', 'applicant',
    'voided_step_count', v_voided_step_count
  );
end;
$function$;

CREATE OR REPLACE FUNCTION edoc_private.assert_official_decision_actor(p_company_id text, p_principal_user_id text, p_decision_actor_user_id text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_now timestamptz := pg_catalog.clock_timestamp();
begin
  if nullif(pg_catalog.btrim(coalesce(p_company_id, '')), '') is null
     or nullif(pg_catalog.btrim(coalesce(p_principal_user_id, '')), '') is null
     or nullif(pg_catalog.btrim(coalesce(p_decision_actor_user_id, '')), '') is null then
    raise exception using errcode = '22023', message = 'official_document_decision_actor_invalid';
  end if;

  if not exists (
    select 1 from public.users as principal
     where principal.id = p_principal_user_id
       and principal.company_id = p_company_id
       and principal.status = '啟用'
  ) or not exists (
    select 1 from public.users as actor
     where actor.id = p_decision_actor_user_id
       and actor.company_id = p_company_id
       and actor.status = '啟用'
  ) then
    raise exception using errcode = '42501', message = 'official_document_decision_actor_company_forbidden';
  end if;

  if p_decision_actor_user_id <> p_principal_user_id
     and not exists (
       select 1
         from public.official_workflow_delegations as delegation
        where delegation.company_id = p_company_id
          and delegation.principal_user_id = p_principal_user_id
          and delegation.delegate_user_id = p_decision_actor_user_id
          and delegation.status = 'active'
          and delegation.starts_at <= v_now
          and delegation.ends_at > v_now
     ) then
    raise exception using errcode = '42501', message = 'official_workflow_delegation_not_active';
  end if;
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_claim_official_document_approval_v2(p_document_id text, p_expected_step_id text, p_approver_user_id text, p_decision_actor_user_id text, p_comment text, p_decision_evidence jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_document public.official_documents%rowtype;
  v_step public.official_document_approval_steps%rowtype;
  v_result jsonb;
  v_ack jsonb;
  v_prepared text;
  v_manifest text;
  v_expected_prepared text := '';
  v_expected_manifest text := '';
begin
  if pg_catalog.jsonb_typeof(coalesce(p_decision_evidence, '{}'::jsonb)) <> 'object' then
    raise exception using errcode = '22023', message = 'official_document_decision_evidence_invalid';
  end if;

  -- Keep the same document -> step lock order as the original RPC.
  select document.* into v_document
    from public.official_documents as document
   where document.id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_not_found';
  end if;

  select step.* into v_step
    from public.official_document_approval_steps as step
   where step.id = p_expected_step_id
     and step.document_id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_approval_step_not_found';
  end if;
  if v_step.approver_user_id is distinct from p_approver_user_id then
    raise exception using errcode = '42501', message = 'not_current_official_document_approver';
  end if;

  perform edoc_private.assert_official_decision_actor(
    v_document.company_id,
    p_approver_user_id,
    p_decision_actor_user_id
  );

  if coalesce(p_decision_evidence->>'expected_step_id', '') <> p_expected_step_id
     or coalesce(p_decision_evidence->>'principal_actor_id', '') <> p_approver_user_id
     or coalesce(p_decision_evidence->>'decision_actor_user_id', '') <> p_decision_actor_user_id then
    raise exception using errcode = '22023', message = 'official_document_decision_evidence_actor_mismatch';
  end if;

  v_ack := p_decision_evidence->'review_acknowledgements';
  if pg_catalog.jsonb_typeof(coalesce(v_ack, 'null'::jsonb)) <> 'object'
     or coalesce(v_ack->>'original_reviewed', '') <> 'true'
     or coalesce(v_ack->>'edited_version_reviewed', '') <> 'true'
     or coalesce(v_ack->>'attachments_reviewed', '') <> 'true' then
    raise exception using errcode = '22023', message = 'official_document_review_acknowledgements_required';
  end if;

  v_prepared := pg_catalog.lower(coalesce(p_decision_evidence->>'prepared_sha256', ''));
  v_manifest := pg_catalog.lower(coalesce(p_decision_evidence->>'manifest_sha256', ''));
  if (v_prepared = '') is distinct from (v_manifest = '')
     or (v_prepared <> '' and (
       v_prepared !~ '^[0-9a-f]{64}$' or v_manifest !~ '^[0-9a-f]{64}$'
     )) then
    raise exception using errcode = '22023', message = 'official_document_review_hashes_invalid';
  end if;

  select
    pg_catalog.lower(coalesce(request.prepared_sha256, '')),
    pg_catalog.lower(coalesce(request.editor_manifest_sha256, ''))
    into v_expected_prepared, v_expected_manifest
    from public.official_document_stamp_requests as request
   where request.document_id = p_document_id
   order by request.created_at desc, request.id desc
   limit 1;
  if not found then
    v_expected_prepared := '';
    v_expected_manifest := '';
  end if;
  if (v_expected_prepared = '') is distinct from (v_expected_manifest = '') then
    raise exception using errcode = '22023', message = 'official_document_locked_hashes_incomplete';
  end if;
  if v_prepared is distinct from v_expected_prepared
     or v_manifest is distinct from v_expected_manifest then
    raise exception using errcode = '22023', message = 'official_document_review_hash_mismatch';
  end if;

  if v_step.step_key in ('ceo', 'admin_director', 'general_affairs_review')
     and nullif(pg_catalog.btrim(coalesce(p_comment, '')), '') is null then
    raise exception using errcode = '22023', message = 'official_document_approval_comment_required';
  end if;

  v_result := public.edoc_claim_official_document_approval(
    p_document_id,
    p_expected_step_id,
    p_approver_user_id,
    p_comment
  );

  if coalesce((v_result->>'claimed')::boolean, false) then
    update public.official_document_approval_steps
       set decision_actor_user_id = p_decision_actor_user_id,
           decision_evidence_json = p_decision_evidence
     where id = p_expected_step_id
       and document_id = p_document_id;
    if not found then
      raise exception using errcode = '40001', message = 'official_document_approval_evidence_conflict';
    end if;

    insert into public.official_document_approval_logs (
      id, document_id, step_id, actor_id, actor_name, principal_actor_id,
      action, comment, decision_evidence_json, ip_address, user_agent, created_at
    ) values (
      'ODLOG-APPROVE-' || pg_catalog.md5(p_document_id || ':' || p_expected_step_id),
      p_document_id, p_expected_step_id, p_decision_actor_user_id,
      coalesce((select u.name from public.users as u where u.id = p_decision_actor_user_id), p_decision_actor_user_id),
      p_approver_user_id, 'approve', coalesce(p_comment, ''), p_decision_evidence,
      '', '', pg_catalog.to_char(pg_catalog.clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS')
    );

    insert into public.audit_logs (
      id, actor, actor_user_id, action, target_type, target_id, detail,
      event_type, result, module_code, resource_type, resource_id, metadata_json, created_at
    ) values (
      'AUD-APPROVE-' || pg_catalog.md5(p_document_id || ':' || p_expected_step_id),
      p_decision_actor_user_id, p_decision_actor_user_id, 'approve',
      'official_documents', p_document_id, 'step_id=' || p_expected_step_id,
      'approve', 'success', 'official_documents', 'official_documents', p_document_id,
      pg_catalog.jsonb_build_object(
        'principal_actor_id', p_approver_user_id,
        'decision_evidence', p_decision_evidence
      )::text,
      pg_catalog.to_char(pg_catalog.clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS')
    );

    if v_result->>'transition' = 'next_step' then
      if not exists (
        select 1
          from public.users as next_actor
         where next_actor.id = v_result#>>'{next_step,approver_user_id}'
           and next_actor.status = '啟用'
           and next_actor.company_id = v_document.company_id
           and nullif(pg_catalog.btrim(coalesce(next_actor.email, '')), '') is not null
      ) then
        raise exception using errcode = '22023', message = 'notification_exact_target_required';
      end if;
      insert into public.notifications (
        id, type, title, target_role, target_user_id, target_company_id, target_email, channel,
        status, priority, source, action_url, body, created_at
      ) values (
        'NOTIF-APPROVE-' || pg_catalog.md5(p_document_id || ':' || p_expected_step_id),
        '發文簽核', v_document.title || ' 待' || coalesce(v_result#>>'{next_step,step_name}', '下一關') || '簽核',
        coalesce(v_result#>>'{next_step,approver_role}', ''),
        nullif(v_result#>>'{next_step,approver_user_id}', ''),
        v_document.company_id,
        (select u.email from public.users as u where u.id = v_result#>>'{next_step,approver_user_id}' and u.status = '啟用'),
        '系統站內通知', '未讀', '高', p_document_id,
        '/official-documents/' || p_document_id,
        v_step.step_name || '已核准，請接續處理。', pg_catalog.clock_timestamp()
      );
    end if;
  end if;
  return v_result;
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_claim_official_document_rejection_v2(p_document_id text, p_expected_step_id text, p_approver_user_id text, p_decision_actor_user_id text, p_comment text, p_decision_evidence jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_document public.official_documents%rowtype;
  v_step public.official_document_approval_steps%rowtype;
  v_result jsonb;
  v_evidence jsonb;
  v_category text;
  v_missing jsonb;
  v_due_text text;
  v_due_date date;
begin
  if pg_catalog.jsonb_typeof(coalesce(p_decision_evidence, '{}'::jsonb)) <> 'object' then
    raise exception using errcode = '22023', message = 'official_document_decision_evidence_invalid';
  end if;

  select document.* into v_document
    from public.official_documents as document
   where document.id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_not_found';
  end if;

  select step.* into v_step
    from public.official_document_approval_steps as step
   where step.id = p_expected_step_id
     and step.document_id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_approval_step_not_found';
  end if;
  if v_step.approver_user_id is distinct from p_approver_user_id then
    raise exception using errcode = '42501', message = 'not_current_official_document_approver';
  end if;

  perform edoc_private.assert_official_decision_actor(
    v_document.company_id,
    p_approver_user_id,
    p_decision_actor_user_id
  );

  if pg_catalog.length(pg_catalog.btrim(coalesce(p_comment, ''))) < 6 then
    raise exception using errcode = '22023', message = 'official_document_rejection_comment_too_short';
  end if;

  v_category := pg_catalog.btrim(coalesce(p_decision_evidence->>'reason_category', ''));
  if v_category = '' or pg_catalog.length(v_category) > 80 then
    raise exception using errcode = '22023', message = 'official_document_rejection_reason_category_required';
  end if;

  v_missing := coalesce(p_decision_evidence->'missing_items', '[]'::jsonb);
  if pg_catalog.jsonb_typeof(v_missing) <> 'array'
     or pg_catalog.jsonb_array_length(v_missing) > 50
     or exists (
       select 1
         from pg_catalog.jsonb_array_elements(v_missing) as item(value)
        where pg_catalog.jsonb_typeof(item.value) <> 'string'
           or pg_catalog.length(pg_catalog.btrim(item.value #>> '{}')) = 0
           or pg_catalog.length(item.value #>> '{}') > 240
     ) then
    raise exception using errcode = '22023', message = 'official_document_rejection_missing_items_invalid';
  end if;

  v_due_text := pg_catalog.btrim(coalesce(p_decision_evidence->>'correction_due_date', ''));
  if v_due_text <> '' then
    if v_due_text !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' then
      raise exception using errcode = '22023', message = 'official_document_correction_due_date_invalid';
    end if;
    begin
      v_due_date := v_due_text::date;
    exception when others then
      raise exception using errcode = '22023', message = 'official_document_correction_due_date_invalid';
    end;
    if pg_catalog.to_char(v_due_date, 'YYYY-MM-DD') <> v_due_text then
      raise exception using errcode = '22023', message = 'official_document_correction_due_date_invalid';
    end if;
    if v_due_date < current_date then
      raise exception using errcode = '22023', message = 'official_document_correction_due_date_in_past';
    end if;
  end if;

  v_evidence := p_decision_evidence || pg_catalog.jsonb_build_object(
    'expected_step_id', p_expected_step_id,
    'principal_actor_id', p_approver_user_id,
    'decision_actor_user_id', p_decision_actor_user_id
  );

  v_result := public.edoc_claim_official_document_rejection(
    p_document_id,
    p_expected_step_id,
    p_approver_user_id,
    p_comment
  );

  if coalesce((v_result->>'claimed')::boolean, false) then
    update public.official_document_approval_steps
       set decision_actor_user_id = p_decision_actor_user_id,
           decision_evidence_json = v_evidence
     where id = p_expected_step_id
       and document_id = p_document_id;
    if not found then
      raise exception using errcode = '40001', message = 'official_document_rejection_evidence_conflict';
    end if;

    update public.official_documents
       set correction_reason_category = v_category,
           correction_missing_items_json = v_missing,
           correction_due_at = case when v_due_date is null then null else v_due_date::timestamptz end,
           correction_requested_at = pg_catalog.clock_timestamp(),
           correction_resubmitted_at = null
     where id = p_document_id;
    if not found then
      raise exception using errcode = '40001', message = 'official_document_rejection_correction_conflict';
    end if;

    insert into public.official_document_approval_logs (
      id, document_id, step_id, actor_id, actor_name, principal_actor_id,
      action, comment, decision_evidence_json, ip_address, user_agent, created_at
    ) values (
      'ODLOG-REJECT-' || pg_catalog.md5(p_document_id || ':' || p_expected_step_id),
      p_document_id, p_expected_step_id, p_decision_actor_user_id,
      coalesce((select u.name from public.users as u where u.id = p_decision_actor_user_id), p_decision_actor_user_id),
      p_approver_user_id, 'reject', p_comment, v_evidence,
      '', '', pg_catalog.to_char(pg_catalog.clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS')
    );

    insert into public.audit_logs (
      id, actor, actor_user_id, action, target_type, target_id, detail,
      event_type, result, module_code, resource_type, resource_id, metadata_json, created_at
    ) values (
      'AUD-REJECT-' || pg_catalog.md5(p_document_id || ':' || p_expected_step_id),
      p_decision_actor_user_id, p_decision_actor_user_id, 'reject',
      'official_documents', p_document_id, 'step_id=' || p_expected_step_id,
      'reject', 'success', 'official_documents', 'official_documents', p_document_id,
      pg_catalog.jsonb_build_object(
        'principal_actor_id', p_approver_user_id,
        'decision_evidence', v_evidence
      )::text,
      pg_catalog.to_char(pg_catalog.clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS')
    );

    if not exists (
      select 1
        from public.users as applicant
       where applicant.id = v_document.applicant_id
         and applicant.status = '啟用'
         and applicant.company_id = v_document.company_id
         and nullif(pg_catalog.btrim(coalesce(applicant.email, '')), '') is not null
    ) then
      raise exception using errcode = '22023', message = 'notification_exact_target_required';
    end if;
    insert into public.notifications (
      id, type, title, target_role, target_user_id, target_company_id, target_email, channel,
      status, priority, source, action_url, body, created_at
    ) values (
      'NOTIF-REJECT-' || pg_catalog.md5(p_document_id || ':' || p_expected_step_id),
      '發文退回', v_document.title || ' 已退回補正',
      coalesce((select u.role from public.users as u where u.id = v_document.applicant_id), '員工'),
      v_document.applicant_id,
      v_document.company_id,
      (select u.email from public.users as u where u.id = v_document.applicant_id and u.status = '啟用'),
      '系統站內通知', '未讀', '高', p_document_id,
      '/official-documents/' || p_document_id, p_comment, pg_catalog.clock_timestamp()
    );

    insert into public.official_document_rejection_jobs (
      id, document_id, expected_step_id, source_revision_id, status, created_at
    )
    select
      'ODREJ-' || pg_catalog.md5(p_document_id || ':' || p_expected_step_id),
      p_document_id, p_expected_step_id, request.locked_editor_revision_id,
      'pending', pg_catalog.clock_timestamp()
      from public.official_document_stamp_requests as request
     where request.document_id = p_document_id
       and request.locked_editor_revision_id is not null
     order by request.created_at desc, request.id desc
     limit 1;
  end if;
  return v_result;
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_create_official_workflow_delegation(p_id text, p_company_id text, p_principal_user_id text, p_delegate_user_id text, p_starts_at timestamp with time zone, p_ends_at timestamp with time zone, p_reason text, p_created_by text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_delegation public.official_workflow_delegations%rowtype;
begin
  -- The trigger obtains the same transaction-scoped lock and repeats all
  -- validation, so direct SQL inserts cannot bypass this transaction boundary.
  insert into public.official_workflow_delegations (
    id, company_id, principal_user_id, delegate_user_id, starts_at, ends_at,
    status, reason, created_by, created_at, updated_at
  ) values (
    p_id, p_company_id, p_principal_user_id, p_delegate_user_id,
    p_starts_at, p_ends_at, 'active', p_reason, p_created_by,
    pg_catalog.clock_timestamp(), pg_catalog.clock_timestamp()
  )
  returning * into v_delegation;

  -- Permission change and its audit-chain row are one transaction.  If the
  -- audit insert or its hash trigger fails, the delegation never becomes
  -- active.
  insert into public.audit_logs (
    id, actor, actor_user_id, action, target_type, target_id, detail,
    event_type, result, module_code, reason, created_at
  ) values (
    'AUD-' || pg_catalog.replace(gen_random_uuid()::text, '-', ''),
    p_created_by, p_created_by, '建立簽核代理',
    'official_workflow_delegation', p_id,
    'principal=' || p_principal_user_id || ';delegate=' || p_delegate_user_id
      || ';period=' || p_starts_at::text || '..' || p_ends_at::text,
    'permission_change', 'success', 'official_documents',
    pg_catalog.left(pg_catalog.btrim(p_reason), 500),
    pg_catalog.to_char(pg_catalog.clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS')
  );

  return pg_catalog.to_jsonb(v_delegation);
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_revoke_official_workflow_delegation(p_delegation_id text, p_revoked_by text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_delegation public.official_workflow_delegations%rowtype;
  v_actor jsonb;
begin
  select delegation.* into v_delegation
    from public.official_workflow_delegations as delegation
   where delegation.id = p_delegation_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_workflow_delegation_not_found';
  end if;
  v_actor := edoc_private.assert_finance_delegation_profile(p_revoked_by);
  if coalesce(v_actor->>'company_id', '') <> v_delegation.company_id then
    raise exception using errcode = '42501', message = 'official_workflow_delegation_company_forbidden';
  end if;
  if p_revoked_by <> v_delegation.principal_user_id
     and not edoc_private.finance_actor_has_delegation_manage(v_actor) then
    raise exception using errcode = '42501', message = 'official_workflow_delegation_manage_forbidden';
  end if;
  if v_delegation.status <> 'active' then
    return pg_catalog.to_jsonb(v_delegation)
      || pg_catalog.jsonb_build_object('revoked', false, 'reason', 'already_terminal');
  end if;

  update public.official_workflow_delegations
     set status = 'revoked', revoked_by = p_revoked_by,
         revoked_at = pg_catalog.clock_timestamp(), updated_at = pg_catalog.clock_timestamp()
   where id = p_delegation_id and status = 'active'
  returning * into v_delegation;
  if not found then
    raise exception using errcode = '40001', message = 'official_workflow_delegation_revoke_conflict';
  end if;
  insert into public.audit_logs (
    id, actor, actor_user_id, action, target_type, target_id, detail,
    event_type, result, module_code, created_at
  ) values (
    'AUD-' || pg_catalog.replace(extensions.gen_random_uuid()::text, '-', ''),
    p_revoked_by, p_revoked_by, '撤銷簽核代理',
    'official_workflow_delegation', p_delegation_id, 'delegation_revoked',
    'permission_change', 'success', 'official_documents',
    pg_catalog.to_char(pg_catalog.clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS')
  );
  return pg_catalog.to_jsonb(v_delegation) || pg_catalog.jsonb_build_object('revoked', true);
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_create_company_seal_file_version(p_file_id text, p_seal_file_id text, p_seal_id text, p_storage_key text, p_file_name text, p_mime_type text, p_file_size bigint, p_sha256 text, p_pixel_width integer, p_pixel_height integer, p_source_aspect_ratio numeric, p_render_width_mm numeric, p_render_height_mm numeric, p_dimension_policy_version text, p_actor text, p_scan_engine text, p_scan_signature text, p_usage_log_id text, p_audit_log_id text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_seal public.company_seals%rowtype;
  v_created public.company_seal_files%rowtype;
  v_next_version integer;
  v_timestamp_text text := to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS');
  v_storage_prefix text := 'seal-vault/seals/' || p_seal_id || '/SEAL-VAULT/';
begin
  if nullif(btrim(p_file_id), '') is null
     or nullif(btrim(p_seal_file_id), '') is null
     or nullif(btrim(p_seal_id), '') is null
     or nullif(btrim(p_storage_key), '') is null
     or nullif(btrim(p_file_name), '') is null
     or nullif(btrim(p_actor), '') is null
     or p_mime_type not in ('image/png', 'image/jpeg', 'image/webp')
     or p_file_size < 1 or p_file_size > 3145728
     or p_sha256 !~ '^[0-9A-Fa-f]{64}$'
     or left(p_storage_key, length(v_storage_prefix)) <> v_storage_prefix
     or p_dimension_policy_version <> 'institution-seal-v2-calibrated' then
    raise exception using errcode = '22023', message = 'seal_file_metadata_invalid';
  end if;

  select seal.* into v_seal
    from public.company_seals as seal
   where seal.id = p_seal_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'seal_not_found';
  end if;
  if v_seal.is_active is distinct from true then
    raise exception using errcode = '55000', message = 'inactive_seal_cannot_upload_new_file';
  end if;
  if not public.edoc_company_seal_dimensions_are_valid(
    v_seal.seal_size_type, p_pixel_width, p_pixel_height,
    p_source_aspect_ratio, p_render_width_mm, p_render_height_mm,
    p_dimension_policy_version, true
  ) then
    raise exception using errcode = '22023', message = 'seal_file_dimension_metadata_invalid';
  end if;

  select coalesce(max(file.version), 0) + 1 into v_next_version
    from public.company_seal_files as file where file.seal_id = p_seal_id;

  insert into public.file_objects (
    id, document_id, file_name, storage_key, bucket, storage_provider,
    mime_type, size_bytes, sha256, encrypted_sha256, encryption_status,
    encryption_alg, encryption_key_id, scan_status, scan_engine,
    quarantine_reason, signed_url_expires_at, last_scan_at, last_download_at,
    version_label, purpose, created_by, created_at
  ) values (
    p_file_id, 'SEAL-VAULT', p_file_name, p_storage_key,
    'edoc-seal-vault', 'seal-vault', p_mime_type, p_file_size, p_sha256,
    '', '由物件儲存服務控管', '', '', '已通過', left(coalesce(p_scan_engine, ''), 200),
    '', null, clock_timestamp(), null, 'seal-v' || v_next_version,
    'seal-vault-original', p_actor, v_timestamp_text
  );

  update public.company_seal_files set is_current = false
   where seal_id = p_seal_id and is_current = true;
  insert into public.company_seal_files (
    id, seal_id, file_object_id, file_storage_key, file_name,
    file_mime_type, file_size, file_hash, pixel_width, pixel_height,
    source_aspect_ratio, render_width_mm, render_height_mm,
    dimension_policy_version, dimension_validated, version, is_current,
    uploaded_by, uploaded_at
  ) values (
    p_seal_file_id, p_seal_id, p_file_id, p_storage_key, p_file_name,
    p_mime_type, p_file_size, p_sha256, p_pixel_width, p_pixel_height,
    p_source_aspect_ratio, p_render_width_mm, p_render_height_mm,
    p_dimension_policy_version, true, v_next_version, true,
    p_actor, v_timestamp_text
  ) returning * into v_created;

  insert into public.seal_usage_logs (id, seal_id, action, actor_id, detail, created_at)
  values (
    p_usage_log_id, p_seal_id, 'upload_seal', p_actor,
    'version=' || v_next_version || ' hash=' || p_sha256 ||
      ' pixels=' || p_pixel_width || 'x' || p_pixel_height ||
      ' render_mm=' || p_render_width_mm || 'x' || p_render_height_mm ||
      ' policy=' || p_dimension_policy_version ||
      ' av=' || left(coalesce(p_scan_signature, ''), 120),
    v_timestamp_text
  );
  insert into public.audit_logs (id, actor, action, target_type, target_id, detail, created_at)
  values (
    p_audit_log_id, p_actor, 'upload_seal', 'seal_usage', p_seal_id,
    'version=' || v_next_version || ' hash=' || p_sha256 ||
      ' pixels=' || p_pixel_width || 'x' || p_pixel_height ||
      ' render_mm=' || p_render_width_mm || 'x' || p_render_height_mm ||
      ' policy=' || p_dimension_policy_version,
    v_timestamp_text
  );
  return jsonb_build_object('file', to_jsonb(v_created));
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_set_current_company_seal_file(p_file_id text, p_actor text, p_usage_log_id text, p_audit_log_id text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_target public.company_seal_files%rowtype;
  v_seal public.company_seals%rowtype;
  v_file_object public.file_objects%rowtype;
  v_timestamp_text text := to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS');
begin
  select target.* into v_target
    from public.company_seal_files as target
   where target.id = p_file_id;
  if not found then
    raise exception using errcode = 'P0002', message = 'seal_file_not_found';
  end if;
  select seal.* into v_seal
    from public.company_seals as seal
   where seal.id = v_target.seal_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'seal_not_found';
  end if;
  select target.* into v_target
    from public.company_seal_files as target
   where target.id = p_file_id and target.seal_id = v_seal.id
   for update;
  select object.* into v_file_object
    from public.file_objects as object
   where object.id = v_target.file_object_id;
  if not found
     or lower(coalesce(v_file_object.scan_status, '')) not in ('已通過', 'clean', 'passed') then
    raise exception using errcode = '55000', message = 'seal_file_antivirus_required';
  end if;
  if v_target.dimension_policy_version <> 'institution-seal-v2-calibrated'
     or not public.edoc_company_seal_dimensions_are_valid(
       v_seal.seal_size_type, v_target.pixel_width, v_target.pixel_height,
       v_target.source_aspect_ratio, v_target.render_width_mm,
       v_target.render_height_mm, v_target.dimension_policy_version,
       v_target.dimension_validated
     ) then
    raise exception using errcode = '55000', message = 'seal_file_dimension_validation_required';
  end if;

  update public.company_seal_files set is_current = false
   where seal_id = v_target.seal_id and is_current = true;
  update public.company_seal_files set is_current = true where id = p_file_id;
  insert into public.seal_usage_logs (id, seal_id, action, actor_id, detail, created_at)
  values (
    p_usage_log_id, v_target.seal_id, 'set_current_seal_file', p_actor,
    'version=' || v_target.version || ' render_mm=' ||
      v_target.render_width_mm || 'x' || v_target.render_height_mm,
    v_timestamp_text
  );
  insert into public.audit_logs (id, actor, action, target_type, target_id, detail, created_at)
  values (
    p_audit_log_id, p_actor, 'set_current_seal_file', 'seal_usage', v_target.seal_id,
    'version=' || v_target.version || ' render_mm=' ||
      v_target.render_width_mm || 'x' || v_target.render_height_mm,
    v_timestamp_text
  );
  v_target.is_current := true;
  return jsonb_build_object('file', to_jsonb(v_target), 'seal_id', v_target.seal_id);
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_create_official_document_dispatch_record(p_document_id text, p_actor_user_id text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_document public.official_documents%rowtype;
  v_record public.official_document_dispatch_records%rowtype;
  v_owner_type text;
  v_owner_user_id text;
  v_dispatch_status text;
  v_now timestamptz := pg_catalog.clock_timestamp();
  v_created boolean := false;
begin
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('edoc:official-dispatch:' || p_document_id, 0)
  );

  select document.* into v_document
    from public.official_documents as document
   where document.id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_not_found';
  end if;

  if nullif(pg_catalog.btrim(coalesce(p_actor_user_id, '')), '') is null then
    raise exception using errcode = '22023', message = 'official_dispatch_actor_required';
  end if;
  if p_actor_user_id <> 'system' and not exists (
    select 1
      from public.users as actor
     where actor.id = p_actor_user_id
       and actor.status = '啟用'
       and actor.company_id = v_document.company_id
  ) then
    raise exception using errcode = '42501', message = 'official_dispatch_actor_forbidden';
  end if;

  v_owner_type := case v_document.dispatch_method
    when 'no_dispatch_required' then 'system'
    when 'return_to_applicant_for_manual_send' then 'applicant'
    when 'electronic_official_document_by_general_affairs' then 'general_affairs'
    when 'email_by_general_affairs' then 'general_affairs'
    when 'physical_mail_by_general_affairs' then 'general_affairs'
    else null
  end;
  if v_owner_type is null then
    raise exception using errcode = '22023', message = 'invalid_official_dispatch_method';
  end if;

  if v_owner_type = 'general_affairs' then
    select step.approver_user_id into v_owner_user_id
      from public.official_document_approval_steps as step
     where step.document_id = v_document.id
       and step.step_key = 'general_affairs_review'
       and step.status = 'approved'
     order by step.step_order desc, step.id desc
     limit 1;
    if nullif(pg_catalog.btrim(coalesce(v_owner_user_id, '')), '') is null then
      raise exception using errcode = '22023', message = 'official_dispatch_owner_unresolved:general_affairs_review';
    end if;
  elsif v_owner_type = 'applicant' then
    v_owner_user_id := v_document.applicant_id;
  else
    v_owner_user_id := 'system';
  end if;
  v_dispatch_status := case when v_owner_type = 'system' then 'dispatched' else 'pending' end;

  select record.* into v_record
    from public.official_document_dispatch_records as record
   where record.document_id = v_document.id
   for update;

  if found then
    if v_record.dispatch_method is distinct from v_document.dispatch_method
       or v_record.dispatch_owner_type is distinct from v_owner_type
       or v_record.dispatch_owner_user_id is distinct from v_owner_user_id then
      raise exception using errcode = '23505', message = 'official_dispatch_route_conflict';
    end if;
  else
    insert into public.official_document_dispatch_records (
      id, document_id, dispatch_method, dispatch_owner_type,
      dispatch_owner_user_id, dispatch_status, recipient, created_by,
      created_at, updated_at, completed_at
    ) values (
      'ODDISP-' || pg_catalog.upper(pg_catalog.substr(pg_catalog.md5(v_document.id), 1, 24)),
      v_document.id,
      v_document.dispatch_method,
      v_owner_type,
      v_owner_user_id,
      v_dispatch_status,
      v_document.recipient,
      coalesce(nullif(pg_catalog.btrim(p_actor_user_id), ''), 'system'),
      pg_catalog.to_char(v_now, 'YYYY-MM-DD HH24:MI:SS'),
      pg_catalog.to_char(v_now, 'YYYY-MM-DD HH24:MI:SS'),
      case when v_owner_type = 'system' then pg_catalog.to_char(v_now, 'YYYY-MM-DD HH24:MI:SS') else null end
    ) returning * into v_record;
    v_created := true;
  end if;

  return pg_catalog.jsonb_build_object(
    'created', v_created,
    'document_id', v_document.id,
    'dispatch_record_id', v_record.id,
    'record', pg_catalog.to_jsonb(v_record)
  );
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_complete_official_document_dispatch(p_document_id text, p_dispatch_record_id text, p_actor_user_id text, p_external_official_document_number text DEFAULT NULL::text, p_dispatch_date text DEFAULT NULL::text, p_recipient text DEFAULT NULL::text, p_recipient_contact text DEFAULT NULL::text, p_dispatch_note text DEFAULT NULL::text, p_ip_address text DEFAULT ''::text, p_user_agent text DEFAULT ''::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_document public.official_documents%rowtype;
  v_record public.official_document_dispatch_records%rowtype;
  v_actor public.users%rowtype;
  v_applicant public.users%rowtype;
  v_proof public.official_document_files%rowtype;
  v_file_object public.file_objects%rowtype;
  v_external_number text;
  v_dispatch_date text;
  v_recipient text;
  v_recipient_contact text;
  v_dispatch_note text;
  v_final_status text;
  v_now timestamptz := pg_catalog.clock_timestamp();
begin
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('edoc:official-dispatch:' || p_document_id, 0)
  );

  select document.* into v_document
    from public.official_documents as document
   where document.id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_not_found';
  end if;

  select record.* into v_record
    from public.official_document_dispatch_records as record
   where record.id = p_dispatch_record_id
     and record.document_id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_dispatch_record_not_found';
  end if;

  if v_record.dispatch_status in ('dispatched', 'sent_by_applicant') then
    return pg_catalog.jsonb_build_object(
      'completed', false,
      'reason', 'official_dispatch_already_completed',
      'document_id', v_document.id,
      'dispatch_record_id', v_record.id
    );
  end if;
  if v_record.dispatch_status is distinct from 'pending' then
    raise exception using errcode = '22023', message = 'official_dispatch_not_pending';
  end if;
  if v_record.dispatch_method is distinct from v_document.dispatch_method then
    raise exception using errcode = '22023', message = 'official_dispatch_route_conflict';
  end if;

  select app_user.* into v_actor
    from public.users as app_user
     where app_user.id = p_actor_user_id
     and app_user.status = '啟用'
     and app_user.company_id = v_document.company_id;
  if not found then
    raise exception using errcode = '42501', message = 'official_dispatch_complete_forbidden';
  end if;
  if v_record.dispatch_owner_type not in ('general_affairs', 'applicant')
     or v_record.dispatch_owner_user_id is distinct from v_actor.id then
    raise exception using errcode = '42501', message = 'official_dispatch_complete_forbidden';
  end if;
  if v_record.dispatch_owner_type = 'general_affairs'
     and (v_document.current_status is distinct from 'pending_general_affairs_dispatch'
          or v_document.current_step is distinct from 'general_affairs_dispatch') then
    raise exception using errcode = '22023', message = 'official_document_not_pending_general_affairs_dispatch';
  end if;
  if v_record.dispatch_owner_type = 'applicant'
     and (v_document.current_status is distinct from 'returned_to_applicant_for_send'
          or v_document.current_step is distinct from 'applicant_dispatch') then
    raise exception using errcode = '22023', message = 'official_document_not_returned_to_applicant_for_send';
  end if;

  v_external_number := case when p_external_official_document_number is null
    then pg_catalog.btrim(coalesce(v_record.external_official_document_number, ''))
    else pg_catalog.btrim(p_external_official_document_number) end;
  v_dispatch_date := case when p_dispatch_date is null
    then pg_catalog.btrim(coalesce(v_record.dispatch_date, ''))
    else pg_catalog.btrim(p_dispatch_date) end;
  v_recipient := case when p_recipient is null
    then pg_catalog.btrim(coalesce(v_record.recipient, ''))
    else pg_catalog.btrim(p_recipient) end;
  v_recipient_contact := case when p_recipient_contact is null
    then pg_catalog.btrim(coalesce(v_record.recipient_contact, ''))
    else pg_catalog.btrim(p_recipient_contact) end;
  v_dispatch_note := case when p_dispatch_note is null
    then pg_catalog.btrim(coalesce(v_record.dispatch_note, ''))
    else pg_catalog.btrim(p_dispatch_note) end;

  if nullif(v_dispatch_date, '') is null then
    raise exception using errcode = '22007', message = 'official_dispatch_date_required';
  end if;
  if v_dispatch_date !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' then
    raise exception using errcode = '22007', message = 'official_dispatch_date_invalid';
  end if;
  begin
    if pg_catalog.to_char(v_dispatch_date::date, 'YYYY-MM-DD') <> v_dispatch_date then
      raise exception using errcode = '22007', message = 'official_dispatch_date_invalid';
    end if;
  exception when datetime_field_overflow or invalid_datetime_format then
    raise exception using errcode = '22007', message = 'official_dispatch_date_invalid';
  end;

  if v_record.dispatch_method = 'electronic_official_document_by_general_affairs'
     and nullif(v_external_number, '') is null then
    raise exception using errcode = '22023', message = 'official_dispatch_external_number_required';
  end if;

  if v_record.dispatch_method <> 'no_dispatch_required' then
    if v_record.proof_file_id is null then
      raise exception using errcode = '22023', message = 'official_dispatch_proof_required';
    end if;
    select proof.* into v_proof
      from public.official_document_files as proof
     where proof.id = v_record.proof_file_id
       and proof.document_id = v_document.id
       and proof.file_type = 'dispatch_proof'
     for update;
    if not found or v_proof.file_object_id is null then
      raise exception using errcode = '22023', message = 'official_dispatch_proof_invalid';
    end if;
    select file_object.* into v_file_object
      from public.file_objects as file_object
     where file_object.id = v_proof.file_object_id
     for update;
    if not found
       or pg_catalog.lower(pg_catalog.btrim(coalesce(v_file_object.scan_status, '')))
          not in ('已通過', 'clean', 'passed') then
      raise exception using errcode = '22023', message = 'official_file_antivirus_required';
    end if;
  end if;

  v_final_status := case when v_record.dispatch_owner_type = 'applicant'
    then 'sent_by_applicant' else 'dispatched' end;

  update public.official_document_dispatch_records as record
     set external_official_document_number = v_external_number,
         dispatch_date = v_dispatch_date,
         recipient = v_recipient,
         recipient_contact = v_recipient_contact,
         dispatch_note = v_dispatch_note,
         dispatch_status = v_final_status,
         completed_at = pg_catalog.to_char(v_now, 'YYYY-MM-DD HH24:MI:SS'),
         updated_at = pg_catalog.to_char(v_now, 'YYYY-MM-DD HH24:MI:SS')
   where record.id = v_record.id
     and record.document_id = v_document.id
     and record.dispatch_status = 'pending';
  if not found then
    raise exception using errcode = '40001', message = 'official_dispatch_completion_conflict';
  end if;

  update public.official_documents as document
     set current_status = v_final_status,
         current_step = 'applicant_confirm',
         updated_at = pg_catalog.to_char(v_now, 'YYYY-MM-DD HH24:MI:SS')
   where document.id = v_document.id
     and document.current_status = v_document.current_status
     and document.current_step = v_document.current_step;
  if not found then
    raise exception using errcode = '40001', message = 'official_dispatch_completion_conflict';
  end if;

  insert into public.official_document_approval_logs (
    id, document_id, step_id, file_id, actor_id, actor_name,
    principal_actor_id, action, comment, decision_evidence_json,
    ip_address, user_agent, created_at
  ) values (
    'ODLOG-DISPATCH-COMPLETE-' || pg_catalog.upper(pg_catalog.substr(pg_catalog.md5(v_record.id), 1, 18)),
    v_document.id,
    null,
    v_record.proof_file_id,
    v_actor.id,
    coalesce(nullif(v_actor.name, ''), v_actor.id),
    null,
    'complete_dispatch',
    v_final_status,
    pg_catalog.jsonb_build_object(
      'dispatch_record_id', v_record.id,
      'dispatch_method', v_record.dispatch_method,
      'proof_file_id', v_record.proof_file_id,
      'dispatch_date', v_dispatch_date
    ),
    pg_catalog.left(coalesce(p_ip_address, ''), 120),
    pg_catalog.left(coalesce(p_user_agent, ''), 180),
    pg_catalog.to_char(v_now, 'YYYY-MM-DD HH24:MI:SS')
  );

  insert into public.audit_logs (
    id, actor, actor_user_id, action, target_type, target_id, detail,
    event_type, result, severity, module_code, resource_type, resource_id,
    metadata_json, created_at
  ) values (
    'AUD-DISPATCH-COMPLETE-' || pg_catalog.upper(pg_catalog.substr(pg_catalog.md5(v_record.id), 1, 18)),
    coalesce(nullif(v_actor.name, ''), v_actor.id),
    v_actor.id,
    'complete_dispatch',
    'official_documents',
    v_document.id,
    v_final_status,
    'submit',
    'success',
    'info',
    'official_documents',
    'official_documents',
    v_document.id,
    pg_catalog.jsonb_build_object(
      'dispatch_record_id', v_record.id,
      'proof_file_id', v_record.proof_file_id,
      'dispatch_date', v_dispatch_date
    )::text,
    pg_catalog.to_char(v_now, 'YYYY-MM-DD HH24:MI:SS')
  );

  select app_user.* into v_applicant
    from public.users as app_user
   where app_user.id = v_document.applicant_id
     and app_user.status = '啟用'
     and app_user.company_id = v_document.company_id;
  if not found then
    raise exception using errcode = '22023', message = 'official_dispatch_applicant_unresolved';
  end if;

  insert into public.notifications (
    id, type, title, target_role, target_user_id, target_company_id, target_email,
    channel, status, priority, source, action_url, body,
    delivery_receipt, created_at, sent_at
  ) values (
    'NTF-DISPATCH-COMPLETE-' || pg_catalog.upper(pg_catalog.substr(pg_catalog.md5(v_record.id), 1, 18)),
    '發文申請人確認',
    v_document.title || ' 已完成寄發，請確認結案',
    coalesce(nullif(v_applicant.role, ''), '員工'),
    v_applicant.id,
    v_applicant.company_id,
    coalesce(v_applicant.email, ''),
    'Email + 系統通知',
    '未讀',
    '高',
    v_document.id,
    '/#officialWorkflow?document=' || v_document.id,
    '寄發狀態：' || v_final_status || '。請確認已用印版本與寄發紀錄。',
    '',
    v_now,
    null
  );

  return pg_catalog.jsonb_build_object(
    'completed', true,
    'document_id', v_document.id,
    'dispatch_record_id', v_record.id,
    'dispatch_status', v_final_status,
    'proof_file_id', v_record.proof_file_id,
    'notification_id', 'NTF-DISPATCH-COMPLETE-' || pg_catalog.upper(pg_catalog.substr(pg_catalog.md5(v_record.id), 1, 18))
  );
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_apply_official_document_correction(p_document_id text, p_applicant_id text, p_company_id text, p_patch jsonb, p_seal_id text, p_stamp_positions jsonb, p_text_overlays jsonb, p_stamp_request_id text, p_position_ids jsonb, p_overlay_ids jsonb, p_source_file_object_id text, p_official_file_id text, p_source_file_type text, p_actor_name text, p_log_id text, p_audit_id text, p_updated_fields jsonb, p_ip_address text DEFAULT ''::text, p_user_agent text DEFAULT ''::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_document public.official_documents%rowtype;
  v_actor public.users%rowtype;
  v_request public.official_document_stamp_requests%rowtype;
  v_file public.file_objects%rowtype;
  v_position jsonb;
  v_overlay jsonb;
  v_position_index bigint;
  v_overlay_index bigint;
  v_active_request_id text := '';
  v_active_file_id text := '';
  v_metadata jsonb;
  v_first_position jsonb;
  v_evidence jsonb;
  v_next_version integer;
  v_seal_size_type text;
  v_unbound_position boolean;
  v_expected_width_pt numeric;
  v_timestamp text := pg_catalog.to_char(pg_catalog.clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS');
begin
  if nullif(pg_catalog.btrim(p_document_id), '') is null
     or nullif(pg_catalog.btrim(p_applicant_id), '') is null
     or nullif(pg_catalog.btrim(p_company_id), '') is null
     or pg_catalog.jsonb_typeof(p_patch) <> 'object'
     or pg_catalog.jsonb_typeof(p_stamp_positions) <> 'array'
     or pg_catalog.jsonb_typeof(p_text_overlays) <> 'array'
     or pg_catalog.jsonb_typeof(p_position_ids) <> 'array'
     or pg_catalog.jsonb_typeof(p_overlay_ids) <> 'array'
     or pg_catalog.jsonb_typeof(p_updated_fields) <> 'array'
     or not (p_patch ? 'workflow_template_key')
     or nullif(pg_catalog.btrim(p_patch->>'workflow_template_key'), '') is null
     or not (p_patch ? 'metadata_json')
     or (p_patch - array[
       'title', 'subject', 'description', 'method', 'recipient',
       'dispatch_unit', 'handler_name', 'request_reason',
       'workflow_template_key', 'metadata_json'
     ]) <> '{}'::jsonb then
    raise exception using errcode = '22023', message = 'official_document_correction_invalid';
  end if;

  if pg_catalog.jsonb_array_length(p_stamp_positions) > 100
     or pg_catalog.jsonb_array_length(p_position_ids) <> pg_catalog.jsonb_array_length(p_stamp_positions)
     or pg_catalog.jsonb_array_length(p_text_overlays) > 100
     or pg_catalog.jsonb_array_length(p_overlay_ids) <> pg_catalog.jsonb_array_length(p_text_overlays) then
    raise exception using errcode = '22023', message = 'official_document_correction_collection_invalid';
  end if;

  select document.*
    into v_document
    from public.official_documents as document
   where document.id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_not_found';
  end if;
  if v_document.applicant_id is distinct from p_applicant_id then
    raise exception using errcode = '42501', message = 'only_applicant_can_correct';
  end if;
  if v_document.company_id is distinct from p_company_id then
    raise exception using errcode = '42501', message = 'official_document_company_forbidden';
  end if;
  if v_document.current_status not in ('draft', 'rejected') then
    raise exception using errcode = '55000', message = 'official_document_correction_locked';
  end if;

  select actor.*
    into v_actor
    from public.users as actor
   where actor.id = p_applicant_id
     and actor.status = '啟用'
     and actor.company_id = p_company_id
   for share;
  if not found then
    raise exception using errcode = '42501', message = 'official_document_applicant_inactive';
  end if;

  begin
    v_metadata := (p_patch->>'metadata_json')::jsonb;
  exception when others then
    raise exception using errcode = '22023', message = 'official_document_metadata_invalid';
  end;
  if pg_catalog.jsonb_typeof(v_metadata) <> 'object'
     or pg_catalog.octet_length(v_metadata::text) > 65536 then
    raise exception using errcode = '22023', message = 'official_document_metadata_invalid';
  end if;

  for v_position, v_position_index in
    select item.value, item.ordinality
      from pg_catalog.jsonb_array_elements(p_stamp_positions) with ordinality as item(value, ordinality)
  loop
    if pg_catalog.jsonb_typeof(v_position) <> 'object'
       or nullif(pg_catalog.btrim(v_position->>'seal_id'), '') is null
       or (v_position->>'page')::integer < 1
       or (v_position->>'x')::numeric < 0
       or (v_position->>'y')::numeric < 0
       or (v_position->>'width')::numeric <= 0
       or (v_position->>'height')::numeric <= 0
       or (v_position->>'opacity')::numeric < 0
       or (v_position->>'opacity')::numeric > 1 then
      raise exception using errcode = '22023', message = 'invalid_official_stamp_position';
    end if;
    select seal.seal_size_type
      into v_seal_size_type
      from public.company_seals as seal
     where seal.id = v_position->>'seal_id'
       and seal.company_id = p_company_id
       and seal.is_active is true;
    if not found then
      raise exception using errcode = '42501', message = 'official_document_seal_company_mismatch';
    end if;
    v_unbound_position := (
      nullif(pg_catalog.btrim(v_position->>'locked_seal_file_id'), '') is null
      and nullif(pg_catalog.btrim(v_position->>'locked_seal_sha256'), '') is null
      and nullif(pg_catalog.btrim(v_position->>'locked_render_width_pt'), '') is null
      and nullif(pg_catalog.btrim(v_position->>'locked_render_height_pt'), '') is null
      and nullif(pg_catalog.btrim(v_position->>'locked_dimension_policy_version'), '') is null
    );
    if v_unbound_position then
      v_expected_width_pt := (
        case v_seal_size_type
          when 'large_seal' then 30.0
          when 'small_seal' then 18.0
          else -1.0
        end
      ) * 72.0 / 25.4;
      if v_document.current_status <> 'draft'
         or pg_catalog.abs((v_position->>'width')::numeric - v_expected_width_pt) > 0.25
         or pg_catalog.abs((v_position->>'height')::numeric - v_expected_width_pt) > 0.25 then
        raise exception using errcode = '22023', message = 'invalid_official_stamp_position';
      end if;
    elsif nullif(pg_catalog.btrim(v_position->>'locked_seal_file_id'), '') is null
       or pg_catalog.coalesce(v_position->>'locked_seal_sha256', '') !~ '^[0-9A-Fa-f]{64}$'
       or (v_position->>'locked_render_width_pt')::numeric <= 0
       or (v_position->>'locked_render_height_pt')::numeric <= 0
       or pg_catalog.coalesce(v_position->>'locked_dimension_policy_version', '')
            not in ('institution-seal-v1', 'institution-seal-v2-calibrated') then
      raise exception using errcode = '22023', message = 'invalid_official_stamp_position';
    end if;
  end loop;

  if pg_catalog.jsonb_array_length(p_stamp_positions) > 0 then
    v_first_position := p_stamp_positions->0;
    if nullif(pg_catalog.btrim(p_seal_id), '') is null
       or p_seal_id is distinct from v_first_position->>'seal_id' then
      raise exception using errcode = '22023', message = 'official_document_seal_required';
    end if;
  elsif v_document.current_status <> 'draft' then
    raise exception using errcode = '22023', message = 'official_document_seal_position_required';
  end if;
  if pg_catalog.jsonb_array_length(p_stamp_positions) = 0
     and pg_catalog.jsonb_array_length(p_text_overlays) > 0 then
    raise exception using errcode = '22023', message = 'official_document_text_overlay_requires_seal_position';
  end if;

  for v_overlay, v_overlay_index in
    select item.value, item.ordinality
      from pg_catalog.jsonb_array_elements(p_text_overlays) with ordinality as item(value, ordinality)
  loop
    if pg_catalog.jsonb_typeof(v_overlay) <> 'object'
       or (v_overlay->>'page')::integer < 1
       or (v_overlay->>'x')::numeric < 0
       or (v_overlay->>'y')::numeric < 0
       or pg_catalog.char_length(pg_catalog.btrim(v_overlay->>'text_content')) not between 1 and 500
       or (v_overlay->>'font_size')::numeric not between 8 and 72 then
      raise exception using errcode = '22023', message = 'invalid_official_text_overlay';
    end if;
  end loop;

  select request.*
    into v_request
    from public.official_document_stamp_requests as request
   where request.document_id = p_document_id
   order by request.created_at desc, request.id desc
   limit 1
   for update;

  if pg_catalog.jsonb_array_length(p_stamp_positions) > 0 then
    if v_document.current_status = 'rejected' or v_request.id is null then
      if nullif(pg_catalog.btrim(p_stamp_request_id), '') is null then
        raise exception using errcode = '22023', message = 'official_document_stamp_request_id_required';
      end if;
      if v_document.current_status = 'rejected' and v_request.id is not null then
        update public.official_document_stamp_requests
           set status = 'failed',
               error_message = 'superseded_by_correction',
               updated_at = v_timestamp
         where id = v_request.id
           and status <> 'stamped';
      end if;
      insert into public.official_document_stamp_requests (
        id, document_id, company_id, seal_id, requested_by,
        stamp_page, stamp_x, stamp_y, stamp_width, stamp_height,
        status, stamped_file_id, locked_editor_revision_id,
        locked_source_sha256, prepared_file_id, prepared_sha256,
        editor_manifest_sha256, editor_schema_version, renderer_version,
        editor_locked_at, error_message, created_at, stamped_at, updated_at
      ) values (
        p_stamp_request_id, p_document_id, p_company_id, p_seal_id, p_applicant_id,
        (v_first_position->>'page')::integer, (v_first_position->>'x')::numeric,
        (v_first_position->>'y')::numeric, (v_first_position->>'width')::numeric,
        (v_first_position->>'height')::numeric,
        case when v_document.current_status = 'draft' then 'draft' else 'pending' end,
        null, null,
        null, null, null, null, null, null, null, '', v_timestamp, '', v_timestamp
      );
      v_active_request_id := p_stamp_request_id;
    else
      update public.official_document_stamp_requests
         set seal_id = p_seal_id,
             stamp_page = (v_first_position->>'page')::integer,
             stamp_x = (v_first_position->>'x')::numeric,
             stamp_y = (v_first_position->>'y')::numeric,
             stamp_width = (v_first_position->>'width')::numeric,
             stamp_height = (v_first_position->>'height')::numeric,
             status = case when v_document.current_status = 'draft' then 'draft' else 'pending' end,
             stamped_file_id = null,
             locked_editor_revision_id = null, locked_source_sha256 = null,
             prepared_file_id = null, prepared_sha256 = null,
             editor_manifest_sha256 = null, editor_schema_version = null,
             renderer_version = null, editor_locked_at = null,
             claim_token = null, claim_owner_id = null,
             claim_started_at = null, claim_expires_at = null,
             claim_attempt_count = 0, error_message = '', stamped_at = '',
             updated_at = v_timestamp
       where id = v_request.id;
      v_active_request_id := v_request.id;
      delete from public.official_document_stamp_positions where request_id = v_active_request_id;
      delete from public.official_document_text_overlays where request_id = v_active_request_id;
    end if;

    for v_position, v_position_index in
      select item.value, item.ordinality
        from pg_catalog.jsonb_array_elements(p_stamp_positions) with ordinality as item(value, ordinality)
    loop
      insert into public.official_document_stamp_positions (
        id, request_id, seal_id, page, x, y, width, height, page_ref,
        rotation, opacity, z_index, locked_seal_file_id,
        locked_seal_sha256, locked_render_width_pt,
        locked_render_height_pt, locked_dimension_policy_version,
        order_index, created_at, updated_at
      ) values (
        p_position_ids->>(v_position_index - 1), v_active_request_id,
        v_position->>'seal_id', (v_position->>'page')::integer,
        (v_position->>'x')::numeric, (v_position->>'y')::numeric,
        (v_position->>'width')::numeric, (v_position->>'height')::numeric,
        pg_catalog.coalesce(v_position->>'page_ref', ''),
        pg_catalog.coalesce((v_position->>'rotation')::numeric, 0),
        pg_catalog.coalesce((v_position->>'opacity')::numeric, 1),
        pg_catalog.coalesce((v_position->>'z_index')::integer, v_position_index::integer),
        pg_catalog.nullif(pg_catalog.btrim(v_position->>'locked_seal_file_id'), ''),
        pg_catalog.coalesce(v_position->>'locked_seal_sha256', ''),
        (v_position->>'locked_render_width_pt')::numeric,
        (v_position->>'locked_render_height_pt')::numeric,
        pg_catalog.coalesce(v_position->>'locked_dimension_policy_version', ''),
        v_position_index::integer, v_timestamp, v_timestamp
      );
    end loop;

    for v_overlay, v_overlay_index in
      select item.value, item.ordinality
        from pg_catalog.jsonb_array_elements(p_text_overlays) with ordinality as item(value, ordinality)
    loop
      insert into public.official_document_text_overlays (
        id, request_id, page, x, y, text_content, font_size,
        font_family, order_index, created_at, updated_at
      ) values (
        p_overlay_ids->>(v_overlay_index - 1), v_active_request_id,
        (v_overlay->>'page')::integer, (v_overlay->>'x')::numeric,
        (v_overlay->>'y')::numeric, v_overlay->>'text_content',
        (v_overlay->>'font_size')::numeric, 'biau_kai',
        v_overlay_index::integer, v_timestamp, v_timestamp
      );
    end loop;
  else
    v_active_request_id := pg_catalog.coalesce(v_request.id, '');
    if v_request.id is not null then
      delete from public.official_document_stamp_positions where request_id = v_request.id;
      delete from public.official_document_text_overlays where request_id = v_request.id;
      update public.official_document_stamp_requests
         set status = 'failed', stamped_file_id = null,
             locked_editor_revision_id = null, locked_source_sha256 = null,
             prepared_file_id = null, prepared_sha256 = null,
             editor_manifest_sha256 = null, editor_schema_version = null,
             renderer_version = null, editor_locked_at = null,
             claim_token = null, claim_owner_id = null,
             claim_started_at = null, claim_expires_at = null,
             claim_attempt_count = 0,
             error_message = 'cleared_by_draft_correction', stamped_at = '',
             updated_at = v_timestamp
       where id = v_request.id;
    end if;
  end if;

  if nullif(pg_catalog.btrim(p_source_file_object_id), '') is not null then
    if p_source_file_type not in ('original_pdf', 'generated_pdf')
       or nullif(pg_catalog.btrim(p_official_file_id), '') is null then
      raise exception using errcode = '22023', message = 'official_document_correction_file_invalid';
    end if;
    select file.*
      into v_file
      from public.file_objects as file
     where file.id = p_source_file_object_id
     for update;
    if not found
       or v_file.document_id is distinct from p_document_id
       or v_file.mime_type is distinct from 'application/pdf'
       or v_file.purpose is distinct from 'official-documents'
       or v_file.bucket is distinct from 'edoc-private'
       or v_file.sha256 !~ '^[A-Fa-f0-9]{64}$'
       or (p_source_file_type = 'original_pdf' and v_file.scan_status is distinct from '已通過')
       or exists (
         select 1 from public.official_document_files as existing
          where existing.file_object_id = v_file.id
       ) then
      raise exception using errcode = '42501', message = 'official_document_correction_file_invalid';
    end if;
    select pg_catalog.coalesce(pg_catalog.max(file.version), 0) + 1
      into v_next_version
      from public.official_document_files as file
     where file.document_id = p_document_id
       and file.file_type = p_source_file_type;
    insert into public.official_document_files (
      id, document_id, file_object_id, file_type, file_name,
      file_storage_key, file_mime_type, file_size, file_hash,
      version, uploaded_by, created_at
    ) values (
      p_official_file_id, p_document_id, v_file.id, p_source_file_type,
      v_file.file_name, v_file.storage_key, v_file.mime_type,
      v_file.size_bytes, v_file.sha256, v_next_version,
      p_actor_name, v_timestamp
    );
    v_active_file_id := p_official_file_id;
  elsif nullif(pg_catalog.btrim(p_official_file_id), '') is not null
        or nullif(pg_catalog.btrim(p_source_file_type), '') is not null then
    raise exception using errcode = '22023', message = 'official_document_correction_file_invalid';
  end if;

  update public.official_documents
     set title = case when p_patch ? 'title' then p_patch->>'title' else title end,
         subject = case when p_patch ? 'subject' then p_patch->>'subject' else subject end,
         description = case when p_patch ? 'description' then p_patch->>'description' else description end,
         method = case when p_patch ? 'method' then p_patch->>'method' else method end,
         recipient = case when p_patch ? 'recipient' then p_patch->>'recipient' else recipient end,
         dispatch_unit = case when p_patch ? 'dispatch_unit' then p_patch->>'dispatch_unit' else dispatch_unit end,
         handler_name = case when p_patch ? 'handler_name' then p_patch->>'handler_name' else handler_name end,
         request_reason = case when p_patch ? 'request_reason' then p_patch->>'request_reason' else request_reason end,
         workflow_template_key = p_patch->>'workflow_template_key',
         metadata_json = p_patch->>'metadata_json',
         updated_at = v_timestamp
   where id = p_document_id;

  v_evidence := pg_catalog.jsonb_build_object(
    'updated_fields', p_updated_fields,
    'stamp_request_id', v_active_request_id,
    'stamp_position_count', pg_catalog.jsonb_array_length(p_stamp_positions),
    'source_file_id', v_active_file_id,
    'source_sha256', pg_catalog.coalesce(v_file.sha256, '')
  );
  insert into public.official_document_approval_logs (
    id, document_id, step_id, file_id, actor_id, actor_name,
    principal_actor_id, action, comment, decision_evidence_json,
    ip_address, user_agent, created_at
  ) values (
    p_log_id, p_document_id, null, nullif(v_active_file_id, ''),
    p_applicant_id, p_actor_name, p_applicant_id, 'correct',
    '申請人完成補正並建立可稽核的新版本', v_evidence,
    pg_catalog.left(pg_catalog.coalesce(p_ip_address, ''), 120),
    pg_catalog.left(pg_catalog.coalesce(p_user_agent, ''), 180), v_timestamp
  );
  insert into public.audit_logs (
    id, actor, actor_user_id, action, target_type, target_id, detail,
    event_type, severity, result, module_code, resource_type, resource_id,
    request_id, before_snapshot_json, after_snapshot_json, metadata_json, created_at
  ) values (
    p_audit_id, p_actor_name, p_applicant_id, 'correct',
    'official_documents', p_document_id, 'official_document_correction_versioned',
    'submit', 'info', 'success', 'official_documents',
    'official_documents', p_document_id,
    'req_' || pg_catalog.substr(pg_catalog.md5(p_log_id), 1, 16),
    pg_catalog.jsonb_build_object('status', v_document.current_status)::text,
    pg_catalog.jsonb_build_object(
      'status', v_document.current_status,
      'updated_field_count', pg_catalog.jsonb_array_length(p_updated_fields),
      'stamp_position_count', pg_catalog.jsonb_array_length(p_stamp_positions),
      'source_sha256', pg_catalog.coalesce(v_file.sha256, '')
    )::text,
    pg_catalog.jsonb_build_object(
      'stamp_request_id', v_active_request_id,
      'source_file_id', v_active_file_id
    )::text,
    v_timestamp
  );

  return pg_catalog.jsonb_build_object(
    'document_id', p_document_id,
    'stamp_request_id', v_active_request_id,
    'official_file_id', v_active_file_id,
    'source_sha256', pg_catalog.coalesce(v_file.sha256, ''),
    'updated_fields', p_updated_fields
  );
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_finalize_official_document_resubmit(p_document_id text, p_applicant_id text, p_company_id text, p_expected_correction_requested_at timestamp with time zone, p_log_id text, p_audit_id text, p_comment text DEFAULT ''::text, p_ip_address text DEFAULT ''::text, p_user_agent text DEFAULT ''::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_document public.official_documents%rowtype;
  v_actor public.users%rowtype;
  v_timestamp timestamptz := pg_catalog.clock_timestamp();
begin
  if nullif(pg_catalog.btrim(p_document_id), '') is null
     or nullif(pg_catalog.btrim(p_applicant_id), '') is null
     or nullif(pg_catalog.btrim(p_company_id), '') is null
     or p_expected_correction_requested_at is null
     or nullif(pg_catalog.btrim(p_log_id), '') is null
     or nullif(pg_catalog.btrim(p_audit_id), '') is null then
    raise exception using errcode = '22023', message = 'official_document_resubmit_finalize_invalid';
  end if;

  select document.*
    into v_document
    from public.official_documents as document
   where document.id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_not_found';
  end if;
  if v_document.applicant_id is distinct from p_applicant_id then
    raise exception using errcode = '42501', message = 'only_applicant_can_resubmit';
  end if;
  if v_document.company_id is distinct from p_company_id then
    raise exception using errcode = '42501', message = 'official_document_company_forbidden';
  end if;
  if v_document.correction_requested_at is distinct from p_expected_correction_requested_at then
    raise exception using errcode = '55000', message = 'official_document_resubmit_generation_mismatch';
  end if;
  if v_document.current_status = 'rejected'
     or v_document.current_status not like 'pending_%'
     or nullif(pg_catalog.btrim(v_document.current_step), '') is null then
    raise exception using errcode = '55000', message = 'official_document_resubmit_not_submitted';
  end if;

  select actor.*
    into v_actor
    from public.users as actor
   where actor.id = p_applicant_id
     and actor.status = '啟用'
     and actor.company_id = p_company_id
   for share;
  if not found then
    raise exception using errcode = '42501', message = 'official_document_applicant_inactive';
  end if;

  update public.official_documents
     set correction_resubmitted_at = pg_catalog.coalesce(correction_resubmitted_at, v_timestamp),
         correction_reason_category = null,
         correction_missing_items_json = '[]'::jsonb,
         correction_due_at = null,
         updated_at = pg_catalog.to_char(v_timestamp, 'YYYY-MM-DD HH24:MI:SS')
   where id = p_document_id;

  insert into public.official_document_approval_logs (
    id, document_id, step_id, file_id, actor_id, actor_name,
    principal_actor_id, action, comment, decision_evidence_json,
    ip_address, user_agent, created_at
  ) values (
    p_log_id, p_document_id, null, null, p_applicant_id,
    pg_catalog.coalesce(nullif(pg_catalog.btrim(v_actor.name), ''), v_actor.email),
    p_applicant_id, 'resubmit',
    pg_catalog.left(pg_catalog.coalesce(nullif(pg_catalog.btrim(p_comment), ''), '補正完成，重新由第一關送簽'), 2000),
    pg_catalog.jsonb_build_object(
      'correction_requested_at', p_expected_correction_requested_at,
      'workflow_status', v_document.current_status,
      'workflow_step', v_document.current_step
    ),
    pg_catalog.left(pg_catalog.coalesce(p_ip_address, ''), 120),
    pg_catalog.left(pg_catalog.coalesce(p_user_agent, ''), 180),
    pg_catalog.to_char(v_timestamp, 'YYYY-MM-DD HH24:MI:SS')
  ) on conflict (id) do nothing;
  if not exists (
    select 1 from public.official_document_approval_logs as log
     where log.id = p_log_id
       and log.document_id = p_document_id
       and log.actor_id = p_applicant_id
       and log.action = 'resubmit'
  ) then
    raise exception using errcode = '23505', message = 'official_document_resubmit_idempotency_conflict';
  end if;

  insert into public.audit_logs (
    id, actor, actor_user_id, action, target_type, target_id, detail,
    event_type, severity, result, module_code, resource_type, resource_id,
    request_id, before_snapshot_json, after_snapshot_json, metadata_json, created_at
  ) values (
    p_audit_id,
    pg_catalog.coalesce(nullif(pg_catalog.btrim(v_actor.name), ''), v_actor.email),
    p_applicant_id, 'resubmit', 'official_documents', p_document_id,
    'official_document_correction_resubmitted', 'submit', 'info', 'success',
    'official_documents', 'official_documents', p_document_id,
    'req_' || pg_catalog.substr(pg_catalog.md5(p_log_id), 1, 16),
    pg_catalog.jsonb_build_object('correction_requested_at', p_expected_correction_requested_at)::text,
    pg_catalog.jsonb_build_object(
      'correction_resubmitted_at', pg_catalog.coalesce(v_document.correction_resubmitted_at, v_timestamp),
      'workflow_status', v_document.current_status,
      'workflow_step', v_document.current_step
    )::text,
    pg_catalog.jsonb_build_object('idempotency_log_id', p_log_id)::text,
    pg_catalog.to_char(v_timestamp, 'YYYY-MM-DD HH24:MI:SS')
  ) on conflict (id) do nothing;
  if not exists (
    select 1 from public.audit_logs as audit
     where audit.id = p_audit_id
       and audit.actor_user_id = p_applicant_id
       and audit.action = 'resubmit'
       and audit.target_type = 'official_documents'
       and audit.target_id = p_document_id
  ) then
    raise exception using errcode = '23505', message = 'official_document_resubmit_audit_idempotency_conflict';
  end if;

  return pg_catalog.jsonb_build_object(
    'document_id', p_document_id,
    'log_id', p_log_id,
    'correction_requested_at', p_expected_correction_requested_at,
    'finalized', true
  );
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_claim_official_document_approval_v3(p_document_id text, p_expected_step_id text, p_approver_user_id text, p_decision_actor_user_id text, p_comment text, p_decision_evidence jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_document public.official_documents%rowtype;
  v_step public.official_document_approval_steps%rowtype;
  v_evidence jsonb;
  v_result jsonb;
begin
  select document.* into v_document
    from public.official_documents as document
   where document.id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_not_found';
  end if;
  select step.* into v_step
    from public.official_document_approval_steps as step
   where step.id = p_expected_step_id
     and step.document_id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_approval_step_not_found';
  end if;
  if v_step.approver_user_id is distinct from p_approver_user_id then
    raise exception using errcode = '42501', message = 'not_current_official_document_approver';
  end if;
  -- A byte-identical retry after a successful decision remains a no-op.  Do
  -- not rebind it to a later step owned by the same person.
  if v_step.status <> 'pending'
     or v_document.current_step is distinct from v_step.step_key then
    return pg_catalog.jsonb_build_object(
      'claimed', false,
      'reason', 'official_document_approval_already_claimed',
      'document_id', p_document_id,
      'expected_step_id', p_expected_step_id
    );
  end if;
  v_evidence := edoc_private.validate_official_document_decision_evidence(
    p_document_id,
    p_expected_step_id,
    p_approver_user_id,
    p_decision_actor_user_id,
    'approve',
    p_decision_evidence
  );
  v_result := public.edoc_claim_official_document_approval_v2(
    p_document_id,
    p_expected_step_id,
    p_approver_user_id,
    p_decision_actor_user_id,
    p_comment,
    v_evidence
  );
  if coalesce((v_result->>'claimed')::boolean, false)
     and v_result->>'transition' = 'next_step' then
    update public.official_document_approval_steps
       set review_started_at = coalesce(
             review_started_at,
             pg_catalog.to_char(pg_catalog.clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS')
           ),
           updated_at = pg_catalog.to_char(pg_catalog.clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS')
     where id = v_result#>>'{next_step,id}'
       and document_id = p_document_id;
    if not found then
      raise exception using errcode = '40001', message = 'official_document_next_step_activation_conflict';
    end if;
  end if;
  return v_result;
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_claim_official_document_rejection_v3(p_document_id text, p_expected_step_id text, p_approver_user_id text, p_decision_actor_user_id text, p_comment text, p_decision_evidence jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_document public.official_documents%rowtype;
  v_step public.official_document_approval_steps%rowtype;
  v_evidence jsonb;
  v_result jsonb;
begin
  select document.* into v_document
    from public.official_documents as document
   where document.id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_not_found';
  end if;
  select step.* into v_step
    from public.official_document_approval_steps as step
   where step.id = p_expected_step_id
     and step.document_id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_approval_step_not_found';
  end if;
  if v_step.approver_user_id is distinct from p_approver_user_id then
    raise exception using errcode = '42501', message = 'not_current_official_document_approver';
  end if;
  if v_step.status <> 'pending'
     or v_document.current_step is distinct from v_step.step_key then
    return pg_catalog.jsonb_build_object(
      'claimed', false,
      'reason', 'official_document_approval_already_claimed',
      'document_id', p_document_id,
      'expected_step_id', p_expected_step_id
    );
  end if;
  v_evidence := edoc_private.validate_official_document_decision_evidence(
    p_document_id,
    p_expected_step_id,
    p_approver_user_id,
    p_decision_actor_user_id,
    'reject',
    p_decision_evidence
  );
  v_result := public.edoc_claim_official_document_rejection_v2(
    p_document_id,
    p_expected_step_id,
    p_approver_user_id,
    p_decision_actor_user_id,
    p_comment,
    v_evidence
  );
  return v_result;
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_cancel_official_document(p_document_id text, p_applicant_user_id text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_document public.official_documents%rowtype;
  v_request public.official_document_stamp_requests%rowtype;
  v_now timestamptz := pg_catalog.clock_timestamp();
begin
  select document.*
    into v_document
    from public.official_documents as document
   where document.id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_not_found';
  end if;
  if v_document.applicant_id is distinct from p_applicant_user_id then
    raise exception using errcode = '42501', message = 'only_applicant_can_cancel';
  end if;

  select request.*
    into v_request
    from public.official_document_stamp_requests as request
   where request.document_id = p_document_id
   order by request.created_at desc, request.id desc
   limit 1
   for update;

  if v_document.current_status in (
       'approved', 'stamping', 'stamping_failed', 'stamped',
       'pending_general_affairs_dispatch', 'returned_to_applicant_for_send',
       'dispatched', 'sent_by_applicant', 'closed'
     )
     or v_document.current_step = 'auto_stamp'
     or (found and v_request.status in ('stamping', 'stamped')) then
    return pg_catalog.jsonb_build_object(
      'cancelled', false,
      'reason', 'official_document_cannot_cancel_after_stamp',
      'document_id', v_document.id,
      'current_status', v_document.current_status
    );
  end if;
  if v_document.current_status = 'cancelled' then
    return pg_catalog.jsonb_build_object(
      'cancelled', false,
      'reason', 'official_document_already_cancelled',
      'document_id', v_document.id,
      'current_status', v_document.current_status
    );
  end if;

  if v_document.current_status = 'draft' then
    delete from public.official_document_stamp_positions as position
     using public.official_document_stamp_requests as request
     where position.request_id = request.id
       and request.document_id = v_document.id
       and (
         nullif(position.locked_seal_file_id, '') is null
         or nullif(position.locked_seal_sha256, '') is null
         or position.locked_render_width_pt is null
         or position.locked_render_height_pt is null
         or nullif(position.locked_dimension_policy_version, '') is null
       );
  end if;

  update public.official_document_stamp_requests
     set status = 'cancelled',
         error_message = 'cancelled_by_applicant',
         updated_at = pg_catalog.to_char(v_now, 'YYYY-MM-DD HH24:MI:SS')
   where document_id = v_document.id
     and status <> 'stamped';

  update public.official_documents
     set current_status = 'cancelled',
         current_step = '',
         updated_at = pg_catalog.to_char(v_now, 'YYYY-MM-DD HH24:MI:SS')
   where id = v_document.id;

  return pg_catalog.jsonb_build_object(
    'cancelled', true,
    'document_id', v_document.id,
    'current_status', 'cancelled'
  );
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_complete_official_document_stamp(p_document_id text, p_stamp_request_id text, p_claim_token text, p_stamped_file_id text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_document public.official_documents%rowtype;
  v_request public.official_document_stamp_requests%rowtype;
  v_file public.official_document_files%rowtype;
  v_now timestamptz := clock_timestamp();
  v_next_status text;
  v_next_step text;
  v_dispatch_owner_type text;
  v_dispatch_owner_user_id text;
  v_dispatch_status text;
  v_dispatch_record_id text;
begin
  select document.*
    into v_document
    from public.official_documents as document
   where document.id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_not_found';
  end if;

  select request.*
    into v_request
    from public.official_document_stamp_requests as request
   where request.id = p_stamp_request_id
     and request.document_id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_stamp_request_required';
  end if;

  if v_document.current_status is distinct from 'stamping'
     or v_document.current_step is distinct from 'auto_stamp'
     or v_request.status is distinct from 'stamping'
     or v_request.claim_token is distinct from p_claim_token
     or v_request.claim_expires_at is null
     or v_request.claim_expires_at <= v_now then
    return jsonb_build_object(
      'completed', false,
      'reason', 'official_stamp_claim_lost',
      'document_id', v_document.id,
      'stamp_request_id', v_request.id
    );
  end if;

  select file.*
    into v_file
    from public.official_document_files as file
   where file.id = p_stamped_file_id
     and file.document_id = p_document_id
     and file.file_type = 'stamped_pdf'
     and file.stamp_request_id = p_stamp_request_id
   for update;
  if not found then
    raise exception using errcode = '22023', message = 'official_stamp_candidate_file_invalid';
  end if;

  v_next_status := case v_document.dispatch_method
    when 'no_dispatch_required' then 'stamped'
    when 'return_to_applicant_for_manual_send' then 'returned_to_applicant_for_send'
    when 'electronic_official_document_by_general_affairs' then 'pending_general_affairs_dispatch'
    when 'email_by_general_affairs' then 'pending_general_affairs_dispatch'
    when 'physical_mail_by_general_affairs' then 'pending_general_affairs_dispatch'
    else null
  end;
  v_next_step := case v_document.dispatch_method
    when 'no_dispatch_required' then 'applicant_confirm'
    when 'return_to_applicant_for_manual_send' then 'applicant_dispatch'
    when 'electronic_official_document_by_general_affairs' then 'general_affairs_dispatch'
    when 'email_by_general_affairs' then 'general_affairs_dispatch'
    when 'physical_mail_by_general_affairs' then 'general_affairs_dispatch'
    else null
  end;
  if v_next_status is null or v_next_step is null then
    raise exception using errcode = '22023', message = 'invalid_official_dispatch_method';
  end if;

  v_dispatch_owner_type := case v_document.dispatch_method
    when 'no_dispatch_required' then 'system'
    when 'return_to_applicant_for_manual_send' then 'applicant'
    else 'general_affairs'
  end;
  v_dispatch_status := case
    when v_dispatch_owner_type = 'system' then 'dispatched'
    else 'pending'
  end;

  if v_dispatch_owner_type = 'general_affairs' then
    select step.approver_user_id
      into v_dispatch_owner_user_id
      from public.official_document_approval_steps as step
     where step.document_id = v_document.id
       and step.step_key = 'general_affairs_review'
       and step.status = 'approved'
     order by step.step_order desc, step.id desc
     limit 1;
    if coalesce(v_dispatch_owner_user_id, '') = '' then
      raise exception using errcode = '22023', message = 'official_dispatch_owner_unresolved:general_affairs_review';
    end if;
  elsif v_dispatch_owner_type = 'applicant' then
    v_dispatch_owner_user_id := v_document.applicant_id;
  else
    v_dispatch_owner_user_id := 'system';
  end if;

  select record.id
    into v_dispatch_record_id
    from public.official_document_dispatch_records as record
   where record.document_id = v_document.id
   order by record.created_at desc, record.id desc
   limit 1
   for update;

  if found then
    update public.official_document_dispatch_records as record
       set dispatch_method = v_document.dispatch_method,
           dispatch_owner_type = v_dispatch_owner_type,
           dispatch_owner_user_id = v_dispatch_owner_user_id,
           dispatch_status = v_dispatch_status,
           recipient = coalesce(nullif(record.recipient, ''), v_document.recipient),
           completed_at = case when v_dispatch_owner_type = 'system'
                               then coalesce(nullif(record.completed_at, ''), to_char(v_now, 'YYYY-MM-DD HH24:MI:SS'))
                               else record.completed_at end,
           updated_at = to_char(v_now, 'YYYY-MM-DD HH24:MI:SS')
     where id = v_dispatch_record_id;
  else
    v_dispatch_record_id := 'ODDISP-' || upper(substr(pg_catalog.md5(v_document.id || ':' || v_request.id), 1, 24));
    insert into public.official_document_dispatch_records (
      id,
      document_id,
      dispatch_method,
      dispatch_owner_type,
      dispatch_owner_user_id,
      dispatch_status,
      recipient,
      created_by,
      created_at,
      updated_at,
      completed_at
    ) values (
      v_dispatch_record_id,
      v_document.id,
      v_document.dispatch_method,
      v_dispatch_owner_type,
      v_dispatch_owner_user_id,
      v_dispatch_status,
      v_document.recipient,
      coalesce(nullif(v_request.claim_owner_id, ''), 'system'),
      to_char(v_now, 'YYYY-MM-DD HH24:MI:SS'),
      to_char(v_now, 'YYYY-MM-DD HH24:MI:SS'),
      case when v_dispatch_owner_type = 'system' then to_char(v_now, 'YYYY-MM-DD HH24:MI:SS') else null end
    );
  end if;

  update public.official_document_stamp_requests
     set status = 'stamped',
         stamped_file_id = v_file.id,
         stamped_at = to_char(v_now, 'YYYY-MM-DD HH24:MI:SS'),
         claim_expires_at = null,
         error_message = '',
         updated_at = to_char(v_now, 'YYYY-MM-DD HH24:MI:SS')
   where id = v_request.id;

  update public.official_documents
     set stamped_file_id = v_file.id,
         current_status = v_next_status,
         current_step = v_next_step,
         updated_at = to_char(v_now, 'YYYY-MM-DD HH24:MI:SS')
   where id = v_document.id;

  return jsonb_build_object(
    'completed', true,
    'document_id', v_document.id,
    'stamp_request_id', v_request.id,
    'stamped_file_id', v_file.id,
    'dispatch_record_id', v_dispatch_record_id,
    'document_status', v_next_status,
    'document_step', v_next_step
  );
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_fail_official_document_stamp(p_document_id text, p_stamp_request_id text, p_claim_token text, p_error_message text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_document public.official_documents%rowtype;
  v_request public.official_document_stamp_requests%rowtype;
  v_now timestamptz := clock_timestamp();
begin
  select document.*
    into v_document
    from public.official_documents as document
   where document.id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_not_found';
  end if;

  select request.*
    into v_request
    from public.official_document_stamp_requests as request
   where request.id = p_stamp_request_id
     and request.document_id = p_document_id
   for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_stamp_request_required';
  end if;

  if v_document.current_status is distinct from 'stamping'
     or v_document.current_step is distinct from 'auto_stamp'
     or v_request.status is distinct from 'stamping'
     or v_request.claim_token is distinct from p_claim_token
     or v_request.claim_expires_at is null
     or v_request.claim_expires_at <= v_now then
    return jsonb_build_object(
      'failed', false,
      'reason', 'official_stamp_claim_lost',
      'document_id', v_document.id,
      'stamp_request_id', v_request.id
    );
  end if;

  update public.official_documents
     set current_status = 'stamping_failed',
         current_step = 'general_affairs_review',
         updated_at = to_char(v_now, 'YYYY-MM-DD HH24:MI:SS')
   where id = v_document.id;

  update public.official_document_stamp_requests
     set status = 'failed',
         claim_expires_at = null,
         error_message = left(coalesce(p_error_message, 'auto_stamp_failed'), 500),
         updated_at = to_char(v_now, 'YYYY-MM-DD HH24:MI:SS')
   where id = v_request.id;

  return jsonb_build_object(
    'failed', true,
    'document_id', v_document.id,
    'stamp_request_id', v_request.id
  );
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_resolve_portal_finance_user(p_auth_user_id uuid, p_email text)
 RETURNS SETOF users
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_email text := lower(pg_catalog.btrim(coalesce(p_email, '')));
  v_target_id text;
begin
  if p_auth_user_id is null or v_email = '' then
    return;
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'edoc_portal_finance_identity:' || p_auth_user_id::text,
      0
    )
  );

  -- Case variants or stale duplicate records are ambiguous and fail closed.
  if (
    select count(*)
    from public.users candidate
    where lower(pg_catalog.btrim(candidate.email)) = v_email
  ) <> 1 then
    return;
  end if;

  select candidate.id
    into v_target_id
  from public.users candidate
  where lower(pg_catalog.btrim(candidate.email)) = v_email
    and lower(coalesce(candidate.account_source, '')) = 'finance'
    and candidate.status = '啟用'
    and (
      candidate.auth_user_id is null
      or candidate.auth_user_id = p_auth_user_id
    )
  limit 1;

  if v_target_id is null or exists (
    select 1
    from public.users conflicting_user
    where conflicting_user.id <> v_target_id
      and conflicting_user.auth_user_id = p_auth_user_id
  ) then
    return;
  end if;

  return query
  update public.users candidate
  set auth_user_id = p_auth_user_id
  where candidate.id = v_target_id
    and (
      candidate.auth_user_id is null
      or candidate.auth_user_id = p_auth_user_id
    )
    and not exists (
      select 1
      from public.users conflicting_user
      where conflicting_user.id <> candidate.id
        and conflicting_user.auth_user_id = p_auth_user_id
    )
  returning candidate.*;
end;
$function$;

CREATE OR REPLACE FUNCTION public.edoc_register_official_archive_export(p_id text, p_document_id text, p_requested_by text, p_manifest_sha256 text, p_package_sha256 text, p_entry_count integer, p_package_size_bytes bigint, p_renderer_version text, p_storage_bucket text, p_storage_path text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '5s'
AS $function$
declare
  v_export public.official_document_archive_exports%rowtype;
  v_user public.users%rowtype;
  v_document public.official_documents%rowtype;
begin
  if p_manifest_sha256 !~ '^[0-9A-Fa-f]{64}$'
     or p_package_sha256 !~ '^[0-9A-Fa-f]{64}$'
     or p_entry_count < 1 or p_package_size_bytes < 1
     or nullif(pg_catalog.btrim(p_storage_bucket), '') is null
     or nullif(pg_catalog.btrim(p_storage_path), '') is null then
    raise exception using errcode = '22023', message = 'official_archive_export_invalid';
  end if;
  select document.* into v_document
    from public.official_documents as document
   where document.id = p_document_id
   for share;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_not_found';
  end if;
  select actor.* into v_user from public.users as actor
   where actor.id = p_requested_by and actor.status = '啟用';
  if not found then
    raise exception using errcode = '42501', message = 'official_archive_export_actor_invalid';
  end if;
  if v_user.company_id is distinct from v_document.company_id then
    raise exception using errcode = '42501', message = 'official_archive_export_company_forbidden';
  end if;

  insert into public.official_document_archive_exports (
    id, document_id, requested_by, manifest_sha256, package_sha256,
    entry_count, package_size_bytes, renderer_version,
    storage_bucket, storage_path, status, created_at
  ) values (
    p_id, p_document_id, p_requested_by, pg_catalog.lower(p_manifest_sha256),
    pg_catalog.lower(p_package_sha256), p_entry_count, p_package_size_bytes,
    p_renderer_version, p_storage_bucket, p_storage_path, 'ready',
    pg_catalog.clock_timestamp()
  ) returning * into v_export;

  insert into public.audit_logs (
    id, actor, actor_user_id, action, target_type, target_id, detail,
    event_type, result, module_code, resource_type, resource_id, created_at
  ) values (
    'AUD-ARCHIVE-' || pg_catalog.md5(p_id),
    p_requested_by, p_requested_by, '匯出正式公文保存包',
    'official_documents', p_document_id,
    'export_id=' || p_id || ';manifest_sha256=' || pg_catalog.lower(p_manifest_sha256)
      || ';package_sha256=' || pg_catalog.lower(p_package_sha256)
      || ';entries=' || p_entry_count::text,
    'export', 'success', 'official_documents', 'official_documents', p_document_id,
    pg_catalog.to_char(pg_catalog.clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS')
  );
  return pg_catalog.to_jsonb(v_export);
end;
$function$;

-- Recreate integrity triggers after their functions exist.
drop trigger if exists trg_internal_dispatches_delete_guard on public.internal_dispatches;
create trigger trg_internal_dispatches_delete_guard before delete on public.internal_dispatches
for each row execute function public.edoc_guard_canonical_record_delete();

drop trigger if exists trg_internal_dispatch_logs_immutable_update on public.internal_dispatch_logs;
create trigger trg_internal_dispatch_logs_immutable_update before update on public.internal_dispatch_logs
for each row execute function public.edoc_block_immutable_record_log_mutation();
drop trigger if exists trg_internal_dispatch_logs_immutable_delete on public.internal_dispatch_logs;
create trigger trg_internal_dispatch_logs_immutable_delete before delete on public.internal_dispatch_logs
for each row execute function public.edoc_block_immutable_record_log_mutation();

drop trigger if exists trg_official_dispatch_events_immutable_update on public.official_document_dispatch_events;
create trigger trg_official_dispatch_events_immutable_update before update on public.official_document_dispatch_events
for each row execute function public.edoc_block_immutable_record_log_mutation();
drop trigger if exists trg_official_dispatch_events_immutable_delete on public.official_document_dispatch_events;
create trigger trg_official_dispatch_events_immutable_delete before delete on public.official_document_dispatch_events
for each row execute function public.edoc_block_immutable_record_log_mutation();

drop trigger if exists trg_official_editor_revisions_no_update on public.official_document_editor_revisions;
create trigger trg_official_editor_revisions_no_update before update on public.official_document_editor_revisions
for each row execute function edoc_private.reject_official_editor_revision_mutation();
drop trigger if exists trg_official_editor_revisions_no_delete on public.official_document_editor_revisions;
create trigger trg_official_editor_revisions_no_delete before delete on public.official_document_editor_revisions
for each row execute function edoc_private.reject_official_editor_revision_mutation();

drop trigger if exists trg_official_workflow_delegation_guard_insert on public.official_workflow_delegations;
create trigger trg_official_workflow_delegation_guard_insert before insert on public.official_workflow_delegations
for each row execute function edoc_private.guard_official_workflow_delegation_insert();
drop trigger if exists trg_official_workflow_delegation_guard_update on public.official_workflow_delegations;
create trigger trg_official_workflow_delegation_guard_update before update on public.official_workflow_delegations
for each row execute function edoc_private.guard_official_workflow_delegation_update();

drop trigger if exists trg_official_stamp_position_dimensions on public.official_document_stamp_positions;
create trigger trg_official_stamp_position_dimensions before insert or update on public.official_document_stamp_positions
for each row execute function public.edoc_enforce_company_seal_position_dimensions();

-- PostgreSQL grants EXECUTE to PUBLIC by default. Make every recovered RPC server-only.
revoke all on function public.edoc_apply_official_document_correction(p_document_id text, p_applicant_id text, p_company_id text, p_patch jsonb, p_seal_id text, p_stamp_positions jsonb, p_text_overlays jsonb, p_stamp_request_id text, p_position_ids jsonb, p_overlay_ids jsonb, p_source_file_object_id text, p_official_file_id text, p_source_file_type text, p_actor_name text, p_log_id text, p_audit_id text, p_updated_fields jsonb, p_ip_address text, p_user_agent text) from public, anon, authenticated;
grant execute on function public.edoc_apply_official_document_correction(p_document_id text, p_applicant_id text, p_company_id text, p_patch jsonb, p_seal_id text, p_stamp_positions jsonb, p_text_overlays jsonb, p_stamp_request_id text, p_position_ids jsonb, p_overlay_ids jsonb, p_source_file_object_id text, p_official_file_id text, p_source_file_type text, p_actor_name text, p_log_id text, p_audit_id text, p_updated_fields jsonb, p_ip_address text, p_user_agent text) to service_role;
revoke all on function public.edoc_block_immutable_record_log_mutation() from public, anon, authenticated;
revoke all on function public.edoc_block_immutable_record_log_mutation() from service_role;
revoke all on function public.edoc_cancel_official_document(p_document_id text, p_applicant_user_id text) from public, anon, authenticated;
grant execute on function public.edoc_cancel_official_document(p_document_id text, p_applicant_user_id text) to service_role;
revoke all on function public.edoc_claim_official_document_approval(p_document_id text, p_expected_step_id text, p_approver_user_id text, p_comment text) from public, anon, authenticated;
revoke all on function public.edoc_claim_official_document_approval(p_document_id text, p_expected_step_id text, p_approver_user_id text, p_comment text) from service_role;
revoke all on function public.edoc_claim_official_document_approval_v2(p_document_id text, p_expected_step_id text, p_approver_user_id text, p_decision_actor_user_id text, p_comment text, p_decision_evidence jsonb) from public, anon, authenticated;
revoke all on function public.edoc_claim_official_document_approval_v2(p_document_id text, p_expected_step_id text, p_approver_user_id text, p_decision_actor_user_id text, p_comment text, p_decision_evidence jsonb) from service_role;
revoke all on function public.edoc_claim_official_document_approval_v3(p_document_id text, p_expected_step_id text, p_approver_user_id text, p_decision_actor_user_id text, p_comment text, p_decision_evidence jsonb) from public, anon, authenticated;
grant execute on function public.edoc_claim_official_document_approval_v3(p_document_id text, p_expected_step_id text, p_approver_user_id text, p_decision_actor_user_id text, p_comment text, p_decision_evidence jsonb) to service_role;
revoke all on function public.edoc_claim_official_document_rejection(p_document_id text, p_expected_step_id text, p_approver_user_id text, p_comment text) from public, anon, authenticated;
revoke all on function public.edoc_claim_official_document_rejection(p_document_id text, p_expected_step_id text, p_approver_user_id text, p_comment text) from service_role;
revoke all on function public.edoc_claim_official_document_rejection_v2(p_document_id text, p_expected_step_id text, p_approver_user_id text, p_decision_actor_user_id text, p_comment text, p_decision_evidence jsonb) from public, anon, authenticated;
revoke all on function public.edoc_claim_official_document_rejection_v2(p_document_id text, p_expected_step_id text, p_approver_user_id text, p_decision_actor_user_id text, p_comment text, p_decision_evidence jsonb) from service_role;
revoke all on function public.edoc_claim_official_document_rejection_v3(p_document_id text, p_expected_step_id text, p_approver_user_id text, p_decision_actor_user_id text, p_comment text, p_decision_evidence jsonb) from public, anon, authenticated;
grant execute on function public.edoc_claim_official_document_rejection_v3(p_document_id text, p_expected_step_id text, p_approver_user_id text, p_decision_actor_user_id text, p_comment text, p_decision_evidence jsonb) to service_role;
revoke all on function public.edoc_company_seal_dimensions_are_valid(p_size_type text, p_pixel_width integer, p_pixel_height integer, p_source_aspect_ratio numeric, p_render_width_mm numeric, p_render_height_mm numeric, p_policy_version text, p_dimension_validated boolean) from public, anon, authenticated;
grant execute on function public.edoc_company_seal_dimensions_are_valid(p_size_type text, p_pixel_width integer, p_pixel_height integer, p_source_aspect_ratio numeric, p_render_width_mm numeric, p_render_height_mm numeric, p_policy_version text, p_dimension_validated boolean) to service_role;
revoke all on function public.edoc_complete_official_document_dispatch(p_document_id text, p_dispatch_record_id text, p_actor_user_id text, p_external_official_document_number text, p_dispatch_date text, p_recipient text, p_recipient_contact text, p_dispatch_note text, p_ip_address text, p_user_agent text) from public, anon, authenticated;
grant execute on function public.edoc_complete_official_document_dispatch(p_document_id text, p_dispatch_record_id text, p_actor_user_id text, p_external_official_document_number text, p_dispatch_date text, p_recipient text, p_recipient_contact text, p_dispatch_note text, p_ip_address text, p_user_agent text) to service_role;
revoke all on function public.edoc_complete_official_document_stamp(p_document_id text, p_stamp_request_id text, p_claim_token text, p_stamped_file_id text) from public, anon, authenticated;
grant execute on function public.edoc_complete_official_document_stamp(p_document_id text, p_stamp_request_id text, p_claim_token text, p_stamped_file_id text) to service_role;
revoke all on function public.edoc_create_company_seal_file_version(p_file_id text, p_seal_file_id text, p_seal_id text, p_storage_key text, p_file_name text, p_mime_type text, p_file_size bigint, p_sha256 text, p_pixel_width integer, p_pixel_height integer, p_source_aspect_ratio numeric, p_render_width_mm numeric, p_render_height_mm numeric, p_dimension_policy_version text, p_actor text, p_scan_engine text, p_scan_signature text, p_usage_log_id text, p_audit_log_id text) from public, anon, authenticated;
grant execute on function public.edoc_create_company_seal_file_version(p_file_id text, p_seal_file_id text, p_seal_id text, p_storage_key text, p_file_name text, p_mime_type text, p_file_size bigint, p_sha256 text, p_pixel_width integer, p_pixel_height integer, p_source_aspect_ratio numeric, p_render_width_mm numeric, p_render_height_mm numeric, p_dimension_policy_version text, p_actor text, p_scan_engine text, p_scan_signature text, p_usage_log_id text, p_audit_log_id text) to service_role;
revoke all on function public.edoc_create_official_document_dispatch_record(p_document_id text, p_actor_user_id text) from public, anon, authenticated;
grant execute on function public.edoc_create_official_document_dispatch_record(p_document_id text, p_actor_user_id text) to service_role;
revoke all on function public.edoc_create_official_workflow_delegation(p_id text, p_company_id text, p_principal_user_id text, p_delegate_user_id text, p_starts_at timestamp with time zone, p_ends_at timestamp with time zone, p_reason text, p_created_by text) from public, anon, authenticated;
grant execute on function public.edoc_create_official_workflow_delegation(p_id text, p_company_id text, p_principal_user_id text, p_delegate_user_id text, p_starts_at timestamp with time zone, p_ends_at timestamp with time zone, p_reason text, p_created_by text) to service_role;
revoke all on function public.edoc_enforce_company_seal_position_dimensions() from public, anon, authenticated;
revoke all on function public.edoc_enforce_company_seal_position_dimensions() from service_role;
revoke all on function public.edoc_fail_official_document_stamp(p_document_id text, p_stamp_request_id text, p_claim_token text, p_error_message text) from public, anon, authenticated;
grant execute on function public.edoc_fail_official_document_stamp(p_document_id text, p_stamp_request_id text, p_claim_token text, p_error_message text) to service_role;
revoke all on function public.edoc_finalize_official_document_resubmit(p_document_id text, p_applicant_id text, p_company_id text, p_expected_correction_requested_at timestamp with time zone, p_log_id text, p_audit_id text, p_comment text, p_ip_address text, p_user_agent text) from public, anon, authenticated;
grant execute on function public.edoc_finalize_official_document_resubmit(p_document_id text, p_applicant_id text, p_company_id text, p_expected_correction_requested_at timestamp with time zone, p_log_id text, p_audit_id text, p_comment text, p_ip_address text, p_user_agent text) to service_role;
revoke all on function public.edoc_guard_canonical_record_delete() from public, anon, authenticated;
revoke all on function public.edoc_guard_canonical_record_delete() from service_role;
revoke all on function public.edoc_register_official_archive_export(p_id text, p_document_id text, p_requested_by text, p_manifest_sha256 text, p_package_sha256 text, p_entry_count integer, p_package_size_bytes bigint, p_renderer_version text, p_storage_bucket text, p_storage_path text) from public, anon, authenticated;
grant execute on function public.edoc_register_official_archive_export(p_id text, p_document_id text, p_requested_by text, p_manifest_sha256 text, p_package_sha256 text, p_entry_count integer, p_package_size_bytes bigint, p_renderer_version text, p_storage_bucket text, p_storage_path text) to service_role;
revoke all on function public.edoc_resolve_portal_finance_user(p_auth_user_id uuid, p_email text) from public, anon, authenticated;
grant execute on function public.edoc_resolve_portal_finance_user(p_auth_user_id uuid, p_email text) to service_role;
revoke all on function public.edoc_revoke_official_workflow_delegation(p_delegation_id text, p_revoked_by text) from public, anon, authenticated;
grant execute on function public.edoc_revoke_official_workflow_delegation(p_delegation_id text, p_revoked_by text) to service_role;
revoke all on function public.edoc_set_current_company_seal_file(p_file_id text, p_actor text, p_usage_log_id text, p_audit_log_id text) from public, anon, authenticated;
grant execute on function public.edoc_set_current_company_seal_file(p_file_id text, p_actor text, p_usage_log_id text, p_audit_log_id text) to service_role;
revoke all on function edoc_private.assert_official_decision_actor(p_company_id text, p_principal_user_id text, p_decision_actor_user_id text) from public, anon, authenticated, service_role;
revoke all on function edoc_private.guard_official_workflow_delegation_insert() from public, anon, authenticated, service_role;
revoke all on function edoc_private.guard_official_workflow_delegation_update() from public, anon, authenticated, service_role;
revoke all on function edoc_private.reject_official_editor_revision_mutation() from public, anon, authenticated, service_role;

-- Commit submission, workflow creation, evidence locking, and audit writes as one transaction.
create or replace function public.edoc_commit_official_document_submission(p_request jsonb)
returns jsonb
language plpgsql
security definer
set search_path to ''
set lock_timeout to '5s'
as $function$
declare
  v_document public.official_documents%rowtype;
  v_stamp public.official_document_stamp_requests%rowtype;
  v_position public.official_document_stamp_positions%rowtype;
  v_step public.official_document_approval_steps%rowtype;
  v_first_step public.official_document_approval_steps%rowtype;
  v_snapshot public.approval_step_actor_snapshots%rowtype;
  v_submit_log public.official_document_approval_logs%rowtype;
  v_submit_audit public.audit_logs%rowtype;
  v_resubmit_log public.official_document_approval_logs%rowtype;
  v_resubmit_audit public.audit_logs%rowtype;
  v_operation_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'operation_id', '')), '');
  v_document_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'document_id', '')), '');
  v_applicant_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'applicant_id', '')), '');
  v_company_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'company_id', '')), '');
  v_expected_status text := nullif(pg_catalog.btrim(coalesce(p_request->>'expected_status', '')), '');
  -- Current production stores these workflow timestamps as canonical TEXT.
  -- Keep the compare/write variables textual so the forward RPC matches live schema.
  v_expected_updated_at text := coalesce(p_request->>'expected_updated_at', '');
  v_submitted_at text := nullif(pg_catalog.btrim(coalesce(p_request->>'submitted_at', '')), '');
  v_first_step_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'first_step_id', '')), '');
  v_first_step_key text := nullif(pg_catalog.btrim(coalesce(p_request->>'first_step_key', '')), '');
  v_first_status text := nullif(pg_catalog.btrim(coalesce(p_request->>'first_status', '')), '');
  v_workflow_generation integer;
  v_supersede_generation integer := 0;
  v_resubmit_enabled boolean := false;
  v_step_count integer;
  v_step_id_count integer;
  v_step_order_count integer;
  v_position_count integer;
  v_existing_log public.official_document_approval_logs%rowtype;
  v_patch jsonb := coalesce(p_request->'document_patch', '{}'::jsonb);
  v_resubmit jsonb := coalesce(p_request->'resubmit', '{}'::jsonb);
begin
  if pg_catalog.jsonb_typeof(p_request) is distinct from 'object'
     or v_operation_id is null or v_document_id is null or v_applicant_id is null
     or v_company_id is null or v_expected_updated_at = '' or v_submitted_at is null
     or v_first_step_id is null
     or v_first_step_key is null or v_first_status is null
     or v_expected_status not in ('draft', 'rejected')
     or pg_catalog.jsonb_typeof(p_request->'stamp_request') is distinct from 'object'
     or pg_catalog.jsonb_typeof(p_request->'stamp_positions') is distinct from 'array'
     or pg_catalog.jsonb_typeof(p_request->'steps') is distinct from 'array'
     or pg_catalog.jsonb_typeof(p_request->'actor_snapshots') is distinct from 'array'
     or pg_catalog.jsonb_typeof(p_request->'submit_log') is distinct from 'object'
     or pg_catalog.jsonb_typeof(p_request->'submit_audit') is distinct from 'object' then
    raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
  end if;

  begin
    v_workflow_generation := (p_request->>'workflow_generation')::integer;
    v_supersede_generation := coalesce((p_request->>'supersede_generation')::integer, 0);
    v_resubmit_enabled := coalesce((v_resubmit->>'enabled')::boolean, false);
  exception when others then
    raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
  end;
  if v_workflow_generation < 1 or v_supersede_generation < 0
     or (v_expected_status = 'rejected') is distinct from v_resubmit_enabled then
    raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
  end if;

  -- Serialize retries that reuse a caller-owned operation id. Without this
  -- lock, two concurrent identical submissions could both miss the witness
  -- row before one of them commits.
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('edoc:official-submit:' || v_operation_id, 0)
  );

  if exists (
    select 1 from pg_catalog.jsonb_object_keys(v_patch) as key
    where key not in ('metadata_json','correction_reason_category','correction_missing_items_json',
                      'correction_due_at','correction_requested_at','correction_resubmitted_at')
  ) then
    raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
  end if;

  select log.* into v_existing_log
  from public.official_document_approval_logs as log
  where log.id = v_operation_id;
  if found then
    select document.* into v_document
    from public.official_documents as document where document.id = v_document_id;
    if found and v_existing_log.document_id = v_document_id
       and v_existing_log.actor_id = v_applicant_id
       and v_existing_log.decision_evidence_json->>'operation_id' = v_operation_id
       and v_existing_log.decision_evidence_json->>'stamp_request_id' = p_request#>>'{stamp_request,id}'
       and coalesce((v_existing_log.decision_evidence_json->>'workflow_generation')::integer, 0) = v_workflow_generation
       and v_document.company_id = v_company_id
       and v_document.current_status = v_first_status
       and v_document.current_step = v_first_step_key
       and exists (
         select 1 from public.official_document_stamp_requests request
         where request.id = p_request#>>'{stamp_request,id}'
           and request.document_id = v_document_id
           and request.company_id = v_company_id
           and request.requested_by = v_applicant_id
       )
       and exists (
         select 1 from public.official_document_approval_steps step
         where step.id = v_first_step_id and step.document_id = v_document_id
           and step.workflow_generation = v_workflow_generation
       ) then
      return pg_catalog.jsonb_build_object(
        'ok', true, 'committed', true, 'idempotent', true,
        'document_id', v_document_id, 'operation_id', v_operation_id,
        'current_status', v_document.current_status, 'current_step', v_document.current_step,
        'first_step_id', v_first_step_id, 'workflow_generation', v_workflow_generation,
        'resubmitted', v_resubmit_enabled
      );
    end if;
    raise exception using errcode = '23505', message = 'official_submission_operation_conflict';
  end if;

  select document.* into v_document
  from public.official_documents as document
  where document.id = v_document_id
  for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'official_document_not_found';
  end if;
  if v_document.applicant_id is distinct from v_applicant_id
     or v_document.company_id is distinct from v_company_id then
    raise exception using errcode = '42501', message = 'official_document_submit_forbidden';
  end if;
  if v_document.current_status is distinct from v_expected_status then
    raise exception using errcode = '55000', message = 'official_document_not_submittable';
  end if;
  if v_document.updated_at is distinct from v_expected_updated_at then
    raise exception using errcode = '40001', message = 'official_document_submit_stale';
  end if;

  v_stamp := pg_catalog.jsonb_populate_record(null::public.official_document_stamp_requests, p_request->'stamp_request');
  v_submit_log := pg_catalog.jsonb_populate_record(null::public.official_document_approval_logs, p_request->'submit_log');
  v_submit_audit := pg_catalog.jsonb_populate_record(null::public.audit_logs, p_request->'submit_audit');
  if v_stamp.id is null or v_stamp.document_id is distinct from v_document_id
     or v_stamp.company_id is distinct from v_company_id
     or v_stamp.requested_by is distinct from v_applicant_id
     or not (
       (
         nullif(v_stamp.locked_editor_revision_id, '') is not null
         and nullif(v_stamp.locked_source_sha256, '') is not null
         and nullif(v_stamp.prepared_file_id, '') is not null
         and nullif(v_stamp.prepared_sha256, '') is not null
         and nullif(v_stamp.editor_manifest_sha256, '') is not null
         and v_stamp.editor_schema_version is not null
         and nullif(v_stamp.renderer_version, '') is not null
         and v_stamp.editor_locked_at is not null
       )
       or
       (
         nullif(v_stamp.locked_editor_revision_id, '') is null
         and nullif(v_stamp.locked_source_sha256, '') is null
         and nullif(v_stamp.prepared_file_id, '') is null
         and nullif(v_stamp.prepared_sha256, '') is null
         and nullif(v_stamp.editor_manifest_sha256, '') is null
         and v_stamp.editor_schema_version is null
         and nullif(v_stamp.renderer_version, '') is null
         and v_stamp.editor_locked_at is null
       )
     )
     or v_submit_log.id is distinct from v_operation_id
     or v_submit_log.document_id is distinct from v_document_id
     or v_submit_log.actor_id is distinct from v_applicant_id
     or v_submit_audit.id is null or v_submit_audit.target_id is distinct from v_document_id then
    raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
  end if;

  select pg_catalog.count(*), pg_catalog.count(distinct elem->>'id'),
         pg_catalog.count(distinct (elem->>'step_order')::integer)
    into v_step_count, v_step_id_count, v_step_order_count
  from pg_catalog.jsonb_array_elements(p_request->'steps') elem;
  if v_step_count < 1 or v_step_count <> v_step_id_count or v_step_count <> v_step_order_count then
    raise exception using errcode = '22023', message = 'official_workflow_existing_steps_invalid';
  end if;
  select step.* into v_first_step
  from pg_catalog.jsonb_populate_recordset(null::public.official_document_approval_steps, p_request->'steps') step
  where step.id = v_first_step_id;
  if not found or v_first_step.document_id is distinct from v_document_id
     or v_first_step.workflow_generation is distinct from v_workflow_generation
     or v_first_step.step_key is distinct from v_first_step_key
     or v_first_step.status is distinct from 'pending'
     or v_first_step.step_order is distinct from (
       select pg_catalog.min((elem->>'step_order')::integer)
       from pg_catalog.jsonb_array_elements(p_request->'steps') elem
     ) then
    raise exception using errcode = '22023', message = 'official_workflow_existing_steps_invalid';
  end if;
  if exists (
    select 1 from pg_catalog.jsonb_populate_recordset(null::public.official_document_approval_steps, p_request->'steps') step
    where step.document_id is distinct from v_document_id
       or step.workflow_generation is distinct from v_workflow_generation
       or step.step_order < 1 or step.id is null or step.step_key is null
  ) or exists (
    select 1 from public.official_document_approval_steps step
    where step.document_id = v_document_id and step.workflow_generation = v_workflow_generation
  ) then
    raise exception using errcode = '23505', message = 'official_workflow_existing_steps_invalid';
  end if;

  select pg_catalog.count(*) into v_position_count
  from pg_catalog.jsonb_array_elements(p_request->'stamp_positions');
  if v_position_count < 1 or exists (
    select 1 from pg_catalog.jsonb_populate_recordset(null::public.official_document_stamp_positions, p_request->'stamp_positions') position
    where position.request_id is distinct from v_stamp.id
       or position.id is null or position.seal_id is null
       or position.locked_seal_file_id is null or nullif(position.locked_seal_sha256, '') is null
       or position.locked_render_width_pt is null or position.locked_render_height_pt is null
       or nullif(position.locked_dimension_policy_version, '') is null
  ) then
    raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
  end if;

  if v_resubmit_enabled then
    if v_supersede_generation < 1
       or v_workflow_generation <= v_supersede_generation
       or v_document.correction_requested_at is distinct from (v_resubmit->>'expected_correction_requested_at')::timestamptz
       or v_supersede_generation is distinct from (
         select pg_catalog.max(step.workflow_generation)
         from public.official_document_approval_steps step where step.document_id = v_document_id
       ) then
      raise exception using errcode = '40001', message = 'official_document_resubmit_generation_conflict';
    end if;
    if pg_catalog.jsonb_typeof(v_resubmit->'log') is distinct from 'object'
       or pg_catalog.jsonb_typeof(v_resubmit->'audit') is distinct from 'object' then
      raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
    end if;
    v_resubmit_log := pg_catalog.jsonb_populate_record(null::public.official_document_approval_logs, v_resubmit->'log');
    v_resubmit_audit := pg_catalog.jsonb_populate_record(null::public.audit_logs, v_resubmit->'audit');
    if v_resubmit_log.id is null or v_resubmit_log.document_id is distinct from v_document_id
       or v_resubmit_log.actor_id is distinct from v_applicant_id
       or v_resubmit_audit.id is null or v_resubmit_audit.target_id is distinct from v_document_id then
      raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
    end if;
    update public.official_document_approval_steps
       set status = 'skipped', updated_at = v_submitted_at
     where document_id = v_document_id and workflow_generation = v_supersede_generation
       and status = 'pending';
  elsif exists (
    select 1 from public.official_document_approval_steps step
    where step.document_id = v_document_id and step.status = 'pending'
  ) then
    raise exception using errcode = '55000', message = 'official_workflow_existing_steps_invalid';
  end if;

  insert into public.official_document_stamp_requests
  select (v_stamp).*
  on conflict (id) do update set
    document_id = excluded.document_id, company_id = excluded.company_id, seal_id = excluded.seal_id,
    requested_by = excluded.requested_by, stamp_page = excluded.stamp_page, stamp_x = excluded.stamp_x,
    stamp_y = excluded.stamp_y, stamp_width = excluded.stamp_width, stamp_height = excluded.stamp_height,
    status = excluded.status, stamped_file_id = excluded.stamped_file_id,
    locked_editor_revision_id = excluded.locked_editor_revision_id,
    locked_source_sha256 = excluded.locked_source_sha256, prepared_file_id = excluded.prepared_file_id,
    prepared_sha256 = excluded.prepared_sha256, editor_manifest_sha256 = excluded.editor_manifest_sha256,
    editor_schema_version = excluded.editor_schema_version, renderer_version = excluded.renderer_version,
    editor_locked_at = excluded.editor_locked_at, error_message = excluded.error_message,
    updated_at = excluded.updated_at;
  delete from public.official_document_stamp_positions where request_id = v_stamp.id;
  for v_position in
    select * from pg_catalog.jsonb_populate_recordset(null::public.official_document_stamp_positions, p_request->'stamp_positions')
  loop
    insert into public.official_document_stamp_positions select (v_position).*;
  end loop;

  for v_step in
    select * from pg_catalog.jsonb_populate_recordset(null::public.official_document_approval_steps, p_request->'steps')
  loop
    insert into public.official_document_approval_steps select (v_step).*;
  end loop;
  for v_snapshot in
    select * from pg_catalog.jsonb_populate_recordset(null::public.approval_step_actor_snapshots, p_request->'actor_snapshots')
  loop
    if v_snapshot.source_type not in (
         'official_document', 'official_documents', 'official_document_application'
       )
       or v_snapshot.source_id is distinct from v_document_id
       or nullif(v_snapshot.snapshot_json->>'step_id', '') is null then
      raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
    end if;
    select step.* into v_step
    from public.official_document_approval_steps step
    where step.id = v_snapshot.snapshot_json->>'step_id'
      and step.document_id = v_document_id
      and step.workflow_generation = v_workflow_generation;
    if not found
       or v_snapshot.approver_user_id is distinct from v_step.approver_user_id
       or v_snapshot.step_no is distinct from v_step.step_order then
      raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
    end if;
    insert into public.approval_step_actor_snapshots select (v_snapshot).*;
  end loop;

  update public.official_documents set
    metadata_json = case when v_patch ? 'metadata_json' then v_patch->>'metadata_json' else metadata_json end,
    correction_reason_category = case when v_patch ? 'correction_reason_category' then v_patch->>'correction_reason_category' else correction_reason_category end,
    correction_missing_items_json = case when v_patch ? 'correction_missing_items_json' then v_patch->'correction_missing_items_json' else correction_missing_items_json end,
    correction_due_at = case when v_patch ? 'correction_due_at' then nullif(v_patch->>'correction_due_at','')::timestamptz else correction_due_at end,
    correction_requested_at = case when v_patch ? 'correction_requested_at' then nullif(v_patch->>'correction_requested_at','')::timestamptz else correction_requested_at end,
    correction_resubmitted_at = case when v_resubmit_enabled then nullif(v_resubmit->>'correction_resubmitted_at','')::timestamptz
                                     when v_patch ? 'correction_resubmitted_at' then nullif(v_patch->>'correction_resubmitted_at','')::timestamptz
                                     else correction_resubmitted_at end,
    current_status = v_first_status,
    current_step = v_first_step_key,
    updated_at = v_submitted_at
  where id = v_document_id;
  if v_resubmit_enabled then
    update public.official_documents set correction_reason_category = null,
      correction_missing_items_json = '[]'::jsonb, correction_due_at = null,
      correction_requested_at = null
    where id = v_document_id;
  end if;
  update public.official_document_approval_steps
     set review_started_at = v_submitted_at, updated_at = v_submitted_at
   where id = v_first_step_id and document_id = v_document_id;

  insert into public.official_document_approval_logs select (v_submit_log).*;
  insert into public.audit_logs (
    id, actor, action, target_type, target_id, ip, device, detail, created_at,
    event_type, severity, result, module_code, resource_type, resource_id, data_scope,
    actor_user_id, actor_email, actor_roles_json, target_user_id, target_email, reason,
    request_id, before_snapshot_json, after_snapshot_json, metadata_json
  ) values (
    v_submit_audit.id, v_submit_audit.actor, v_submit_audit.action, v_submit_audit.target_type,
    v_submit_audit.target_id, v_submit_audit.ip, v_submit_audit.device, v_submit_audit.detail,
    v_submit_audit.created_at, v_submit_audit.event_type, v_submit_audit.severity,
    v_submit_audit.result, v_submit_audit.module_code, v_submit_audit.resource_type,
    v_submit_audit.resource_id, v_submit_audit.data_scope, v_submit_audit.actor_user_id,
    v_submit_audit.actor_email, coalesce(v_submit_audit.actor_roles_json, '[]'),
    v_submit_audit.target_user_id, v_submit_audit.target_email, v_submit_audit.reason,
    v_submit_audit.request_id, coalesce(v_submit_audit.before_snapshot_json, '{}'),
    coalesce(v_submit_audit.after_snapshot_json, '{}'), coalesce(v_submit_audit.metadata_json, '{}')
  );
  if v_resubmit_enabled then
    insert into public.official_document_approval_logs select (v_resubmit_log).*;
    insert into public.audit_logs (
      id, actor, action, target_type, target_id, ip, device, detail, created_at,
      event_type, severity, result, module_code, resource_type, resource_id, data_scope,
      actor_user_id, actor_email, actor_roles_json, target_user_id, target_email, reason,
      request_id, before_snapshot_json, after_snapshot_json, metadata_json
    ) values (
      v_resubmit_audit.id, v_resubmit_audit.actor, v_resubmit_audit.action,
      v_resubmit_audit.target_type, v_resubmit_audit.target_id, v_resubmit_audit.ip,
      v_resubmit_audit.device, v_resubmit_audit.detail, v_resubmit_audit.created_at,
      v_resubmit_audit.event_type, v_resubmit_audit.severity, v_resubmit_audit.result,
      v_resubmit_audit.module_code, v_resubmit_audit.resource_type, v_resubmit_audit.resource_id,
      v_resubmit_audit.data_scope, v_resubmit_audit.actor_user_id, v_resubmit_audit.actor_email,
      coalesce(v_resubmit_audit.actor_roles_json, '[]'), v_resubmit_audit.target_user_id,
      v_resubmit_audit.target_email, v_resubmit_audit.reason, v_resubmit_audit.request_id,
      coalesce(v_resubmit_audit.before_snapshot_json, '{}'),
      coalesce(v_resubmit_audit.after_snapshot_json, '{}'), coalesce(v_resubmit_audit.metadata_json, '{}')
    );
  end if;

  return pg_catalog.jsonb_build_object(
    'ok', true, 'committed', true, 'idempotent', false,
    'document_id', v_document_id, 'operation_id', v_operation_id,
    'current_status', v_first_status, 'current_step', v_first_step_key,
    'first_step_id', v_first_step_id, 'workflow_generation', v_workflow_generation,
    'resubmitted', v_resubmit_enabled
  );
exception
  when invalid_text_representation or numeric_value_out_of_range or not_null_violation or check_violation then
    raise exception using errcode = '22023', message = 'official_submission_invalid_payload';
end;
$function$;

revoke all on function public.edoc_commit_official_document_submission(jsonb) from public, anon, authenticated;
grant execute on function public.edoc_commit_official_document_submission(jsonb) to service_role;

-- Finalize a direct-uploaded editor asset and create its immutable revision atomically.
create or replace function public.edoc_finalize_editor_asset_v2(p_request jsonb)
returns jsonb
language plpgsql
security definer
set search_path to ''
set lock_timeout to '5s'
as $function$
declare
  v_document public.official_documents%rowtype;
  v_asset public.official_document_editor_assets%rowtype;
  v_latest public.official_document_editor_revisions%rowtype;
  v_revision public.official_document_editor_revisions%rowtype;
  v_file public.file_objects%rowtype;
  v_official_file public.official_document_files%rowtype;
  v_log public.official_document_approval_logs%rowtype;
  v_audit public.audit_logs%rowtype;
  v_operation_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'operation_id','')), '');
  v_document_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'document_id','')), '');
  v_applicant_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'applicant_id','')), '');
  v_company_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'company_id','')), '');
  v_asset_id text := nullif(pg_catalog.btrim(coalesce(p_request->>'asset_id','')), '');
  v_expected_status text := nullif(pg_catalog.btrim(coalesce(p_request->>'expected_asset_status','')), '');
  v_expected_sha text := pg_catalog.lower(coalesce(p_request->>'expected_asset_sha256',''));
  v_expected_size bigint;
  v_expected_base_id text := nullif(coalesce(p_request->>'expected_base_revision_id',''), '');
  v_expected_base_no integer;
  v_has_official_file boolean := false;
  v_asset_patch jsonb := coalesce(p_request->'asset_patch', '{}'::jsonb);
begin
  if pg_catalog.jsonb_typeof(p_request) is distinct from 'object'
     or v_operation_id is null or v_document_id is null or v_applicant_id is null
     or v_company_id is null or v_asset_id is null
     or v_expected_status not in ('pending','uploaded')
     or v_expected_sha !~ '^[0-9a-f]{64}$'
     or pg_catalog.jsonb_typeof(p_request->'file_object') is distinct from 'object'
     or pg_catalog.jsonb_typeof(p_request->'asset_patch') is distinct from 'object'
     or pg_catalog.jsonb_typeof(p_request->'revision') is distinct from 'object'
     or pg_catalog.jsonb_typeof(p_request->'approval_log') is distinct from 'object'
     or pg_catalog.jsonb_typeof(p_request->'audit_log') is distinct from 'object' then
    raise exception using errcode = '22023', message = 'editor_finalize_invalid_payload';
  end if;
  begin
    v_expected_size := (p_request->>'expected_asset_size_bytes')::bigint;
    v_expected_base_no := coalesce((p_request->>'expected_base_revision_no')::integer, 0);
  exception when others then
    raise exception using errcode = '22023', message = 'editor_finalize_invalid_payload';
  end;
  if v_expected_size < 1 or v_expected_base_no < 0 then
    raise exception using errcode = '22023', message = 'editor_finalize_invalid_payload';
  end if;

  select document.* into v_document from public.official_documents document
  where document.id = v_document_id for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'editor_upload_not_found';
  end if;
  if v_document.applicant_id is distinct from v_applicant_id
     or v_document.company_id is distinct from v_company_id then
    raise exception using errcode = '42501', message = 'official_editor_write_forbidden';
  end if;
  if v_document.current_status not in ('draft','rejected') then
    raise exception using errcode = '55000', message = 'editor_locked_after_submit';
  end if;

  select asset.* into v_asset from public.official_document_editor_assets asset
  where asset.id = v_asset_id and asset.document_id = v_document_id for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'editor_upload_not_found';
  end if;
  v_revision := pg_catalog.jsonb_populate_record(null::public.official_document_editor_revisions, p_request->'revision');
  v_file := pg_catalog.jsonb_populate_record(null::public.file_objects, p_request->'file_object');
  v_log := pg_catalog.jsonb_populate_record(null::public.official_document_approval_logs, p_request->'approval_log');
  v_audit := pg_catalog.jsonb_populate_record(null::public.audit_logs, p_request->'audit_log');
  v_has_official_file := pg_catalog.jsonb_typeof(p_request->'official_file') = 'object'
                         and p_request->'official_file' <> '{}'::jsonb;
  if v_has_official_file then
    v_official_file := pg_catalog.jsonb_populate_record(null::public.official_document_files, p_request->'official_file');
  end if;

  if v_asset.upload_status = 'finalized' then
    if v_log.id = v_operation_id
       and v_log.document_id = v_document_id
       and v_log.actor_id = v_applicant_id
       and v_audit.id is not null
       and v_audit.target_id = v_document_id
       and v_asset.editor_revision_id = v_revision.id and v_asset.file_object_id = v_file.id
       and pg_catalog.lower(v_asset.sha256) = v_expected_sha and v_asset.size_bytes = v_expected_size
       and (not v_has_official_file or v_asset.official_file_id = v_official_file.id)
       and exists (select 1 from public.file_objects f
                   where f.id = v_file.id and f.document_id = v_document_id
                     and pg_catalog.lower(f.sha256) = v_expected_sha
                     and f.size_bytes = v_expected_size)
       and (not v_has_official_file or exists (
         select 1 from public.official_document_files f
         where f.id = v_official_file.id and f.document_id = v_document_id
           and f.file_object_id = v_file.id
           and pg_catalog.lower(f.file_hash) = v_expected_sha
           and f.file_size = v_expected_size
       ))
       and exists (select 1 from public.official_document_editor_revisions r
                   where r.id = v_revision.id and r.document_id = v_document_id
                     and r.manifest_sha256 = v_revision.manifest_sha256)
       and exists (select 1 from public.official_document_approval_logs l
                   where l.id = v_operation_id and l.document_id = v_document_id
                     and l.actor_id = v_applicant_id)
       and exists (select 1 from public.audit_logs a
                   where a.id = v_audit.id and a.target_id = v_document_id
                     and a.request_id = v_operation_id) then
      return pg_catalog.jsonb_build_object(
        'ok', true, 'committed', true, 'idempotent', true,
        'document_id', v_document_id, 'asset_id', v_asset_id,
        'operation_id', v_operation_id, 'revision_id', v_revision.id,
        'revision_no', v_revision.revision_no, 'manifest_sha256', v_revision.manifest_sha256,
        'file_object_id', v_file.id,
        'official_file_id', case when v_has_official_file then v_official_file.id else null end
      );
    end if;
    raise exception using errcode = '23505', message = 'editor_finalize_operation_conflict';
  end if;
  if exists (select 1 from public.official_document_approval_logs l where l.id = v_operation_id)
     or exists (select 1 from public.audit_logs a where a.id = v_audit.id) then
    raise exception using errcode = '23505', message = 'editor_finalize_operation_conflict';
  end if;
  if v_asset.upload_status is distinct from v_expected_status
     or pg_catalog.lower(v_asset.expected_sha256) is distinct from v_expected_sha
     or v_asset.size_bytes is distinct from v_expected_size then
    raise exception using errcode = '40001', message = 'editor_upload_new_intent_required';
  end if;

  select revision.* into v_latest
  from public.official_document_editor_revisions revision
  where revision.document_id = v_document_id
  order by revision.revision_no desc limit 1 for update;
  if found then
    if v_latest.id is distinct from v_expected_base_id
       or v_latest.revision_no is distinct from v_expected_base_no
       or v_revision.parent_revision_id is distinct from v_latest.id
       or v_revision.revision_no is distinct from v_latest.revision_no + 1 then
      raise exception using errcode = '40001', message = 'editor_revision_conflict';
    end if;
  elsif v_expected_base_id is not null or v_expected_base_no <> 0
        or v_revision.parent_revision_id is not null or v_revision.revision_no <> 1 then
    raise exception using errcode = '40001', message = 'editor_revision_conflict';
  end if;

  if v_revision.id is null or v_revision.document_id is distinct from v_document_id
     or v_revision.created_by is distinct from v_applicant_id
     or v_file.id is null or v_file.document_id is distinct from v_document_id
     or v_file.created_by is distinct from v_applicant_id
     or pg_catalog.lower(v_file.sha256) is distinct from v_expected_sha
     or v_file.size_bytes is distinct from v_expected_size
     or v_log.id is distinct from v_operation_id or v_log.document_id is distinct from v_document_id
     or v_log.actor_id is distinct from v_applicant_id
     or v_audit.id is null or v_audit.target_id is distinct from v_document_id
     or v_asset_patch->>'file_object_id' is distinct from v_file.id
     or pg_catalog.lower(coalesce(v_asset_patch->>'sha256','')) is distinct from v_expected_sha
     or v_asset_patch->>'upload_status' is distinct from 'finalized'
     or v_asset_patch->>'scan_status' is distinct from 'passed' then
    raise exception using errcode = '22023', message = 'editor_finalize_invalid_payload';
  end if;
  if v_has_official_file and (
       v_official_file.id is null or v_official_file.document_id is distinct from v_document_id
       or v_official_file.file_object_id is distinct from v_file.id
       or v_official_file.file_type is distinct from 'original_pdf'
       or pg_catalog.lower(v_official_file.file_hash) is distinct from v_expected_sha
       or v_official_file.file_size is distinct from v_expected_size
       or v_asset_patch->>'official_file_id' is distinct from v_official_file.id
     ) then
    raise exception using errcode = '22023', message = 'editor_finalize_invalid_payload';
  end if;

  if exists (select 1 from public.file_objects f where f.id = v_file.id or f.storage_key = v_file.storage_key) then
    raise exception using errcode = '23505', message = 'editor_file_object_conflict';
  end if;
  if v_has_official_file and exists (select 1 from public.official_document_files f where f.id = v_official_file.id) then
    raise exception using errcode = '23505', message = 'editor_official_file_conflict';
  end if;
  if exists (select 1 from public.official_document_editor_revisions r
             where r.id = v_revision.id
                or (r.document_id = v_document_id and r.revision_no = v_revision.revision_no)
                or (v_revision.parent_revision_id is not null and r.document_id = v_document_id
                    and r.parent_revision_id = v_revision.parent_revision_id)) then
    raise exception using errcode = '23505', message = 'editor_revision_conflict';
  end if;

  insert into public.file_objects select (v_file).*;
  if v_has_official_file then
    insert into public.official_document_files select (v_official_file).*;
  end if;
  insert into public.official_document_editor_revisions select (v_revision).*;
  update public.official_document_editor_assets set
    file_object_id = v_file.id,
    official_file_id = case when v_has_official_file then v_official_file.id else null end,
    sha256 = pg_catalog.upper(v_expected_sha),
    upload_status = 'finalized', scan_status = 'passed',
    preflight_status = coalesce(nullif(v_asset_patch->>'preflight_status',''), preflight_status),
    page_count = coalesce((v_asset_patch->>'page_count')::integer, page_count),
    metadata_json = coalesce(v_asset_patch->>'metadata_json', metadata_json),
    finalized_at = v_asset_patch->>'finalized_at',
    editor_revision_id = v_revision.id
  where id = v_asset_id and document_id = v_document_id;
  insert into public.official_document_approval_logs select (v_log).*;
  insert into public.audit_logs (
    id, actor, action, target_type, target_id, ip, device, detail, created_at,
    event_type, severity, result, module_code, resource_type, resource_id, data_scope,
    actor_user_id, actor_email, actor_roles_json, target_user_id, target_email, reason,
    request_id, before_snapshot_json, after_snapshot_json, metadata_json
  ) values (
    v_audit.id, v_audit.actor, v_audit.action, v_audit.target_type, v_audit.target_id,
    v_audit.ip, v_audit.device, v_audit.detail, v_audit.created_at, v_audit.event_type,
    v_audit.severity, v_audit.result, v_audit.module_code, v_audit.resource_type,
    v_audit.resource_id, v_audit.data_scope, v_audit.actor_user_id, v_audit.actor_email,
    coalesce(v_audit.actor_roles_json, '[]'), v_audit.target_user_id, v_audit.target_email,
    v_audit.reason, v_audit.request_id, coalesce(v_audit.before_snapshot_json, '{}'),
    coalesce(v_audit.after_snapshot_json, '{}'), coalesce(v_audit.metadata_json, '{}')
  );

  return pg_catalog.jsonb_build_object(
    'ok', true, 'committed', true, 'idempotent', false,
    'document_id', v_document_id, 'asset_id', v_asset_id, 'operation_id', v_operation_id,
    'revision_id', v_revision.id, 'revision_no', v_revision.revision_no,
    'manifest_sha256', v_revision.manifest_sha256, 'file_object_id', v_file.id,
    'official_file_id', case when v_has_official_file then v_official_file.id else null end
  );
exception
  when invalid_text_representation or numeric_value_out_of_range or not_null_violation or check_violation then
    raise exception using errcode = '22023', message = 'editor_finalize_invalid_payload';
end;
$function$;

revoke all on function public.edoc_finalize_editor_asset_v2(jsonb) from public, anon, authenticated;
grant execute on function public.edoc_finalize_editor_asset_v2(jsonb) to service_role;

notify pgrst, 'reload schema';
