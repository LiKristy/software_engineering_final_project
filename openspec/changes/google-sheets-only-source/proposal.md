# Proposal

## Why

Google Sheet 已是課堂題目來源，保留 Excel 上傳與下載副本會讓老師在建立房間時面對不必要的來源選擇，也維護兩條檔案流程。系統應只以 Google Sheet 建立題目，並將課後答案留在來源試算表；Service Account 路徑則由本機忽略的 `.env` 設定。

## What Changes

- **BREAKING** 移除老師建立房間時的 `.xlsx` 上傳選項，只接受有效且已分享給 Service Account 的 Google Sheet 連結。
- **BREAKING** 移除已填答案 `.xlsx` 副本下載按鈕與 API；保留 Google Sheet 原表回填及歷史 CSV 匯出。
- 停止匯出 Google Sheet 的 `.xlsx` 快照與相關 Drive API 呼叫及唯讀授權需求。
- 將 `GOOGLE_SERVICE_ACCOUNT_FILE` 設為 `.env` 中現有 Service Account JSON 的 repo 相對路徑（`credential/<既有 JSON 檔名>`）；`.env.example` 僅記錄路徑格式，不放金鑰內容。
- 保留既有房間、提交歷史與資料庫紀錄；不因移除匯入／下載功能而刪除舊資料。

## Capabilities

### New Capabilities

- `guided-notes-google-sheets`: 以 Google Sheet 作為唯一建立房間的題目來源，回填得主答案至原表，並保留 CSV 歷史匯出。

### Modified Capabilities

無。專案目前沒有已同步的 durable specs；本 change 會建立 Google Sheet 單一來源能力規格。

## Impact

- 修改老師建立房間頁面與前端表單，移除來源選擇、檔案上傳及 `.xlsx` 下載操作。
- 修改 FastAPI 建房與匯出 API，使建房只接受 Sheet 連結並移除 `.xlsx` 副本匯出端點。
- 修改 Google Sheets adapter 與 Service Account scope，不再呼叫 Drive 匯出 API。
- 更新 `.env.example`、README、測試及 OpenSpec 規格；本機 `.env` 及 `credential/` 內的金鑰檔不得提交至版本庫。
