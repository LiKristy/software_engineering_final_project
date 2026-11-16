from pathlib import Path
import pytest

from fastapi.testclient import TestClient

from app.api import get_google_sheets_adapter, get_room_service
from app.database import Database
from app.main import app
from app.repositories.room_repository import RoomRepository
from app.services.room_service import RoomService
from google_helpers import FakeGoogleSheetsAdapter


SINGLE = Path("tests/fixtures/guided-notes-single.xlsx")
SHEET_URL = "https://docs.google.com/spreadsheets/d/1dHJOnfihH0J2OPeqzkMofJD17TXMsT10PfVDbCqW7aQ/edit"


def install_overrides(database):
    app.dependency_overrides[get_room_service] = lambda: RoomService(RoomRepository(database))
    app.dependency_overrides[get_google_sheets_adapter] = lambda: FakeGoogleSheetsAdapter(SINGLE.read_bytes())


def test_phase_changes_are_broadcast_and_reconnect_gets_current_snapshot(tmp_path):
    database = Database(tmp_path / "realtime.sqlite3")
    database.migrate()
    install_overrides(database)
    try:
        with TestClient(app) as client:
            app.state.database = database
            room = client.post("/api/rooms", data={"sheet_url": SHEET_URL}).json()
            group = client.post(
                f"/api/rooms/{room['room_id']}/join", json={"group_name": "第 1 組"}
            ).json()
            with client.websocket_connect(f"/ws/{room['room_id']}") as socket:
                socket.send_json({"role": "student", "group_id": group["group_id"], "token": group["group_token"]})
                snapshot = socket.receive_json()
                assert snapshot["type"] == "snapshot" and snapshot["status"] == "waiting", snapshot
                started = client.post(
                    f"/api/rooms/{room['room_id']}/start",
                    headers={"X-Teacher-Token": room["teacher_token"]},
                )
                assert started.status_code == 200
                assert socket.receive_json() == {
                    "type": "phase.changed", "room_id": room["room_id"], "status": "active"
                }
                ended = client.post(
                    f"/api/rooms/{room['room_id']}/end",
                    headers={"X-Teacher-Token": room["teacher_token"]},
                )
                assert ended.status_code == 200
                assert socket.receive_json()["status"] == "ended"

            with client.websocket_connect(f"/ws/{room['room_id']}") as socket:
                socket.send_json({"role": "student", "group_id": group["group_id"], "token": group["group_token"]})
                assert socket.receive_json()["status"] == "ended"
    finally:
        app.dependency_overrides.clear()


def test_teacher_phase_commands_require_token_and_valid_transition(tmp_path):
    database = Database(tmp_path / "phase.sqlite3")
    database.migrate()
    install_overrides(database)
    try:
        with TestClient(app) as client:
            app.state.database = database
            room = client.post("/api/rooms", data={"sheet_url": SHEET_URL}).json()
            denied = client.post(f"/api/rooms/{room['room_id']}/start")
            started = client.post(
                f"/api/rooms/{room['room_id']}/start",
                headers={"X-Teacher-Token": room["teacher_token"]},
            )
            repeated = client.post(
                f"/api/rooms/{room['room_id']}/start",
                headers={"X-Teacher-Token": room["teacher_token"]},
            )
    finally:
        app.dependency_overrides.clear()

    assert denied.status_code == 403
    assert started.status_code == 200
    assert repeated.status_code == 409


def test_submission_events_are_filtered_by_role_and_group(tmp_path):
    database = Database(tmp_path / "private-events.sqlite3")
    database.migrate()
    install_overrides(database)
    try:
        with TestClient(app) as client:
            app.state.database = database
            room = client.post("/api/rooms", data={"sheet_url": SHEET_URL}).json()
            groups = [client.post(f"/api/rooms/{room['room_id']}/join", json={"group_name": f"組 {i}"}).json() for i in range(2)]
            client.post(f"/api/rooms/{room['room_id']}/start", headers={"X-Teacher-Token": room["teacher_token"]})
            with client.websocket_connect(f"/ws/{room['room_id']}") as teacher, client.websocket_connect(f"/ws/{room['room_id']}") as first, client.websocket_connect(f"/ws/{room['room_id']}") as other, client.websocket_connect(f"/ws/{room['room_id']}") as projection:
                teacher.send_json({"role": "teacher", "token": room["teacher_token"]})
                first.send_json({"role": "student", "group_id": groups[0]["group_id"], "token": groups[0]["group_token"]})
                other.send_json({"role": "student", "group_id": groups[1]["group_id"], "token": groups[1]["group_token"]})
                projection.send_json({"role": "projection", "token": room["projection_url"].split("#")[-1]})
                assert teacher.receive_json()["role"] == "teacher"
                assert first.receive_json()["role"] == other.receive_json()["role"] == "student"
                assert projection.receive_json()["role"] == "projection"
                question = client.get(f"/api/rooms/{room['room_id']}/questions").json()["questions"][0]
                client.post(f"/api/rooms/{room['room_id']}/submissions", json={"group_id": groups[0]["group_id"], "group_token": groups[0]["group_token"], "bundle_id": "Q1", "answers": {question["slots"][0]["id"]: "秘密答案"}})
                teacher_event = teacher.receive_json()
                own_event = first.receive_json()
                projection_event = projection.receive_json()
                assert teacher_event["type"] == "progress.updated"
                assert "秘密答案" in str(teacher_event)
                assert own_event == {"type": "submission.saved", "bundle_id": "Q1"}
                assert projection_event["type"] == "results.updated"
                assert projection_event["winners"]["Q1"]["group_name"] == "組 0"
                from app.realtime import connections
                import asyncio
                asyncio.run(connections.broadcast_group(room["room_id"], groups[1]["group_id"], {"type": "probe"}))
                assert other.receive_json() == {"type": "probe"}
    finally:
        app.dependency_overrides.clear()


def test_cooldown_is_private_and_restored_on_reconnect(tmp_path):
    database = Database(tmp_path / "cooldown-events.sqlite3")
    database.migrate()
    install_overrides(database)
    try:
        with TestClient(app) as client:
            app.state.database = database
            room = client.post("/api/rooms", data={"sheet_url": SHEET_URL}).json()
            groups = [client.post(f"/api/rooms/{room['room_id']}/join", json={"group_name": f"第 {i} 組"}).json() for i in (1, 2)]
            client.post(f"/api/rooms/{room['room_id']}/start", headers={"X-Teacher-Token": room["teacher_token"]})
            with client.websocket_connect(f"/ws/{room['room_id']}") as own, client.websocket_connect(f"/ws/{room['room_id']}") as other:
                own.send_json({"role": "student", "group_id": groups[0]["group_id"], "token": groups[0]["group_token"]})
                other.send_json({"role": "student", "group_id": groups[1]["group_id"], "token": groups[1]["group_token"]})
                own_snapshot, other_snapshot = own.receive_json(), other.receive_json()
                assert not own_snapshot["cooldown"]["active"]
                question = client.get(f"/api/rooms/{room['room_id']}/questions").json()["questions"][0]
                submitted = client.post(
                    f"/api/rooms/{room['room_id']}/submissions",
                    json={"group_id": groups[0]["group_id"], "group_token": groups[0]["group_token"], "bundle_id": "Q1", "answers": {question["slots"][0]["id"]: "私密答案"}},
                )
                assert submitted.status_code == 200
                assert own.receive_json()["type"] == "submission.saved"
                event = own.receive_json()
                assert event["type"] == "cooldown.updated" and event["active"]
                other.send_json({"type": "ping"})
                assert other.receive_json() == {"type": "pong"}
                duplicate = client.websocket_connect(f"/ws/{room['room_id']}")
                with duplicate as blocked:
                    blocked.send_json({"role": "student", "group_id": groups[0]["group_id"], "token": groups[0]["group_token"]})
                    from starlette.websockets import WebSocketDisconnect
                    with pytest.raises(WebSocketDisconnect):
                        blocked.receive_json()
            with client.websocket_connect(f"/ws/{room['room_id']}") as resumed:
                resumed.send_json({"role": "student", "group_id": groups[0]["group_id"], "token": groups[0]["group_token"]})
                snapshot = resumed.receive_json()
                assert snapshot["cooldown"]["active"]
                assert snapshot["submitted_bundles"] == ["Q1"]
    finally:
        app.dependency_overrides.clear()


def test_students_only_receive_answers_after_activity_ends(tmp_path):
    database = Database(tmp_path / "result-view.sqlite3")
    database.migrate()
    install_overrides(database)
    try:
        with TestClient(app) as client:
            app.state.database = database
            room = client.post("/api/rooms", data={"sheet_url": SHEET_URL, "cooldown_seconds": "0"}).json()
            first = client.post(f"/api/rooms/{room['room_id']}/join", json={"group_name": "第 1 組"}).json()
            second = client.post(f"/api/rooms/{room['room_id']}/join", json={"group_name": "第 2 組"}).json()
            client.post(f"/api/rooms/{room['room_id']}/start", headers={"X-Teacher-Token": room["teacher_token"]})
            with client.websocket_connect(f"/ws/{room['room_id']}") as student:
                student.send_json({"role": "student", "group_id": second["group_id"], "token": second["group_token"]})
                snapshot = student.receive_json()
                assert "results" not in snapshot and "progress" not in snapshot
                question = client.get(f"/api/rooms/{room['room_id']}/questions").json()["questions"][0]
                client.post(
                    f"/api/rooms/{room['room_id']}/submissions",
                    json={"group_id": first["group_id"], "group_token": first["group_token"], "bundle_id": "Q1", "answers": {question["slots"][0]["id"]: "全班答案"}},
                )
                student.send_json({"type": "ping"})
                assert student.receive_json() == {"type": "pong"}
                client.post(f"/api/rooms/{room['room_id']}/end", headers={"X-Teacher-Token": room["teacher_token"]})
                assert student.receive_json()["type"] == "phase.changed"
                results = student.receive_json()
                assert results["type"] == "results.updated"
                assert results["winners"]["Q1"]["group_name"] == "第 1 組"
                assert results["winners"]["Q1"]["answers"][0]["answer"] == "全班答案"
    finally:
        app.dependency_overrides.clear()


def test_websocket_prompt_visibility_is_limited_by_role_and_phase(tmp_path):
    database = Database(tmp_path / "prompt-events.sqlite3")
    database.migrate()
    install_overrides(database)
    try:
        with TestClient(app) as client:
            app.state.database = database
            room = client.post("/api/rooms", data={"sheet_url": SHEET_URL}).json()
            group = client.post(
                f"/api/rooms/{room['room_id']}/join", json={"group_name": "題目測試組"}
            ).json()
            with client.websocket_connect(f"/ws/{room['room_id']}") as student, client.websocket_connect(f"/ws/{room['room_id']}") as teacher, client.websocket_connect(f"/ws/{room['room_id']}") as projection:
                student.send_json({"role": "student", "group_id": group["group_id"], "token": group["group_token"]})
                teacher.send_json({"role": "teacher", "token": room["teacher_token"]})
                projection.send_json({"role": "projection", "token": room["projection_url"].split("#")[-1]})
                waiting = [student.receive_json(), teacher.receive_json(), projection.receive_json()]
                assert all(not question["prompts"] for snapshot in waiting for question in snapshot["questions"])

                started = client.post(
                    f"/api/rooms/{room['room_id']}/start",
                    headers={"X-Teacher-Token": room["teacher_token"]},
                )
                assert started.status_code == 200
                phase_events = [student.receive_json(), teacher.receive_json(), projection.receive_json()]
                assert all(event["type"] == "phase.changed" and "prompts" not in event for event in phase_events)

            active_questions = client.get(f"/api/rooms/{room['room_id']}/questions").json()["questions"]
            prompt_text = active_questions[0]["prompts"][0]["text"]
            assert prompt_text

            with client.websocket_connect(f"/ws/{room['room_id']}") as student, client.websocket_connect(f"/ws/{room['room_id']}") as teacher, client.websocket_connect(f"/ws/{room['room_id']}") as projection:
                student.send_json({"role": "student", "group_id": group["group_id"], "token": group["group_token"]})
                teacher.send_json({"role": "teacher", "token": room["teacher_token"]})
                projection.send_json({"role": "projection", "token": room["projection_url"].split("#")[-1]})
                active_student, active_teacher, active_projection = (
                    student.receive_json(), teacher.receive_json(), projection.receive_json()
                )
                assert active_student["status"] == "active"
                assert any(prompt_text == prompt["text"] for question in active_student["questions"] for prompt in question["prompts"])
                assert all(not question["prompts"] for snapshot in (active_teacher, active_projection) for question in snapshot["questions"])
    finally:
        app.dependency_overrides.clear()
