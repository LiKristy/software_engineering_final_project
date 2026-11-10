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

    assert {"rooms", "groups", "questions", "answer_slots", "submissions", "submission_answers"} <= tables
    assert len(versions) == 2


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
