from pathlib import Path

from fastapi.testclient import TestClient

from app.api import get_room_service
from app.database import Database
from app.main import app
from app.repositories.room_repository import RoomRepository
from app.services.room_service import RoomService


def test_student_and_teacher_pages_are_served():
    with TestClient(app) as client:
        student = client.get("/student")
        teacher = client.get("/teacher")

    assert student.status_code == teacher.status_code == 200
    assert 'data-page="student"' in student.text
    assert 'id="answer-board"' in student.text
    assert 'name="file"' in teacher.text


def test_question_api_returns_exact_fields_for_both_templates(tmp_path):
    database = Database(tmp_path / "ui.sqlite3")
    database.migrate()
    app.dependency_overrides[get_room_service] = lambda: RoomService(RoomRepository(database))
    try:
        with TestClient(app) as client:
            single = client.post(
                "/api/rooms", files={"file": ("single.xlsx", Path("tests/fixtures/guided-notes-single.xlsx").read_bytes())}
            ).json()
            group = client.post(
                "/api/rooms",
                files={"file": ("group.xlsx", Path("tests/fixtures/guided-notes-group.xlsx").read_bytes())},
                data={"question_bundles": '[["Q3", "Q4"]]'},
            ).json()
            single_questions = client.get(f"/api/rooms/{single['room_id']}/questions").json()["questions"]
            group_questions = client.get(f"/api/rooms/{group['room_id']}/questions").json()["questions"]
    finally:
        app.dependency_overrides.clear()

    assert len(single_questions) == 6
    assert len(single_questions[0]["slots"]) == 1
    assert [slot["marker"] for slot in group_questions[0]["slots"]] == ["(1)", "(2)"]
    assert group_questions[2]["bundle_id"] == group_questions[3]["bundle_id"]
