-- Explicit EDOC seal-owner policy; never infer legal/institution type from names.
create table if not exists public.company_seal_policies (
  id text primary key,
  company_id text not null unique references public.companies(id) on delete restrict,
  owner_kind text not null default 'unclassified'
    check (owner_kind in ('company', 'institution', 'unclassified')),
  updated_by text not null,
  created_at text not null,
  updated_at text not null
);
alter table public.company_seal_policies enable row level security;
alter table public.company_seal_policies force row level security;
create unique index if not exists company_seal_policies_company_uidx on public.company_seal_policies(company_id);
revoke all on public.company_seal_policies from public, anon, authenticated;
grant select, insert, update on public.company_seal_policies to service_role;
create policy company_seal_policies_backend_only on public.company_seal_policies
  for all to service_role using (true) with check (true);

insert into public.seal_reference_options (id, option_type, code, name, description, sort_order, status, created_at, updated_at)
values
  ('SREF-CAT-CONTINUOUS', 'category', 'continuous_seal', '連續章', '單枚連續章，須依原章明確校準寬高。', 40, 'active', now()::text, now()::text),
  ('SREF-SIZE-SINGLE', 'size', 'single_seal', '單枚', '連續章不套用大小章的正方形尺寸。', 30, 'active', now()::text, now()::text)
on conflict (option_type, code) do update set name=excluded.name, description=excluded.description, status='active', updated_at=excluded.updated_at;
update public.seal_reference_options set name='公司章', updated_at=now()::text where option_type='category' and code='establishment_seal';
update public.seal_reference_options set name='圖記章', updated_at=now()::text where option_type='category' and code='official_seal';
-- Codes and existing seal/file IDs remain immutable historical evidence.
alter table public.company_seals add constraint company_seals_continuous_size_pair
  check ((seal_category='continuous_seal') = (seal_size_type='single_seal')) not valid;

create or replace function public.edoc_set_company_seal_policy(p_company_id text, p_owner_kind text, p_actor text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare v_before text; v_timestamp text := pg_catalog.now()::text;
begin
  if p_owner_kind not in ('company','institution','unclassified') or p_owner_kind is null then
    raise exception 'invalid_seal_owner_kind';
  end if;
  if p_actor is null or pg_catalog.btrim(p_actor)='' or pg_catalog.length(p_actor)>256 then
    raise exception 'seal_policy_actor_required';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('seal-policy:'||p_company_id,0));
  perform 1 from public.companies where id=p_company_id and status='active'
    and source_system='finance' and nullif(pg_catalog.btrim(finance_entity_id),'') is not null;
  if not found then raise exception 'seal_company_not_finance_linked'; end if;
  select owner_kind into v_before from public.company_seal_policies where company_id=p_company_id;
  insert into public.company_seal_policies(id,company_id,owner_kind,updated_by,created_at,updated_at)
    values(p_company_id,p_company_id,p_owner_kind,p_actor,v_timestamp,v_timestamp)
    on conflict(company_id) do update set owner_kind=excluded.owner_kind,updated_by=excluded.updated_by,updated_at=excluded.updated_at;
  insert into public.seal_usage_logs(id,action,actor_id,detail,created_at)
    values('SLOG-'||pg_catalog.gen_random_uuid()::text,'classify_seal_owner',p_actor,
      'company_id='||p_company_id||';owner_kind='||coalesce(v_before,'unclassified')||'->'||p_owner_kind,v_timestamp);
  insert into public.audit_logs(id,actor,action,target_type,target_id,detail,event_type,module_code,resource_type,resource_id,result,severity,created_at)
    values('AUD-'||pg_catalog.gen_random_uuid()::text,p_actor,'classify_seal_owner','company_seal_policies',p_company_id,
      'owner_kind='||coalesce(v_before,'unclassified')||'->'||p_owner_kind,'classify_seal_owner','seals','company_seal_policies',p_company_id,'success','info',v_timestamp);
  return pg_catalog.jsonb_build_object('company_id',p_company_id,'owner_kind',p_owner_kind);
end $$;
revoke all on function public.edoc_set_company_seal_policy(text,text,text) from public,anon,authenticated;
grant execute on function public.edoc_set_company_seal_policy(text,text,text) to service_role;

create or replace function public.edoc_company_seal_dimensions_are_valid(p_size_type text,p_pixel_width integer,p_pixel_height integer,p_source_aspect_ratio numeric,p_render_width_mm numeric,p_render_height_mm numeric,p_policy_version text,p_dimension_validated boolean)
returns boolean language sql immutable set search_path='' as $$
select coalesce((coalesce(p_dimension_validated,false) and p_pixel_width>0 and p_pixel_height>0
  and p_source_aspect_ratio>0 and p_render_width_mm>0 and p_render_height_mm>0
  and abs(p_source_aspect_ratio-p_pixel_width::numeric/nullif(p_pixel_height::numeric,0))<=0.000001
  and abs((p_pixel_width::numeric/nullif(p_pixel_height::numeric,0))/nullif(p_render_width_mm/nullif(p_render_height_mm,0),0)-1.0)<=0.01
  and (
    (p_policy_version in ('continuous-seal-v1-calibrated','official-seal-v1-calibrated')
      and ((p_policy_version='continuous-seal-v1-calibrated' and p_size_type='single_seal')
           or (p_policy_version='official-seal-v1-calibrated' and p_size_type in ('large_seal','small_seal')))
      -- Technical bounds only, not a legal size standard or suggested calibration.
      and p_render_width_mm between 1.0 and 200.0 and p_render_height_mm between 1.0 and 200.0
      and p_pixel_width>=ceil(p_render_width_mm/25.4*250)
      and p_pixel_height>=ceil(p_render_height_mm/25.4*250))
    or
    (abs(p_render_width_mm-p_render_height_mm)<=0.01
      and least(p_pixel_width,p_pixel_height)>=ceil(greatest(p_render_width_mm,p_render_height_mm)/25.4*250)
      and (
        (p_policy_version='institution-seal-v1'
          and ((p_size_type='large_seal' and abs(p_render_width_mm-30.0)<=0.000001 and abs(p_render_height_mm-30.0)<=0.000001)
               or(p_size_type='small_seal' and abs(p_render_width_mm-18.0)<=0.000001 and abs(p_render_height_mm-18.0)<=0.000001)))
        or (p_policy_version='institution-seal-v2-calibrated'
          and ((p_size_type='large_seal' and p_render_width_mm between 25.0 and 35.0 and p_render_height_mm between 25.0 and 35.0)
               or(p_size_type='small_seal' and p_render_width_mm between 15.0 and 22.0 and p_render_height_mm between 15.0 and 22.0)))
      ))
  )),false);
$$;
revoke all on function public.edoc_company_seal_dimensions_are_valid(text,integer,integer,numeric,numeric,numeric,text,boolean) from public,anon,authenticated;
grant execute on function public.edoc_company_seal_dimensions_are_valid(text,integer,integer,numeric,numeric,numeric,text,boolean) to service_role;

create or replace function public.edoc_enforce_seal_category_geometry()
returns trigger language plpgsql security invoker set search_path='' as $$
declare v_category text; v_size text;
begin
  select seal_category,seal_size_type into v_category,v_size from public.company_seals where id=new.seal_id;
  if not found then raise exception 'seal_not_found'; end if;
  if (new.dimension_policy_version='continuous-seal-v1-calibrated'
      and (v_category<>'continuous_seal' or v_size<>'single_seal'))
    or (new.dimension_policy_version='official-seal-v1-calibrated'
      and (v_category<>'official_seal' or v_size not in ('large_seal','small_seal')))
    or (v_category='continuous_seal' and new.dimension_policy_version is distinct from 'continuous-seal-v1-calibrated') then
    raise exception 'seal_category_dimension_policy_mismatch';
  end if;
  return new;
end $$;
revoke all on function public.edoc_enforce_seal_category_geometry() from public,anon,authenticated;
revoke all on function public.edoc_enforce_seal_category_geometry() from service_role;
create trigger edoc_company_seal_category_geometry before insert or update of seal_id,dimension_policy_version,is_current
  on public.company_seal_files for each row execute function public.edoc_enforce_seal_category_geometry();

create or replace function public.edoc_lock_uploaded_seal_category()
returns trigger language plpgsql security invoker set search_path='' as $$
begin
  if new.seal_category is distinct from old.seal_category and exists(
    select 1 from public.company_seal_files where seal_id=old.id
  ) then raise exception 'seal_category_locked_after_upload'; end if;
  return new;
end $$;
revoke all on function public.edoc_lock_uploaded_seal_category() from public,anon,authenticated,service_role;
create trigger edoc_lock_uploaded_seal_category before update of seal_category on public.company_seals
  for each row execute function public.edoc_lock_uploaded_seal_category();

-- Preserve existing atomic version locks/audit and historical geometry replay.
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
     or p_dimension_policy_version not in ('institution-seal-v2-calibrated','official-seal-v1-calibrated','continuous-seal-v1-calibrated') then
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
  if v_target.dimension_policy_version not in ('institution-seal-v2-calibrated','official-seal-v1-calibrated','continuous-seal-v1-calibrated')
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

CREATE OR REPLACE FUNCTION public.edoc_enforce_company_seal_position_dimensions()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare
  v_size_type text;
  v_category text;
  v_file public.company_seal_files%rowtype;
  v_expected_width_pt numeric;
  v_expected_height_pt numeric;
begin
  select seal.seal_size_type, seal.seal_category into v_size_type, v_category
    from public.company_seals as seal
   where seal.id = new.seal_id;
  if not found then
    raise exception using errcode = 'P0002', message = 'seal_not_found';
  end if;

  if nullif(new.locked_seal_file_id, '') is null then
    if v_category in ('official_seal','continuous_seal') then
      raise exception using errcode='22023',message='seal_manual_calibration_required';
    end if;
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
     or (v_file.dimension_policy_version='official-seal-v1-calibrated' and v_category<>'official_seal')
     or (v_file.dimension_policy_version='continuous-seal-v1-calibrated' and (v_category<>'continuous_seal' or v_size_type<>'single_seal'))
     or (v_category='continuous_seal' and v_file.dimension_policy_version<>'continuous-seal-v1-calibrated')
     or not public.edoc_company_seal_dimensions_are_valid(
       v_size_type, v_file.pixel_width, v_file.pixel_height,
       v_file.source_aspect_ratio, v_file.render_width_mm,
       v_file.render_height_mm, v_file.dimension_policy_version,
       v_file.dimension_validated
     )
     or not exists (
       select 1 from public.file_objects as object
       where object.id = v_file.file_object_id
         and object.sha256 = v_file.file_hash
         and object.size_bytes = v_file.file_size
         and object.mime_type = v_file.file_mime_type
         and object.storage_key = v_file.file_storage_key
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

