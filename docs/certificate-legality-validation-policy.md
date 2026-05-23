# 電子簽章憑證合法性驗證政策

更新日期：2026-05-23
負責單位：行政部主任、總務、資訊管理員

## 範圍

本政策適用於歲悅長照電子公文交換系統內的正式電子簽章、PDF 自動押章、交換封包簽章與簽核不可否認證據。正式上線時，憑證來源需涵蓋自然人憑證、工商憑證、組織憑證與 TSA 時間戳憑證。

## 驗證項目

1. 憑證鏈驗證：確認簽章憑證可追溯至信任根憑證，且憑證用途包含 `digitalSignature`、`nonRepudiation` 或文件簽章用途。
2. 有效期間驗證：簽章時間需落在憑證 `valid_from` 與 `valid_to` 期間內。
3. OCSP 驗證：簽章與驗章時查詢即時撤銷狀態，結果需為 `良好`。
4. CRL 驗證：定期同步撤銷清單，簽章憑證不得列入撤銷清單。
5. TSA 驗證：每次簽章需取得 RFC 3161 時間戳權杖，驗章時需檢查 token imprint 與文件 digest 是否一致。
6. 不可否認紀錄：每次驗證需寫入 `certificate_validation_events`，並關聯 `electronic_signatures`、`tsa_timestamp_tokens` 與 audit log。

## 操作規則

- 總務與行政部主任可在印鑑管理區執行「驗證憑證合法性」。
- 正式電子簽章完成時，系統會自動建立憑證合法性驗證事件。
- 驗章時若雜湊正確但 OCSP/CRL/TSA 任一項失敗，簽章狀態改為 `憑證驗證失敗`，不得送交 jAgent。
- 憑證停用、撤銷、逾期或信任鏈異常時，系統需阻擋後續送簽、押章與交換封包簽章。

## API 與資料表

- `GET /api/certificates/health`：檢查憑證鏈、TSA、OCSP、CRL 服務狀態。
- `POST /api/certificates/validate`：驗證指定憑證，可選擇關聯簽章序號。
- `POST /api/signatures/sign`：簽章後自動寫入憑證合法性事件。
- `POST /api/signatures/verify`：驗章時重新驗證 TSA、OCSP、CRL 與信任鏈。

正式資料表：

- `signing_certificates`
- `certificate_authorities`
- `certificate_validation_events`
- `tsa_timestamp_tokens`
- `electronic_signatures`

## 上線前替換項

目前開發環境使用本機可驗證的模擬 CA、OCSP、CRL 與 TSA URL。正式環境需由資訊管理員替換為實際憑證服務：

- 自然人憑證與工商憑證信任根憑證。
- 組織憑證信任根憑證。
- TSA 服務 URL 與政策 OID。
- OCSP responder URL。
- CRL 發布 URL 與同步排程。

替換後需完成至少一筆簽章、驗章、撤銷憑證阻擋與逾期憑證阻擋測試，並將結果存入季檢稽核紀錄。
