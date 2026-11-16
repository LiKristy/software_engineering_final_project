# Spec Delta

## Purpose

讓學生在搶答結束後清楚查看正式結果，並確保老師、學生與投影畫面依相同得主資料呈現最新結果。

## ADDED Requirements

### Requirement: Switch student interface to the final results view
系統 SHALL 在活動結束時將學生介面切換為結果視圖，並隱藏或移除作答表單。

#### Scenario: Race ends with winners
- **WHEN** 老師結束活動
- **THEN** 所有已連線學生端顯示各題得主組別及其有效答案，且不再顯示可作答表單

#### Scenario: Some questions have no winner
- **WHEN** 活動結束時某題沒有有效且符合獲勝上限的提交
- **THEN** 結果視圖明確顯示該題「無得主」且不顯示答案

#### Scenario: Student reconnects after the race ended
- **WHEN** 學生在活動結束後重新連線
- **THEN** 系統直接恢復結果視圖與目前伺服器結果，不重新顯示作答表單

### Requirement: Synchronize reviewed results across classroom views
系統 SHALL 在老師駁回得主或順位遞補後更新老師、學生與投影視圖中的同一組結果。

#### Scenario: Winner is rejected after results are published
- **WHEN** 老師駁回目前得主並由下一順位候選遞補
- **THEN** 老師、所有學生與投影端即時顯示遞補後的得主與答案

#### Scenario: Results views do not expose active answers early
- **WHEN** 活動仍在進行中
- **THEN** 學生端不得顯示結果視圖、其他組別答案或即時候選順位
