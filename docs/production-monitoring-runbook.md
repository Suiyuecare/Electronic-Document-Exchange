# 正式部署與監控 Runbook

## 監控端點

- `GET /api/healthz`：給 uptime monitor 使用，只確認 API 程序可回應；不代表資料庫或外部服務已就緒。
- `GET /api/readyz`：目前核准的內部 eDoc 模組部署門檻，檢查 Supabase、私密儲存、掃毒、Finance SSO 與公司開放範圍。
- `GET /api/production/readiness`：政府正式交換與法定簽章切換門檻；provider 尚未取得規格及人工核准前維持 fail-closed。
- `GET /api/production/deployment`：顯示環境、版本、分支、Vercel region、資料庫與儲存設定。
- `GET /api/production/monitoring`：彙整 readiness、Cron、通知憑證、交換失敗、背景任務、檔案儲存。
- `POST /api/production/monitoring/check`：由維運中心手動執行，會寫入 audit log 並在有告警時呼叫 webhook。
- `GET /api/cron/monitoring`：由 Vercel Cron 執行，必須帶 `Authorization: Bearer $CRON_SECRET`。

## 告警分級

- `critical`：正式環境不可持續營運，例如 Supabase 未啟用、交換任務失敗、Cron 停擺、正式憑證缺漏或到期。
- `warning`：需要排程處理，例如 Sentry/外部 webhook 未設定、通知派送失敗、憑證即將到期。
- `healthy`：沒有告警，或只剩已確認可接受的維運資訊。

## 值班處理

1. 先看維運中心「正式部署與監控」區塊，確認 `監控狀態`、`Readiness`、`Cron`、`通知憑證`。
2. 若是 `ENV-MISSING` 或 `READINESS-BLOCKER`，到 Vercel Environment Variables 補齊後重新部署。
3. 若是 `EXCHANGE-FAILED`，由總務工作台查詢交換任務，先重送，仍失敗再查 jAgent 事件與廠商錯誤碼。
4. 若是 `CRON-STALLED`，確認 Vercel Production Deployment 是否仍啟用 Cron，並以 CRON_SECRET 手動打 `/api/cron/run-due`。
5. 若是 `CREDENTIAL-INVALID`，更新 Email、Line、站內通知簽章密鑰與到期日，再於通知中心執行正式憑證驗證。
6. 處理後重新執行 `POST /api/production/monitoring/check`，確認 audit log 留有處理紀錄。

## 上線門檻

- GitHub Actions `Static checks`、`vercel build --prod`、`Smoke test production` 全數通過。
- `/api/healthz` 與 `/api/readyz` 在 production 回傳 HTTP 200。
- 政府正式交換尚未核准時，`/api/production/readiness` 維持 HTTP 503 為預期；取得 jAgent／API／SDK／封包規格並人工核准正式 provider 後，才要求回傳 `ready: true`。
- `/api/production/monitoring` 沒有 `critical` alert。
- Vercel Dashboard 可看到 `/api/cron/run-due` 與 `/api/cron/monitoring` 的正式排程。
- Supabase 具備正式備份策略，且已完成一次還原演練紀錄。

## Rollback

1. 使用 `vercel ls` 找到上一版穩定 deployment。
2. 執行 `vercel rollback <deployment-url-or-id>`。
3. 重新打 `/api/production/deployment` 確認 revision 與 branch。
4. 重新打 `/api/production/monitoring`，確認沒有新的 critical alert。
5. 若問題來自資料庫 migration，不可只做 Vercel rollback，需依 migration rollback 或資料修復程序處理。
