# 分階段發布：第一階段

使用者同意先發布通過隔離驗收的修繕，離職交接與關聯新案等本人驗收後再開放。
政府正式電子公文交換仍停用，不在本次發布範圍。

## 發布邊界

- 基準是正式版本 `e5cece10b45ca8817e97b49e21d0380f44c56f14`。
- 修復電子用印文件類型變更未納入申請資訊自動保存；未選類型時保留輸入，不送出無效背景請求。
- 共用動作按鈕至少 44px，保留 Finance 的側欄、配色、字體與既有較大導覽按鈕。
- CI 增加實際 PostgreSQL 配號／還原與 Node 測試；不得把 opt-in skip 計作通過。
- privileged signed-identity probe 預設在讀 secret 或帳號前拒絕；不替代真人 Google SSO。
- 不帶入 PR #37 的交接 UI、後端 API、責任鏈、關聯新案及任何 migration。
  此為整包不發布，不是僅隱藏按鈕；`test_phase1_release_boundary.py` 防止誤合併。
- 正式 backend、Supabase schema／RLS／ACL 與業務資料不變；不修改真人角色，不停用真人帳號，不寄發測試公文。

## 驗收指標

1. 更換用印文件類型後，自動保存並從授權 detail 讀回同一類型；舊版本 409 不自動覆蓋，403 不重試。
2. 無類型時不送 PATCH，保留輸入；重新選類型後可保存。
3. 電腦／手機六頁動作尺寸達標、無整頁溢出；原側欄與配色不變，Tab／Escape 與 reduced motion 回歸。
4. 全部可用本機測試與 CI 通過，PostgreSQL／Storage TUS 的真實隔離結果分層紀錄。
5. 正式環境 staged build 先不綁正式 alias；來源提交、靜態 hash、health、內部 readyz、匿名拒絕均確認後才 promotion。
6. 正式站不得包含交接控制器或關聯新案按鈕，相關未發布靜態資源為 404。

## 證據與剩餘門檻

本次實測報告放在 Git 忽略的 `tests/.artifacts/phase1-release-20261007/`。
隔離 fixture／loopback Storage 不證明真人 SSO、正式業務全流程或實體手機弱網已通過。
不得宣稱所有 PDF 2 秒或工作區資料全部 0.5 秒完成；本機可編輯與雲端保存分開量測。

第二階段仍需五角色本人及額外一名一般員工的 SSO／正式去識別案件驗收、
最新備份、正確 shared forward 的 schema／ACL 檢核與人工核准。
原交接候選保留於 PR #37 draft；本次不將 PENDING 改寫為 PASS。

## 第一階段本機回歸結果

- Python discover：1,574 項，1,564 通過、10 opt-in skip；skip 不計為通過。
- 另行執行真實隔離 PostgreSQL 配號 7 項、備份還原 2 項，均通過且無 skip。
- Node：160 項通過，0 fail／skip。
- 六角色 browser：108 個頁面情境、99 張截圖、18 組編輯保存／類型後端讀回／跨公司 403／舊版本 409 通過，0 整頁溢出。
- fluid browser：桌機／手機 12 頁通過；改前 6 個桌機 action-hit-area 失敗，改後為 0。
- Design token lint：0 error、7 warning；secret scanner 無發現，diff／JS syntax 通過。
- 嚴格静態 UI 掃描仍有既有 event delegation／form markup 的 481 項待判讀（404 actionless-button、49 novalidate、28 textarea resize）；本次新增行沒有掃描發現，不宣稱整套 UI 已無缺點。動作行為另由真實瀏覽器回歸驗證。
- Hosted TUS 與 CI 的真實隔離結果、正式 staged／promotion 結果須在發布操作中另確認；本機 fixture 不替代該證據。

## 回退

發布前正式 deployment 為 `dpl_Btv5q25drFvf1vPqhpTiP6y5dTVD`。
本階段沒有新 schema 或交接寫入，必要時回退 deployment，不回復舊備份覆蓋正式業務資料。
