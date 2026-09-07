# Finance 公司資料一致性修復

驗證時間：2026-09-07 21:11（Asia/Taipei）。範圍為公司投影及公司選擇範圍，不涉及印章檔案。

## 已確認原因

Finance 公司主檔為 11 個穩定 entity ID（E1 至 E11）。eDoc 的舊 CO-008 沒有 Finance entity、tenant 或來源綁定；Finance E8 已有另一筆正確名稱的 canonical 投影。兩筆統編一致，但舊名少了「服務」二字。eDoc 的 Finance 下拉選單原已排除未綁定資料，上線檢查及啟用公司總數仍會納入舊資料。

## 已套用修正

- 將經核對的 CO-008 設為 inactive / legacy_superseded，保留原始 ID、名稱及全部歷史關聯。
- 保留 CO-008 的 8 個空印章設定槽；沒有新增、刪除、搬移或變更印章檔案。
- 正式環境的 Finance 公司範圍須具備有效來源、entity、tenant 及啟用狀態。未綁定舊資料列在 excluded metadata，不再當成上線公司。
- 已有公司修訂版本時，無版本的舊同步快照不得覆寫名稱、地址、統編或啟用狀態；並行建立的衝突路徑亦適用。
- 後續公司更名繼續依 Finance 穩定 entity ID 更新既有投影；已退役的舊資料不得以名稱重新認領。

## 正式資料驗證

| 項目 | 修正前 | 修正後 |
| --- | --- | --- |
| 啟用公司 | 12 | 11 |
| 未綁定的啟用公司 | 1 | 0 |
| 啟用 Finance entity | E1 至 E11 | E1 至 E11 |
| 舊公司印章設定槽 | 8 | 8 |
| 印章檔案 | 0 | 0 |

修正前逐表檢查舊公司：使用者、公文、用印申請、委派、收文、合約及其他文件引用均為 0；印章設定槽內檔案為 0。

先以完整交易執行並 ROLLBACK，確認公司總數為 11、舊槽位保留、稽核雜湊正常，再正式套用。重複套用不新增稽核或重寫資料。稽核 ID：`AUD-COMPANY-PARITY-20260907-CO008`，使用現有 v2 稽核 trigger，重新計算雜湊吻合且 immutable=true。shared migration ledger 由 53 筆增加至 54 筆。

## 重播與部署

公司同步、下拉選單、公司範圍及 shared migration 驗證 67 項通過；包含舊快照重送、並行建立衝突、退役公司拒絕重新認領、未綁定公司隱藏及 migration 雜湊一致性。

專用資料庫來源：`supabase/migrations/20260907130400_retire_unmapped_legacy_company_projection.sql`。

已存在的 shared eDoc schema：`supabase/shared-project-migrations/20260907130912_retire_shared_legacy_company_projection.sql`。此檔案已於正式 shared schema 套用；來源與轉換後的 SHA-256 均已記入不可變 ledger。資料更正已生效；應用程式保護需與本次程式版本一起部署。

修正只限上述已核實 ID；任何識別欄位或引用狀態不符合預期時，交易會停止。不得把此 SQL 擴大為依名稱或統編批次合併所有公司。

Supabase security advisor 已執行；本次沒有新增 schema、權限或 RLS 設定。既存的私密表無公開 policy 資訊提示及 Auth 密碼外洩防護警告未因本次公司更正而變更。
