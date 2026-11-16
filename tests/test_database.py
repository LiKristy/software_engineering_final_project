from app.database import Database


def test_migrations_create_schema_and_are_idempotent(tmp_path):
    database = Database(tmp_path / "test.sqlite3")

    database.migrate()
    database.migrate()

    with database.connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        versions = connection.execute(
            "SELECT version FROM schema_migrations"
        ).fetchall()

    assert {"rooms", "groups", "questions", "answer_slots", "submissions", "submission_answers", "question_prompts"} <= tables
    assert len(versions) == 4
    with database.connect() as connection:
        room_columns = {row["name"] for row in connection.execute("PRAGMA table_info(rooms)")}
        slot_columns = {row["name"] for row in connection.execute("PRAGMA table_info(answer_slots)")}
        group_columns = {row["name"] for row in connection.execute("PRAGMA table_info(groups)")}
    assert {"source_type", "google_spreadsheet_id", "google_sheet_gid", "cooldown_seconds"} <= room_columns
    assert {"imported_baseline_value", "last_written_value"} <= slot_columns
    assert {"cooldown_until", "cooldown_source_submission_id"} <= group_columns


def test_transaction_rolls_back_on_error(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    database.migrate()

    try:
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO rooms "
                "(id, teacher_token_hash, projection_token_hash, workbook_name, workbook_blob, created_at) "
                "VALUES ('room', 'teacher', 'projection', 'notes.xlsx', X'00', 'now')"
            )
            raise RuntimeError("rollback")
    except RuntimeError:
        pass

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0


def test_existing_upload_rooms_remain_readable_after_additive_migration(tmp_path):
    database = Database(tmp_path / "existing.sqlite3")
    # Build the schema exactly as a pre-change database would have looked.
    with database.connect() as connection:
        connection.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        from pathlib import Path

        migration_dir = Path("app/migrations")
        for version in (1, 2):
            migration = next(migration_dir.glob(f"{version:03d}_*.sql"))
            connection.executescript(migration.read_text(encoding="utf-8"))
            connection.execute("INSERT INTO schema_migrations VALUES (?, 'old')", (version,))
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO rooms (id, teacher_token_hash, projection_token_hash, workbook_name, workbook_blob, created_at) "
            "VALUES ('old-room', 't', 'p', 'notes.xlsx', X'00', 'now')"
        )
        connection.execute(
            "INSERT INTO groups (id, room_id, name, name_key, session_token_hash, lease_expires_at, joined_at) "
            "VALUES ('old-group', 'old-room', '第 1 組', '第 1 組', 'g', 9999999999, 'now')"
        )
        connection.execute(
            "INSERT INTO questions (id, room_id, question_number, bundle_id, ordinal) "
            "VALUES ('old-room:Q1', 'old-room', 'Q1', 'Q1', 1)"
        )
    database.migrate()
    with database.connect() as connection:
        room = connection.execute("SELECT source_type, cooldown_seconds FROM rooms WHERE id='old-room'").fetchone()
        assert tuple(room) == ("upload", 0)
        assert connection.execute("SELECT COUNT(*) FROM groups WHERE room_id='old-room'").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM questions WHERE room_id='old-room'").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM question_awards").fetchone()[0] == 0
    from app.repositories.room_repository import RoomRepository
    old_questions = RoomRepository(database).get_questions("old-room")
    assert old_questions[0]["id"] == "Q1"
    assert old_questions[0]["prompts"] == []
