from pathlib import Path

from fastapi.testclient import TestClient

from app.api import get_room_service
from app.database import Database
from app.main import app
from app.repositories.room_repository import RoomRepository
from app.services.room_service import RoomService


SINGLE = Path("tests/fixtures/guided-notes-single.xlsx")


def test_create_room_from_template_and_store_tokens_as_hashes(tmp_path):
    database = Database(tmp_path / "rooms.sqlite3")
    database.migrate()
    app.dependency_overrides[get_room_service] = lambda: RoomService(RoomRepository(database))
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/rooms",
                files={"file": ("single.xlsx", SINGLE.read_bytes(), "application/octet-stream")},
                data={"max_wins": "2", "question_bundles": '[["Q3", "Q4"]]'},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["room_id"]) == 6
    assert payload["question_count"] == 6
    assert payload["teacher_token"]
    assert payload["projection_url"].startswith("/projector/")
    assert payload["questions"][2]["bundle_id"] == "bundle:Q3:Q4"
    with database.connect() as connection:
        room = connection.execute("SELECT * FROM rooms WHERE id = ?", (payload["room_id"],)).fetchone()
        q3 = connection.execute("SELECT bundle_id FROM questions WHERE room_id = ? AND question_number = 'Q3'", (payload["room_id"],)).fetchone()
    assert room["teacher_token_hash"] != payload["teacher_token"]
    assert q3["bundle_id"] == "bundle:Q3:Q4"


def test_create_room_rejects_invalid_file_without_partial_room(tmp_path):
    database = Database(tmp_path / "rooms.sqlite3")
    database.migrate()
    app.dependency_overrides[get_room_service] = lambda: RoomService(RoomRepository(database))
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/rooms", files={"file": ("bad.xlsx", b"not a workbook", "application/octet-stream")}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0


def test_create_room_enforces_configured_upload_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "32")
    database = Database(tmp_path / "large-upload.sqlite3")
    database.migrate()
    app.dependency_overrides[get_room_service] = lambda: RoomService(RoomRepository(database))
    try:
        with TestClient(app) as client:
            response = client.post("/api/rooms", files={"file": ("single.xlsx", SINGLE.read_bytes())})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 413


def test_create_room_rejects_overlapping_question_bundles(tmp_path):
    database = Database(tmp_path / "rooms.sqlite3")
    database.migrate()
    app.dependency_overrides[get_room_service] = lambda: RoomService(RoomRepository(database))
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/rooms",
                files={"file": ("single.xlsx", SINGLE.read_bytes(), "application/octet-stream")},
                data={"question_bundles": '[["Q3", "Q4"], ["Q4", "Q5"]]'},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0


def test_one_group_session_can_resume_but_a_second_window_is_rejected(tmp_path):
    database = Database(tmp_path / "rooms.sqlite3")
    database.migrate()
    app.dependency_overrides[get_room_service] = lambda: RoomService(RoomRepository(database))
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/rooms", files={"file": ("single.xlsx", SINGLE.read_bytes(), "application/octet-stream")}
            ).json()
            room_id = created["room_id"]
            joined = client.post(f"/api/rooms/{room_id}/join", json={"group_name": "第 1 組"})
            first = joined.json()
            duplicate = client.post(f"/api/rooms/{room_id}/join", json={"group_name": "第 1 組"})
            resumed = client.post(
                f"/api/rooms/{room_id}/join",
                json={"group_name": "第 1 組", "group_token": first["group_token"]},
            )
            no_teacher = client.get(f"/api/rooms/{room_id}/groups")
            groups = client.get(
                f"/api/rooms/{room_id}/groups",
                headers={"X-Teacher-Token": created["teacher_token"]},
            )
    finally:
        app.dependency_overrides.clear()

    assert joined.status_code == 200
    assert duplicate.status_code == 409
    assert resumed.status_code == 200 and resumed.json()["resumed"] is True
    assert no_teacher.status_code == 403
    assert groups.json()["groups"][0]["name"] == "第 1 組"
