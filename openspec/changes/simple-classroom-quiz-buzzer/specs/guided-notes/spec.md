# Spec Delta

## Purpose

讓老師直接以提供的單題及題組 Guided Notes 範本建立搶答題目，並在活動後把得主答案填回對應空格，產生可留存或發放的已完成講義。

## ADDED Requirements

### Requirement: Import Guided Notes question structure
系統 SHALL 依提供的單題與題組 Guided Notes 範本匯入題號、題組關係及各題答案空格標記，題數 SHALL 與來源講義一致，且不要求匯入題目敘述。系統 SHALL 支援範本中的題號欄與空白作答欄，也 SHALL 能辨識明確的 `[Q1]` 類題號填空標籤。

#### Scenario: Single-question template is imported
- **WHEN** 老師匯入符合單題範本的 Guided Notes
- **THEN** 系統依範本建立相同題數的題目，學生介面以題號呈現，不要求題目敘述

#### Scenario: Question-group template is imported
- **WHEN** 老師匯入符合題組範本且標示題組的 Guided Notes
- **THEN** 系統保留題號與題組歸屬，供學生一次填寫及提交該題組

#### Scenario: Multiple answer slots belong to one question number
- **WHEN** 題組範本在同一題號下列出多個標記空格，例如 (1) 與 (2)
- **THEN** 系統保留各空格標記及其位置，並讓學生分別填答

#### Scenario: Explicit question placeholder is imported
- **WHEN** 範本以 `[Q1]` 形式標示答案填空
- **THEN** 系統將該填空映射至 Q1，且不把其他題目的答案寫入該處

#### Scenario: Unsupported or malformed template
- **WHEN** 上傳檔案無法依單題或題組範本辨識題號或空格
- **THEN** 系統指出無法辨識的格式或題目位置，且不建立不完整房間

### Requirement: Render answer fields from imported questions
系統 SHALL 依匯入的 Guided Notes 題號與答案空格標記產生對應答案欄位，且同一題組的題目 SHALL 同置於一個可辨識的題組卡片。

#### Scenario: Questions are rendered
- **WHEN** 學生加入已匯入五題的房間
- **THEN** 學生端顯示 Q1 至 Q5 的文字答案欄位

#### Scenario: Group questions are rendered together
- **WHEN** 匯入內容將 Q3、Q4 標示為同一題組
- **THEN** 學生端將 Q3、Q4 放在同一題組卡片中

#### Scenario: Multiple answer slots are individually editable
- **WHEN** 一個題號有多個標記答案空格
- **THEN** 學生端在該題號下為每個空格標記提供獨立文字欄位

### Requirement: Export answers into a Guided Notes copy
系統 SHALL 將各題有效得主答案依題號及空格標記寫入來源 Guided Notes 對應填空格，並下載已填妥的講義副本，不得覆寫原始講義。

#### Scenario: Successful answer-sheet export
- **WHEN** 老師匯出已完成的 Guided Notes
- **THEN** 輸出副本的每個得主答案出現在原題對應填空格，且題目及版面內容獲保留

#### Scenario: Question has no valid winner
- **WHEN** 匯出時某題沒有有效得主
- **THEN** 輸出副本保留該題原本空格
