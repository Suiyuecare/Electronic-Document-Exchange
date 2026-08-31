# 備份還原演練

## 目的

正式營運前與每月例行維運時，需證明備份可用、可還原、資料筆數一致，且符合 RTO / RPO 目標。

## API

```bash
curl -X POST https://edoc.suiyuecare.com/api/backup/restore-drill \
  -H "Authorization: Bearer $EDOC_OPERATOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "scope": "全部資料表",
    "target_env": "測試沙盒",
    "rto_target_minutes": 30,
    "rpo_target_minutes": 15
  }'
```

此 API 只允許具有「系統管理」權限的登入者執行；一般員工與未登入請求必須分別
回傳 403／401。`EDOC_OPERATOR_TOKEN` 是短效 session，不得保存於文件、repo 或 log。

## 本機 / SQLite 演練

1. 建立 SQLite 備份檔。
2. 計算備份 SHA-256。
3. 複製備份到 `restore-sandbox-*`。
4. 對沙盒執行 `PRAGMA integrity_check`。
5. 比對來源與還原後資料表筆數。
6. 比對來源備份與還原沙盒 SHA-256。
7. 計算 RTO / RPO 並寫入 audit log。

## Supabase 正式演練

Vercel serverless 不應直接還原正式資料庫，因此正式環境採 logical snapshot 演練：

1. 依演練範圍讀取 Supabase 資料表。
2. 產生 logical snapshot SHA-256。
3. 還原至 JSON sandbox。
4. 比對筆數與雜湊。
5. 寫入 `audit_logs`。

正式上線後仍需搭配 Supabase PITR、scheduled dump 或管理後台備份，定期在測試 project 執行真正資料庫還原。

## 通過標準

- `ok: true`
- `result: 通過`
- `checks.integrity: true`
- `checks.hash_match: true`
- `checks.counts_match: true`
- RTO / RPO 皆小於或等於目標

若不通過，依 `improvements` 列出的改善項目處理。
