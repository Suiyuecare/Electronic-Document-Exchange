# 通知通道真實送達測試

## 測試目標

- Email 必須透過已設定的 Resend 或 SMTP 送出，回傳 provider id 或 Message-ID。此回應只證明服務接受，不代表已到達信箱。
- LINE 工作群組可使用 `LINE_WEBHOOK_URL`，或使用 LINE Messaging API 的 `LINE_CHANNEL_ACCESS_TOKEN + LINE_TARGET_ID` push。
- 系統站內通知必須寫入 `system_inbox`，並回傳 inbox id。
- 每次測試都必須寫入 `notification_deliveries`，保留 status、target、receipt、error 與 attempt time。

## 必要環境變數

目前優先沿用 Resend：`RESEND_API_KEY` 與 `MAIL_FROM`（相容 `RESEND_FROM`）。
只在使用 SMTP 或 LINE 時設定下列對應值；LINE 不是內部上線必備通道。

```bash
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=notify@suiyuecare.com
SMTP_PASSWORD=<secret>
SMTP_FROM=notify@suiyuecare.com
SMTP_USE_TLS=true
SMTP_CREDENTIAL_EXPIRES_AT=2026-12-31

LINE_WEBHOOK_URL=https://line-webhook.example.com/suiyuecare-edoc
# 或改用 LINE Messaging API push：
LINE_CHANNEL_ACCESS_TOKEN=<secret>
LINE_TARGET_ID=<group-or-user-id>
LINE_CREDENTIAL_EXPIRES_AT=2026-12-31

APP_SECRET=<secret>
INBOX_SIGNING_KEY_EXPIRES_AT=2026-12-31
```

## API 驗收

```bash
curl -X POST "$EDOC_PUBLIC_BASE_URL/api/notifications/test" \
  -H "Authorization: Bearer $EDOC_ADMIN_SESSION" \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "Email + 系統通知",
    "target_user_id": "<EXISTING_ENABLED_FINANCE_USER_ID>",
    "target_company_id": "<MATCHING_COMPANY_ID>",
    "target_role": "行政部主任",
    "target_email": "<MATCHING_ACCOUNT_EMAIL>",
    "title": "通知通道正式實測",
    "body": "請確認 Email、LINE 與站內通知都已收到。"
  }'
```

通過標準：

- `report.ok` 為 `true`
- `report.success` 等於 `report.total`
- Email `receipt` 為 Resend provider id 或 SMTP Message-ID
- LINE `receipt` 為 request id 或 webhook receipt
- 系統站內通知 `receipt` 為 `INBOX-*`

若 `report.failed` 有資料，先看 `error`，再補正式環境變數或憑證到期日。

收件者需另行確認待簽、退件、完成通知的信箱與站內待辦；不得只憑 `report.ok` 填寫已實收。
`GET /api/notifications/gateway-status` 的 `runtimeReadiness` 分別顯示憑證設定與既有服務接受紀錄。
