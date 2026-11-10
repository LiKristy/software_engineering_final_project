from pathlib import Path

from fastapi.testclient import TestClient

from app.api import get_room_service
from app.database import Database
from app.main import app
from app.repositories.room_repository import RoomRepository
from app.services.room_service import RoomService


SINGLE = Path("tests/fixtures/guided-notes-single.xlsx")


def test_phase_changes_are_broadcast_and_reconnect_gets_current_snapshot(tmp_path):
    database = Database(tmp_path / "realtime.sqlite3")
    database.migrate()
    app.dependency_overrides[get_room_service] = lambda: RoomService(RoomRepository(database))
    try:
        with TestClient(app) as client:
            app.state.database = database
            room = client.post(
                "/api/rooms", files={"file": ("single.xlsx", SINGLE.read_bytes())}
            ).json()
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
    app.dependency_overrides[get_room_service] = lambda: RoomService(RoomRepository(database))
    try:
        with TestClient(app) as client:
            app.state.database = database
            room = client.post(
                "/api/rooms", files={"file": ("single.xlsx", SINGLE.read_bytes())}
            ).json()
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
    app.dependency_overrides[get_room_service] = lambda: RoomService(RoomRepository(database))
    try:
        with TestClient(app) as client:
            app.state.database = database
            room = client.post("/api/rooms", files={"file": ("single.xlsx", SINGLE.read_bytes())}).json()
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
