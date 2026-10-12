# 候選資料庫變更

此目錄不屬於 `supabase/migrations` 或 `shared-project-migrations`，也不列入正式 `migration_manifest.json`。正式 fresh bootstrap 與 db push 不得自動載入。

離職交接尚未取得真人 SSO 全流程驗收；Python 與 UI 預設停用。候選 SQL 會調整既有 RPC 的責任與通知對象，因此不可只以「前端隱藏」為理由先部署到正式資料庫。

隔離測試會建立並刪除 loopback 暫存資料庫，明確載入候選 public／shared 變更；正式環境啟用必須另經人工批准、實際驗收與回復計畫。

```sh
EDOC_COMPOSE_TEST_PG_PORT=55439 EDOC_TEST_PG_USER=postgres python -m unittest -v tests.test_official_handover_postgres
python -m tools.offboarding_handover_shared_forward --check
```
