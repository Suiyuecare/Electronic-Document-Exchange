# 電子用印送簽必要欄位修復與驗收

## 根因與範圍

簽核關卡 builder 沒有提供 `decision_evidence_json`。正式欄位為
`jsonb NOT NULL DEFAULT '{}'`，但原子 RPC 先以
`jsonb_populate_recordset(null::rowtype, ...)` 建立整列，再整列 INSERT，
使缺少的 key 成為 SQL NULL，而不是套用欄位 DEFAULT。
舊 RPC 因此回滾，將 `23502` 包裝成 `22023 official_submission_invalid_payload`。
這不是要求申請人增加權限或重新上傳 PDF 的問題。

本次只修送簽契約與錯誤恢復；不代替真人送件、不改既有案件、不變更角色、
不啟用正式政府交換，也不修改共享資料庫的 HR public schema。

## 改善

1. Python 兩個關卡 builder 明確提供空物件證據欄位。
2. SQL 關卡 INSERT 改明確欄位清單。舊 payload 缺少該欄位時相容為 `{}`；
   明確 null、陣列、字串、數字等仍拒絕，不放寬完整性條件。
3. 只對送簽 RPC 的精準錯誤契約提供安全機器碼；不回傳 SQL detail 或文件資料。
4. 已確認回滾與結果不明分開處理。結果不明必須先查簽核紀錄，不自動重送。
5. 送簽錯誤持續顯示於既有確認區並保留問題編號、申請內容與 PDF；沿用
   `UX-CONTRACT.md` 的錯誤與恢復元件，不做另外一套介面。

## 本機驗收證據

| 驗收項目 | 結果 |
| --- | --- |
| 舊整列 INSERT 精準重現 `23502`，欄位為 `decision_evidence_json` | 通過 |
| 真 Python builder + 真 PostgreSQL；public/shared、PDF/公文、初送/退回重送 | 通過 |
| 同時重試只建立一代簽核與一筆送簽 audit | 通過 |
| 後段失敗完全回滾；舊版本、錯誤申請人/公司、錯誤證據型別拒絕 | 通過 |
| 新增正式限制回歸 | 16 項通過，已加入 CI 的明確 PostgreSQL gate |
| 送簽、最後版本、跨公司、簽核列表、終止/抽單 PostgreSQL 回歸 | 117 項通過，0 skip |
| Python 全套 | 2,247 項：1,834 通過、413 opt-in skip，0 fail |
| Node 全套 | 290 項通過，0 skip |
| 桌機/手機送簽失敗真瀏覽器 | 4/4 案例通過；真 PDF 上傳、編輯、確認版，最後 POST 故障注入 |
| 瀏覽器保留內容、持續錯誤、單次 POST、返回修改及保存、無水平溢出 | 通過 |
| secret scanner、JS syntax、shared forward hash、diff whitespace | 通過 |

PostgreSQL 首次跨套件執行有 6 個連線錯誤：既有並行測試固定以 postgres
登入，而本機臨時角色為 NOLOGIN。僅在 disposable loopback cluster 啟用該
角色登入後，117 項全數通過；正式角色完全未變更。

證據位於 worktree 外的 `artifacts/submission-fix-release-20261014/`。
瀏覽器是去識別化隔離帳號及 viewport 模擬，不代表真人 Google SSO、實體手機、
正式業務送簽或正式用印全流程已驗收。

嚴格靜態 UI 掃描仍有 409 項既有 heuristic findings；本次未改表單結構或
動作綁定，新增 UI 行未增加同類問題，且失敗恢復另由真瀏覽器驗證。
不宣稱整個系統的靜態 UI audit 通過。

## 發布閘門

歷史狀態：本次修補最初讀回的 main 保護要求兩個 CI checks 與一位
非提交者 review，因此當時未套正式 shared forward，也未 promotion。

2026-10-14，owner 明確同意取消 GitHub 第二人 review，改採單人 owner
核准發布。`docs/release-protection-policy.json` 的
`required_approving_review_count` 因而由 `1` 改為 `0`；仍保留兩項 CI、
`strict=true`、`enforce_admins=true`、禁止 force push／刪除及對話必須解決
等既有保護。這是已核准的政策變更，不是冒用 review 或管理者 bypass。

修補與政策更新仍透過既有 PR #40；依 `docs/deployment-production.md`
核對 owner 核准範圍、遠端保護讀回值與精確 commit 的兩項 CI，只從核准
main 發布。本機政策與本段紀錄不代表遠端設定、正式 migration 或部署
已完成；發布完成須另留下正式驗證證據。

核准後順序：核對備份與回復點 → 只套用 hash-bound shared forward
`20261014031923_shared_atomic_submission_step_evidence_defaults.sql` →
20 項 shared cutover 全過、RPC 權限不變 → 核准 main 的乾淨匯出 staged
build → health/readiness/靜態 hash/匿名拒絕 smoke → promotion 精確 build →
正式 alias 重驗。不得以成功 smoke 取代真人 SSO 送件驗收。
