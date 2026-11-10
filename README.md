# 簡課堂搶答系統

以 Python、FastAPI、SQLite、WebSocket 與原生 HTML/CSS/JavaScript 建置的課堂分組搶答系統。老師上傳 Guided Notes `.xlsx` 範本建立房間，學生以房間代碼和組名加入；提交、審核、排名、結果與匯出由伺服端處理。

## 環境需求

- Python 3.11 以上
- Node.js/npm（執行 OpenSpec 命令時使用）
- `uv` 套件管理工具

## 安裝與啟動

```sh
uv sync --extra dev
uv run python -m app.init_db
uv run uvicorn app.main:app --reload
```

開啟 `http://127.0.0.1:8000`。老師控制台位於 `/teacher`，學生加入頁位於 `/student`，健康檢查為 `/health`。SQLite 資料庫預設建立在 `data/classroom_quiz.sqlite3`；應用程式啟動時會自動套用遷移。手動初始化命令可重複執行。

複製 `.env.example` 為 `.env` 可調整本機設定；`.env`、資料庫和虛擬環境已列入 `.gitignore`。範例設定不放任何憑證。

## 使用流程

1. 老師上傳 Guided Notes 單題或題組 `.xlsx` 範本，可設定 Q3,Q4 等題組，以及每組獲勝題數上限。
2. 把房間代碼和學生加入網址提供給各組；每組以共用組名加入。同組只允許一個有效視窗，原視窗可使用工作階段 token 重連。
3. 老師開始搶答後，學生填寫題目或題組並送出。題組答案會以一筆原子提交處理；其他學生不會收到答案、作答狀態或排名。
4. 老師可查看即時候選順位並駁回無效答案。系統自動略過被駁回或超過獲勝上限的候選，更新得主與排行榜。
5. 老師結束活動後，所有學生可查看結果。老師可下載完整歷史 CSV，或下載自動回填得主答案的 Guided Notes 副本。
6. 老師可開啟房間建立時提供的投影連結；投影頁會顯示開始倒數、各題得主及組別得分，不含控制按鈕。

### Guided Notes 範本

匯入器讀取工作表「學習單」的「題號」與「作答」欄位，也支援 `[Q1]` 這類填空標籤。原始檔保存在房間資料中，回填匯出會產生新檔，不會修改原始範本。驗收用的公開範本副本位於 `tests/fixtures/`。

## 設定

| 變數 | 預設值 | 說明 |
| --- | --- | --- |
| `DATABASE_PATH` | `data/classroom_quiz.sqlite3` | SQLite 檔案位置 |
| `MAX_UPLOAD_BYTES` | `10485760` | 上傳檔案大小上限（10 MiB） |
| `SESSION_TTL_SECONDS` | `300` | 組別閒置連線租約秒數 |

## 測試與檢查

```sh
uv run python -m pytest -q
node --check app/static/app.js
npm exec -- openspec instructions apply --change "simple-classroom-quiz-buzzer" --json
```

測試涵蓋實際 Guided Notes 範本解析、房間與單一組別會話、WebSocket 階段同步與角色過濾、併發提交順位、題組原子性、審核遞補、獲勝上限、CSV/XLSX 匯出及上傳限制。

## 部署注意

目前即時 WebSocket 連線管理器為單一 Python 程序內的記憶體 fan-out，部署時請使用單一 ASGI worker。SQLite 適用於課堂專案或單機部署；若需多程序或多台主機，需換成共享即時訊息傳遞與集中式持久化服務。

房間老師、組別與投影憑證皆由伺服端隨機產生；資料庫只保存雜湊。投影憑證放在 URL fragment（`#` 後），不會隨頁面 HTTP 請求送出或進入一般 access log。不要將真實憑證提交到版本庫。
