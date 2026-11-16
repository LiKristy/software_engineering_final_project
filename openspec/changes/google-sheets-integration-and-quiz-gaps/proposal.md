# Proposal

## Why

目前系統要求老師先把 Guided Notes 下載成 `.xlsx` 再上傳，活動後也只提供回填後的副本，無法完成以 Google Sheet 連結建立房間並直接寫回原表的課堂流程。另一方面，既有 12 步驗收中的冷卻規則與結果頁行為尚未完成，老師頁亦有重複的進度／結果區塊。

## What Changes

- 老師建立房間時可提供 Google Sheet 連結；系統使用 `.env` 指定路徑的 Service Account JSON 憑證讀取題號、題組、空格位置與工作表資訊。
- 保留現有 `.xlsx` 上傳建立房間流程，供離線或尚未分享給 Service Account 的範本使用。
- 老師需先將來源試算表分享給 Service Account；系統建立房間時驗證可讀取，回填時驗證可寫入。
- 新增「回填至 Google Sheet」操作，將有效得主答案寫回來源表對應儲存格，並回報寫入結果；保留現有 `.xlsx` 匯出副本作為替代輸出。
- 新增老師可設定的得主冷卻秒數，預設 30 秒；進入冷卻的組別暫時不能搶答，介面顯示剩餘時間。每組單一有效視窗限制維持不變。
- 活動結束時學生介面切換至結果視圖並隱藏作答表單；修正老師頁重複的進度／結果區塊，保留單一可更新的面板。
- 保留現有房間加入、階段同步、答案隱私、排名、題組原子提交、CSV、人工駁回遞補、獲勝上限及投影功能，並補上十二步整合驗收。
- Google 憑證檔案內容、私鑰與存取權杖不得寫入 repo、資料庫或一般日誌；設定只保存憑證檔案路徑。

## Capabilities

### New Capabilities

- `guided-notes-google-sheets`: 以 Google Sheet 連結匯入 Guided Notes 結構，並將得主答案寫回來源試算表。
- `race-cooldown`: 設定及執行得主冷卻期間，並將冷卻狀態同步至組別介面。
- `classroom-results-view`: 活動結束後切換成正式結果視圖，顯示各題得主與答案。

### Modified Capabilities

無。此 repo 尚無已同步至 `openspec/specs/` 的 durable specs；上述新行為將由本 change 的新能力規格定義。

## Impact

- 修改 `app/static/teacher.html`、`student.html`、`app.js` 與樣式，加入 Google Sheet 連結、冷卻設定／狀態、回填操作與結果視圖，並移除重複 DOM id。
- 修改 FastAPI API、`RoomService`、資料存取與 SQLite migration，保存來源 spreadsheet/tab/cell 映射、冷卻設定及安全的同步狀態。
- 新增 Google Sheets API 認證與讀寫 adapter，使用環境設定中的 Service Account JSON 檔案路徑；部署需啟用 Google Sheets API，並將試算表分享給該 Service Account。
- 更新 `.env.example`、README 與整合測試；不提交實際憑證檔或憑證內容。
