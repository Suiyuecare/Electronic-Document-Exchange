# 印章置頂：版本相容與驗收

本次只改印章繪製順序，不包含正式印章原圖、不變更公司權限或尺寸校準、不執行正式公文交換。

## 新案件

- PDF 編輯器 renderer：`pymupdf-1.26.5-editor-v4-seal-front`。
- 公文 renderer：`reportlab-4.4.9-formal-tw-v6-manual-edukai-5.1-seal-front`。
- 新申請保存 `seal_layer_policy=company_seal_above_all_content`。
- 文字、圖片與其他編輯物件先繪製，印章最後繪製；多枚章保留其內部層序。
- 透明 PNG 的透明區仍顯示下方內容；透明度、尺寸、旋轉、章版本及雜湊驗證不變。
- 騎縫章仍以同一鎖定圖檔分割，半章透明區不填白。

## 歷史案件

- 已鎖定 V3 保留原「輸入文字在印章上」的繪製方式。
- 已核准或已產出的 PDF 不重製、不回寫。
- 無新 policy 的舊申請保留舊層序。
- 舊草稿在新版重新預檢時建立新 revision，不修改舊 revision。
- 提交時核對 revision 與 prepared asset 的 renderer；舊確認版不可直接以新版本送簽，必須重新預覽。
- 前端同步預檢回傳的 revision、manifest 與 renderer，並拒絕覆蓋預檢期間新增的編輯或另一份文件。

## 回歸測試

- `tests/test_seal_front_policy.py`：前端排序、版本資訊、預檢切換、舊申請相容與兩種後端分支。
- `tests/test_seal_front_regression.py`：合成 PNG 的實際 PDF 像素、透明區、透明度、多章順序、V3 相容與騎縫章。
- 既有編輯、簽核、用印及權限測試一併回歸。

測試只使用合成印章與去識別資料。上述測試不等同於正式印章已完成收檔、去背、校準、掃毒或啟用。
