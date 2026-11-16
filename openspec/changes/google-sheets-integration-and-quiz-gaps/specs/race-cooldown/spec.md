# Spec Delta

## Purpose

以得主冷卻時間限制單一組別連續參與搶答，並讓老師能依課程節奏設定限制，讓各組有公平作答機會。

## ADDED Requirements

### Requirement: Configure room cooldown duration
系統 SHALL 允許老師在建立房間時設定 0 至 3600 秒的得主冷卻時間，未設定時使用 30 秒，設定為 0 時停用冷卻。

#### Scenario: Default cooldown is applied
- **WHEN** 老師建立房間但未指定冷卻秒數
- **THEN** 房間使用 30 秒冷卻

#### Scenario: Teacher chooses a cooldown duration
- **WHEN** 老師建立房間並設定有效的非負冷卻秒數
- **THEN** 房間保存並套用該冷卻時間

#### Scenario: Invalid cooldown is rejected
- **WHEN** 老師設定負數或超出系統允許範圍的冷卻秒數
- **THEN** 系統拒絕建立房間並指出設定錯誤

### Requirement: Pause a winning group during cooldown
系統 SHALL 在組別被仲裁為目前有效得主後啟動冷卻；冷卻期間該組不得提交新的題目或題組，伺服器 SHALL 以伺服器時間判斷是否仍在冷卻。

#### Scenario: Winner enters cooldown
- **WHEN** 組別取得單題或完整題組得主資格且房間冷卻秒數大於零
- **THEN** 系統從得主資格生效時間起暫停該組新的搶答提交

#### Scenario: Submission is attempted during cooldown
- **WHEN** 冷卻尚未結束的組別提交新題目或題組
- **THEN** 系統拒絕提交、不配置順位，並回傳剩餘冷卻秒數

#### Scenario: Cooldown expires
- **WHEN** 伺服器時間已達該組冷卻結束時間
- **THEN** 系統恢復該組提交權限

#### Scenario: Cooldown is disabled
- **WHEN** 房間冷卻秒數為零
- **THEN** 得主取得題目後仍可提交其他尚未提交的題目

### Requirement: Synchronize cooldown status to the group
系統 SHALL 將組別目前的冷卻狀態與結束時間提供給該組介面，並在重連快照中恢復正確狀態。

#### Scenario: Group sees remaining cooldown
- **WHEN** 組別進入冷卻或重新連線時仍在冷卻
- **THEN** 該組介面顯示冷卻剩餘時間並停用新題目送出控制

#### Scenario: Other groups do not receive private cooldown state
- **WHEN** 某組進入冷卻
- **THEN** 其他組別不會收到該組名稱、冷卻時間或作答狀態

### Requirement: Rejection removes cooldown from an invalid winner
系統 SHALL 在老師駁回造成冷卻來源得主失效時，重新計算該組可用狀態，並對遞補得主套用房間冷卻。

#### Scenario: Rejected winner no longer owns the cooldown
- **WHEN** 老師駁回目前得主且該得主沒有其他仍有效的冷卻來源
- **THEN** 系統解除其由該得主資格產生的剩餘冷卻，並開始遞補得主的冷卻
