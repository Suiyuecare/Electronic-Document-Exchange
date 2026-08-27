-- Safe notification bootstrap: the internal inbox is the launch baseline.
-- No Email or LINE credential, token, receipt, or successful validation is
-- fabricated by this migration.

insert into public.notification_rules (id, type, rule_text, target_role, channel, status, updated_at)
values
  ('NRULE-INBOX-APPROVAL', '待簽核', '簽核工作送達時建立個人站內通知。', '簽核人', '系統通知', '啟用', now()),
  ('NRULE-INBOX-REJECTED', '退回補正', '案件退回時建立申請人站內通知。', '申請人', '系統通知', '啟用', now()),
  ('NRULE-INBOX-STAMPED', '用印完成', '用印檔案完成時建立申請人站內通知。', '申請人', '系統通知', '啟用', now()),
  ('NRULE-INBOX-OVERDUE', '逾期查核', '案件逾期時建立責任人站內通知。', '責任人', '系統通知', '啟用', now())
on conflict (id) do update set
  type = excluded.type,
  rule_text = excluded.rule_text,
  target_role = excluded.target_role,
  channel = '系統通知',
  status = '啟用',
  updated_at = now();

-- Legacy example rules must not activate external delivery before credentials
-- are independently configured and verified.
update public.notification_rules
set status = '停用', updated_at = now()
where id in ('NRULE-002', 'NRULE-003', 'NRULE-004', 'NRULE-005')
  and (channel ilike '%email%' or channel ilike '%line%');

insert into public.notification_channel_credentials (
  id, channel, provider, credential_type, env_key_name, masked_identifier,
  fingerprint_sha256, expires_at, status, validation_report_json, created_at, updated_at
)
values
  ('NCRED-EMAIL-SMTP', 'Email', 'Resend / Transactional Email', 'Server environment',
   'RESEND_API_KEY,MAIL_FROM', '尚未設定；僅由 Vercel server environment 注入',
   'PENDING:NO_CREDENTIAL_CONFIGURED', null, '待驗證', '{"configured":false,"verified":false}'::jsonb, now(), now()),
  ('NCRED-LINE-WEBHOOK', 'Line 工作群組', 'LINE Messaging API / Webhook', 'Server environment',
   'LINE_WEBHOOK_URL 或 LINE_CHANNEL_ACCESS_TOKEN,LINE_TARGET_ID',
   '尚未設定；僅由 Vercel server environment 注入', 'PENDING:NO_CREDENTIAL_CONFIGURED', null,
   '待驗證', '{"configured":false,"verified":false}'::jsonb, now(), now()),
  ('NCRED-INBOX-SIGNING', '系統站內通知', 'Suiyuecare eDoc', 'Server signing secret',
   'APP_SECRET 或 CRON_SECRET', '僅由 Vercel server environment 注入',
   'PENDING:RUNTIME_CONFIGURATION_CHECK', null, '待驗證',
   '{"configured":null,"verified":false,"validation":"runtime"}'::jsonb, now(), now())
on conflict (id) do update set
  provider = excluded.provider,
  credential_type = excluded.credential_type,
  env_key_name = excluded.env_key_name,
  masked_identifier = excluded.masked_identifier,
  fingerprint_sha256 = case
    when public.notification_channel_credentials.status in ('有效', '即將到期')
      then public.notification_channel_credentials.fingerprint_sha256
    else excluded.fingerprint_sha256
  end,
  status = case
    when public.notification_channel_credentials.status in ('有效', '即將到期')
      then public.notification_channel_credentials.status
    else '待驗證'
  end,
  validation_report_json = case
    when public.notification_channel_credentials.status in ('有效', '即將到期')
      then public.notification_channel_credentials.validation_report_json
    else excluded.validation_report_json
  end,
  updated_at = now();

insert into public.settings (key, value_json, version, updated_at)
values (
  'notification_readiness',
  '{"system_inbox":{"enabled":true,"credentialValidation":"runtime"},"external":{"email":"disabled_pending_credentials","line":"disabled_pending_credentials"}}',
  1,
  to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
)
on conflict (key) do update set
  value_json = excluded.value_json,
  version = public.settings.version + 1,
  updated_at = excluded.updated_at;

-- Notification data is served through the authenticated eDoc backend, not by
-- direct browser Data API access.
alter table public.notifications enable row level security;
alter table public.notification_deliveries enable row level security;
alter table public.system_inbox enable row level security;
alter table public.notification_rules enable row level security;
alter table public.notification_channel_credentials enable row level security;

revoke all on table public.notifications from public, anon, authenticated;
revoke all on table public.notification_deliveries from public, anon, authenticated;
revoke all on table public.system_inbox from public, anon, authenticated;
revoke all on table public.notification_rules from public, anon, authenticated;
revoke all on table public.notification_channel_credentials from public, anon, authenticated;
grant select, insert, update, delete on table public.notifications to service_role;
grant select, insert, update, delete on table public.notification_deliveries to service_role;
grant select, insert, update, delete on table public.system_inbox to service_role;
grant select, insert, update, delete on table public.notification_rules to service_role;
grant select, insert, update, delete on table public.notification_channel_credentials to service_role;

drop policy if exists "service role manages notifications" on public.notifications;
create policy "service role manages notifications" on public.notifications
  for all to service_role using (true) with check (true);
drop policy if exists "service role manages notification deliveries" on public.notification_deliveries;
create policy "service role manages notification deliveries" on public.notification_deliveries
  for all to service_role using (true) with check (true);
drop policy if exists "service role manages system inbox" on public.system_inbox;
create policy "service role manages system inbox" on public.system_inbox
  for all to service_role using (true) with check (true);
drop policy if exists "service role manages notification rules" on public.notification_rules;
create policy "service role manages notification rules" on public.notification_rules
  for all to service_role using (true) with check (true);
drop policy if exists "authorized users read notification credentials" on public.notification_channel_credentials;
drop policy if exists "authorized users manage notification credentials" on public.notification_channel_credentials;
create policy "service role manages notification credentials" on public.notification_channel_credentials
  for all to service_role using (true) with check (true);
