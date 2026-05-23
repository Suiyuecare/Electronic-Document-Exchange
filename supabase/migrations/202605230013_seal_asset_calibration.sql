create table if not exists public.seal_assets (
  id text primary key,
  seal_id text not null,
  name text not null,
  seal_type text not null,
  owner text not null,
  doc_type text not null,
  file_object_id text references public.file_objects(id) on delete set null,
  width_mm numeric(8, 2) not null check (width_mm > 0),
  height_mm numeric(8, 2) not null check (height_mm > 0),
  width_pt numeric(10, 2) not null check (width_pt > 0),
  height_pt numeric(10, 2) not null check (height_pt > 0),
  calibration_status text not null default '待校準',
  hash text not null,
  status text not null default '啟用',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_seal_assets_seal_id on public.seal_assets(seal_id);
create index if not exists idx_seal_assets_owner on public.seal_assets(owner);

alter table public.seal_assets enable row level security;

grant select, insert, update on public.seal_assets to authenticated;

drop policy if exists "authorized users read seal assets" on public.seal_assets;
create policy "authorized users read seal assets"
on public.seal_assets for select
to authenticated
using (edoc_private.current_user_role() in ('主任', '執行長', '行政部主任', '總務'));

drop policy if exists "authorized users manage seal assets" on public.seal_assets;
create policy "authorized users manage seal assets"
on public.seal_assets for all
to authenticated
using (edoc_private.current_user_role() in ('主任', '執行長', '行政部主任', '總務'))
with check (edoc_private.current_user_role() in ('主任', '執行長', '行政部主任', '總務'));

insert into public.seal_assets (
  id, seal_id, name, seal_type, owner, doc_type, width_mm, height_mm, width_pt, height_pt, calibration_status, hash, status
) values
  ('ASSET-SEAL-001', 'SEAL-001', '歲悅長照公司章', '公司章', '行政部主任', '函', 30.00, 30.00, 85.04, 85.04, '待上傳圖檔', 'SHA256-SEAL-A19F', '啟用'),
  ('ASSET-SEAL-002', 'SEAL-002', '歲悅負責人章', '負責人章', '行政部主任', '函', 18.00, 18.00, 51.02, 51.02, '待上傳圖檔', 'SHA256-SEAL-B72C', '啟用'),
  ('ASSET-SEAL-003', 'SEAL-003', '附件騎縫章', '騎縫章', '總務', '附件', 10.00, 35.00, 28.35, 99.21, '待上傳圖檔', 'SHA256-SEAL-C44D', '停用')
on conflict (id) do nothing;
