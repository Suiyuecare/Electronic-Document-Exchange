# 通知通道真實送達測試

## 測試目標

- Email 必須透過正式 SMTP 或交易郵件服務送出，回傳 Message-ID。
- LINE 工作群組可使用 `LINE_WEBHOOK_URL`，或使用 LINE Messaging API 的 `LINE_CHANNEL_ACCESS_TOKEN + LINE_TARGET_ID` push。
- 系統站內通知必須寫入 `system_inbox`，並回傳 inbox id。
- 每次測試都必須寫入 `notification_deliveries`，保留 status、target、receipt、error 與 attempt time。

## 必要環境變數

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
curl -X POST https://edoc.suiyuecare.com/api/notifications/test \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "Email + Line + 系統通知",
    "target_role": "行政部主任",
    "target_email": "records@suiyuecare.com",
    "title": "通知通道正式實測",
    "body": "請確認 Email、LINE 與站內通知都已收到。"
  }'
```

通過標準：

- `report.ok` 為 `true`
- `report.success` 等於 `report.total`
- Email `receipt` 為 Message-ID
- LINE `receipt` 為 request id 或 webhook receipt
- 系統站內通知 `receipt` 為 `INBOX-*`

若 `report.failed` 有資料，先看 `error`，再補正式環境變數或憑證到期日。
