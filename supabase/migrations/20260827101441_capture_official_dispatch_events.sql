-- Capture the immutable dispatch history from the canonical dispatch record.
--
-- The application may continue to create and complete dispatch records through
-- the existing SECURITY DEFINER RPCs, or patch allowed metadata through the
-- backend.  Events are database-owned evidence: service_role keeps SELECT only
-- and cannot forge, update, or delete an event through PostgREST.
-- This migration does not enable or contact a formal exchange provider.

begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

create schema if not exists edoc_private;
revoke all on schema edoc_private from public, anon, authenticated;

create or replace function edoc_private.capture_official_dispatch_event_v1()
returns trigger
language plpgsql
security definer
set search_path to ''
as $function$
declare
  v_event_sequence bigint;
  v_event_type text;
  v_changed_fields text[] := array[]::text[];
  v_snapshot_sha256 text;
  v_database_actor text;
begin
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('edoc:dispatch-event:' || new.id, 0)
  );

  select coalesce(
           pg_catalog.max(event.event_sequence),
           0::bigint
         ) + 1
    into v_event_sequence
    from public.official_document_dispatch_events as event
   where event.dispatch_record_id = new.id;

  if tg_op = 'INSERT' then
    v_event_type := 'created';
    v_changed_fields := array[
      'dispatch_method',
      'dispatch_owner_type',
      'dispatch_owner_user_id',
      'dispatch_status',
      'external_official_document_number',
      'dispatch_date',
      'recipient',
      'recipient_contact',
      'dispatch_note',
      'proof_file_id',
      'completed_at'
    ]::text[];
  else
    select coalesce(
             pg_catalog.array_agg(change.field_name order by change.ordinal),
             array[]::text[]
           )
      into v_changed_fields
      from (
        values
          (1, 'dispatch_method', old.dispatch_method is distinct from new.dispatch_method),
          (2, 'dispatch_owner_type', old.dispatch_owner_type is distinct from new.dispatch_owner_type),
          (3, 'dispatch_owner_user_id', old.dispatch_owner_user_id is distinct from new.dispatch_owner_user_id),
          (4, 'dispatch_status', old.dispatch_status is distinct from new.dispatch_status),
          (5, 'external_official_document_number', old.external_official_document_number is distinct from new.external_official_document_number),
          (6, 'dispatch_date', old.dispatch_date is distinct from new.dispatch_date),
          (7, 'recipient', old.recipient is distinct from new.recipient),
          (8, 'recipient_contact', old.recipient_contact is distinct from new.recipient_contact),
          (9, 'dispatch_note', old.dispatch_note is distinct from new.dispatch_note),
          (10, 'proof_file_id', old.proof_file_id is distinct from new.proof_file_id),
          (11, 'completed_at', old.completed_at is distinct from new.completed_at)
      ) as change(ordinal, field_name, has_changed)
     where change.has_changed;

    if pg_catalog.cardinality(v_changed_fields) = 0 then
      return new;
    end if;

    v_event_type := case
      when old.dispatch_status is distinct from new.dispatch_status
        then 'status_transition'
      else 'metadata_updated'
    end;
  end if;

  v_snapshot_sha256 := pg_catalog.encode(
    extensions.digest(
      pg_catalog.convert_to(
        pg_catalog.jsonb_build_object(
          'id', new.id,
          'document_id', new.document_id,
          'dispatch_method', new.dispatch_method,
          'dispatch_owner_type', new.dispatch_owner_type,
          'dispatch_owner_user_id', new.dispatch_owner_user_id,
          'dispatch_status', new.dispatch_status,
          'external_official_document_number', new.external_official_document_number,
          'dispatch_date', new.dispatch_date,
          'recipient', new.recipient,
          'recipient_contact', new.recipient_contact,
          'dispatch_note', new.dispatch_note,
          'proof_file_id', new.proof_file_id,
          'created_by', new.created_by,
          'created_at', new.created_at,
          'updated_at', new.updated_at,
          'completed_at', new.completed_at
        )::text,
        'UTF8'
      ),
      'sha256'
    ),
    'hex'
  );

  v_database_actor := coalesce(
    nullif(pg_catalog.current_setting('request.jwt.claim.sub', true), ''),
    nullif(pg_catalog.current_setting('request.jwt.claim.role', true), ''),
    session_user::text
  );

  insert into public.official_document_dispatch_events (
    id,
    dispatch_record_id,
    document_id,
    event_sequence,
    event_type,
    from_status,
    to_status,
    changed_fields,
    record_snapshot_sha256,
    database_actor,
    created_at
  ) values (
    'ODDEVT-' || pg_catalog.upper(
      pg_catalog.substr(
        pg_catalog.md5(new.id || ':' || v_event_sequence::text),
        1,
        24
      )
    ),
    new.id,
    new.document_id,
    v_event_sequence,
    v_event_type,
    case when tg_op = 'UPDATE' then old.dispatch_status else null end,
    new.dispatch_status,
    v_changed_fields,
    v_snapshot_sha256,
    v_database_actor,
    pg_catalog.clock_timestamp()
  );

  return new;
end;
$function$;

alter function edoc_private.capture_official_dispatch_event_v1() owner to postgres;
revoke all on function edoc_private.capture_official_dispatch_event_v1()
  from public, anon, authenticated, service_role;

-- A dispatch record's identity is canonical.  Metadata and status may change,
-- but moving the record to another document or rewriting its creator/time
-- would disconnect it from prior event evidence.
create or replace function edoc_private.guard_official_dispatch_identity_v1()
returns trigger
language plpgsql
security definer
set search_path to ''
as $function$
begin
  if old.id is distinct from new.id
     or old.document_id is distinct from new.document_id
     or old.created_by is distinct from new.created_by
     or old.created_at is distinct from new.created_at then
    raise exception using
      errcode = '42501',
      message = 'official_dispatch_identity_immutable';
  end if;
  return new;
end;
$function$;

alter function edoc_private.guard_official_dispatch_identity_v1()
  owner to postgres;
revoke all on function edoc_private.guard_official_dispatch_identity_v1()
  from public, anon, authenticated, service_role;

-- Keep trigger installation and the legacy baseline in one write-blocking
-- window.  This prevents an old record from changing between the baseline
-- existence check and trigger activation.
lock table public.official_document_dispatch_records in share row exclusive mode;
lock table public.official_document_dispatch_events in share row exclusive mode;

drop trigger if exists trg_official_dispatch_record_identity_guard
  on public.official_document_dispatch_records;
create trigger trg_official_dispatch_record_identity_guard
before update of id, document_id, created_by, created_at
on public.official_document_dispatch_records
for each row
when (
  old.id is distinct from new.id
  or old.document_id is distinct from new.document_id
  or old.created_by is distinct from new.created_by
  or old.created_at is distinct from new.created_at
)
execute function edoc_private.guard_official_dispatch_identity_v1();

drop trigger if exists trg_official_dispatch_record_capture_insert
  on public.official_document_dispatch_records;
create trigger trg_official_dispatch_record_capture_insert
after insert on public.official_document_dispatch_records
for each row
execute function edoc_private.capture_official_dispatch_event_v1();

drop trigger if exists trg_official_dispatch_record_capture_update
  on public.official_document_dispatch_records;
create trigger trg_official_dispatch_record_capture_update
after update of
  dispatch_method,
  dispatch_owner_type,
  dispatch_owner_user_id,
  dispatch_status,
  external_official_document_number,
  dispatch_date,
  recipient,
  recipient_contact,
  dispatch_note,
  proof_file_id,
  completed_at
on public.official_document_dispatch_records
for each row
when (
  old.dispatch_method is distinct from new.dispatch_method
  or old.dispatch_owner_type is distinct from new.dispatch_owner_type
  or old.dispatch_owner_user_id is distinct from new.dispatch_owner_user_id
  or old.dispatch_status is distinct from new.dispatch_status
  or old.external_official_document_number is distinct from new.external_official_document_number
  or old.dispatch_date is distinct from new.dispatch_date
  or old.recipient is distinct from new.recipient
  or old.recipient_contact is distinct from new.recipient_contact
  or old.dispatch_note is distinct from new.dispatch_note
  or old.proof_file_id is distinct from new.proof_file_id
  or old.completed_at is distinct from new.completed_at
)
execute function edoc_private.capture_official_dispatch_event_v1();

-- Existing records predate event capture.  Preserve them as an explicit
-- baseline snapshot rather than inventing a historical creation/transition.
insert into public.official_document_dispatch_events (
  id,
  dispatch_record_id,
  document_id,
  event_sequence,
  event_type,
  from_status,
  to_status,
  changed_fields,
  record_snapshot_sha256,
  database_actor,
  created_at
)
select
  'ODDEVT-' || pg_catalog.upper(
    pg_catalog.substr(pg_catalog.md5(record.id || ':1'), 1, 24)
  ),
  record.id,
  record.document_id,
  1,
  'baseline_snapshot',
  null,
  record.dispatch_status,
  array[]::text[],
  pg_catalog.encode(
    extensions.digest(
      pg_catalog.convert_to(
        pg_catalog.jsonb_build_object(
          'id', record.id,
          'document_id', record.document_id,
          'dispatch_method', record.dispatch_method,
          'dispatch_owner_type', record.dispatch_owner_type,
          'dispatch_owner_user_id', record.dispatch_owner_user_id,
          'dispatch_status', record.dispatch_status,
          'external_official_document_number', record.external_official_document_number,
          'dispatch_date', record.dispatch_date,
          'recipient', record.recipient,
          'recipient_contact', record.recipient_contact,
          'dispatch_note', record.dispatch_note,
          'proof_file_id', record.proof_file_id,
          'created_by', record.created_by,
          'created_at', record.created_at,
          'updated_at', record.updated_at,
          'completed_at', record.completed_at
        )::text,
        'UTF8'
      ),
      'sha256'
    ),
    'hex'
  ),
  'migration:20260827101441',
  pg_catalog.clock_timestamp()
from public.official_document_dispatch_records as record
where not exists (
  select 1
  from public.official_document_dispatch_events as event
  where event.dispatch_record_id = record.id
)
order by record.id;

-- Event evidence remains API-read-only.  Trigger execution does not require
-- direct INSERT/UPDATE/DELETE grants for service_role.
revoke insert, update, delete
  on table public.official_document_dispatch_events
  from service_role;

commit;
