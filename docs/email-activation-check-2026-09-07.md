# Email 啟用查核紀錄 — 2026-09-07

查核時間：2026-09-07 22:33（Asia/Taipei）。範圍僅限目前 Vercel 團隊既有 Resend 整合、資源、連接及官方管理入口；本輪未修改應用程式或正式環境設定。

## 結論

尚不能宣告 Email 通過上線驗收。現有正式環境的寄件地址及 Resend 金鑰格式檢查均未通過；先前固定驗收通知的站內通知成功 2 筆，Email 失敗 2 筆（遮罩碼 `Resend HTTP 400`），沒有服務接受收據，更沒有人工實收確認。

本輪找到既有免費 Resend 安裝，但沒有可供直接重新連接至 eDoc 的已列示資源或 Connect 連接。官方 SSO 管理入口在全新隔離瀏覽器中回覆 `Unauthorized`，需要擁有者先登入 Vercel。不能藉由繞過敏感環境變數保護、另建除錯端點或讀取其他本機憑證來解決。

## 已驗證項目

| 項目 | 實際結果 |
| --- | --- |
| Resend 安裝 | 正式 configuration API 查到既有 `resend` Marketplace 安裝，2026-07 已完成，沒有停用或刪除標記。 |
| 既有安裝帳務 | 現有 `billingPlan` 與 `vendorBillingPlan` 都是 Free、cost `0.00`、installation scope。這不表示目前仍允許新增免費資源。 |
| 可重新連接的資源 | CLI 資源清單及 `/v1/storage/stores` 未列出 Resend 資源；Vercel Connect 以 `--service resend --all-projects` 查得 0 個連接。 |
| Provider 專用資源 API | `/v1/installations/{id}/resources` 回覆 HTTP 403；沒有繞過此權限限制，因此不能據此宣告 provider 帳號內完全沒有任何資料。 |
| 目前新增資源方案 | 帶入既有 installation ID 的正式 billing-plans API 顯示 Free（3,000 封／月、0.00）為 `disabled: true`；可用選項為 Pro US$20／月與 Scale US$90／月。未選購任何方案。 |
| 官方管理入口 | `vercel integration open resend --json` 成功提供既有安裝的 Vercel SSO URL；全新瀏覽器開啟後顯示 `Unauthorized`，尚未進入 Resend Dashboard。 |
| 正式環境憑證狀態 | 前次正式域名的零寫入 dry-run 回報 `senderPresent: true`、`senderFormatValid: false`、`resendKeyFormatValid: false`。Sensitive env 無法合法讀回，未重試解密。 |
| 最新派送狀態 | `email_validation: delivery_failed`；保留既有失敗與站內成功紀錄，不把「已設定」等同於「可寄信」。 |

## 接續流程

1. 登入既有 Vercel 團隊後，從 Resend 整合選擇 **Open in Resend**。這是既有帳號的官方 SSO，不需要重新建立整套系統，也不要選購新方案。
2. 本人確認上述登入完成後，代理可在同一授權 session 接手：確認既有 Resend 帳號可寄送的已驗證網域，建立或重新簽發只供 eDoc 使用、限制寄件網域的 sending-access 金鑰。若帳號另要求認領、驗證或購買方案，仍須停止交由帳號擁有者處理；目前沒有代為認領。
3. 代理在 eDoc 專案的 **Production** 環境變數安全設定 `RESEND_API_KEY` 與 `MAIL_FROM`（合法單一寄件地址或 `名稱 <address>`），不要將金鑰貼到聊天、文件或 Git。不得改用未驗證地址或 Resend 測試寄件者作為正式替代。

已開啟並保留可見的獨立瀏覽器登入視窗（agent-browser session：`edoc-resend-owner`），可見 Google／Vercel 登入畫面，未代填帳號、密碼或驗證碼。擁有者需在這個獨立視窗操作；在一般 Chrome 登入不會自動與它共享登入狀態。尚未確認 Resend SSO 成功。

上述完成後才能安排重新部署、零寫入格式驗證及先前已實作的限定一次驗收重試。該重試只允許原有固定通知、原收件人、原內容及原 idempotency key，不可建立新測試通知來繞過次數限制。若跨日或不符合閘門條件，需重新確認測試授權，不能放寬限制。

## 本輪明確未執行

- 未新增 Resend 資源、Connect 連接、付費方案或其他寄信服務。
- 未變更收件人、寄件人或 API 金鑰。
- 未重寄 Email，未消耗唯一限定重試，未重發站內通知。
- 未啟用 `edoc-production-monitoring-15min` 排程；仍依先前失敗安全條件保持停用。
- 未把 provider 接受收據或站內通知成功當作 Email 人工實收證明。

## 官方參考

- [Vercel integration CLI：官方 SSO 管理入口](https://vercel.com/docs/cli/integration)
- [Vercel：列出 Integration Billing Plans](https://vercel.com/docs/rest-api/integrations/list-integration-billing-plans)
- [Vercel：Get Integration Resources 與權限](https://vercel.com/docs/integrations/create-integration/marketplace-api/reference/vercel/get-integration-resources)
- [Resend Marketplace](https://vercel.com/marketplace/resend)
- [Resend 公開方案](https://resend.com/pricing)（直接註冊方案與目前團隊的 Marketplace 可新增方案不同，不以公開 Free 頁面推定本團隊可無條件新增免費資源。）
