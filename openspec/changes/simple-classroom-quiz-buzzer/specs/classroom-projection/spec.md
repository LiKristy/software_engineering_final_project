# Spec Delta

## Purpose

提供適合教室大螢幕的專用搶答展示介面，清楚呈現活動進度與競賽結果，同時避免投影畫面誤觸教師控制操作。

## ADDED Requirements

### Requirement: Provide a dedicated projection view
系統 SHALL 提供老師可另行開啟的投影專用網址，使用放大介面並隱藏房間控制按鈕。

#### Scenario: Teacher opens projection view
- **WHEN** 老師開啟本場活動的投影專用網址
- **THEN** 系統顯示大字體投影介面且不顯示開始、結束或審核等控制按鈕

### Requirement: Display live classroom race information
投影視圖 SHALL 顯示搶答倒數動畫、各題得主看板及組別得分排行榜，並即時同步活動結果。

#### Scenario: Race is active
- **WHEN** 活動進行中
- **THEN** 投影視圖顯示倒數動畫、已產生的題目得主資訊及即時更新的組別排行榜

#### Scenario: Race has ended
- **WHEN** 老師結束活動或審核造成得主變動
- **THEN** 投影視圖同步顯示最新的各題得主看板與組別得分排行榜
