ALTER TABLE rooms ADD COLUMN source_type TEXT NOT NULL DEFAULT 'upload';
ALTER TABLE rooms ADD COLUMN google_spreadsheet_id TEXT;
ALTER TABLE rooms ADD COLUMN google_sheet_gid INTEGER;
ALTER TABLE rooms ADD COLUMN cooldown_seconds INTEGER NOT NULL DEFAULT 0;

ALTER TABLE answer_slots ADD COLUMN imported_baseline_value TEXT;
ALTER TABLE answer_slots ADD COLUMN last_written_value TEXT;

ALTER TABLE groups ADD COLUMN cooldown_until REAL;
ALTER TABLE groups ADD COLUMN cooldown_source_submission_id TEXT;

CREATE TABLE IF NOT EXISTS question_awards (
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL,
    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    submission_id TEXT NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    awarded_at TEXT NOT NULL,
    cooldown_until REAL,
    PRIMARY KEY (room_id, question_id),
    FOREIGN KEY (room_id, question_id) REFERENCES questions(room_id, id) ON DELETE CASCADE
);
