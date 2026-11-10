import secrets
import uuid
from datetime import datetime, timezone
from typing import Iterable

from app.database import Database


class RoomRepository:
    def __init__(self, database: Database):
        self.database = database

    def get(self, room_id: str):
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT * FROM rooms WHERE id = ?", (room_id,)
            ).fetchone()

    def list_groups(self, room_id: str):
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT id, name, joined_at FROM groups WHERE room_id = ? ORDER BY joined_at, name",
                (room_id,),
            ).fetchall()

    def get_group(self, group_id: str):
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT * FROM groups WHERE id = ?", (group_id,)
            ).fetchone()

    def update_room_status(self, room_id: str, expected: str, target: str) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE rooms SET status = ? WHERE id = ? AND status = ?",
                (target, room_id, expected),
            )
            return cursor.rowcount == 1

    def refresh_group_lease(self, group_id: str, expires_at: float) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE groups SET lease_expires_at = ? WHERE id = ?",
                (expires_at, group_id),
            )

    def get_questions(self, room_id: str):
        with self.database.connect() as connection:
            questions = connection.execute(
                "SELECT id, question_number AS public_id, bundle_id, ordinal FROM questions WHERE room_id = ? ORDER BY ordinal",
                (room_id,),
            ).fetchall()
            result = []
            for question in questions:
                slots = connection.execute(
                    "SELECT id, marker, worksheet_name, cell_coordinate FROM answer_slots WHERE question_id = ? ORDER BY marker, cell_coordinate",
                    (question["id"],),
                ).fetchall()
                result.append(
                    {
                        **dict(question),
                        "id": question["public_id"],
                        "slots": [dict(slot) for slot in slots],
                    }
                )
            return result

    def submit(self, room_id: str, group_id: str, bundle_id: str, answers: dict[str, str]):
        """Serialize submissions with SQLite's write transaction and retain receipt sequence."""
        with self.database.transaction() as connection:
            submission_id = uuid.uuid4().hex
            cursor = connection.execute(
                "INSERT INTO submissions (id, room_id, group_id, bundle_id, received_at) VALUES (?, ?, ?, ?, ?)",
                (submission_id, room_id, group_id, bundle_id, datetime.now(timezone.utc).isoformat()),
            )
            sequence = cursor.lastrowid
            for slot_id, answer in answers.items():
                connection.execute(
                    "INSERT INTO submission_answers (submission_id, answer_slot_id, answer_text) VALUES (?, ?, ?)",
                    (submission_id, slot_id, answer),
                )
            return {"id": submission_id, "receipt_sequence": sequence}

    def submissions(self, room_id: str):
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT s.receipt_sequence, s.id, s.group_id, g.name AS group_name, s.bundle_id, s.received_at, s.review_status, s.rejection_reason, sa.answer_slot_id, sl.question_id, q.question_number, sl.marker, sl.worksheet_name, sl.cell_coordinate, sa.answer_text "
                "FROM submissions s JOIN groups g ON g.id=s.group_id "
                "JOIN submission_answers sa ON sa.submission_id=s.id "
                "JOIN answer_slots sl ON sl.id=sa.answer_slot_id "
                "JOIN questions q ON q.id=sl.question_id "
                "WHERE s.room_id=? ORDER BY s.receipt_sequence, q.ordinal, sl.marker",
                (room_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def submission_received_at(self, submission_id: str):
        with self.database.connect() as connection:
            row = connection.execute("SELECT received_at FROM submissions WHERE id=?", (submission_id,)).fetchone()
            return row["received_at"] if row else None

    def submitted_bundles(self, room_id: str, group_id: str):
        with self.database.connect() as connection:
            rows = connection.execute("SELECT bundle_id FROM submissions WHERE room_id=? AND group_id=?", (room_id, group_id)).fetchall()
            return [row["bundle_id"] for row in rows]

    def reject_submission(self, room_id: str, submission_id: str, reason: str | None):
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE submissions SET review_status='rejected', rejection_reason=? WHERE room_id=? AND id=? AND review_status='pending'",
                (reason, room_id, submission_id),
            )
            return cursor.rowcount == 1

    def create(self, room: dict, questions: Iterable[dict]) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO rooms "
                "(id, status, max_wins, teacher_token_hash, projection_token_hash, "
                "workbook_name, workbook_blob, created_at) "
                "VALUES (:id, 'waiting', :max_wins, :teacher_token_hash, "
                ":projection_token_hash, :workbook_name, :workbook_blob, :created_at)",
                room,
            )
            for question in questions:
                question_db_id = f"{room['id']}:{question['id']}"
                connection.execute(
                    "INSERT INTO questions (id, room_id, question_number, bundle_id, ordinal) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (question_db_id, room["id"], question["id"], question["bundle_id"], question["ordinal"]),
                )
                for slot in question["slots"]:
                    connection.execute(
                        "INSERT INTO answer_slots "
                        "(id, room_id, question_id, marker, worksheet_name, cell_coordinate) "
                        "VALUES (:id, :room_id, :question_id, :marker, :worksheet_name, :cell_coordinate)",
                        {
                            **slot,
                            "id": f"{room['id']}:{slot['id']}",
                            "question_id": question_db_id,
                        },
                    )

    def join_group(
        self,
        room_id: str,
        name: str,
        name_key: str,
        session_token_hash: str,
        lease_expires_at: float,
        joined_at: str,
        resume_hash: str | None = None,
        now: float = 0,
    ) -> dict:
        with self.database.transaction() as connection:
            room = connection.execute("SELECT id FROM rooms WHERE id = ?", (room_id,)).fetchone()
            if room is None:
                return {"error": "room_not_found"}
            existing = connection.execute(
                "SELECT * FROM groups WHERE room_id = ? AND name_key = ?",
                (room_id, name_key),
            ).fetchone()
            if existing:
                if existing["lease_expires_at"] > now:
                    if resume_hash != existing["session_token_hash"]:
                        return {"error": "already_joined"}
                    connection.execute(
                        "UPDATE groups SET lease_expires_at = ? WHERE id = ?",
                        (lease_expires_at, existing["id"]),
                    )
                    return {"id": existing["id"], "resumed": True}
                connection.execute(
                    "UPDATE groups SET name = ?, session_token_hash = ?, lease_expires_at = ?, joined_at = ? WHERE id = ?",
                    (name, session_token_hash, lease_expires_at, joined_at, existing["id"]),
                )
                return {"id": existing["id"], "resumed": False}
            group_id = secrets.token_urlsafe(12)
            connection.execute(
                "INSERT INTO groups "
                "(id, room_id, name, name_key, session_token_hash, lease_expires_at, joined_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (group_id, room_id, name, name_key, session_token_hash, lease_expires_at, joined_at),
            )
            return {"id": group_id, "resumed": False}
