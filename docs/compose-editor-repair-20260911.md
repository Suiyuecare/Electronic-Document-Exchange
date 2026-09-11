# 公文撰寫與電子用印修繕（2026-09-11）

## 交付範圍

- 公文撰寫：不完整表單可私密雲端保存；正式公文內容採版本比對；AI 回覆不覆蓋等待期間手動修改的內容；附件失敗重試不重傳已成功項目。
- 電子用印：版本衝突可保留成新草稿或明確選用最新版本；PDF 上傳／匯入／讀取的非同步回應受帳號、草稿與工作區代次保護。
- 手機提示：儲存／失敗提示顯示在底部導覽上方，避免訊息被遮住。
- 非 A4 PDF：先顯示異常頁碼與尺寸，經確認後由後端等比例置中轉成 A4，不裁切、不拉伸；原檔另存並保留 hash。使用者逐頁預覽後確認採用，取消則保留目前編輯內容。
- 騎縫章：本版採相鄰兩頁一組，批次拆成左右半章並預設錯開高度；每組可各自調整距頁首高度。使用既有已校準的印章版本，不開放一般使用者改尺寸。頁序變更破壞配對時先提醒，復原可還原原組。

## 安全邊界

- 送簽後仍鎖定來源、編輯清單、章位與印章版本；本輪沒有放寬簽核權限或變更 Finance 組織來源。
- 印章原檔不送到瀏覽器；畫面仍使用短效浮水印預覽。
- 騎縫章最終輸出前檢查兩個半章完整、版本一致、尺寸一致、頁面相鄰與章位一致。
- V2 章位保存保留四位小數 PDF point，避免送簽時的舊版二位小數規則破壞騎縫章一致性；沒有放寬竄改檢查容差。
- 非 A4 轉換不繞過掃毒、加密、數位簽章、XFA、JavaScript 或內嵌附件阻擋。
- 新雲端草稿表啟用 RLS，撤銷 anon/authenticated；新 RPC 僅供後端角色使用。
- 正式電子公文交換 provider 維持 Mock／停用；測試均使用去識別化資料。

## 重跑驗證

```sh
python -m unittest discover -s tests -p 'test_*.py'
node --test tests/editor_seam.test.js tests/editor_upload_scope.test.js
python tools/verify_no_embedded_credentials.py
python tools/verify_editor_a4_seam.py
python tools/verify_editor_conflict_browser.py
python tools/verify_compose_resilience_browser.py
```

PostgreSQL 測試需由 `EDOC_COMPOSE_TEST_PG_PORT` 指向隔離的本機 PostgreSQL；不可指向正式資料庫。瀏覽器工具自行建立隔離 SQLite／合成帳號與印章，不會進入正式站送單。

## 本輪驗收結果

- 完整 unittest：785 項收集，775 項通過、10 項環境限定略過，46.259 秒。包含本機 PostgreSQL 新表與 RPC 驗證。
- Node：38 項上傳工作區隔離與騎縫章幾何行為通過（已由 unittest wrapper 納入，勿重複加總）。
- 瀏覽器：公文員工／執行長 × 桌機／手機 4 條流程、56 checks；A4／騎縫章桌機／手機 2 條流程、19 checks；真 HTTP 409 保留新稿桌機／手機 2 條流程，全部通過。
- 三頁、兩組不同高度騎縫章經實際隔離 save → preflight → submit → 逐關檢閱與核准 → 用印 → 下載 → 申請人結案，全程通過；所有簽核關係人可再下載。原稿、prepared PDF、manifest 與 Seal Vault 原 bytes 未變。
- Poppler 全三頁人工目視複核，半章位於配對頁邊、分組高度正確；另有逐頁像素斷言。
- Public／shared 發布檢查補齊新表、欄位、索引與 25 個 RPC；刻意破壞權限、RLS、欄位或索引的負向測試均拒絕。
- JavaScript／Python 語法、credential scanner、shared forward hash 與 diff 檢查通過。

證據保存於此工作樹的 `tests/.artifacts/repair-20260911/`（不納入 Git）；日誌中的 readiness_failed 是刻意製造的負向測試，不是正式站量測。

## 發布注意事項

本文件不是正式上線證明。正式發布前須先套用經驗證的資料庫 migration，再部署同一版前後端，驗證正式站版本與 readiness。

- `20260911133144_compose_resilience_drafts_revision.sql`
- `20260911133603_editor_conflict_copy_atomic.sql`
- 共用 Supabase 採對應的 `20260911135434_shared_compose_editor_resilience.sql` forward migration，避免誤改 Finance 表。

- 已開啟的舊版公文撰寫頁須重新整理，才能傳送新的內容版本欄位；舊頁遭拒絕不代表已存資料遺失。
- 新版產生騎縫章案件後，不可直接回滾至不支援半章 metadata 的舊 backend，否則舊 renderer 可能把半章位置輸出成整章。故障復原應採保留新版騎縫章 renderer 的向前修正版；資料庫備份不是舊 binary 可安全回滾的保證。

本輪瀏覽器驗收涵蓋桌機與 390px 手機版面；不等同 iPhone／Android 實機、正式 Google SSO、正式 Supabase TUS、正式用印或寄送驗收，也不構成 50 MB／300 頁手機效能保證。
