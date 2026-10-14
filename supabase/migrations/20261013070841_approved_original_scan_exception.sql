-- User-approved 1:1 original scan exception, limited to exact hashes/slots.
-- No artwork, rows, activation, actor assignment or general DPI relaxation.
-- Source SHA256: 95d90878c71f0efd874de4b0e812daebd536ec23435bb3a5ffb0dde9ed604b2e
create or replace function public.edoc_approved_original_scan_dimensions_are_valid(p_seal_id text,p_company_id text,p_category text,p_size_type text,p_sha256 text,p_pixel_width integer,p_pixel_height integer,p_source_aspect_ratio numeric,p_render_width_mm numeric,p_render_height_mm numeric,p_policy_version text,p_dimension_validated boolean)
returns boolean language sql immutable security invoker set search_path='' as $$
select coalesce(p_dimension_validated,false) and p_policy_version='original-scan-200dpi-20260914-v1'
 and exists(select 1 from (values
('8e47708f7838e097c31a94ee261da349f8fe4d84187da60f923f0b8f5067a0df','FINCO-263DD88BDAAA','CSEAL-FINCO-263DD88BDAAA-establishment_seal-large_seal','establishment_seal','large_seal',235,237,29.845,30.099),
('8a620f14bb6730bbbaa08f8d54a1b3b6872ef2ef0889917692293184f719f416','FINCO-263DD88BDAAA','CSEAL-FINCO-263DD88BDAAA-establishment_seal-small_seal','establishment_seal','small_seal',116,119,14.732,15.113),
('362d7b21d3c0433e1b37f32309dc5e3b87388e7b7d3f4ccc662eea0d8ee9edd6','FINCO-263DD88BDAAA','CSEAL-FINCO-263DD88BDAAA-bank_seal-large_seal','bank_seal','large_seal',236,240,29.972,30.48),
('a760f16ca1f5e29edf141f6f8807865bf3a81aa00a294fdf616ea4eb79d0a6c2','FINCO-263DD88BDAAA','CSEAL-FINCO-263DD88BDAAA-bank_seal-small_seal','bank_seal','small_seal',128,119,16.256,15.113),
('e1b08350f16327a056dd7fcd63bf5033ab833e448010afbd48a805a4e0069dbd','CO-002','CSEAL-CO-002-EST-L','establishment_seal','large_seal',211,207,26.797,26.289),
('ccfb0e087067844a4e7d4afe51fee634c5c572276ca8dd5132f20f58daa1227e','CO-002','CSEAL-CO-002-EST-S','establishment_seal','small_seal',126,124,16.002,15.748),
('48b910ea4ccf6e33191933a5d7029c44eea4eb88a6132b223100e29ef2eb366d','CO-002','CSEAL-CO-002-BANK-L','bank_seal','large_seal',221,213,28.067,27.051),
('baffd6716eaca45d349365e195f751d8889b1e680855ea86421e45d44279ae56','CO-002','CSEAL-CO-002-BANK-S','bank_seal','small_seal',124,123,15.748,15.621),
('33a28ffb114a6fca2855915cbe195252afff001e89cc1e25a033d4c026e8ad6c','CO-004','CSEAL-CO-004-EST-L','establishment_seal','large_seal',205,205,26.035,26.035),
('f2203b43f74e535a613cbdb6e3ce11826fb712a30ac3ed50b866efe1fcc60180','CO-004','CSEAL-CO-004-EST-S','establishment_seal','small_seal',128,131,16.256,16.637),
('b7d5dda2261ea8f07083418d29634f520f65bb3915610ffcd7510e03a8f2bdd5','CO-004','CSEAL-CO-004-BANK-L','bank_seal','large_seal',211,206,26.797,26.162),
('662e7c187bcd55413090cb71edad57880a5f7b622b088a14c3311b937656e3a4','CO-004','CSEAL-CO-004-BANK-S','bank_seal','small_seal',136,138,17.272,17.526),
('c4139a4b9013c582e1ce68ced15828f45a2ea4d96c6c72d224e6fdf362eaa1dd','CO-001','CSEAL-CO-001-EST-L','establishment_seal','large_seal',213,208,27.051,26.416),
('b0b3ebb6cc0bbc0baae2838a5e57d61db0637a4745d3ff79f643054b89bbbdc7','CO-001','CSEAL-CO-001-EST-S','establishment_seal','small_seal',119,116,15.113,14.732),
('c1d4ad0f7618e2cc1275ed5b454a04ada4fe4e01ad56c6fe388061fc5aa11d53','CO-001','CSEAL-CO-001-BANK-L','bank_seal','large_seal',214,208,27.178,26.416),
('4271ba55c9536f7ad808602a3fd7532612f9a3a8d93e4bb611c14211aad12379','CO-001','CSEAL-CO-001-BANK-S','bank_seal','small_seal',148,136,18.796,17.272),
('a300936f86617156c88f0867ffde3cd763381f6e7bea65a2b7345105e18775e7','CO-005','CSEAL-CO-005-BANK-L','bank_seal','large_seal',211,208,26.797,26.416),
('6bac3cb23dbb70702cfa2c19d48fac147b8552babc268dec176474cfe189d69e','CO-005','CSEAL-CO-005-BANK-S','bank_seal','small_seal',148,143,18.796,18.161),
('079e4845086f2af65d9c3d6eeb69349e1822928ed9b7a5c477522c4922a3b16b','CO-005','CSEAL-CO-005-official_seal-large_seal','official_seal','large_seal',448,635,56.896,80.645),
('6fc9c30acf425bc57cc84ec5ee5528f62218b6c265c6c37cb8af11d70631e459','CO-006','CSEAL-CO-006-BANK-L','bank_seal','large_seal',266,264,33.782,33.528),
('107f8cc21b0afae3218f4e354fe6f0a39feb959f85d38b3e306495d63632b64b','CO-006','CSEAL-CO-006-BANK-S','bank_seal','small_seal',123,119,15.621,15.113),
('5a0e37eb44a0df6ff4a4e32dc5b0b1fa086e7901cc835fb658a0c0c10f226b0d','CO-006','CSEAL-CO-006-official_seal-large_seal','official_seal','large_seal',438,609,55.626,77.343)
 ) as a(digest,company_id,seal_id,category,size_type,pw,ph,mw,mh)
 where a.digest=pg_catalog.lower(p_sha256) and a.company_id=p_company_id and a.seal_id=p_seal_id
 and a.category=p_category and a.size_type=p_size_type
 and a.pw=p_pixel_width and a.ph=p_pixel_height
 and abs(a.mw-p_render_width_mm)<=0.000001 and abs(a.mh-p_render_height_mm)<=0.000001
 and abs(p_source_aspect_ratio-a.pw::numeric/a.ph)<=0.000001);
$$;
revoke all on function public.edoc_approved_original_scan_dimensions_are_valid(text,text,text,text,text,integer,integer,numeric,numeric,numeric,text,boolean) from public,anon,authenticated;
grant execute on function public.edoc_approved_original_scan_dimensions_are_valid(text,text,text,text,text,integer,integer,numeric,numeric,numeric,text,boolean) to service_role;

create or replace function public.edoc_company_seal_file_dimensions_are_valid(p_seal_id text,p_company_id text,p_category text,p_size_type text,p_sha256 text,p_pixel_width integer,p_pixel_height integer,p_source_aspect_ratio numeric,p_render_width_mm numeric,p_render_height_mm numeric,p_policy_version text,p_dimension_validated boolean)
returns boolean language sql immutable security invoker set search_path='' as $$
select coalesce(public.edoc_approved_original_scan_dimensions_are_valid(p_seal_id,p_company_id,p_category,p_size_type,p_sha256,p_pixel_width,p_pixel_height,p_source_aspect_ratio,p_render_width_mm,p_render_height_mm,p_policy_version,p_dimension_validated),false)
 or (p_policy_version is distinct from 'original-scan-200dpi-20260914-v1' and public.edoc_company_seal_dimensions_are_valid(p_size_type,p_pixel_width,p_pixel_height,p_source_aspect_ratio,p_render_width_mm,p_render_height_mm,p_policy_version,p_dimension_validated));
$$;
revoke all on function public.edoc_company_seal_file_dimensions_are_valid(text,text,text,text,text,integer,integer,numeric,numeric,numeric,text,boolean) from public,anon,authenticated;
grant execute on function public.edoc_company_seal_file_dimensions_are_valid(text,text,text,text,text,integer,integer,numeric,numeric,numeric,text,boolean) to service_role;

create or replace function public.edoc_enforce_approved_original_scan_file()
returns trigger language plpgsql security invoker set search_path='' as $$
declare s public.company_seals%rowtype;
begin
 if new.dimension_policy_version='original-scan-200dpi-20260914-v1' then
  select * into s from public.company_seals where id=new.seal_id;
  if not found or new.file_mime_type is distinct from 'image/png' or not
   public.edoc_approved_original_scan_dimensions_are_valid(s.id,s.company_id,s.seal_category,s.seal_size_type,new.file_hash,new.pixel_width,new.pixel_height,new.source_aspect_ratio,new.render_width_mm,new.render_height_mm,new.dimension_policy_version,new.dimension_validated) then
   raise exception 'approved_original_scan_metadata_invalid';
  end if;
 end if;
 return new;
end $$;
revoke all on function public.edoc_enforce_approved_original_scan_file() from public,anon,authenticated,service_role;
create trigger edoc_approved_original_scan_file before insert or update on public.company_seal_files
 for each row execute function public.edoc_enforce_approved_original_scan_file();

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
     or p_dimension_policy_version not in ('institution-seal-v2-calibrated','official-seal-v1-calibrated','continuous-seal-v1-calibrated','original-scan-200dpi-20260914-v1') then
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
  if v_target.dimension_policy_version not in ('institution-seal-v2-calibrated','official-seal-v1-calibrated','continuous-seal-v1-calibrated','original-scan-200dpi-20260914-v1')
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
create table public.approved_original_scan_import_batches (
 batch_id text primary key check(batch_id='original-scan-200dpi-20260914-v1'),
 source_pdf_sha256 text not null check(source_pdf_sha256='95d90878c71f0efd874de4b0e812daebd536ec23435bb3a5ffb0dde9ed604b2e'),
 key_sha256 text not null check(key_sha256 ~ '^[0-9a-f]{64}$'),
 started_at_epoch bigint not null,
 expires_at_epoch bigint not null check(expires_at_epoch>started_at_epoch and expires_at_epoch-started_at_epoch<=3600),
 status text not null check(status in ('open','completed','revoked')),
 completed_file_count integer not null default 0 check(completed_file_count between 0 and 22),
 updated_at timestamptz not null default pg_catalog.now()
);
alter table public.approved_original_scan_import_batches enable row level security;
alter table public.approved_original_scan_import_batches force row level security;
revoke all on public.approved_original_scan_import_batches from public,anon,authenticated,service_role;
grant select on public.approved_original_scan_import_batches to service_role;
create policy approved_scan_import_backend_read on public.approved_original_scan_import_batches
 for select to service_role using(true);

create or replace function public.edoc_import_approved_original_scan_file(
 p_seal_id text,p_object_id text,p_file_id text,p_storage_key text,p_file_name text,
 p_file_size bigint,p_sha256 text,p_pixel_width integer,p_pixel_height integer,
 p_ratio numeric,p_width_mm numeric,p_height_mm numeric,p_scan_engine text,p_scan_signature text,
 p_source_pdf_sha256 text,p_key_sha256 text)
returns jsonb language plpgsql security definer set search_path='' set lock_timeout='5s' as $$
declare b public.approved_original_scan_import_batches%rowtype;
 s public.company_seals%rowtype; f public.company_seal_files%rowtype;
 result jsonb; owner_kind text; desired_kind text; total integer; current_epoch bigint;
 actor constant text := 'system:codex-operator-import';
begin
 select * into b from public.approved_original_scan_import_batches where batch_id='original-scan-200dpi-20260914-v1' for update;
 current_epoch := pg_catalog.floor(extract(epoch from pg_catalog.clock_timestamp()))::bigint;
 if not found or b.status<>'open' or b.key_sha256 is distinct from p_key_sha256
  or b.source_pdf_sha256 is distinct from p_source_pdf_sha256
  or current_epoch<b.started_at_epoch or current_epoch>=b.expires_at_epoch then
  raise exception 'approved_scan_import_permit_closed';
 end if;
 select * into s from public.company_seals where id=p_seal_id for update;
 if not found or s.is_active is distinct from true then raise exception 'approved_scan_import_slot_unavailable'; end if;
 perform 1 from public.companies where id=s.company_id and status='active' and source_system='finance' and nullif(finance_entity_id,'') is not null for share;
 if not found then
  raise exception 'seal_company_not_finance_linked';
 end if;
 if p_source_pdf_sha256 is distinct from '95d90878c71f0efd874de4b0e812daebd536ec23435bb3a5ffb0dde9ed604b2e' or not
  public.edoc_approved_original_scan_dimensions_are_valid(s.id,s.company_id,s.seal_category,s.seal_size_type,p_sha256,p_pixel_width,p_pixel_height,p_ratio,p_width_mm,p_height_mm,'original-scan-200dpi-20260914-v1',true)
  or p_object_id is distinct from 'FILE-APPROVED-'||pg_catalog.lower(p_sha256)
  or p_file_id is distinct from 'SFILE-APPROVED-'||pg_catalog.lower(p_sha256)
  or p_file_name is distinct from pg_catalog.lower(p_sha256)||'.png'
  or p_storage_key is distinct from 'seal-vault/seals/'||s.id||'/SEAL-VAULT/'||p_object_id||'.png'
  or nullif(pg_catalog.btrim(p_scan_engine),'') is null or nullif(pg_catalog.btrim(p_scan_signature),'') is null then
  raise exception 'approved_scan_import_metadata_invalid';
 end if;
 desired_kind := case s.company_id when 'CO-005' then 'institution' when 'CO-006' then 'institution'
  when 'CO-001' then 'company' when 'CO-002' then 'company' when 'CO-004' then 'company'
  when 'FINCO-263DD88BDAAA' then 'company' else null end;
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('seal-policy:'||s.company_id,0));
 select p.owner_kind into owner_kind from public.company_seal_policies p where p.company_id=s.company_id;
 if desired_kind is null or (owner_kind is not null and owner_kind not in ('unclassified',desired_kind)) then
  raise exception 'approved_scan_import_owner_policy_conflict';
 end if;
 if (select count(*) from public.company_seal_files where seal_id=s.id and is_current=true)>1 then
  raise exception 'approved_scan_import_current_conflict';
 end if;
 select * into f from public.company_seal_files where seal_id=s.id and is_current=true for update;
 if found then
  if not public.edoc_approved_original_scan_dimensions_are_valid(s.id,s.company_id,s.seal_category,s.seal_size_type,f.file_hash,f.pixel_width,f.pixel_height,f.source_aspect_ratio,f.render_width_mm,f.render_height_mm,f.dimension_policy_version,f.dimension_validated)
   or pg_catalog.lower(f.file_hash) is distinct from pg_catalog.lower(p_sha256)
   or not exists(select 1 from public.file_objects o where o.id=f.file_object_id and o.sha256=f.file_hash
    and o.size_bytes=f.file_size and o.mime_type='image/png' and o.mime_type=f.file_mime_type
    and o.storage_key=f.file_storage_key and o.bucket='edoc-seal-vault'
    and pg_catalog.lower(coalesce(o.scan_status,'')) in ('已通過','clean','passed')) then
   raise exception 'approved_scan_import_current_conflict';
  end if;
  result := pg_catalog.jsonb_build_object('file',pg_catalog.to_jsonb(f),'import_status','already_registered');
 else
  result := public.edoc_create_company_seal_file_version(p_object_id,p_file_id,s.id,p_storage_key,p_file_name,'image/png',p_file_size,p_sha256,p_pixel_width,p_pixel_height,p_ratio,p_width_mm,p_height_mm,'original-scan-200dpi-20260914-v1',actor,p_scan_engine,p_scan_signature,'SLOG-APPROVED-'||pg_catalog.lower(p_sha256),'AUD-APPROVED-'||pg_catalog.lower(p_sha256));
  result := result||pg_catalog.jsonb_build_object('import_status','registered');
 end if;
 if owner_kind is null or owner_kind='unclassified' then
  perform public.edoc_set_company_seal_policy(s.company_id,desired_kind,actor);
 end if;
 insert into public.audit_logs(id,actor,action,target_type,target_id,detail,event_type,module_code,result,created_at)
  values('AUD-IMPORT-'||p_key_sha256||'-'||pg_catalog.lower(p_sha256),actor,'operator_import_original_scan','company_seal_files',result->'file'->>'id',
   'source_pdf_sha256='||p_source_pdf_sha256||';batch='||b.batch_id,'operator_import_original_scan','seals','success',pg_catalog.clock_timestamp()::text)
  on conflict(id) do nothing;
 select count(distinct files.seal_id) into total from public.company_seal_files files join public.company_seals seals on seals.id=files.seal_id
  join public.companies companies on companies.id=seals.company_id and companies.status='active'
   and companies.source_system='finance' and nullif(companies.finance_entity_id,'') is not null
  join public.company_seal_policies policies on policies.company_id=seals.company_id
   and policies.owner_kind=case seals.company_id when 'CO-005' then 'institution' when 'CO-006' then 'institution'
    when 'CO-001' then 'company' when 'CO-002' then 'company' when 'CO-004' then 'company'
    when 'FINCO-263DD88BDAAA' then 'company' else null end
  join public.file_objects objects on objects.id=files.file_object_id and objects.sha256=files.file_hash
   and objects.size_bytes=files.file_size and objects.mime_type='image/png' and objects.mime_type=files.file_mime_type
   and objects.storage_key=files.file_storage_key and objects.bucket='edoc-seal-vault'
   and pg_catalog.lower(coalesce(objects.scan_status,'')) in ('已通過','clean','passed')
  where seals.is_active=true and files.is_current=true and public.edoc_approved_original_scan_dimensions_are_valid(seals.id,seals.company_id,seals.seal_category,seals.seal_size_type,files.file_hash,files.pixel_width,files.pixel_height,files.source_aspect_ratio,files.render_width_mm,files.render_height_mm,files.dimension_policy_version,files.dimension_validated);
 update public.approved_original_scan_import_batches set completed_file_count=total,
  status=case when total=22 then 'completed' else 'open' end,updated_at=pg_catalog.clock_timestamp()
  where batch_id=b.batch_id;
 if pg_catalog.floor(extract(epoch from pg_catalog.clock_timestamp()))::bigint>=b.expires_at_epoch then
  raise exception 'approved_scan_import_permit_closed';
 end if;
 return result||pg_catalog.jsonb_build_object('completed_file_count',total,'batch_status',case when total=22 then 'completed' else 'open' end);
end $$;
revoke all on function public.edoc_import_approved_original_scan_file(text,text,text,text,text,bigint,text,integer,integer,numeric,numeric,numeric,text,text,text,text) from public,anon,authenticated;
grant execute on function public.edoc_import_approved_original_scan_file(text,text,text,text,text,bigint,text,integer,integer,numeric,numeric,numeric,text,text,text,text) to service_role;
