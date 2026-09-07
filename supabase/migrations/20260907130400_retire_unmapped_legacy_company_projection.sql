-- Preserve the old record and its empty seal slots, but remove one verified
-- legacy duplicate from active company scope. Finance E8 is the canonical
-- identity. This correction never renumbers or deletes historical records.
begin;

do $company_parity$
declare
  legacy public.companies%rowtype;
  canonical public.companies%rowtype;
begin
  select * into legacy from public.companies where id = 'CO-008' for update;
  if not found then
    return;
  end if;
  if legacy.status = 'inactive' and legacy.source_system = 'legacy_superseded' then
    return;
  end if;

  select * into canonical from public.companies
  where id = 'FINCO-D7FAD93DE9AE' and finance_entity_id = 'E8'
  for update;
  -- A fresh replay has not received the Finance company projection yet.
  if not found then
    return;
  end if;

  if legacy.name <> '愛無限整合有限公司附設新北市私立愛無限居家長照機構'
     or canonical.name <> '愛無限整合服務有限公司附設新北市私立愛無限居家長照機構'
     or legacy.tax_id <> '91254360'
     or canonical.tax_id is distinct from legacy.tax_id
     or coalesce(legacy.finance_entity_id, '') <> ''
     or coalesce(legacy.finance_tenant_id, '') <> ''
     or coalesce(legacy.source_system, '') <> ''
     or coalesce(legacy.finance_source_revision, 0) <> 0
     or legacy.status not in ('active', '啟用')
     or canonical.status not in ('active', '啟用')
     or canonical.source_system is distinct from 'finance'
     or canonical.finance_tenant_id is distinct from '00000000-0000-0000-0000-000000000001'
     or coalesce(canonical.finance_source_revision, 0) < 1 then
    raise exception 'legacy_company_parity_identity_mismatch';
  end if;

  if exists (select 1 from public.users where company_id = legacy.id)
     or exists (select 1 from public.official_documents where company_id = legacy.id)
     or exists (select 1 from public.official_document_stamp_requests where company_id = legacy.id)
     or exists (select 1 from public.official_workflow_delegations where company_id = legacy.id)
     or exists (select 1 from public.seal_usage_requests where company_id = legacy.id)
     or exists (select 1 from public.inbound_documents where company_id = legacy.id)
     or exists (select 1 from public.inbound_document_mutations where company_id = legacy.id)
     or exists (select 1 from public.contracts where company_name = legacy.name)
     or exists (select 1 from public.documents where company_name = legacy.name)
     or exists (select 1 from public.seal_applications where company_name = legacy.name)
     or exists (
       select 1 from public.company_seal_files file_row
       join public.company_seals seal_row on seal_row.id = file_row.seal_id
       where seal_row.company_id = legacy.id
     ) then
    raise exception 'legacy_company_parity_references_require_review';
  end if;

  update public.companies
  set status = 'inactive', source_system = 'legacy_superseded',
      updated_at = to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
  where id = legacy.id;

  -- The existing hash trigger serializes this append and computes the chain.
  -- Keep the correction log restricted to IDs and status, with no user data.
  insert into public.audit_logs (
    id, actor, action, target_type, target_id, detail,
    event_type, severity, result, module_code, resource_type, resource_id,
    reason, before_snapshot_json, after_snapshot_json, metadata_json
  ) values (
    'AUD-COMPANY-PARITY-20260907-CO008', 'system:finance-company-reconciliation',
    'finance_company_legacy_retired', 'companies', legacy.id,
    '{"legacyCompanyId":"CO-008","canonicalCompanyId":"FINCO-D7FAD93DE9AE","financeEntityId":"E8","errorCode":"LEGACY_COMPANY_SUPERSEDED"}',
    'config_change', 'info', 'success', 'finance_sync', 'companies', legacy.id,
    'verified_finance_canonical_projection',
    jsonb_build_object('status', legacy.status, 'source_system', legacy.source_system)::text,
    '{"status":"inactive","source_system":"legacy_superseded"}',
    '{"preservedHistoricalRows":true,"sealFilesChanged":0}'
  );
end
$company_parity$;

commit;
