-- Remove only the identifiers used by the retired demo seed. This migration
-- deliberately avoids pattern matching so genuine production records cannot be
-- removed merely because their names resemble test data.

begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

-- These session-local guards deliberately inspect the live catalog. The first
-- follows every foreign key, including composite foreign keys and foreign keys
-- that target an alternate unique key. The second checks exact fixture IDs in
-- text identifier columns only, so it never scans document bodies, subjects,
-- metadata or other large content fields. Both helpers disappear with the
-- migration session.
create or replace function pg_temp.edoc_demo_assert_no_fk_references(
  p_parent_relation pg_catalog.regclass,
  p_parent_id text,
  p_error_prefix text
)
returns void
language plpgsql
as $guard$
declare
  v_fk record;
  v_has_reference boolean;
begin
  for v_fk in
    select
      child_namespace.nspname as child_schema_name,
      child_relation.relname as child_table_name,
      parent_namespace.nspname as parent_schema_name,
      parent_relation.relname as parent_table_name,
      pg_catalog.string_agg(
        pg_catalog.format(
          'child_row.%I = parent_row.%I',
          child_attribute.attname,
          parent_attribute.attname
        ),
        ' and '
        order by child_key.position
      ) as join_predicate
    from pg_catalog.pg_constraint constraint_row
    join pg_catalog.pg_class child_relation
      on child_relation.oid = constraint_row.conrelid
    join pg_catalog.pg_namespace child_namespace
      on child_namespace.oid = child_relation.relnamespace
    join pg_catalog.pg_class parent_relation
      on parent_relation.oid = constraint_row.confrelid
    join pg_catalog.pg_namespace parent_namespace
      on parent_namespace.oid = parent_relation.relnamespace
    join lateral pg_catalog.unnest(constraint_row.conkey)
      with ordinality child_key(attnum, position) on true
    join lateral pg_catalog.unnest(constraint_row.confkey)
      with ordinality parent_key(attnum, position)
      on parent_key.position = child_key.position
    join pg_catalog.pg_attribute child_attribute
      on child_attribute.attrelid = constraint_row.conrelid
     and child_attribute.attnum = child_key.attnum
    join pg_catalog.pg_attribute parent_attribute
      on parent_attribute.attrelid = constraint_row.confrelid
     and parent_attribute.attnum = parent_key.attnum
    where constraint_row.contype = 'f'
      and constraint_row.confrelid = p_parent_relation
    group by
      constraint_row.oid,
      child_namespace.nspname,
      child_relation.relname,
      parent_namespace.nspname,
      parent_relation.relname
  loop
    execute pg_catalog.format(
      'select exists ('
      || 'select 1 from %I.%I child_row '
      || 'join %I.%I parent_row on %s '
      || 'where parent_row.id::pg_catalog.text = $1)',
      v_fk.child_schema_name,
      v_fk.child_table_name,
      v_fk.parent_schema_name,
      v_fk.parent_table_name,
      v_fk.join_predicate
    )
    into v_has_reference
    using p_parent_id;

    if v_has_reference then
      raise exception using
        errcode = '55000',
        message = pg_catalog.format(
          '%s:%I.%I',
          p_error_prefix,
          v_fk.child_schema_name,
          v_fk.child_table_name
        );
    end if;
  end loop;
end
$guard$;

create or replace function pg_temp.edoc_demo_assert_no_exact_scalar_references(
  p_fixture_ids text[]
)
returns void
language plpgsql
as $guard$
declare
  v_table record;
  v_has_reference boolean;
begin
  if p_fixture_ids is null or pg_catalog.cardinality(p_fixture_ids) = 0 then
    return;
  end if;

  -- Run after every expected fixture row has been removed. Build one predicate
  -- per public table, so each table is scanned at most once regardless of the
  -- number of retired IDs. Foreign-key references are checked earlier with the
  -- catalog FK helper; this bounded final pass catches exact text references in
  -- intentionally denormalized history columns without fixture x column scans.
  for v_table in
    select
      namespace_row.nspname as schema_name,
      relation_row.relname as table_name,
      pg_catalog.string_agg(
        pg_catalog.format('table_row.%I = any($1)', attribute_row.attname),
        ' or '
        order by attribute_row.attnum
      ) as match_predicate
    from pg_catalog.pg_attribute attribute_row
    join pg_catalog.pg_class relation_row
      on relation_row.oid = attribute_row.attrelid
    join pg_catalog.pg_namespace namespace_row
      on namespace_row.oid = relation_row.relnamespace
    where attribute_row.attnum > 0
      and not attribute_row.attisdropped
      and relation_row.relkind in ('r', 'p')
      and namespace_row.nspname = 'public'
      and attribute_row.atttypid = 'pg_catalog.text'::pg_catalog.regtype
      and (
        attribute_row.attname = 'id'
        or pg_catalog.right(attribute_row.attname, 3) = '_id'
        or attribute_row.attname = any(array[
          'source',
          'created_by',
          'updated_by',
          'requested_by',
          'approved_by',
          'rejected_by',
          'revoked_by',
          'granted_by',
          'uploaded_by',
          'changed_by',
          'last_accessed_by'
        ]::text[])
      )
    group by namespace_row.nspname, relation_row.relname
    order by namespace_row.nspname, relation_row.relname
  loop
    execute pg_catalog.format(
      'select exists (select 1 from %I.%I table_row where %s)',
      v_table.schema_name,
      v_table.table_name,
      v_table.match_predicate
    )
    into v_has_reference
    using p_fixture_ids;

    if v_has_reference then
      raise exception using
        errcode = '55000',
        message = pg_catalog.format(
          'demo_cleanup_has_non_fk_reference:%I.%I',
          v_table.schema_name,
          v_table.table_name
        );
    end if;
  end loop;
end
$guard$;

-- Notification IDs are short and can collide with real data. Delete only the
-- untouched historical fixtures. Any delivery, inbox row, changed target or
-- later-added FK reference is evidence of use and stops the migration.
do $cleanup_demo_notifications$
declare
  v_fk record;
  v_notification_id text;
  v_has_reference boolean;
begin
  perform 1
  from public.notifications
  where id in ('NTF-001', 'NTF-002', 'NTF-003', 'NTF-004', 'NTF-005')
  for update;

  if exists (
    select 1
    from public.notifications
    where id in ('NTF-001', 'NTF-002', 'NTF-003', 'NTF-004', 'NTF-005')
      and not (
        (id = 'NTF-001' and type = '收文' and title = '衛福部補件通知待登錄' and target_role = '總務' and target_email is null and target_user_id is null and target_company_id is null and channel = '系統通知' and status = '未讀' and priority = '高' and source = 'IN-1140522-00018' and action_url is null and body = 'jAgent 已拉取新來文，請完成收文登錄與附件檢核。' and delivery_receipt is null and sent_at is null)
        or (id = 'NTF-002' and type = '待清稿' and title = '日照中心補正資料待清稿' and target_role = '行政部主任' and target_email is null and target_user_id is null and target_company_id is null and channel = 'Email + 系統通知' and status = '未讀' and priority = '高' and source = 'OUT-1140522-007' and action_url is null and body = '函稿已建立，請進行清稿檢核與附件封裝。' and delivery_receipt is null and sent_at is null)
        or (id = 'NTF-003' and type = '交換失敗' and title = '新北市政府衛生局交換失敗' and target_role = '總務' and target_email is null and target_user_id is null and target_company_id is null and channel = 'Email + Line + 系統通知' and status = '未讀' and priority = '高' and source = 'OUT-1140519-006' and action_url is null and body = 'jAgent 回覆 failed，請確認機關代碼並重送。' and delivery_receipt is null and sent_at is null)
        or (id = 'NTF-004' and type = 'Token 到期' and title = 'jAgent Token 即將到期' and target_role = '行政部主任' and target_email is null and target_user_id is null and target_company_id is null and channel = 'Email + 系統通知' and status = '未讀' and priority = '中' and source = 'SEC-TOKEN' and action_url is null and body = 'Token 剩餘時間不足，請刷新或重新憑證登入。' and delivery_receipt is null and sent_at is null)
        or (id = 'NTF-005' and type = '逾期查核' and title = '收1140522-00013 分派逾期' and target_role = '行政部主任' and target_email is null and target_user_id is null and target_company_id is null and channel = 'Line 工作群組' and status = '未讀' and priority = '高' and source = 'TRK-003' and action_url is null and body = '收文尚未完成分派，請啟動逾期查核提醒。' and delivery_receipt is null and sent_at is null)
      )
  ) then
    raise exception using errcode = '55000', message = 'demo_notification_signature_mismatch';
  end if;

  for v_notification_id in
    select id from public.notifications
    where id in ('NTF-001', 'NTF-002', 'NTF-003', 'NTF-004', 'NTF-005')
    order by id
  loop
    for v_fk in
      select namespace_row.nspname as schema_name,
             relation_row.relname as table_name,
             child_attribute.attname as column_name
      from pg_catalog.pg_constraint constraint_row
      join pg_catalog.pg_class relation_row on relation_row.oid = constraint_row.conrelid
      join pg_catalog.pg_namespace namespace_row on namespace_row.oid = relation_row.relnamespace
      join lateral pg_catalog.unnest(constraint_row.conkey) with ordinality child_key(attnum, position) on true
      join lateral pg_catalog.unnest(constraint_row.confkey) with ordinality parent_key(attnum, position) on parent_key.position = child_key.position
      join pg_catalog.pg_attribute child_attribute on child_attribute.attrelid = constraint_row.conrelid and child_attribute.attnum = child_key.attnum
      join pg_catalog.pg_attribute parent_attribute on parent_attribute.attrelid = constraint_row.confrelid and parent_attribute.attnum = parent_key.attnum
      where constraint_row.contype = 'f'
        and constraint_row.confrelid = 'public.notifications'::pg_catalog.regclass
        and parent_attribute.attname = 'id'
        and pg_catalog.cardinality(constraint_row.conkey) = 1
    loop
      execute pg_catalog.format('select exists (select 1 from %I.%I where %I = $1)', v_fk.schema_name, v_fk.table_name, v_fk.column_name)
        into v_has_reference using v_notification_id;
      if v_has_reference then
        raise exception using errcode = '55000', message = pg_catalog.format('demo_notification_has_reference:%I.%I', v_fk.schema_name, v_fk.table_name);
      end if;
    end loop;
  end loop;

  delete from public.notifications
  where id in ('NTF-001', 'NTF-002', 'NTF-003', 'NTF-004', 'NTF-005');

  if exists (
    select 1 from public.notifications
    where id in ('NTF-001', 'NTF-002', 'NTF-003', 'NTF-004', 'NTF-005')
  ) then
    raise exception using errcode = '55000', message = 'demo_notification_delete_failed';
  end if;
end
$cleanup_demo_notifications$;

-- AUD-SEED-001 is intentionally not deleted if an older environment already
-- recorded it: audit_logs is append-only, and cleanup must not weaken or bypass
-- that evidence-preservation control. Fresh environments no longer create it.

do $cleanup_demo_certificates$
declare
  v_fk record;
  v_certificate_id text;
  v_has_reference boolean;
begin
  perform 1
  from public.signing_certificates
  where id in ('CERT-SEAL-001', 'CERT-SEAL-002', 'CERT-TSA-001')
  for update;

  if exists (
    select 1
    from public.signing_certificates
    where id in ('CERT-SEAL-001', 'CERT-SEAL-002', 'CERT-TSA-001')
      and (
        not (
          (id = 'CERT-SEAL-001' and owner = '行政部主任' and subject = 'CN=Suiyuecare Admin Chief Seal,O=Suiyuecare' and issuer = 'Suiyuecare Internal CA' and serial_no = 'SYC-SEAL-2026-0001' and algorithm = 'HMAC-SHA256-RSA-PSS-READY' and valid_from = '2026-01-01'::timestamptz and valid_to = '2027-12-31'::timestamptz and status = '啟用' and fingerprint_sha256 = 'SHA256-CERT-SEAL-001' and certificate_type = 'organization')
          or (id = 'CERT-SEAL-002' and owner = '總務' and subject = 'CN=Suiyuecare General Affairs Seal,O=Suiyuecare' and issuer = 'Suiyuecare Internal CA' and serial_no = 'SYC-GA-2026-0002' and algorithm = 'HMAC-SHA256-RSA-PSS-READY' and valid_from = '2026-01-01'::timestamptz and valid_to = '2027-12-31'::timestamptz and status = '啟用' and fingerprint_sha256 = 'SHA256-CERT-SEAL-002' and certificate_type = 'business')
          or (id = 'CERT-TSA-001' and owner = '系統時間戳' and subject = 'CN=Suiyuecare TSA,O=Suiyuecare' and issuer = 'Suiyuecare Internal CA' and serial_no = 'SYC-TSA-2026-0001' and algorithm = 'RFC3161-TSA-SIM' and valid_from = '2026-01-01'::timestamptz and valid_to = '2027-12-31'::timestamptz and status = '啟用' and fingerprint_sha256 = 'SHA256-CERT-TSA-001' and certificate_type = 'tsa')
        )
      or key_usage is distinct from 'digitalSignature,nonRepudiation'
      or extended_key_usage is distinct from 'documentSigning,clientAuth'
      or chain_status is distinct from '待驗證'
      or ocsp_status is distinct from '待查詢'
      or crl_status is distinct from '待查詢'
      or tsa_url is distinct from 'https://tsa.suiyuecare.local/rfc3161'
      or ocsp_url is distinct from 'https://ocsp.suiyuecare.local'
      or crl_url is distinct from 'https://crl.suiyuecare.local/root.crl'
      or root_ca_fingerprint is distinct from 'SHA256-SYC-ROOT-001'
      or last_validated_at is not null
      or validation_report_json is not null
      )
  ) then
    raise exception using errcode = '55000', message = 'demo_certificate_signature_mismatch';
  end if;

  for v_certificate_id in
    select id from public.signing_certificates
    where id in ('CERT-SEAL-001', 'CERT-SEAL-002', 'CERT-TSA-001')
    order by id
  loop
    for v_fk in
      select namespace_row.nspname as schema_name,
             relation_row.relname as table_name,
             child_attribute.attname as column_name
      from pg_catalog.pg_constraint constraint_row
      join pg_catalog.pg_class relation_row on relation_row.oid = constraint_row.conrelid
      join pg_catalog.pg_namespace namespace_row on namespace_row.oid = relation_row.relnamespace
      join lateral pg_catalog.unnest(constraint_row.conkey) with ordinality child_key(attnum, position) on true
      join lateral pg_catalog.unnest(constraint_row.confkey) with ordinality parent_key(attnum, position) on parent_key.position = child_key.position
      join pg_catalog.pg_attribute child_attribute on child_attribute.attrelid = constraint_row.conrelid and child_attribute.attnum = child_key.attnum
      join pg_catalog.pg_attribute parent_attribute on parent_attribute.attrelid = constraint_row.confrelid and parent_attribute.attnum = parent_key.attnum
      where constraint_row.contype = 'f'
        and constraint_row.confrelid = 'public.signing_certificates'::pg_catalog.regclass
        and parent_attribute.attname = 'id'
        and pg_catalog.cardinality(constraint_row.conkey) = 1
    loop
      execute pg_catalog.format('select exists (select 1 from %I.%I where %I = $1)', v_fk.schema_name, v_fk.table_name, v_fk.column_name)
        into v_has_reference using v_certificate_id;
      if v_has_reference then
        raise exception using errcode = '55000', message = pg_catalog.format('demo_certificate_has_reference:%I.%I', v_fk.schema_name, v_fk.table_name);
      end if;
    end loop;
  end loop;

  delete from public.signing_certificates
  where id in ('CERT-SEAL-001', 'CERT-SEAL-002', 'CERT-TSA-001');

  if exists (
    select 1 from public.signing_certificates
    where id in ('CERT-SEAL-001', 'CERT-SEAL-002', 'CERT-TSA-001')
  ) then
    raise exception using errcode = '55000', message = 'demo_certificate_delete_failed';
  end if;
end
$cleanup_demo_certificates$;

-- DOC-ADMIN-1140523-001 was inserted by a historical isolation demo after the
-- core seed. Delete it only when the complete immutable seed signature still
-- matches and no child table shows that it was ever used for real activity.
-- This is deliberately fail closed: an ID collision or any reference aborts
-- the migration instead of cascading away evidence.
do $cleanup_admin_demo$
declare
  v_fk record;
  v_has_reference boolean;
  v_deleted integer;
begin
  perform 1
  from public.documents
  where id = 'DOC-ADMIN-1140523-001'
  for update;

  if not found then
    return;
  end if;

  if not exists (
    select 1
    from public.documents
    where id = 'DOC-ADMIN-1140523-001'
      and doc_no = '行管字第1140523001號'
      and direction = '發文'
      and doc_type = '函'
      and priority = '普通件'
      and security_level = '普通'
      and agency_name = '臺北市政府社會局'
      and agency_code = 'A63000000J'
      and subject = '檢送行政部內部流程控管與清稿規則修訂資料。'
      and body = '本件屬行政部主任工作區範例，用於驗證總務與行政部門公文隔離。'
      and status = '待清稿'
      and owner = '行政部主任'
      and department = '行政部'
      and due_date = '2026-05-30'
      and received_at is null
      and retention_policy_code = 'EDOC-SEAL-15Y'
      and retention_years = 15
      and retention_until = (pg_catalog.left(created_at, 10)::date + pg_catalog.make_interval(years => retention_years))::date
      and legal_hold = false
      and disposition_status = '保存中'
      and disposed_at is null
      and confidentiality_scope = '一般'
      and company_name = '歲悅長照股份有限公司'
      and seal_plan_json = '{}'
      and metadata_json = '{}'
      and updated_at = created_at
  ) then
    raise exception using
      errcode = '55000',
      message = 'admin_demo_document_signature_mismatch';
  end if;

  if exists (
    select 1 from public.document_acl
    where id in ('ACL-006', 'ACL-007')
      and not (
        (id = 'ACL-006' and document_id = 'DOC-ADMIN-1140523-001' and principal_type = 'role' and principal_id = '行政部主任' and can_view = true and can_sign = true and can_download = true and can_seal = true and can_delegate = true and reason = '行政部門內部清稿與維運公文。' and granted_by = 'system' and expires_at is null)
        or (id = 'ACL-007' and document_id = 'DOC-ADMIN-1140523-001' and principal_type = 'role' and principal_id = '總務' and can_view = false and can_sign = false and can_download = false and can_seal = false and can_delegate = false and reason = '明確隔離總務收文池與行政部內部公文。' and granted_by = 'system' and expires_at is null)
      )
  ) then
    raise exception using errcode = '55000', message = 'admin_demo_acl_signature_mismatch';
  end if;

  if exists (
    select 1 from public.document_acl_events
    where id = 'ACLEVT-003'
      and not (
        document_id = 'DOC-ADMIN-1140523-001'
        and actor = 'system'
        and action = '建立隔離 ACL'
        and detail = '行政部主任公文對總務明確關閉。'
      )
  ) then
    raise exception using errcode = '55000', message = 'admin_demo_acl_event_signature_mismatch';
  end if;

  if exists (
    select 1 from public.file_objects where document_id = 'DOC-ADMIN-1140523-001'
  ) or exists (
    select 1 from public.pdf_versions where document_id = 'DOC-ADMIN-1140523-001'
  ) or exists (
    select 1 from public.signature_provider_events where document_id = 'DOC-ADMIN-1140523-001'
  ) or exists (
    select 1 from public.seal_applications where document_id = 'DOC-ADMIN-1140523-001'
  ) then
    raise exception using errcode = '55000', message = 'admin_demo_document_has_untracked_activity';
  end if;

  perform pg_temp.edoc_demo_assert_no_fk_references(
    'public.document_acl_events'::pg_catalog.regclass,
    'ACLEVT-003',
    'admin_demo_acl_event_has_fk_reference'
  );

  for v_fk in
    select id from public.document_acl
    where id in ('ACL-006', 'ACL-007')
    order by id
  loop
    perform pg_temp.edoc_demo_assert_no_fk_references(
      'public.document_acl'::pg_catalog.regclass,
      v_fk.id,
      'admin_demo_acl_has_fk_reference'
    );
  end loop;

  delete from public.document_acl_events where id = 'ACLEVT-003';
  if exists (select 1 from public.document_acl_events where id = 'ACLEVT-003') then
    raise exception using errcode = '55000', message = 'admin_demo_acl_event_delete_failed';
  end if;

  delete from public.document_acl where id in ('ACL-006', 'ACL-007');
  if exists (select 1 from public.document_acl where id in ('ACL-006', 'ACL-007')) then
    raise exception using errcode = '55000', message = 'admin_demo_acl_delete_failed';
  end if;

  for v_fk in
    select
      namespace_row.nspname as schema_name,
      relation_row.relname as table_name,
      child_attribute.attname as column_name
    from pg_catalog.pg_constraint constraint_row
    join pg_catalog.pg_class relation_row
      on relation_row.oid = constraint_row.conrelid
    join pg_catalog.pg_namespace namespace_row
      on namespace_row.oid = relation_row.relnamespace
    join lateral pg_catalog.unnest(constraint_row.conkey)
      with ordinality child_key(attnum, position) on true
    join lateral pg_catalog.unnest(constraint_row.confkey)
      with ordinality parent_key(attnum, position)
      on parent_key.position = child_key.position
    join pg_catalog.pg_attribute child_attribute
      on child_attribute.attrelid = constraint_row.conrelid
     and child_attribute.attnum = child_key.attnum
    join pg_catalog.pg_attribute parent_attribute
      on parent_attribute.attrelid = constraint_row.confrelid
     and parent_attribute.attnum = parent_key.attnum
    where constraint_row.contype = 'f'
      and constraint_row.confrelid = 'public.documents'::pg_catalog.regclass
      and parent_attribute.attname = 'id'
      and pg_catalog.cardinality(constraint_row.conkey) = 1
  loop
    execute pg_catalog.format(
      'select exists (select 1 from %I.%I where %I = $1)',
      v_fk.schema_name,
      v_fk.table_name,
      v_fk.column_name
    )
    into v_has_reference
    using 'DOC-ADMIN-1140523-001';

    if v_has_reference then
      raise exception using
        errcode = '55000',
        message = pg_catalog.format(
          'admin_demo_document_has_reference:%I.%I',
          v_fk.schema_name,
          v_fk.table_name
        );
    end if;
  end loop;

  perform pg_temp.edoc_demo_assert_no_fk_references(
    'public.documents'::pg_catalog.regclass,
    'DOC-ADMIN-1140523-001',
    'admin_demo_document_has_fk_reference'
  );

  update public.documents
  set retention_until = current_date
  where id = 'DOC-ADMIN-1140523-001';

  delete from public.documents
  where id = 'DOC-ADMIN-1140523-001'
    and doc_no = '行管字第1140523001號'
    and body = '本件屬行政部主任工作區範例，用於驗證總務與行政部門公文隔離。';

  get diagnostics v_deleted = row_count;
  if v_deleted <> 1 then
    raise exception using
      errcode = '55000',
      message = 'admin_demo_document_delete_failed';
  end if;
end
$cleanup_admin_demo$;

-- Remove the three legacy seed documents only after validating both their full
-- row signatures and every known seed child row. Unknown activity, changed
-- seed rows, file access history, signatures, or any other FK reference aborts
-- the migration. That prevents an old demo identifier from becoming a broad
-- cascade-delete primitive in a real environment.
do $cleanup_legacy_demo_documents$
declare
  v_fk record;
  v_parent record;
  v_document_id text;
  v_has_reference boolean;
begin
  perform 1
  from public.documents
  where id in (
    'DOC-IN-1140522-00018',
    'DOC-OUT-1140522-007',
    'DOC-OUT-1140519-006'
  )
  for update;

  if exists (
    select 1
    from public.documents
    where id in (
      'DOC-IN-1140522-00018',
      'DOC-OUT-1140522-007',
      'DOC-OUT-1140519-006'
    )
      and not (
        (
          id = 'DOC-IN-1140522-00018'
          and doc_no = '收1140522-00018'
          and direction = '收文'
          and doc_type = '函'
          and priority = '速件'
          and security_level = '普通'
          and agency_name = '衛生福利部'
          and agency_code = 'A21000000I'
          and subject = '長照服務品質稽核資料補件通知'
          and body = 'jAgent 已拉取，待登錄收文號與附件完整性。'
          and status = '待登錄'
          and owner = '總務'
          and department = '總管理處'
          and due_date = '2026-05-29'
          and received_at = '2026-05-22 09:42'
          and retention_policy_code = 'EDOC-STD-07Y'
          and retention_years = 7
          and retention_until = (pg_catalog.left(created_at, 10)::date + pg_catalog.make_interval(years => retention_years))::date
          and legal_hold = false
          and disposition_status = '保存中'
          and disposed_at is null
          and confidentiality_scope = '一般'
          and company_name = '歲悅長照股份有限公司'
          and seal_plan_json = '{}'
          and metadata_json = '{}'
          and updated_at = created_at
        ) or (
          id = 'DOC-OUT-1140522-007'
          and doc_no = '歲悅字第1140522007號'
          and direction = '發文'
          and doc_type = '函'
          and priority = '速件'
          and security_level = '普通'
          and agency_name = '臺北市政府社會局'
          and agency_code = 'A63000000J'
          and subject = '檢送本公司日間照顧中心設立許可補正資料，請查照。'
          and body = '依貴局通知辦理，檢附補正資料、附件清冊及相關證明文件。'
          and status = '待清稿'
          and owner = '總務'
          and department = '總管理處'
          and due_date = '2026-05-29'
          and received_at is null
          and retention_policy_code = 'EDOC-SEAL-15Y'
          and retention_years = 15
          and retention_until = (pg_catalog.left(created_at, 10)::date + pg_catalog.make_interval(years => retention_years))::date
          and legal_hold = false
          and disposition_status = '保存中'
          and disposed_at is null
          and confidentiality_scope = '一般'
          and company_name = '歲悅長照股份有限公司'
          and seal_plan_json = '{}'
          and metadata_json = '{}'
          and updated_at = created_at
        ) or (
          id = 'DOC-OUT-1140519-006'
          and doc_no = '歲悅字第1140519006號'
          and direction = '發文'
          and doc_type = '函'
          and priority = '速件'
          and security_level = '普通'
          and agency_name = '新北市政府衛生局'
          and agency_code = 'A65000000I'
          and subject = '補送居家服務品質改善計畫。'
          and body = '補送改善計畫附件，請惠予備查。'
          and status = '交換失敗'
          and owner = '總務'
          and department = '居家照顧課'
          and due_date = '2026-05-24'
          and received_at is null
          and retention_policy_code = 'EDOC-SEAL-15Y'
          and retention_years = 15
          and retention_until = (pg_catalog.left(created_at, 10)::date + pg_catalog.make_interval(years => retention_years))::date
          and legal_hold = false
          and disposition_status = '保存中'
          and disposed_at is null
          and confidentiality_scope = '一般'
          and company_name = '歲悅長照股份有限公司'
          and seal_plan_json = '{}'
          and metadata_json = '{}'
          and updated_at = created_at
        )
      )
  ) then
    raise exception using
      errcode = '55000',
      message = 'legacy_demo_document_signature_mismatch';
  end if;

  if exists (
    select 1 from public.attachments
    where id in ('ATT-001', 'ATT-002', 'ATT-003')
      and not (
        (id = 'ATT-001' and document_id = 'DOC-IN-1140522-00018' and file_name = '稽核補件通知.pdf' and version = 'v1' and mime_type = 'application/pdf' and size_bytes = 838860 and sha256 = 'SHA256-C8202AF1' and scan_status = '待掃描' and storage_key = 'inbound/1140522/稽核補件通知.pdf' and retention_until is null and legal_hold = false)
        or (id = 'ATT-002' and document_id = 'DOC-IN-1140522-00018' and file_name = '附件清冊.xml' and version = 'v1' and mime_type = 'application/xml' and size_bytes = 4096 and sha256 = 'SHA256-AD997210' and scan_status = '待掃描' and storage_key = 'inbound/1140522/附件清冊.xml' and retention_until is null and legal_hold = false)
        or (id = 'ATT-003' and document_id = 'DOC-OUT-1140522-007' and file_name = '設立許可補正資料.pdf' and version = 'v2' and mime_type = 'application/pdf' and size_bytes = 19496960 and sha256 = 'SHA256-4D91FA33' and scan_status = '雜湊通過' and storage_key = 'outbound/1140522/設立許可補正資料.pdf' and retention_until is null and legal_hold = false)
      )
  ) then
    raise exception using errcode = '55000', message = 'legacy_demo_attachment_signature_mismatch';
  end if;

  if exists (
    select 1 from public.attachment_security
    where id in ('ASEC-ATT-001', 'ASEC-ATT-002', 'ASEC-ATT-003')
      and not (
        (id = 'ASEC-ATT-001' and attachment_id = 'ATT-001' and document_id = 'DOC-IN-1140522-00018' and file_name = '稽核補件通知.pdf' and file_ext = 'pdf' and size_bytes = 838860 and max_size_bytes = 52428800 and scan_status = '待掃描' and scan_engine = 'ClamAV-compatible' and scan_signature = 'SIG-SEED-001' and mask_status = '需遮罩' and sensitive_hits_json = '["身分證","電話"]'::jsonb and confidential_level = '密' and allowed_roles = '行政部主任,主任,執行長' and watermark_status = '未下載' and quarantine_reason = '' and backup_id = '' and last_accessed_by is null and last_accessed_at is null)
        or (id = 'ASEC-ATT-002' and attachment_id = 'ATT-002' and document_id = 'DOC-IN-1140522-00018' and file_name = '附件清冊.xml' and file_ext = 'xml' and size_bytes = 4096 and max_size_bytes = 52428800 and scan_status = '待掃描' and scan_engine = 'ClamAV-compatible' and scan_signature = 'SIG-SEED-002' and mask_status = '未遮罩' and sensitive_hits_json = '[]'::jsonb and confidential_level = '普通' and allowed_roles = '一般角色' and watermark_status = '未下載' and quarantine_reason = '' and backup_id = '' and last_accessed_by is null and last_accessed_at is null)
        or (id = 'ASEC-ATT-003' and attachment_id = 'ATT-003' and document_id = 'DOC-OUT-1140522-007' and file_name = '設立許可補正資料.pdf' and file_ext = 'pdf' and size_bytes = 19496960 and max_size_bytes = 52428800 and scan_status = '已通過' and scan_engine = 'ClamAV-compatible' and scan_signature = 'SIG-SEED-003' and mask_status = '未遮罩' and sensitive_hits_json = '[]'::jsonb and confidential_level = '普通' and allowed_roles = '一般角色' and watermark_status = '未下載' and quarantine_reason = '' and backup_id = '' and last_accessed_by is null and last_accessed_at is null)
      )
  ) then
    raise exception using errcode = '55000', message = 'legacy_demo_attachment_security_signature_mismatch';
  end if;

  if exists (
    select 1 from public.exchange_tasks
    where id in ('TASK-001', 'TASK-002')
      and not (
        (id = 'TASK-001' and document_id = 'DOC-OUT-1140522-007' and direction = '發文' and target_agency = '臺北市政府社會局' and status = '待清稿' and package_id is null and retry_count = 0 and next_check_at = '2026-05-23 09:00')
        or (id = 'TASK-002' and document_id = 'DOC-OUT-1140519-006' and direction = '發文' and target_agency = '新北市政府衛生局' and status = '交換失敗' and package_id = 'PKG-1140519-006' and retry_count = 1 and next_check_at = '2026-05-23 09:00')
      )
  ) then
    raise exception using errcode = '55000', message = 'legacy_demo_exchange_task_signature_mismatch';
  end if;

  if exists (
    select 1 from public.document_acl
    where id in ('ACL-001', 'ACL-002', 'ACL-003', 'ACL-004', 'ACL-005')
      and not (
        (id = 'ACL-001' and document_id = 'DOC-IN-1140522-00018' and principal_type = 'role' and principal_id = '總務' and can_view = true and can_sign = false and can_download = true and can_seal = false and can_delegate = true and reason = '總務統一收文、登錄與分派。' and granted_by = 'system' and expires_at is null)
        or (id = 'ACL-002' and document_id = 'DOC-IN-1140522-00018' and principal_type = 'role' and principal_id = '主任' and can_view = true and can_sign = true and can_download = true and can_seal = false and can_delegate = false and reason = '分派後由部門主管承接與簽核。' and granted_by = 'system' and expires_at is null)
        or (id = 'ACL-003' and document_id = 'DOC-OUT-1140522-007' and principal_type = 'role' and principal_id = '業務助理' and can_view = true and can_sign = false and can_download = false and can_seal = false and can_delegate = false and reason = '承辦撰稿，只能檢視與補正內容。' and granted_by = 'system' and expires_at is null)
        or (id = 'ACL-004' and document_id = 'DOC-OUT-1140522-007' and principal_type = 'role' and principal_id = '行政部主任' and can_view = true and can_sign = true and can_download = true and can_seal = true and can_delegate = true and reason = '清稿、會辦、用印前核准。' and granted_by = 'system' and expires_at is null)
        or (id = 'ACL-005' and document_id = 'DOC-OUT-1140522-007' and principal_type = 'role' and principal_id = '總務' and can_view = true and can_sign = false and can_download = true and can_seal = true and can_delegate = false and reason = '封裝、用印與送交 jAgent。' and granted_by = 'system' and expires_at is null)
      )
  ) then
    raise exception using errcode = '55000', message = 'legacy_demo_acl_signature_mismatch';
  end if;

  if exists (
    select 1 from public.document_acl_events
    where id in ('ACLEVT-001', 'ACLEVT-002')
      and not (
        (id = 'ACLEVT-001' and document_id = 'DOC-IN-1140522-00018' and actor = 'system' and action = '建立文件 ACL' and detail = '總務可登錄下載；主任可檢視簽核。')
        or (id = 'ACLEVT-002' and document_id = 'DOC-OUT-1140522-007' and actor = 'system' and action = '建立文件 ACL' and detail = '業務助理、行政部主任、總務依流程分權。')
      )
  ) then
    raise exception using errcode = '55000', message = 'legacy_demo_acl_event_signature_mismatch';
  end if;

  if exists (
    select 1 from public.seal_applications
    where id = 'USEAL-SEED-001'
      and not (
        document_id = 'DOC-OUT-1140522-007'
        and seal_id = 'SEAL-001'
        and applicant = '總務'
        and approver = '行政部主任'
        and status = '待簽核'
        and reason = '日照中心設立許可補正資料發文用印'
        and stamp_no is null
        and pdf_before_version_id is null
        and pdf_after_version_id is null
        and approved_at is null
        and signature_id is null
        and provider_status is null
        and failure_reason is null
        and evidence_json is null
        and updated_at is null
        and application_type = 'official_document'
        and company_name = '歲悅股份有限公司'
        and department is null
        and title is null
        and source_pdf_file_object_id is null
        and source_pdf_sha256 is null
        and source_pdf_name is null
        and locked_pdf_sha256 is null
        and locked_positions_sha256 is null
        and stamp_positions_json = '[]'::jsonb
        and approval_route_code is null
        and approval_route_name is null
        and approval_snapshot_json = '{}'::jsonb
        and current_step_no = 1
        and current_step_name is null
        and current_approver_role is null
        and applicant_user_id is null
        and applicant_name is null
        and applicant_email is null
        and reject_reason is null
        and returned_at is null
        and completed_at is null
        and notification_id is null
      )
  ) then
    raise exception using errcode = '55000', message = 'legacy_demo_seal_application_signature_mismatch';
  end if;

  if exists (
    select 1
    from public.approval_step_actor_snapshots
    where seal_application_id = 'USEAL-SEED-001'
       or source_id = 'USEAL-SEED-001'
  ) then
    raise exception using errcode = '55000', message = 'legacy_demo_seal_application_has_actor_snapshot';
  end if;

  if exists (
    select 1 from public.file_objects
    where document_id in ('DOC-IN-1140522-00018', 'DOC-OUT-1140522-007', 'DOC-OUT-1140519-006')
  ) or exists (
    select 1 from public.pdf_versions
    where document_id in ('DOC-IN-1140522-00018', 'DOC-OUT-1140522-007', 'DOC-OUT-1140519-006')
  ) or exists (
    select 1 from public.signature_provider_events
    where document_id in ('DOC-IN-1140522-00018', 'DOC-OUT-1140522-007', 'DOC-OUT-1140519-006')
  ) or exists (
    select 1 from public.seal_applications
    where document_id in ('DOC-IN-1140522-00018', 'DOC-OUT-1140522-007', 'DOC-OUT-1140519-006')
      and id <> 'USEAL-SEED-001'
  ) then
    raise exception using errcode = '55000', message = 'legacy_demo_document_has_untracked_activity';
  end if;

  for v_parent in
    select * from (values
      ('ASEC-ATT-001'),
      ('ASEC-ATT-002'),
      ('ASEC-ATT-003')
    ) as security_row(parent_id)
  loop
    perform pg_temp.edoc_demo_assert_no_fk_references(
      'public.attachment_security'::pg_catalog.regclass,
      v_parent.parent_id,
      'legacy_demo_attachment_security_has_fk_reference'
    );
  end loop;

  delete from public.attachment_security
  where id in ('ASEC-ATT-001', 'ASEC-ATT-002', 'ASEC-ATT-003');

  if exists (
    select 1 from public.attachment_security
    where id in ('ASEC-ATT-001', 'ASEC-ATT-002', 'ASEC-ATT-003')
  ) then
    raise exception using errcode = '55000', message = 'legacy_demo_attachment_security_delete_failed';
  end if;

  -- Refuse to orphan any access log or later-added child record that points at
  -- one of the known seed attachments.
  for v_parent in
    select * from (values
      ('public.attachments'::pg_catalog.regclass, 'ATT-001'),
      ('public.attachments'::pg_catalog.regclass, 'ATT-002'),
      ('public.attachments'::pg_catalog.regclass, 'ATT-003')
    ) as parent_row(parent_relation, parent_id)
  loop
    for v_fk in
      select namespace_row.nspname as schema_name,
             relation_row.relname as table_name,
             child_attribute.attname as column_name
      from pg_catalog.pg_constraint constraint_row
      join pg_catalog.pg_class relation_row on relation_row.oid = constraint_row.conrelid
      join pg_catalog.pg_namespace namespace_row on namespace_row.oid = relation_row.relnamespace
      join lateral pg_catalog.unnest(constraint_row.conkey) with ordinality child_key(attnum, position) on true
      join lateral pg_catalog.unnest(constraint_row.confkey) with ordinality parent_key(attnum, position) on parent_key.position = child_key.position
      join pg_catalog.pg_attribute child_attribute on child_attribute.attrelid = constraint_row.conrelid and child_attribute.attnum = child_key.attnum
      join pg_catalog.pg_attribute parent_attribute on parent_attribute.attrelid = constraint_row.confrelid and parent_attribute.attnum = parent_key.attnum
      where constraint_row.contype = 'f'
        and constraint_row.confrelid = v_parent.parent_relation
        and parent_attribute.attname = 'id'
        and pg_catalog.cardinality(constraint_row.conkey) = 1
    loop
      execute pg_catalog.format('select exists (select 1 from %I.%I where %I = $1)', v_fk.schema_name, v_fk.table_name, v_fk.column_name)
        into v_has_reference using v_parent.parent_id;
      if v_has_reference then
        raise exception using errcode = '55000', message = pg_catalog.format('legacy_demo_attachment_has_reference:%I.%I', v_fk.schema_name, v_fk.table_name);
      end if;
    end loop;

    perform pg_temp.edoc_demo_assert_no_fk_references(
      v_parent.parent_relation,
      v_parent.parent_id,
      'legacy_demo_attachment_has_fk_reference'
    );
  end loop;

  delete from public.attachments where id in ('ATT-001', 'ATT-002', 'ATT-003');

  if exists (
    select 1 from public.attachments
    where id in ('ATT-001', 'ATT-002', 'ATT-003')
  ) then
    raise exception using errcode = '55000', message = 'legacy_demo_attachment_delete_failed';
  end if;

  for v_parent in
    select * from (values
      ('public.exchange_tasks'::pg_catalog.regclass, 'TASK-001'),
      ('public.exchange_tasks'::pg_catalog.regclass, 'TASK-002')
    ) as parent_row(parent_relation, parent_id)
  loop
    for v_fk in
      select namespace_row.nspname as schema_name,
             relation_row.relname as table_name,
             child_attribute.attname as column_name
      from pg_catalog.pg_constraint constraint_row
      join pg_catalog.pg_class relation_row on relation_row.oid = constraint_row.conrelid
      join pg_catalog.pg_namespace namespace_row on namespace_row.oid = relation_row.relnamespace
      join lateral pg_catalog.unnest(constraint_row.conkey) with ordinality child_key(attnum, position) on true
      join lateral pg_catalog.unnest(constraint_row.confkey) with ordinality parent_key(attnum, position) on parent_key.position = child_key.position
      join pg_catalog.pg_attribute child_attribute on child_attribute.attrelid = constraint_row.conrelid and child_attribute.attnum = child_key.attnum
      join pg_catalog.pg_attribute parent_attribute on parent_attribute.attrelid = constraint_row.confrelid and parent_attribute.attnum = parent_key.attnum
      where constraint_row.contype = 'f'
        and constraint_row.confrelid = v_parent.parent_relation
        and parent_attribute.attname = 'id'
        and pg_catalog.cardinality(constraint_row.conkey) = 1
    loop
      execute pg_catalog.format('select exists (select 1 from %I.%I where %I = $1)', v_fk.schema_name, v_fk.table_name, v_fk.column_name)
        into v_has_reference using v_parent.parent_id;
      if v_has_reference then
        raise exception using errcode = '55000', message = pg_catalog.format('legacy_demo_exchange_task_has_reference:%I.%I', v_fk.schema_name, v_fk.table_name);
      end if;
    end loop;

    perform pg_temp.edoc_demo_assert_no_fk_references(
      v_parent.parent_relation,
      v_parent.parent_id,
      'legacy_demo_exchange_task_has_fk_reference'
    );
  end loop;

  delete from public.exchange_tasks where id in ('TASK-001', 'TASK-002');
  if exists (select 1 from public.exchange_tasks where id in ('TASK-001', 'TASK-002')) then
    raise exception using errcode = '55000', message = 'legacy_demo_exchange_task_delete_failed';
  end if;

  for v_parent in
    select * from (values
      ('public.document_acl_events'::pg_catalog.regclass, 'ACLEVT-001', 'legacy_demo_acl_event_has_fk_reference'),
      ('public.document_acl_events'::pg_catalog.regclass, 'ACLEVT-002', 'legacy_demo_acl_event_has_fk_reference'),
      ('public.document_acl'::pg_catalog.regclass, 'ACL-001', 'legacy_demo_acl_has_fk_reference'),
      ('public.document_acl'::pg_catalog.regclass, 'ACL-002', 'legacy_demo_acl_has_fk_reference'),
      ('public.document_acl'::pg_catalog.regclass, 'ACL-003', 'legacy_demo_acl_has_fk_reference'),
      ('public.document_acl'::pg_catalog.regclass, 'ACL-004', 'legacy_demo_acl_has_fk_reference'),
      ('public.document_acl'::pg_catalog.regclass, 'ACL-005', 'legacy_demo_acl_has_fk_reference'),
      ('public.seal_applications'::pg_catalog.regclass, 'USEAL-SEED-001', 'legacy_demo_seal_application_has_fk_reference')
    ) as child_row(parent_relation, parent_id, fk_error)
  loop
    perform pg_temp.edoc_demo_assert_no_fk_references(
      v_parent.parent_relation,
      v_parent.parent_id,
      v_parent.fk_error
    );
  end loop;

  delete from public.document_acl_events where id in ('ACLEVT-001', 'ACLEVT-002');
  if exists (select 1 from public.document_acl_events where id in ('ACLEVT-001', 'ACLEVT-002')) then
    raise exception using errcode = '55000', message = 'legacy_demo_acl_event_delete_failed';
  end if;

  delete from public.document_acl where id in ('ACL-001', 'ACL-002', 'ACL-003', 'ACL-004', 'ACL-005');
  if exists (select 1 from public.document_acl where id in ('ACL-001', 'ACL-002', 'ACL-003', 'ACL-004', 'ACL-005')) then
    raise exception using errcode = '55000', message = 'legacy_demo_acl_delete_failed';
  end if;

  delete from public.seal_applications where id = 'USEAL-SEED-001';
  if exists (select 1 from public.seal_applications where id = 'USEAL-SEED-001') then
    raise exception using errcode = '55000', message = 'legacy_demo_seal_application_delete_failed';
  end if;

  for v_document_id in
    select id from public.documents
    where id in ('DOC-IN-1140522-00018', 'DOC-OUT-1140522-007', 'DOC-OUT-1140519-006')
    order by id
  loop
    for v_fk in
      select namespace_row.nspname as schema_name,
             relation_row.relname as table_name,
             child_attribute.attname as column_name
      from pg_catalog.pg_constraint constraint_row
      join pg_catalog.pg_class relation_row on relation_row.oid = constraint_row.conrelid
      join pg_catalog.pg_namespace namespace_row on namespace_row.oid = relation_row.relnamespace
      join lateral pg_catalog.unnest(constraint_row.conkey) with ordinality child_key(attnum, position) on true
      join lateral pg_catalog.unnest(constraint_row.confkey) with ordinality parent_key(attnum, position) on parent_key.position = child_key.position
      join pg_catalog.pg_attribute child_attribute on child_attribute.attrelid = constraint_row.conrelid and child_attribute.attnum = child_key.attnum
      join pg_catalog.pg_attribute parent_attribute on parent_attribute.attrelid = constraint_row.confrelid and parent_attribute.attnum = parent_key.attnum
      where constraint_row.contype = 'f'
        and constraint_row.confrelid = 'public.documents'::pg_catalog.regclass
        and parent_attribute.attname = 'id'
        and pg_catalog.cardinality(constraint_row.conkey) = 1
    loop
      execute pg_catalog.format('select exists (select 1 from %I.%I where %I = $1)', v_fk.schema_name, v_fk.table_name, v_fk.column_name)
        into v_has_reference using v_document_id;
      if v_has_reference then
        raise exception using errcode = '55000', message = pg_catalog.format('legacy_demo_document_has_reference:%I.%I', v_fk.schema_name, v_fk.table_name);
      end if;
    end loop;

    perform pg_temp.edoc_demo_assert_no_fk_references(
      'public.documents'::pg_catalog.regclass,
      v_document_id,
      'legacy_demo_document_has_fk_reference'
    );

    update public.documents set retention_until = current_date where id = v_document_id;
    delete from public.documents where id = v_document_id;
  end loop;

  if exists (
    select 1 from public.documents
    where id in ('DOC-IN-1140522-00018', 'DOC-OUT-1140522-007', 'DOC-OUT-1140519-006')
  ) then
    raise exception using errcode = '55000', message = 'legacy_demo_document_delete_failed';
  end if;
end
$cleanup_legacy_demo_documents$;

do $cleanup_demo_recipients$
declare
  v_fk record;
  v_recipient_id text;
  v_has_reference boolean;
begin
  perform 1
  from public.recipients
  where id in ('REC-001', 'REC-002', 'REC-003', 'REC-004')
  for update;

  if exists (
    select 1
    from public.recipients
    where id in ('REC-001', 'REC-002', 'REC-003', 'REC-004')
      and not (
        (id = 'REC-001' and name = '臺北市政府社會局' and code = 'A63000000J' and exchange_center = 'G2B2C 統合交換中心' and status = '可交換' and contact = '文書收發窗口')
        or (id = 'REC-002' and name = '臺北市政府衛生局' and code = 'A63000000I' and exchange_center = 'G2B2C 統合交換中心' and status = '可交換' and contact = '衛生局收發')
        or (id = 'REC-003' and name = '新北市政府衛生局' and code = 'A65000000I' and exchange_center = '北區交換中心' and status = '可交換' and contact = '公文交換窗口')
        or (id = 'REC-004' and name = '衛生福利部' and code = 'A21000000I' and exchange_center = 'G2B2C 統合交換中心' and status = '可交換' and contact = '部本部總收文')
      )
  ) then
    raise exception using errcode = '55000', message = 'demo_recipient_signature_mismatch';
  end if;

  for v_recipient_id in
    select id from public.recipients
    where id in ('REC-001', 'REC-002', 'REC-003', 'REC-004')
    order by id
  loop
    for v_fk in
      select namespace_row.nspname as schema_name,
             relation_row.relname as table_name,
             child_attribute.attname as column_name
      from pg_catalog.pg_constraint constraint_row
      join pg_catalog.pg_class relation_row on relation_row.oid = constraint_row.conrelid
      join pg_catalog.pg_namespace namespace_row on namespace_row.oid = relation_row.relnamespace
      join lateral pg_catalog.unnest(constraint_row.conkey) with ordinality child_key(attnum, position) on true
      join lateral pg_catalog.unnest(constraint_row.confkey) with ordinality parent_key(attnum, position) on parent_key.position = child_key.position
      join pg_catalog.pg_attribute child_attribute on child_attribute.attrelid = constraint_row.conrelid and child_attribute.attnum = child_key.attnum
      join pg_catalog.pg_attribute parent_attribute on parent_attribute.attrelid = constraint_row.confrelid and parent_attribute.attnum = parent_key.attnum
      where constraint_row.contype = 'f'
        and constraint_row.confrelid = 'public.recipients'::pg_catalog.regclass
        and parent_attribute.attname = 'id'
        and pg_catalog.cardinality(constraint_row.conkey) = 1
    loop
      execute pg_catalog.format('select exists (select 1 from %I.%I where %I = $1)', v_fk.schema_name, v_fk.table_name, v_fk.column_name)
        into v_has_reference using v_recipient_id;
      if v_has_reference then
        raise exception using errcode = '55000', message = pg_catalog.format('demo_recipient_has_reference:%I.%I', v_fk.schema_name, v_fk.table_name);
      end if;
    end loop;
  end loop;

  delete from public.recipients
  where id in ('REC-001', 'REC-002', 'REC-003', 'REC-004');

  if exists (
    select 1 from public.recipients
    where id in ('REC-001', 'REC-002', 'REC-003', 'REC-004')
  ) then
    raise exception using errcode = '55000', message = 'demo_recipient_delete_failed';
  end if;
end
$cleanup_demo_recipients$;

do $cleanup_demo_ip_allowlist$
declare
  v_fk record;
  v_has_reference boolean;
begin
  perform 1 from public.ip_allowlist where id = 'IP-001' for update;
  if not found then
    return;
  end if;

  if not exists (
    select 1 from public.ip_allowlist
    where id = 'IP-001'
      and cidr = '203.0.113.0/24'
      and purpose = '歲悅辦公室與 VPN'
      and status = '啟用'
  ) then
    raise exception using errcode = '55000', message = 'demo_ip_allowlist_signature_mismatch';
  end if;

  for v_fk in
    select namespace_row.nspname as schema_name,
           relation_row.relname as table_name,
           child_attribute.attname as column_name
    from pg_catalog.pg_constraint constraint_row
    join pg_catalog.pg_class relation_row on relation_row.oid = constraint_row.conrelid
    join pg_catalog.pg_namespace namespace_row on namespace_row.oid = relation_row.relnamespace
    join lateral pg_catalog.unnest(constraint_row.conkey) with ordinality child_key(attnum, position) on true
    join lateral pg_catalog.unnest(constraint_row.confkey) with ordinality parent_key(attnum, position) on parent_key.position = child_key.position
    join pg_catalog.pg_attribute child_attribute on child_attribute.attrelid = constraint_row.conrelid and child_attribute.attnum = child_key.attnum
    join pg_catalog.pg_attribute parent_attribute on parent_attribute.attrelid = constraint_row.confrelid and parent_attribute.attnum = parent_key.attnum
    where constraint_row.contype = 'f'
      and constraint_row.confrelid = 'public.ip_allowlist'::pg_catalog.regclass
      and parent_attribute.attname = 'id'
      and pg_catalog.cardinality(constraint_row.conkey) = 1
  loop
    execute pg_catalog.format('select exists (select 1 from %I.%I where %I = $1)', v_fk.schema_name, v_fk.table_name, v_fk.column_name)
      into v_has_reference using 'IP-001';
    if v_has_reference then
      raise exception using errcode = '55000', message = pg_catalog.format('demo_ip_allowlist_has_reference:%I.%I', v_fk.schema_name, v_fk.table_name);
    end if;
  end loop;

  delete from public.ip_allowlist
  where id = 'IP-001'
    and cidr = '203.0.113.0/24'
    and purpose = '歲悅辦公室與 VPN'
    and status = '啟用';

  if exists (select 1 from public.ip_allowlist where id = 'IP-001') then
    raise exception using errcode = '55000', message = 'demo_ip_allowlist_delete_failed';
  end if;
end
$cleanup_demo_ip_allowlist$;

-- Retire the seven historical password-bearing accounts only when every row
-- still matches the immutable fixture signature and has never been linked to
-- Supabase Auth or used by a workflow. Known fixture devices are validated and
-- removed first; any other FK or notification reference aborts the migration.
do $cleanup_demo_accounts$
declare
  v_fk record;
  v_user_id text;
  v_has_reference boolean;
begin
  perform 1
  from public.users
  where id in ('USR-001', 'USR-002', 'USR-003', 'USR-004', 'USR-005', 'USR-006', 'USR-007')
  for update;

  if exists (
    select 1
    from public.users
    where id in ('USR-001', 'USR-002', 'USR-003', 'USR-004', 'USR-005', 'USR-006', 'USR-007')
      and (
        not (
        (id = 'USR-001' and name = '林總務' and email = 'edoc@suiyuecare.com' and unit = '總管理處' and title = '總務' and role = '總務' and provider = 'Google Workspace' and password_hash = 'pbkdf2_sha256$622057556f08af8493df12e74ad7983b$017349cb0c360d23daa17e3baeb64776915f73758a1845d064d5211a356745b7' and auth_user_id is null)
        or (id = 'USR-002' and name = '張行政' and email = 'records@suiyuecare.com' and unit = '行政部' and title = '行政部主任' and role = '行政部主任' and provider = 'Microsoft Entra' and password_hash = 'pbkdf2_sha256$84869515ca7759d72177dce8d4c2ca68$3baecf2b36ff55f0e19b92604f77bd030f88ec36c15e2c10e12ef9b815063262' and auth_user_id is null)
        or (id = 'USR-003' and name = '王主任' and email = 'director@suiyuecare.com' and unit = '營運管理處' and title = '主任' and role = '主任' and provider = 'Google Workspace' and password_hash = 'pbkdf2_sha256$8be7da483b04cbf4e06adf98fd4f287c$79e7c06ee0f8032a4b3f8c816f8638a81d0d6f213a7f7c4363d819722e0fe800' and auth_user_id is null)
        or (id = 'USR-004' and name = '陳執行長' and email = 'ceo@suiyuecare.com' and unit = '經營管理' and title = '執行長' and role = '執行長' and provider = 'Google Workspace' and password_hash = 'pbkdf2_sha256$622057556f08af8493df12e74ad7983b$017349cb0c360d23daa17e3baeb64776915f73758a1845d064d5211a356745b7' and auth_user_id is null)
        or (id = 'USR-005' and name = '何人資' and email = 'hr@suiyuecare.com' and unit = '人資' and title = '人資' and role = '人資' and provider = 'Microsoft Entra' and password_hash = 'pbkdf2_sha256$622057556f08af8493df12e74ad7983b$017349cb0c360d23daa17e3baeb64776915f73758a1845d064d5211a356745b7' and auth_user_id is null)
        or (id = 'USR-006' and name = '許會計' and email = 'accounting@suiyuecare.com' and unit = '會計' and title = '會計' and role = '會計' and provider = 'Microsoft Entra' and password_hash = 'pbkdf2_sha256$622057556f08af8493df12e74ad7983b$017349cb0c360d23daa17e3baeb64776915f73758a1845d064d5211a356745b7' and auth_user_id is null)
        or (id = 'USR-007' and name = '周業助' and email = 'sales-assistant@suiyuecare.com' and unit = '業務部' and title = '業務助理' and role = '業務助理' and provider = 'Google Workspace' and password_hash = 'pbkdf2_sha256$622057556f08af8493df12e74ad7983b$017349cb0c360d23daa17e3baeb64776915f73758a1845d064d5211a356745b7' and auth_user_id is null)
        )
        or mfa_status is distinct from case when id = 'USR-007' then '待設定' else '已啟用' end
        or status is distinct from '啟用'
        or last_login_at is not null
        or account_source is distinct from 'edoc'
        or logging_account_id is not null
        or logging_role_key is not null
        or external_account_payload_json is distinct from '{}'
        or last_synced_from_logging_at is not null
        or job_level is distinct from case
          when id in ('USR-001', 'USR-005', 'USR-006') then '課長'
          when id in ('USR-002', 'USR-003') then '部長'
          when id = 'USR-004' then '執行長'
          else '職員'
        end
        or finance_employee_id is not null
        or company_id is not null
        or company_address is not null
        or manager_employee_id is not null
        or manager_name is not null
        or manager_email is not null
        or manager_role_key is not null
        or approval_manager_employee_id is not null
        or approval_manager_name is not null
        or approval_manager_email is not null
        or approval_manager_role_key is not null
        or finance_source_revision is distinct from 0
        or finance_source_event_id is not null
        or finance_source_status is distinct from 'legacy'
        or finance_source_updated_at is not null
        or finance_tenant_id is not null
      )
  ) then
    raise exception using errcode = '55000', message = 'demo_account_signature_mismatch';
  end if;

  if exists (
    select 1 from public.trusted_devices
    where id in ('ACC-DEV-001', 'ACC-DEV-002', 'ACC-DEV-003', 'ACC-DEV-004', 'ACC-DEV-005', 'ACC-DEV-006', 'ACC-DEV-007')
      and not (
        (id = 'ACC-DEV-001' and user_id = 'USR-001' and name = '總務辦公室 Mac' and ip = '203.0.113.18' and fingerprint = 'FP-SYC-EDOC-A1F9' and status = '信任' and last_seen_at = created_at)
        or (id = 'ACC-DEV-002' and user_id = 'USR-002' and name = '行政部主任筆電' and ip = '198.51.100.27' and fingerprint = 'FP-SYC-EDOC-B8C2' and status = '信任' and last_seen_at = created_at)
        or (id = 'ACC-DEV-003' and user_id = 'USR-003' and name = '主任辦公室 Mac' and ip = '203.0.113.18' and fingerprint = 'FP-SYC-EDOC-C339' and status = '信任' and last_seen_at = created_at)
        or (id = 'ACC-DEV-004' and user_id = 'USR-004' and name = '執行長筆電' and ip = '203.0.113.44' and fingerprint = 'FP-SYC-EDOC-D601' and status = '信任' and last_seen_at = created_at)
        or (id = 'ACC-DEV-005' and user_id = 'USR-005' and name = '人資筆電' and ip = '198.51.100.27' and fingerprint = 'FP-SYC-EDOC-HR01' and status = '信任' and last_seen_at = created_at)
        or (id = 'ACC-DEV-006' and user_id = 'USR-006' and name = '會計筆電' and ip = '198.51.100.28' and fingerprint = 'FP-SYC-EDOC-ACC1' and status = '信任' and last_seen_at = created_at)
        or (id = 'ACC-DEV-007' and user_id = 'USR-007' and name = '業務助理筆電' and ip = '203.0.113.19' and fingerprint = 'FP-SYC-EDOC-SA01' and status = '待複核' and last_seen_at = created_at)
      )
  ) then
    raise exception using errcode = '55000', message = 'demo_trusted_device_signature_mismatch';
  end if;

  if exists (
    select 1 from public.notifications
    where target_user_id in ('USR-001', 'USR-002', 'USR-003', 'USR-004', 'USR-005', 'USR-006', 'USR-007')
  ) or exists (
    select 1 from public.system_inbox
    where target_user_id in ('USR-001', 'USR-002', 'USR-003', 'USR-004', 'USR-005', 'USR-006', 'USR-007')
  ) then
    raise exception using errcode = '55000', message = 'demo_account_has_notification_activity';
  end if;

  for v_fk in
    select id from public.trusted_devices
    where id in ('ACC-DEV-001', 'ACC-DEV-002', 'ACC-DEV-003', 'ACC-DEV-004', 'ACC-DEV-005', 'ACC-DEV-006', 'ACC-DEV-007')
    order by id
  loop
    perform pg_temp.edoc_demo_assert_no_fk_references(
      'public.trusted_devices'::pg_catalog.regclass,
      v_fk.id,
      'demo_trusted_device_has_fk_reference'
    );
  end loop;

  delete from public.trusted_devices
  where id in ('ACC-DEV-001', 'ACC-DEV-002', 'ACC-DEV-003', 'ACC-DEV-004', 'ACC-DEV-005', 'ACC-DEV-006', 'ACC-DEV-007');

  if exists (
    select 1 from public.trusted_devices
    where id in ('ACC-DEV-001', 'ACC-DEV-002', 'ACC-DEV-003', 'ACC-DEV-004', 'ACC-DEV-005', 'ACC-DEV-006', 'ACC-DEV-007')
  ) then
    raise exception using errcode = '55000', message = 'demo_trusted_device_delete_failed';
  end if;

  for v_user_id in
    select id from public.users
    where id in ('USR-001', 'USR-002', 'USR-003', 'USR-004', 'USR-005', 'USR-006', 'USR-007')
    order by id
  loop
    for v_fk in
      select namespace_row.nspname as schema_name,
             relation_row.relname as table_name,
             child_attribute.attname as column_name
      from pg_catalog.pg_constraint constraint_row
      join pg_catalog.pg_class relation_row on relation_row.oid = constraint_row.conrelid
      join pg_catalog.pg_namespace namespace_row on namespace_row.oid = relation_row.relnamespace
      join lateral pg_catalog.unnest(constraint_row.conkey) with ordinality child_key(attnum, position) on true
      join lateral pg_catalog.unnest(constraint_row.confkey) with ordinality parent_key(attnum, position) on parent_key.position = child_key.position
      join pg_catalog.pg_attribute child_attribute on child_attribute.attrelid = constraint_row.conrelid and child_attribute.attnum = child_key.attnum
      join pg_catalog.pg_attribute parent_attribute on parent_attribute.attrelid = constraint_row.confrelid and parent_attribute.attnum = parent_key.attnum
      where constraint_row.contype = 'f'
        and constraint_row.confrelid = 'public.users'::pg_catalog.regclass
        and parent_attribute.attname = 'id'
        and pg_catalog.cardinality(constraint_row.conkey) = 1
    loop
      execute pg_catalog.format('select exists (select 1 from %I.%I where %I = $1)', v_fk.schema_name, v_fk.table_name, v_fk.column_name)
        into v_has_reference using v_user_id;
      if v_has_reference then
        raise exception using errcode = '55000', message = pg_catalog.format('demo_account_has_reference:%I.%I', v_fk.schema_name, v_fk.table_name);
      end if;
    end loop;

    perform pg_temp.edoc_demo_assert_no_fk_references(
      'public.users'::pg_catalog.regclass,
      v_user_id,
      'demo_account_has_fk_reference'
    );
  end loop;

  delete from public.users
  where id in ('USR-001', 'USR-002', 'USR-003', 'USR-004', 'USR-005', 'USR-006', 'USR-007');

  if exists (
    select 1 from public.users
    where id in ('USR-001', 'USR-002', 'USR-003', 'USR-004', 'USR-005', 'USR-006', 'USR-007')
  ) then
    raise exception using errcode = '55000', message = 'demo_account_delete_failed';
  end if;
end
$cleanup_demo_accounts$;

-- The old demo-only multi-channel defaults must not imply that external
-- credentials exist. The inbox-only defaults are installed separately.
do $cleanup_demo_notification_rules$
declare
  v_rule_id text;
begin
  perform 1
  from public.notification_rules
  where id in ('NRULE-001', 'NRULE-002', 'NRULE-003', 'NRULE-004', 'NRULE-005')
  for update;

  if exists (
    select 1
    from public.notification_rules
    where id in ('NRULE-001', 'NRULE-002', 'NRULE-003', 'NRULE-004', 'NRULE-005')
      and not (
        (id = 'NRULE-001' and type = '收文' and rule_text = 'jAgent 拉取來文後立即通知總務。' and target_role = '總務' and channel = '系統通知' and status = '啟用')
        or (id = 'NRULE-002' and type = '待清稿' and rule_text = '發文待清稿超過 2 小時通知行政部主任。' and target_role = '行政部主任' and channel = 'Email + 系統通知' and status = '停用')
        or (id = 'NRULE-003' and type = '交換失敗' and rule_text = '交換失敗即時發送 Email、LINE 與站內通知。' and target_role = '總務' and channel = 'Email + Line + 系統通知' and status = '停用')
        or (id = 'NRULE-004' and type = 'Token 到期' and rule_text = 'Token 到期前 60 分鐘通知行政部主任。' and target_role = '行政部主任' and channel = 'Email + 系統通知' and status = '停用')
        or (id = 'NRULE-005' and type = '逾期查核' and rule_text = '每日 09:00 送出逾期查核提醒。' and target_role = '行政部主任' and channel = 'Line 工作群組' and status = '停用')
      )
  ) then
    raise exception using errcode = '55000', message = 'demo_notification_rule_signature_mismatch';
  end if;

  for v_rule_id in
    select id from public.notification_rules
    where id in ('NRULE-001', 'NRULE-002', 'NRULE-003', 'NRULE-004', 'NRULE-005')
    order by id
  loop
    perform pg_temp.edoc_demo_assert_no_fk_references(
      'public.notification_rules'::pg_catalog.regclass,
      v_rule_id,
      'demo_notification_rule_has_fk_reference'
    );
  end loop;

  delete from public.notification_rules
  where id in ('NRULE-001', 'NRULE-002', 'NRULE-003', 'NRULE-004', 'NRULE-005');

  if exists (
    select 1 from public.notification_rules
    where id in ('NRULE-001', 'NRULE-002', 'NRULE-003', 'NRULE-004', 'NRULE-005')
  ) then
    raise exception using errcode = '55000', message = 'demo_notification_rule_delete_failed';
  end if;
end
$cleanup_demo_notification_rules$;

-- All expected fixture rows have now passed their exact immutable signatures,
-- catalog FK guards and asserted deletes. Scan each public text-bearing table
-- once for any denormalized exact reference to a retired fixture ID. A match
-- aborts this transaction, rolling back every cleanup delete.
do $cleanup_demo_non_fk_references$
begin
  perform pg_temp.edoc_demo_assert_no_exact_scalar_references(array[
    'NTF-001', 'NTF-002', 'NTF-003', 'NTF-004', 'NTF-005',
    'CERT-SEAL-001', 'CERT-SEAL-002', 'CERT-TSA-001',
    'DOC-ADMIN-1140523-001', 'ACL-006', 'ACL-007', 'ACLEVT-003',
    'DOC-IN-1140522-00018', 'DOC-OUT-1140522-007', 'DOC-OUT-1140519-006',
    'ATT-001', 'ATT-002', 'ATT-003',
    'ASEC-ATT-001', 'ASEC-ATT-002', 'ASEC-ATT-003',
    'TASK-001', 'TASK-002',
    'ACL-001', 'ACL-002', 'ACL-003', 'ACL-004', 'ACL-005',
    'ACLEVT-001', 'ACLEVT-002',
    'USEAL-SEED-001',
    'REC-001', 'REC-002', 'REC-003', 'REC-004',
    'IP-001',
    'ACC-DEV-001', 'ACC-DEV-002', 'ACC-DEV-003', 'ACC-DEV-004',
    'ACC-DEV-005', 'ACC-DEV-006', 'ACC-DEV-007',
    'USR-001', 'USR-002', 'USR-003', 'USR-004', 'USR-005', 'USR-006', 'USR-007',
    'NRULE-001', 'NRULE-002', 'NRULE-003', 'NRULE-004', 'NRULE-005'
  ]::text[]);
end
$cleanup_demo_non_fk_references$;

commit;
