CREATE TABLE IF NOT EXISTS rooms (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'waiting' CHECK (status IN ('waiting', 'active', 'ended')),
    max_wins INTEGER CHECK (max_wins IS NULL OR max_wins > 0),
    teacher_token_hash TEXT NOT NULL,
    projection_token_hash TEXT NOT NULL,
    workbook_name TEXT NOT NULL,
    workbook_blob BLOB NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS groups (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    session_token_hash TEXT NOT NULL,
    lease_expires_at REAL NOT NULL,
    joined_at TEXT NOT NULL,
    UNIQUE (room_id, name_key)
);

CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    bundle_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    UNIQUE (room_id, id),
    UNIQUE (room_id, ordinal)
);

CREATE TABLE IF NOT EXISTS answer_slots (
    id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    marker TEXT NOT NULL DEFAULT '',
    worksheet_name TEXT NOT NULL,
    cell_coordinate TEXT NOT NULL,
    UNIQUE (room_id, question_id, marker)
);

CREATE TABLE IF NOT EXISTS submissions (
    receipt_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    bundle_id TEXT NOT NULL,
    received_at TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'rejected')),
    rejection_reason TEXT,
    UNIQUE (room_id, group_id, bundle_id)
);

CREATE TABLE IF NOT EXISTS submission_answers (
    submission_id TEXT NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    answer_slot_id TEXT NOT NULL REFERENCES answer_slots(id) ON DELETE CASCADE,
    answer_text TEXT NOT NULL,
    PRIMARY KEY (submission_id, answer_slot_id)
);

CREATE INDEX IF NOT EXISTS idx_groups_room ON groups(room_id);
CREATE INDEX IF NOT EXISTS idx_questions_room ON questions(room_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_submissions_room_sequence ON submissions(room_id, receipt_sequence);
CREATE INDEX IF NOT EXISTS idx_submissions_group ON submissions(room_id, group_id);
