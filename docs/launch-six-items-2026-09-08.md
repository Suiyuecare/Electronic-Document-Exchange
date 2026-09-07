# 1–6 修繕與發布驗證（2026-09-08）

本次不處理印章，不代替真人簽核，也不啟用政府正式電子交換。

## 修繕範圍

| 項目 | 已完成的實作／驗證 | 尚待確認的邊界 |
| --- | --- | --- |
| 1 備份 | 固定主機 runtime、每來源互斥鎖、全程期限、失敗保留上次成功、90 分鐘過期狀態；終端及 launchd 非互動執行均完成正式唯讀備份及本機隔離還原；私密 Drive 新下載 bytes 與 hash 吻合，真正取回後隔離還原成功 | launchd 本次以 kickstart 觸發，非首個整點週期證據；尚無獨立異地金鑰保管、外部備份過期通知；非無人值守雲端 DR |
| 2 六角色 | 六種隔離 Finance 角色，桌機／手機實際操作；正式使用者 Google → Portal → eDoc 修補前及修補後兩次登入成功 | 六位真人分別登入及實際簽核尚未完成；不可把 fixture 當成真人 |
| 3 金鑰 | GitHub secret-scanning 未回傳公開警示；目前追蹤檔案高信心密鑰掃描零發現；CI 新增阻擋私密金鑰 gate，輸出不含值 | 聊天中曾貼出的 OpenAI 金鑰未確認撤銷，Platform 停在本人登入頁；零掃描警示不等於金鑰已撤銷 |
| 4 通知 | 固定驗收通知以 immutable claim/outcome 精確對帳、摘要 CAS 更新、同秒／跨日／併發處理；寄送已完成但摘要失敗不再誤回 generic 500 | 對帳不呼叫寄信、不改派送 ledger；真實人員讀信仍需本人確認 |
| 5 故障 | 系統外獨立 health/ready 探測已在 main 啟用，兩次手動 runner 及 cache 保存／回讀驗證；連續故障／恢復判斷、best-effort 去重；後端 5xx 問題編號、遮罩後 fingerprint 與程式位置 | 真正 cron 觸發與通知實收另驗；平台信件依通知偏好；未連 Sentry／外部長期封存 |
| 6 體驗／速度 | 介面外部字型非阻塞載入、手機 header／側欄關閉鈕 44px、公文 EduKai 範圍保持；三組獨立登入投影查詢並行，保留全部六次檢查及最終原子撤權防護；新增安全分段計時 | 正式未登入 cold/warm 與真人登入分開量測；不可宣稱 0.5 秒完整登入 SLA |

## 本機與來源驗證

- 完整測試（含發布後診斷補強）：575 項，574 通過、1 項環境跳過（29.590 秒）。含持久 PostgreSQL 17 真正 dump/restore 測試；不呼叫正式政府交換。
- 通知相關 targeted：76 項通過；ledger UPDATE/DELETE 權限不變。
- 唯讀來源備份 receipt：`DRILL-20260908-004342-96f72eba`，95 tables、1,184 rows、116 policies、73 秒。
- 上述來源的 private Storage 物件數為 0；不能稱已驗證實際附件還原。
- archive SHA-256：`1d08853c465ab9651d135462a11c404fff20077627a9f19ef070b788e73e1dd2`。
- launchd 非互動成功 receipt：`DRILL-20260908-005440-5ca424bf`，95 tables、1,190 rows、116 policies、73 秒；exit code 0，已設定每小時執行。此資料列差異來自不同時間點的來源快照，非還原遺漏。
- launchd archive SHA-256：`b5c19103a6e210e04e086aaba5f2aa44218a1d1a35995ed621c1050e34aad94b`；上傳前既有異地資料夾驗證為僅 owner、未分享。
- 異地真實下載的 829,476 bytes 與上述 SHA-256 相同；原始 receipt 亦重新下載核對 1,419 bytes 及 SHA-256。實際取回檔經解密及隔離 PostgreSQL 還原，receipt `RESTORE-20260908-010750-6bcc3d49`：95 tables、1,190 rows、116 policies 全部一致。本機原封存未冒充下載檔。
- 檔案與憑證均不放 repo；備份密鑰仍在原有本機私密位置，未複製到備份資料夾。
- 原有 15 分鐘資料庫監控已見兩次真正排程成功，不再列為「尚未跑過」。

## 瀏覽器證據

六角色報告在本機 ignored artifact `tests/.artifacts/six-role-final-20260908/`，使用明確標示的去識別化隔離資料。
正式瀏覽器證據不提交公開 repo，也不記錄 Cookie、Bearer token、Google assertion 或私密公文內容。

匿名正式站修補前：cold 讀取條首顯約 4,883ms、warm 約 120.5ms；兩者最後返回登入入口，authenticated usable 均未測得。
修補後同工具、1440×1000、新匿名 session：cold 305.5ms、warm 84.5ms；兩者仍返回 Portal、authenticated usable=null。此次前兩次工具 open 未完成，經診斷後第三次完整原工具重跑取得數值；不可當穩定 p95，也不把所有差異歸因字型修補。
正式 Google 使用者已成功進入首頁，但該次導航 responseStart 約 11,963ms，不能拿匿名 warm 數字當成真人端到端登入時間。
其中修補前 handoff redirect 約 11,913ms、首頁 HTML TTFB 約 43ms。修補後兩次真實 handoff 分別 5,071ms／5,936ms，導航 DOM complete 約 5,840ms／6,330ms。這是少量同帳號觀察，不是 p95、完整頁面資料載入或 0.5 秒 SLA。
第一輪後端安全分段計時：nonce 745ms、Finance 1,583ms、projection 2,107ms、session 262ms、total 4,697ms。保留即時 Finance 權限、nonce、60 秒重新驗證及 final v2 RPC，不以快取略過撤權。返回模組頁亦正常。

## 發布狀態

- 修繕 commit `5e3a98473d69c1425d786442dbca6db4bdc2ccd0`，PR #3 已合併；main merge `6949817b267c16beb26d51e2f35381557b0a34be`。
- PR CI `34146094404` 與 main CI `34146370867` 全部成功，包含 fresh Supabase、RPC、真實 TUS 上傳及五帳號驗收。
- 正式部署 `dpl_AKmgcPyfUwARyxx8RT9p2FZhZEnZ` 已 READY 並套用正式域名；前台資源版號 `20260908-launch-six-items-r1` 已讀回。
- 候選及正式 health／ready 200；未登入公文 API 401、私密檔案路徑 404。正式通知 dry-run 200、writesPerformed=false，通知／派送／稽核數量不變。
- 外部 monitor 首次手動執行觀察到 ready 200／503／200，正確判為 inconclusive；第二次兩組全 200 判為 healthy。沒有掩蓋短暫異常或宣稱確定根因。
- 印章與政府正式交換仍維持原核准範圍，沒有在本次開啟。

## 發布後診斷補強

第一次外部監測的短暫 503 暴露日誌定位不足，因此補上 `runtime_readiness_failed`：僅失敗時記固定探測名稱、白名單錯誤碼、ready 布林、各項／總耗時與時限。未知錯誤碼一律使用固定 `unknown_probe_failure`。不記原始例外、URL、內容、身份或憑證；不改变公開回應、時限、權限或判定，也不加成功快取或重試。這讓未來可辨認失敗依賴，不代表追溯出先前短暫失敗的確定根因。

相關操作說明：`docs/independent-monitoring.md`、`docs/backup-restore-drill.md`。
