# Module_edoc

歲悅長照獨立電子公文交換系統原型。此模組不隸屬官網，定位與財務中台相同，屬於內部營運系統，介面風格比照 Finance：登入畫面、深色側欄、暖橘品牌色與固定中台工作區。

## 目標

依國家發展委員會檔案管理局《機關公文電子交換作業辦法》、《公文電子交換系統資訊安全管理規範》與文書檔案管理相關規範，規劃串接「機關層公文收發模組 jAgent」，處理與政府機關往來的電子收文、電子發文、交換狀態、異常重送、歸檔保存與稽核紀錄。

## 目前內容

- `index.html`：獨立系統入口。
- `styles.css`：內部系統 UI 樣式。
- `app.js`：登入/登出、模擬資料、頁籤切換、收發文列表、功能總表與互動提示。
- `backend.py`：零依賴 Python 後端，提供靜態檔服務、REST API、SQLite schema migration、seed data、audit log 與資料備份。
- `data/edoc.sqlite3`：本機 SQLite 後端資料庫，啟動後自動建立。
- `backups/`：後端資料庫備份輸出目錄。

## 後端啟動

```bash
python3 backend.py --host 127.0.0.1 --port 5174
```

可用 API：

- `GET /api/health`
- `GET /api/dashboard`
- `GET /api/documents`
- `GET /api/recipients`
- `GET /api/attachments`
- `GET /api/exchange_tasks`
- `GET /api/exchange_events`
- `GET /api/audit_logs`
- `POST /api/actions/pull-inbound`
- `POST /api/actions/backup`

## GitHub / Vercel / Supabase 串接

本專案已初始化 Git，並補齊三平台部署檔：

- GitHub：本地 Git repo 已建立；目前 GitHub App 尚未安裝到任何 repo，且本機沒有 `gh` CLI，因此尚無遠端 origin。
- Vercel：`vercel.json` 與 `api/index.py` 已建立，可部署靜態前端與 Python API。
- Supabase：`supabase/migrations/202605220001_edoc_core.sql` 與 `supabase/seed.sql` 已建立；後端在 `SUPABASE_URL` 與 `SUPABASE_SERVICE_ROLE_KEY` 存在時會自動改走 Supabase REST API。

Vercel 需要設定的環境變數：

```bash
EDOC_DB_MODE=supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<server-only-service-role-key>
```

Supabase 專案建議建立獨立的 `Suiyuecare eDoc` project，不要混用 Finance / Website / HR 的正式資料庫。

## 需要的完整功能

1. 收文管理：jAgent 拉取來文、收文登錄、條碼/收文號、附件檢視、承辦分派、誤送漏送通知。
2. 發文管理：建立函稿、受文者與副本管理、清稿檢核、附件封裝、送交 jAgent、狀態查詢、重送。
3. jAgent 介接：憑證登入、Token 管理、API 狀態、交換中心連線、地址簿查詢、送件、收件、回覆同步。
4. 文書格式：文號、文別、速別、密等、主旨、說明、辦法、附件清冊、受文者機關代碼、標準交換資料欄位。
5. 流程控管：總收發、承辦人、文書主管、資訊管理員、稽核人員權限與待辦。
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
