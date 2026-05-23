create table if not exists public.notification_channel_credentials (
  id text primary key,
  channel text not null,
  provider text not null,
  credential_type text not null,
  env_key_name text not null,
  masked_identifier text not null,
  fingerprint_sha256 text not null,
  expires_at timestamptz,
  status text not null default '待驗證',
  last_validated_at timestamptz,
  validation_report_json jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_notification_credentials_channel on public.notification_channel_credentials(channel);
create index if not exists idx_notification_credentials_status on public.notification_channel_credentials(status);

alter table public.notification_channel_credentials enable row level security;

grant select, insert, update on public.notification_channel_credentials to authenticated;

drop policy if exists "authorized users read notification credentials" on public.notification_channel_credentials;
create policy "authorized users read notification credentials"
on public.notification_channel_credentials for select
to authenticated
using (edoc_private.current_user_role() in ('主任', '執行長', '行政部主任', '總務'));

drop policy if exists "authorized users manage notification credentials" on public.notification_channel_credentials;
create policy "authorized users manage notification credentials"
on public.notification_channel_credentials for all
to authenticated
using (edoc_private.current_user_role() in ('主任', '執行長', '行政部主任'))
with check (edoc_private.current_user_role() in ('主任', '執行長', '行政部主任'));

insert into public.notification_channel_credentials (
  id, channel, provider, credential_type, env_key_name, masked_identifier, fingerprint_sha256,
  expires_at, status
) values
  ('NCRED-EMAIL-SMTP', 'Email', 'SMTP / Transactional Email', 'SMTP 帳號/應用程式密碼', 'SMTP_HOST,SMTP_USERNAME,SMTP_PASSWORD,SMTP_FROM', '由 Vercel/Supabase 環境變數注入', 'ENV-SMTP-PENDING', null, '待驗證'),
  ('NCRED-LINE-WEBHOOK', 'Line 工作群組', 'LINE Messaging API / Webhook', 'Webhook Secret / Channel Access Token', 'LINE_WEBHOOK_URL,LINE_CHANNEL_SECRET,LINE_CHANNEL_ACCESS_TOKEN', '由 Vercel/Supabase 環境變數注入', 'ENV-LINE-PENDING', null, '待驗證'),
  ('NCRED-INBOX-SIGNING', '系統站內通知', 'Suiyuecare eDoc', '站內通知簽章金鑰', 'APP_SECRET,CRON_SECRET', '由 Vercel/Supabase 環境變數注入', 'ENV-INBOX-PENDING', null, '待驗證')
on conflict (id) do nothing;
