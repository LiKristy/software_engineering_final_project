ALTER TABLE questions ADD COLUMN question_number TEXT NOT NULL DEFAULT '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_questions_room_number
    ON questions(room_id, question_number);
