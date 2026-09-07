# 上線前非印章改善與驗收

範圍：依使用者「印章先跳過，其餘都改善」辦理。正式政府電子交換仍停用。
正式印章、章檔、尺寸和用印放行條件未變更；不以測試章代替。

## 已修正

- 公司清單：正式啟用 11 家，對應 Finance E1–E11；未綁定 Finance 的舊公司停止開放，歷史關聯保留。
- 同步版本：無版本舊快照不能覆寫新版公司異動或重新啟用舊公司。
- 人員：19 人啟用、12 人待首次 Google 登入、6 人停用，三種狀態分開呈現。
- 管理介面新增「待首次登入」篩選；手機搜尋欄改為完整寬度。
- 上線角色檢核納入執行長。資料齊備不再誤寫為已完成真人登入驗收。
- 人員只在 Finance 維護。舊名冊範本改為同步檢查清單，不引導在 eDoc 另建帳號。
- 通知依即時設定與實際服務回應顯示，修正 Resend 寄件人別名、舊 SMTP 到期日誤判，以及已重送成功仍計為失敗。
- 告警沿用 Email／站內通知，按 Finance 目前啟用的行政部主任及總務精準收件；一般建議不反覆寄送。
- 新監控憑證僅授權指定監控 GET 端點，不能登入、讀公文或呼叫其他排程。
- 寄信設定診斷僅輸出格式布林；上游錯誤僅保留白名單代碼，不保存原始錯誤本文、信箱或金鑰。
- 最新寄信失敗不再被舊的成功紀錄掩蓋。驗收通知禁止一般／批次重送繞過上限，另提供原 ID、原內容、唯一原子 claim 的一次 Email-only 重試。
- 補齊內部收發、異常處理、責任角色及回復交接文件。

## 測試證據及限制

最新本機完整 suite：507 tests，0 failures，2 skipped；備份 PostgreSQL 隔離實測另行完成。
GitHub CI run `34130720456` 對應 `cb8e08c34fc60043757702d1b63258e587d9a92b`，
前後端驗證與 Supabase fresh bootstrap 兩個 job 均為 SUCCESS。
後者包含全新 migration 重建、RPC、RLS、稽核鏈及隔離 Storage 真實 TUS 五帳號驗收。

桌機 1440×1000、手機 390×844 已以隔離資料在真實瀏覽器測試六大入口及待登入篩選，
無頁面 JavaScript 例外、無整頁水平溢出。這是本機瀏覽器驗收，不是正式人員 Google 登入證明。

既有五帳號 HTTP 測試涵蓋一般員工、課長、主任的 A/B/C/D 流程、PDF 編輯、409 衝突、
鎖定與越權拒絕。它使用隔離帳號及測試替身，不得稱為五個真人在正式環境送單。

正式五帳號／PDF 編輯工具已具備測試 session 撤銷、失敗收尾與去識別化輸出。
本次因無可用正式 Google session／可讀取的 Portal 簽章秘密而未執行該完整流程，沒有新增登入例外。
正式站健康檢查和匿名存取拒絕另行驗證。

正式 private Storage 已實際上傳去識別測試物件、以短效網址下載核對 SHA-256，並刪除本次物件。
再次請求明確回覆 `NoSuchKey`，資料庫複查無殘留測試物件。這不等於瀏覽器 TUS 或完整編輯器驗收。

## 真實備份還原

最新版 receipt：`DRILL-20260907-212822-d74a7408`。

- 95 張 eDoc 資料表、1,164 筆資料、116 個 RLS 政策。
- 還原至新建、無 TCP 的本機 PostgreSQL，筆數、完整資料 hash、ACL、RLS 相符。
- 79 秒完成；向上取整 RTO 2 分鐘、快照年齡 2 分鐘。
- 備份採 AES-256-GCM，另以備份完成離線還原驗證。
- Receipt SHA-256：`31daaf4893b6b5ca7d030373151f2f803bb95de6bc44f3205aef22c8f32bdf0a`。
- 兩個私密 bucket 皆無正式物件；不能宣稱已完成正式 PDF／章檔抽樣。

永久加密備份與 receipt 由操作人私密保存，金鑰另置受限目錄，均不在 repo。
這不是 Supabase 雲端平台 DR；外部還原 runner、固定備份排程、異地位置及金鑰交接仍待完成。
異地位置已詢問使用者，不自行建立付費服務或公開分享。

## 仍需真人完成

1. 待啟用同仁以本人公司 Google 帳號首次登入，確認公司、部門及待辦。
2. 六種角色實際操作驗收；已有資料與自動化測試不能取代真人確認。
3. 帳號擁有者先在 eDoc Vercel Production 安全重設有效 `RESEND_API_KEY` 與合法 `MAIL_FROM`，重新部署後驗證；通知服務接受後，行政部主任／總務再確認信箱實收與站內待辦。不要將金鑰貼入對話或 repo。
4. 確認異地備份及上線日主責、備援人與聯絡方式。
5. 正式印章補齊後，另驗收實際用印、申請人收件、歷任簽核人下載。

## 發布與回復

前一個正式部署：`dpl_BKQ15UvCGaFpHoxWCvpyFj43KpkT`。
前端版本標記：`20260907-launch-readiness-r1`。
首批修復部署：`dpl_3Ep7LjQLVmQwqFQjUBHLoHum21FQ`（`cf0096a`）。
最新正式部署：`dpl_BJn6fiWPwSStmtE4cb8AtBb7g6D4`，由已通過 CI 的 `cb8e08c` 建立，
先使用 production env 的 skip-domain 候選部署，再於 CI 成功後 promote。
正式網域已回傳新版 cache tag 及「待首次登入」篩選。
`/api/readyz` 與 `/api/healthz` 皆 HTTP 200；匿名 editor-state 與 monitoring 皆 HTTP 401，
四者皆 `Cache-Control: no-store`。
全新瀏覽器從 eDoc 導向共用 Portal 的 Google 登入，未使用真人帳號或另建 eDoc 登入頁。

監控 dryRun：HTTP 200，`writesPerformed=false`，notifications、deliveries、audit 三表筆數不變。
固定驗收通知僅建立行政部主任及總務各一筆，兩筆站內通知成功，Email 均回覆 `Resend HTTP 400`。
候選環境唯讀診斷進一步確認：`senderPresent=true`，`singleValidAddress=false`、
`senderFormatValid=false`、`resendKeyFormatValid=false`；引號、換行、字面換行及全形括號檢查皆 false。
這是正式 production env 的執行期格式結果，不是由 Vercel 遮罩字串推測。
Vercel 的 eDoc 與官網同名變數均為 sensitive，唯讀 API 無法取得可供重新設定的原值。
已停止：未消耗唯一重試、未更換 provider／收件人，15 分鐘排程保持 inactive；Email 驗收尚未通過。
原有每日 Vercel 排程未變更，MONTEST 驗收通知已排除於一般批次重送之外。

因此本次證明「程式修補已部署、CI／Storage／隔離還原已通過」，不代表所有正式上線驗收完成。
仍待有效寄信設定、真人角色流程驗收、異地備份位置與排班確認；印章依使用者要求排除。

參考：[Resend 寄信 API](https://resend.com/docs/api-reference/emails/send-email)、
[錯誤代碼](https://resend.com/docs/api-reference/errors)、
[冪等重試](https://resend.com/docs/dashboard/emails/idempotency-keys)。
