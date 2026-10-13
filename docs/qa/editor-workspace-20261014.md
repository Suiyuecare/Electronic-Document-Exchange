# 電子用印與工作區改善驗收

本次依已核准需求改善；正式政府交換仍停用。以下自動化資料為隔離合成資料，不代表真人 SSO 或正式網路速度。

## 功能與驗收對照

| 項目 | 實作 | 驗收 |
| --- | --- | --- |
| 公司／部門 | 用印公司在前，部門在後；切換公司保留原稿及非印章編輯 | 最後送出版本綁定公司、部門、章檔與簽核；異公司章不能殘留 |
| 下拉選單 | 本機固定版本 Tom Select；搜尋、鍵盤、IME、觸控、長名稱及視窗邊界 | 16 個真實瀏覽器情境；原生欄位值、option 順序與 change 事件不變 |
| 草稿 | 左側草稿入口與完整數量；25 筆游標分頁；明確選取才載入 | 31 筆前端／82 筆 PG 資料、去重、搜尋、跨使用者拒絕；另寫新稿時附件先確認 |
| 簽核 | 待簽核、我申請的、已簽核、被退件；保留總務與收件子任務 | 真正決策人與被指派者分開；SQL 先篩選候選資料，Python 再驗證權限 |
| 圖片 | PNG/JPEG 本機先編輯，背景同步；移除編輯器圖片 AV 步驟 | MIME、解碼、大小、雜湊、不可變儲存及權限仍驗證；狀態如實為 not_scanned |
| 即時操作 | 拖曳只更新選取圖層、rAF 合併指標事件、常駐暫存／預覽送簽 | 文字與圖片等比例；延遲同步、取消、重試、撤銷／重做與換案不覆寫新內容 |
| 印章保護 | 申請者只見實體尺寸的幾何示意；相容 preview API 亦不讀取真章像素 | 預覽端點無 Vault bytes；正式核准後才由伺服器產生真章 |
| 大小章 | 一般大小章選擇器與騎縫大章獨立 | 已登錄的小章不因打開騎縫工具消失；無實際合格檔案不能選 |
| 騎縫章 | 新版固定顯示右邊、上下各 10mm、每 5 頁一組，餘數均分 | 7 頁為 5+2；左至右切片且不壓縮；各組初始同高、可個別調高；歷史版本保留 |

一般附件與 Seal Vault 的安全檢查不在此次 AV 移除範圍。使用者上傳的 PDF 原有章圖不會被刪除；已核准下載檔也不宣稱能防止截圖。

## 回歸範圍

- `tests/editor_fluid_interaction.test.js`：本機先編輯、確定／不確定上傳失敗、finalize 中移除、跨草稿隔離、等比例與 rAF。
- `tests/test_editor_placeholder_image_policy.py`：預覽不讀真章、200／120 DPI 已核准尺寸例外保留。
- `tests/test_editor_seam_v2.py`：新舊政策、10mm 邊界、分組及輸出裁切。
- `tests/test_editor_image_upload_shared_forward.py`：真實隔離 PG finalize／copy、權限、原子性、冪等與偽造中繼資料拒絕。
- `tests/test_workspace_drafts_postgres.py`：public 與共享 edoc schema、草稿權限與分頁。
- `tools/workspace_navigation_browser_acceptance.py`：員工／負責人 × 桌機1440／平板820／手機390。
- `tools/verify_editor_correctness_browser.py`：圖片、文字、暫存、重開、預覽 PDF 與操作焦點。
- `tools/verify_grouped_seam_browser.py`：七頁騎縫、暫存、重開與預覽檔案。

## 靜態設計稽核判讀

`design.md lint`：0 errors、7 個既有孤立 token 提示。Premium 靜態稽核不是全綠：407 個 actionless-button 提示的掃描器只辨識 inline onclick／submit，專案以 app.js 事件綁定；2 個 native-select 提示則是 Tom Select 保留作為業務資料契約的 backing select。不得為消除提示而新增假事件或移除底層欄位。這些提示不作功能通過證明；各入口以實際瀏覽器互動、事件單次發送、權限與 HTTP readback 驗收。

## 本機效能樣本

同台 Chromium、1440／820／390 viewport，各 10 次（共 30 次），使用 20 頁約 4.87MB 合成 PDF（共用一張 raster）及 240KB PNG；不代表實體手機、冷快取、不同頁高解析掃描或正式網路。

| p95 毫秒 | 桌機版面 | 平板版面 | 手機版面 |
| --- | ---: | ---: | ---: |
| PDF 非空白畫面與可編輯模型就緒 | 334 | 372 | 352 |
| PDF 背景保存完成 | 1200 | 1347 | 1533 |
| PNG 可編輯 | 19 | 15 | 16 |
| PNG 背景保存完成 | 2143 | 2122 | 2182 |

360 次原生指標移動沒有完整 SVG 重建。事件到 rAF 回呼完成不等於硬體螢幕輸入延遲。本機 1.5 秒內「可編輯」達標，不宣稱所有檔案背景同步或正式站都在 1.5 秒內完成。

## 發布閘門

完整 Node／Python 回歸、隔離 PG、三種尺寸瀏覽器、相同 commit CI 通過後，才套用精確雜湊共享 forward migrations，建置凍結來源、驗證未指向網域的 production stage，再將該部署提升至前台。正式 URL、commit、deployment、資產雜湊與測試結果另記在發布證據；本文件本身不表示已部署。
