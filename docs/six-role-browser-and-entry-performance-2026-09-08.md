# 六角色瀏覽器與入口效能驗證（2026-09-08）

## 結果與範圍

使用獨立 agent-browser session `edoc-roles-20260908`，在剛建立的暫存 SQLite／Storage 隔離環境中執行。角色為一般員工、課長、部門主任、行政主任、總務及執行長；所有人物、公司及 PDF 都是去識別化測試資料。未讀取其他瀏覽器的 Cookie、未自簽 Google／Portal 身分，也未建立正式測試帳號。

| 項目 | 結果 |
| --- | --- |
| 六角色 × 桌機 1440×1000／手機 390×844 × 六入口 | 72 項檢查；66 項可見頁面實際導航及截圖 |
| 受限入口 | 員工、課長、部門主任不顯示系統設定，兩種尺寸共 6 項確認 |
| A4 上傳 → PDF 加字 → 自動保存 → API 回讀 | 12／12 通過，保存文字一致 |
| 過期版本寫入 | 12／12 回傳 409，未靜默覆蓋 |
| 不同公司讀取編輯草稿 | 12／12 回傳 403 |
| 文件水平溢出／未處理前端錯誤 | 檢查範圍內均 0 |
| 503 錯誤訊息 | 桌機／手機顯示可追蹤 ERR 編號，未顯示內部診斷內容 |
| 用印／送簽／通知／正式政府交換 | 均未執行 |

A4 流程使用真實本機 HTTP API、編輯器及自動保存邏輯；Finance 來源與掃毒為隔離測試替身，不能稱為正式 TUS、真實掃毒供應商、真人簽核或正式公文驗收。

## 本次修正

- 手機通知鈕、主選單鈕及抽屜關閉鈕的實際尺寸調為 44px；六大入口與既有資訊架構不變。
- 介面 Google 字型採非阻塞載入；公文預覽及輸出的 EduKai 標楷體範圍未改。
- 三份前端資產版本一致使用 `20260908-launch-six-items-r1`。
- 操作驗證等待抽屜動畫結束、PDF 上傳結束及捲動後控制項可點擊，避免自動化座標競態被誤判為產品故障。
- 新增本機六角色工具及匿名正式入口量測工具；正式量測不取得使用者登入權杖。

手機自動掃描仍列出 CEO「系統設定」14 個 checkbox 原生 glyph 小於 44px。此掃描未計算關聯 label 的有效點擊範圍，尚不能據此認定為可用性缺陷；也不宣稱整站已通過無障礙或實機認證。

## 效能：分開量測，不混用

| 環境／單次導航 | 讀取條首顯 | 已認證介面可操作 |
| --- | ---: | ---: |
| 本機隔離 cold，修正前 | 317.2ms | 580.9ms |
| 本機隔離 cold，修正後 | 34.5ms | 295.1ms |
| 本機隔離 warm，修正後 | 43.0ms | 268.2ms |
| 本機介面字型刻意延遲 1,500ms，cold | 47.2ms | 281.4ms |
| 正式匿名入口，修正前 cold | 4,883.0ms | 未測得，返回登入入口 |
| 正式匿名入口，修正前 warm | 120.5ms | 未測得，返回登入入口 |

本機 24 次導航中，讀取條首顯介於 15.1–60.6ms，已載入隔離帳號的介面可操作介於 235.7–295.1ms。這些是單次樣本及樣本範圍，並非 p95、SLA 或真人 Google 登入時間；cold 前後也未控制遠端網路條件，不能把差值全部歸因於字型修改。1,500ms 延遲字型案例則直接證明介面不必等待字型才顯示。

主代理另有正式本人 Google → Portal → eDoc 成功登入的證據，應列於總報告，不合併計為本工具的六位真人驗收。正式部署後的匿名量測另外留存，不覆蓋本次 baseline。

## 畫面與重跑方式

- [六入口桌機／手機 Before / After 看板](../tests/.artifacts/six-role-before-after-20260908.html)
- [六角色完整結果](../tests/.artifacts/six-role-final-20260908/report.json)
- [慢字型行為驗證](../tests/.artifacts/six-role-slow-font-20260908/report.json)
- [正式匿名入口 baseline](../tests/.artifacts/public-loader-probe/report.json)

看板使用實際瀏覽器截圖，不是生成式概念圖。截圖包含隔離測試資料、捲動位置及當時提示；本次沒有重新設計頁面。artifact 目錄為 ignored 本機驗收產物，不含權杖，也不推送正式使用者畫面至 repo。

```sh
python tools/six_role_browser_acceptance.py --output tests/.artifacts/six-role-rerun
python tools/six_role_browser_acceptance.py --roles staff --devices desktop --slow-font-ms 1500 --output tests/.artifacts/six-role-slow-font-rerun
python tools/public_entry_browser_probe.py --output tests/.artifacts/public-loader-rerun
python -m unittest tests.test_six_role_browser_acceptance tests.test_four_role_ui_contract tests.test_uiux_simplification_contract tests.test_official_font_scope_contract -q
```

需既有測試相依套件及 agent-browser。六角色工具限本機剛建立的隔離環境，完成後清除自己的測試 DB／Storage；不提供正式 Auth 繞過選項。公開入口工具仅匿名導航，不登入 Google。

## 尚未由本輪工具驗收

- 六位真人逐一由自己的 Google 帳號登入、確認角色與公司，並完成需要本人確認的實際業務流程。
- iPhone、Android、iPad 實機觸控與 Safari／Firefox；本次為 Chromium 桌機與行動尺寸模擬。
- 大型 50MB／300 頁 PDF、完整多頁工具、真實掃毒供應商、印章與正式送簽。
- 正式端到端 0.5 秒登入承諾；需以實際權限驗證／來源同步／冷啟動分段量測及足夠樣本判定。

本文件完成時程式碼已交主代理凍結檢查；不代表已部署。
