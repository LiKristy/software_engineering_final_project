import secrets
import uuid
import time
from datetime import datetime, timezone
from typing import Iterable

from app.database import Database


class CooldownActive(Exception):
    def __init__(self, remaining: int):
        self.remaining = remaining


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
                prompts = connection.execute(
                    "SELECT row_order, answer_marker AS marker, prompt_text AS text "
                    "FROM question_prompts WHERE question_id = ? ORDER BY row_order",
                    (question["id"],),
                ).fetchall()
                result.append(
                    {
                        **dict(question),
                        "id": question["public_id"],
                        "slots": [dict(slot) for slot in slots],
                        "prompts": [dict(prompt) for prompt in prompts],
                    }
                )
            return result

    def submit(self, room_id: str, group_id: str, bundle_id: str, answers: dict[str, str]):
        """Serialize submissions with SQLite's write transaction and retain receipt sequence."""
        with self.database.transaction() as connection:
            now = time.time()
            group = connection.execute(
                "SELECT cooldown_until FROM groups WHERE id=? AND room_id=?", (group_id, room_id)
            ).fetchone()
            if group and group["cooldown_until"] and group["cooldown_until"] > now:
                raise CooldownActive(max(1, int(group["cooldown_until"] - now + 0.999)))
            room = connection.execute("SELECT max_wins, cooldown_seconds FROM rooms WHERE id=?", (room_id,)).fetchone()
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
            self._reconcile_awards(connection, room_id, room["max_wins"], room["cooldown_seconds"], now)
            return {"id": submission_id, "receipt_sequence": sequence}

    @staticmethod
    def _reconcile_awards(connection, room_id: str, max_wins: int | None, cooldown_seconds: int, now: float) -> None:
        questions = [dict(row) for row in connection.execute(
            "SELECT id, bundle_id, ordinal FROM questions WHERE room_id=? ORDER BY ordinal", (room_id,)
        )]
        grouped_questions = {}
        for question in questions:
            grouped_questions.setdefault(question["bundle_id"], []).append(question)
        submissions = [dict(row) for row in connection.execute(
            "SELECT id, group_id, bundle_id, receipt_sequence, review_status FROM submissions "
            "WHERE room_id=? ORDER BY receipt_sequence", (room_id,)
        )]
        candidates_by_bundle = {}
        for submission in submissions:
            if submission["review_status"] == "pending":
                candidates_by_bundle.setdefault(submission["bundle_id"], []).append(submission)
        bundle_order = sorted(
            grouped_questions,
            key=lambda bundle: (
                min((s["receipt_sequence"] for s in candidates_by_bundle.get(bundle, [])), default=float("inf")),
                min(q["ordinal"] for q in grouped_questions[bundle]),
            ),
        )
        old_awards = {}
        for row in connection.execute(
            "SELECT q.bundle_id, qa.submission_id, qa.awarded_at, qa.cooldown_until "
            "FROM question_awards qa JOIN questions q ON q.id=qa.question_id "
            "WHERE qa.room_id=? GROUP BY q.bundle_id", (room_id,)
        ):
            old_awards[row["bundle_id"]] = dict(row)
        winners = {}
        wins = {}
        for bundle in bundle_order:
            members = grouped_questions[bundle]
            winner = next((candidate for candidate in candidates_by_bundle.get(bundle, [])
                           if max_wins is None or wins.get(candidate["group_id"], 0) + len(members) <= max_wins), None)
            if winner:
                winners[bundle] = winner
                wins[winner["group_id"]] = wins.get(winner["group_id"], 0) + len(members)
        connection.execute("DELETE FROM question_awards WHERE room_id=?", (room_id,))
        awards_by_group = {}
        for bundle, winner in winners.items():
            old = old_awards.get(bundle)
            if old and old["submission_id"] == winner["id"]:
                awarded_at, deadline = old["awarded_at"], old["cooldown_until"]
            else:
                awarded_at = datetime.now(timezone.utc).isoformat()
                deadline = now + cooldown_seconds if cooldown_seconds > 0 else None
            for question in grouped_questions[bundle]:
                connection.execute(
                    "INSERT INTO question_awards (room_id, question_id, group_id, submission_id, awarded_at, cooldown_until) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (room_id, question["id"], winner["group_id"], winner["id"], awarded_at, deadline),
                )
            if deadline and deadline > now:
                awards_by_group.setdefault(winner["group_id"], []).append((deadline, winner["id"]))
        connection.execute("UPDATE groups SET cooldown_until=NULL, cooldown_source_submission_id=NULL WHERE room_id=?", (room_id,))
        for group_id, sources in awards_by_group.items():
            deadline, submission_id = max(sources)
            connection.execute(
                "UPDATE groups SET cooldown_until=?, cooldown_source_submission_id=? WHERE id=?",
                (deadline, submission_id, group_id),
            )

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
            if cursor.rowcount == 1:
                room = connection.execute("SELECT max_wins, cooldown_seconds FROM rooms WHERE id=?", (room_id,)).fetchone()
                self._reconcile_awards(connection, room_id, room["max_wins"], room["cooldown_seconds"], time.time())
            return cursor.rowcount == 1

    def create(self, room: dict, questions: Iterable[dict]) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO rooms "
                "(id, status, max_wins, teacher_token_hash, projection_token_hash, "
                "workbook_name, workbook_blob, created_at, source_type, google_spreadsheet_id, google_sheet_gid, cooldown_seconds) "
                "VALUES (:id, 'waiting', :max_wins, :teacher_token_hash, "
                ":projection_token_hash, :workbook_name, :workbook_blob, :created_at, :source_type, :google_spreadsheet_id, :google_sheet_gid, :cooldown_seconds)",
                room,
            )
            for question in questions:
                question_db_id = f"{room['id']}:{question['id']}"
                connection.execute(
                    "INSERT INTO questions (id, room_id, question_number, bundle_id, ordinal) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (question_db_id, room["id"], question["id"], question["bundle_id"], question["ordinal"]),
                )
                for prompt in question.get("prompts", []):
                    connection.execute(
                        "INSERT INTO question_prompts "
                        "(question_id, row_order, answer_marker, prompt_text) VALUES (?, ?, ?, ?)",
                        (question_db_id, prompt["row_order"], prompt["marker"], prompt["text"]),
                    )
                for slot in question["slots"]:
                    connection.execute(
                        "INSERT INTO answer_slots "
                        "(id, room_id, question_id, marker, worksheet_name, cell_coordinate, imported_baseline_value) "
                        "VALUES (:id, :room_id, :question_id, :marker, :worksheet_name, :cell_coordinate, :imported_baseline_value)",
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
