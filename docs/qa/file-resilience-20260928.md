# PDF 操作、傳輸與檔案可見性驗收

本次只處理已確認的檔案操作問題；不改簽核規則、不寫入正式案件，
不呼叫正式電子公文交換環境。既有 Finance 視覺沿用。

## 問題與驗收標準

| 已確認問題 | 改善與通過條件 |
| --- | --- |
| 精簡案件清單漏掉完成檔下載 | 清單保留入口；點擊時重新取得授權詳情，只下載精確核定 ID／類型；沒有候選檔回退。 |
| PDF 元件載入失敗後永遠沿用 rejected Promise | 失敗清除快取、有限度換網址重試；並行使用者共用同一載入。 |
| 傳輸／下載／資料讀取無止境等待 | Metadata 20 秒、PDF 重處理與傳輸每 request 120 秒、檔案下載含 body 45 秒；取消不自動重試。 |
| A4 必須等整份傳完才能開始編輯 | 本機 PDF 檢查與取得意圖後先開編輯、背景傳輸；取消及同步失敗保留此頁編輯，未同步不能送簽。 |
| 多來源重開逐份序列讀取 | 最多兩份授權來源並行，優先讀第一頁來源；原稿暫時唯讀預覽不代表送簽版；全部驗證後才切換模型。 |
| 最終區塊已存成功但回應遺失，重試撞 immutable object | 保存已驗證的 TUS session URL，重試 HEAD 原 session，僅傳未完成 bytes，不重建 session 或 overwrite。 |
| 同時送簽導致詳情與編輯狀態不是同一版 | 非草稿必須同時符合 locked revision、確認檔 ID／SHA、鎖定狀態；不一致保留舊案並要求重開。 |
| 草稿建立／非 A4 finalize 結果不明後重建或隔離 | 不自動重送，也不回報失敗隔離；改由使用者選擇「重新載入確認」。已知 pending intent 的安全同步重試仍保留。 |
| 登出後殘留預覽／下載 | 登出或帳號切換清除暫存預覽、取消開啟；下載 body 完成後再驗同一 session，不能觸發舊帳號下載。 |

## 已執行瀏覽器驗收

- 六種合成角色 × 電腦／平板／手機，共 18 條實際上傳、文字編輯、
  自動儲存與後端回讀流程通過。舊版儲存 409、跨公司 403 各 18 次。
- 既有多分頁／確認版／拖曳／雙指縮放／重開競態 5 情境、34 項檢查通過。
- 桌機／手機的延遲傳輸與取消重試、雙來源唯讀預覽與取消重開共 4 情境通過。
  使用實際 localhost HTTP 回應，延遲包裝不偽造成功。取消後的文字仍可同步回讀。
- 暫時預覽在既有右側編輯欄內，不增加左右 grid 第三個子項；原編輯欄位置與寬度不變。
- PDF 元件首次預載實際回應 HTTP 503 後，正常上傳可取得真正的 retry=1 模組；
  不重新整理、不無限重試，且文字修改確實保存。啟動預載與編輯器共用最多三次載入額度。
- 已檢視手機編輯、桌機暫時預覽截圖，無 JavaScript 錯誤或水平溢出。

證據刻意不提交，避免合成操作記錄變成產品資料：
`/tmp/edoc-file-ux-six-role-20260928/report.json`、
`/tmp/edoc-file-ux-race-browser-20260928/report.json`、
`tests/.artifacts/editor-file-resilience-20260928/report.json`、
`tests/.artifacts/editor-file-preload-recovery-20260928/report.json`。

## 其他檢查與邊界

- shipping 函式執行測試包含 body deadline、失敗重試、同 intent 續傳、
  未同步編輯、權限、核定版本、登出及不確定 mutation。
- JavaScript 語法、Python 編譯及 credential verifier 為必要門檻。
- DESIGN.md lint 無 error；既有 CSS 為 token 真實來源，未重塑品牌。
- Premium 靜態 heuristic 全庫報告仍有既有問題及 `.vercel/output` 重複項，
  不能把它當成全產品通過證明。新增按鈕使用既有事件綁定與實際瀏覽器操作驗證。
- 本機小型合成 PDF 的時間不代表正式 SSO／網路／Supabase 時間。
  非 A4 轉換、大型或掃描 PDF 無法保證兩秒內完成；保留明確進度與安全送簽門檻。
- 手機是 Chromium 尺寸／觸控模擬，非實體 iPhone Safari 驗收。
- 正式發布仍須遠端 CI／全新 Supabase＋Storage TUS gate 成功、部署 READY、
  正式 alias 指向新提交、公開健康／readiness 與靜態雜湊相符。
  生產 proof 只讀，不使用正式員工或公文製造測試案件。
