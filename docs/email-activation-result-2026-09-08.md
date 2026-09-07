# Email 啟用與重試修復結果 — 2026-09-08

本次接續使用者完成的既有 Resend 管理登入。範圍為 Email、相關稽核修復及已建立的監控排程；
未變更印章、正式政府交換 provider、公司／人員權限或其他模組。

## 已完成

- 在既有免費 Resend 團隊確認公司寄件網域已驗證；未新增付費方案或修改 DNS。
- 建立 eDoc 專用、限制公司寄件網域的 Sending access 金鑰；保留其他既有金鑰。
- 金鑰僅由登入管理頁透過程序記憶體與 stdin 寫入 eDoc Production 的 sensitive 環境變數。
  同步修正 `MAIL_FROM`；未將金鑰寫入 repo、聊天、前端、剪貼簿或本機檔案。
- 候選與正式環境的寄件地址／金鑰格式診斷均通過，零寫入 dry-run 三表筆數不變。
- 原兩筆驗收通知都已有真實 provider receipt；Resend 管理頁均顯示 `Delivered`。
  沒有新增測試通知、改收件人、重發站內通知或為同一人第三次寄信。

## 發現並修正的回寫問題

第一封 Email 成功送出後，舊程式試圖 PATCH `notification_deliveries`，回覆 HTTP 500。
正式 `edoc_backend` 對此表只有 SELECT／INSERT，沒有 UPDATE；這是程式與追加式稽核權限不相容，
不是需要放寬資料庫權限。

修正採「不可變 claim＋不可變 outcome」：

- 固定 `NDEL-MONRETRY-` claim 在寄信前先提交，任何不確定結果都不得再次寄送。
- 固定 `NDEL-MONRESULT-` 結果以 INSERT 追加；`attempt_count=0`，不當成額外寄送次數。
- 同秒紀錄優先讀 outcome；收據先持久化，即使通知摘要更新失敗也不會第三次寄送。
- 重複結果只有內容完全一致才可讀回確認；矛盾或無法確認皆安全失敗。
- 未新增 UPDATE／DELETE grants，原始失敗、claim 與結果均保留。

第一封處理方式為對帳，不是重寄。已從 Resend 原始 POST 紀錄核對 HTTP 200、
原收件人、主旨、內容、模組標記及 claim 後約 1.3 秒的寄送時間，才使用
`edoc_backend` 在短交易內追加結果、更新指定通知摘要並寫入 ID／hash 稽核。
第二封在修正版正式部署後完成原本尚未消耗的唯一重試；API 回覆 HTTP 201、
`attempted=1`，第一封明確 `skipped`。

| 原通知 | 郵件服務收據 | 結果 |
| --- | --- | --- |
| `NTF-MONTEST-56543988BDC2BC142B36F5CD6D82719C` | `c3321c82-36e0-44f0-9d8f-37d351f45517` | Delivered；核對後補回收據，沒有重寄 |
| `NTF-MONTEST-0FDFED1C895126997875056E28D56FA3` | `64ecd6b7-647f-4533-be7f-6a531c186614` | Delivered；修正版自行保存收據 |

第一封對帳稽核：`AUD-MONRECON-95C811184E9AFEBA8CDB9C391E567AF7`。
原 provider request hash：`199addf818216788544100ca9f3a2d5ed09d8861637e0acfe647a6d338375549`。
稽核不保存郵件本文、收件信箱或秘密。API 的 `humanReceiptConfirmed` 保持 false；
`Delivered` 仍不等於收件者已閱讀或完成真人驗收。

## 測試與發布證據

- 修補 commit：`1e19c8db775ed4175985d97b9f800d3efe5c171c`。
- 本機完整測試：513 項，0 失敗，2 項既有 skip；凍結後重跑結果相同。
- 針對性測試 67 項通過；另一代理獨立執行通知測試 38 項通過。
- Python compile、前端 JavaScript syntax、`git diff --check` 通過。
- GitHub CI `34140994621`：前後端與 Supabase fresh bootstrap 兩個 job 均 SUCCESS，
  包含 migration／權限／稽核鏈、隔離 TUS 與五帳號測試。
- 正式部署：`dpl_73VR9VjuD7xEy6b6QGec4cW7DBpy`，先以 production env 建立候選，
  CI 成功後 promote；未跳過驗證直接切換。
- 正式 `/api/readyz` HTTP 200；匿名監控端點 HTTP 401。
- 候選首次 readyz 曾出現一次 HTTP 503，其後兩次候選及正式檢查回覆 ready；
  未將單次恢復解讀為已證明所有冷啟動／長期可用性。
- 正式 dry-run 最新 `email_validation=provider_accepted`，`NOTIFICATION-FAILED` 已消除；
  僅剩不對外寄信的 `READINESS-WARNING` 建議。

## 15 分鐘監控

既有 `edoc-production-monitoring-15min`（job 1）已啟用，`*/15 * * * *`。
啟用前驗證兩筆收據及摘要，並實際呼叫相同的私密同步傳輸函式，回覆 HTTP 201；
notifications／deliveries 筆數不變，未重寄驗收信。其餘 jobs、Vault secrets 與角色權限未修改。
這證明設定啟用與同一路徑手動執行成功；本文發布時尚未將首個定時排程 run 列為通過。

## 未完成的上線門檻

1. 行政部主任與總務確認測試 Email 實際可見，以及系統站內通知。
2. 各正式角色本人 Google 登入及簽核操作驗收；Resend 管理登入不能替代此項。
3. 異地備份取回 bytes hash／還原、固定備份排程、異機金鑰保管與值班交接。
4. 印章依使用者要求排除；正式政府交換仍停用。

本次已完成寄信設定、回寫程式修復、正式發布與監控啟用，不宣稱全部上線門檻通過。
前版回復候選 `dpl_8iqJbQgPdk1bLBvfgCQTZguZU2Sr` 保留有效寄信設定，但包含已知重試回寫問題；
若必須回復，不得再次呼叫驗收重試，亦不得刪除已追加的結果與 claim。
