# 法遵驗收與內控制度簽核

## 目的

本制度用於正式上線前、季度檢核與重大變更後，確認電子公文交換系統已符合內控制度、法遵控制與營運證據留存要求。

## API

```bash
curl -X POST https://edoc.suiyuecare.com/api/compliance/attest \
  -H "Content-Type: application/json" \
  -d '{
    "signer_name": "行政部主任",
    "signer_role": "行政部主任",
    "reviewer_name": "主任",
    "reviewer_role": "主任",
    "period": "2026-Q2",
    "attestation_type": "法遵驗收與內控制度簽核"
  }'
```

## 驗收內容

- 機關公文電子交換作業辦法：收發文、交換事件、異常處理與留存。
- 公文電子交換系統資訊安全管理規範：帳號、RBAC、憑證、Token、IP/裝置與操作留痕。
- 文書及檔案管理電腦化作業規範：文號、附件清冊、PDF 套版、用印版本與歸檔保存。
- 個資與資安：敏感遮罩、密件隔離、浮水印、檔案存取紀錄。
- 正式資料庫權限：RLS、密件隔離、保存年限、audit log 不可竄改。
- 檔案儲存與防毒：private bucket、加密、短效 URL、防毒掃描與隔離阻擋。
- 電子簽章憑證合法性：信任鏈、TSA、OCSP、CRL 與不可否認簽章證據。
- 營運管理：部署、監控、排程、通知、備份還原與 SOP。

## 簽核證據

每次簽核會產生：

- `compliance_attestations` 簽核紀錄
- `report_hash`
- `report_json`
- `non_repudiation_json`
- `audit_logs` 操作紀錄

## 通過標準

- 內控分數 >= 90
- 無 readiness blocker
- 已完成備份還原演練
- 監控沒有 critical alert

若分數 >= 70 但仍有阻擋或告警，狀態為「有條件通過」，需列入缺失追蹤。
