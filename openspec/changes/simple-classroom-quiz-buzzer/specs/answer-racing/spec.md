# Spec Delta

## Purpose

支援學生組別對匯入題目進行即時搶答，依伺服器接收順序公平排列候選答案，並讓老師審核、遞補及限制每組獲勝題數。

## ADDED Requirements

### Requirement: Submit answers by group
系統 SHALL 允許已加入且目前可作答的組別提交答案，並以組別及題目為單位防止重複提交。

#### Scenario: Group submits one answer
- **WHEN** 活動進行中，組別填寫 Q1 並送出
- **THEN** 系統接受該組 Q1 答案，且該題顯示「已送出」

#### Scenario: Duplicate submission is prevented
- **WHEN** 同組再次提交已送出的題目，或活動已結束後送出答案
- **THEN** 系統拒絕重複或逾期提交，且不改變原提交順位

#### Scenario: Same-group window sees submitted state
- **WHEN** 組別的有效視窗提交題目
- **THEN** 該組房間狀態同步為已送出，並顯示「已送出」

### Requirement: Submit a question group atomically
系統 SHALL 要求題組中所有題目皆已填答後，才接受該組題目的一次性提交與順位仲裁。

#### Scenario: Incomplete question group cannot be submitted
- **WHEN** 學生尚未填完 Q3、Q4 中任一題便送出該題組
- **THEN** 系統提示缺漏題目且不接受提交

#### Scenario: Complete question group is submitted once
- **WHEN** 學生填妥 Q3、Q4 並按下該題組送出按鈕
- **THEN** 系統以同一提交時間對 Q3、Q4 原子接受或拒絕，不拆分題組順位

#### Scenario: Rejection applies to a bundled submission
- **WHEN** 老師駁回包含 Q3、Q4 的同一題組提交
- **THEN** 系統將該組在題組中的兩題一併視為駁回，並對兩題遞補同一個下一順位合格組別

### Requirement: Keep answers private during the race
系統 SHALL 僅向提交組別與老師提供其答案內容，且在活動結束前不得向其他學生組別揭露答案或組別作答進度。

#### Scenario: Other students cannot see active submissions
- **WHEN** 一組已提交答案而搶答仍在進行
- **THEN** 其他組別看不到該答案、提交狀態或即時排名

#### Scenario: Teacher sees live progress
- **WHEN** 活動進行且有組別提交答案
- **THEN** 老師端即時看到各題候選組別與順位，但學生端不收到這些資訊

### Requirement: Rank submissions by server receipt order
系統 SHALL 以伺服器接收提交的順序仲裁排名，記錄伺服器接收時間，並以穩定處理序列區分時間精度相同的提交。

#### Scenario: Concurrent submissions receive deterministic ranks
- **WHEN** 不同組別近乎同時提交同一題
- **THEN** 系統依伺服器處理序列指定第 1 名、第 2 名及後續順位，並記錄其接收時間與順位

### Requirement: Teacher reviews and rejects candidates
系統 SHALL 允許老師將候選答案標記為有效或駁回，並在候選被駁回時自動將得主遞補至下一個有效且符合資格的組別。

#### Scenario: First candidate is rejected
- **WHEN** 老師駁回 Q1 第一順位候選答案
- **THEN** 系統將 Q1 得主遞補為下一順位有效且符合資格的組別，並同步更新結果

#### Scenario: Rejection advances through candidates
- **WHEN** 多個較前順位候選答案被老師駁回
- **THEN** 系統依序略過已駁回候選並選出下一個有效合格組別，若無候選則標示無得主

### Requirement: Enforce per-group win limit
系統 SHALL 允許老師為活動設定每組獲勝題數上限，並使超過上限或剩餘額度不足以涵蓋完整題組的候選失去該題或題組的得主資格。

#### Scenario: Group reaches configured cap
- **WHEN** 組別已獲勝題數達到設定上限，且該組更早提交其他題目
- **THEN** 系統略過該組作為新得主的資格，將得主遞補給下一順位有效且未達上限的組別

#### Scenario: Group has insufficient capacity for a bundle
- **WHEN** 題組包含兩題而組別僅剩一題獲勝額度
- **THEN** 系統不拆分題組或授予部分得主，並將題組得主資格遞補給下一順位符合資格的組別

#### Scenario: Bundle wins count each question
- **WHEN** 組別贏得包含兩題的題組
- **THEN** 系統將該組獲勝題數增加二
