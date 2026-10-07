# 上線交接與季檢清單

版本：2026-10-08
用途：正式上線前交接、每季稽核檢查

> 適用範圍更新（2026-10-08）：本次只上線內部公文、用印、簽核與收發管理，
> 正式電子公文交換維持 Mock／停用。本文件涉及 jAgent、機關代碼、交換憑證及
> `/api/production/readiness` 的項目，改列為未來正式交換 provider 啟用條件，
> **不作為本次內部上線的成功訊號**。本次必須依
> `docs/deployment-production.md`：`/readyz` 回傳 HTTP 200、內部 Go/No-Go 通過，
> 且正式交換仍為 `formalGo=false`；在正式交換規格與人工核准完成前，
> `/api/production/readiness` 回傳 503 是預期的安全狀態。

本輪六項改善：離職未結案件交接、真人 SSO／人員異動、上傳效能／多裝置操作、通知／收發閉環、例行備份／復原、操作手冊／介面文字。程式、隔離測試、發布與正式驗收分別記錄；真人 SSO、實體手機、異地金鑰保管及連續 7 日備份證據仍 pending。以下「待確認」不得因文件更新或一次發布自動改成通過。

## 1. 上線前必要條件

| 項目 | 狀態 |
|---|---|
| eDoc Supabase 隔離拓撲已建立（獨立 project，或核准的 edoc schema／edoc_backend 共享模式） | 待確認 |
| 本次已批准發布所需 migration 已套用，且相容性與讀回檢查通過；未批准候選不自動啟用 | 待確認 |
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
| 員工、主管、總務、行政主任、負責人本人完成跨模組及新分頁 SSO，無權限入口仍拒絕存取 | pending：真人驗收 |
| 新進、調職、停用／離職資料同步及未結案件交接；候選須核准才生效，關聯新案不覆寫原案 | pending：受控驗收 |
| 抽單、退回上一關、否決、加簽與版本鎖定各依狀態拒絕越權；申請人收件確認、用印已認領／開始、完成或寄發後不可抽單的界線已實測 | 待確認 |
| PDF 本機先可編輯、背景雲端保存；失敗不顯示已保存、同步／預檢完成前禁止送簽與切換案件 | 待確認 |
| A4 橫直式可編輯；非 A4 經等比例轉換同意與預覽確認，原稿保留；50 MB／300 頁、權限、結構及 hash 檢查保留，PDF 沒有掃毒等待步驟 | 待確認 |
| 電腦、平板、實體手機含弱網及斷線重試；記錄樣本條件與 p95，驗收工作區 0.5 秒／本機編輯 2 秒目標，不宣稱任意檔案都達標 | pending：實體手機與量測 |
| 選定公司只顯示可用章款；實際用印 PDF 可開啟、透明章層在最上層、位置／尺寸／大小章或騎縫章符合申請 | 待確認 |
| 站內通知／待辦及已啟用外部通道實測；服務接受、本人收到與已讀分開，不以 receipt 冒充送達 | pending：真人收件證據 |
| 收文保存／派發、承辦回覆、期限與主管追溯查詢，具權限與不可覆寫歷程 | 待確認 |
| 本機隔離 PostgreSQL／Storage bytes 還原與完整 receipt 校驗 | 本輪隔離回歸已通過；正式演練仍待確認 |
| 異地副本實際 bytes 取回後還原、異地金鑰保管與備援人交接 | pending：異地證據與保管確認 |
| 例行備份至少連續 7 日，包含快照時效、中斷／失敗告警、補跑；證明持續 RPO ≤ 15 分鐘／RTO ≤ 30 分鐘 | pending：尚無連續證據 |
| 資安事件通報窗口已確認 | 待確認 |

## 2. 權限交接

以下為交接責任，不表示職稱列於文件即已取得平台權限。須由實際主責／備援人登入平台讀回並確認；不在文件放密碼、Token、憑證或金鑰內容。

- GitHub repo admin：行政部主任
- Vercel project owner：行政部主任
- Supabase owner：行政部主任
- 備份解密金鑰：公司核准保管庫的主責／備援人，與異地備份分開保管；交接仍 pending
- jAgent 憑證保管：總務（未來正式交換啟用前另行核准；目前停用）
- 文書格式與清稿規則：行政部主任
- 季檢稽核：主任

## 3. 每季檢查

1. 匯出角色與權限矩陣。
2. 檢查停用人員帳號、裝置與 IP 限制。
3. 抽核內部派發失敗、退回、加簽、抽單及重送紀錄；正式交換 provider 啟用後才另核交換紀錄。
4. 抽核用印申請、押章座標、押章前後 PDF。
5. 抽核檔案雜湊與保存年限。
6. 執行備份復原演練，使用完整 receipt 重算 hash、核對本次 `drill_id`、來源／隔離目標及實際 RTO/RPO；異地取回與 PDF 開啟另測，不因本機通過而代填。
7. 測試通知通道，分開記錄 provider 接受、本人的收件確認及已讀；失敗重送不得抹除歷史。
8. 更新法遵控制矩陣與缺失追蹤。
9. 抽查 `official_document_editor_storage_jobs`：逾期 cleanup backlog、invalid finalized asset、invalid job、active／expired lease 均為 0，且不得輸出完整 path、hash 或文件名稱；過期 lease 必須由 worker 以 compare-and-set 接管，不得人工直改為成功。
10. 正式站 `/readyz` 必須通過 required RPC 與 PDF Editor V2 server-only table 的 Data API contract；任一缺少時，建立草稿、取得 TUS 上傳資格、finalize 與 prepared PDF preflight 必須先回 `editor_runtime_maintenance`（503），不得建立半套草稿或把資料庫缺件誤顯示為登入失敗。
11. 抽核人員新進、調職、停用／離職後的權限與未結簽核；主管更動不得把待處理寫成已簽核，離職補正由接任人建立關聯新案並保留原申請人。

## 4. 上線後 7 日觀察

- 每日確認內部收發文量、簽核／用印成功率與失敗類型；正式交換維持 Mock／停用期間不以交換成功率作為內部上線指標。
- 每日確認背景任務是否準時執行。
- 每日核對各角色待辦、通知失敗／重送及本人收件確認；通道接受不等於收到或已讀。
- 留存備份每次開始／完成／失敗、來源快照年齡及異地驗證。每日人工查看不是 15 分鐘 RPO 的證明；整段 7 日均須量測，超時、斷線與漏跑不能隱藏。主機 prepare-only plist 或 `unattendedCloudDR: false` 的 receipt 不能當作無人值守雲端 DR。
- 持續記錄工作區可互動、本機 PDF 可編輯、雲端保存、產出與下載的分段耗時及 p95，連同裝置／網路／大小／頁數；快取命中與冷啟動分開，不只取最快一筆。
- 每日確認 PDF Editor 逾期 staging cleanup 已完成，且 finalized asset 仍綁定原本的不可變檔案。
- 若內部簽核、用印或收發失敗率超過 2%，需由行政部主任與總務共同檢查；正式交換 provider 啟用後才另計交換失敗率。

## 5. 退場或暫停服務

若需暫停正式服務：

1. 暫停 PDF Editor 新上傳與 finalize；正式交換 provider 啟用後才另行暫停 jAgent 送件。
2. 保留未結公文、簽核、派發／用印任務、不可變檔案及歷程；未來正式交換啟用時亦保留未完成交換任務。
3. 匯出保存包與 audit log。
4. 通知總務、行政部主任、主任與執行長。
5. 程式 rollback 先讀回當次已驗證且資料結構相容的上一版部署；不使用未驗證舊 ID，不直接以舊備份覆寫正式資料。復原後重驗 `/readyz`、內部 Go/No-Go、SSO、編輯／簽核／用印及檔案下載；正式交換仍停用，只有未來經核准啟用時才另做其 readiness 與交換測試。
