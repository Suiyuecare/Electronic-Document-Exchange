# 獨立可用性監控與錯誤追蹤

狀態（2026-09-08）：已發布至 main，正式域名可用後已啟用 enable variable。兩次真正 GitHub runner 手動執行及 cache 保存／回讀已驗證；schedule 觸發與人員通知實收仍需分別核實，不能用手動執行代替。

## 監控範圍

`.github/workflows/availability.yml` 使用 GitHub Actions runner，獨立於 eDoc 程序及 Supabase 排程。它只讀取 `/api/healthz` 與 `/api/readyz`，不登入、不讀取公文、不寫入資料庫、不呼叫寄信 API，也不持有應用程式或資料庫金鑰。

目前排程為每小時第 7、22、37、52 分鐘。每輪最多三組檢查，每個 HTTP 請求上限 8 秒、回應最多讀取 4,097 bytes；拒絕重新導向，不記錄網址及回應本文。

| 觀察結果 | 行為 |
| --- | --- |
| 連續兩組正常 | 判定正常；原有故障才記錄恢復事件 |
| 連續兩組失敗 | 判定故障；新故障才讓 job 失敗以觸發既有通知機制 |
| 正常／失敗交錯 | 判定尚無定論，保留既有狀態，不新增故障或恢復通知 |
| runner、設定或狀態保存失敗 | 明確回報監控器故障，不冒稱網站正常 |

## 部署與啟用檢核

1. 由負責發布的主工作完成程式審查與測試，依既有流程將 workflow 與腳本發布到儲存庫的 **default branch**。不要只部署 Vercel 或只推送功能分支便宣布排程已啟用。
2. 在該儲存庫的 Settings → Secrets and variables → Actions 設定 repository secret `EDOC_MONITOR_BASE_URL`。值由有權限的管理者直接輸入：僅 HTTPS origin，不含帳密、額外路徑、query、fragment 或非標準連接埠；不要把值寫進 repo、截圖或執行紀錄。
3. 先確認正式版本的兩個探測端點可用，再把 repository variable `EDOC_INDEPENDENT_MONITOR_ENABLED` 設為字串 `true`。尚未設定或其他值都不執行 probe job。
4. 在 Actions 手動執行 `eDoc independent availability`，使用 default branch。確認 probe、cache save 均成功；再執行一次確認 cache restore 可讀到前次狀態。手動執行成功仍不等於 schedule 已驗證。
5. 等候至少一次真正的 scheduled run，記錄 run ID、commit SHA、觸發方式、執行時間與結果；不記錄正式網址或帳號。GitHub 排程只使用 default branch，負載高時可能延遲或丟棄；公開 repo 長期無活動也可能自動停用。因此這不是具有準時保證的 15 分鐘 SLA。[GitHub 排程限制](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
6. 由通知負責人確認自己的 GitHub Actions 通知偏好及收件管道。不可為了驗收製造正式服務故障；故障／恢復去重使用隔離測試驗證，真實收信另記錄驗收結果。
7. 完成上述證據後，才更新本文件的啟用狀態。若尚欠排程或收信證據，明確保留待驗證項目。

要暫停此獨立監控，把 enable variable 改為 `false`；若需要停止已在執行的 run，由管理者在 Actions 取消。這不會停用 eDoc 既有的應用程式內監控或改動其他系統排程。

## 去重與通知限制

- 去重狀態放在 Actions cache，只含狀態、時間、版本與事件布林值，不含網址、HTTP 本文、帳號或金鑰。cache 不是私密資料庫，也不是持久稽核庫；不要把任何敏感資料加入其中。[GitHub cache 安全](https://docs.github.com/en/actions/concepts/workflows-and-actions/dependency-caching#cache-security)
- 去重是 **best effort**：cache 被清除、失效、還原／保存失敗，或超過 48 小時未更新時，可能把仍存在的故障視為新事件。第一次執行沒有 cache 是正常情況；之後持續缺失應查核，不能保證永不重複提醒。
- 已知故障持續時，job 可以成功結束，但 JSON 的 `status` 仍是 `outage`。綠色勾號表示這輪沒有新增需通知的事件，不等於服務已恢復；查看 `status`、`observation` 與探測結果。
- `EDOC_MONITOR_RUNNER_FAILED` 是監控器本身失敗，可能每輪再次使 job 失敗；它不受網站故障去重保證。應修復缺漏設定或 runner/cache 問題，必要時暫停後修復，不要只忽略信件。
- GitHub 郵件由平台通知偏好決定。排程通知與最後修改 cron 的使用者有關，不會自動套用 Finance 的行政主任／總務收件人，也不能由一次 job 失敗推定有人收到信。[GitHub 排程通知對象](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#actor-for-scheduled-workflows)、[GitHub 通知設定](https://docs.github.com/en/subscriptions-and-notifications/get-started/configuring-notifications)
- 恢復只輸出 `EDOC_AVAILABILITY_RECOVERED` notice 與狀態；是否有平台信件仍依 GitHub 設定，不能保證另寄恢復信。本流程不新增郵件服務或付費監控方案。

## 執行期 errorId 查詢

`runtime_observability.py` 在後端 JSON 5xx 回應附上 `errorId`，同時提供 `X-EDOC-Error-ID` header。使用者只需提供此編號與大約時間，不應貼上公文本文、附件、Cookie、Bearer token 或私人聯絡資料。

維運人員在對應正式 deployment 的 Vercel Runtime Logs 搜尋該 `ERR-` 編號，核對安全欄位：route 群組、HTTP method/status、錯誤分類、程式檔名／行號及 fingerprint。相同 fingerprint 可用來比對重複故障；每次事件仍有獨立編號。找不到時先核對 deployment、時區及平台保留期間，不推論錯誤從未發生。

日誌刻意不收錄例外原文、request body/header、動態公文 ID、SQL 值或本機變數。這是結構化執行期日誌，不代表已接入 Sentry、外部 log drain 或長期封存；平台無法啟動程序、非 JSON 回應等情況也不保證有應用層 errorId。

依賴探測失敗另產生 `runtime_readiness_failed` 事件，提供固定探測名稱、白名單錯誤碼、各項／總耗時及設定時限。未知碼統一為 `unknown_probe_failure`；成功探測不另產生事件，logger 本身失敗不影響 readiness。此事件不改變 1.5 秒預設探測時限、公開明細隱藏或安全判定。

## 本版驗證證據

- 單元測試覆蓋連續失敗、連續恢復、兩種交錯結果、過期／未來 cache、HTTPS 限制、禁止重新導向、回應遮罩與私密狀態檔。
- 錯誤追蹤測試覆蓋敏感原文排除、動態路徑排除、fingerprint／事件 ID 及日誌寫入失敗不影響回應。
- 已發布 main commit：`6949817b267c16beb26d51e2f35381557b0a34be`。
- 手動 run `34146467078`：首次 cache 不存在後成功保存；health 全 200，ready 200／503／200，正確保留 unknown／inconclusive，沒有將綠色 workflow 結果誤當網站健康。
- 手動 run `34146544888`：成功回讀前次 cache，兩組 health／ready 全 200，判定 healthy 並保存新狀態。
- 該次短暫 503 已產生遮罩後 runtime 事件；現有資訊不足以認定是哪個依賴故障，因此不放寬探測時限，也不宣稱根因已確定。
- 真正的 default-branch scheduled run 與 GitHub 人員通知實收：仍待獨立證據；未故意製造正式故障或重寄既有通知。
