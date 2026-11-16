CREATE TABLE IF NOT EXISTS question_prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    row_order INTEGER NOT NULL,
    answer_marker TEXT NOT NULL DEFAULT '',
    prompt_text TEXT NOT NULL,
    UNIQUE (question_id, row_order)
);

CREATE INDEX IF NOT EXISTS idx_question_prompts_question_order
    ON question_prompts(question_id, row_order);
