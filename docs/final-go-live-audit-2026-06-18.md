# 2026-06-18 上線前最終 Go / No-Go 稽核

檢查日期：2026-06-17  
目標上線日期：2026-06-18

## 判定

目前判定為 **NO-GO for formal external launch**。

系統可做內部演練、教育訓練、簽核流程試跑、PDF 用印流程驗收與 UI/UX 驗收；不可對外宣告正式電子公文交換已完成，也不可送正式 jAgent / 電子交換環境。

## 可開放範圍

- 員工撰寫公文、確認預覽、暫存草稿、送簽流程演練。
- 主管簽核、退回補正、風險排序與簽核紀錄檢視。
- 總務收文登錄、分派、發文查詢、合約用印與 PDF 押章流程演練。
- 收到公文或合約的單位可檢視承接狀態、目前關卡、待辦數與風險數。
- 維運中心可執行 `/api/production/go-live-audit`、`/api/production/readiness`、`/api/production/monitoring`。

## 不可開放範圍

- 不可使用 mock provider 對外宣稱正式電子交換已啟用。
- 不可連正式電子公文交換環境，除非機關已提供 jAgent/API/SDK/封包規格，且測試通過並有人工核准。
- 不可把 production 留在 Vercel `/tmp` SQLite 當正式資料庫。
- 不可用 local-simulation 簽章作為正式對外公文或合約用印證據。
- 不可讓未掃描、未加密或未進 private object storage 的附件進入正式交換。

## 必補阻塞項

1. 建立獨立 eDoc Supabase project，設定 `SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`、`EDOC_DB_MODE=supabase`，套用 migrations 並驗證 RLS。
2. 完成 private object storage、短效下載 URL、檔案加密金鑰與 AV endpoint/API key。
3. 完成正式電子簽章 provider、HSM/KMS、信任根、TSA、OCSP、CRL。
4. 完成 SMTP、LINE、監控 webhook、Sentry 與 Cron 實測。
5. 匯入正式帳號後設定 `EDOC_DISABLE_DEMO_ACCOUNTS=true`，移除 demo1234 上線風險。
6. 等機關提供正式 jAgent/API/SDK/封包規格後，才可實作並啟用 RealExchangeProvider。

## 明天操作建議

1. 先以「內部試營運」名稱開放，不稱正式對外交換。
2. 上線前先登入總務、員工、主管、行政部主任四種帳號各跑一次 smoke test。
3. 維運中心按「上線 Go / No-Go 判定」，若不是 `GO`，只開內部演練。
4. 每次補完一項正式服務後重新部署，再打 `/api/production/go-live-audit`。
5. 等 Go / No-Go 判定為 `GO` 後，再安排正式交換上線公告。
