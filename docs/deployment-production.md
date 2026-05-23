# 歲悅電子公文交換系統正式部署手冊

本系統正式環境建議採用：

- GitHub：`Suiyuecare/Electronic-Document-Exchange`
- Vercel：靜態前端 + Python Serverless API
- Supabase：正式 Postgres 資料庫與後端 REST 資料層
- Vercel Cron：定期觸發 `/api/cron/run-due` 與 `/api/cron/monitoring`

## 1. Supabase

1. 建立獨立 Supabase project，不要混用 Finance、Website 或 HR 資料庫。
2. 依序執行 `supabase/migrations/*.sql`。
3. 執行 `supabase/seed.sql` 建立初始角色、測試帳號、排程與通知規則。
4. 確認 Supabase project 使用受支援 Postgres 版本；若仍是 Postgres 14，需在 2026-07-01 前升級。
5. 正式環境只把 `SUPABASE_SERVICE_ROLE_KEY` 設在 Vercel server-side environment variables，不可放入前端或 `NEXT_PUBLIC_*`。

## 2. Vercel Environment Variables

Production 必填：

```text
EDOC_DEPLOYMENT_ENV=production
EDOC_DB_MODE=supabase
EDOC_PUBLIC_BASE_URL=https://edoc.suiyuecare.com
EDOC_MONITORING_EXPECTED_CRON_MINUTES=1440
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
CRON_SECRET=...
SMTP_HOST=...
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM=...
SMTP_USE_TLS=true
SMTP_PROVIDER=SMTP / Transactional Email
SMTP_CREDENTIAL_EXPIRES_AT=2026-12-31
LINE_WEBHOOK_URL=...
LINE_CHANNEL_SECRET=...
LINE_CHANNEL_ACCESS_TOKEN=...
LINE_CREDENTIAL_EXPIRES_AT=2026-12-31
APP_SECRET=...
INBOX_SIGNING_KEY_EXPIRES_AT=2026-12-31
MONITORING_WEBHOOK_URL=...
SENTRY_DSN=...
```

設定方式：

```bash
vercel link --yes --project Electronic-Document-Exchange
vercel env add EDOC_DEPLOYMENT_ENV production
vercel env add EDOC_DB_MODE production
vercel env add EDOC_PUBLIC_BASE_URL production
vercel env add EDOC_MONITORING_EXPECTED_CRON_MINUTES production
vercel env add SUPABASE_URL production
vercel env add SUPABASE_SERVICE_ROLE_KEY production --sensitive
vercel env add CRON_SECRET production --sensitive
vercel env add SMTP_HOST production
vercel env add SMTP_PORT production
vercel env add SMTP_USERNAME production
vercel env add SMTP_PASSWORD production --sensitive
vercel env add SMTP_FROM production
vercel env add SMTP_USE_TLS production
vercel env add SMTP_PROVIDER production
vercel env add SMTP_CREDENTIAL_EXPIRES_AT production
vercel env add LINE_WEBHOOK_URL production --sensitive
vercel env add LINE_CHANNEL_SECRET production --sensitive
vercel env add LINE_CHANNEL_ACCESS_TOKEN production --sensitive
vercel env add LINE_CREDENTIAL_EXPIRES_AT production
vercel env add APP_SECRET production --sensitive
vercel env add INBOX_SIGNING_KEY_EXPIRES_AT production
vercel env add MONITORING_WEBHOOK_URL production --sensitive
vercel env add SENTRY_DSN production --sensitive
```

## 3. Vercel Cron

`vercel.json` 已建立：

```json
[
  { "path": "/api/cron/run-due", "schedule": "0 1 * * *" },
  { "path": "/api/cron/monitoring", "schedule": "0 2 * * *" }
]
```

這個預設值相容 Hobby plan 的每日排程限制與 2 個 cron job 限制。若使用 Pro / Enterprise 並需要接近正式 SLA，可改成：

```json
[
  { "path": "/api/cron/run-due", "schedule": "*/15 * * * *" },
  { "path": "/api/cron/monitoring", "schedule": "*/15 * * * *" }
]
```

若 Vercel 設定 `CRON_SECRET`，Vercel Cron 會以 `Authorization: Bearer <CRON_SECRET>` 呼叫端點，本系統會驗證此 header。

## 4. 部署

手動部署：

```bash
python3 -m py_compile backend.py api/index.py
node --check app.js
vercel pull --yes --environment=production
vercel build --prod
vercel deploy --prebuilt --prod
```

GitHub Actions 部署：

1. 在 GitHub repository secrets 建立 `VERCEL_TOKEN`、`VERCEL_ORG_ID=team_LGag47eU8tKbsK6ixAmVa5Uq`、`VERCEL_PROJECT_ID=prj_iNAxeAFkzDkrwkDFoeOZvJj78L7K`。
2. 在 Vercel 專案連結 GitHub repo，或本機先執行 `vercel link` 產生 `.vercel/project.json` 後，把 `VERCEL_ORG_ID` / `VERCEL_PROJECT_ID` 依公司政策放入 CI。
3. 建立 `EDOC_PRODUCTION_URL=https://edoc.suiyuecare.com` secret，讓 CI 部署後固定檢查正式網址；未設定時會使用 `https://edoc.suiyuecare.com`。
4. Push 到 `main` 後執行 `.github/workflows/deploy-vercel.yml`。

## 5. 上線後檢查

```bash
curl https://edoc.suiyuecare.com/api/healthz
curl https://edoc.suiyuecare.com/api/production/readiness
curl https://edoc.suiyuecare.com/api/production/deployment
curl https://edoc.suiyuecare.com/api/production/monitoring
curl -H "Authorization: Bearer $CRON_SECRET" https://edoc.suiyuecare.com/api/cron/run-due
curl -H "Authorization: Bearer $CRON_SECRET" https://edoc.suiyuecare.com/api/cron/monitoring
```

判斷標準：

- `/api/healthz` 回傳 `ok: true`。
- `/api/production/readiness` 在 production 回傳 `ready: true`。
- `/api/production/deployment` 顯示 production、revision、branch、deployment URL、Supabase 與 Storage 設定。
- `/api/production/monitoring` 回傳 `status: healthy` 或只有可接受的 warning；critical 必須先處理。
- `/api/cron/run-due` 回傳 `count` 與 `results`，且 Supabase `job_runs` 有新增紀錄。
- `/api/cron/monitoring` 會寫入 audit log；若有 alert 且設定 `MONITORING_WEBHOOK_URL`，會推送外部值班通道。
- 通知中心測試通道後，`notification_deliveries` 有 Email / LINE / 站內通知的成功或失敗紀錄。

## 6. Rollback

```bash
vercel ls
vercel rollback <deployment-url-or-id>
```

資料庫 migration 已套用後不可用 Vercel rollback 反轉，需另寫 Supabase rollback migration 或資料修復腳本。

正式值班、告警分級與處理步驟請使用 `docs/production-monitoring-runbook.md`。
