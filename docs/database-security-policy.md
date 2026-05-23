# 正式資料庫權限政策

本文件對應 `supabase/migrations/202605230010_formal_database_security_policy.sql`，作為歲悅電子公文交換系統正式上線前的資料庫權限、保存與稽核驗收依據。

## 控制目標

- 所有 `public` schema 核心資料表啟用 Row Level Security。
- 公文、附件、PDF、簽章與交換事件依登入者角色、單位、承辦人與文件 ACL 控制可見性。
- 密件、機密、極機密、絕對機密須再經 ACL 或主管角色授權才可查閱。
- audit log 採 append-only，不允許 update/delete。
- audit log 寫入時自動產生 `previous_hash` 與 `entry_hash`，可用 `audit_log_chain_check` 驗證是否遭竄改。
- 公文主檔自動套用保留年限、屆期狀態與法務凍結欄位。

## 角色資料範圍

| 角色 | 可見資料 |
|---|---|
| 總務 | 總務收文入口、待登錄、待分派、總務負責發文、被 ACL 授權案件 |
| 行政部主任 | 行政部、總管理處、清稿/簽核/維運授權案件；不可因角色直接讀取總務隔離池 |
| 主任 | 營運管理處、主任待簽核、被 ACL 授權案件 |
| 執行長 | 全域狀態、重大案件、密件與跨部門核定案件 |
| 人資/會計/業務助理 | 自己單位、自己承辦、被 ACL 授權案件 |

## 密件 Row-Level 隔離

`documents.security_level` 為 `密`、`機密`、`極機密`、`絕對機密` 時，除一般角色範圍外，還需符合任一條件：

- `document_acl` 對該使用者、角色或單位有 `can_view = true`
- 使用者角色為 `主任`、`執行長`、`行政部主任`

附件、附件安全、PDF 版本、用印申請、電子簽章會回查 `documents`，因此不會繞過公文主檔的 RLS。

## 保留年限

| 政策代碼 | 適用範圍 | 年限 |
|---|---|---:|
| `EDOC-STD-07Y` | 普通/速件收發文 | 7 年 |
| `EDOC-CONF-10Y` | 密件與機密公文 | 10 年 |
| `EDOC-SEAL-15Y` | 發文、用印、電子簽章、交換完成公文 | 15 年 |

刪除公文前會檢查：

- `legal_hold = true` 時禁止刪除
- `retention_until` 未屆期時禁止刪除
- 屆期後刪除會寫入 `document_retention_events`

## Audit Log 不可竄改

`audit_logs` 具備：

- `previous_hash`
- `entry_hash`
- `chain_version`
- `immutable`

新增 audit log 時會由 trigger 自動計算 hash。任何 update/delete 都會被 trigger 阻擋。稽核人員可查詢：

```sql
select *
from public.audit_log_chain_check
where hash_valid is false;
```

查無資料代表目前 hash 驗證通過。

## 驗收 SQL

```sql
-- RLS 必須啟用
select relname, relrowsecurity
from pg_class
where relname in ('documents', 'attachments', 'audit_logs', 'document_acl', 'attachment_security');

-- audit log hash chain 必須有效
select count(*) as invalid_hash_count
from public.audit_log_chain_check
where hash_valid is false;

-- 保留年限政策必須存在
select code, retention_years, status
from public.document_retention_policies
order by retention_years;

-- 密件公文須有隔離欄位
select id, doc_no, security_level, confidentiality_scope, retention_policy_code
from public.documents
where security_level in ('密', '機密', '極機密', '絕對機密');
```

## 上線注意

- 不得把 `service_role` key 放到前端。
- RLS 判斷使用 `public.users.auth_user_id = auth.uid()`，不使用可被使用者改寫的 user metadata。
- `edoc_private` schema 不應加入 Supabase Data API exposed schemas。
- 新增資料表若要開放 Data API，需明確 grant 並啟用 RLS。
