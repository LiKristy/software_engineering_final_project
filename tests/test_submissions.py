from pathlib import Path
import csv
from io import StringIO, BytesIO
from openpyxl import load_workbook
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.api import get_room_service
from app.database import Database
from app.main import app
from app.repositories.room_repository import RoomRepository
from app.services.room_service import RoomService

NOTES = Path("tests/fixtures/guided-notes-single.xlsx")
GROUP_NOTES = Path("tests/fixtures/guided-notes-group.xlsx")


def test_atomic_bundle_submission_ranking_review_and_cap(tmp_path):
    database = Database(tmp_path / "race.sqlite3")
    database.migrate()
    app.dependency_overrides[get_room_service] = lambda: RoomService(RoomRepository(database))
    try:
        with TestClient(app) as client:
            app.state.database = database
            room = client.post("/api/rooms", files={"file": ("notes.xlsx", NOTES.read_bytes())}, data={"max_wins": "2", "question_bundles": '[["Q3","Q4"]]'}).json()
            questions = client.get(f"/api/rooms/{room['room_id']}/questions").json()["questions"]
            groups = [client.post(f"/api/rooms/{room['room_id']}/join", json={"group_name": f"第 {i} 組"}).json() for i in range(1, 4)]
            client.post(f"/api/rooms/{room['room_id']}/start", headers={"X-Teacher-Token": room["teacher_token"]})

            def submit(group, bundle):
                members = [q for q in questions if q["bundle_id"] == bundle]
                answers = {slot["id"]: f"{group['group_name']}答案" for q in members for slot in q["slots"]}
                return client.post(f"/api/rooms/{room['room_id']}/submissions", json={"group_id": group["group_id"], "group_token": group["group_token"], "bundle_id": bundle, "answers": answers})

            q1_first = submit(groups[0], "Q1")
            q1_second = submit(groups[1], "Q1")
            assert q1_first.status_code == q1_second.status_code == 200
            assert q1_first.json()["receipt_sequence"] < q1_second.json()["receipt_sequence"]
            assert submit(groups[0], "Q1").status_code == 409

            bundle = questions[2]["bundle_id"]
            qbundle = [q for q in questions if q["bundle_id"] == bundle]
            incomplete = client.post(f"/api/rooms/{room['room_id']}/submissions", json={"group_id": groups[1]["group_id"], "group_token": groups[1]["group_token"], "bundle_id": bundle, "answers": {qbundle[0]["slots"][0]["id"]: "only one"}})
            assert incomplete.status_code == 400
            assert submit(groups[0], bundle).status_code == 200
            assert submit(groups[1], bundle).status_code == 200

            headers = {"X-Teacher-Token": room["teacher_token"]}
            assert client.get(f"/api/rooms/{room['room_id']}/results").status_code == 403
            assert client.get(f"/api/rooms/{room['room_id']}/export/history.csv").status_code == 403
            assert client.get(f"/api/rooms/{room['room_id']}/export/guided-notes.xlsx").status_code == 403
            results = client.get(f"/api/rooms/{room['room_id']}/results", headers=headers).json()
            assert len(results["scores"]) == 3
            assert any(score["group_id"] == groups[2]["group_id"] and score["wins"] == 0 for score in results["scores"])
            q1_winner = results["winners"]["Q1"]
            rejected = client.post(f"/api/rooms/{room['room_id']}/submissions/{q1_winner['submission_id']}/reject", headers=headers, json={"reason": "錯誤"})
            assert rejected.status_code == 200
            assert rejected.json()["winners"]["Q1"]["group_id"] == groups[1]["group_id"]
            assert rejected.json()["winners"]["Q3"]["group_id"] == groups[0]["group_id"]
            # Group 2's two-question bundle exceeds its one remaining win slot and is skipped atomically.
            assert "Q4" in rejected.json()["winners"]
            second = client.post(f"/api/rooms/{room['room_id']}/submissions/{rejected.json()['winners']['Q1']['submission_id']}/reject", headers=headers, json={"reason": "仍不正確"})
            assert second.status_code == 200
            assert "Q1" not in second.json()["winners"]
            csv_response = client.get(f"/api/rooms/{room['room_id']}/export/history.csv", headers=headers)
            assert csv_response.status_code == 200
            csv_rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
            assert csv_rows[0][:6] == ["題號", "空格標記", "組別", "送出答案", "伺服器接收時間", "搶答排名"]
            assert any(row[0] == "Q3" and row[2] == "第 1 組" and row[5] == "1" for row in csv_rows[1:])
            notes_response = client.get(f"/api/rooms/{room['room_id']}/export/guided-notes.xlsx", headers=headers)
            assert notes_response.status_code == 200
            exported = load_workbook(BytesIO(notes_response.content), data_only=False)
            original = load_workbook(BytesIO(NOTES.read_bytes()), data_only=False)
            slots = qbundle[0]["slots"]
            coordinate = slots[0]["cell_coordinate"]
            assert exported[slots[0]["worksheet_name"]][coordinate].value == "第 1 組答案"
            assert original[slots[0]["worksheet_name"]][coordinate].value != "第 1 組答案"
            exported.close(); original.close()
            client.post(f"/api/rooms/{room['room_id']}/end", headers=headers)
            assert client.post(f"/api/rooms/{room['room_id']}/submissions", json={"group_id": groups[2]["group_id"], "group_token": groups[2]["group_token"], "bundle_id": "Q2", "answers": {}}).status_code == 409
            with client.websocket_connect(f"/ws/{room['room_id']}") as socket:
                socket.send_json({"role": "student", "group_id": groups[2]["group_id"], "token": groups[2]["group_token"]})
                snapshot = socket.receive_json()
                assert snapshot["status"] == "ended"
                assert "Q1" not in snapshot["results"]["winners"]
                assert snapshot["results"]["winners"]["Q3"]["group_id"] == groups[0]["group_id"]
    finally:
        app.dependency_overrides.clear()


def test_guided_notes_export_fills_group_slots_and_leaves_no_winner_blank(tmp_path):
    database = Database(tmp_path / "notes-export.sqlite3")
    database.migrate()
    app.dependency_overrides[get_room_service] = lambda: RoomService(RoomRepository(database))
    try:
        with TestClient(app) as client:
            app.state.database = database
            room = client.post("/api/rooms", files={"file": ("group.xlsx", GROUP_NOTES.read_bytes())}).json()
            group = client.post(f"/api/rooms/{room['room_id']}/join", json={"group_name": "答案組"}).json()
            questions = client.get(f"/api/rooms/{room['room_id']}/questions").json()["questions"]
            client.post(f"/api/rooms/{room['room_id']}/start", headers={"X-Teacher-Token": room["teacher_token"]})
            question = questions[0]
            answers = {question["slots"][0]["id"]: "第一空", question["slots"][1]["id"]: "第二空"}
            submitted = client.post(f"/api/rooms/{room['room_id']}/submissions", json={"group_id": group["group_id"], "group_token": group["group_token"], "bundle_id": question["bundle_id"], "answers": answers})
            assert submitted.status_code == 200
            response = client.get(f"/api/rooms/{room['room_id']}/export/guided-notes.xlsx", headers={"X-Teacher-Token": room["teacher_token"]})
            output = load_workbook(BytesIO(response.content))
            assert output["學習單"]["H5"].value == "第一空"
            assert output["學習單"]["H6"].value == "第二空"
            assert output["學習單"]["H7"].value is None
            output.close()
    finally:
        app.dependency_overrides.clear()


def test_concurrent_receipts_have_stable_server_sequence(tmp_path):
    database = Database(tmp_path / "concurrent.sqlite3")
    database.migrate()
    app.dependency_overrides[get_room_service] = lambda: RoomService(RoomRepository(database))
    try:
        with TestClient(app) as client:
            app.state.database = database
            room = client.post("/api/rooms", files={"file": ("single.xlsx", NOTES.read_bytes())}).json()
            questions = client.get(f"/api/rooms/{room['room_id']}/questions").json()["questions"]
            groups = [client.post(f"/api/rooms/{room['room_id']}/join", json={"group_name": f"同時組 {i}"}).json() for i in range(2)]
            client.post(f"/api/rooms/{room['room_id']}/start", headers={"X-Teacher-Token": room["teacher_token"]})
            question = questions[0]
            def race(group):
                payload = {"group_id": group["group_id"], "group_token": group["group_token"], "bundle_id": "Q1", "answers": {question["slots"][0]["id"]: group["group_name"]}}
                return client.post(f"/api/rooms/{room['room_id']}/submissions", json=payload)
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(race, groups))
            assert all(response.status_code == 200 for response in responses)
            sequences = sorted(response.json()["receipt_sequence"] for response in responses)
            assert sequences[1] == sequences[0] + 1
            progress = client.get(f"/api/rooms/{room['room_id']}/results", headers={"X-Teacher-Token": room["teacher_token"]}).json()["progress"]
            assert [entry["rank"] for entry in progress] == [1, 2]
            assert [entry["receipt_sequence"] for entry in progress] == sequences
    finally:
        app.dependency_overrides.clear()
