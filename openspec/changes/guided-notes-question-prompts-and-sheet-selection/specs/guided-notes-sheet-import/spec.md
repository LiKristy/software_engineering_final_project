# Spec Delta

## Purpose

讓老師使用名稱不限的 Google Sheets 分頁建立 Guided Notes 房間，並保留題號、題目內容與答案格之間的對應，讓新題目可放在最新分頁而不必改名為「學習單」。

## ADDED Requirements

### Requirement: Select a valid Guided Notes worksheet

系統 SHALL 接受名稱不限的 Google Sheets 分頁作為題目來源；分頁須能辨識題號及答案格，題目文字欄可缺省。

#### Scenario: Explicit worksheet is selected by gid
- **WHEN** 老師提供包含有效 `gid` 的試算表連結，且指定分頁符合題號與答案格格式
- **THEN** 系統只從該分頁建立房間，不改選其他分頁

#### Scenario: Latest valid worksheet is selected without gid
- **WHEN** 老師未提供 `gid`，且試算表有一個或多個符合格式的分頁
- **THEN** 系統依分頁順序由最新分頁往前檢查，使用第一個符合格式的分頁建立房間

#### Scenario: No worksheet contains recognizable questions and answer cells
- **WHEN** 指定分頁不符合格式，或未指定分頁且所有分頁皆不符合格式
- **THEN** 系統顯示可理解的格式錯誤且不建立部分房間

### Requirement: Import question text and answer-slot mapping

系統 SHALL 將「題目」欄的文字與題號及答案格映射一併匯入；同題多列文字 SHALL 保留列順序及各列答案標記的對應。

#### Scenario: Single-row question text is imported
- **WHEN** 有效分頁包含題號、題目及作答欄
- **THEN** 系統將各題題目文字與題號及答案格一起保存

#### Scenario: Multiple rows belong to one question
- **WHEN** 同一題號跨多列，且各列有題目文字及不同答案標記
- **THEN** 系統保留原列順序及題目文字與答案標記的逐列對應

#### Scenario: Question text column is absent or blank
- **WHEN** 有效分頁能辨識題號與答案格，但缺少「題目」欄或題目文字為空
- **THEN** 系統仍可建立房間，該題維持空白題目內容
