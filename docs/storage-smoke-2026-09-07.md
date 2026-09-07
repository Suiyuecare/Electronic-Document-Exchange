# 私密 Storage 上線驗收

驗證時間：2026-09-07 13:30:59 UTC（台北 21:30:59）。

## 已通過

- 對目前指定的 Supabase 專案 `edoc-private` bucket 實際建立一份無個資測試檔案。
- 取得短效簽名下載資格並下載，內容 SHA-256 與上傳內容完全一致。
- 只刪除本次隨機名稱的測試物件；再次請求得到明確 `NoSuchKey`。
- 資料庫唯讀複查：`smoke-tests/storage-cutover-*` 殘留物件數為 0。
- 沒有讀寫 Seal Vault、沒有建立送簽、沒有寄發公文。

## 驗收工具修正

既有 `tools/storage_cutover_smoke.py` 原先只接受 HTTP 404，導致實際刪除完成卻回報失敗。本次實測服務回應 HTTP 400，JSON 同時提供 `statusCode: "404"`、`code: "NoSuchKey"`。工具現在核對明確的物件不存在代碼；HTTP 403、缺少 bucket、一般 400、回應代碼矛盾都不會當成通過。

錯誤輸出僅保留白名單錯誤碼，不輸出原始例外、簽名 URL、API key 或檔案路徑。憑證只透過私密記憶體與 stdin 交給既有工具，沒有寫入此報告或程式碼。

## 覆蓋邊界

這是 Storage 真實讀寫驗收，不等於真人登入或完整 PDF 編輯器驗收。本次未驗證瀏覽器 TUS、掃毒、PDF 編輯與 preflight、正式簽核、寄送或印章。

`tools/live_editor_launch_acceptance.py` 已提供可重跑、去識別化、只建立未送簽草稿的流程工具，並有本機模擬測試；但執行環境缺少可用的既有登入資格，正式執行在任何草稿寫入前停止。不能將它列為正式環境驗收通過。
