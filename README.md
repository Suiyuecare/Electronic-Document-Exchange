# Module_edoc

歲悅長照獨立電子公文交換系統原型。此模組不隸屬官網，定位與財務中台相同，屬於內部營運系統，介面風格比照 Finance：登入畫面、深色側欄、暖橘品牌色與固定中台工作區。

## 目標

依國家發展委員會檔案管理局《機關公文電子交換作業辦法》、《公文電子交換系統資訊安全管理規範》與文書檔案管理相關規範，規劃串接「機關層公文收發模組 jAgent」，處理與政府機關往來的電子收文、電子發文、交換狀態、異常重送、歸檔保存與稽核紀錄。

## 目前內容

- `index.html`：獨立系統入口。
- `styles.css`：內部系統 UI 樣式。
- `app.js`：登入/登出、後端 Auth session、RBAC 載入、模擬資料、頁籤切換、收發文列表、功能總表與互動提示。
- `backend.py`：Python 後端，提供靜態檔服務、REST API、SQLite schema migration、PDF 衍生版本、Auth session、RBAC、audit log 與資料備份。
- `data/edoc.sqlite3`：本機 SQLite 後端資料庫，啟動後自動建立。
- `backups/`：後端資料庫備份輸出目錄。

## 後端啟動

```bash
python3 backend.py --host 127.0.0.1 --port 5174
```

可用 API：

- `GET /api/health`
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/auth/logout`
- `GET /api/dashboard`
- `GET /api/documents`
- `GET /api/recipients`
- `GET /api/attachments`
- `GET /api/exchange_tasks`
- `GET /api/exchange_events`
- `GET /api/audit_logs`
- `GET /api/users`
- `GET /api/roles`
- `GET /api/permissions`
- `GET /api/role_permissions`
- `GET /api/auth_sessions`
- `GET /api/login_events`
- `GET /api/trusted_devices`
- `GET /api/ip_allowlist`
- `GET /api/sso_providers`
- `POST /api/actions/pull-inbound`
- `POST /api/actions/backup`
- `POST /api/jobs/:id/run`
- `POST /api/jobs/run-due`
- `POST /api/jobs/run-all`
- `GET /api/job_runs`
- `POST /api/pdf/generate`
- `POST /api/pdf/stamp`
- `POST /api/pdf/verify`
- `GET /api/files/:id/download`

系統不提供內建 demo 帳號或 EDOC 專屬密碼登入；正式使用者一律由 Portal／Finance Google SSO 的短效簽章 handoff 進入，且必須先存在於 Finance 同步的人員主檔。

## GitHub / Vercel / Supabase 串接

本專案已初始化 Git，並補齊三平台部署檔：

- GitHub：本地 Git repo 已建立，Codex GitHub connector 已授權到 `Suiyuecare/Electronic-Document-Exchange`；本機 Git HTTPS credential 仍需更新後才能直接 push。
- Vercel：`vercel.json` 與 `api/index.py` 已建立，可部署靜態前端與 Python API。
- Supabase：`supabase/migrations/202605220001_edoc_core.sql`、`supabase/migrations/202605230001_auth_rbac.sql` 與 `supabase/seed.sql` 已建立；後端在 `SUPABASE_URL` 與 `SUPABASE_SERVICE_ROLE_KEY` 存在時會自動改走 Supabase REST API。正式 `SUPABASE_URL` 必須是獨立主 eDoc project，不可指向官網 CMS、會計或專用 Storage project。

Vercel 需要設定的環境變數：

```text
EDOC_DEPLOYMENT_ENV=production
EDOC_DB_MODE=supabase
EDOC_LAUNCH_COMPANY_MODE=finance_active
EDOC_PDF_EDITOR_V2_COMPANY_MODE=finance_active
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<server-only-service-role-key>
CRON_SECRET=<random-secret>
RESEND_API_KEY=<server-only-resend-key>
MAIL_FROM=公文收發電子用印系統 <notifications@suiyuecare.com>
LINE_WEBHOOK_URL=<line-webhook-url>
EDOC_SIGNATURE_PROVIDER=<formal-provider-name>
EDOC_SIGNATURE_API_URL=https://<signature-provider>/api
EDOC_SIGNATURE_API_KEY=<server-only-signature-api-key>
EDOC_SIGNATURE_KEY_ID=<hsm-or-kms-key-id>
EDOC_HSM_PROVIDER=<hsm-or-kms-provider>
EDOC_CERT_TRUST_STORE=<trusted-root-ca-bundle-or-secret-ref>
EDOC_TSA_URL=https://<tsa-provider>/timestamp
EDOC_TSA_API_KEY=<server-only-tsa-api-key>
EDOC_OCSP_RESPONDER_URL=https://<ocsp-responder>
EDOC_CRL_DISTRIBUTION_URL=https://<crl-url>
```

公司與人員皆以 Finance 為唯一主檔。`EDOC_LAUNCH_COMPANY_MODE=finance_active` 會自動開放並同步 Finance 啟用公司；`EDOC_PDF_EDITOR_V2_COMPANY_MODE=finance_active` 讓同一批公司使用 V2，不必在新增公司後重改 Vercel。若發生資安事件或需要分批停用，可暫時切為 `manual_allowlist`，再以對應的 `*_COMPANY_IDS` 限制範圍。

正式環境必須同時配置可用的 ClamAV 掃毒端點與明確的 Finance 公司來源模式才可開啟。推薦的私人 Cloud Run gateway 位於 [`services/clamav-scanner`](services/clamav-scanner/README.md)，eDoc 與 gateway 以 HTTPS HMAC v1 雙向驗證；大檔由 gateway 讀取 60 秒 Supabase signed URL，避免經過 Vercel／Cloud Run HTTP/1 body 上限。V2 preflight 目前採同步、失敗即阻擋送簽；在具備原子 claim／lease／重送上限的 durable worker 前，不得宣稱為非同步處理或把既有週期任務表當作工作佇列。

編輯器使用自架、鎖版 PDF.js canvas＋SVG 編輯層。來源 PDF、匯入 PDF 與圖片走 private Storage 直傳、雜湊、掃毒及 preflight；送簽時鎖定 EditorState revision、manifest、prepared PDF 與每一枚印章版本。正式電子公文交換仍維持 Mock／停用，取得機關 jAgent／API／SDK／封包規格並完成測試與人工核准前不得切換正式 provider。

正式部署手冊：[`docs/deployment-production.md`](docs/deployment-production.md)。
正式環境檢查端點：

- `GET /api/readyz`：目前核准的內部 eDoc 模組就緒檢查；不會因尚未核准的正式交換／法定簽章 provider 而誤判故障。
- `GET /api/production/readiness`：完整正式交換與法定簽章就緒檢查；相關 provider 未核准前維持 fail-closed。
- `GET /api/cron/run-due`，需 `Authorization: Bearer <CRON_SECRET>`

PDF 與檔案儲存：

- SQLite 模式會把產生的 PDF 實體檔案寫入 `storage/pdf/<document-id>/`。
- `file_objects` 保存檔名、storage key、mime type、大小、SHA-256、用途與建立者。
- `pdf_versions` 保存押章前、押章後、用印申請 PDF 的版本、座標、章戳序號與前版關聯。
- `seal_applications` 保存用印申請、核准人、章戳序號、押章前後 PDF 版本 id。

Supabase 專案建議建立獨立的 `Suiyuecare eDoc` project，不要混用 Finance / Website / HR 的正式資料庫。Supabase 正式檔案實體可接 Storage bucket，現有 migration 已先建立 metadata tables 與 RLS。

背景任務：

- `background_jobs` 保存任務定義、週期、下次執行、啟用狀態與最近結果。
- `job_runs` 保存每次 worker 執行紀錄、結果、耗時與 payload。
- `python3 backend.py --run-due-jobs` 可由系統 cron、Vercel Cron 或其他排程器呼叫。
- 目前已落地任務：每日收文拉取、發文翌日查核、Token 到期檢查、逾期稽催、交換狀態同步、歸檔封存、報表產生。

通知真正送出：

- `notifications` 保存通知佇列，`notification_deliveries` 保存每次 Email / LINE / 站內通知派送結果。
- `system_inbox` 保存站內通知，`notification_rules` 保存收文、待清稿、交換失敗、Token 到期與逾期查核規則。
- `POST /api/notifications/sync` 會依公文、交換任務與 Token 狀態建立通知。
- `POST /api/notifications/send` 會實際呼叫 Resend、LINE webhook，並寫入站內通知。
- `POST /api/notifications/test`、`/retry-failed`、`/push-inbox` 分別提供通道測試、失敗重送與站內推送。
- Email 沿用官網的 `RESEND_API_KEY` 與 `MAIL_FROM`；LINE 需設定 `LINE_WEBHOOK_URL`。未設定時不會假裝成功，會寫入「未設定」派送紀錄。

法遵與營運文件：

- [`docs/compliance-control-matrix.md`](docs/compliance-control-matrix.md)：法規、控制要求、系統落點、證據與責任人。
- [`docs/operations-runbook.md`](docs/operations-runbook.md)：每日收發、發文、交換失敗、備份復原與變更管理 SOP。
- [`docs/incident-response-sop.md`](docs/incident-response-sop.md)：資安事件分級、隔離、通報、復原與事後檢討。
- [`docs/retention-audit-policy.md`](docs/retention-audit-policy.md)：保存年限、刪除凍結、稽核抽樣與輸出。
- [`docs/go-live-operating-checklist.md`](docs/go-live-operating-checklist.md)：上線交接、季檢與退場暫停服務清單。
- 系統內「法遵營運」頁籤可查看控制矩陣、文件清單、SOP、待補事項、季檢簽核與演練紀錄。

## 需要的完整功能

1. 收文管理：jAgent 拉取來文後統一由總務收文登錄，再分發給各部門主管，並保留條碼/收文號、附件檢視、誤送漏送通知。
2. 發文管理：建立函稿、受文者與副本管理、清稿檢核、附件封裝、送交 jAgent、狀態查詢、重送。
3. jAgent 介接：憑證登入、Token 管理、API 狀態、交換中心連線、地址簿查詢、送件、收件、回覆同步。
4. 文書格式：文號、文別、速別、密等、主旨、說明、辦法、附件清冊、受文者機關代碼、標準交換資料欄位。
5. 流程控管：僅主任、執行長、行政部主任、人資、會計、總務、業務助理可使用電子公文功能；總務為唯一收文入口，且總務與行政部主任不可直接檢視彼此部門公文，跨部門需透過分派、會辦、簽核或授權紀錄。
6. 稽催追蹤：發文翌日查核、逾期提醒、未收確認提醒、異常重送、退回補正。
7. 歸檔保存：原文、附件、交換事件、操作軌跡、檔案雜湊、版本與保存年限。
8. 資安控管：憑證卡、RBAC、IP/裝置限制、敏感欄位遮罩、Token 過期、操作不可否認性。
9. 報表統計：收發量、機關往來量、成功率、異常類型、承辦量、逾期件、月報。
10. 系統設定：機關代碼、交換中心、API URL、防火牆、憑證、角色、通知、測試/正式環境。
11. 通知中心：收文通知、待清稿提醒、交換失敗、Token 即將過期、逾期查核、退回補正。
12. 後端資料庫：公文主檔、受文者、附件、交換任務、交換事件、jAgent session、audit log、地址簿快取。

## 正式上線前條件

- 取得 jAgent API 文件、SDK 或部署套件。
- 取得交換測試環境、正式環境、憑證卡與機關代碼。
- 完成所屬統合交換中心連線、防火牆與地址簿服務設定。
- 建立後端 API、資料庫、權限、稽核與備份保存機制。
- 完成收發文人員操作流程、資安管理與異常通報程序。
