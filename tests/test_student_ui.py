from pathlib import Path
import re

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
    ids = re.findall(r'\bid="([^"]+)"', teacher.text)
    assert len(ids) == len(set(ids))
    assert 'id="teacher-progress"' in teacher.text
    assert 'id="teacher-results"' in teacher.text
    assert 'id="google-backfill"' in teacher.text
    assert 'name="cooldown_seconds"' in teacher.text
    assert 'id="cooldown-status"' in student.text


def test_readme_documents_cooldown_and_bundle_cap_rules():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "得題冷卻秒數（預設 30，範圍 0–3600，0 停用）" in readme
    assert "題組一次得主事件只開始一次冷卻" in readme
    assert "題組內每題仍分別計入獲勝上限" in readme


def test_student_phase_script_toggles_answer_and_result_views():
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    assert '$("#answer-board").hidden = ended;' in script
    assert '$("#results-board").hidden = !ended;' in script
    assert 'message.status === "ended" && message.results' in script


def test_teacher_websocket_updates_target_single_progress_and_result_elements():
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    assert 'document.querySelector("#teacher-progress")' in script
    assert 'document.querySelector("#results-board") || document.querySelector("#teacher-results")' in script


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
