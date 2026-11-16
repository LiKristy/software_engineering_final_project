# Spec Delta

## Purpose

讓老師直接以 Google Sheet 連結建立 Guided Notes 搶答房間，並將審核後的得主答案寫回原試算表，避免下載、上傳及手動複製答案。

## ADDED Requirements

### Requirement: Import Guided Notes from a Google Sheet link
系統 SHALL 接受老師提供的 Google Sheet 連結，讀取指定學習單工作表的題號、題組與答案空格位置，並以辨識出的題目建立房間。

#### Scenario: Valid shared sheet creates a room
- **WHEN** 老師提供符合 Guided Notes 格式且已分享給系統 Service Account 的 Google Sheet 連結
- **THEN** 系統讀取題號與空格映射並建立題數相同的房間，學生介面顯示對應題號與可編輯空格

#### Scenario: Sheet link contains a worksheet identifier
- **WHEN** 老師提供帶有工作表識別資訊的試算表連結
- **THEN** 系統依該連結定位工作表；若未指定則使用 Guided Notes 預設工作表

#### Scenario: Invalid or unsupported sheet
- **WHEN** 連結格式錯誤、試算表不存在、工作表不符合 Guided Notes 格式或系統沒有讀取權限
- **THEN** 系統不建立房間，並顯示可理解的錯誤原因與分享權限指引

### Requirement: Keep Google service credentials private
系統 SHALL 從部署環境設定取得 Service Account JSON 憑證檔案路徑，並只在伺服器端使用憑證存取 Google API。

#### Scenario: Credentials are not exposed
- **WHEN** 系統讀取或更新 Google Sheet
- **THEN** 憑證內容與存取權杖不得出現在瀏覽器回應、WebSocket 事件、資料庫、版本庫範例或一般應用程式日誌中

#### Scenario: Credential path is invalid
- **WHEN** 憑證路徑未設定、檔案不存在或憑證無法使用
- **THEN** 系統拒絕建立房間或回填，且不回傳憑證內容

### Requirement: Write winners into the source Google Sheet
系統 SHALL 允許老師將有效得主答案寫入原 Google Sheet 中建立房間時記錄的答案儲存格，且只更新有得主的對應空格。

#### Scenario: Teacher writes approved winners back
- **WHEN** 老師點擊「回填至 Google Sheet」且來源表可寫入
- **THEN** 系統將各題有效得主答案寫入原題對應儲存格並回報成功結果

#### Scenario: No winner leaves the answer cell unchanged
- **WHEN** 某題沒有有效且符合獲勝上限的得主
- **THEN** 系統不更新該題的來源儲存格

#### Scenario: Source cell changed outside the application
- **WHEN** 回填時任一目標儲存格的內容既不符合匯入時快照，也不符合系統上次成功寫入的答案
- **THEN** 系統不覆寫該儲存格，回報衝突位置供老師檢查

#### Scenario: Write permission is missing
- **WHEN** Service Account 對原試算表沒有編輯權限或 Google API 拒絕寫入
- **THEN** 系統不宣告成功，保留答案紀錄並提示老師確認分享權限後重試

#### Scenario: Same winners are written more than once
- **WHEN** 老師再次回填且目標儲存格已是相同得主答案
- **THEN** 系統回報已同步，不重複覆寫其他試算表內容

#### Scenario: Winner changes after a previous write
- **WHEN** 老師駁回已回填的得主並再次回填遞補答案，且來源格仍是系統上次寫入的舊答案
- **THEN** 系統將舊答案更新為目前有效得主答案並記錄新的同步值

#### Scenario: Batch write fails
- **WHEN** 一次回填中的任一目標更新被 Google API 拒絕
- **THEN** 該次回填不得留下部分儲存格更新，並回報失敗

### Requirement: Keep the downloadable workbook export
系統 SHALL 保留匯出已回填 `.xlsx` 副本的能力，且該能力不得取代或修改原 Google Sheet。

#### Scenario: Teacher downloads a filled copy
- **WHEN** 老師選擇匯出學習單副本
- **THEN** 系統下載包含有效得主答案的 `.xlsx` 檔案，原 Google Sheet 不因該次下載而改變
