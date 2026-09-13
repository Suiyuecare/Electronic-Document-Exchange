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
- 本節為第一批修正提交前的本機驗收快照；正式發布結果見下方補錄。

## 第一批正式發布補錄

- PR #15 已合併，主線版本 `83f9f594ab23c649487cf3398e653277103f9a7e`。
- PR CI `34773840881` 與合併 CI `34774079297` 通過；包含 backend/frontend 與 fresh Supabase/TUS 工作。
- 正式 deployment `dpl_AUS8arVM8MJrN3goXbNRCZRXdJoL` 為 Ready。正式 alias 的 HTML、app、CSS、A4 與騎縫章腳本 SHA-256 與發布檔案一致。
- `/api/healthz`、`/api/readyz` 回 200；5 個受保護 API 的匿名請求回 401，未取得案件或印章資料。
- CI 的獨立 Supabase private Storage/TUS 五帳號流程 5/5 通過。應用資料庫、Finance 與掃毒仍為隔離測試 fixture；不把它當成真實 Finance／正式掃毒服務／實體印章的驗收。
- 正式匿名入口桌機/手機 18 項功能檢查通過，但效能檢查發現主程式下載造成登入探測延後。此結果促成下一節第二補丁，不宣稱全程 0.5 秒達標。
- 證據：`tests/.artifacts/launch-20260914/production-confirmed/production-release.json`、`tests/.artifacts/launch-20260914/production-browser/report.json`、`tests/.artifacts/launch-20260914/ci-tus/latest.json`。

## 第二補丁：匿名入口不再等待大主程式

正式入口追蹤顯示，匿名瀏覽器需要先載入約 1.6 MB `app.js` 才執行 handoff 探測；本輪網路下，桌機/手機該資源分別耗時約 15.845/14.954 秒。這不是 PDF 字型或帳號權限遭拒造成。

修正只將「沒有已知 session／handoff marker／舊 bridge」的同源 HttpOnly 探測前移至 head：

- 只有後端明確回 `401 + handoff_session_missing` 才能提早到相同的安全 Portal 登入目標，不能憑可讀 cookie 不存在就導頁。
- 成功 Response 由主程式取用一次，保留原 JSON 錯誤處理、登入驗證與 503 重試；不在 head 解鎖模組。
- 暫時網路錯誤、403、異常 JSON 不會被改為成功或跳過授權。
- 另一個頁籤在探測期間新增登入 session／bridge 時，不使用遲到的 missing 回應直接導走。
- 新 handoff marker 在探測或接管期間到達時，只有舊回應為明確 missing 401 才重新請後端驗證；成功或其他拒絕不丟棄、不重複取用。head 與 app 同步更新快取版本。

隔離真實瀏覽器驗收刻意把 `app.js` 延遲 8 秒，只把 production hostname guard 與 Portal 目標改到 localhost，其餘使用真實 HTML、head、app 與後端匿名缺 cookie 端點。舊版桌機/手機約 8.087/8.077 秒才發起探測；修正版約 9.21/9.22 ms 發起探測，18.11/24.79 ms 到本機登入頁，兩者皆僅 1 次探測且沒有橫向溢位。**這是依賴關係的 red→green 證據，不是正式網路或 Google SSO 的速度保證。**

- 工具：`tools/verify_entry_early_handoff_browser.py`。
- 舊版證據：`tests/.artifacts/entry-20260914/baseline-confirmed/report.json`。
- 修正版證據：`tests/.artifacts/entry-20260914/candidate-confirmed/report.json`。
- 最後補丁再驗：`tests/.artifacts/entry-20260914/final-browser/report.json`，桌機/手機探測 14.01/9.23 ms、登入頁 19.54/23.88 ms，12 checks 通過。
- 最終完整測試 1,063 項：982 通過、81 條件跳過、零失敗（77.399 秒）；獨立登入回歸 74 項通過，同步快取版本後另跑 30 項全部通過。憑證掃描、Node 語法與 diff 檢查通過。
- 第二補丁 PR #16 與合併後 CI 均通過（`34775266636`、`34775486813`）。正式版本 `07d4b6a3cdc47ff3b515cb7b9b1e8b047137321c`，deployment `dpl_MtAWUPSsVTXdyvNovx2dYMXnnLtP` Ready；6 個前端檔案 hash 一致，健康與匿名授權檢查通過。
- 正式桌機／手機 18/18 入口檢查、4/4 early-probe 順序檢查通過。探測開始 720/317 ms，早於主程式完成 1,622/742 ms，各只有一次 handoff。單次樣本，不作 p95 或固定加速倍數的宣稱。

## 最後窄補丁：晚到的匿名 401 不清除新登入 Cookie

後續獨立複查確認原端點的缺 cookie 401 也會附兩個 `Max-Age=0`。若另一頁籤剛設新 handoff，舊回應晚到時會刪除同 host/name/path 的新 HttpOnly token 與 marker；瀏覽器會先套用 Set-Cookie，僅在 JavaScript 檢查 marker 並不足以避免此問題。這是已存在的登入可靠性問題，不是越權。

最小修正只有後端 5 行：完全缺少／空 token 的 401 使用原有 no-store 回應，不發 Set-Cookie。非空畸形 token、403、失效 session、成功後清除與 503 暫時失敗保留 cookie 的既有行為不變。

新增 `tests/test_handoff_cookie_race.py` 以真實 Handler cookie parser/header builder 與標準 CookieJar 重放晚到回應。另以 `tools/verify_handoff_cookie_race_browser.py` 使用真實 Chromium、HTTP Set-Cookie、實際後端 session 驗證：先延遲缺 cookie 401，再經隔離 HTTP 裝入新 handoff，最後釋放舊回應並驗新 handoff。沒有用 JavaScript 注入 cookie/token、沒有替換登入驗證，也不連正式帳號。

- 舊版本 `07d4b6a` 真實 Handler：桌機／手機皆重現新 cookie 被刪，最後 handoff 401。
- 修正版真實 Chromium／HTTP：桌機／手機 14/14 checks 通過；晚到匿名回應仍 401，但不刪除新 cookie，最後由真實後端驗證新 session 回 200，成功後仍清除 handoff。
- 最終完整套件 1,070 項：989 通過、81 條件跳過、零失敗（76.524 秒）；51 項重點測試通過。Python 編譯、憑證掃描與 diff 檢查通過。
- 證據：`tests/.artifacts/cookie-race-20260914/baseline/report.json`、`tests/.artifacts/cookie-race-20260914/candidate/report.json`。
- 本節為最後補丁驗收中快照；正式發布結果以最終發布報告與 deployment 核對為準。
