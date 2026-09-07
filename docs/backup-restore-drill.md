# 備份與隔離還原演練

## 本次可執行的流程

`scripts/backup_restore_drill.py` 是維運人員執行的工具，會真正執行 PostgreSQL 還原。
它不在瀏覽器或 Vercel Function 內運作，且不接受任何遠端還原目標。

1. 透過已授權 Supabase CLI 取得短效登入，用唯讀 repeatable-read snapshot 讀取 `edoc`、`edoc_private`。
2. 用 `pg_dump` 備份上述 schema 的資料、函式、約束、索引、RLS 與授權。
3. 只保留外部 `auth.users` 關聯所需 UUID 骨架與 `auth.uid/role/jwt` 函式，不匯出共用人資或 Auth 個人資料。
4. 讀取兩個既有 private bucket，逐檔備份並計算大小及 SHA-256，重讀清冊以排除備份期間變動。
5. 以 AES-256-GCM 加密整份備份，再從加密檔解密驗證。
6. 啟動全新本機 PostgreSQL。禁止 TCP，只允許 `0700` 私密目錄中的 Unix socket；無法指定正式資料庫為目標。
7. 從解密後備份執行 `pg_restore`，逐表核對筆數、完整資料雜湊、RLS、政策與 ACL，任一差異即失敗。
8. 將還原的 Storage bytes 複製到私密隔離目錄，逐檔核對 hash、大小與數量。
9. 關閉並刪除隔離 PostgreSQL 及未加密暫存，只留下加密備份與不含內容的 receipt。

這個流程沒有 JSON sandbox 假還原，也不會覆寫正式資料庫或正式檔案。

## 先備條件

- Python 3.12+ 與 `scripts/backup-restore-requirements.txt` 中的鎖版套件。
- 與來源同版本或更新版本的 `pg_dump`、`pg_restore`、`initdb`、`pg_ctl`。
- Supabase CLI 已登入且 linked project 正確。
- 可讀兩個 private bucket 的 server-side Storage key；可透過已授權 CLI 在 process 內讀取，不將 key 放入命令列或檔案。
- 備份目錄位於 repo 外，權限 `0700`；金鑰檔 `0600`。首次自動建立 32-byte 金鑰，重跑沿用，不覆寫。

## 執行方式

下列變數由維運人員設定；不要將正式 project ref、端點或秘密填入本文件。

```sh
python -m pip install -r scripts/backup-restore-requirements.txt
python scripts/backup_restore_drill.py \
  --pg-bin-dir "$EDOC_PG_BIN_DIR" \
  --source-project-ref "$EDOC_SOURCE_PROJECT_REF" \
  --storage-project-ref "$EDOC_STORAGE_PROJECT_REF" \
  --output-dir "$EDOC_ENCRYPTED_BACKUP_DIR" \
  --encryption-key-file "$EDOC_BACKUP_KEY_FILE"
```

`--source-project-ref` 必須與 CLI linked project 完全一致。
若已有私密且被忽略的 operator env 檔，也可用 `--env-file` 載入 Storage 設定，不使用 `--storage-project-ref`。
Vercel 的 sensitive env 無法 pull；內容為 placeholder 時不得當成有效憑證。
不要同時啟動多個會刷新 Supabase CLI 登入的工作，避免同名登入在 dump 開始前失效。

來源系統無法連線時，可用同一工具完全離線重驗既有備份，不需要 Supabase 或 Storage 憑證：

```sh
python scripts/backup_restore_drill.py \
  --restore-backup "$EDOC_ENCRYPTED_BACKUP_FILE" \
  --pg-bin-dir "$EDOC_PG_BIN_DIR" \
  --source-project-ref "$EDOC_SOURCE_PROJECT_REF" \
  --output-dir "$EDOC_ENCRYPTED_BACKUP_DIR" \
  --encryption-key-file "$EDOC_BACKUP_KEY_FILE"
```

離線演練仍只還原至全新本機隔離環境。若快照已超過 RPO 目標，會完成還原但將時間目標標為未達；不能藉由重跑舊備份宣稱新的即時備份。

## 通過標準

- `ok: true`，且有 `receipt_id`、`receipt_sha256`。
- `target_type: isolated_local_postgresql`、`target_isolated: true`。
- `database.restored/integrity/counts_match/row_hashes_match/permissions_match` 全為 `true`。
- `storage.restored/hash_match/counts_match/private` 全為 `true`。
- `backup.encrypted: true`，receipt 中保留加密檔 hash 與大小。
- `rto_minutes` 不超過設定目標，預設 30 分鐘。
- 來源沒有檔案時，必須明示 `storage.empty_source: true`，不能宣稱完成正式 PDF 或章檔抽樣。

receipt 僅包含 schema 名稱、總表數、總筆數、物件總數、hash、時間與固定錯誤碼。
逐表和逐物件清冊只存在加密備份內。receipt hash 用來驗證完整性，不等同第三方簽章。

## 測試

```sh
EDOC_TEST_PG_BIN="$EDOC_PG_BIN_DIR" python -m unittest tests.test_backup_restore_runner -v
```

涵蓋真正 PostgreSQL dump/restore、RLS/ACL、AES-GCM 往返與竄改拒絕、Storage bytes 還原、空 bucket 明示、金鑰權限和 archive 路徑攻擊。
測試只使用去識別化 fixture，不連正式交換 provider。

## 與系統上還原按鈕的差別

`POST /api/backup/restore-drill` 目前呼叫外部隔離 runner。
未設定 `EDOC_RESTORE_DRILL_ENDPOINT`／`EDOC_RESTORE_DRILL_TOKEN` 時必須回傳 blocked，
不能把本機 receipt 偽裝成線上 runner 成功。

維運人員可先執行上述 CLI 演練。若系統要顯示結果，需透過經管理者驗證的 receipt 匯入功能，保留 target type、範圍與限制。

## 保證範圍與尚需交接項目

- 這是 eDoc 資料與檔案的真實本機隔離還原，不是新 Supabase project 的平台復原測試。
- 共用 HR、完整 Auth、Vault 根金鑰、平台內建 schema、網域與 Google OAuth 設定不在 eDoc 最小備份內，依共用平台備份程序處理。
- private filesystem 還原可驗證 bytes 可恢復，不代表新 Storage API、權限或簽名 URL 已驗收。
- `rpo_minutes` 依來源快照的實際年齡計算，仍不能證明例行排程、異地備份或持續達成 15 分鐘 RPO。
- 加密備份需另存到組織核准的異機位置，金鑰另存公司密碼保管庫。兩者只留同台電腦仍無法應付設備遺失。
- 未完成排程、異地保存與金鑰交接時須保留待辦，不能因一次演練通過而標為全部備援措施完成。

## 官方參考

- [Supabase CLI 備份與還原](https://supabase.com/docs/guides/platform/migrating-within-supabase/backup-restore)
- [Supabase 備份範圍與限制](https://supabase.com/docs/guides/platform/backups)

Supabase 資料庫備份不包含 Storage 物件內容，因此本工具另行處理檔案 bytes。
