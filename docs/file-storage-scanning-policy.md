# 正式檔案儲存與病毒掃描政策

本文件對應 `supabase/migrations/202605230011_formal_file_storage_scanning.sql` 與後端檔案 API，作為附件、PDF、用印版本與歸檔檔案正式上線驗收依據。

## 控制目標

- 使用 private object bucket，不開 public read。
- 所有下載都由後端產生短效 signed URL，預設 300 秒。
- 檔案寫入時保存原文 SHA-256，並記錄加密後 SHA-256。
- 本機/測試環境會做 envelope encryption；正式環境需設定 `EDOC_FILE_ENCRYPTION_KEY`。
- 所有檔案需有防毒掃描狀態，隔離檔案不可下載。
- 下載、阻擋、掃描、隔離、解除隔離都寫入 audit log / file access log。

## 物件儲存

正式 bucket：

| 項目 | 值 |
|---|---|
| Bucket | `edoc-private` |
| Public | `false` |
| Default max size | 100 MB |
| 允許 MIME | PDF、XML、DOCX、XLSX、P7M、octet-stream |

環境變數：

```bash
EDOC_STORAGE_PROVIDER=supabase
EDOC_STORAGE_BUCKET=edoc-private
EDOC_OBJECT_STORAGE_URL=https://<project-ref>.supabase.co/storage/v1
EDOC_STORAGE_ACCESS_MODE=server-signed-url
EDOC_SIGNED_URL_TTL_SECONDS=300
EDOC_FILE_ENCRYPTION_ENABLED=true
EDOC_FILE_ENCRYPTION_KEY=<production-secret>
EDOC_SCAN_ENGINE=ClamAV-compatible
EDOC_AV_PROVIDER=ClamAV daemon / ICAP / AV gateway
EDOC_AV_ENDPOINT=tcp://clamav.internal:3310
EDOC_AV_API_KEY=<av-service-key-if-required>
EDOC_MAX_FILE_SIZE_MB=100
EDOC_ALLOWED_MIME_TYPES=application/pdf,application/xml,text/xml,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/pkcs7-mime,application/octet-stream
```

## 後端 API

| API | 用途 |
|---|---|
| `GET /api/files/storage-health` | 查看 provider、bucket、加密、掃描與 token 狀態 |
| `POST /api/files/upload` | 上傳檔案內容，建立 `file_objects`，立即掃描並回傳短效 URL |
| `POST /api/files/{id}/signed-url` | 產生短效下載 URL |
| `GET /api/files/{id}/download?token=...` | 驗證 token、掃描狀態、解密後下載 |
| `POST /api/files/{id}/scan` | 執行防毒掃描並建立 `virus_scan_jobs` |

## 防毒掃描

正式環境必須設定獨立 AV 服務，不得只靠畫面或本機模擬檢查。`/api/files/storage-health` 會檢查：

- `EDOC_AV_PROVIDER`
- `EDOC_AV_ENDPOINT`
- `EDOC_AV_API_KEY`，若採內網 `tcp://` / `clamd://` 可視為內網連線憑證
- `EDOC_SCAN_ENGINE`

Production 若未完整設定，`/api/production/readiness` 與 `/api/production/monitoring` 會回報 `STORAGE-SERVICE-INCOMPLETE`，`POST /api/files/upload` 與 `POST /api/files/{id}/scan` 也會回傳 `formal_storage_av_not_ready`，避免未掃描檔案進入交換。

掃描結果：

- `待掃描`：尚未進入掃描任務
- `已通過`：可進入封裝、押章、下載
- `已隔離`：不可下載、不可封裝、不可交換

測試資料可使用 EICAR 字串驗證隔離邏輯。

## Signed URL

下載 token 會寫入 `file_download_tokens`：

- `token_hash`
- `expires_at`
- `used_at`
- `revoked_at`
- `actor`

正式環境不得直接暴露 storage key 或 permanent URL。

## 驗收 SQL

```sql
select id, public
from storage.buckets
where id = 'edoc-private';

select id, file_name, encryption_status, scan_status, signed_url_expires_at
from public.file_objects
order by created_at desc
limit 20;

select id, engine, result, signature, finished_at
from public.virus_scan_jobs
order by created_at desc
limit 20;

select id, file_object_id, expires_at, used_at, revoked_at
from public.file_download_tokens
order by created_at desc
limit 20;
```

## 上線注意

- `edoc-private` bucket 必須保持 private。
- 前端不可使用 service role key。
- 上傳、掃描、signed URL 產生都應由後端或 Edge Function 執行。
- 隔離檔案解除需主管角色確認，且必須留下 file access log。
