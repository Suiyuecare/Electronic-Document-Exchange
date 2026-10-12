# 完整改善與驗收紀錄

日期：2026-10-12。範圍：內部公文、用印、簽核、收發與維運。

本輪修正均在獨立工作區完成，未清理或覆寫原工作目錄。正式政府電子交換仍停用；未取得機關規格，不自行實作正式封包或發送。此文件不是正式上線通過證明。

## 十項改善及驗收界線

| 項目 | 已製作內容 | 驗收標準與證據 |
|---|---|---|
| 收文漏件 | 公司、Finance tenant、使用者 ACL、狀態與搜尋先篩選，再以 cursor 分頁；游標綁定身分與條件 | 至少 1,201 筆混合資料，最舊有權限待辦可找到；跨公司、同名、停用、換條件游標拒絕；載入失敗不顯示空清單成功 |
| 逾期催辦漏件 | 完整 keyset 掃描，實際目前關係人資格與不可變 ID 去重 | 超過 500 筆可處理；第二批故障後重跑不重複通知、不隱藏失敗；已結案、已回覆不催辦 |
| 老闆時效統計 | 後端完整權限範圍彙總；Asia/Taipei 到期分布與實際等待天數分開 | 缺期限／起算時間列未知；超過頁面筆數仍納入；跨公司不得統計；部分查詢失敗標示不完整 |
| 離職未結交接 | 候選、獨立確認、即時接任資格及原案保留；補正建立關聯新案、重跑簽核 | public/shared PostgreSQL 競態、越權、停用、舊版、不可逆階段；真人驗收前不啟用、不自動套正式候選 SQL |
| 真實員工 SSO | 補妥伺服器功能開關與登入／刷新身分正規化；去識別角色隔離流程 | 具名五角色及另外一位無管理權限普通員工本人操作 OAuth、新分頁、直連、重整、登出換人、新進／調職／停用；合成登入不算真人通過 |
| PDF 等待與效能 | A4 本機先開啟並可加字；草稿、hash、上傳資格在背景完成，再綁正式 asset；可編輯與已保存分開 | 確實在上傳資格延遲時編輯；雲端讀回文字、無 LOCAL asset；取消／重試／換帳號保留隔離；每裝置／網路至少 30 筆，冷啟動、一般 A4、大檔、非 A4 分開 |
| 操作確認與表單 | 共用非阻塞確認視窗、焦點／IME／取消守門；共用欄位驗證與錯誤定位 | 取消零變更、確認一次、中文組字不誤提交，錯誤必填／格式不發請求；未保存內容不被切換覆蓋；桌機／平板／手機無溢出 |
| 通知與 PDF 產出 | 重跑簽核、退回、加簽、派發、回覆、結案與真產物；服務接受與送達仍分開 | 六種合成角色完整 HTTP 流程與實際用印 PDF；已啟用外部通道的本人收件證據仍須另驗，不以 provider receipt 冒充收到 |
| 備份與復原 | 真 PostgreSQL 還原、失敗／中斷可見、排程可達 RPO 判定、7 日連續異地證據驗證器 | 原始 receipt、私密加密 bytes、實際下載另一份與還原；每個時點 RPO ≤ 15 分鐘、RTO ≤ 30 分鐘；7 個日期或一小時排程不能冒充持續達標 |
| 發布防護 | main 必須 PR、兩項必過 CI、一位人工核准；管理者亦受限，禁止強制推送／刪除，舊審查失效需重審 | GitHub API 實際設定後讀回；候選 commit 的兩項 CI 必須成功；目前唯一寫入帳號不能自行核准自己的 PR，需另一位既有審查者 |

## 可重跑命令

```sh
python -m unittest discover -s tests -p 'test_*.py'
node --test tests/*.test.js
node tests/handover_feature_gate.js
python tools/complete_role_flow_acceptance.py --include-handover --report "$EDOC_REDACTED_ROLE_REPORT"
python tools/ux_complete_browser_acceptance.py --samples 30 --output "$EDOC_REDACTED_BROWSER_OUTPUT" --candidate-commit "$EDOC_CANDIDATE_COMMIT"
python -m tools.workflow_readiness_shared_forward --check
python -m tools.offboarding_handover_shared_forward --check
```

實際 PostgreSQL 契約測試必須在 disposable loopback cluster 明確設定 `EDOC_COMPOSE_TEST_PG_PORT`／`EDOC_TEST_PG_USER`；跳過數不能列為通過數。CI 的 Supabase 重建工作另跑真實 PostgREST、signed TUS、Storage finalize 與不同帳號的權限拒絕。沒有本機 Docker 時，不以本機 direct upload 代替該 CI。

## 正式驗收與發布

1. 凍結 candidate commit；所有報告綁定該 SHA／實際 source hash，修改後重驗受影響範圍。
2. 依 `tools/readiness_acceptance.py` 留存六項獨立門檻、真人操作與遮罩證據。效能使用 `tools/service_level_acceptance.py` 的分裝置／網路原始樣本；異地備援使用 `tools/backup_continuity_acceptance.py` 的連續時窗與原始 bytes／receipt。
3. `tools/complete_acceptance.py` 會同時檢查上述三份記錄。即使記錄完整也只回傳等待獨立審查，不會自動授權發布、資料修復或政府交換。
4. 未完成真人 SSO、實體裝置／實際網路、本人收件、核准異地位置／金鑰保管、7 日例行備份及獨立人工審查，保持 pending，不能以本機綠燈宣告全系統正式通過。
5. 交接 SQL 位於 `supabase/candidate-migrations/`，不列入自動正式 migration 清冊；其既有 RPC 行為有變化，正式啟用必須另核准並驗收，不能只隱藏 UI 就先上庫。
6. 一般缺件修正亦須先通過 migration／runtime 就緒與預備環境驗收，核實上一版相容回復候選，再正式推送；不得直接覆寫正式案件或跳過發布保護。

## 本輪已觀察的證據

完整角色隔離 runner：13 組、131 項、零失敗／零跳過；六種身分均實際建立、編輯、審閱、簽核、產出用印文件、下載及結案。原始檔、prepared 及 stamped hash 不同，鎖定／越權直接呼叫均拒絕。

凍結候選 `225d881919b9d8c81ca30c172c37d8c158c502d0` 的 PDF 瀏覽器：桌機、平板、手機尺寸各 30 次，共 90 次通過。暖 localhost 的 workspace p95 為 15／15／14 ms，兩頁約 1.9 KB 合成向量 A4 本機編輯 p95 為 56／46／82 ms，雲端保存 p95 為 558／794／607 ms。**不是正式站、實體裝置、冷啟動、掃描大檔或真實 SSO 的速度證明**；後續候選變更要重新綁定與驗收，不直接沿用此數字。

上述凍結候選的完整 PostgreSQL 全套回歸為 1,909 項中的 1,908 項通過、1 項未執行；該項是本機未啟動完整 Supabase signed TUS stack，不計入本機通過數。相同候選的 GitHub [run 38189391166](https://github.com/Suiyuecare/Electronic-Document-Exchange/actions/runs/38189391166) 兩項必要 CI 成功：真實 PostgREST／Storage／signed TUS／finalize 的七種檔案與重試情境通過，五個不同合成帳號的 A／B／C／D 流程上傳驗收零失敗、零跳過。這仍不是正式 Storage 或本人 OAuth 的證據。最終候選與新增測量工具回歸結果記在 [PR 40](https://github.com/Suiyuecare/Electronic-Document-Exchange/pull/40)，不刪除首次失敗與跳過紀錄。

另追加 12 組合成 PDF：1／25／300 頁向量、約 9.98／39.92 MB 掃描重量、非 A4，各在桌機／手機尺寸操作。首輪測量工具得到 7 通過／5 逾時，完整保留原報告；實際加字及雲端讀回診斷確認六組大檔可用。原因是草稿與 LOCAL asset 換綁期間，已完成的同頁畫面仍可能回傳 `false`，舊測量工具只接受 `true` 因而漏掉。新探針等待真實 render task 完成、同頁／同 SHA／同 session／epoch／proxy／geometry、非空白 canvas 及下一畫格，不修改產品 render 回傳值；state 必須動態讀取，不能綁定載入前的空物件。修正後 12／12 完成 pointer 加字、同步釋放、伺服器讀回、頁數及無 LOCAL asset 保存檢查。非 A4 是轉換同意及轉換結果確認，不表示已送簽。這些單次大檔觀察不混入一般 A4 的 p95，也不提供任何真實網路兩秒保證。

新確認／欄位驗證保留 Finance 視覺、原業務處理與伺服器守門。實際瀏覽器欄位驗證為 3 裝置尺寸 × 4 表單，共 12 項；錯誤／IME 不觸發業務請求，修正後僅一次進原處理。全 repo Premium 靜態工具仍有 414 項既有 vanilla-JS 綁定的 actionless-button 辨識結果，未清零或宣稱完整靜態驗收通過。另六角色 × 六路由的只讀動態觀察共 33 個可見角色／路由；補強 fieldset disabled、once／abort lifecycle 及 native popover 條件後，1,009 次啟用按鈕觀察有直接或表單 owner。該檢查不點擊批次變更、不讀取 handler 內容，也不把 delegated／once lifecycle 候選當成已證明業務功能。按鈕稽核工具會在啟動測試前拒絕 repo／symlink／hardlink／既有報告，使用私密目錄及持有目錄 fd 的原子寫入；十一項守門回歸及前後 source hash 比對通過。

已唯讀核對現有正式 Vercel project 的 production env metadata：沒有 `EDOC_OFFBOARDING_HANDOVER_ENABLED` 設定，故未驗收交接不會由舊環境旗標意外開啟；此查核不會發布新程式或修改正式案件。
