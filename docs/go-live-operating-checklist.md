# 上線交接與季檢清單

版本：2026-08-27
用途：正式上線前交接、每季稽核檢查

> 適用範圍更新（2026-08-27）：本次只上線內部公文、用印、簽核與收發管理，
> 正式電子公文交換維持 Mock／停用。本文件涉及 jAgent、機關代碼、交換憑證及
> `/api/production/readiness` 的項目，改列為未來正式交換 provider 啟用條件，
> **不作為本次內部上線的成功訊號**。本次必須依
> `docs/deployment-production.md`：`/readyz` 回傳 HTTP 200、內部 Go/No-Go 通過，
> 且正式交換仍為 `formalGo=false`；在正式交換規格與人工核准完成前，
> `/api/production/readiness` 回傳 503 是預期的安全狀態。

## 1. 上線前必要條件

| 項目 | 狀態 |
|---|---|
| 獨立 eDoc Supabase project 已建立 | 待確認 |
| 所有 migration 已套用 | 待確認 |
| Vercel production env 已設定 | 待確認 |
| PDF Editor 維護窗口內 `editor_storage_promotion_preflight.sql` 通過 | 待確認 |
| Pre-migration verifier exit 0、invalid=0，且 checked count 等於 SQL finalized count | 待確認 |
| Post-migration verifier exit 0、invalid=0，且 storage job 綁定通過 | 待確認 |
| 受保護 cleanup worker 已執行，無 cleanup_failed／逾期 backlog | 待確認 |
| Storage lifecycle job／immutable trigger 結構與安全檢查通過 | 待確認 |
| PostgreSQL major version 至少 16（本版目標 17） | 待確認 |
| invalid finalized asset、invalid storage job、active／expired storage job lease、逾期 cleanup backlog 均為 0 | 待確認 |
| Signed TUS 暫存重播無法改動 `editor-final/` 正式檔 | 待確認 |
| 維運 API／切換產物拒絕未登入與一般員工，只允許系統管理權限 | 待確認 |
| 維運頁 jAgent 狀態來自後端；停用時無假 Token、延遲或成功紀錄 | 待確認 |
| `/api/production/go-live-audit` 回傳 `decision=INTERNAL_GO`、`formalGo=false` | 待確認 |
| `/readyz` 回傳 HTTP 200，內部 Go/No-Go 通過 | 待確認 |
| `/api/production/readiness`、jAgent URL、機關代碼及交換憑證 | 未來正式交換啟用時確認；本次維持 Mock／停用 |
| 站內通知已驗證；Email／LINE 僅在正式啟用時驗證 | 待確認 |
| 備份與復原演練已完成 | 待確認 |
| 資安事件通報窗口已確認 | 待確認 |

## 2. 權限交接

- GitHub repo admin：行政部主任
- Vercel project owner：行政部主任
- Supabase owner：行政部主任
- jAgent 憑證保管：總務
- 文書格式與清稿規則：行政部主任
- 季檢稽核：主任

## 3. 每季檢查

1. 匯出角色與權限矩陣。
2. 檢查停用人員帳號、裝置與 IP 限制。
3. 抽核交換失敗與重送紀錄。
4. 抽核用印申請、押章座標、押章前後 PDF。
5. 抽核檔案雜湊與保存年限。
6. 執行備份復原演練。
7. 測試通知通道。
8. 更新法遵控制矩陣與缺失追蹤。
9. 抽查 `official_document_editor_storage_jobs`：逾期 cleanup backlog、invalid finalized asset、invalid job、active／expired lease 均為 0，且不得輸出完整 path、hash 或文件名稱；過期 lease 必須由 worker 以 compare-and-set 接管，不得人工直改為成功。
10. 正式站 `/readyz` 必須通過 required RPC 與 PDF Editor V2 server-only table 的 Data API contract；任一缺少時，建立草稿、取得 TUS 上傳資格、finalize 與 prepared PDF preflight 必須先回 `editor_runtime_maintenance`（503），不得建立半套草稿或把資料庫缺件誤顯示為登入失敗。

## 4. 上線後 7 日觀察

- 每日確認內部收發文量、簽核／用印成功率與失敗類型；正式交換維持 Mock／停用期間不以交換成功率作為內部上線指標。
- 每日確認背景任務是否準時執行。
- 每日確認通知派送是否成功。
- 每日確認 PDF Editor 逾期 staging cleanup 已完成，且 finalized asset 仍綁定原本的不可變檔案。
- 若內部簽核、用印或收發失敗率超過 2%，需由行政部主任與總務共同檢查；正式交換 provider 啟用後才另計交換失敗率。

## 5. 退場或暫停服務

若需暫停正式服務：

1. 暫停 PDF Editor 新上傳與 finalize；正式交換 provider 啟用後才另行暫停 jAgent 送件。
2. 保留所有未完成交換任務。
3. 匯出保存包與 audit log。
4. 通知總務、行政部主任、主任與執行長。
5. 復原後重新執行 Go / No-Go、readiness 與交換測試。
