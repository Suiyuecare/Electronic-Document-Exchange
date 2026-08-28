-- The calibrated seal RPCs introduced by the runtime-parity migration use
-- these fields through company_seal_files%rowtype. The original table predates
-- that contract, so add the metadata forward-only instead of rewriting the
-- already-applied table migration.
--
-- Existing seal files remain immutable evidence. Their physical dimensions
-- cannot be inferred safely from database metadata alone, so they are left
-- unvalidated and are no longer designated current. An authorised custodian
-- must upload a validated v2 file before the seal can be selected again.

alter table public.company_seal_files
  add column if not exists pixel_width integer,
  add column if not exists pixel_height integer,
  add column if not exists source_aspect_ratio numeric,
  add column if not exists render_width_mm numeric,
  add column if not exists render_height_mm numeric,
  add column if not exists dimension_policy_version text,
  add column if not exists dimension_validated boolean not null default false;

-- Some runtime databases may already have a nullable copy of this column.
-- Normalise only the validation flag; never manufacture physical dimensions.
update public.company_seal_files
   set dimension_validated = false
 where dimension_validated is null;

alter table public.company_seal_files
  alter column dimension_validated set default false,
  alter column dimension_validated set not null;

update public.company_seal_files as seal_file
   set is_current = false
  from public.company_seals as seal
 where seal_file.is_current is true
   and seal.id = seal_file.seal_id
   and (
     seal_file.dimension_policy_version is distinct from
       'institution-seal-v2-calibrated'
     or not pg_catalog.coalesce(
       public.edoc_company_seal_dimensions_are_valid(
         seal.seal_size_type,
         seal_file.pixel_width,
         seal_file.pixel_height,
         seal_file.source_aspect_ratio,
         seal_file.render_width_mm,
         seal_file.render_height_mm,
         seal_file.dimension_policy_version,
         seal_file.dimension_validated
       ),
       false
     )
   );

notify pgrst, 'reload schema';
