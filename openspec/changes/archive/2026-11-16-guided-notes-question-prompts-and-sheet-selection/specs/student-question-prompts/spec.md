# Spec Delta

## Purpose

讓學生在搶答開始後看到題號及對應題目內容，並在等待階段隱藏題目文字，避免尚未開始時提前取得題目。多列題目亦需依來源順序，對應顯示各自的答案標記。

## ADDED Requirements

### Requirement: Reveal question text only after the race starts

系統 SHALL 在搶答等待階段不向學生介面或學生可存取的題目回應提供題目文字，並 SHALL 在搶答開始後同時顯示題號與題目內容。

#### Scenario: Student waits for the race
- **WHEN** 房間仍處於等待階段
- **THEN** 學生只能看到題號與鎖定的作答欄，題目文字不出現在畫面或學生可存取的題目回應中

#### Scenario: Teacher starts the race
- **WHEN** 老師開始搶答且學生收到階段更新
- **THEN** 學生端顯示每題題號與對應題目內容，並解鎖作答欄

#### Scenario: Student joins an active room
- **WHEN** 學生加入已開始搶答的房間
- **THEN** 初始題目畫面同時顯示題號與題目內容

### Requirement: Preserve question text row and answer-marker correspondence

系統 SHALL 依原試算表列順序顯示同一題號的多列題目內容，並保留每列題目與答案標記的對應。

#### Scenario: A question has multiple answer parts
- **WHEN** 同一題號有多列題目文字，並各自對應 `(1)`、`(2)` 等答案標記
- **THEN** 學生端於該題號下依序分行顯示題目文字及其標記

#### Scenario: A question has no prompt text
- **WHEN** 題目沒有匯入到題目文字
- **THEN** 學生端仍顯示題號及既有答案欄位，其他題目的內容不受影響
