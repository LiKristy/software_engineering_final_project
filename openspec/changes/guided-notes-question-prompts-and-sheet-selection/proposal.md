# Proposal

## Why

目前匯入器依賴「學習單」分頁名稱，老師把新題目放在其他分頁時無法建立房間。系統也只保存題號與答案格，學生搶答時看不到題目敘述，必須另行對照講義。

## What Changes

- 移除分頁名稱必須為「學習單」的限制；有 `gid` 時使用指定分頁，沒有 `gid` 時依試算表分頁順序由新至舊尋找，選擇最新且符合題號與答案格格式的分頁。
- 匯入「題目」欄的文字；同題號多列內容依原列順序分行呈現，並保留其答案標記對應。沒有題目文字欄的表仍可依題號與答案格建立房間。
- 搶答等待階段不向學生提供題目文字；開始後學生介面同時顯示題號與題目內容。
- 更新 README 老師指引，說明將新題目放在最新分頁、Google Sheet 分頁格式、指定 `gid` 的方式，以及把試算表分享給 Service Account 的 `client_email`。僅建房需檢視權限，回填需編輯權限。
- 保留既有題號、答案格、題組、回填及競賽流程；既有房間須能在新增題目文字欄位後繼續讀取。

## Capabilities

### New Capabilities

- `guided-notes-sheet-import`: 從符合題號與答案格格式的 Google Sheet 分頁選取並匯入題目內容。
- `student-question-prompts`: 在搶答開始後向學生顯示題號及對應題目內容。

### Modified Capabilities

目前 `openspec/specs/` 沒有既有主規格；相關行為曾記錄於已完成 change 的規格中，因此本 change 以新能力建立可持續維護的需求契約。

## Impact

- Python 匯入解析器、Google Sheets 分頁選取與房間建立服務。
- SQLite 題目資料及向學生提供題目的 API／WebSocket 階段切換；需新增非破壞性遷移，既有題目文字保持空值。
- 學生 HTML/CSS/JavaScript 題目卡片與 README 老師使用說明。
- 不新增 Google API 權限，不讀取或揭露 Service Account 憑證內容。
