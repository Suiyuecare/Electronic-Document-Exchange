# 正式真人角色驗收：合法登入邊界與待核對項目

日期：2026-09-07（Asia/Taipei）。本輪僅執行正式入口瀏覽器檢查、資料庫唯讀聚合與程式碼查核；沒有新增正式草稿、送簽、代簽、寄送、用印或變更人員權限。

## 正式入口實測

使用全新、獨立命名的 agent-browser 工作階段及空白專用設定，排除既有瀏覽器設定繼承。未使用 Chrome profile、cookies、Keychain、任意 token 檔案或自造登入憑證。

已確認的真實路徑：

1. 正式 Portal 的 `/portal` 顯示共用「帳號登入」畫面。
2. 點擊「使用 Google 登入」後，正常進入 Google 的 `/v3/signin/identifier`。
3. Google 顯示「電子郵件地址或電話號碼」欄位與「下一步」，應用名稱為 `Suiyuecare's Finance`。
4. 停在需要本人輸入帳號的步驟，沒有輸入帳密或完成 MFA；工作階段已關閉，臨時空白設定已清除。

因此，本輪可證明正式 Google 入口可到達，但**不能**證明任何真人已完成登入、進入 eDoc 或完成角色操作。未保存 OAuth 查詢參數、cookies 或 session token。

## 正式名冊唯讀聚合

Finance 範圍為 `active=true` 且 `org_status='active'`，共 31 筆。Portal 比對範圍為已確認 email 且存在 Google identity 的 Auth 人員；跨庫比對在私密記憶體內進行，不輸出姓名、email 或身份指紋。

| Finance 角色 | 有效人員 | Finance 有 Google 驗證時間 | 目前同登入身分可對應 Portal confirmed Google |
| --- | ---: | ---: | ---: |
| employee／一般員工 | 13 | 3 | 5 |
| section_chief／課長 | 9 | 7 | 6 |
| dept_manager／部門主任 | 5 | 5 | 5 |
| admin_director／行政部門主任 | 1 | 1 | 1 |
| general_affairs／總務 | 1 | 1 | 1 |
| ceo／執行長 | 1 | 1 | 1 |
| hr／人資 | 1 | 1 | 1 |
| 合計 | 31 | 19 | 20 |

eDoc 的 Finance 投影同時顯示：啟用 19、待啟用 12、停用 6；本輪查得這些投影都具備公司綁定。這是名冊狀態，不是登入成功證據。

Portal、Finance、eDoc 使用不同的 Auth namespace，不能以跨專案 Auth UUID 不同或 eDoc 本地 Auth 欄位未填，直接判定帳號異常。各系統的「Google 驗證時間」與「目前 Portal 身分可對應」也不是同一個指標。

### 五筆待本人登入核對

以下只表示查詢當下的兩邊紀錄差異；**不判定為缺陷、不判定哪邊錯誤、不直接變更權限**。可能涉及首次登入、主帳號變更、待重綁或不同登入通路，需以本人當次正式登入結果確認。

| Finance ID | 角色 | 公司 ID | 待核對的觀察 |
| --- | --- | --- | --- |
| `u_ppt_46a575c1cbecffdc` | employee | E9 | Portal 可對應 confirmed Google；Finance 無驗證時間 |
| `u_ppt_65af0fe56faa6789` | employee | E5 | Portal 可對應 confirmed Google；Finance 無驗證時間 |
| `u_ppt_5df79081f0c7c3cb` | employee | E8 | Portal 可對應 confirmed Google；Finance 無驗證時間 |
| `u_ppt_58b24e472ef9efdd` | employee | E9 | Finance 有驗證時間；目前登入身分未對應 Portal confirmed Google |
| `u_1779426018533` | section_chief | E5 | Finance 有驗證時間；目前登入身分未對應 Portal confirmed Google |

不能把兩欄總數相減當成差異人數：逐 ID 核對才得到上述 5 筆。本輪沒有啟用、停用、重新綁定或補寫任何一筆。

總務、執行長、行政部門主任目前各只有 1 個有效正式帳號，不可能宣稱每個角色都各抽測了 5 個不同真人帳號。相同帳號跑 5 種情境、或 5 個去識別化模擬帳號，必須分開標示。

## 已存在的本人登入恢復機制

以下是現有程式及正式資料庫函式／trigger 的唯讀查核，並未呼叫任何會修改身份的 RPC。

- Finance 前端在有效的公司 Google session 建立後，先執行 `completeCurrentGoogleAccountLinkV2()`；必要時使用既有 reconciliation／`claim_current_finance_user_auth_id` 路徑。帳號衝突或暫時性錯誤會停止，不直接改綁。
- 正式 Finance 的 `finance_complete_current_google_account_link_v2()` 先檢查 `auth.uid()`，再從當次身份取得已驗證 Google email，交由私有連結函式處理；不是讓管理員任意指定另一個人的身份。
- `claim_current_finance_user_auth_id()` 與 `reconcile_current_google_finance_identity()` 也以 `auth.uid()` 為主體；私有完成連結函式已有驗證時間與 projection 同步邏輯。
- 正式 `finance_users_edoc_outbox_v1` trigger 已啟用，對 `finance_users` 的 INSERT／UPDATE 透過既有 outbox 產生 eDoc 同步工作。
- eDoc 的 `supabase_authenticate_preprovisioned_logging_bridge()` 使用已驗證且已消耗的 Portal handoff，再即時取得 Finance 權威快照。`sync_supabase_finance_login_snapshot(..., portal_authenticated=True)` 允許已驗證 Portal 身份在 Finance 人員／公司仍有效的前提下完成待啟用投影，不要求先綁第二組 Auth UUID。
- eDoc 仍檢查公司有效性、上線範圍與身份綁定；不會以 Portal 登入覆蓋 Finance 的停用或公司限制。

這表示已有本人登入後的合法核對與恢復路徑，**不表示本輪已替上述 5 人完成恢復**，也不能保證所有差異會在一次登入後消失。若仍受阻，記錄去識別化錯誤碼並回到 Finance 的既有「檢查登入」流程確認指定主帳號／重綁狀態。

相關程式位置：`backend.py` 的 `current_finance_bridge_snapshot`、`sync_supabase_finance_login_snapshot`、`supabase_authenticate_preprovisioned_logging_bridge`；Finance `index.html` 的 Google 登入完成流程。

## 既有 live 工具不能代表真人驗收

- `tools/live_five_account_sso_acceptance.py` 的 `signed_handoff()` 自行用 HMAC 產生 handoff，再呼叫正式 session 介面。即使先比對已驗證名冊，也不是本人操作 Google 登入；它明確標示 `humanGoogleLoginExercised=false`。
- `tools/live_editor_launch_acceptance.py` 的 `main()` 同樣呼叫上述自簽 handoff。**本輪沒有執行這兩個 main，也沒有取得或使用簽章密鑰。**
- 編輯器工具的已登入後檢查可涵蓋標記草稿、合成 A4 PDF、直傳、掃毒、文字編輯、autosave／409、prepared PDF、原稿 hash、變更清單與非參與者跨公司拒絕；不送正式簽核、不操作印章。
- 後續若使用這些檢查，必須改由本任務內、本人剛完成登入且明確授權的 session 接續；不得以現有自簽入口冒充真人。現有草稿保留規則沒有公開刪除 API，建立前須接受留下明確標記的未送簽驗收草稿。

## 最小真人驗收步驟

1. 一般員工、課長、部門主任、行政部門主任、總務、執行長各選一名實際持有該角色的人；每人使用獨立、全新的有畫面驗收視窗。不能以一個管理員切換標籤代替六種真實角色。
2. 本人只需在正式 Portal 點 Google 登入，親自輸入帳密及必要 MFA／授權確認；看到模組頁後停下。**不需要把密碼交給驗收人員，也不匯出 cookies。**
3. 接續在同一個已授權 session 點 eDoc，核對實際角色、公司、部門、六大頁面、預設欄位與手機／桌面操作。只讀角色頁面不等於已完成簽核。
4. 取得建立測試資料的明確核准後，僅由申請人建立「上線驗收測試－不送簽」草稿，上傳去識別化 A4 PDF，測試文字編輯、儲存、重整後保留、prepared PDF 與下載。
5. 跨公司拒絕測試使用另一個已獲授權登入、且不在該草稿參與者名單的帳號；正式工作流程中的跨公司共享服務簽核人不應一律當成未授權者。
6. 不代點正式核准／駁回，不寄發、不用印；需要驗收正式簽核決策時，必須由對應簽核人本人執行，並另行限定測試案件與影響範圍。

### 不等待真人也能先完成的證據

- CI 的隔離五帳號、角色縮減規則、跨公司拒絕、revision／409、鎖定、RPC 與 TUS 測試，清楚標記為隔離自動化驗收。
- 正式公開入口／未登入拒絕、健康檢查、公司與角色名冊聚合、同步 trigger 存在與啟用狀態。
- 既有正式 Storage 去識別化上傳、簽名下載雜湊與自清除證據，見 `docs/storage-smoke-2026-09-07.md`。

以上證據不能替代 Google 帳密／MFA、真人角色畫面、真實待辦接收或簽核人的實際判斷。
