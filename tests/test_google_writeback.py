from pathlib import Path

import pytest

from app.database import Database
from app.repositories.room_repository import RoomRepository
from app.services.google_sheets import GoogleSheetsError
from app.services.room_service import RoomError, RoomService


SHEET_URL = "https://docs.google.com/spreadsheets/d/1dHJOnfihH0J2OPeqzkMofJD17TXMsT10PfVDbCqW7aQ/edit?gid=77"
NOTES = Path("tests/fixtures/guided-notes-single.xlsx").read_bytes()


class FakeSheet:
    def __init__(self, read_error=None, write_error=None):
        self.values = {}
        self.read_error = read_error
        self.write_error = write_error
        self.write_calls = []

    def import_sheet(self, reference):
        return NOTES, "學習單", 77, NOTES

    def read_cells(self, spreadsheet_id, worksheet_name, coordinates):
        if self.read_error:
            raise GoogleSheetsError("denied", self.read_error)
        return {coordinate: self.values.get(coordinate) for coordinate in coordinates}

    def write_cells(self, spreadsheet_id, sheet_id, cells):
        self.write_calls.append(cells)
        if self.write_error:
            raise GoogleSheetsError("batch rejected", self.write_error)
        self.values.update({cell["coordinate"]: cell["value"] for cell in cells})


def build_room(tmp_path, adapter):
    database = Database(tmp_path / "google-writeback.sqlite3")
    database.migrate()
    service = RoomService(RoomRepository(database))
    room = service.create_room_from_google_sheet(SHEET_URL, adapter=adapter)
    questions = service.get_questions(room["room_id"])["questions"]
    return database, service, room, questions


def submit(service, room, question, group_name, answer):
    group = service.join_room(room["room_id"], group_name)
    service.change_phase(room["room_id"], "active")
    slots = question["slots"]
    receipt = service.submit(
        room["room_id"], group["group_id"], group["group_token"], question["bundle_id"],
        {slot["id"]: answer for slot in slots},
    )
    return group, receipt


def test_backfill_writes_current_winner_and_is_idempotent(tmp_path):
    adapter = FakeSheet()
    _, service, room, questions = build_room(tmp_path, adapter)
    submit(service, room, questions[0], "第 1 組", "正確答案")
    first = service.writeback_google_sheet(room["room_id"], adapter)
    second = service.writeback_google_sheet(room["room_id"], adapter)
    assert first == {"status": "synced", "updated_cells": len(questions[0]["slots"])}
    assert second == {"status": "already_synced", "updated_cells": 0}
    assert len(adapter.write_calls) == 1


def test_backfill_detects_external_edit_before_any_write(tmp_path):
    adapter = FakeSheet()
    _, service, room, questions = build_room(tmp_path, adapter)
    submit(service, room, questions[0], "第 1 組", "正確答案")
    coordinate = questions[0]["slots"][0]["cell_coordinate"]
    adapter.values[coordinate] = "老師的外部修改"
    with pytest.raises(RoomError, match="外部修改") as error:
        service.writeback_google_sheet(room["room_id"], adapter)
    assert error.value.status_code == 409
    assert adapter.write_calls == []


def test_backfill_permission_and_batch_failure_are_reported_without_partial_write(tmp_path):
    adapter = FakeSheet(read_error="permission_denied")
    _, service, room, questions = build_room(tmp_path, adapter)
    submit(service, room, questions[0], "第 1 組", "答案")
    with pytest.raises(RoomError) as denied:
        service.writeback_google_sheet(room["room_id"], adapter)
    assert denied.value.status_code == 403

    adapter.read_error = None
    adapter.write_error = "google_api_error"
    with pytest.raises(RoomError) as failed:
        service.writeback_google_sheet(room["room_id"], adapter)
    assert failed.value.status_code == 502
    assert adapter.values == {}
    with service.rooms.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM answer_slots WHERE last_written_value IS NOT NULL").fetchone()[0] == 0


def test_backfill_rejects_when_there_are_no_winners(tmp_path):
    adapter = FakeSheet()
    _, service, room, _ = build_room(tmp_path, adapter)
    with pytest.raises(RoomError, match="沒有可回填"):
        service.writeback_google_sheet(room["room_id"], adapter)


def test_backfill_after_teacher_rejection_replaces_previously_written_winner(tmp_path):
    adapter = FakeSheet()
    database, service, room, questions = build_room(tmp_path, adapter)
    first_group = service.join_room(room["room_id"], "第 1 組")
    second_group = service.join_room(room["room_id"], "第 2 組")
    service.change_phase(room["room_id"], "active")
    question = questions[0]
    first = service.submit(
        room["room_id"], first_group["group_id"], first_group["group_token"], question["bundle_id"],
        {slot["id"]: "第一順位" for slot in question["slots"]},
    )
    service.submit(
        room["room_id"], second_group["group_id"], second_group["group_token"], question["bundle_id"],
        {slot["id"]: "第二順位" for slot in question["slots"]},
    )
    service.writeback_google_sheet(room["room_id"], adapter)
    service.review(room["room_id"], first["id"], "答案錯誤")
    result = service.writeback_google_sheet(room["room_id"], adapter)
    assert result["status"] == "synced"
    assert all(value == "第二順位" for value in adapter.values.values())
    with database.connect() as connection:
        stored = connection.execute("SELECT workbook_blob FROM rooms WHERE id=?", (room["room_id"],)).fetchone()[0]
    assert bytes(stored) == NOTES
    exported = service.export_guided_notes(room["room_id"])
    assert exported.startswith(b"PK")
    assert bytes(stored) == NOTES  # local XLSX export never writes to the Google source
