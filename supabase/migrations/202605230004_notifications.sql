create table if not exists public.notifications (
  id text primary key,
  type text not null,
  title text not null,
  target_role text not null,
  target_email text,
  channel text not null,
  status text not null default '未讀',
  priority text not null default '中',
  source text,
  body text not null,
  delivery_receipt text,
  created_at timestamptz not null default now(),
  sent_at timestamptz
);

create table if not exists public.notification_deliveries (
  id text primary key,
  notification_id text references public.notifications(id) on delete set null,
  channel text not null,
  target text not null,
  status text not null,
  receipt text,
  error text,
  attempt_count integer not null default 1,
  created_at timestamptz not null default now()
);

create table if not exists public.system_inbox (
  id text primary key,
  notification_id text references public.notifications(id) on delete set null,
  target_role text not null,
  target_user_id text,
  title text not null,
  body text not null,
  status text not null default '未讀',
  created_at timestamptz not null default now()
);

create table if not exists public.notification_rules (
  id text primary key,
  type text not null,
  rule_text text not null,
  target_role text not null,
  channel text not null,
  status text not null default '啟用',
  updated_at timestamptz not null default now()
);

create index if not exists idx_notifications_status on public.notifications(status);
create index if not exists idx_notifications_source on public.notifications(source);
create index if not exists idx_notification_deliveries_notification on public.notification_deliveries(notification_id);
create index if not exists idx_system_inbox_notification on public.system_inbox(notification_id);

alter table public.notifications enable row level security;
alter table public.notification_deliveries enable row level security;
alter table public.system_inbox enable row level security;
alter table public.notification_rules enable row level security;

drop policy if exists "service role manages notifications" on public.notifications;
create policy "service role manages notifications"
on public.notifications for all
using (auth.role() = 'service_role')
with check (auth.role() = 'service_role');

drop policy if exists "service role manages notification deliveries" on public.notification_deliveries;
create policy "service role manages notification deliveries"
on public.notification_deliveries for all
using (auth.role() = 'service_role')
with check (auth.role() = 'service_role');

drop policy if exists "service role manages system inbox" on public.system_inbox;
create policy "service role manages system inbox"
on public.system_inbox for all
using (auth.role() = 'service_role')
with check (auth.role() = 'service_role');

drop policy if exists "service role manages notification rules" on public.notification_rules;
create policy "service role manages notification rules"
on public.notification_rules for all
using (auth.role() = 'service_role')
with check (auth.role() = 'service_role');
