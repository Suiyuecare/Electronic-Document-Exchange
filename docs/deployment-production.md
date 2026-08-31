# 歲悅電子公文系統正式部署手冊

本文件只涵蓋已核准的內部公文、用印、簽核與收發管理。正式電子公文交換 provider 在取得機關 jAgent/API/SDK/封包規格、完成測試與人工核准前，必須維持 Mock／停用；不得以本手冊連線正式交換環境。

## 1. 資料庫與檔案儲存分工

- 主 eDoc Supabase 支援兩種核准拓撲：獨立 project，或共享 project 內的 `edoc`／`edoc_private` 隔離 schema。共享模式不得把 eDoc 物件放入既有 HR `public` schema。
- Storage 可使用專用 project；共享模式則以 `edoc_backend` custom role 的 RLS 精確限制在 `edoc-private`、`edoc-seal-vault`，不得存取 `hr-documents`。
- Finance／會計系統：人員、公司與組織的唯一主資料來源；eDoc 不手動建立正式人員。
- 前端不得取得任一 project 的 backend secret／`service_role`，也不得列舉 bucket 或接受任意 storage path。

正式發布前先在隔離環境完整重建一次；不可直接把未驗證 migration 套到正式資料庫。

### 已核准的共享 project 隔離模式

共享模式只適用於資料擁有者已明確同意保留既有 HR 資料、另建 eDoc namespace 的 project：

1. 先以唯讀方式確認 `public.users`、`public.employees`、`public.companies`、`public.departments` 存在，且 `edoc`、`edoc_private`、`edoc_backend` 尚未存在，兩個 eDoc bucket 沒有既有物件。
2. 執行 `python3 tools/shared_supabase_bootstrap.py apply --project-ref <project-ref>`。預設一定以 `ROLLBACK` 結束，並在前後比對 HR 人員、公司、部門與 `hr-documents` 物件筆數。
3. 回滾預演與人工審核通過後，才執行相同命令並加上 `--commit --acknowledge-shared-project`。工具會在單一 transaction 內轉換 immutable migration chain、建立 93 個 eDoc relation、52 筆來源雜湊 ledger、非登入且不 bypass RLS 的 `edoc_backend`，並保留 PostgREST 原有 exposed schemas。
4. 執行 `supabase/shared-project-migrations/20260831093000_harden_shared_edoc_bucket_limits.sql`，將文件 bucket 鎖在 100 MiB、Seal Vault 鎖在 3 MiB，移除 SVG 與舊的 authenticated 直連 policy。
5. 執行 `supabase/verification/shared_project_cutover_checks.sql`；`__all_shared_project_checks__` 必須為 true，任何一項 false 都不得建立 runtime key 或部署。
6. 透過 Supabase Management API 建立 `type=secret` 且 `secret_jwt_template.role=edoc_backend` 的專用 key。先呼叫 `edoc.edoc_runtime_identity()` 證明 `databaseRole=edoc_backend`，再實測 public HR API 與 `hr-documents` 均拒絕、Storage 只列出兩個 eDoc bucket，才可寫入 Vercel server-side environment。普通 default secret 會解析成 `service_role` 並 bypass RLS，不可用於共享模式 runtime。

歷史 `supabase/migrations` 仍維持獨立 project 的 immutable public-schema 路徑；不得手動搜尋取代後直接執行，也不得重新執行已完成的共享 bootstrap。共享模式後續變更只能新增專用 forward migration。

新環境執行 `supabase db reset` 時，CLI 會先載入
`supabase/roles.sql`。該檔補齊歷史 migration 在外鍵指派前漏建的 9 個
legacy permission reference rows、早期 migration 所需的 pgcrypto `digest()`
相容 overload、空的後端專用 `private` schema，以及只供全新 reset 通過既有
Finance tenant backfill 的結構性 sentinel。sentinel 不是帳號、公司或組織資料，
且會由 `20260827064100_remove_fresh_finance_bootstrap_sentinel.sql` 核對完整簽章、
確認零引用後於同一次 migration replay 中刪除。相容函式在歷史 replay 階段
僅供資料庫擁有者與 `service_role` 使用；runtime hardening 完成後會再收回
`service_role` 權限，只保留資料庫擁有者。空的相容 schema 不授權前台角色。
此做法不改寫任何已套用的 migration。既有正式資料庫不得為此重跑舊 migration，
仍只依核准的 forward migration 與變更單發布。

### 主 eDoc Supabase

1. 先執行 `supabase unlink` 清除舊連結，再以 `supabase link --project-ref <main-edoc-project-ref>` 連結主 eDoc project；用 `supabase projects list`／project URL 再確認一次，禁止沿用專用 Storage project 的 link。repository 不再硬編碼舊 project ref，避免誤推到已退役或 Storage 專案。
2. 比對 `supabase/verification/migration_manifest.json` 與 `supabase/migrations/*.sql`，再執行 `supabase migration list --linked` 確認遠端與 repository 的 migration 歷程一致。
3. 若遠端出現 repository 不存在的 migration，或同一版本的套用狀態不一致，立即停止；不得自行執行 `supabase migration repair`、不得略過版本，也不得用 `db pull` 產生未經審查的正式基線。先由資料庫負責人核對遠端 SQL、雜湊與變更單，再以核准的 baseline／forward migration 補齊 repository。
4. 先判定 linked project 是「全新空白」或「已有 migration 歷程」，兩條路徑不可混用：
   - **全新空白 project**：`roles.sql` 必須先於歷史 migration chain 載入。先執行 `python3 tools/supabase_main_migration_push.py fresh-empty --project-ref <main-edoc-project-ref>` 做 dry-run；核准後才在同一命令加 `--apply`。wrapper 只有在遠端 migration 歷程為空時才會加入 `supabase db push --include-roles`，否則拒絕。
   - **既有 project**：執行 `python3 tools/supabase_main_migration_push.py existing --project-ref <main-edoc-project-ref>` 做 dry-run；核准後才加 `--apply`。此路徑永不加入 `--include-roles`，也不得手動重跑 `roles.sql`，避免在移除 migration 已通過後重新插入 fresh-only sentinel。wrapper 會檢查官網／CMS relation marker 與非 eDoc bucket；只要判定為共用 project 就拒絕，因為後續 Data API hardening 會全面收回 public schema 的 browser grant／policy。
   - 若既有 eDoc 資料仍位於官網／CMS project，禁止在該 project 直接套用本 migration chain。先建立乾淨的獨立主 eDoc project，依核准的欄位級匯出／匯入與 hash、筆數、外鍵驗證移轉 eDoc 資料；官網 project 僅作為唯讀來源，且不得把公文本文、附件、憑證或個資輸出到 log／證據檔。
   - wrapper 只接受 Supabase CLI `2.116.0`，並用唯讀 `db query` JSON 介面驗證 migration table 與版本。`fresh-empty` 還要求 public 非 extension 物件、Auth 使用者、Storage buckets/objects 全部為 0；CLI 版本、查詢格式、linked ref 或遠端狀態無法確認時一律停止，不猜測 fresh／existing。
5. 歷程一致後，先確認 linked project 的 PostgreSQL major version 至少為 16（本 repository 的 `supabase/config.toml` 鎖定 17；Storage lifecycle 約束使用 `pg_input_is_valid`，舊版不得發布），再於隔離環境完整 reset／重建並執行 `fresh_bootstrap_smoke.sql`、`runtime_schema_parity_smoke.sql`、`service_role_data_api_grant_smoke.sql` 及五帳號驗收。
6. 取得資料庫備份、指定回復點與人工變更核准後，才依核准路徑套用正式 migrations。既有 project 在套用 `20260827194500_promote_editor_tus_staging_to_immutable.sql` 前，必須先暫停 PDF Editor 的新建上傳與 finalize、等待在途請求與最晚一枚 signed TUS capability 失效。操作人員先以不輸出 credential 的方式，核對目前 server environment 的主資料庫與專用 Storage project ref 都等於核准變更單，再執行 `python3 scripts/verify_editor_storage_assets.py --acknowledge-private-document-download`；URL 與 service-role key 只能來自 server environment，不得寫入命令、shell history 或證據檔。工具必須 exit 0，且 aggregate JSON 為 `passed=true`、`invalidAssetCount=0`，不得輸出 path、檔名、hash、document ID 或文件內容。接著才以唯讀方式執行 `supabase/verification/editor_storage_promotion_preflight.sql`；`checkedAssetCount` 必須精確等於 SQL 的 `finalized_editor_asset_count`，且 `active_editor_upload_count=0`、`finalized_assets_requiring_byte_promotion=0`、`nonfinalized_assets_without_durable_job_input=0`，最後回傳 `editor_storage_promotion_preflight_ok` 才可繼續。若任一 gate 阻擋，先依變更單完成可稽核的 Storage bytes 搬移／清理，禁止只改資料庫 path、跳過檢查或把 metadata 相符當成 bytes 已驗證。
7. migration 套用後仍維持 PDF Editor 維護狀態，先執行 `python3 scripts/verify_editor_storage_assets.py --acknowledge-private-document-download --post-migration`，再次要求 exit 0、`passed=true`、`invalidAssetCount=0`，並確認 `checkedAssetCount` 與 pre-migration 證據一致；此階段同時驗證已建立的 storage job 綁定。接著部署相容版本的後端，以既有 server-side `CRON_SECRET` 觸發受保護的 `/api/cron/run-due` cleanup，確認沒有 `cleanup_failed` 後，再執行 `fresh_bootstrap_smoke.sql`（fresh 隔離環境）、`runtime_schema_parity_smoke.sql` 與 `service_role_data_api_grant_smoke.sql`。不可在舊後端仍會建立「沒有 storage job 的 upload intent」時重開上傳，也不可為通過 cutover 直接人工把 job 狀態改成 `cleaned`。
8. 執行 `supabase/verification/production_cutover_checks.sql`；所有 required table/RPC、RLS、grant 與 demo-data 檢查必須通過，`fresh_finance_bootstrap_sentinel`、`invalid_finalized_editor_assets`、`invalid_editor_storage_jobs`、`active_editor_storage_job_leases`、`expired_editor_storage_job_leases`、已逾期的 `editor_storage_cleanup_backlog` 必須為 0，且 immutable trigger/function 檢查必須為 true。`promoting`／`cleaning` 使用五分鐘 durable lease 與 compare-and-set；部署或回復時不得略過有效 lease，也不得把過期 lease 直接標為成功，必須由 cleanup worker 接管並完成或留下 bounded machine error code。
9. 以隔離的五個正式測試帳號完成 TUS 上傳、finalize、簽核、用印、收件與下載；另以不同 bytes 重播尚未到期的 staging capability，確認 `editor-final/` 的 path、hash 與下載內容不變。證據完成後才解除 PDF Editor 維護狀態。

`supabase/recovery/complete_edoc_runtime_recovery_20260827.sql` 是 2026-08-27 的唯讀災難復原快照，不在 `supabase/migrations`、不在 migration manifest，也不得用 `supabase db push` 套到既有正式資料庫。可線性部署的主資料庫變更只有 manifest 內的純 forward migrations；本次相關檔案依序為：

1. `20260827050436_complete_edoc_runtime_schema_parity.sql`：以 idempotent DDL 補齊 fresh bootstrap 與既有環境的 runtime tables、欄位、constraints、RLS、trigger 與 service-only RPC；不啟用正式交換 provider。
2. `20260827050447_remove_exact_demo_bootstrap_records_forward.sql`：只依已列明的精確 demo identifier 清理舊 bootstrap 資料，不使用模糊名稱、email 或 regex 刪除。
3. `20260827050450_atomic_official_submission_editor_finalize_forward.sql`：只建立／取代兩支 atomic RPC、收回 browser 執行權、只授權 `service_role`，並通知 PostgREST 重載 schema。
4. `20260827050452_add_confirmed_edoc_fk_indexes_forward.sql`：只以 `create index if not exists` 補齊 Supabase Performance Advisor 已確認的 eDoc 外鍵索引，不處理 shared CMS，也不刪除 unused index。
5. `20260827061915_harden_audit_hash_runtime.sql`：將新稽核紀錄切換至序列化雜湊鏈，並把鏈頭資料與驗證權限鎖在後端。
6. `20260827063824_lock_runtime_table_data_api_grants.sql`：回溯移除 public schema 所有 `PUBLIC`／`anon`／`authenticated` table、sequence、function Data API grant 與 browser policy，再按後端實際操作授予 `service_role` 最小權限。
7. `20260827064100_remove_fresh_finance_bootstrap_sentinel.sql`：只在全新 reset 存在完整結構性 sentinel 且沒有任何引用時移除；既有環境沒有該列時為精確 no-op。
8. `20260827101441_capture_official_dispatch_events.sql`：以後端私有 trigger 將寄送紀錄建立、欄位異動與狀態轉換寫入不可變事件；既有寄送紀錄只建立 baseline snapshot，不臆造歷史事件，並禁止改掛公文、改寫建立者或建立時間。
9. `20260827101636_avoid_postgrest_business_conflict_retries.sql`：把公開 RPC 人工拋出的業務／樂觀鎖衝突改為 `PT409`，避免舊版 PostgREST 將 `40001` 當成可重試序列化失敗而使請求逾時，也讓人工 `23505` 與真正 constraint violation 分流；資料庫真正產生的序列化失敗與唯一鍵衝突仍維持原本行為。
10. `20260827194500_promote_editor_tus_staging_to_immutable.sql`：建立後端專用的 Storage lifecycle job 與 promotion／cleanup durable lease、將 finalize 原子綁定至 `editor-final/` 不可變物件，並鎖定已 finalized asset（包含禁止刪除）。既有 finalized staging asset 無法由 SQL 安全搬移 bytes，必須先通過 `editor_storage_promotion_preflight.sql`；不得把 migration 的 fail-closed 例外當成可略過的警告。

這些檔案仍須先在與正式 schema 相同的隔離環境完成 `supabase db reset`、RPC smoke 與安全檢查，並逐檔取得人工核准；拆成 forward migration 不代表可以略過備份、回復點或變更審查。

`supabase/seed.sql` 是刻意無資料的 production-safe seed，不會建立人員、公司、文件、憑證、裝置或通知。正式環境不需要執行 seed；若 CI 的 fresh bootstrap 固定會執行，也只會得到一個無副作用的檢查結果。

### 專用 Storage Supabase

專用 Storage project 不得套用主資料庫的全部 migrations，只執行 `supabase/storage-migrations` 的以下三個純 Storage migration，且順序不可顛倒：

執行前先比對 `supabase/verification/storage_migration_manifest.json` 與
`supabase/storage-migrations/*.sql`；清單或順序不一致時立即停止。

1. `supabase/storage-migrations/20260824034730_dedicated_edoc_private_storage_buckets.sql`
2. `supabase/storage-migrations/20260827042214_harden_edoc_storage_buckets.sql`
3. `supabase/storage-migrations/20260827050000_enforce_empty_storage_client_policy_allowlist.sql`

這三個檔案只允許套用到 dedicated Storage project，絕不可套用到官網／CMS、會計或主 eDoc database project；其中 allowlist migration 會移除 dedicated project 的所有 browser client object policies。檔案要作為獨立、經人工核准的 Storage 變更執行；不得在仍連結專用 Storage project 時執行主資料庫的 `supabase db push`。完成後再次 `supabase unlink`，避免下一次誤把主資料庫 migration 推到 Storage project。

獨立主 eDoc 資料庫只執行 `supabase/verification/production_cutover_checks.sql`；專用 Storage project 另執行 `supabase/verification/dedicated_storage_cutover_checks.sql`。不可把兩份檢查互換，也不可對官網／CMS 或會計 project 執行任一份 eDoc cutover SQL。

套用後必須確認：

- `edoc-private`、`edoc-seal-vault` 均為 private。
- Storage project 只能有上述兩個 bucket；不得殘留其他模組 bucket。
- `edoc-private` 接受 PDF、核准的辦公文件／圖片及 archive 所需的 `application/zip`。
- 兩個 bucket 均不接受 `image/svg+xml`。
- `storage.objects` 的 `PUBLIC`／`anon`／`authenticated` policy allowlist 為空；瀏覽器僅使用後端簽發的短效能力。若其他模組未來需要直接 Storage policy，必須先拆分 bucket／project 或另行安全審查，不可直接加回共用 policy。
- `auth.users`、public 非 extension application relations/functions 都必須為 0；若專案仍有舊系統帳號、資料表或函式，必須改用乾淨的專用 Storage project，或依獨立核准的除役變更單處理，不能由 eDoc 部署流程直接刪除。

## 2. Vercel 正式環境變數

已核准共享 project 模式的必要設定：

```text
EDOC_DEPLOYMENT_ENV=production
EDOC_DB_MODE=supabase
EDOC_PUBLIC_BASE_URL=https://edoc.suiyuecare.com
SUPABASE_URL=https://<main-edoc-project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<edoc_backend-custom-secret-only>
EDOC_SUPABASE_SCHEMA=edoc
EDOC_SUPABASE_BACKEND_ROLE=edoc_backend

EDOC_STORAGE_PROVIDER=supabase
EDOC_STORAGE_SUPABASE_MODE=shared-project-schema
EDOC_STORAGE_SUPABASE_URL=https://<same-project>.supabase.co
EDOC_STORAGE_SERVICE_ROLE_KEY=<same-edoc_backend-custom-secret>
EDOC_STORAGE_PUBLISHABLE_KEY=<publishable-key>
EDOC_STORAGE_BUCKET=edoc-private
EDOC_STORAGE_ACCESS_MODE=server-signed-url
EDOC_SIGNED_URL_TTL_SECONDS=300

EDOC_FILE_ENCRYPTION_ENABLED=true
EDOC_FILE_ENCRYPTION_KEY=<server-only>
EDOC_SCAN_ENGINE=ClamAV-compatible
EDOC_AV_PROVIDER=vercel-sandbox-clamav-v1
EDOC_AV_SANDBOX_SNAPSHOT_ID=<approved-snap_id>
EDOC_AV_SANDBOX_PROJECT_ID=<optional-vercel-project-id>
EDOC_AV_TIMEOUT_SECONDS=120
EDOC_AV_SMOKE_SECRET=<server-only-random-32-byte-secret>
# Legacy HTTPS HMAC alternative only when separately approved:
# EDOC_AV_PROVIDER=edoc-clamav-https-v1
# EDOC_AV_ENDPOINT=https://<approved-private-endpoint>/v1/scan
# EDOC_AV_API_KEY=<server-only-32-byte-minimum>
EDOC_MAX_FILE_SIZE_MB=100
CRON_SECRET=<server-only>
APP_SECRET=<server-only>
```

`EDOC_STORAGE_PUBLISHABLE_KEY` 只用於 Storage 的公開 client identification；上傳授權仍須由後端核發。共享模式的 `EDOC_STORAGE_SERVICE_ROLE_KEY` 與 `SUPABASE_SERVICE_ROLE_KEY` 是同一把 `edoc_backend` custom secret，且只存在 server-side environment；獨立 project 模式仍必須使用各 project 自己的 server key 並分開輪替。

PDF Editor 的 signed TUS 只可寫入 `editor/` 暫存路徑。Finalize 完成大小、SHA-256、掃毒與 PDF／圖片解析後，後端必須把已驗證 bytes 以 service role 建立在 `editor-final/<document>/<asset>/` 不可變路徑；migration `20260827194500_promote_editor_tus_staging_to_immutable.sql` 會在同一筆資料庫交易中將 asset 與 file object 綁到正式路徑，成功後才清除暫存。正式驗收不得把短效 Storage token 宣稱為密碼學上的一次性 token，而要用不同內容重播，確認正式檔案的路徑、hash 與下載內容完全不變。

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
vercel env add EDOC_SUPABASE_SCHEMA production
vercel env add EDOC_SUPABASE_BACKEND_ROLE production
vercel env add EDOC_STORAGE_SUPABASE_MODE production
vercel env add EDOC_STORAGE_SUPABASE_URL production
vercel env add EDOC_STORAGE_SERVICE_ROLE_KEY production --sensitive
vercel env add EDOC_STORAGE_PUBLISHABLE_KEY production
vercel env add EDOC_STORAGE_BUCKET production
vercel env add EDOC_FILE_ENCRYPTION_KEY production --sensitive
vercel env add EDOC_AV_PROVIDER production
vercel env add EDOC_AV_SANDBOX_SNAPSHOT_ID production --sensitive
vercel env add EDOC_AV_SMOKE_SECRET production --sensitive
vercel env add CRON_SECRET production --sensitive
vercel env add APP_SECRET production --sensitive
```

## 3. 發布前資料與安全閘門

在正式部署核准單留下以下證據：

1. migration manifest 與 repository migration 清單一致。
2. `supabase migration list --linked` 顯示遠端與 repository 歷程一致，沒有使用未核准的 `migration repair` 覆寫歷程。
3. 隔離環境 fresh bootstrap 成功，且 `supabase/seed.sql` 未建立 demo data。
4. `production_cutover_checks.sql` 的 demo identifier 計數為 0。
5. 88 張後端直連表的 service-role 最小權限矩陣逐項相符，且 23 個直接 RPC 全部存在。
6. 23 個直接 RPC 僅 `service_role` 可執行；`PUBLIC`、`anon`、`authenticated` 無權限，且沒有未列入 allowlist 的 legacy RPC。
7. runtime tables 啟用 RLS，browser Data API grant 為 0；`login_events` 可由後端新增／讀取但不可更新或刪除。
8. 40 個已確認的 eDoc 外鍵索引全部存在，且未新增 shared CMS index 或刪除 unused index。
9. Storage bucket private、包含 ZIP、排除 SVG，舊 direct-object policies 不存在。
10. 站內通知規則 ready；Email／LINE 若未設定應明確顯示 pending，而非阻擋內部上線或假裝成功。
11. Pre／post-migration `verify_editor_storage_assets.py` 都 exit 0、`invalidAssetCount=0`，兩次 `checkedAssetCount` 與 SQL `finalized_editor_asset_count` 完全一致；`editor_storage_promotion_preflight.sql` 已於維護窗口通過。stale editor upload、invalid finalized asset、invalid storage job、active／expired lease 與逾期 cleanup backlog 均為 0。`official_document_editor_storage_jobs` 必須啟用並強制 RLS，immutable trigger/function 必須存在、owner/search path/EXECUTE ACL 正確。
12. Finance 人員、公司、部門投影同步檢查通過，沒有手動維護的 demo 帳號。
13. fresh-only Finance sentinel 計數為 0；既有 project 的發布紀錄中沒有 `--include-roles` 或重跑 `roles.sql`。

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
curl -H "Authorization: Bearer $EDOC_OPERATOR_TOKEN" https://edoc.suiyuecare.com/api/production/deployment
curl -H "Authorization: Bearer $EDOC_OPERATOR_TOKEN" https://edoc.suiyuecare.com/api/production/monitoring
curl -H "Authorization: Bearer $EDOC_OPERATOR_TOKEN" https://edoc.suiyuecare.com/api/files/storage-health
curl -H "Authorization: Bearer $CRON_SECRET" https://edoc.suiyuecare.com/api/cron/run-due
curl -H "Authorization: Bearer $CRON_SECRET" https://edoc.suiyuecare.com/api/cron/monitoring
```

`EDOC_OPERATOR_TOKEN` 必須來自已登入且具有「系統管理」權限的短效 eDoc
session；不得寫入 repo、操作文件或 shell history。部署資訊、監控明細、Storage／AV
狀態、憑證狀態與切換產物 API 一律拒絕一般員工及未登入請求。健康檢查與經過遮罩的
readiness 才維持公開，供 Vercel 與負載平衡器探測。

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

Vercel rollback 只能回復應用部署。已套用的資料庫 migration 要用經審查的 forward-fix migration；正式發布前必須先有資料庫備份、回復點與負責人。若回退的應用版本不會建立 storage lifecycle job，必須同步關閉 PDF Editor 上傳／finalize，不能讓舊版後端寫入新 schema。正式值班、告警分級與處理步驟見 `docs/production-monitoring-runbook.md`。
