# 1–6 修繕與發布驗證（2026-09-08）

本次不處理印章，不代替真人簽核，也不啟用政府正式電子交換。

## 修繕範圍

| 項目 | 已完成的實作／驗證 | 尚待確認的邊界 |
| --- | --- | --- |
| 1 備份 | 固定主機 runtime、每來源互斥鎖、全程期限、失敗保留上次成功、90 分鐘過期狀態；終端及 launchd 非互動執行均完成正式唯讀備份及本機隔離還原；新加密封存與 receipt 已上傳既有私密異地資料夾 | launchd 本次以 kickstart 觸發，非首個整點週期證據；雲端原始 bytes 取回及異地解密金鑰保管尚未驗證；非無人值守雲端 DR |
| 2 六角色 | 六種隔離 Finance 角色，桌機／手機實際操作；正式使用者 Google → Portal → eDoc 登入已成功一次 | 六位真人分別登入及實際簽核尚未完成；不可把 fixture 當成真人 |
| 3 金鑰 | GitHub secret-scanning 未回傳公開警示；目前追蹤檔案高信心密鑰掃描零發現；CI 新增阻擋私密金鑰 gate，輸出不含值 | 聊天中曾貼出的 OpenAI 金鑰未確認撤銷，Platform 停在本人登入頁；零掃描警示不等於金鑰已撤銷 |
| 4 通知 | 固定驗收通知以 immutable claim/outcome 精確對帳、摘要 CAS 更新、同秒／跨日／併發處理；寄送已完成但摘要失敗不再誤回 generic 500 | 對帳不呼叫寄信、不改派送 ledger；真實人員讀信仍需本人確認 |
| 5 故障 | 系統外獨立 health/ready 探測、連續故障／恢復判斷、best-effort 去重；後端 5xx 問題編號、遮罩後 fingerprint 與程式位置 | GitHub default-branch workflow 待發布啟用；平台信件依通知偏好；未連 Sentry／外部長期封存 |
| 6 體驗／速度 | 介面外部字型非阻塞載入、手機 header／側欄關閉鈕 44px、公文 EduKai 範圍保持；三組獨立登入投影查詢並行，保留全部六次檢查及最終原子撤權防護；新增安全分段計時 | 正式未登入 cold/warm 與真人登入分開量測；不可宣稱 0.5 秒完整登入 SLA |

## 本機與來源驗證

- 完整測試：567 項，566 通過、1 項環境跳過（28.956 秒）。含持久 PostgreSQL 17 真正 dump/restore 測試；不呼叫正式政府交換。
- 通知相關 targeted：76 項通過；ledger UPDATE/DELETE 權限不變。
- 唯讀來源備份 receipt：`DRILL-20260908-004342-96f72eba`，95 tables、1,184 rows、116 policies、73 秒。
- 上述來源的 private Storage 物件數為 0；不能稱已驗證實際附件還原。
- archive SHA-256：`1d08853c465ab9651d135462a11c404fff20077627a9f19ef070b788e73e1dd2`。
- launchd 非互動成功 receipt：`DRILL-20260908-005440-5ca424bf`，95 tables、1,190 rows、116 policies、73 秒；exit code 0，已設定每小時執行。此資料列差異來自不同時間點的來源快照，非還原遺漏。
- launchd archive SHA-256：`b5c19103a6e210e04e086aaba5f2aa44218a1d1a35995ed621c1050e34aad94b`；上傳前既有異地資料夾驗證為僅 owner、未分享。
- 檔案與憑證均不放 repo；備份密鑰仍在原有本機私密位置，未複製到備份資料夾。
- 原有 15 分鐘資料庫監控已見兩次真正排程成功，不再列為「尚未跑過」。

## 瀏覽器證據

六角色報告在本機 ignored artifact `tests/.artifacts/six-role-final-20260908/`，使用明確標示的去識別化隔離資料。
正式瀏覽器證據不提交公開 repo，也不記錄 Cookie、Bearer token、Google assertion 或私密公文內容。

匿名正式站修補前：cold 讀取條首顯約 4,883ms、warm 約 120.5ms；兩者最後返回登入入口，authenticated usable 均未測得。
正式 Google 使用者已成功進入首頁，但該次導航 responseStart 約 11,963ms，不能拿匿名 warm 數字當成真人端到端登入時間。
其中 handoff redirect 約 11,913ms、首頁 HTML TTFB 約 43ms；本次調整聚焦 handoff 獨立查詢並行，部署後再比較。保留即時 Finance 權限、nonce、60 秒重新驗證及 final v2 RPC，不以快取略過撤權。

## 發布狀態

待本次 commit、CI、候選部署、正式域名驗證後填入；本文件目前不代表已發布。

相關操作說明：`docs/independent-monitoring.md`、`docs/backup-restore-drill.md`。
