# 上線前權限、表單與 PDF 保存驗收（2026-09-14）

## 本次修正

1. **列表 scope 資料外露**：列表查詢不再把粗篩候選資料當作最終授權；依當前流程世代、可執行任務及參與者權限再次過濾，避免透過其他 scope 看見無權限案件。
2. **代理人審閱與完成後留存**：有效且正輪到該關的代理人，可審閱原稿、編輯確認版及附件；實際完成決策後，依實際簽核人紀錄保留案件與下載權限。僅被指定但未執行的代理，不因代理紀錄永久取得檔案。
3. **代理現職資格與失效列表**：使用目前人員的公司、職級與角色檢查資格；離職、轉調、角色異動、過期或舊流程代理不得沿用。失效代理不能使整份待辦列表載入失敗，決策端仍保持嚴格驗證。
4. **PDF 遲到的自動保存回應**：保存請求綁定原文件及登入/編輯範圍；清空、登出或開啟新文件後，舊回應不得覆寫新文件內容、保存狀態或進行中的保存 Promise。

沒有移除權限檢查、PDF 預檢、送簽鎖定或原稿保留機制。本輪沒有介面改版、資料庫 migration 或真實印章變更。

## 本機驗收結果

| 範圍 | 結果 |
| --- | --- |
| 完整 unittest discover | 1,046 項：965 通過、81 跳過、零失敗；79.025 秒 |
| 額外隨機五帳號流程（seed 90210） | 5 案/5 通過；測試程式 3 項中 2 通過、1 跳過 |
| PDF 保存範圍單元測試 | 8 項通過 |
| 權限新增回歸／重點組合 | 新增 14 項通過；重點組合 65 項中 64 通過、1 條件跳過 |
| 四角色六大頁，桌機/手機 | 48 列、288 checks 通過；含設定入口與直接路由授權、列表可達、無整頁橫向溢出 |
| 四角色公文表單，桌機/手機 | 8 journeys、176 checks 通過 |
| 公文排版、保存/重開、文書規則 | 桌機/手機通過；5 個寄件聯絡欄完整保留 |
| 收發與簽核頁使用性 | 16 probes 完成；包含雙擊僅 1 次建立、收件回覆、載入失敗重試、鍵盤操作 |
| 公文/表單重點 HTTP 與前端合約測試 | 49 項通過 |
| PDF 直接編輯 | 151 checks 通過 |
| PDF 真實 409 衝突 | 桌機/手機 2 journeys 通過 |
| 六角色 PDF 編輯 | 桌機/手機 12 journeys 完成、整頁橫向溢出 0 |
| PDF 遲到保存的真實瀏覽器回歸 | 桌機/手機 24 checks 通過；兩份文件 API 讀回內容、URL 與保存次數保持隔離 |

表單驗收涵蓋今日日期及傳真 N/A、必填摘要、電子/實體公文大小章切換、可編輯附件說明、延遲 AI 不覆蓋人工內容、復原、雲端草稿恢復、部分附件失敗只重試失敗檔、409 保留人工內容與另存新稿。保存草稿與預覽不會送出正式申請。

後端新增回歸位於 `tests/test_launch_permission_regressions.py`；PDF 保存回歸位於 `tests/test_editor_save_scope.py`。完整測試的 81 項跳過不計為通過，所需指定資料庫/外部條件未由本機 fixture 證明。

## 測試工具修正與排除的假陽性

曾懷疑人工寄件地址被預設值覆寫；追查後是舊 harness 對已收合、不可見的聯絡欄直接 fill，未完成真實輸入。已改為先按「修改寄件資訊」，再填寫並 assert 值；桌機/手機保存及重開後，地址、承辦人、電話、傳真、Email 全部保留。**這是測試工具假陽性，不是產品地址覆寫修復**，沒有更動 Finance 初始預設。

PDF 編輯驗收工具已改用目前可見的文件內文字編輯操作，未把舊版隱藏輸入欄當成可操作介面。

## 原始證據

- `tests/.artifacts/launch-forms-20260914/pages-final/report.json`
- `tests/.artifacts/launch-forms-20260914/compose-final/report.json`
- `tests/.artifacts/launch-forms-20260914/contact-final/report.json`
- `tests/.artifacts/launch-forms-20260914/usability/report.json`
- `tests/.artifacts/launch-forms-20260914/editor-save-scope/report.json`
- `tests/.artifacts/launch-20260914/editor-inline-final/report.json`
- `tests/.artifacts/launch-20260914/editor-conflict-final/report.json`
- `tests/.artifacts/launch-20260914/editor-six-role-final/report.json`
- `tests/.artifacts/five-account-acceptance/seed-90210.json`

以上目錄保留同一套隔離合成資料的桌機/手機截圖；artifact 為本機證據，不保證納入版本庫。其餘主線測試/發布證據由主線補錄。

## 驗收與發布邊界

- 瀏覽器為真實 Chromium，手機使用 390px 響應式 viewport；未宣稱 iPhone/Android 實機或 Safari/Firefox 已驗收。
- 使用去識別合成帳號、文件與本機隔離資料，不使用正式客戶合約、不建立正式申請、不用真章、不寄送正式公文。
- 不連接正式電子公文交換，不實作或啟用正式 provider；Mock/停用邊界維持。
- 本機 production-branch fixture 使用 SQLite/本機儲存，健康檢核回 503 NO_GO 是預期環境限制；不列為產品錯誤，也不能當作正式環境可上線的證據。
- PDF 遲到回應測試在真實 localhost HTTP 完成後延遲傳回，未替換產品 editor 函式；同一頁的再次登入使用合成 fixture auth，不代表 Google/Portal OAuth 驗收。
- **本機修正與驗收已完成；CI、正式部署及部署後 smoke test 仍待主線核對補錄。** 不以本文件宣稱已推至前台或正式可上線。
