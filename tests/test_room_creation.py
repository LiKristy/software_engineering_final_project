from pathlib import Path
import pytest

from fastapi.testclient import TestClient

from app.api import get_google_sheets_adapter, get_room_service
from app.database import Database
from app.main import app
from app.repositories.room_repository import RoomRepository
from app.services.room_service import RoomService


SINGLE = Path("tests/fixtures/guided-notes-single.xlsx")
SHEET_URL = "https://docs.google.com/spreadsheets/d/1dHJOnfihH0J2OPeqzkMofJD17TXMsT10PfVDbCqW7aQ/edit?gid=77"


class FakeGoogleAdapter:
    def __init__(self, status=None):
        self.status = status
        self.calls = 0

    def import_sheet(self, reference):
        self.calls += 1
        assert reference.spreadsheet_id == "1dHJOnfihH0J2OPeqzkMofJD17TXMsT10PfVDbCqW7aQ"
        if self.status:
            from app.services.google_sheets import GoogleSheetsError
            raise GoogleSheetsError("mock failure", self.status)
        return SINGLE.read_bytes(), "學習單", 77


def install_overrides(database, adapter=None):
    app.dependency_overrides[get_room_service] = lambda: RoomService(RoomRepository(database))
    app.dependency_overrides[get_google_sheets_adapter] = lambda: adapter or FakeGoogleAdapter()


def test_create_room_from_template_and_store_tokens_as_hashes(tmp_path):
    database = Database(tmp_path / "rooms.sqlite3")
    database.migrate()
    install_overrides(database)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/rooms",
                data={"sheet_url": SHEET_URL, "max_wins": "2", "question_bundles": '[["Q3", "Q4"]]'},
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
    assert room["cooldown_seconds"] == 30
    assert room["teacher_token_hash"] != payload["teacher_token"]
    assert q3["bundle_id"] == "bundle:Q3:Q4"


def test_create_room_rejects_file_upload_without_sheet_url(tmp_path):
    database = Database(tmp_path / "rooms.sqlite3")
    database.migrate()
    install_overrides(database)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/rooms", files={"file": ("bad.xlsx", b"not a workbook", "application/octet-stream")}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0


def test_create_room_rejects_cooldown_outside_allowed_range(tmp_path):
    database = Database(tmp_path / "invalid-cooldown.sqlite3")
    database.migrate()
    install_overrides(database)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/rooms",
                data={"sheet_url": SHEET_URL, "cooldown_seconds": "3601"},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0


def test_create_room_rejects_overlapping_question_bundles(tmp_path):
    database = Database(tmp_path / "rooms.sqlite3")
    database.migrate()
    install_overrides(database)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/rooms",
                data={"sheet_url": SHEET_URL, "question_bundles": '[["Q3", "Q4"], ["Q4", "Q5"]]'},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0


def test_one_group_session_can_resume_but_a_second_window_is_rejected(tmp_path):
    database = Database(tmp_path / "rooms.sqlite3")
    database.migrate()
    install_overrides(database)
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/rooms", data={"sheet_url": SHEET_URL}
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


def test_create_room_from_google_sheet_stores_mapping_and_internal_parser_workbook(tmp_path):
    database = Database(tmp_path / "google.sqlite3")
    database.migrate()
    install_overrides(database)
    try:
        with TestClient(app) as client:
            response = client.post("/api/rooms", data={"sheet_url": SHEET_URL})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    with database.connect() as connection:
        room = connection.execute("SELECT source_type, google_spreadsheet_id, google_sheet_gid, workbook_blob FROM rooms").fetchone()
        slots = connection.execute("SELECT COUNT(*) FROM answer_slots WHERE imported_baseline_value IS NOT NULL").fetchone()[0]
    assert room["source_type"] == "google_sheet"
    assert room["google_spreadsheet_id"] == "1dHJOnfihH0J2OPeqzkMofJD17TXMsT10PfVDbCqW7aQ"
    assert room["google_sheet_gid"] == 77
    assert bytes(room["workbook_blob"])
    assert slots == 0


@pytest.mark.parametrize(("status", "expected"), [("permission_denied", 403), ("invalid_sheet", 400)])
def test_google_sheet_import_failure_does_not_create_partial_room(tmp_path, status, expected):
    database = Database(tmp_path / "failed-google.sqlite3")
    database.migrate()
    adapter = FakeGoogleAdapter(status)
    install_overrides(database, adapter)
    try:
        with TestClient(app) as client:
            response = client.post("/api/rooms", data={"sheet_url": SHEET_URL})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == expected
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0


def test_invalid_google_url_does_not_call_adapter_or_create_room(tmp_path):
    database = Database(tmp_path / "invalid-url.sqlite3")
    database.migrate()
    adapter = FakeGoogleAdapter()
    install_overrides(database, adapter)
    try:
        with TestClient(app) as client:
            response = client.post("/api/rooms", data={"sheet_url": "https://example.com/spreadsheets/d/1dHJOnfihH0J2OPeqzkMofJD17TXMsT10PfVDbCqW7aQ/edit"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 400
    assert adapter.calls == 0
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0


def test_existing_upload_room_records_remain_readable(tmp_path):
    database = Database(tmp_path / "legacy-room.sqlite3")
    database.migrate()
    service = RoomService(RoomRepository(database))
    legacy = service.create_room(SINGLE.read_bytes(), "legacy.xlsx", source_type="upload")
    install_overrides(database)
    try:
        with TestClient(app) as client:
            room = client.get(f"/api/rooms/{legacy['room_id']}")
            results = client.get(
                f"/api/rooms/{legacy['room_id']}/results",
                headers={"X-Teacher-Token": legacy["teacher_token"]},
            )
    finally:
        app.dependency_overrides.clear()
    assert room.status_code == 200 and room.json()["status"] == "waiting"
    assert results.status_code == 200 and len(results.json()["questions"]) == 6


def test_google_sheet_backfill_requires_teacher_authentication(tmp_path):
    database = Database(tmp_path / "auth-google.sqlite3")
    database.migrate()
    install_overrides(database)
    try:
        with TestClient(app) as client:
            room = client.post("/api/rooms", data={"sheet_url": SHEET_URL}).json()
            response = client.post(f"/api/rooms/{room['room_id']}/google-sheet/backfill")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403
