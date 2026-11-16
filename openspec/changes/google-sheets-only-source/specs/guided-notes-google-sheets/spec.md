# Spec Delta

## Purpose

讓課堂搶答系統以 Google Sheet 作為唯一 Guided Notes 題目來源，並將得主答案回填至來源表，避免老師維護重複的檔案匯入與下載流程。

## ADDED Requirements

### Requirement: Create rooms only from Google Sheets
系統 SHALL 只接受有效的 Google Sheet 連結建立新房間，並 SHALL 依指定或預設工作表建立對應題號及答案空格。

#### Scenario: A shared Guided Notes sheet creates a room
- **WHEN** 老師提供可讀取且符合 Guided Notes 格式的 Google Sheet 連結
- **THEN** 系統建立房間並依試算表題號呈現學生作答欄位

#### Scenario: Excel upload is no longer accepted
- **WHEN** 用戶嘗試以 `.xlsx` 檔案建立房間
- **THEN** 系統拒絕該請求並要求提供 Google Sheet 連結

#### Scenario: Invalid sheet does not create a room
- **WHEN** Sheet 連結無效、無讀取權限或格式不符合 Guided Notes
- **THEN** 系統回報可理解的錯誤且不留下部分房間資料

### Requirement: Write winners back to the source sheet
系統 SHALL 允許老師將目前有效得主答案回填至來源 Google Sheet，並 SHALL 在回填前辨識來源儲存格衝突。

#### Scenario: Teacher backfills current winners
- **WHEN** 老師要求回填且來源儲存格未遭外部修改
- **THEN** 系統將有效得主答案寫入對應空格並回報同步結果

#### Scenario: Conflicting source cell stops backfill
- **WHEN** 任一目標儲存格既不符合匯入基準值也不符合系統上次寫入值
- **THEN** 系統停止整批回填並指出衝突位置

### Requirement: Remove filled XLSX copy downloads
系統 SHALL 不提供已填答案 `.xlsx` 副本的下載操作或 API，並 SHALL 保留歷史 CSV 匯出。

#### Scenario: XLSX copy download is unavailable
- **WHEN** 老師查看房間控制台或呼叫舊的 `.xlsx` 匯出端點
- **THEN** 控制台不顯示 `.xlsx` 下載操作且 API 對舊匯出端點回覆 HTTP 404

#### Scenario: History CSV remains available
- **WHEN** 老師匯出搶答歷史
- **THEN** 系統下載包含提交答案、接收時間及排名的 CSV

### Requirement: Configure server-side Google credentials safely
系統 SHALL 從 `.env` 設定的 `GOOGLE_SERVICE_ACCOUNT_FILE` 路徑讀取 Service Account JSON，且 SHALL 不將金鑰內容寫入版本庫、資料庫、用戶端回應或一般日誌。

#### Scenario: Existing ignored credential file is configured
- **WHEN** 管理者在 `.env` 設定 repo 相對路徑 `credential/<既有 JSON 檔名>`
- **THEN** 伺服器使用該檔案連線 Google Sheets API

#### Scenario: Credential path is missing or unusable
- **WHEN** 憑證路徑未設定、檔案不存在或無法載入
- **THEN** 系統拒絕 Google Sheet 建房或回填，且不回傳金鑰內容
