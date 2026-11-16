from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from io import BytesIO

from app.api import get_google_sheets_adapter, get_room_service
from app.database import Database
from app.main import app
from app.repositories.room_repository import RoomRepository
from app.services.room_service import RoomService


NOTES = Path("tests/fixtures/guided-notes-single.xlsx").read_bytes()
SHEET_URL = "https://docs.google.com/spreadsheets/d/1dHJOnfihH0J2OPeqzkMofJD17TXMsT10PfVDbCqW7aQ/edit?gid=77"


class MockGoogleApi:
    def __init__(self):
        self.cells = {}

    def import_sheet(self, reference):
        return NOTES, "學習單", 77, NOTES

    def read_cells(self, spreadsheet_id, worksheet_name, coordinates):
        return {coordinate: self.cells.get(coordinate) for coordinate in coordinates}

    def write_cells(self, spreadsheet_id, sheet_id, cells):
        self.cells.update({cell["coordinate"]: cell["value"] for cell in cells})


def test_google_room_full_race_and_exports_end_to_end(tmp_path):
    database = Database(tmp_path / "end-to-end.sqlite3")
    database.migrate()
    google = MockGoogleApi()
    app.dependency_overrides[get_room_service] = lambda: RoomService(RoomRepository(database))
    app.dependency_overrides[get_google_sheets_adapter] = lambda: google
    try:
        with TestClient(app) as client:
            app.state.database = database
            created = client.post(
                "/api/rooms",
                data={"sheet_url": SHEET_URL, "max_wins": "2", "cooldown_seconds": "0", "question_bundles": '[["Q3","Q4"]]'},
            )
            assert created.status_code == 200
            room = created.json()
            assert room["source_type"] == "google_sheet"
            groups = [
                client.post(f"/api/rooms/{room['room_id']}/join", json={"group_name": f"第 {i} 組"}).json()
                for i in (1, 2, 3)
            ]
            assert client.post(f"/api/rooms/{room['room_id']}/join", json={"group_name": "第 1 組"}).status_code == 409
            questions = client.get(f"/api/rooms/{room['room_id']}/questions").json()["questions"]
            teacher_headers = {"X-Teacher-Token": room["teacher_token"]}
            assert client.post(f"/api/rooms/{room['room_id']}/start", headers=teacher_headers).status_code == 200

            def send(group_index, question_ids, answer):
                members = [q for q in questions if q["id"] in question_ids]
                bundle = members[0]["bundle_id"]
                answers = {slot["id"]: answer for question in members for slot in question["slots"]}
                return client.post(
                    f"/api/rooms/{room['room_id']}/submissions",
                    json={"group_id": groups[group_index]["group_id"], "group_token": groups[group_index]["group_token"], "bundle_id": bundle, "answers": answers},
                )

            q1_first = send(0, ["Q1"], "第一組的錯誤答案")
            q1_second = send(1, ["Q1"], "第二組的正確答案")
            assert q1_first.status_code == q1_second.status_code == 200
            assert q1_first.json()["receipt_sequence"] < q1_second.json()["receipt_sequence"]
            before_review = client.get(f"/api/rooms/{room['room_id']}/results", headers=teacher_headers).json()
            assert before_review["winners"]["Q1"]["group_name"] == "第 1 組"
            rejected = client.post(
                f"/api/rooms/{room['room_id']}/submissions/{q1_first.json()['id']}/reject",
                headers=teacher_headers, json={"reason": "答案不正確"},
            )
            assert rejected.status_code == 200
            assert rejected.json()["winners"]["Q1"]["group_name"] == "第 2 組"

            assert send(0, ["Q3", "Q4"], "題組答案").status_code == 200
            assert send(0, ["Q2"], "超過上限候選").status_code == 200
            assert send(1, ["Q2"], "遞補組答案").status_code == 200
            board = client.get(f"/api/rooms/{room['room_id']}/results", headers=teacher_headers).json()
            assert board["winners"]["Q3"]["group_name"] == board["winners"]["Q4"]["group_name"] == "第 1 組"
            assert board["winners"]["Q2"]["group_name"] == "第 2 組"

            history = client.get(f"/api/rooms/{room['room_id']}/export/history.csv", headers=teacher_headers)
            assert history.status_code == 200 and "伺服器接收時間" in history.content.decode("utf-8-sig")
            backfilled = client.post(f"/api/rooms/{room['room_id']}/google-sheet/backfill", headers=teacher_headers)
            assert backfilled.status_code == 200 and backfilled.json()["status"] == "synced"
            assert google.cells
            xlsx = client.get(f"/api/rooms/{room['room_id']}/export/guided-notes.xlsx", headers=teacher_headers)
            workbook = load_workbook(BytesIO(xlsx.content), data_only=True)
            assert workbook["學習單"]
            workbook.close()

            with client.websocket_connect(f"/ws/{room['room_id']}") as student:
                student.send_json({"role": "student", "group_id": groups[2]["group_id"], "token": groups[2]["group_token"]})
                assert "results" not in student.receive_json()
                client.post(f"/api/rooms/{room['room_id']}/end", headers=teacher_headers)
                assert student.receive_json()["status"] == "ended"
                public_results = student.receive_json()
                assert public_results["type"] == "results.updated"
                assert public_results["winners"]["Q1"]["answers"][0]["answer"] == "第二組的正確答案"

            projection_token = room["projection_url"].split("#", 1)[1]
            with client.websocket_connect(f"/ws/{room['room_id']}") as projection:
                projection.send_json({"role": "projection", "token": projection_token})
                projection_snapshot = projection.receive_json()
                assert projection_snapshot["role"] == "projection"
                assert projection_snapshot["results"]["winners"]["Q3"]["group_name"] == "第 1 組"
    finally:
        app.dependency_overrides.clear()
