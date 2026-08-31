-- A signed Supabase TUS capability is path-scoped and short-lived, but it is
-- not individually revocable. Finalized editor records must bind atomically
-- to a server-created immutable path. A durable cleanup job keeps both the
-- capability-writable staging path and any pre-commit promoted object under
-- lifecycle control until the token has expired.

do $version_gate$
begin
  if pg_catalog.current_setting('server_version_num')::integer < 160000 then
    raise exception using
      errcode = '0A000',
      message = 'editor_storage_migration_requires_postgresql_16';
  end if;
end;
$version_gate$;

create table if not exists public.official_document_editor_storage_jobs (
  id text primary key,
  asset_id text not null unique
    references public.official_document_editor_assets(id) on delete restrict,
  document_id text not null
    references public.official_documents(id) on delete restrict,
  staging_bucket text not null,
  staging_path text not null unique,
  final_bucket text not null,
  final_path text not null unique,
  expected_sha256 text not null,
  expected_size_bytes bigint not null,
  token_expires_at text not null,
  status text not null default 'pending',
  lease_token text not null default '',
  lease_expires_at text not null default '',
  final_file_object_id text
    references public.file_objects(id) on delete restrict,
  attempt_count integer not null default 0,
  last_error_code text not null default '',
  created_at text not null default pg_catalog.to_char(pg_catalog.now(), 'YYYY-MM-DD HH24:MI:SS'),
  updated_at text not null default pg_catalog.to_char(pg_catalog.now(), 'YYYY-MM-DD HH24:MI:SS'),
  cleaned_at text,
  constraint official_editor_storage_job_sha256_check
    check (expected_sha256 ~ '^[A-Fa-f0-9]{64}$'),
  constraint official_editor_storage_job_size_check
    check (expected_size_bytes > 0),
  constraint official_editor_storage_job_path_check
    check (
      staging_bucket = 'edoc-private'
      and pg_catalog.btrim(staging_path) <> ''
      and final_bucket = 'edoc-private'
      and pg_catalog.btrim(final_path) <> ''
      and pg_catalog.btrim(token_expires_at) <> ''
      and token_expires_at ~
        '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}$'
      and pg_catalog.pg_input_is_valid(
        token_expires_at,
        'timestamp without time zone'
      )
      and staging_path <> final_path
      and pg_catalog.left(
            staging_path,
            pg_catalog.length('editor/' || document_id || '/' || asset_id || '-')
          ) = 'editor/' || document_id || '/' || asset_id || '-'
      and pg_catalog.left(
            final_path,
            pg_catalog.length(
              'editor-final/' || document_id || '/' || asset_id || '/' ||
              pg_catalog.upper(expected_sha256) || '-'
            )
          ) =
          'editor-final/' || document_id || '/' || asset_id || '/' ||
          pg_catalog.upper(expected_sha256) || '-'
    ),
  constraint official_editor_storage_job_attempt_check
    check (attempt_count >= 0),
  constraint official_editor_storage_job_error_code_check
    check (
      last_error_code = ''
      or last_error_code ~ '^[a-z0-9_:-]{1,96}$'
    ),
  constraint official_editor_storage_job_status_check
    check (
      status in (
        'pending', 'promoting', 'committed',
        'cleaning', 'cleaned', 'cleanup_failed'
      )
    ),
  constraint official_editor_storage_job_lease_check
    check (
      (
        status in ('promoting', 'cleaning')
        and lease_token ~ '^[A-F0-9]{32}$'
        and lease_expires_at ~
          '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}$'
        and pg_catalog.pg_input_is_valid(
          lease_expires_at,
          'timestamp without time zone'
        )
      )
      or (
        status not in ('promoting', 'cleaning')
        and lease_token = ''
        and lease_expires_at = ''
      )
    ),
  constraint official_editor_storage_job_commit_file_check
    check (status <> 'committed' or final_file_object_id is not null),
  constraint official_editor_storage_job_cleaned_at_check
    check ((status = 'cleaned') = (cleaned_at is not null))
);

create index if not exists idx_official_editor_storage_jobs_due
on public.official_document_editor_storage_jobs(status, token_expires_at);

create index if not exists idx_official_editor_storage_jobs_document
on public.official_document_editor_storage_jobs(document_id, created_at);

create index if not exists idx_official_editor_storage_jobs_final_file
on public.official_document_editor_storage_jobs(final_file_object_id)
where final_file_object_id is not null;

alter table public.official_document_editor_storage_jobs enable row level security;
alter table public.official_document_editor_storage_jobs force row level security;
revoke all on table public.official_document_editor_storage_jobs
from public, anon, authenticated;
grant select, insert, update on table public.official_document_editor_storage_jobs
to service_role;

-- Backfill lifecycle rows for already-conforming assets. Existing finalized
-- staging references remain a hard blocker below because SQL cannot safely
-- perform the required byte-level Storage copy.
insert into public.official_document_editor_storage_jobs (
  id, asset_id, document_id, staging_bucket, staging_path,
  final_bucket, final_path, expected_sha256, expected_size_bytes,
  token_expires_at, status, final_file_object_id,
  attempt_count, last_error_code, created_at, updated_at, cleaned_at
)
select
  'EDOC-STORAGE-' || asset.id,
  asset.id,
  asset.document_id,
  'edoc-private',
  'editor/' || asset.document_id || '/' || asset.id || '-' ||
    pg_catalog.regexp_replace(asset.file_name, '^.*/', ''),
  file_object.bucket,
  file_object.storage_key,
  pg_catalog.upper(asset.sha256),
  asset.size_bytes,
  pg_catalog.to_char(
    case
      when pg_catalog.pg_input_is_valid(
        asset.created_at,
        'timestamp without time zone'
      ) then asset.created_at::timestamp + interval '2 hours'
    end,
    'YYYY-MM-DD"T"HH24:MI:SS'
  ),
  'committed',
  file_object.id,
  0,
  '',
  asset.created_at,
  pg_catalog.to_char(pg_catalog.now(), 'YYYY-MM-DD HH24:MI:SS'),
  null
from public.official_document_editor_assets asset
join public.file_objects file_object on file_object.id = asset.file_object_id
where asset.asset_kind in ('source_pdf', 'import_pdf', 'image')
  and asset.upload_status = 'finalized'
  and asset.sha256 ~ '^[A-Fa-f0-9]{64}$'
  and pg_catalog.lower(asset.expected_sha256) = pg_catalog.lower(asset.sha256)
  and asset.size_bytes > 0
  and asset.created_at ~
    '^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}'
  and pg_catalog.pg_input_is_valid(
    asset.created_at,
    'timestamp without time zone'
  )
  and file_object.document_id = asset.document_id
  and file_object.bucket = 'edoc-private'
  and file_object.storage_provider = 'supabase'
  and pg_catalog.left(
        file_object.storage_key,
        pg_catalog.length(
          'editor-final/' || asset.document_id || '/' || asset.id || '/' ||
          pg_catalog.upper(asset.sha256) || '-'
        )
      ) =
      'editor-final/' || asset.document_id || '/' || asset.id || '/' ||
      pg_catalog.upper(asset.sha256) || '-'
  and pg_catalog.lower(file_object.sha256) = pg_catalog.lower(asset.sha256)
  and file_object.size_bytes = asset.size_bytes
  and not exists (
    select 1
    from public.official_document_editor_storage_jobs existing_job
    where existing_job.asset_id = asset.id
  )
on conflict (asset_id) do nothing;

insert into public.official_document_editor_storage_jobs (
  id, asset_id, document_id, staging_bucket, staging_path,
  final_bucket, final_path, expected_sha256, expected_size_bytes,
  token_expires_at, status, final_file_object_id,
  attempt_count, last_error_code, created_at, updated_at, cleaned_at
)
select
  'EDOC-STORAGE-' || asset.id,
  asset.id,
  asset.document_id,
  asset.storage_bucket,
  asset.storage_path,
  'edoc-private',
  'editor-final/' || asset.document_id || '/' || asset.id || '/' ||
    pg_catalog.upper(asset.expected_sha256) || '-' ||
    pg_catalog.regexp_replace(asset.file_name, '^.*/', ''),
  pg_catalog.upper(asset.expected_sha256),
  asset.size_bytes,
  pg_catalog.to_char(
    case
      when pg_catalog.pg_input_is_valid(
        asset.created_at,
        'timestamp without time zone'
      ) then asset.created_at::timestamp + interval '2 hours'
    end,
    'YYYY-MM-DD"T"HH24:MI:SS'
  ),
  'pending',
  null,
  0,
  '',
  asset.created_at,
  pg_catalog.to_char(pg_catalog.now(), 'YYYY-MM-DD HH24:MI:SS'),
  null
from public.official_document_editor_assets asset
where asset.asset_kind in ('source_pdf', 'import_pdf', 'image')
  and asset.upload_status <> 'finalized'
  and asset.expected_sha256 ~ '^[A-Fa-f0-9]{64}$'
  and asset.size_bytes > 0
  and asset.created_at ~
    '^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}'
  and pg_catalog.pg_input_is_valid(
    asset.created_at,
    'timestamp without time zone'
  )
  and asset.storage_bucket = 'edoc-private'
  and pg_catalog.btrim(asset.storage_path) <> ''
  and not exists (
    select 1
    from public.official_document_editor_storage_jobs existing_job
    where existing_job.asset_id = asset.id
  )
on conflict (asset_id) do nothing;

create or replace function public.edoc_guard_editor_storage_job()
returns trigger
language plpgsql
set search_path to ''
as $function$
declare
  v_asset public.official_document_editor_assets%rowtype;
  v_file public.file_objects%rowtype;
  v_expected_final_path text;
begin
  if tg_op = 'INSERT' then
    select asset.*
    into v_asset
    from public.official_document_editor_assets asset
    where asset.id = new.asset_id;

    v_expected_final_path :=
      'editor-final/' || new.document_id || '/' || new.asset_id || '/' ||
      pg_catalog.upper(new.expected_sha256) || '-' ||
      pg_catalog.regexp_replace(v_asset.file_name, '^.*/', '');
    if v_asset.id is null
       or v_asset.document_id is distinct from new.document_id
       or v_asset.asset_kind not in ('source_pdf', 'import_pdf', 'image')
       or v_asset.upload_status = 'finalized'
       or new.staging_bucket is distinct from 'edoc-private'
       or new.staging_bucket is distinct from v_asset.storage_bucket
       or new.staging_path is distinct from v_asset.storage_path
       or new.final_bucket is distinct from 'edoc-private'
       or new.final_path is distinct from v_expected_final_path
       or pg_catalog.lower(new.expected_sha256)
            is distinct from pg_catalog.lower(v_asset.expected_sha256)
       or new.expected_size_bytes is distinct from v_asset.size_bytes
       or new.status is distinct from 'pending'
       or new.lease_token <> ''
       or new.lease_expires_at <> ''
       or new.final_file_object_id is not null
       or new.attempt_count <> 0
       or new.last_error_code <> ''
       or new.cleaned_at is not null then
      raise exception using
        errcode = '22023',
        message = 'editor_storage_job_binding_invalid';
    end if;
    return new;
  end if;

  -- Path, digest, object identity and capability expiry are append-only
  -- evidence. Cleanup may update only lifecycle fields.
  if new.id is distinct from old.id
     or new.asset_id is distinct from old.asset_id
     or new.document_id is distinct from old.document_id
     or new.staging_bucket is distinct from old.staging_bucket
     or new.staging_path is distinct from old.staging_path
     or new.final_bucket is distinct from old.final_bucket
     or new.final_path is distinct from old.final_path
     or new.expected_sha256 is distinct from old.expected_sha256
     or new.expected_size_bytes is distinct from old.expected_size_bytes
     or new.token_expires_at is distinct from old.token_expires_at
     or new.created_at is distinct from old.created_at
     or new.attempt_count < old.attempt_count
     or (old.final_file_object_id is not null
         and new.final_file_object_id is distinct from old.final_file_object_id) then
    raise exception using
      errcode = '55000',
      message = 'editor_storage_job_binding_immutable';
  end if;

  if old.final_file_object_id is null
     and new.final_file_object_id is not null
     and not (
       old.status = 'promoting'
       and new.status = 'committed'
       and pg_catalog.pg_trigger_depth() >= 2
     ) then
    raise exception using
      errcode = '55000',
      message = 'editor_storage_job_file_binding_forbidden';
  end if;

  if old.status = 'cleaned' and new is distinct from old then
    raise exception using
      errcode = '55000',
      message = 'editor_storage_job_cleaned_immutable';
  end if;

  if new.status in ('promoting', 'cleaning') then
    if (case
         when not pg_catalog.pg_input_is_valid(
           new.lease_expires_at,
           'timestamp without time zone'
         ) then true
         else new.lease_expires_at::timestamp <= pg_catalog.clock_timestamp()
       end)
       or (
         (
           old.status not in ('promoting', 'cleaning')
           or new.lease_token is distinct from old.lease_token
           or new.status is distinct from old.status
         )
         and new.attempt_count <= old.attempt_count
       ) then
      raise exception using
        errcode = '22023',
        message = 'editor_storage_job_lease_invalid';
    end if;
  end if;

  if old.status in ('promoting', 'cleaning')
     and old.lease_token <> ''
     and old.lease_expires_at::timestamp > pg_catalog.clock_timestamp()
     and new.status in ('promoting', 'cleaning')
     and (
       new.lease_token is distinct from old.lease_token
       or new.status is distinct from old.status
     ) then
    raise exception using
      errcode = '55000',
      message = 'editor_storage_job_lease_active';
  end if;

  if new.status = 'committed' then
    if old.status is distinct from 'promoting'
       or pg_catalog.pg_trigger_depth() < 2
       or new.final_file_object_id is null
       or old.lease_token = ''
       or not pg_catalog.pg_input_is_valid(
            old.lease_expires_at,
            'timestamp without time zone'
          )
       or old.lease_expires_at::timestamp < pg_catalog.clock_timestamp()
       or new.lease_token <> ''
       or new.lease_expires_at <> '' then
      raise exception using
        errcode = '55000',
        message = 'editor_storage_job_commit_forbidden';
    end if;
    select file_object.*
    into v_file
    from public.file_objects file_object
    where file_object.id = new.final_file_object_id;
    if v_file.id is null
       or v_file.document_id is distinct from new.document_id
       or v_file.bucket is distinct from new.final_bucket
       or v_file.storage_key is distinct from new.final_path
       or pg_catalog.lower(v_file.sha256)
            is distinct from pg_catalog.lower(new.expected_sha256)
       or v_file.size_bytes is distinct from new.expected_size_bytes
       or v_file.storage_provider is distinct from 'supabase' then
      raise exception using
        errcode = '22023',
        message = 'editor_storage_job_commit_invalid';
    end if;
  elsif old.status = 'pending'
        and new.status not in ('pending', 'promoting', 'cleaning') then
    raise exception using
      errcode = '55000',
      message = 'editor_storage_job_transition_invalid';
  elsif old.status = 'promoting'
        and new.status not in ('promoting', 'pending', 'committed', 'cleaning') then
    raise exception using
      errcode = '55000',
      message = 'editor_storage_job_transition_invalid';
  elsif old.status = 'committed'
        and new.status not in ('committed', 'cleaning') then
    raise exception using
      errcode = '55000',
      message = 'editor_storage_job_transition_invalid';
  elsif old.status = 'cleanup_failed'
        and new.status not in ('cleanup_failed', 'cleaning') then
    raise exception using
      errcode = '55000',
      message = 'editor_storage_job_transition_invalid';
  elsif old.status = 'cleaning'
        and new.status not in ('cleaning', 'cleaned', 'cleanup_failed') then
    raise exception using
      errcode = '55000',
      message = 'editor_storage_job_transition_invalid';
  end if;

  if new.status = 'cleaned' and new.cleaned_at is null then
    raise exception using
      errcode = '22023',
      message = 'editor_storage_job_cleaned_at_required';
  end if;
  return new;
end;
$function$;

alter function public.edoc_guard_editor_storage_job() owner to postgres;
revoke all on function public.edoc_guard_editor_storage_job()
from public, anon, authenticated;

drop trigger if exists trg_edoc_guard_editor_storage_job
on public.official_document_editor_storage_jobs;

create trigger trg_edoc_guard_editor_storage_job
before insert or update
on public.official_document_editor_storage_jobs
for each row
execute function public.edoc_guard_editor_storage_job();

create or replace function public.edoc_bind_finalized_editor_asset_storage()
returns trigger
language plpgsql
security definer
set search_path to ''
as $function$
declare
  v_file public.file_objects%rowtype;
  v_job public.official_document_editor_storage_jobs%rowtype;
  v_expected_prefix text;
begin
  if tg_op = 'DELETE' then
    if old.asset_kind in ('source_pdf', 'import_pdf', 'image')
       and old.upload_status = 'finalized' then
      raise exception using
        errcode = '55000',
        message = 'editor_finalized_asset_immutable';
    end if;
    return old;
  end if;

  -- Once finalized, every field is immutable. This also prevents a stale
  -- failure request from downgrading a successful concurrent finalize.
  if tg_op = 'UPDATE'
     and old.asset_kind in ('source_pdf', 'import_pdf', 'image')
     and old.upload_status = 'finalized' then
    if new is distinct from old then
      raise exception using
        errcode = '55000',
        message = 'editor_finalized_asset_immutable';
    end if;
    return new;
  end if;

  if new.asset_kind not in ('source_pdf', 'import_pdf', 'image')
     or new.upload_status is distinct from 'finalized' then
    return new;
  end if;

  if new.file_object_id is null
     or new.sha256 !~ '^[A-Fa-f0-9]{64}$'
     or new.size_bytes <= 0 then
    raise exception using
      errcode = '22023',
      message = 'editor_immutable_file_object_required';
  end if;

  -- Browser-uploaded source assets are always created as pending first so a
  -- lifecycle job exists before bytes can be promoted. A direct finalized
  -- insert bypasses that invariant and is rejected.
  if tg_op <> 'UPDATE' then
    raise exception using
      errcode = '22023',
      message = 'editor_finalized_asset_insert_forbidden';
  end if;

  select file_object.*
  into v_file
  from public.file_objects file_object
  where file_object.id = new.file_object_id;

  select storage_job.*
  into v_job
  from public.official_document_editor_storage_jobs storage_job
  where storage_job.asset_id = new.id
    and storage_job.document_id = new.document_id
  for update;

  v_expected_prefix :=
    'editor-final/' || new.document_id || '/' || new.id || '/' ||
    pg_catalog.upper(new.sha256) || '-';
  if v_file.id is null
     or v_job.id is null
     or v_job.status is distinct from 'promoting'
     or v_job.lease_token = ''
     or not pg_catalog.pg_input_is_valid(
          v_job.lease_expires_at,
          'timestamp without time zone'
        )
     or v_job.lease_expires_at::timestamp < pg_catalog.clock_timestamp()
     or v_file.document_id is distinct from new.document_id
     or v_file.bucket is distinct from 'edoc-private'
     or v_file.storage_provider is distinct from 'supabase'
     or pg_catalog.left(v_file.storage_key, pg_catalog.length(v_expected_prefix))
          is distinct from v_expected_prefix
     or pg_catalog.lower(v_file.sha256) is distinct from pg_catalog.lower(new.sha256)
     or v_file.size_bytes is distinct from new.size_bytes
     or v_job.staging_bucket is distinct from old.storage_bucket
     or v_job.staging_path is distinct from old.storage_path
     or v_job.final_bucket is distinct from v_file.bucket
     or v_job.final_path is distinct from v_file.storage_key
     or pg_catalog.lower(v_job.expected_sha256) is distinct from pg_catalog.lower(new.sha256)
     or pg_catalog.lower(new.expected_sha256) is distinct from pg_catalog.lower(new.sha256)
     or v_job.expected_size_bytes is distinct from new.size_bytes then
    raise exception using
      errcode = '22023',
      message = 'editor_immutable_storage_required';
  end if;

  new.storage_bucket := v_file.bucket;
  new.storage_path := v_file.storage_key;
  update public.official_document_editor_storage_jobs
  set status = 'committed',
      lease_token = '',
      lease_expires_at = '',
      final_file_object_id = v_file.id,
      last_error_code = '',
      updated_at = pg_catalog.to_char(pg_catalog.now(), 'YYYY-MM-DD HH24:MI:SS')
  where id = v_job.id;
  return new;
end;
$function$;

alter function public.edoc_bind_finalized_editor_asset_storage() owner to postgres;
revoke all on function public.edoc_bind_finalized_editor_asset_storage()
from public, anon, authenticated;

-- Existing records are accepted only when they already point at an immutable
-- server-created file object and have a durable committed cleanup job.
update public.official_document_editor_assets asset
set storage_bucket = file_object.bucket,
    storage_path = file_object.storage_key
from public.file_objects file_object
where asset.file_object_id = file_object.id
  and asset.asset_kind in ('source_pdf', 'import_pdf', 'image')
  and asset.upload_status = 'finalized'
  and file_object.bucket = 'edoc-private'
  and file_object.storage_provider = 'supabase'
  and pg_catalog.left(
        file_object.storage_key,
        pg_catalog.length(
          'editor-final/' || asset.document_id || '/' || asset.id || '/' ||
          pg_catalog.upper(asset.sha256) || '-'
        )
      ) =
      'editor-final/' || asset.document_id || '/' || asset.id || '/' ||
      pg_catalog.upper(asset.sha256) || '-'
  and pg_catalog.lower(file_object.sha256) = pg_catalog.lower(asset.sha256)
  and file_object.size_bytes = asset.size_bytes;

do $block$
begin
  if exists (
    select 1
    from public.official_document_editor_assets asset
    left join public.file_objects file_object on file_object.id = asset.file_object_id
    left join public.official_document_editor_storage_jobs storage_job
      on storage_job.asset_id = asset.id
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
        or asset.storage_bucket is distinct from file_object.bucket
        or asset.storage_path is distinct from file_object.storage_key
        or storage_job.id is null
        or storage_job.status is distinct from 'committed'
        or storage_job.final_file_object_id is distinct from file_object.id
        or storage_job.final_bucket is distinct from file_object.bucket
        or storage_job.final_path is distinct from file_object.storage_key
        or pg_catalog.lower(storage_job.expected_sha256)
             is distinct from pg_catalog.lower(asset.sha256)
        or storage_job.expected_size_bytes is distinct from asset.size_bytes
      )
  ) then
    raise exception using
      errcode = '55000',
      message = 'existing_editor_assets_require_immutable_promotion';
  end if;

  if exists (
    select 1
    from public.official_document_editor_assets asset
    left join public.official_document_editor_storage_jobs storage_job
      on storage_job.asset_id = asset.id
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
        or storage_job.id is null
        or storage_job.document_id is distinct from asset.document_id
        or storage_job.staging_bucket is distinct from asset.storage_bucket
        or storage_job.staging_path is distinct from asset.storage_path
        or storage_job.final_bucket is distinct from 'edoc-private'
        or storage_job.final_path is distinct from
             'editor-final/' || asset.document_id || '/' || asset.id || '/' ||
             pg_catalog.upper(asset.expected_sha256) || '-' ||
             pg_catalog.regexp_replace(asset.file_name, '^.*/', '')
        or pg_catalog.lower(storage_job.expected_sha256)
             is distinct from pg_catalog.lower(asset.expected_sha256)
        or storage_job.expected_size_bytes is distinct from asset.size_bytes
        or storage_job.status is distinct from 'pending'
        or storage_job.final_file_object_id is not null
      )
  ) then
    raise exception using
      errcode = '55000',
      message = 'existing_editor_uploads_require_audited_cleanup';
  end if;
end;
$block$;

drop trigger if exists trg_edoc_bind_finalized_editor_asset_storage
on public.official_document_editor_assets;

create trigger trg_edoc_bind_finalized_editor_asset_storage
before insert or update or delete
on public.official_document_editor_assets
for each row
execute function public.edoc_bind_finalized_editor_asset_storage();

comment on function public.edoc_bind_finalized_editor_asset_storage() is
'Atomically binds finalized editor assets to server-created immutable paths, prevents downgrade or mutation, and commits their durable Storage cleanup job.';
