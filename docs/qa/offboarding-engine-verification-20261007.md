# 人員異動交接：候選版本驗證

狀態：候選程式，未發布；不得據此宣告全員可正式使用。
隔離分支：`codex/offboarding-handover-20261007`。
原始髒工作目錄未修改；未變更正式員工、角色或離職狀態。

## 已實作

- 簽核紀錄頁的離職交接清單、提案、確認、退回與歷程。
- 總務提出、另一位行政部門主任確認；不能自批或交接自身案件。
- 確認當下重查有效 Finance 人員、公司、租戶、職級與案件版本。
- 未確認不改簽核人；確認後待簽關卡須重新審閱精確版本文件。
- 已完成簽核保留原實際行為人、主體及證據，不改成接任人。
- 離職申請人的追蹤責任與原申請人分開；接任人可依權限讀檔、收件並接收通知。
- 補正採「關聯新案、原案保留」：重新選文件類型、上傳文件、編輯及完整送簽，不複製舊章或審核。
- 接任人再次離職可重新提案；確認前不授權，確認後保存整條前任／後任歷程。
- 同操作重試不重複建案或確認；版本、資格變更與越權採拒絕處理。
- 前台接任待辦分類修正，以及文件類型變更保存與未選類型不送無效背景請求。

## 程式回歸結果

交接引擎完整執行紀錄（本輪前五項追加驗收另見 `readiness-1-5-20261007.md`）：

```sh
EDOC_COMPOSE_TEST_PG_PORT=55436 python -m unittest discover -s tests -q
python -m tools.offboarding_handover_shared_forward --check
node --check app.js
node --check official-handover-ui.js
git diff --check
```

共 1,651 項：1,641 通過、10 跳過、0 失敗／錯誤，123.164 秒。
跳過項不是通過；本機隔離 PostgreSQL public 與共享 edoc namespace 交易均實際執行。
新交接 RPC、私有責任證明 helper、瀏覽器與服務角色 ACL 亦有驗證。
forward 產生檔一致性、JavaScript 語法及差異空白檢查通過。
日誌位於忽略的 `tests/.artifacts/offboarding-handover-20261007/`，不提交執行紀錄。

## 瀏覽器及閉環

`python tools/offboarding_handover_browser_acceptance.py` 僅連線 loopback 與暫存資料庫。
驗證桌機、平板、手機的提案、主任確認、關聯新案及重新上傳／編輯／保存回讀。
新案續測透過真實隔離 HTTP API，重新完整簽核、下載用印 PDF 與收件結案。
每關未重新讀檔先核准必須被拒絕；原案保持不變。
測試印章、PDF、身分與組織資料均為合成資料，不連正式交換、寄信或停用在職人員。
基礎 reviewer fixture 未提供申請人組織關係，續測補入合成組織圖，而非繞過正式 Finance 檢查。
最後成功執行 15 條：12 條瀏覽器流程與 3 條關聯新案 HTTP 完整簽核／用印／收件閉環，`passed=true`。
每台裝置驗證新案重新簽核 2 關；未重新下載完整文件的核准請求均被拒絕。
局部交接控件觸控尺寸、文字輸入大小、溢位與瀏覽器例外均通過；既有其他控件發現保留在報告。
結果保存於 `report.json`；早期失敗紀錄保留除錯用途，不算成通過。

依 UI skill 使用 Finance 既有控件與共用 modal：焦點／Escape／背景 inert、欄位錯誤及行動觸控尺寸。
已目視桌機交接紀錄與手機 PDF 編輯；局部功能無橫向溢位。
strict UI 靜態稽核尚非全專案乾淨：1,455 項包含既有頁面、測試與 `.vercel/output`。
新 UI 的 4 項工具發現逐項核對：native select 權責記於 UX-CONTRACT、委派 click handler 在瀏覽器實行、textarea 由樣式表設定 resize:none。
不為通過掃描而加入 inline onclick、放寬 CSP 或聲稱全專案 UI 已全數通過。

## 本人 SSO 與發布前門檻

五角色本人 SSO 全部 PENDING，詳見 `human-sso-acceptance-20261007.md`。
先前只讀資料預檢顯示指定人員的有效帳號與模組連結，但本次未重新核對正式資料；不能代替本人登入。
指定員工驗收者的實際角色為主管，可驗申請人流程，不能代表一般員工最低權限。
已請使用者另指定一般員工；不得修改人員角色來讓驗收通過。

仍須本人 Finance/APM→EDOC 新分頁 SSO、各角色實際操作與遮罩證據，人工確認、CI 及部署前備份／migration 檢查。
本次以隔離分支提交候選程式並走 PR／CI，未提升正式 alias、未套用正式 Supabase migration；正式站沒有本次候選功能。
未取得機關 provider 規格與核准前，正式電子公文交換仍不得啟用。
