# 電子用印版本與編輯競態驗收

## 範圍

修正電子用印的五項競態；不變更印章、公司授權、簽核規則或正式案件。
測試使用 localhost、暫存 SQLite／PostgreSQL 與合成帳號、PDF、印章。
不連正式電子公文交換環境。

## 問題與驗收標準

| 問題 | 驗收標準 |
| --- | --- |
| 同一編輯版本產生兩份確認 PDF，送簽鎖定第一份但檢閱取得第二份 | 本機與 Supabase state、主管下載連結使用送簽鎖定的 file ID／SHA；鎖定證據缺失時阻擋，不退回最新版。下載原稿與鎖定版後可正常核准。 |
| 舊分頁申請資料覆蓋新分頁 | PATCH 與送簽帶入用戶端 content revision；後端以該版本做原子 CAS。舊版本得到 409，保留原輸入與先成功的資料。 |
| 拖曳時收到前次保存回應，位置跳回 | 活躍手勢的座標不被舊回應覆蓋；放開、保存、重開位置相同。 |
| 拖曳後第二指縮放，未記錄修改 | 切入縮放前完成拖曳、記錄復原歷史並排程保存；其他 pointer 不能終止該手勢。 |
| 切案等待時新修改遺失，或新案下載失敗清空舊案 | 新案資料與 PDF 先載入驗證；等待中若原案有新修改或手勢，停止切換並保留原案。下載／解析失敗也不清空原案。 |

## 回歸入口

- `tests/test_editor_revision_races.py`：本機與 Supabase 路徑、鎖定 ID／SHA／URL、缺失證據、申請資料 CAS。
- `tests/editor_correctness.test.js`：保存／手勢／切案競態，透過既有 Python wrapper 納入 CI。
- `tests/test_editor_application_autosave.py`：用戶端版本游標與衝突輸入保留。
- `tools/editor_race_browser_acceptance.py`：真實頁面與 localhost HTTP 的五個競態；`--app-ref 41ff86f` 可供舊前端比較。
- 既有五帳號 HTTP、一般文件大小章／騎縫章、可設定簽核與隔離 PostgreSQL RPC 驗收保持啟用。

## 發布門檻

1. Python 編譯、JavaScript 語法、憑證掃描、完整回歸與隔離資料庫測試通過。
2. 桌面與窄螢幕瀏覽器驗收通過；真實 iPhone／Safari 不宣稱已驗收。
3. GitHub CI（含全新 Supabase／Storage TUS）通過後發布主分支。
4. 正式站 health／ready、匿名授權防護、快取版本與資源雜湊核對。
5. 正式交換 provider 保持未啟用；Vercel 回滾不代表資料庫回滾。

## 瀏覽器驗收結果

- 五項競態共 34 個 checks 通過，包含主管從簽核決定畫面實際下載鎖定 PDF（HTTP 200），沒有下載另一份未送簽的確認 PDF。
- 六種合成角色（員工、主管、部門主任、行政部門主任、總務、執行長）在電腦／平板／手機尺寸共 18 組上傳、文字編輯、保存與重讀通過；過期保存回傳 409、跨公司未授權讀取回傳 403，沒有頁面溢出或 JavaScript 錯誤。
- 拖曳、切入縮放、延遲切案保留了可見修改；縮放使用 Chromium 原生觸控輸入模擬，不代表實體 iPhone／Safari 已驗收。
- 可重跑證據位於 `tests/.artifacts/editor-races-20260927/` 與 `tests/.artifacts/editor-race-six-role-20260927/`；內容皆為合成資料，不提交個資或正式印章。
