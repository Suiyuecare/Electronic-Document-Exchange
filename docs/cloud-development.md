# EDOC 雲端開發與接續驗收

本流程讓 EDOC 的來源取得、文件修改、測試與 PR 審查都在雲端完成，不需要使用開發者的個人電腦。開始前先閱讀根目錄的 [AGENTS.md](../AGENTS.md)；本文件不授權變更應用、權限、migration 或正式環境。

## 來源與執行環境

- 原始碼唯一來源為 [GitHub：Suiyuecare/Electronic-Document-Exchange](https://github.com/Suiyuecare/Electronic-Document-Exchange)，不從私人備份還原程式目錄。
- 優先使用已發布且連接此 repository 的私人 Codex Cloud 環境 `Electronic-Document-Exchange`。若目前執行器無法使用該環境，可在其他雲端容器執行，但必須記錄實際環境、工作區、作業系統、runtime 版本與 commit，不可宣稱使用了指定環境。
- 使用 Python **3.12** 與 Node.js **22 或 24**。既有 CI 的一般驗證使用 Node 24，隔離資料庫驗證使用 Node 22。
- 本流程建立於 PR #44 合併後的 `main`：`33f6b0225f202ce6e6cc5097c54a993a4119b292`。每次接續工作仍應重新確認 GitHub 分支與實際 checkout 的 SHA。

在雲端 checkout 中確認來源與版本，再從基底建立獨立分支：

```bash
git remote get-url origin
git rev-parse HEAD
python3.12 --version
node --version
git switch -c docs/cloud-development-followup
```

也可透過 GitHub 連接工具讀取指定 commit、建立分支、寫入文件與開啟 PR；所有寫入都應指定獨立分支，避免使用預設分支。

## 隔離預設與資料界線

`tools/cloud-development.sh` 僅接受下列開發組合，並在執行前檢查：

| 項目 | 開發設定 |
| --- | --- |
| 執行模式 | `EDOC_DEPLOYMENT_ENV=development` |
| 資料庫 | `EDOC_DB_MODE=sqlite`，可拋棄的 SQLite |
| 公文交換 | `EDOC_EXCHANGE_PROVIDER=mock`、`EDOC_EXCHANGE_ENV=sandbox` |
| 檔案儲存 | `EDOC_STORAGE_PROVIDER=local`，雲端容器內的測試儲存 |
| 簽章 | `EDOC_SIGNATURE_PROVIDER=local-simulation` |

腳本會拒絕其檢查清單中的已配置服務端點或憑證、正式執行模式，以及 checkout 根目錄的 `.env`、`.env.local`、`.env.production`、`.env.production.local`。不要為了通過開發測試而移除這些保護。

**禁止將私人備份中的 `.env`、真實公文 PDF、附件、印章圖檔或印章庫還原進公共 repository；即使檔案被 `.gitignore` 忽略，也不得將它們當作此流程的測試資料。** 憑證、PIN、私鑰、API key 與正式端點不得寫入程式碼、文件、commit、PR 或測試輸出；使用合成或去識別化的測試資料，記錄須遮罩敏感內容。

## setup：建立或重用雲端 Python 環境

在 repository 根目錄執行：

```bash
bash tools/cloud-development.sh setup
```

此命令使用 Python 3.12 建立預設的 `.venv-cloud`，安裝 `requirements.txt`、`scripts/backup-restore-requirements.txt` 與固定版本 `pglast==7.21`，並檢查 Node 版本。相依套件下載需要雲端執行器可用的套件來源；安裝失敗時應記錄實際錯誤，不可將未完成的 setup 回報為通過。

若 `.venv-cloud` 已存在且相依套件完整，可直接重用執行 `check`；也可重跑 `setup` 檢查安裝。若使用其他既有雲端虛擬環境，可設定 `EDOC_CLOUD_VENV` 指向該目錄；`EDOC_CLOUD_PYTHON` 可指定 Python 3.12 的執行檔。

若已存在 `/workspace/edoc-local-env.sh`，應先確認它僅設定此開發流程需要的隔離參數、不含正式端點或憑證，再於同一個雲端 shell 載入。此檔案不是必要前提，不需要從私人備份補回，也不要複製進 repository 或輸出其敏感內容。

## check：實際執行開發檢查

修改文件後執行：

```bash
bash tools/cloud-development.sh check
git diff --check
git status --short
```

`check` 依序執行：

1. 編譯檢查 `backend.py` 與 `api/index.py`。
2. 執行 `tools/verify_no_embedded_credentials.py`。
3. 執行 `node --check app.js` 與全部 `tests/*.test.js`。
4. 執行以下五個 Python unittest 模組：`tests.test_exchange_gateway`、`tests.test_compose_preflight_seals`、`tests.test_private_draft_archive`、`tests.test_official_document_workflow`、`tests.test_runtime_readiness_probes`。

檢查會建立臨時的 `EDOC_WRITABLE_DIR`，結束時清理；這是開發 smoke test，不是完整資料庫、前端或正式驗收的替代品。保留實際退出碼與摘要，分別記錄 Node 與 Python 的通過、失敗、略過數；未執行的驗收應標為「未執行」，不可混算成測試通過或 runner 的略過數。

## serve：僅在雲端預覽

需要互動檢視時，在雲端執行：

```bash
bash tools/cloud-development.sh serve
```

預設以虛擬環境中的 Python 啟動後端，綁定 `127.0.0.1:5174`。`EDOC_CLOUD_PORT` 可調整連接埠；測試狀態預設存放在 `.cloud-local-state`，可用 `EDOC_WRITABLE_DIR` 指向另一個雲端測試目錄。預覽透過雲端平台提供的受控入口查看，停止服務時在該雲端終端結束程序。不要將預覽服務當作正式部署。

## 修改、草稿 PR 與既有 CI

1. 確認 GitHub 基底 SHA、閱讀適用的 `AGENTS.md`，在新分支只修改本次授權的文件。
2. 實跑 `setup` 與修改後的 `check`，檢查差異只包含預期的 Markdown；不要提交虛擬環境、SQLite、測試儲存、私有環境設定或備份。
3. 透過 GitHub 連接工具將文件提交到獨立分支，建立以 `main` 為目標的 **draft PR**。核對遠端文件與測試時的文件一致，記錄實際產生的 commit SHA。
4. PR 說明附上實際雲端環境、來源與變更 commit、執行命令、退出碼、通過／略過／失敗數，以及未執行的項目。依既有 PR template 標示未執行檢查，不可勾選沒有證據的項目。
5. 由既有 [eDoc CI](../.github/workflows/ci.yml) 執行 `Validate backend and frontend` 與 `Rebuild Supabase from migrations`。後者在 CI 的可拋棄環境驗證資料庫與 Storage；不應為文件任務手動操作正式資料庫或更動 migration。CI 仍在執行、失敗或未觸發時，如實記錄當下狀態。
6. 保持 draft PR 供審查。本次接續驗收不 merge、不部署，也不更動 branch protection 或既有 CI。

## 驗收範圍與尚未證明的能力

本次開發接續的驗收鏈為：**雲端取得 GitHub 來源 → 修改文件 → 實際執行測試 → 建立草稿 PR**。所有程式、測試狀態與結果留在雲端，不需要下載到使用者電腦。

此隔離環境**不提供真人 SSO 或正式電子公文交換驗收**。Mock 交換、簽章模擬、模擬帳號測試、readiness probe 單元測試或 CI 成功，都不能證明真人登入、正式收發文、正式簽章或正式交換已通過。正式 provider 須待機關提供 jAgent／API／SDK／封包規格後才能實作；任何正式系統連線與驗收均須另立任務，符合 `AGENTS.md` 的測試及人工核准要求。
