# 簡課堂搶答系統

以 Python、FastAPI、SQLite、WebSocket 與原生 HTML/CSS/JavaScript 建置的課堂分組搶答系統。老師貼上 Guided Notes Google Sheet 連結建立房間，學生以房間代碼和組名加入；提交、審核、排名、結果與匯出由伺服端處理。

## 環境需求

- Python 3.11 以上
- Node.js/npm（執行 OpenSpec 命令時使用）
- `uv` 套件管理工具
- Google Sheets 整合時需 Google Cloud 專案與外部 Service Account JSON 金鑰檔

## 安裝與啟動

```sh
cd /path/to/software_engineering_final_project
uv sync --extra dev
cp .env.example .env
uv run python -m app.init_db
uv run uvicorn app.main:app --reload
```

開啟 `http://127.0.0.1:8000`。老師控制台位於 `/teacher`，學生加入頁位於 `/student`，健康檢查為 `/health`。SQLite 資料庫預設建立在 `data/classroom_quiz.sqlite3`；應用程式啟動時會自動套用遷移。手動初始化命令可重複執行。

從 repository 根目錄啟動命令，讓應用程式載入根目錄 `.env`。`.env`、資料庫、虛擬環境及 `credential/` 已列入 `.gitignore`。`.env.example` 只提供路徑範例，絕不放金鑰內容。

## 使用流程

1. 老師提供 Guided Notes Google Sheet 連結建立房間；可設定 Q3,Q4 等題組、每組獲勝題數上限與得題冷卻秒數（預設 30，範圍 0–3600，0 停用）。
2. 把房間代碼和學生加入網址提供給各組；每組以共用組名加入。同組只允許一個有效視窗，原視窗可使用工作階段 token 重連。
3. 老師開始搶答後，學生填寫題目或題組並送出。題組答案會以一筆原子提交處理；其他學生不會收到答案、作答狀態或排名。
4. 老師可查看即時候選順位並駁回無效答案。系統自動略過被駁回或超過獲勝上限的候選，更新得主與排行榜。
5. 老師結束活動後，所有學生可查看結果。老師可下載完整歷史 CSV，並可將得主答案回填至原 Google Sheet；系統會檢查儲存格是否遭外部修改，確認後才一次批次寫入原表。
6. 老師可開啟房間建立時提供的投影連結；投影頁會顯示開始倒數、各題得主及組別得分，不含控制按鈕。

老師控制台使用單一即時進度面板與單一結果面板；學生在活動結束前只看得到自己的送出狀態，結束後作答表單會收起並顯示全班得主答案（未有人取得的題目標示「無得主」）。

### Guided Notes 範本

系統從 Google Sheet 讀取題號與答案空格欄位，也支援 `[Q1]` 這類填空標籤；建立房間時會將必要的題目結構與欄位映射保存在房間資料中。回填直接寫入原始 Google Sheet，不產生講義副本。驗收用的解析器範本 fixture 位於 `tests/fixtures/`。

冷卻從組別成為目前有效得主時開始；題組一次得主事件只開始一次冷卻，但題組內每題仍分別計入獲勝上限。駁回得主會重算得主，解除已失效且沒有其他有效得主來源的原組冷卻，並為遞補組別啟動冷卻。冷卻期限由伺服器交易判斷，學生頁倒數僅供顯示。

建立 Google Cloud 專案並啟用 Google Sheets API，建立 Service Account，將來源試算表分享給該 Service Account 電子郵件；若要回填，請授予編輯權限。老師貼標準格式 `https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit`，也可用 `?gid=工作表ID` 或 `#gid=工作表ID` 指定工作表。系統只接受 HTTPS 的 `docs.google.com/spreadsheets/d/...` 連結。將 Service Account JSON 放入被忽略的 `credential/` 目錄，在 `.env` 設定相對於 repository 根目錄的路徑，例如 `GOOGLE_SERVICE_ACCOUNT_FILE=credential/service-account.json`。絕不可複製金鑰內容到 repo、文件、日誌或畫面。建立房間一律使用 Google Sheet；系統不提供 `.xlsx` 上傳或副本下載。

## 設定

| 變數 | 預設值 | 說明 |
| --- | --- | --- |
| `DATABASE_PATH` | `data/classroom_quiz.sqlite3` | SQLite 檔案位置 |
| `SESSION_TTL_SECONDS` | `300` | 組別閒置連線租約秒數 |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | 空 | Service Account JSON 檔案路徑；建立房間及回填 Google Sheets 必須設定 |

## 測試與檢查

```sh
uv run python -m pytest -q
node --check app/static/app.js
npm exec -- openspec instructions apply --change "simple-classroom-quiz-buzzer" --json
```

測試涵蓋 Guided Notes 結構解析、Google Sheets mock 匯入與原子回填、房間與單一組別會話、WebSocket 階段／冷卻同步與角色過濾、併發提交順位、題組原子性、審核遞補、獲勝上限、結果視圖、CSV 匯出及舊房間資料相容性。

## 部署注意

目前即時 WebSocket 連線管理器為單一 Python 程序內的記憶體 fan-out，部署時請使用單一 ASGI worker。SQLite 適用於課堂專案或單機部署；若需多程序或多台主機，需換成共享即時訊息傳遞與集中式持久化服務。

房間老師、組別與投影憑證皆由伺服端隨機產生；資料庫只保存雜湊。投影憑證放在 URL fragment（`#` 後），不會隨頁面 HTTP 請求送出或進入一般 access log。不要將真實憑證提交到版本庫。
