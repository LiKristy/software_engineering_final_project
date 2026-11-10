# Spec Delta

## Purpose

讓老師與學生在活動結束後查看一致的正式搶答結果，並讓老師匯出包含提交明細與伺服器排名依據的 CSV 留存課堂紀錄。

## ADDED Requirements

### Requirement: Publish results when the race ends
系統 SHALL 在老師結束搶答後向所有學生公布每題得主組別與其答案，並同步顯示審核或順位遞補後的最新結果。

#### Scenario: Students see final winners
- **WHEN** 老師結束搶答且 Q1 至 Q5 均已完成仲裁
- **THEN** 全部學生端切換至結果頁並列出每題第一名組別與其答案

#### Scenario: Question has no winner
- **WHEN** 活動結束時某題沒有有效且符合資格的提交
- **THEN** 結果頁將該題顯示為無得主，不虛構答案

#### Scenario: Winner changes after rejection
- **WHEN** 老師於結果面板駁回目前得主
- **THEN** 老師及全班學生的結果看板同步顯示遞補後得主及答案

### Requirement: Export race history as CSV
系統 SHALL 允許老師匯出本場搶答提交明細為 CSV，欄位包含題號、組別、送出答案、伺服器接收時間與搶答排名。

#### Scenario: Teacher downloads race history
- **WHEN** 老師點擊「匯出紀錄」
- **THEN** 瀏覽器下載本場 CSV，且每筆提交包含題號、組別、答案、伺服器接收時間及排名

#### Scenario: Question-group submission is represented
- **WHEN** 匯出包含題組提交的活動紀錄
- **THEN** CSV 保留題組內各題答案與其共同提交順序，使各題結果可追溯
