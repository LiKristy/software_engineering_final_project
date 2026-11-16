from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

import pytest

from app.database import Database
from app.repositories.room_repository import RoomRepository
from app.services.room_service import RoomError, RoomService


NOTES = Path("tests/fixtures/guided-notes-single.xlsx").read_bytes()


def create_service(tmp_path):
    database = Database(tmp_path / "cooldown.sqlite3")
    database.migrate()
    service = RoomService(RoomRepository(database))
    return database, service


def new_room(service, cooldown=30, max_wins=None, bundles=None):
    room = service.create_room(NOTES, "notes.xlsx", max_wins, bundles, cooldown_seconds=cooldown)
    questions = service.get_questions(room["room_id"])["questions"]
    return room, questions


def answer(service, room, group, question, text):
    members = [q for q in service.get_questions(room["room_id"])["questions"] if q["bundle_id"] == question["bundle_id"]]
    return service.submit(
        room["room_id"], group["group_id"], group["group_token"], question["bundle_id"],
        {slot["id"]: text for member in members for slot in member["slots"]},
    )


def test_default_and_configured_cooldown_seconds_are_validated(tmp_path):
    _, service = create_service(tmp_path)
    room, _ = new_room(service)
    assert service.get_room(room["room_id"])["cooldown_seconds"] == 30
    with pytest.raises(RoomError):
        service.create_room(NOTES, "notes.xlsx", cooldown_seconds=3601)
    with pytest.raises(RoomError):
        service.create_room(NOTES, "notes.xlsx", cooldown_seconds=-1)
    disabled, _ = new_room(service, cooldown=0)
    assert service.get_room(disabled["room_id"])["cooldown_seconds"] == 0


def test_award_starts_server_cooldown_and_rejects_without_receipt_sequence(tmp_path):
    database, service = create_service(tmp_path)
    room, questions = new_room(service)
    first = service.join_room(room["room_id"], "第 1 組")
    second = service.join_room(room["room_id"], "第 2 組")
    service.change_phase(room["room_id"], "active")
    answer(service, room, first, questions[0], "首答")
    assert service.cooldown_state(first["group_id"])["active"]
    with pytest.raises(RoomError, match="冷卻中"):
        answer(service, room, first, questions[1], "仍冷卻")
    answer(service, room, second, questions[1], "第二組")
    with database.connect() as connection:
        rows = connection.execute("SELECT group_id, receipt_sequence FROM submissions ORDER BY receipt_sequence").fetchall()
    assert len(rows) == 2
    assert [row["receipt_sequence"] for row in rows] == [1, 2]


def test_zero_cooldown_allows_next_submission_and_bundle_award_counts_each_question(tmp_path):
    database, service = create_service(tmp_path)
    room, questions = new_room(service, cooldown=0, max_wins=2, bundles=[["Q3", "Q4"]])
    group = service.join_room(room["room_id"], "第 1 組")
    service.change_phase(room["room_id"], "active")
    bundled = next(q for q in questions if q["id"] == "Q3")
    receipt = answer(service, room, group, bundled, "題組答案")
    assert not service.cooldown_state(group["group_id"])["active"]
    with database.connect() as connection:
        awards = connection.execute("SELECT * FROM question_awards WHERE submission_id=?", (receipt["id"],)).fetchall()
    assert len(awards) == 2
    assert {row["cooldown_until"] for row in awards} == {None}


def test_rejecting_award_releases_old_group_and_cools_promoted_winner(tmp_path):
    database, service = create_service(tmp_path)
    room, questions = new_room(service)
    first = service.join_room(room["room_id"], "第 1 組")
    second = service.join_room(room["room_id"], "第 2 組")
    service.change_phase(room["room_id"], "active")
    first_submission = answer(service, room, first, questions[0], "第一順位")
    answer(service, room, second, questions[0], "第二順位")
    assert service.cooldown_state(first["group_id"])["active"]
    service.review(room["room_id"], first_submission["id"], "無效")
    assert not service.cooldown_state(first["group_id"])["active"]
    assert service.cooldown_state(second["group_id"])["active"]


def test_consecutive_rejections_reassign_cooldown_to_each_promoted_group(tmp_path):
    _, service = create_service(tmp_path)
    room, questions = new_room(service)
    groups = [service.join_room(room["room_id"], f"第 {i} 組") for i in range(1, 4)]
    service.change_phase(room["room_id"], "active")
    receipts = [answer(service, room, group, questions[0], f"順位 {index}") for index, group in enumerate(groups, 1)]
    service.review(room["room_id"], receipts[0]["id"], "無效")
    assert service.cooldown_state(groups[1]["group_id"])["active"]
    service.review(room["room_id"], receipts[1]["id"], "仍無效")
    assert not service.cooldown_state(groups[1]["group_id"])["active"]
    assert service.cooldown_state(groups[2]["group_id"])["active"]


def test_concurrent_submissions_are_serialized_with_cooldown(tmp_path):
    database, service = create_service(tmp_path)
    room, questions = new_room(service)
    group = service.join_room(room["room_id"], "第 1 組")
    service.change_phase(room["room_id"], "active")

    def send(question):
        try:
            answer(service, room, group, question, question["id"])
            return "accepted"
        except RoomError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(send, questions[:2]))
    assert outcomes.count("accepted") == 1
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 1


def test_expired_cooldown_allows_submission(tmp_path):
    database, service = create_service(tmp_path)
    room, questions = new_room(service)
    group = service.join_room(room["room_id"], "第 1 組")
    service.change_phase(room["room_id"], "active")
    answer(service, room, group, questions[0], "首題")
    with database.transaction() as connection:
        connection.execute("UPDATE groups SET cooldown_until=? WHERE id=?", (time.time() - 1, group["group_id"]))
    answer(service, room, group, questions[1], "冷卻已過")
