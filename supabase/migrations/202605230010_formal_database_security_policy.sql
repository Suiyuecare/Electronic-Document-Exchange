-- Formal database security policy for Suiyuecare eDoc Exchange.
-- Covers RLS, confidential row isolation, retention policy, and append-only audit logs.

create extension if not exists pgcrypto;

create schema if not exists edoc_private;
revoke all on schema edoc_private from public;
grant usage on schema edoc_private to authenticated;

alter table public.documents add column if not exists retention_policy_code text not null default 'EDOC-STD-07Y';
alter table public.documents add column if not exists retention_years integer not null default 7;
alter table public.documents add column if not exists retention_until date;
alter table public.documents add column if not exists legal_hold boolean not null default false;
alter table public.documents add column if not exists disposition_status text not null default '保存中';
alter table public.documents add column if not exists disposed_at timestamptz;
alter table public.documents add column if not exists confidentiality_scope text not null default '一般';

alter table public.attachments add column if not exists retention_until date;
alter table public.attachments add column if not exists legal_hold boolean not null default false;

alter table public.audit_logs add column if not exists previous_hash text;
alter table public.audit_logs add column if not exists entry_hash text;
alter table public.audit_logs add column if not exists chain_version integer not null default 1;
alter table public.audit_logs add column if not exists immutable boolean not null default true;

create table if not exists public.document_retention_policies (
  code text primary key,
  name text not null,
  retention_years integer not null check (retention_years >= 1),
  applies_to text not null,
  legal_basis text not null,
  disposition_action text not null default 'archive_review',
  status text not null default '啟用',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.document_retention_events (
  id text primary key,
  document_id text references public.documents(id) on delete set null,
  actor text not null,
  action text not null,
  policy_code text references public.document_retention_policies(code),
  detail text,
  created_at timestamptz not null default now()
);

insert into public.document_retention_policies (code, name, retention_years, applies_to, legal_basis, disposition_action)
values
  ('EDOC-STD-07Y', '一般電子公文保存七年', 7, '普通/速件收發文', '內部文書保存政策與稽核追蹤需求', 'archive_review'),
  ('EDOC-CONF-10Y', '密件電子公文保存十年', 10, '密/機密/極機密/絕對機密', '密件權限隔離、不可否認與稽核證據保存', 'security_review'),
  ('EDOC-SEAL-15Y', '用印與電子簽章公文保存十五年', 15, '已押章、正式電子簽章、對外發文', '用印紀錄、簽章證據與防竄改雜湊保存', 'legal_review')
on conflict (code) do update set
  name = excluded.name,
  retention_years = excluded.retention_years,
  applies_to = excluded.applies_to,
  legal_basis = excluded.legal_basis,
  disposition_action = excluded.disposition_action,
  updated_at = now();

create index if not exists idx_documents_retention_until on public.documents(retention_until);
create index if not exists idx_documents_confidentiality_scope on public.documents(confidentiality_scope);
create index if not exists idx_documents_legal_hold on public.documents(legal_hold);
create index if not exists idx_audit_logs_entry_hash on public.audit_logs(entry_hash);
create index if not exists idx_retention_events_document on public.document_retention_events(document_id);

alter table public.document_retention_policies enable row level security;
alter table public.document_retention_events enable row level security;

grant select on public.document_retention_policies to authenticated;
grant select, insert on public.document_retention_events to authenticated;
grant execute on all functions in schema edoc_private to authenticated;

create or replace function edoc_private.current_user_role()
returns text
language sql
stable
security definer
set search_path = public, auth
as $$
  select u.role
  from public.users u
  where u.auth_user_id = auth.uid()
    and u.status = '啟用'
  limit 1
$$;

create or replace function edoc_private.current_user_unit()
returns text
language sql
stable
security definer
set search_path = public, auth
as $$
  select u.unit
  from public.users u
  where u.auth_user_id = auth.uid()
    and u.status = '啟用'
  limit 1
$$;

create or replace function edoc_private.current_user_name()
returns text
language sql
stable
security definer
set search_path = public, auth
as $$
  select u.name
  from public.users u
  where u.auth_user_id = auth.uid()
    and u.status = '啟用'
  limit 1
$$;

create or replace function edoc_private.current_user_email()
returns text
language sql
stable
security definer
set search_path = public, auth
as $$
  select u.email
  from public.users u
  where u.auth_user_id = auth.uid()
    and u.status = '啟用'
  limit 1
$$;

create or replace function edoc_private.has_permission(permission_code text)
returns boolean
language sql
stable
security definer
set search_path = public, auth
as $$
  select exists (
    select 1
    from public.users u
    join public.roles r on r.name = u.role and r.status = '啟用'
    join public.role_permissions rp on rp.role_id = r.id
    join public.permissions p on p.id = rp.permission_id
    where u.auth_user_id = auth.uid()
      and u.status = '啟用'
      and p.code = permission_code
  )
$$;

create or replace function edoc_private.has_document_acl(target_document_id text, required_action text default 'view')
returns boolean
language sql
stable
security definer
set search_path = public, auth
as $$
  select exists (
    select 1
    from public.document_acl acl
    where acl.document_id = target_document_id
      and (acl.expires_at is null or acl.expires_at > now())
      and (
        (acl.principal_type = 'role' and acl.principal_id = edoc_private.current_user_role()) or
        (acl.principal_type = 'unit' and acl.principal_id = edoc_private.current_user_unit()) or
        (acl.principal_type = 'user' and acl.principal_id in (edoc_private.current_user_name(), edoc_private.current_user_email()))
      )
      and case required_action
        when 'sign' then acl.can_sign
        when 'download' then acl.can_download
        when 'seal' then acl.can_seal
        when 'delegate' then acl.can_delegate
        else acl.can_view
      end
  )
$$;

create or replace function edoc_private.document_in_role_scope(
  target_document_id text,
  target_owner text,
  target_department text,
  target_direction text,
  target_status text,
  target_security_level text
)
returns boolean
language sql
stable
security definer
set search_path = public, auth
as $$
  select
    case
      when edoc_private.current_user_role() = '執行長' then true
      when edoc_private.has_document_acl(target_document_id, 'view') then true
      when edoc_private.current_user_role() = '總務' then
        target_owner = '總務'
        or target_department = '總務'
        or (target_direction = '收文' and target_status in ('待登錄', '待分派'))
      when edoc_private.current_user_role() = '行政部主任' then
        target_owner = '行政部主任'
        or target_department in ('行政部', '總管理處')
      when edoc_private.current_user_role() = '主任' then
        target_owner = '主任'
        or target_department = '營運管理處'
      else
        target_owner in (edoc_private.current_user_role(), edoc_private.current_user_name(), edoc_private.current_user_email())
        or target_department = edoc_private.current_user_unit()
    end
$$;

create or replace function edoc_private.document_can_view(
  target_document_id text,
  target_owner text,
  target_department text,
  target_direction text,
  target_status text,
  target_security_level text
)
returns boolean
language sql
stable
security definer
set search_path = public, auth
as $$
  select
    edoc_private.current_user_role() is not null
    and edoc_private.document_in_role_scope(target_document_id, target_owner, target_department, target_direction, target_status, target_security_level)
    and (
      coalesce(target_security_level, '普通') not in ('密', '機密', '極機密', '絕對機密')
      or edoc_private.has_document_acl(target_document_id, 'view')
      or edoc_private.current_user_role() in ('執行長', '主任', '行政部主任')
    )
$$;

create or replace function edoc_private.document_can_manage(
  target_document_id text,
  target_owner text,
  target_department text,
  target_direction text,
  target_status text,
  target_security_level text,
  required_action text default 'sign'
)
returns boolean
language sql
stable
security definer
set search_path = public, auth
as $$
  select
    edoc_private.current_user_role() is not null
    and (
      edoc_private.has_document_acl(target_document_id, required_action)
      or (
        edoc_private.document_can_view(target_document_id, target_owner, target_department, target_direction, target_status, target_security_level)
        and (
          edoc_private.current_user_role() in ('主任', '執行長', '行政部主任')
          or (edoc_private.current_user_role() = '總務' and required_action in ('download', 'delegate', 'send'))
          or target_owner in (edoc_private.current_user_role(), edoc_private.current_user_name(), edoc_private.current_user_email())
        )
      )
    )
$$;

create or replace function edoc_private.set_document_retention()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  base_date date;
begin
  if new.security_level in ('密', '機密', '極機密', '絕對機密') then
    new.retention_policy_code := 'EDOC-CONF-10Y';
    new.retention_years := 10;
    new.confidentiality_scope := '密件';
  elsif new.status in ('已押章', '交換完成') or new.direction = '發文' then
    new.retention_policy_code := 'EDOC-SEAL-15Y';
    new.retention_years := 15;
    new.confidentiality_scope := '一般';
  else
    new.retention_policy_code := 'EDOC-STD-07Y';
    new.retention_years := 7;
    new.confidentiality_scope := '一般';
  end if;

  begin
    base_date := coalesce(nullif(left(new.created_at, 10), '')::date, current_date);
  exception when others then
    base_date := current_date;
  end;

  if new.retention_until is null then
    new.retention_until := (base_date + make_interval(years => new.retention_years))::date;
  end if;

  if new.legal_hold then
    new.disposition_status := '法務凍結';
  elsif new.disposed_at is not null then
    new.disposition_status := '已處分';
  elsif new.retention_until <= current_date then
    new.disposition_status := '待屆期審查';
  else
    new.disposition_status := '保存中';
  end if;

  return new;
end;
$$;

drop trigger if exists trg_documents_set_retention on public.documents;
create trigger trg_documents_set_retention
before insert or update of security_level, status, direction, created_at, retention_until, legal_hold, disposed_at
on public.documents
for each row execute function edoc_private.set_document_retention();

create or replace function edoc_private.prevent_document_delete_before_retention()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if old.legal_hold then
    raise exception 'Document % is under legal hold and cannot be deleted.', old.id;
  end if;

  if old.retention_until is null or old.retention_until > current_date then
    raise exception 'Document % is still within retention period until %.', old.id, old.retention_until;
  end if;

  insert into public.document_retention_events (id, document_id, actor, action, policy_code, detail)
  values (
    'RET-' || replace(gen_random_uuid()::text, '-', ''),
    old.id,
    coalesce(edoc_private.current_user_email(), current_user),
    'DELETE_AFTER_RETENTION',
    old.retention_policy_code,
    'Retention period completed; delete allowed by retention trigger.'
  );

  return old;
end;
$$;

drop trigger if exists trg_documents_prevent_delete_before_retention on public.documents;
create trigger trg_documents_prevent_delete_before_retention
before delete on public.documents
for each row execute function edoc_private.prevent_document_delete_before_retention();

create or replace function edoc_private.audit_log_hash_payload(
  audit_id text,
  actor text,
  action text,
  target_type text,
  target_id text,
  ip text,
  device text,
  detail text,
  created_at text,
  previous_hash text
)
returns text
language sql
immutable
as $$
  select encode(
    digest(
      concat_ws('|',
        coalesce(previous_hash, ''),
        coalesce(audit_id, ''),
        coalesce(actor, ''),
        coalesce(action, ''),
        coalesce(target_type, ''),
        coalesce(target_id, ''),
        coalesce(ip, ''),
        coalesce(device, ''),
        coalesce(detail, ''),
        coalesce(created_at, '')
      ),
      'sha256'
    ),
    'hex'
  )
$$;

create or replace function edoc_private.prepare_audit_log_hash()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  last_hash text;
begin
  select entry_hash into last_hash
  from public.audit_logs
  where entry_hash is not null
  order by created_at desc, id desc
  limit 1;

  new.previous_hash := coalesce(new.previous_hash, last_hash);
  new.entry_hash := edoc_private.audit_log_hash_payload(
    new.id,
    new.actor,
    new.action,
    new.target_type,
    new.target_id,
    new.ip,
    new.device,
    new.detail,
    new.created_at,
    new.previous_hash
  );
  new.immutable := true;
  return new;
end;
$$;

create or replace function edoc_private.prevent_audit_log_mutation()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  raise exception 'audit_logs is append-only; update/delete is not allowed.';
end;
$$;

drop trigger if exists trg_audit_logs_prepare_hash on public.audit_logs;

update public.audit_logs
set
  previous_hash = coalesce(previous_hash, 'GENESIS'),
  entry_hash = coalesce(entry_hash, edoc_private.audit_log_hash_payload(
    id,
    actor,
    action,
    target_type,
    target_id,
    ip,
    device,
    detail,
    created_at,
    coalesce(previous_hash, 'GENESIS')
  )),
  immutable = true
where entry_hash is null;

create trigger trg_audit_logs_prepare_hash
before insert on public.audit_logs
for each row execute function edoc_private.prepare_audit_log_hash();

drop trigger if exists trg_audit_logs_no_update on public.audit_logs;
create trigger trg_audit_logs_no_update
before update on public.audit_logs
for each row execute function edoc_private.prevent_audit_log_mutation();

drop trigger if exists trg_audit_logs_no_delete on public.audit_logs;
create trigger trg_audit_logs_no_delete
before delete on public.audit_logs
for each row execute function edoc_private.prevent_audit_log_mutation();

create or replace view public.audit_log_chain_check
with (security_invoker = true)
as
select
  id,
  created_at,
  previous_hash,
  entry_hash,
  edoc_private.audit_log_hash_payload(id, actor, action, target_type, target_id, ip, device, detail, created_at, previous_hash) = entry_hash as hash_valid
from public.audit_logs;

grant select on public.audit_log_chain_check to authenticated;

drop policy if exists "authenticated read documents by role scope" on public.documents;
create policy "authenticated read documents by role scope"
on public.documents for select
to authenticated
using (edoc_private.document_can_view(id, owner, department, direction, status, security_level));

drop policy if exists "authenticated insert documents by role" on public.documents;
create policy "authenticated insert documents by role"
on public.documents for insert
to authenticated
with check (
  edoc_private.current_user_role() in ('主任', '執行長', '行政部主任', '人資', '會計', '總務', '業務助理')
  and (
    security_level not in ('密', '機密', '極機密', '絕對機密')
    or edoc_private.current_user_role() in ('主任', '執行長', '行政部主任')
  )
);

drop policy if exists "authenticated update documents by role scope" on public.documents;
create policy "authenticated update documents by role scope"
on public.documents for update
to authenticated
using (edoc_private.document_can_manage(id, owner, department, direction, status, security_level, 'sign'))
with check (edoc_private.document_can_view(id, owner, department, direction, status, security_level));

drop policy if exists "authenticated read attachments by document scope" on public.attachments;
create policy "authenticated read attachments by document scope"
on public.attachments for select
to authenticated
using (
  exists (
    select 1
    from public.documents d
    where d.id = attachments.document_id
      and edoc_private.document_can_view(d.id, d.owner, d.department, d.direction, d.status, d.security_level)
  )
);

drop policy if exists "authenticated read attachment security" on public.attachment_security;
drop policy if exists "service role manages attachment security" on public.attachment_security;
create policy "authenticated read attachment security by document scope"
on public.attachment_security for select
to authenticated
using (
  exists (
    select 1
    from public.documents d
    where d.id = attachment_security.document_id
      and edoc_private.document_can_view(d.id, d.owner, d.department, d.direction, d.status, d.security_level)
      and (
        attachment_security.confidential_level not in ('密', '機密', '極機密', '絕對機密')
        or edoc_private.has_document_acl(d.id, 'download')
        or edoc_private.current_user_role() in ('主任', '執行長', '行政部主任')
      )
  )
);

drop policy if exists "authenticated read file objects" on public.file_objects;
create policy "authenticated read file objects by document scope"
on public.file_objects for select
to authenticated
using (
  document_id is null
  or exists (
    select 1
    from public.documents d
    where d.id = file_objects.document_id
      and edoc_private.document_can_view(d.id, d.owner, d.department, d.direction, d.status, d.security_level)
      and (
        file_objects.purpose not in ('confidential_original', 'confidential_attachment')
        or edoc_private.has_document_acl(d.id, 'download')
        or edoc_private.current_user_role() in ('主任', '執行長', '行政部主任')
      )
  )
);

drop policy if exists "authenticated read pdf versions" on public.pdf_versions;
create policy "authenticated read pdf versions by document scope"
on public.pdf_versions for select
to authenticated
using (
  exists (
    select 1
    from public.documents d
    where d.id = pdf_versions.document_id
      and edoc_private.document_can_view(d.id, d.owner, d.department, d.direction, d.status, d.security_level)
      and (
        pdf_versions.version_type <> 'after_seal'
        or edoc_private.has_document_acl(d.id, 'download')
        or edoc_private.current_user_role() in ('主任', '執行長', '行政部主任', '總務')
      )
  )
);

drop policy if exists "authenticated read seal applications" on public.seal_applications;
create policy "authenticated read seal applications by document scope"
on public.seal_applications for select
to authenticated
using (
  exists (
    select 1
    from public.documents d
    where d.id = seal_applications.document_id
      and edoc_private.document_can_view(d.id, d.owner, d.department, d.direction, d.status, d.security_level)
      and (
        edoc_private.current_user_role() in ('主任', '執行長', '行政部主任', '總務')
        or edoc_private.has_document_acl(d.id, 'seal')
      )
  )
);

drop policy if exists "authenticated read electronic signatures" on public.electronic_signatures;
drop policy if exists "service role manages electronic signatures" on public.electronic_signatures;
create policy "authenticated read electronic signatures by document scope"
on public.electronic_signatures for select
to authenticated
using (
  exists (
    select 1
    from public.documents d
    where d.id = electronic_signatures.document_id
      and edoc_private.document_can_view(d.id, d.owner, d.department, d.direction, d.status, d.security_level)
      and (
        edoc_private.current_user_role() in ('主任', '執行長', '行政部主任', '總務')
        or edoc_private.has_document_acl(d.id, 'sign')
      )
  )
);

drop policy if exists "authenticated read signing certificates" on public.signing_certificates;
drop policy if exists "service role manages signing certificates" on public.signing_certificates;
create policy "authenticated read active signing certificates"
on public.signing_certificates for select
to authenticated
using (
  status = '啟用'
  and (
    owner in (edoc_private.current_user_role(), edoc_private.current_user_name(), edoc_private.current_user_email())
    or edoc_private.current_user_role() in ('主任', '執行長', '行政部主任')
  )
);

drop policy if exists "authenticated read exchange tasks by document scope" on public.exchange_tasks;
create policy "authenticated read exchange tasks by document scope"
on public.exchange_tasks for select
to authenticated
using (
  exists (
    select 1
    from public.documents d
    where d.id = exchange_tasks.document_id
      and edoc_private.document_can_view(d.id, d.owner, d.department, d.direction, d.status, d.security_level)
  )
);

drop policy if exists "authenticated read exchange events by document scope" on public.exchange_events;
create policy "authenticated read exchange events by document scope"
on public.exchange_events for select
to authenticated
using (
  document_id is null
  or exists (
    select 1
    from public.documents d
    where d.id = exchange_events.document_id
      and edoc_private.document_can_view(d.id, d.owner, d.department, d.direction, d.status, d.security_level)
  )
);

drop policy if exists "authenticated read document acl by scope" on public.document_acl;
drop policy if exists "service role manages document acl" on public.document_acl;
create policy "authenticated read document acl by scope"
on public.document_acl for select
to authenticated
using (
  exists (
    select 1
    from public.documents d
    where d.id = document_acl.document_id
      and edoc_private.document_can_view(d.id, d.owner, d.department, d.direction, d.status, d.security_level)
  )
);

drop policy if exists "authenticated read document acl events by audit role" on public.document_acl_events;
drop policy if exists "service role manages document acl events" on public.document_acl_events;
create policy "authenticated read document acl events by audit role"
on public.document_acl_events for select
to authenticated
using (
  edoc_private.current_user_role() in ('主任', '執行長', '行政部主任')
  or edoc_private.has_permission('audit.view')
);

drop policy if exists "authenticated insert audit logs append only" on public.audit_logs;
create policy "authenticated insert audit logs append only"
on public.audit_logs for insert
to authenticated
with check (edoc_private.current_user_role() is not null);

drop policy if exists "authenticated read audit logs by audit role" on public.audit_logs;
create policy "authenticated read audit logs by audit role"
on public.audit_logs for select
to authenticated
using (
  edoc_private.current_user_role() in ('主任', '執行長', '行政部主任')
  or edoc_private.has_permission('audit.view')
  or actor in (edoc_private.current_user_name(), edoc_private.current_user_email())
);

drop policy if exists "authenticated read file access logs" on public.file_access_logs;
drop policy if exists "service role manages file access logs" on public.file_access_logs;
create policy "authenticated read file access logs by audit role"
on public.file_access_logs for select
to authenticated
using (
  edoc_private.current_user_role() in ('主任', '執行長', '行政部主任')
  or actor in (edoc_private.current_user_name(), edoc_private.current_user_email())
);

drop policy if exists "authenticated read retention policies" on public.document_retention_policies;
create policy "authenticated read retention policies"
on public.document_retention_policies for select
to authenticated
using (true);

drop policy if exists "authenticated read retention events by audit role" on public.document_retention_events;
create policy "authenticated read retention events by audit role"
on public.document_retention_events for select
to authenticated
using (
  edoc_private.current_user_role() in ('主任', '執行長', '行政部主任')
  or edoc_private.has_permission('audit.view')
);

drop policy if exists "authenticated insert retention events" on public.document_retention_events;
create policy "authenticated insert retention events"
on public.document_retention_events for insert
to authenticated
with check (
  edoc_private.current_user_role() in ('主任', '執行長', '行政部主任')
  or edoc_private.has_permission('audit.view')
);

update public.documents
set security_level = coalesce(security_level, '普通')
where security_level is null;

update public.documents
set retention_until = null
where retention_until is null;

insert into public.audit_logs (id, actor, action, target_type, target_id, detail)
values (
  'AUD-DBSEC-20260523-001',
  'Migration',
  '正式資料庫權限政策',
  'database',
  '202605230010_formal_database_security_policy',
  '已建立 RLS、密件 row-level 隔離、保留年限政策、audit log hash chain 與 append-only trigger。'
)
on conflict (id) do nothing;

grant execute on all functions in schema edoc_private to authenticated;
