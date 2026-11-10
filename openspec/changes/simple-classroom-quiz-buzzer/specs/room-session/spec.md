# Spec Delta

## Purpose

提供課堂搶答的房間與組別連線基礎，讓老師能控制同一場活動，並讓學生組別以唯一身分加入且接收一致的階段狀態。

## ADDED Requirements

### Requirement: Teacher creates a room
系統 SHALL 允許老師以匯入的 Guided Notes 建立房間，並產生可供學生加入的房間代碼。

#### Scenario: Room is created
- **WHEN** 老師成功匯入有效的單題或題組 Guided Notes 並建立房間
- **THEN** 系統建立房間、保留匯入題目與題組結構，並顯示房間代碼

### Requirement: Student joins a room as a group
系統 SHALL 允許學生輸入有效房間代碼與組名加入房間，並即時將已加入組別顯示於老師端。

#### Scenario: Group joins successfully
- **WHEN** 學生輸入有效房間代碼及尚未加入的組名
- **THEN** 該組加入房間，老師端即時顯示該組名稱

#### Scenario: Invalid room code
- **WHEN** 學生輸入不存在或已不可加入的房間代碼
- **THEN** 系統拒絕加入並顯示可理解的錯誤訊息

### Requirement: One active window per group
系統 SHALL 限制同一房間中的每個組別只能有一個有效加入視窗，避免同組重複參賽。

#### Scenario: Duplicate group window is rejected
- **WHEN** 已加入的組別從另一個視窗再次嘗試加入同一房間
- **THEN** 系統拒絕新的加入並告知該組已在房間中

### Requirement: Room stage is synchronized
系統 SHALL 將房間活動階段同步至老師與所有已加入學生端，並依階段控制學生的作答權限。

#### Scenario: Waiting stage locks answers
- **WHEN** 學生加入一個尚未開始搶答的房間
- **THEN** 學生端顯示「等待搶答」且作答輸入介面鎖定

#### Scenario: Teacher starts the race
- **WHEN** 老師點擊「開始搶答」
- **THEN** 全部已連線學生端即時顯示進行中階段並解鎖可作答題目

#### Scenario: Teacher ends the race
- **WHEN** 老師點擊「結束搶答」
- **THEN** 全部已連線學生端即時鎖定作答介面並切換至結果頁

#### Scenario: Reconnected client receives current stage
- **WHEN** 已加入房間的用戶端重新連線
- **THEN** 系統傳送目前房間階段及該組已提交狀態，使介面恢復至正確狀態
