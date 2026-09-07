# 正式部署與監控 Runbook

## 監控端點

- `GET /api/healthz`：給 uptime monitor 使用，只確認 API 程序可回應；不代表資料庫或外部服務已就緒。
- `GET /api/readyz`：目前核准的內部 eDoc 模組部署門檻，檢查 Supabase、私密儲存、掃毒、Finance SSO 與公司開放範圍。
- `GET /api/production/readiness`：政府正式交換與法定簽章切換門檻；provider 尚未取得規格及人工核准前維持 fail-closed。
- `GET /api/production/deployment`：顯示環境、版本、分支、Vercel region、資料庫與儲存設定。
- `GET /api/production/monitoring`：彙整 readiness、Cron、通知憑證、交換失敗、背景任務、檔案儲存。
- `POST /api/production/monitoring/check`：由維運中心手動執行，會寫入 audit log；有告警時先呼叫 webhook，未設定或失敗則沿用 Email 與站內通知提醒 Finance 名冊的行政部門主任及總務。
- `GET /api/cron/monitoring`：由 Vercel Cron 執行，必須帶 `Authorization: Bearer $CRON_SECRET`。

### 15 分鐘補充監控

目前 Vercel 帳號為 Hobby，保留原本兩個每日排程，無須升級付費方案。
補充監控使用既有 Supabase 的 `pg_cron`、同步 `http`，job 名稱固定為
`edoc-production-monitoring-15min`。Vault 只使用 `edoc_monitor_base_url` 與
`edoc_monitor_cron_secret` 兩個 eDoc 專用名稱，SQL migration 不含實際 URL 或秘密。

此來源使用獨立 `EDOC_MONITORING_CRON_SECRET`，僅授權 `GET /api/cron/monitoring`；
不得用來執行背景工作、登入、讀取公文或呼叫其他管理 API。原 `CRON_SECRET` 繼續供 Vercel 使用。
新 secret 必須由私密程序產生並以 stdin／參數綁定設定到兩端；不得放入命令參數、repo、稽核文字。

migration 只建立停用中的 job。部署支援此認證的新版本後，先驗證通知收件人、
測試通知與 endpoint HTTP 回應，再只啟用此 eDoc job：

```sql
select cron.alter_job(jobid, active := true)
from cron.job where jobname = 'edoc-production-monitoring-15min';
```

以 `cron.job_run_details` 核對執行時間；私有 `edoc_private.run_monitoring_http()`
只有 HTTP 2xx 才成功，非 2xx、連線失敗或逾時會回遮罩錯誤碼並使該次 Cron 失敗。
同步函式只傳回 status，不保存 response body／headers；bearer 只在 Vault 與執行記憶體中，
不寫入 `net.http_request_queue`。連線逾時 10 秒、總逾時 120 秒；鎖定 http 1.6 不跟隨重新導向。
managed `pg_net` 表／schema 的 PUBLIC grants 不能由 postgres 代管者撤銷，
因此改用不經 queue 的傳輸，不能把無效的 REVOKE 當作修復證據。
`cron` schema 與私有函式不得授權給 anon／authenticated；不用改動其他模組權限。
停用時同一查詢改為 `active := false`；傳輸修正 migration 保留既有 active 值，避免重播意外啟停。
不要修改其他模組的 jobs、Vault secrets 或資料權限。

除 `healthz`、`readyz` 與經遮罩的 `production/readiness` 外，上述部署／監控明細
必須帶具有「系統管理」權限的登入 session；一般員工與未登入請求不得取得環境、
Storage、AV、憑證、背景任務或切換產物資訊。維運頁必須讀取
`/api/exchange/gateway-status` 的真實狀態；正式交換停用時不得產生假的 jAgent Token、
延遲或成功紀錄。

## 告警分級

- `critical`：正式環境不可持續營運，例如 Supabase 未啟用或 Cron 停擺；交換任務與正式憑證只在政府正式交換另行核准啟用後納入本級告警。
- `warning`：需要排程處理，例如錯誤追蹤未設定、尚未成功重送的通知、憑證即將到期。未設定 webhook 時可使用既有 Email，不另強制開通新通道；內部範圍未使用 LINE 時不以 LINE 憑證報警。
- `healthy`：沒有告警，或只剩已確認可接受的維運資訊。

## 值班處理

1. 先看維運中心「正式部署與監控」區塊，確認 `監控狀態`、`Readiness`、`Cron`、`通知憑證`。
2. 若是 `ENV-MISSING` 或 `READINESS-BLOCKER`，到 Vercel Environment Variables 補齊後重新部署。
3. 若是 `EXCHANGE-FAILED`，由總務工作台查詢交換任務，先重送，仍失敗再查 jAgent 事件與廠商錯誤碼。
4. 若是 `CRON-STALLED`，確認 Vercel Production Deployment 是否仍啟用 Cron，並以 CRON_SECRET 手動打 `/api/cron/run-due`。
5. 若是 `CREDENTIAL-INVALID`，更新 Email、Line、站內通知簽章密鑰與到期日，再於通知中心執行正式憑證驗證。
6. 處理後重新執行 `POST /api/production/monitoring/check`，確認 audit log 留有處理紀錄。

`GET /api/production/monitoring` 的 `checks.alertDelivery` 為唯讀收件人預覽，
包含 provider、使用者 ID、公司 ID、Finance 角色及 `fallbackReady`，不寄送測試信。
相同錯誤碼與等級對同一人，critical 每小時最多一筆，warning 每日最多一筆。
`READINESS-WARNING`（例如未設定 Sentry）只顯示建議，不向外派送。
通知不包含環境值、公文本文或人員個資。
Email receipt 代表郵件服務接受寄送，不等於收件者收到或閱讀。通知狀態以 runtime 為準，
不得把資料庫初始化的 `disabled_pending_credentials` 字串當成最新設定。

具監控專用 token 的維護者可呼叫同一 `GET /api/cron/monitoring?dryRun=1`，
唯讀查看 runtime 狀態與收件人，且不寫入 audit、settings、notification。
`?deliveryTest=1` 僅產生固定「上線驗收測試」文字，投遞同一組 Finance 行政部門主任／總務；
不接受外部指定收件人或內容。同日每人固定通知 ID，重試會回既有 provider receipt，避免重寄。
receipt 回應僅代表服務接受，仍需收件者另行確認。空值、重複值、未知參數或兩模式同時傳入均回 400。

`dryRun` 額外提供寄件設定格式的布林診斷，不顯示地址或 key。若最新 Email 嘗試失敗，
runtime 顯示 `delivery_failed` 及遮罩代碼；舊成功紀錄仍保留，不當成目前送件正常。
經維護者確認後，`?deliveryTestRetry=1` 只允許今日原固定測試、唯一一次 Email 嘗試為
`Resend HTTP 400` 且無成功 receipt 的通知重試一次。原 ID、收件人、內容及 idempotency key 不變，
不新增通知也不重發站內通知；固定 delivery PK 先佔位再寄送，並發或中斷後不得第三次自動寄送。
`重試中` 未決紀錄仍計入待處理失敗，不會被監控誤認成修復。

### 重試紀錄與寄送後中斷

`notification_deliveries` 是追加式紀錄；後端保留 SELECT／INSERT，不能 UPDATE。
限定重試使用固定 `NDEL-MONRETRY-` claim，在寄信前先提交；結果另以相同摘要的
`NDEL-MONRESULT-` 固定 ID 追加，`attempt_count=0` 表示這是同一次寄送的結果，
不是第三次嘗試。同一時間戳記的結果優先於 claim，但原 claim 與舊失敗均保留。
結果已落庫、通知彙總尚未更新時，也不得重新寄信。

若寄送後程序中斷或收據回寫失敗，先停止重送，從已授權的 provider 管理頁核對
原收件人、固定主旨／內容、模組標記、時間及實際 receipt。只有證據完全吻合時，
維護者才能以短交易追加固定結果、更新通知彙總並留下只含 ID／hash 的對帳稽核。
不能修改或刪除 claim、放寬表格 UPDATE 權限、捏造 receipt，亦不能新建測試通知繞過上限。
Provider 的 Delivered 表示郵件服務回報已送達，不代表收件者已閱讀或完成人工驗收。

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

2026-09-07 本次改善前正式部署回復候選：`dpl_BKQ15UvCGaFpHoxWCvpyFj43KpkT`。
具體值班與內部寄發流程見 [內部上線交接](internal-launch-handoff.md)。
