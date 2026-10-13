"""Generate exact-byte original-scan forwards; no database or network access."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import seal_scan_exceptions as approved
from tools.shared_supabase_bootstrap import BUNDLE_VERSION, sha256_text, transform_sql

SOURCE = "20261013070841_approved_original_scan_exception.sql"
SHARED = "20261013070842_shared_approved_original_scan_exception.sql"
PREREQUISITE = "20261012114854_explicit_seal_owner_policy_and_continuous_geometry.sql"


def source_sql():
    values = ",\n".join("(" + ",".join("'" + x + "'" if isinstance(x,str) else str(x) for x in row[:-1]) + ")" for row in approved._ROWS)
    signature = "text,text,text,text,text,integer,integer,numeric,numeric,numeric,text,boolean"
    params = "p_seal_id text,p_company_id text,p_category text,p_size_type text,p_sha256 text,p_pixel_width integer,p_pixel_height integer,p_source_aspect_ratio numeric,p_render_width_mm numeric,p_render_height_mm numeric,p_policy_version text,p_dimension_validated boolean"
    sql = f"""-- User-approved 1:1 original scan exception, limited to exact hashes/slots.
-- No artwork, rows, activation, actor assignment or general DPI relaxation.
-- Source SHA256: {approved.SOURCE_SHA256}
create or replace function public.edoc_approved_original_scan_dimensions_are_valid({params})
returns boolean language sql immutable security invoker set search_path='' as $$
select coalesce(p_dimension_validated,false) and p_policy_version='{approved.POLICY}'
 and exists(select 1 from (values
{values}
 ) as a(digest,company_id,seal_id,category,size_type,pw,ph,mw,mh)
 where a.digest=pg_catalog.lower(p_sha256) and a.company_id=p_company_id and a.seal_id=p_seal_id
 and a.category=p_category and a.size_type=p_size_type
 and a.pw=p_pixel_width and a.ph=p_pixel_height
 and abs(a.mw-p_render_width_mm)<=0.000001 and abs(a.mh-p_render_height_mm)<=0.000001
 and abs(p_source_aspect_ratio-a.pw::numeric/a.ph)<=0.000001);
$$;
revoke all on function public.edoc_approved_original_scan_dimensions_are_valid({signature}) from public,anon,authenticated;
grant execute on function public.edoc_approved_original_scan_dimensions_are_valid({signature}) to service_role;

create or replace function public.edoc_company_seal_file_dimensions_are_valid({params})
returns boolean language sql immutable security invoker set search_path='' as $$
select coalesce(public.edoc_approved_original_scan_dimensions_are_valid(p_seal_id,p_company_id,p_category,p_size_type,p_sha256,p_pixel_width,p_pixel_height,p_source_aspect_ratio,p_render_width_mm,p_render_height_mm,p_policy_version,p_dimension_validated),false)
 or (p_policy_version is distinct from '{approved.POLICY}' and public.edoc_company_seal_dimensions_are_valid(p_size_type,p_pixel_width,p_pixel_height,p_source_aspect_ratio,p_render_width_mm,p_render_height_mm,p_policy_version,p_dimension_validated));
$$;
revoke all on function public.edoc_company_seal_file_dimensions_are_valid({signature}) from public,anon,authenticated;
grant execute on function public.edoc_company_seal_file_dimensions_are_valid({signature}) to service_role;

create or replace function public.edoc_enforce_approved_original_scan_file()
returns trigger language plpgsql security invoker set search_path='' as $$
declare s public.company_seals%rowtype;
begin
 if new.dimension_policy_version='{approved.POLICY}' then
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

"""
    previous = (ROOT / "supabase/migrations" / PREREQUISITE).read_text()
    functions = previous[previous.index("CREATE OR REPLACE FUNCTION public.edoc_create_company_seal_file_version"):]
    functions = functions.replace("not in ('institution-seal-v2-calibrated','official-seal-v1-calibrated','continuous-seal-v1-calibrated')", "not in ('institution-seal-v2-calibrated','official-seal-v1-calibrated','continuous-seal-v1-calibrated','" + approved.POLICY + "')")
    functions = functions.replace("public.edoc_company_seal_dimensions_are_valid(\n    v_seal.seal_size_type,", "public.edoc_company_seal_file_dimensions_are_valid(\n    v_seal.id,v_seal.company_id,v_seal.seal_category,v_seal.seal_size_type,p_sha256,")
    functions = functions.replace("public.edoc_company_seal_dimensions_are_valid(\n       v_seal.seal_size_type,", "public.edoc_company_seal_file_dimensions_are_valid(\n       v_seal.id,v_seal.company_id,v_seal.seal_category,v_seal.seal_size_type,v_target.file_hash,")
    functions = functions.replace("  v_category text;\n", "  v_category text;\n  v_company_id text;\n")
    functions = functions.replace("select seal.seal_size_type, seal.seal_category into v_size_type, v_category", "select seal.seal_size_type, seal.seal_category, seal.company_id into v_size_type, v_category, v_company_id")
    functions = functions.replace("public.edoc_company_seal_dimensions_are_valid(\n       v_size_type,", "public.edoc_company_seal_file_dimensions_are_valid(\n       new.seal_id,v_company_id,v_category,v_size_type,v_file.file_hash,")
    if "public.edoc_company_seal_dimensions_are_valid(" in functions:
        raise RuntimeError("exception_forward_unreplaced_validation_call")
    # Do not copy any pre-existing generic helper or weaken its 250 DPI checks.
    batch = f"""
-- Temporary operator permit is controlled separately from file attestation.
-- No permit is opened by this migration; an explicitly authorized operator
-- must configure the short-lived batch through the administrative connection.
create table public.approved_original_scan_import_batches (
 batch_id text primary key check(batch_id='{approved.POLICY}'),
 source_pdf_sha256 text not null check(source_pdf_sha256='{approved.SOURCE_SHA256}'),
 key_sha256 text not null check(key_sha256 ~ '^[0-9a-f]{{64}}$'),
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
 select * into b from public.approved_original_scan_import_batches where batch_id='{approved.POLICY}' for update;
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
 if p_source_pdf_sha256 is distinct from '{approved.SOURCE_SHA256}' or not
  public.edoc_approved_original_scan_dimensions_are_valid(s.id,s.company_id,s.seal_category,s.seal_size_type,p_sha256,p_pixel_width,p_pixel_height,p_ratio,p_width_mm,p_height_mm,'{approved.POLICY}',true)
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
  result := public.edoc_create_company_seal_file_version(p_object_id,p_file_id,s.id,p_storage_key,p_file_name,'image/png',p_file_size,p_sha256,p_pixel_width,p_pixel_height,p_ratio,p_width_mm,p_height_mm,'{approved.POLICY}',actor,p_scan_engine,p_scan_signature,'SLOG-APPROVED-'||pg_catalog.lower(p_sha256),'AUD-APPROVED-'||pg_catalog.lower(p_sha256));
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
"""
    return sql + functions + batch


def shared_sql(source):
    transformed = transform_sql(source) + """
-- Do not inherit shared-project legacy/default service-role privileges.
revoke all on edoc.approved_original_scan_import_batches from service_role,authenticator;
revoke all on function edoc.edoc_approved_original_scan_dimensions_are_valid(text,text,text,text,text,integer,integer,numeric,numeric,numeric,text,boolean) from service_role,authenticator;
revoke all on function edoc.edoc_company_seal_file_dimensions_are_valid(text,text,text,text,text,integer,integer,numeric,numeric,numeric,text,boolean) from service_role,authenticator;
revoke all on function edoc.edoc_import_approved_original_scan_file(text,text,text,text,text,bigint,text,integer,integer,numeric,numeric,numeric,text,text,text,text) from service_role,authenticator;
"""
    return f"""-- Generated by tools/seal_scan_exception_forward.py; backend-only exact scan exception.
begin;
select pg_catalog.pg_advisory_xact_lock(1788103601,20261013);
do $approved_scan_forward$
begin
 if pg_catalog.to_regclass('edoc_private.shared_project_migration_ledger') is null
  or not exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='{PREREQUISITE}') then
  raise exception 'approved_scan_forward_prerequisite_missing';
 end if;
 if exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='{SOURCE}'
  and (source_sha256 is distinct from '{sha256_text(source)}' or transformed_sha256 is distinct from '{sha256_text(transformed)}')) then
  raise exception 'approved_scan_forward_hash_mismatch';
 end if;
 if not exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='{SOURCE}') then
  execute $approved_scan_source$
{transformed}$approved_scan_source$;
  insert into edoc_private.shared_project_migration_ledger(file_name,source_sha256,transformed_sha256,bundle_version)
   values('{SOURCE}','{sha256_text(source)}','{sha256_text(transformed)}','{BUNDLE_VERSION}');
 end if;
end $approved_scan_forward$;
notify pgrst,'reload schema';
commit;
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-generated", action="store_true")
    args = parser.parse_args()
    source = source_sql()
    targets = {ROOT / "supabase/migrations" / SOURCE: source,
               ROOT / "supabase/shared-project-migrations" / SHARED: shared_sql(source)}
    if args.write_generated:
        for path, content in targets.items():
            path.write_text(content)
    else:
        for path, content in targets.items():
            if not path.is_file() or path.read_text() != content:
                raise SystemExit("generated_forward_mismatch:" + path.name)
    print("approved_scan_forwards_verified")
