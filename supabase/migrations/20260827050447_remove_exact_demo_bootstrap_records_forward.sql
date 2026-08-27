-- Remove only the identifiers used by the retired demo seed. This migration
-- deliberately avoids pattern matching so genuine production records cannot be
-- removed merely because their names resemble test data.

delete from public.notification_deliveries
where notification_id in ('NTF-001', 'NTF-002', 'NTF-003', 'NTF-004', 'NTF-005');

delete from public.system_inbox
where notification_id in ('NTF-001', 'NTF-002', 'NTF-003', 'NTF-004', 'NTF-005');

delete from public.notifications
where id in ('NTF-001', 'NTF-002', 'NTF-003', 'NTF-004', 'NTF-005');

delete from public.seal_applications
where id = 'USEAL-SEED-001';

-- AUD-SEED-001 is intentionally not deleted if an older environment already
-- recorded it: audit_logs is append-only, and cleanup must not weaken or bypass
-- that evidence-preservation control. Fresh environments no longer create it.

delete from public.signing_certificates
where id in ('CERT-SEAL-001', 'CERT-SEAL-002', 'CERT-TSA-001');

delete from public.documents
where id in (
  'DOC-IN-1140522-00018',
  'DOC-OUT-1140522-007',
  'DOC-OUT-1140519-006'
);

delete from public.recipients
where id in ('REC-001', 'REC-002', 'REC-003', 'REC-004');

delete from public.trusted_devices
where id in (
  'ACC-DEV-001', 'ACC-DEV-002', 'ACC-DEV-003', 'ACC-DEV-004',
  'ACC-DEV-005', 'ACC-DEV-006', 'ACC-DEV-007'
);

delete from public.ip_allowlist
where id = 'IP-001';

delete from public.notifications
where target_user_id in (
  'USR-001', 'USR-002', 'USR-003', 'USR-004', 'USR-005', 'USR-006', 'USR-007'
);

delete from public.system_inbox
where target_user_id in (
  'USR-001', 'USR-002', 'USR-003', 'USR-004', 'USR-005', 'USR-006', 'USR-007'
);

delete from public.users
where id in (
  'USR-001', 'USR-002', 'USR-003', 'USR-004', 'USR-005', 'USR-006', 'USR-007'
)
and email in (
  'edoc@suiyuecare.com', 'records@suiyuecare.com', 'director@suiyuecare.com',
  'ceo@suiyuecare.com', 'hr@suiyuecare.com', 'accounting@suiyuecare.com',
  'sales-assistant@suiyuecare.com'
)
and not exists (
  select 1 from public.official_document_approval_logs log
  where log.principal_actor_id = public.users.id
)
and not exists (
  select 1 from public.official_document_approval_steps step
  where step.decision_actor_user_id = public.users.id
)
and not exists (
  select 1 from public.official_document_archive_exports export
  where export.requested_by = public.users.id
)
and not exists (
  select 1 from public.official_workflow_delegations delegation
  where delegation.principal_user_id = public.users.id
     or delegation.delegate_user_id = public.users.id
     or delegation.created_by = public.users.id
     or delegation.revoked_by = public.users.id
);

-- The old demo-only multi-channel defaults must not imply that external
-- credentials exist. The inbox-only defaults are installed separately.
delete from public.notification_rules
where id in ('NRULE-001', 'NRULE-002', 'NRULE-003', 'NRULE-004', 'NRULE-005');
