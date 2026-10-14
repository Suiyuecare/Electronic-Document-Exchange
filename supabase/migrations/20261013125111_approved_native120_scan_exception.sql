-- Six user-approved raw DCT native crops, no recompression or resizing.
-- Exact source SHA256: 4426fcf11ca7cd45ed8d2e942b137c7f5f4ac6efc585ad87078faaadf941487c
-- Existing 22-image permit and generic 250 DPI geometry are unchanged.
create or replace function public.edoc_approved_native120_scan_dimensions_are_valid(p_seal_id text,p_company_id text,p_category text,p_size_type text,p_sha256 text,p_pixel_width integer,p_pixel_height integer,p_source_aspect_ratio numeric,p_render_width_mm numeric,p_render_height_mm numeric,p_policy_version text,p_dimension_validated boolean)
returns boolean language sql immutable security invoker set search_path='' as $$
select coalesce(p_dimension_validated,false) and p_policy_version='native-scan-120dpi-20261013-v1'
 and exists(select 1 from (values
('f429854fb082934e93961458628e041b2682f94d89d726b92cc73fd1c042f8e7','CO-007','CSEAL-CO-007-EST-L','establishment_seal','large_seal',125,124,26.458,26.247),
('4011a30985893479a30bdf2c6481cf60b9c22ce122e22a094898cebffa2082a6','CO-007','CSEAL-CO-007-EST-S','establishment_seal','small_seal',66,65,13.97,13.758),
('5249fba51127b75b0918bb33b2b46dfa6317fb1b79109309ed4f4312a119997f','FINCO-AE264D87483E','CSEAL-FINCO-AE264D87483E-official_seal-large_seal','official_seal','large_seal',123,123,26.035,26.035),
('d68ff63f4fd1e4a6674676640a6c1ac8fd11c019f5db8ce8473fbaec975be002','FINCO-AE264D87483E','CSEAL-FINCO-AE264D87483E-official_seal-small_seal','official_seal','small_seal',69,68,14.605,14.393),
('100e26e3c369aa9e2c09df8ce60fba994148158826279d86d62867c56421d947','FINCO-D7FAD93DE9AE','CSEAL-FINCO-D7FAD93DE9AE-official_seal-large_seal','official_seal','large_seal',156,156,33.02,33.02),
('0c8f7d93ee3cf50ad88065a7ffb22ebef7bfc7026353821589113da75b90d02a','FINCO-D7FAD93DE9AE','CSEAL-FINCO-D7FAD93DE9AE-official_seal-small_seal','official_seal','small_seal',70,69,14.817,14.605)
 ) as a(digest,company_id,seal_id,category,size_type,pw,ph,mw,mh)
 where a.digest=pg_catalog.lower(p_sha256) and a.company_id=p_company_id and a.seal_id=p_seal_id
 and a.category=p_category and a.size_type=p_size_type
 and a.pw=p_pixel_width and a.ph=p_pixel_height
 and abs(a.mw-p_render_width_mm)<=0.000001 and abs(a.mh-p_render_height_mm)<=0.000001
 and abs(p_source_aspect_ratio-a.pw::numeric/a.ph)<=0.000001);
$$;
revoke all on function public.edoc_approved_native120_scan_dimensions_are_valid(text,text,text,text,text,integer,integer,numeric,numeric,numeric,text,boolean) from public,anon,authenticated;
grant execute on function public.edoc_approved_native120_scan_dimensions_are_valid(text,text,text,text,text,integer,integer,numeric,numeric,numeric,text,boolean) to service_role;

create or replace function public.edoc_company_seal_file_dimensions_are_valid(p_seal_id text,p_company_id text,p_category text,p_size_type text,p_sha256 text,p_pixel_width integer,p_pixel_height integer,p_source_aspect_ratio numeric,p_render_width_mm numeric,p_render_height_mm numeric,p_policy_version text,p_dimension_validated boolean)
returns boolean language sql immutable security invoker set search_path='' as $$
select coalesce(public.edoc_approved_native120_scan_dimensions_are_valid(p_seal_id,p_company_id,p_category,p_size_type,p_sha256,p_pixel_width,p_pixel_height,p_source_aspect_ratio,p_render_width_mm,p_render_height_mm,p_policy_version,p_dimension_validated),false)
 or coalesce(public.edoc_approved_original_scan_dimensions_are_valid(p_seal_id,p_company_id,p_category,p_size_type,p_sha256,p_pixel_width,p_pixel_height,p_source_aspect_ratio,p_render_width_mm,p_render_height_mm,p_policy_version,p_dimension_validated),false)
 or (p_policy_version not in ('original-scan-200dpi-20260914-v1','native-scan-120dpi-20261013-v1') and public.edoc_company_seal_dimensions_are_valid(p_size_type,p_pixel_width,p_pixel_height,p_source_aspect_ratio,p_render_width_mm,p_render_height_mm,p_policy_version,p_dimension_validated));
$$;
revoke all on function public.edoc_company_seal_file_dimensions_are_valid(text,text,text,text,text,integer,integer,numeric,numeric,numeric,text,boolean) from public,anon,authenticated;
grant execute on function public.edoc_company_seal_file_dimensions_are_valid(text,text,text,text,text,integer,integer,numeric,numeric,numeric,text,boolean) to service_role;

create or replace function public.edoc_enforce_approved_native120_scan_file()
returns trigger language plpgsql security invoker set search_path='' as $$
declare s public.company_seals%rowtype;
begin
 if new.dimension_policy_version='native-scan-120dpi-20261013-v1' then
  select * into s from public.company_seals where id=new.seal_id;
  if not found or new.file_mime_type is distinct from 'image/png' or not
   public.edoc_approved_native120_scan_dimensions_are_valid(s.id,s.company_id,s.seal_category,s.seal_size_type,new.file_hash,new.pixel_width,new.pixel_height,new.source_aspect_ratio,new.render_width_mm,new.render_height_mm,new.dimension_policy_version,new.dimension_validated) then
   raise exception 'approved_native120_scan_metadata_invalid';
  end if;
 end if;
 return new;
end $$;
revoke all on function public.edoc_enforce_approved_native120_scan_file() from public,anon,authenticated,service_role;
create trigger edoc_approved_native120_scan_file before insert or update on public.company_seal_files
 for each row execute function public.edoc_enforce_approved_native120_scan_file();

-- Create only the two missing institutional small slots. This does not set
-- owner policies, register files, open a permit or activate any seal version.
-- Fresh empty catalogs may not yet have Finance owners; never invent them.
do $native120_small_slots$
declare r record; s public.company_seals%rowtype; c public.companies%rowtype;
begin
 for r in select * from (values
  ('FINCO-AE264D87483E','E9','CSEAL-FINCO-AE264D87483E-official_seal-small_seal'),
  ('FINCO-D7FAD93DE9AE','E8','CSEAL-FINCO-D7FAD93DE9AE-official_seal-small_seal')
 ) a(company_id,finance_entity_id,seal_id) loop
  select * into c from public.companies where id=r.company_id for share;
  if found then
   if c.status is distinct from 'active' or c.source_system is distinct from 'finance'
      or c.finance_entity_id is distinct from r.finance_entity_id then
    raise exception 'native120_small_slot_owner_mismatch';
   end if;
   select * into s from public.company_seals where id=r.seal_id for update;
   if found and (s.company_id is distinct from r.company_id or s.seal_category is distinct from 'official_seal'
       or s.seal_size_type is distinct from 'small_seal' or s.is_active is distinct from true) then
    raise exception 'native120_small_slot_conflict';
   end if;
   insert into public.company_seals(id,company_id,seal_name,seal_category,seal_size_type,purpose_description,is_active,created_by,created_at,updated_at)
    values(r.seal_id,r.company_id,'圖記章（小章）','official_seal','small_seal','使用原始掃描核定尺寸；僅 exact source 登錄後可用。',true,
     'system:codex-operator-import',pg_catalog.now()::text,pg_catalog.now()::text)
    on conflict(id) do nothing;
  end if;
 end loop;
end $native120_small_slots$;

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
     or p_dimension_policy_version not in ('institution-seal-v2-calibrated','official-seal-v1-calibrated','continuous-seal-v1-calibrated','original-scan-200dpi-20260914-v1','native-scan-120dpi-20261013-v1') then
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
  if not public.edoc_company_seal_file_dimensions_are_valid(
    v_seal.id,v_seal.company_id,v_seal.seal_category,v_seal.seal_size_type,p_sha256, p_pixel_width, p_pixel_height,
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
  if v_target.dimension_policy_version not in ('institution-seal-v2-calibrated','official-seal-v1-calibrated','continuous-seal-v1-calibrated','original-scan-200dpi-20260914-v1','native-scan-120dpi-20261013-v1')
     or not public.edoc_company_seal_file_dimensions_are_valid(
       v_seal.id,v_seal.company_id,v_seal.seal_category,v_seal.seal_size_type,v_target.file_hash, v_target.pixel_width, v_target.pixel_height,
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
  v_company_id text;
  v_file public.company_seal_files%rowtype;
  v_expected_width_pt numeric;
  v_expected_height_pt numeric;
begin
  select seal.seal_size_type, seal.seal_category, seal.company_id into v_size_type, v_category, v_company_id
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
     or not public.edoc_company_seal_file_dimensions_are_valid(
       new.seal_id,v_company_id,v_category,v_size_type,v_file.file_hash, v_file.pixel_width, v_file.pixel_height,
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


-- Temporary operator permit is controlled separately from file attestation.
-- No permit is opened by this migration; an explicitly authorized operator
-- must configure the short-lived batch through the administrative connection.
create table public.approved_native120_scan_import_batches (
 batch_id text primary key check(batch_id='native-scan-120dpi-20261013-v1'),
 source_pdf_sha256 text not null check(source_pdf_sha256='4426fcf11ca7cd45ed8d2e942b137c7f5f4ac6efc585ad87078faaadf941487c'),
 key_sha256 text not null check(key_sha256 ~ '^[0-9a-f]{64}$'),
 started_at_epoch bigint not null,
 expires_at_epoch bigint not null check(expires_at_epoch>started_at_epoch and expires_at_epoch-started_at_epoch<=3600),
 status text not null check(status in ('open','completed','revoked')),
 completed_file_count integer not null default 0 check(completed_file_count between 0 and 6),
 updated_at timestamptz not null default pg_catalog.now()
);
alter table public.approved_native120_scan_import_batches enable row level security;
alter table public.approved_native120_scan_import_batches force row level security;
revoke all on public.approved_native120_scan_import_batches from public,anon,authenticated,service_role;
grant select on public.approved_native120_scan_import_batches to service_role;
create policy native120_scan_import_backend_read on public.approved_native120_scan_import_batches
 for select to service_role using(true);

create or replace function public.edoc_import_approved_native120_scan_file(
 p_seal_id text,p_object_id text,p_file_id text,p_storage_key text,p_file_name text,
 p_file_size bigint,p_sha256 text,p_pixel_width integer,p_pixel_height integer,
 p_ratio numeric,p_width_mm numeric,p_height_mm numeric,p_scan_engine text,p_scan_signature text,
 p_source_pdf_sha256 text,p_key_sha256 text)
returns jsonb language plpgsql security definer set search_path='' set lock_timeout='5s' as $$
declare b public.approved_native120_scan_import_batches%rowtype;
 s public.company_seals%rowtype; f public.company_seal_files%rowtype;
 result jsonb; owner_kind text; desired_kind text; total integer; current_epoch bigint;
 actor constant text := 'system:codex-operator-import';
begin
 select * into b from public.approved_native120_scan_import_batches where batch_id='native-scan-120dpi-20261013-v1' for update;
 current_epoch := pg_catalog.floor(extract(epoch from pg_catalog.clock_timestamp()))::bigint;
 if not found or b.status<>'open' or b.key_sha256 is distinct from p_key_sha256
  or b.source_pdf_sha256 is distinct from p_source_pdf_sha256
  or current_epoch<b.started_at_epoch or current_epoch>=b.expires_at_epoch then
  raise exception 'native120_scan_import_permit_closed';
 end if;
 select * into s from public.company_seals where id=p_seal_id for update;
 if not found or s.is_active is distinct from true then raise exception 'native120_scan_import_slot_unavailable'; end if;
 perform 1 from public.companies where id=s.company_id and status='active' and source_system='finance' and finance_entity_id=case s.company_id when 'CO-007' then 'E7' when 'FINCO-AE264D87483E' then 'E9' when 'FINCO-D7FAD93DE9AE' then 'E8' else null end for share;
 if not found then
  raise exception 'seal_company_not_finance_linked';
 end if;
 if p_source_pdf_sha256 is distinct from '4426fcf11ca7cd45ed8d2e942b137c7f5f4ac6efc585ad87078faaadf941487c' or not
  public.edoc_approved_native120_scan_dimensions_are_valid(s.id,s.company_id,s.seal_category,s.seal_size_type,p_sha256,p_pixel_width,p_pixel_height,p_ratio,p_width_mm,p_height_mm,'native-scan-120dpi-20261013-v1',true)
  or p_object_id is distinct from 'FILE-APPROVED-'||pg_catalog.lower(p_sha256)
  or p_file_id is distinct from 'SFILE-APPROVED-'||pg_catalog.lower(p_sha256)
  or p_file_name is distinct from pg_catalog.lower(p_sha256)||'.png'
  or p_storage_key is distinct from 'seal-vault/seals/'||s.id||'/SEAL-VAULT/'||p_object_id||'.png'
  or nullif(pg_catalog.btrim(p_scan_engine),'') is null or nullif(pg_catalog.btrim(p_scan_signature),'') is null then
  raise exception 'native120_scan_import_metadata_invalid';
 end if;
 desired_kind := case s.company_id when 'CO-007' then 'company'
  when 'FINCO-AE264D87483E' then 'institution' when 'FINCO-D7FAD93DE9AE' then 'institution' else null end;
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('seal-policy:'||s.company_id,0));
 select p.owner_kind into owner_kind from public.company_seal_policies p where p.company_id=s.company_id;
 if desired_kind is null or (owner_kind is not null and owner_kind not in ('unclassified',desired_kind)) then
  raise exception 'native120_scan_import_owner_policy_conflict';
 end if;
 if (select count(*) from public.company_seal_files where seal_id=s.id and is_current=true)>1 then
  raise exception 'native120_scan_import_current_conflict';
 end if;
 select * into f from public.company_seal_files where seal_id=s.id and is_current=true for update;
 if found then
  if not public.edoc_approved_native120_scan_dimensions_are_valid(s.id,s.company_id,s.seal_category,s.seal_size_type,f.file_hash,f.pixel_width,f.pixel_height,f.source_aspect_ratio,f.render_width_mm,f.render_height_mm,f.dimension_policy_version,f.dimension_validated)
   or pg_catalog.lower(f.file_hash) is distinct from pg_catalog.lower(p_sha256)
   or not exists(select 1 from public.file_objects o where o.id=f.file_object_id and o.sha256=f.file_hash
    and o.size_bytes=f.file_size and o.mime_type='image/png' and o.mime_type=f.file_mime_type
    and o.storage_key=f.file_storage_key and o.bucket='edoc-seal-vault'
    and pg_catalog.lower(coalesce(o.scan_status,'')) in ('已通過','clean','passed')) then
   raise exception 'native120_scan_import_current_conflict';
  end if;
  result := pg_catalog.jsonb_build_object('file',pg_catalog.to_jsonb(f),'import_status','already_registered');
 else
  result := public.edoc_create_company_seal_file_version(p_object_id,p_file_id,s.id,p_storage_key,p_file_name,'image/png',p_file_size,p_sha256,p_pixel_width,p_pixel_height,p_ratio,p_width_mm,p_height_mm,'native-scan-120dpi-20261013-v1',actor,p_scan_engine,p_scan_signature,'SLOG-APPROVED-'||pg_catalog.lower(p_sha256),'AUD-APPROVED-'||pg_catalog.lower(p_sha256));
  result := result||pg_catalog.jsonb_build_object('import_status','registered');
 end if;
 if owner_kind is null or owner_kind='unclassified' then
  perform public.edoc_set_company_seal_policy(s.company_id,desired_kind,actor);
 end if;
 insert into public.audit_logs(id,actor,action,target_type,target_id,detail,event_type,module_code,result,created_at)
  values('AUD-IMPORT-'||p_key_sha256||'-'||pg_catalog.lower(p_sha256),actor,'operator_import_native120_scan','company_seal_files',result->'file'->>'id',
   'source_pdf_sha256='||p_source_pdf_sha256||';batch='||b.batch_id,'operator_import_native120_scan','seals','success',pg_catalog.clock_timestamp()::text)
  on conflict(id) do nothing;
 select count(distinct files.seal_id) into total from public.company_seal_files files join public.company_seals seals on seals.id=files.seal_id
  join public.companies companies on companies.id=seals.company_id and companies.status='active'
   and companies.source_system='finance' and companies.finance_entity_id=case seals.company_id when 'CO-007' then 'E7' when 'FINCO-AE264D87483E' then 'E9' when 'FINCO-D7FAD93DE9AE' then 'E8' else null end
  join public.company_seal_policies policies on policies.company_id=seals.company_id
   and policies.owner_kind=case seals.company_id when 'CO-007' then 'company'
    when 'FINCO-AE264D87483E' then 'institution' when 'FINCO-D7FAD93DE9AE' then 'institution' else null end
  join public.file_objects objects on objects.id=files.file_object_id and objects.sha256=files.file_hash
   and objects.size_bytes=files.file_size and objects.mime_type='image/png' and objects.mime_type=files.file_mime_type
   and objects.storage_key=files.file_storage_key and objects.bucket='edoc-seal-vault'
   and pg_catalog.lower(coalesce(objects.scan_status,'')) in ('已通過','clean','passed')
  where seals.is_active=true and files.is_current=true and public.edoc_approved_native120_scan_dimensions_are_valid(seals.id,seals.company_id,seals.seal_category,seals.seal_size_type,files.file_hash,files.pixel_width,files.pixel_height,files.source_aspect_ratio,files.render_width_mm,files.render_height_mm,files.dimension_policy_version,files.dimension_validated);
 update public.approved_native120_scan_import_batches set completed_file_count=total,
  status=case when total=6 then 'completed' else 'open' end,updated_at=pg_catalog.clock_timestamp()
  where batch_id=b.batch_id;
 if pg_catalog.floor(extract(epoch from pg_catalog.clock_timestamp()))::bigint>=b.expires_at_epoch then
  raise exception 'native120_scan_import_permit_closed';
 end if;
 return result||pg_catalog.jsonb_build_object('completed_file_count',total,'batch_status',case when total=6 then 'completed' else 'open' end);
end $$;
revoke all on function public.edoc_import_approved_native120_scan_file(text,text,text,text,text,bigint,text,integer,integer,numeric,numeric,numeric,text,text,text,text) from public,anon,authenticated;
grant execute on function public.edoc_import_approved_native120_scan_file(text,text,text,text,text,bigint,text,integer,integer,numeric,numeric,numeric,text,text,text,text) to service_role;
