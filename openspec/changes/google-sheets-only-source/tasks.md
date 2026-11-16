# Tasks

## 1. Service Account 設定與 Sheets adapter 收斂

- [x] 1.1 將本機 `.env` 的 `GOOGLE_SERVICE_ACCOUNT_FILE` 設為 `credential/` 內既有 JSON 的 repo 相對路徑；`.env.example` 保持不含金鑰內容的範例路徑，並以設定測試及 ignored-file 檢查確認路徑可載入且憑證檔不會加入版本庫。
- [x] 1.2 移除 Google Sheets adapter 的 Drive 匯出服務、`files.export` 呼叫與 `drive.readonly` scope；以 fake Google API 測試確認匯入、讀格及 batch write 僅使用 Sheets API。

## 2. Google Sheet 作為唯一建房來源

- [x] 2.1 移除老師頁的 Excel／Google 來源選擇及檔案上傳控制，改為必填 Google Sheet 連結；更新 README 建房說明，並以 DOM 測試確認頁面沒有 `.xlsx` 上傳入口。
- [x] 2.2 移除 `POST /api/rooms` 的 `UploadFile`、ZIP／大小驗證與 `.xlsx` 分支，僅接受已驗證的 Sheet 連結；以 API 測試確認 Google 建房成功、檔案請求遭拒、無效來源不建立部分房間，並確認舊房間資料可讀。

## 3. 移除 XLSX 副本下載

- [x] 3.1 移除老師頁「匯出學習單」操作、`.xlsx` 匯出 API 及服務層填妥副本功能；以 UI/API 測試確認新舊房間都沒有副本下載入口或端點。
- [x] 3.2 保留 Google Sheet 原表回填與 CSV 歷史匯出，保留舊房間與提交資料且不新增破壞性 migration；以 mock 回填、CSV 匯出及既有資料庫相容測試確認行為。

## 4. 文件與整合驗收

- [x] 4.1 更新 README、`.env.example` 與設定文件，說明 Google Cloud Sheets API、Service Account 分享、repo-root 啟動、`.env` 路徑、Google-only 建房及 CSV 匯出；以文件檢查確認不再宣稱支援 Excel 上傳或 XLSX 副本下載。
- [x] 4.2 執行完整測試、JavaScript 語法檢查、OpenSpec strict validation、資料庫初始化與憑證模式掃描；確認測試、設定範例、事件負載及版本庫內容沒有私鑰或 access token。
