-- eDoc production cutover checks (metadata only, read only).
-- This file intentionally does not select document content, attachment paths,
-- seal originals, credentials, session tokens, or environment values.

-- 1. Required public tables and RLS state. Missing rows fail the cutover.
with required_tables(table_name) as (
  values
    ('audit_logs'), ('auth_sessions'), ('companies'), ('company_seal_files'),
    ('company_seals'), ('file_download_tokens'), ('file_objects'),
    ('finance_member_sync_nonces'), ('finance_member_sync_receipts'),
    ('inbound_document_attachments'), ('inbound_documents'),
    ('internal_dispatch_logs'), ('internal_dispatch_recipients'),
    ('internal_dispatch_replies'), ('internal_dispatches'), ('login_events'),
    ('official_document_approval_logs'), ('official_document_approval_steps'),
    ('official_document_dispatch_records'), ('official_document_files'),
    ('official_document_stamp_positions'), ('official_document_stamp_requests'),
    ('official_document_text_overlays'), ('official_documents'),
    ('seal_permissions'), ('seal_reference_options'), ('seal_usage_approvals'),
    ('seal_usage_logs'), ('seal_usage_requests'), ('users'), ('virus_scan_jobs')
)
select
  r.table_name,
  c.oid is not null as table_exists,
  coalesce(c.relrowsecurity, false) as rls_enabled
from required_tables r
left join pg_class c
  on c.relname = r.table_name
 and c.relkind in ('r', 'p')
 and c.relnamespace = 'public'::regnamespace
order by r.table_name;

-- 2. Data API grants. service_role needs backend access; anon/authenticated
-- grants must be reviewed together with RLS and must not expose sync receipts.
select table_name, grantee, privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and table_name in (
    'audit_logs', 'auth_sessions', 'companies', 'company_seal_files',
    'company_seals', 'file_download_tokens', 'file_objects',
    'finance_member_sync_nonces', 'finance_member_sync_receipts',
    'inbound_document_attachments', 'inbound_documents',
    'internal_dispatch_logs', 'internal_dispatch_recipients',
    'internal_dispatch_replies', 'internal_dispatches', 'login_events',
    'official_document_approval_logs', 'official_document_approval_steps',
    'official_document_dispatch_records', 'official_document_files',
    'official_document_stamp_positions', 'official_document_stamp_requests',
    'official_document_text_overlays', 'official_documents',
    'seal_permissions', 'seal_reference_options', 'seal_usage_approvals',
    'seal_usage_logs', 'seal_usage_requests', 'users', 'virus_scan_jobs'
  )
order by table_name, grantee, privilege_type;

-- 3. Finance projection schema required before deploying the new eDoc code.
with required_columns(table_name, column_name) as (
  values
    ('users', 'finance_source_revision'),
    ('users', 'finance_source_event_id'),
    ('users', 'finance_source_status'),
    ('users', 'finance_source_updated_at'),
    ('companies', 'finance_source_revision'),
    ('companies', 'finance_source_event_id'),
    ('companies', 'finance_source_updated_at')
)
select
  r.table_name,
  r.column_name,
  (c.column_name is not null) as column_exists,
  c.data_type,
  c.is_nullable
from required_columns r
left join information_schema.columns c
  on c.table_schema = 'public'
 and c.table_name = r.table_name
 and c.column_name = r.column_name
order by r.table_name, r.column_name;

-- 4. Finance sync tables must remain backend-only.
select table_name, grantee, privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and table_name in ('finance_member_sync_nonces', 'finance_member_sync_receipts')
  and grantee in ('anon', 'authenticated', 'PUBLIC')
order by table_name, grantee, privilege_type;
-- Pass condition: zero rows.

-- 5. Private Storage buckets only; no object names or paths are selected.
select id, public, file_size_limit, allowed_mime_types
from storage.buckets
where id in ('edoc-private', 'edoc-seal-vault')
order by id;

-- 6. Policy inventory without policy expressions or stored object metadata.
select schemaname, tablename, policyname, permissive, roles, cmd
from pg_policies
where (schemaname = 'storage' and tablename = 'objects')
   or (schemaname = 'public' and tablename in (
     'company_seal_files', 'file_objects',
     'finance_member_sync_nonces', 'finance_member_sync_receipts'
   ))
order by schemaname, tablename, policyname;

-- 7. Security-definer inventory for eDoc-related public functions. Every
-- privileged function must have an explicit owner, search_path and EXECUTE
-- grant review; this query does not expose function bodies.
select
  n.nspname as schema_name,
  p.proname as function_name,
  pg_get_userbyid(p.proowner) as owner_name,
  p.prosecdef as security_definer,
  p.proconfig as function_settings
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public'
  and (
    p.proname like 'edoc_%'
    or p.proname like 'official_document_%'
    or p.proname like 'seal_%'
    or p.proname like 'finance_%'
  )
order by p.proname;

-- 8. Internal-launch reference option counts only. No business document data.
select option_type, count(*) as active_option_count
from public.seal_reference_options
where status = 'active'
group by option_type
order by option_type;
