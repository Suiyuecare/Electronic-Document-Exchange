# 歲悅電子公文系統正式部署手冊

本文件只涵蓋已核准的內部公文、用印、簽核與收發管理。正式電子公文交換 provider 在取得機關 jAgent/API/SDK/封包規格、完成測試與人工核准前，必須維持 Mock／停用；不得以本手冊連線正式交換環境。

## 1. 資料庫與檔案儲存分工

- 主 eDoc Supabase：Postgres、Auth 對應資料與應用資料。
- 專用 Storage Supabase：只存放 `edoc-private`、`edoc-seal-vault` 私有 bucket 與物件。
- Finance／會計系統：人員、公司與組織的唯一主資料來源；eDoc 不手動建立正式人員。
- 前端不得取得任一 project 的 `service_role`，也不得列舉 bucket 或接受任意 storage path。

正式發布前先在隔離環境完整重建一次；不可直接把未驗證 migration 套到正式資料庫。

新環境執行 `supabase db reset` 時，CLI 會先載入
`supabase/roles.sql`。該檔只補齊歷史 migration 在外鍵指派前漏建的 9 個
legacy permission reference rows，以及早期 migration 所需的 pgcrypto `digest()`
相容 overload；相容函式已撤銷前台角色權限，只允許資料庫擁有者與
`service_role` 執行，且不含帳號、密碼、公司、文件或正式資料，
也不改寫任何已套用的 migration。既有正式資料庫不得為此重跑舊 migration，
仍只依核准的 forward migration 與變更單發布。

### 主 eDoc Supabase

1. 先執行 `supabase unlink` 清除舊連結，再以 `supabase link --project-ref ussnmxdpxeoshlrdchov` 連結主 eDoc project；用 `supabase projects list`／project URL 再確認一次，禁止沿用專用 Storage project 的 link。
2. 比對 `supabase/verification/migration_manifest.json` 與 `supabase/migrations/*.sql`，再執行 `supabase migration list --linked` 確認遠端與 repository 的 migration 歷程一致。
3. 若遠端出現 repository 不存在的 migration，或同一版本的套用狀態不一致，立即停止；不得自行執行 `supabase migration repair`、不得略過版本，也不得用 `db pull` 產生未經審查的正式基線。先由資料庫負責人核對遠端 SQL、雜湊與變更單，再以核准的 baseline／forward migration 補齊 repository。
4. 歷程一致後才執行 migration dry-run，再於隔離環境完整 reset／重建並執行測試。
5. 取得資料庫備份、指定回復點與人工變更核准後，才依序套用正式 migrations。
6. 執行 `supabase/verification/production_cutover_checks.sql`；所有 required table/RPC、RLS、grant 與 demo-data 檢查必須通過。

`supabase/recovery/complete_edoc_runtime_recovery_20260827.sql` 是 2026-08-27 的唯讀災難復原快照，不在 `supabase/migrations`、不在 migration manifest，也不得用 `supabase db push` 套到既有正式資料庫。可線性部署的主資料庫變更只有 manifest 內的純 forward migrations；本次相關檔案依序為：

1. `20260827050436_complete_edoc_runtime_schema_parity.sql`：以 idempotent DDL 補齊 fresh bootstrap 與既有環境的 runtime tables、欄位、constraints、RLS、trigger 與 service-only RPC；不啟用正式交換 provider。
2. `20260827050447_remove_exact_demo_bootstrap_records_forward.sql`：只依已列明的精確 demo identifier 清理舊 bootstrap 資料，不使用模糊名稱、email 或 regex 刪除。
3. `20260827050450_atomic_official_submission_editor_finalize_forward.sql`：只建立／取代兩支 atomic RPC、收回 browser 執行權、只授權 `service_role`，並通知 PostgREST 重載 schema。
4. `20260827050452_add_confirmed_edoc_fk_indexes_forward.sql`：只以 `create index if not exists` 補齊 Supabase Performance Advisor 已確認的 eDoc 外鍵索引，不處理 shared CMS，也不刪除 unused index。

這些檔案仍須先在與正式 schema 相同的隔離環境完成 `supabase db reset`、RPC smoke 與安全檢查，並逐檔取得人工核准；拆成 forward migration 不代表可以略過備份、回復點或變更審查。

`supabase/seed.sql` 是刻意無資料的 production-safe seed，不會建立人員、公司、文件、憑證、裝置或通知。正式環境不需要執行 seed；若 CI 的 fresh bootstrap 固定會執行，也只會得到一個無副作用的檢查結果。

### 專用 Storage Supabase

專用 Storage project 不得套用主資料庫的全部 migrations，只執行 `supabase/storage-migrations` 的以下三個純 Storage migration，且順序不可顛倒：

1. `supabase/storage-migrations/20260824034730_dedicated_edoc_private_storage_buckets.sql`
2. `supabase/storage-migrations/20260827042214_harden_edoc_storage_buckets.sql`
3. `supabase/storage-migrations/20260827050000_enforce_empty_storage_client_policy_allowlist.sql`

這三個檔案只允許套用到 dedicated Storage project，絕不可套用到主網站／CMS Supabase project；其中 allowlist migration 會移除 dedicated project 的所有 browser client object policies。檔案要作為獨立、經人工核准的 Storage 變更執行；不得在仍連結專用 Storage project 時執行主資料庫的 `supabase db push`。完成後再次 `supabase unlink`，避免下一次誤把主資料庫 migration 推到 Storage project。

主資料庫只執行 `supabase/verification/production_cutover_checks.sql`；專用 Storage project 另執行 `supabase/verification/dedicated_storage_cutover_checks.sql`。不可把兩份檢查互換，因為主資料庫同時承載 CMS storage policies，而專用 Storage project 的 browser policy allowlist 必須為空。

套用後必須確認：

- `edoc-private`、`edoc-seal-vault` 均為 private。
- `edoc-private` 接受 PDF、核准的辦公文件／圖片及 archive 所需的 `application/zip`。
- 兩個 bucket 均不接受 `image/svg+xml`。
- `storage.objects` 的 `PUBLIC`／`anon`／`authenticated` policy allowlist 為空；瀏覽器僅使用後端簽發的短效能力。若其他模組未來需要直接 Storage policy，必須先拆分 bucket／project 或另行安全審查，不可直接加回共用 policy。

## 2. Vercel 正式環境變數

必要的主資料庫與專用 Storage 設定：

```text
EDOC_DEPLOYMENT_ENV=production
EDOC_DB_MODE=supabase
EDOC_PUBLIC_BASE_URL=https://edoc.suiyuecare.com
SUPABASE_URL=https://<main-edoc-project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<server-only>

EDOC_STORAGE_PROVIDER=supabase
EDOC_STORAGE_SUPABASE_MODE=dedicated-project
EDOC_STORAGE_SUPABASE_URL=https://<dedicated-storage-project>.supabase.co
EDOC_STORAGE_SERVICE_ROLE_KEY=<server-only>
EDOC_STORAGE_PUBLISHABLE_KEY=<publishable-key>
EDOC_STORAGE_BUCKET=edoc-private
EDOC_STORAGE_ACCESS_MODE=server-signed-url
EDOC_SIGNED_URL_TTL_SECONDS=300

EDOC_FILE_ENCRYPTION_ENABLED=true
EDOC_FILE_ENCRYPTION_KEY=<server-only>
EDOC_SCAN_ENGINE=ClamAV-compatible
EDOC_AV_PROVIDER=<approved-provider>
EDOC_AV_ENDPOINT=<approved-private-endpoint>
EDOC_AV_API_KEY=<server-only>
EDOC_MAX_FILE_SIZE_MB=100
CRON_SECRET=<server-only>
APP_SECRET=<server-only>
```

`EDOC_STORAGE_PUBLISHABLE_KEY` 只用於專用 Storage 的可公開 client identification；上傳授權仍須由後端核發。`EDOC_STORAGE_SERVICE_ROLE_KEY` 與主資料庫的 `SUPABASE_SERVICE_ROLE_KEY` 必須分開保存、分開輪替，且只存在 server-side environment。

正式通知的最低可上線基準是站內通知。Email 與 LINE 為選配，未提供並驗證下列環境變數時必須保持 disabled/pending，不可放假值或把「待驗證」視為成功：

```text
# Optional Email channel
RESEND_API_KEY=<server-only>
MAIL_FROM=<verified-sender>

# Optional LINE channel
LINE_WEBHOOK_URL=<server-only>
# 或 LINE_CHANNEL_ACCESS_TOKEN + LINE_TARGET_ID
LINE_CHANNEL_ACCESS_TOKEN=<server-only>
LINE_TARGET_ID=<server-only>
```

簽章、HSM、TSA、OCSP、CRL 與正式交換 provider 的環境變數，只能在該功能另行完成規格驗收與人工核准後加入。本次內部上線不可填入模擬值冒充可用。

使用 Vercel CLI 時，每個命令會再提示輸入實際值；命令尾端的 `production` 是環境名稱，不是變數值：

```bash
vercel link --yes --project Electronic-Document-Exchange
vercel env add EDOC_DEPLOYMENT_ENV production
vercel env add EDOC_DB_MODE production
vercel env add EDOC_PUBLIC_BASE_URL production
vercel env add SUPABASE_URL production
vercel env add SUPABASE_SERVICE_ROLE_KEY production --sensitive
vercel env add EDOC_STORAGE_SUPABASE_URL production
vercel env add EDOC_STORAGE_SERVICE_ROLE_KEY production --sensitive
vercel env add EDOC_STORAGE_PUBLISHABLE_KEY production
vercel env add EDOC_STORAGE_BUCKET production
vercel env add EDOC_FILE_ENCRYPTION_KEY production --sensitive
vercel env add EDOC_AV_API_KEY production --sensitive
vercel env add CRON_SECRET production --sensitive
vercel env add APP_SECRET production --sensitive
```

## 3. 發布前資料與安全閘門

在正式部署核准單留下以下證據：

1. migration manifest 與 repository migration 清單一致。
2. `supabase migration list --linked` 顯示遠端與 repository 歷程一致，沒有使用未核准的 `migration repair` 覆寫歷程。
3. 隔離環境 fresh bootstrap 成功，且 `supabase/seed.sql` 未建立 demo data。
4. `production_cutover_checks.sql` 的 demo identifier 計數為 0。
5. 13 個補齊的 runtime tables、15 個既有 RPC 與 2 個 atomic RPC 全部存在。
6. atomic RPC 僅 `service_role` 可執行；`PUBLIC`、`anon`、`authenticated` 無權限。
7. runtime tables 啟用 RLS，敏感表的 browser Data API grant 為 0。
8. 40 個已確認的 eDoc 外鍵索引全部存在，且未新增 shared CMS index 或刪除 unused index。
9. Storage bucket private、包含 ZIP、排除 SVG，舊 direct-object policies 不存在。
10. 站內通知規則 ready；Email／LINE 若未設定應明確顯示 pending，而非阻擋內部上線或假裝成功。
11. stale editor upload 檢查無超過允許時限的 pending/uploaded 資產。
12. Finance 人員、公司、部門投影同步檢查通過，沒有手動維護的 demo 帳號。

若任何一項不通過，停止發布；資料庫 migration 不得用 Vercel rollback 反轉，需另寫經審查的 forward-fix migration。

## 4. Vercel Cron

`vercel.json` 目前以兩個每日工作相容 Hobby plan：

```json
[
  { "path": "/api/cron/run-due", "schedule": "0 1 * * *" },
  { "path": "/api/cron/monitoring", "schedule": "0 2 * * *" }
]
```

若未來使用 Pro／Enterprise 且 SLA 需要 15 分鐘頻率，再經容量測試與變更核准調整。設定 `CRON_SECRET` 後，Vercel Cron 會以 `Authorization: Bearer <CRON_SECRET>` 呼叫，系統必須驗證該 header。

## 5. 部署與上線後檢查

```bash
python3 -m py_compile backend.py api/index.py
node --check app.js
vercel pull --yes --environment=production
vercel build --prod
vercel deploy --prebuilt --prod
```

部署後：

```bash
curl https://edoc.suiyuecare.com/api/healthz
curl https://edoc.suiyuecare.com/api/readyz
curl https://edoc.suiyuecare.com/api/production/readiness
curl https://edoc.suiyuecare.com/api/production/deployment
curl https://edoc.suiyuecare.com/api/production/monitoring
curl https://edoc.suiyuecare.com/api/files/storage-health
curl -H "Authorization: Bearer $CRON_SECRET" https://edoc.suiyuecare.com/api/cron/run-due
curl -H "Authorization: Bearer $CRON_SECRET" https://edoc.suiyuecare.com/api/cron/monitoring
```

判斷標準：

- `/api/healthz` 回傳 `ok: true`；`/api/readyz` 回傳 HTTP 200 與 `ready: true`。
- `/api/files/storage-health` 指向專用 Storage project，且 provider、bucket、AV、加密與短效 URL ready。
- 站內通知實測成功並產生 inbox id。Email／LINE 只有在憑證已正式設定時才測試；未設定時必須回報 disabled/pending，不得產生寄送成功 receipt。
- 正式電子公文交換尚未核准時，`/api/production/readiness` 對正式交換能力回傳未就緒是預期結果，不可藉此啟用模擬憑證或猜測 provider 格式。
- cron 執行有 audit/job-run 紀錄，且 log 不包含文件本文、個資、憑證、token 或完整檔案路徑。

## 6. 回復與事故處理

```bash
vercel ls
vercel rollback <deployment-url-or-id>
```

Vercel rollback 只能回復應用部署。已套用的資料庫 migration 要用經審查的 forward-fix migration；正式發布前必須先有資料庫備份、回復點與負責人。正式值班、告警分級與處理步驟見 `docs/production-monitoring-runbook.md`。
