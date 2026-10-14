"""Generate the independently approved six-byte native 120 DPI forward.

Only local reviewed SQL is generated. No image, network, permit or database
activation occurs here; the existing 22-original operator permit is untouched.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import seal_scan_20261013 as approved
import seal_scan_exceptions as original
from tools.shared_supabase_bootstrap import BUNDLE_VERSION, sha256_text, transform_sql

SOURCE = "20261013125111_approved_native120_scan_exception.sql"
SHARED = "20261013125112_shared_approved_native120_scan_exception.sql"
PREREQUISITE = "20261013070841_approved_original_scan_exception.sql"
PREREQUISITE_SHA = "ce8c72275232d689afdeee7376a2d69ce6fd67282cfdfd4477da8bb9d2205565"
PREREQUISITE_TRANSFORMED_SHA = "f85521c9a4a187d1135124441647e8535b0e402f1e0edcc7d3e93517720087d9"
SIGNATURE = "text,text,text,text,text,integer,integer,numeric,numeric,numeric,text,boolean"
PARAMS = "p_seal_id text,p_company_id text,p_category text,p_size_type text,p_sha256 text,p_pixel_width integer,p_pixel_height integer,p_source_aspect_ratio numeric,p_render_width_mm numeric,p_render_height_mm numeric,p_policy_version text,p_dimension_validated boolean"
RPC_SIGNATURE = "text,text,text,text,text,bigint,text,integer,integer,numeric,numeric,numeric,text,text,text,text"


def source_sql() -> str:
    previous = (ROOT / "supabase/migrations" / PREREQUISITE).read_text()
    if sha256_text(previous) != PREREQUISITE_SHA:
        raise RuntimeError("native120_reviewed_prerequisite_hash_mismatch")
    values = ",\n".join("(" + ",".join("'" + x + "'" if isinstance(x, str) else str(x) for x in row[:-1]) + ")" for row in approved._ROWS)
    helper = f"""-- Six user-approved raw DCT native crops, no recompression or resizing.
-- Exact source SHA256: {approved.SOURCE_SHA256}
-- Existing 22-image permit and generic 250 DPI geometry are unchanged.
create or replace function public.edoc_approved_native120_scan_dimensions_are_valid({PARAMS})
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
revoke all on function public.edoc_approved_native120_scan_dimensions_are_valid({SIGNATURE}) from public,anon,authenticated;
grant execute on function public.edoc_approved_native120_scan_dimensions_are_valid({SIGNATURE}) to service_role;

create or replace function public.edoc_company_seal_file_dimensions_are_valid({PARAMS})
returns boolean language sql immutable security invoker set search_path='' as $$
select coalesce(public.edoc_approved_native120_scan_dimensions_are_valid(p_seal_id,p_company_id,p_category,p_size_type,p_sha256,p_pixel_width,p_pixel_height,p_source_aspect_ratio,p_render_width_mm,p_render_height_mm,p_policy_version,p_dimension_validated),false)
 or coalesce(public.edoc_approved_original_scan_dimensions_are_valid(p_seal_id,p_company_id,p_category,p_size_type,p_sha256,p_pixel_width,p_pixel_height,p_source_aspect_ratio,p_render_width_mm,p_render_height_mm,p_policy_version,p_dimension_validated),false)
 or (p_policy_version not in ('{original.POLICY}','{approved.POLICY}') and public.edoc_company_seal_dimensions_are_valid(p_size_type,p_pixel_width,p_pixel_height,p_source_aspect_ratio,p_render_width_mm,p_render_height_mm,p_policy_version,p_dimension_validated));
$$;
revoke all on function public.edoc_company_seal_file_dimensions_are_valid({SIGNATURE}) from public,anon,authenticated;
grant execute on function public.edoc_company_seal_file_dimensions_are_valid({SIGNATURE}) to service_role;

create or replace function public.edoc_enforce_approved_native120_scan_file()
returns trigger language plpgsql security invoker set search_path='' as $$
declare s public.company_seals%rowtype;
begin
 if new.dimension_policy_version='{approved.POLICY}' then
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

"""
    marker = "-- Temporary operator permit"
    functions = previous[previous.index("CREATE OR REPLACE FUNCTION public.edoc_create_company_seal_file_version"):previous.index(marker)]
    functions = functions.replace("'" + original.POLICY + "')", "'" + original.POLICY + "','" + approved.POLICY + "')")
    if functions.count(approved.POLICY) != 2:
        raise RuntimeError("native120_forward_policy_replacement_mismatch")
    # The unchanged atomic create/current/position functions already call the
    # source-bound facade; only their explicit version allowlists are extended.
    batch = previous[previous.index(marker):]
    batch = batch.replace("approved_original_scan_import_batches", "approved_native120_scan_import_batches")
    batch = batch.replace("edoc_import_approved_original_scan_file", "edoc_import_approved_native120_scan_file")
    batch = batch.replace("edoc_approved_original_scan_dimensions_are_valid", "edoc_approved_native120_scan_dimensions_are_valid")
    batch = batch.replace("approved_scan_import", "native120_scan_import")
    batch = batch.replace("operator_import_original_scan", "operator_import_native120_scan")
    batch = batch.replace(original.POLICY, approved.POLICY).replace(original.SOURCE_SHA256, approved.SOURCE_SHA256)
    batch = batch.replace("between 0 and 22", "between 0 and 6").replace("total=22", "total=6")
    old_owners = "case s.company_id when 'CO-005' then 'institution' when 'CO-006' then 'institution'\n  when 'CO-001' then 'company' when 'CO-002' then 'company' when 'CO-004' then 'company'\n  when 'FINCO-263DD88BDAAA' then 'company' else null end"
    new_owners = "case s.company_id when 'CO-007' then 'company'\n  when 'FINCO-AE264D87483E' then 'institution' when 'FINCO-D7FAD93DE9AE' then 'institution' else null end"
    old_count_owners = "case seals.company_id when 'CO-005' then 'institution' when 'CO-006' then 'institution'\n    when 'CO-001' then 'company' when 'CO-002' then 'company' when 'CO-004' then 'company'\n    when 'FINCO-263DD88BDAAA' then 'company' else null end"
    new_count_owners = "case seals.company_id when 'CO-007' then 'company'\n    when 'FINCO-AE264D87483E' then 'institution' when 'FINCO-D7FAD93DE9AE' then 'institution' else null end"
    if old_owners not in batch or old_count_owners not in batch:
        raise RuntimeError("native120_operator_owner_replacement_mismatch")
    batch = batch.replace(old_owners, new_owners).replace(old_count_owners, new_count_owners)
    batch = batch.replace("and nullif(finance_entity_id,'') is not null for share", "and finance_entity_id=case s.company_id when 'CO-007' then 'E7' when 'FINCO-AE264D87483E' then 'E9' when 'FINCO-D7FAD93DE9AE' then 'E8' else null end for share")
    batch = batch.replace("and nullif(companies.finance_entity_id,'') is not null", "and companies.finance_entity_id=case seals.company_id when 'CO-007' then 'E7' when 'FINCO-AE264D87483E' then 'E9' when 'FINCO-D7FAD93DE9AE' then 'E8' else null end")
    return helper + functions + batch


def transformed_sql(source: str) -> str:
    return transform_sql(source) + f"""
-- No shared-project legacy/default role may access this maintenance path.
revoke all on edoc.approved_native120_scan_import_batches from service_role,authenticator;
revoke all on function edoc.edoc_approved_native120_scan_dimensions_are_valid({SIGNATURE}) from service_role,authenticator;
revoke all on function edoc.edoc_company_seal_file_dimensions_are_valid({SIGNATURE}) from service_role,authenticator;
revoke all on function edoc.edoc_import_approved_native120_scan_file({RPC_SIGNATURE}) from service_role,authenticator;
"""


def shared_sql(source: str) -> str:
    transformed = transformed_sql(source)
    return f"""-- Generated by tools/seal_native120_forward.py; six exact source assets only.
begin;
select pg_catalog.pg_advisory_xact_lock(1788103601,20261013);
do $native120_scan_forward$
begin
 if pg_catalog.to_regclass('edoc_private.shared_project_migration_ledger') is null
  or not exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='{PREREQUISITE}'
   and source_sha256='{PREREQUISITE_SHA}' and transformed_sha256='{PREREQUISITE_TRANSFORMED_SHA}') then
  raise exception 'native120_scan_forward_prerequisite_missing';
 end if;
 if exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='{SOURCE}'
  and (source_sha256 is distinct from '{sha256_text(source)}' or transformed_sha256 is distinct from '{sha256_text(transformed)}')) then
  raise exception 'native120_scan_forward_hash_mismatch';
 end if;
 if not exists(select 1 from edoc_private.shared_project_migration_ledger where file_name='{SOURCE}') then
  execute $native120_scan_source$
{transformed}$native120_scan_source$;
  insert into edoc_private.shared_project_migration_ledger(file_name,source_sha256,transformed_sha256,bundle_version)
   values('{SOURCE}','{sha256_text(source)}','{sha256_text(transformed)}','{BUNDLE_VERSION}');
 end if;
end $native120_scan_forward$;
notify pgrst,'reload schema';
commit;
"""


def function_body_sha(source: str, name: str, schema: str) -> str:
    match = re.search(r"create or replace function " + schema + r"\." + name + r"\([^;]*?as (\$[a-z_]*\$)(.*?)\1;", source, re.S | re.I)
    if not match:
        raise RuntimeError("native120_function_source_missing:" + name)
    return sha256_text(match.group(2))


def gate_sql(schema: str) -> str:
    source = source_sql() if schema == "public" else transformed_sql(source_sql())
    backend = "service_role" if schema == "public" else "edoc_backend"
    denied = "'anon','authenticated','authenticator'" if schema == "public" else "'anon','authenticated','service_role','authenticator'"
    functions = (
        ("edoc_approved_native120_scan_dimensions_are_valid", SIGNATURE, False, "i", True),
        ("edoc_company_seal_file_dimensions_are_valid", SIGNATURE, False, "i", True),
        ("edoc_import_approved_native120_scan_file", RPC_SIGNATURE, True, "v", True),
        ("edoc_create_company_seal_file_version", "text,text,text,text,text,text,bigint,text,integer,integer,numeric,numeric,numeric,text,text,text,text,text,text", True, "v", True),
        ("edoc_set_current_company_seal_file", "text,text,text,text", True, "v", True),
        ("edoc_enforce_approved_native120_scan_file", "", False, "v", False),
        ("edoc_enforce_company_seal_position_dimensions", "", False, "v", False),
    )
    entries = ",\n".join(f"    ('{schema}.{name}({signature})',{str(definer).lower()},'{volatility}',{str(execute).lower()},'{function_body_sha(source,name,schema)}')" for name, signature, definer, volatility, execute in functions)
    return f"""-- Six native120 assets: exact-source, role and trigger gate; read-only.
do $approved_native120_scan_import_gate$
declare
  v_table regclass := pg_catalog.to_regclass('{schema}.approved_native120_scan_import_batches');
  v_backend text := '{backend}';
  v_denied text[] := array[{denied}];
  v_role text; v_expected record; v_proc record;
begin
  if v_table is null or not exists(select 1 from pg_catalog.pg_class where oid=v_table
      and relrowsecurity and relforcerowsecurity and pg_catalog.pg_get_userbyid(relowner)='postgres') then
    raise exception 'native120_scan_import_table_security_mismatch';
  end if;
  if not pg_catalog.has_table_privilege(v_backend,v_table,'SELECT')
     or pg_catalog.has_table_privilege(v_backend,v_table,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') then
    raise exception 'native120_scan_import_table_grant_mismatch';
  end if;
  foreach v_role in array v_denied loop
    if pg_catalog.has_table_privilege(v_role,v_table,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') then
      raise exception 'native120_scan_import_browser_table_grant';
    end if;
  end loop;
  if exists(select 1 from pg_catalog.pg_class c, lateral pg_catalog.aclexplode(
      coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a where c.oid=v_table and a.grantee=0)
     or (select count(*) from pg_catalog.pg_policy where polrelid=v_table)<>1
     or not exists(select 1 from pg_catalog.pg_policy where polrelid=v_table and polcmd='r'
       and polroles=array[pg_catalog.to_regrole(v_backend)::oid]
       and pg_catalog.pg_get_expr(polqual,polrelid)='true' and polwithcheck is null) then
    raise exception 'native120_scan_import_table_policy_mismatch';
  end if;
  if (select pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(
       pg_catalog.string_agg(conname||':'||pg_catalog.pg_get_constraintdef(oid,true),'|' order by conname),'UTF8')),'hex')
       from pg_catalog.pg_constraint where conrelid=v_table)
     is distinct from '75e64288b64d1637b85dda9be1b70df1c03544610188d0ed4e26ffa403927e4e' then
    raise exception 'native120_scan_import_exact_constraints_mismatch';
  end if;
  for v_expected in select * from (values
{entries}
  ) expected(signature,is_definer,volatility,backend_execute,body_sha256) loop
    select * into v_proc from pg_catalog.pg_proc where oid=pg_catalog.to_regprocedure(v_expected.signature);
    if not found then raise exception 'native120_scan_import_rpc_missing'; end if;
    if v_proc.prosecdef is distinct from v_expected.is_definer
       or v_proc.provolatile::text is distinct from v_expected.volatility
       or pg_catalog.pg_get_userbyid(v_proc.proowner)<>'postgres'
       or not coalesce(v_proc.proconfig @> array['search_path=""'],false)
       or pg_catalog.has_function_privilege(v_backend,v_proc.oid,'EXECUTE') is distinct from v_expected.backend_execute
       or pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(v_proc.prosrc,'UTF8')),'hex')<>v_expected.body_sha256 then
      raise exception 'native120_scan_import_rpc_security_or_source_mismatch';
    end if;
    if v_expected.is_definer and not coalesce(v_proc.proconfig @> array['lock_timeout=5s'],false) then
      raise exception 'native120_scan_import_rpc_lock_timeout_missing';
    end if;
    foreach v_role in array v_denied loop
      if pg_catalog.has_function_privilege(v_role,v_proc.oid,'EXECUTE') then
        raise exception 'native120_scan_import_browser_rpc_grant';
      end if;
    end loop;
    if exists(select 1 from pg_catalog.aclexplode(coalesce(v_proc.proacl,
        pg_catalog.acldefault('f',v_proc.proowner))) a where a.grantee=0 and a.privilege_type='EXECUTE') then
      raise exception 'native120_scan_import_public_rpc_grant';
    end if;
  end loop;
  if not exists(select 1 from pg_catalog.pg_trigger where tgrelid='{schema}.company_seal_files'::regclass
       and tgname='edoc_approved_native120_scan_file' and not tgisinternal and tgenabled='O' and tgtype=23
       and tgfoid='{schema}.edoc_enforce_approved_native120_scan_file()'::regprocedure and tgnargs=0 and tgattr=''::int2vector) then
    raise exception 'native120_scan_import_attestation_trigger_mismatch';
  end if;
end;
$approved_native120_scan_import_gate$;
"""


def update_verification() -> None:
    """Mechanical source-bound inventory refresh; no generalized grant changes."""
    directory = ROOT / "supabase/verification"
    for name, schema in (("fresh_bootstrap_smoke.sql", "public"), ("shared_project_cutover_checks.sql", "edoc")):
        path = directory / name
        text = path.read_text()
        pattern = r"-- Six native120 assets:.*?\$approved_native120_scan_import_gate\$;\n"
        if re.search(pattern, text, re.S):
            text = re.sub(pattern, lambda _: gate_sql(schema), text, count=1, flags=re.S)
        else:
            text = text.replace("do $approved_original_scan_import_gate$", gate_sql(schema) + "\ndo $approved_original_scan_import_gate$", 1)
        facade_hash = function_body_sha(source_sql() if schema == "public" else transformed_sql(source_sql()), "edoc_company_seal_file_dimensions_are_valid", schema)
        text = re.sub(r"('" + schema + r"\.edoc_company_seal_file_dimensions_are_valid\([^']*\)',false,'i',')[0-9a-f]{64}('\))", lambda m: m.group(1) + facade_hash + m.group(2), text)
        if schema == "edoc":
            text = text.replace("('r','p','v','m')) = 98", "('r','p','v','m')) = 99")
            text = text.replace("migration_ledger) = 73", "migration_ledger) = 74")
            ledger_pattern = r"      and exists\(select 1 from edoc_private\.shared_project_migration_ledger\n        where file_name='" + SOURCE + r"'.*?\)\n"
            text = re.sub(ledger_pattern, "", text, flags=re.S)
            anchor = "      and exists(select 1 from edoc_private.shared_project_migration_ledger\n        where file_name='" + PREREQUISITE + "'"
            addition = f"      and exists(select 1 from edoc_private.shared_project_migration_ledger\n        where file_name='{SOURCE}'\n          and source_sha256='{sha256_text(source_sql())}'\n          and transformed_sha256='{sha256_text(transformed_sql(source_sql()))}')\n"
            if anchor not in text:
                raise RuntimeError("native120_verification_ledger_anchor_missing")
            text = text.replace(anchor, addition + anchor, 1)
        path.write_text(text)
    for name in ("production_cutover_checks.sql", "service_role_data_api_grant_smoke.sql"):
        path = directory / name
        text = path.read_text()
        rpc = "('public.edoc_import_approved_original_scan_file(" + RPC_SIGNATURE + ")')"
        new_rpc = "('public.edoc_import_approved_native120_scan_file(" + RPC_SIGNATURE + ")')"
        text = re.sub(r"\s*" + re.escape(new_rpc) + r",", "", text)
        text = text.replace(rpc + ",", rpc + ",\n    " + new_rpc + ",")
        helper = "('public.edoc_approved_original_scan_dimensions_are_valid(" + SIGNATURE + ")')"
        new_helper = "('public.edoc_approved_native120_scan_dimensions_are_valid(" + SIGNATURE + ")')"
        text = re.sub(r"\s*" + re.escape(new_helper) + r",", "", text)
        text = text.replace(helper + ",", helper + ",\n    " + new_helper + ",")
        if name == "production_cutover_checks.sql":
            text = text.replace("('approved_original_scan_import_batches'), ('file_download_tokens')", "('approved_original_scan_import_batches'), ('approved_native120_scan_import_batches'), ('file_download_tokens')")
            text = text.replace("'approved_original_scan_import_batches',\n", "'approved_original_scan_import_batches', 'approved_native120_scan_import_batches',\n") if "'approved_native120_scan_import_batches',\n" not in text else text
        else:
            text = text.replace("('approved_original_scan_import_batches', 'S'),", "('approved_original_scan_import_batches', 'S'),\n      ('approved_native120_scan_import_batches', 'S'),") if "('approved_native120_scan_import_batches', 'S')" not in text else text
            text = text.replace("('approved_original_scan_import_batches'), ('attachment_security')", "('approved_original_scan_import_batches'), ('approved_native120_scan_import_batches'), ('attachment_security')")
        path.write_text(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-generated", action="store_true")
    parser.add_argument("--update-verification", action="store_true")
    args = parser.parse_args()
    source = source_sql()
    targets = {ROOT / "supabase/migrations" / SOURCE: source,
               ROOT / "supabase/shared-project-migrations" / SHARED: shared_sql(source)}
    for path, content in targets.items():
        if args.write_generated:
            path.write_text(content)
        elif not path.is_file() or path.read_text() != content:
            raise SystemExit("generated_forward_mismatch:" + path.name)
    if args.update_verification:
        update_verification()
    print("native120_scan_forwards_verified")
