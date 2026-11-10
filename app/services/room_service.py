from datetime import datetime, timezone
import hashlib
import hmac
import secrets
import string
import time
import unicodedata
import sqlite3

from app.guided_notes import fill_guided_notes, parse_guided_notes
from app.config import get_settings
from app.repositories.room_repository import RoomRepository


class RoomError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class RoomService:
    def __init__(self, rooms: RoomRepository):
        self.rooms = rooms

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_room(
        self,
        data: bytes,
        filename: str,
        max_wins: int | None = None,
        question_bundles: list[list[str]] | None = None,
    ) -> dict:
        if max_wins is not None and max_wins < 1:
            raise RoomError("每組獲勝上限必須大於 0。")
        notes = parse_guided_notes(data, filename)
        by_id = {question.id: question for question in notes.questions}
        bundle_by_question = {question_id: question_id for question_id in by_id}
        used: set[str] = set()
        for bundle in question_bundles or []:
            members = [str(member).upper() for member in bundle]
            if len(members) < 2 or len(set(members)) != len(members):
                raise RoomError("題組至少需要兩個不同題號。")
            if any(member not in by_id for member in members):
                raise RoomError("題組包含不存在的題號。")
            if used.intersection(members):
                raise RoomError("同一題不可加入多個題組。")
            used.update(members)
            bundle_id = "bundle:" + ":".join(members)
            for member in members:
                bundle_by_question[member] = bundle_id

        room_id = self._new_code(6)
        teacher_token = secrets.token_urlsafe(32)
        projection_token = secrets.token_urlsafe(24)
        room = {
            "id": room_id,
            "max_wins": max_wins,
            "teacher_token_hash": self.token_hash(teacher_token),
            "projection_token_hash": self.token_hash(projection_token),
            "workbook_name": filename[:255],
            "workbook_blob": data,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        questions = []
        for question in notes.questions:
            questions.append(
                {
                    "id": question.id,
                    "room_id": room_id,
                    "bundle_id": bundle_by_question[question.id],
                    "ordinal": question.ordinal,
                    "slots": [
                        {
                            "id": slot.id,
                            "room_id": room_id,
                            "question_id": question.id,
                            "marker": slot.marker,
                            "worksheet_name": slot.worksheet_name,
                            "cell_coordinate": slot.cell_coordinate,
                        }
                        for slot in question.slots
                    ],
                }
            )
        self.rooms.create(room, questions)
        imported = notes.as_dict()
        for question in imported["questions"]:
            question["bundle_id"] = bundle_by_question[question["id"]]
        return {
            "room_id": room_id,
            "teacher_token": teacher_token,
            # The token is a URL fragment, so browsers never send it in HTTP requests or access logs.
            "projection_url": f"/projector/{room_id}#{projection_token}",
            "question_count": len(questions),
            "questions": imported["questions"],
        }

    def get_room(self, room_id: str):
        return self.rooms.get(room_id)

    def list_groups(self, room_id: str):
        return [dict(group) for group in self.rooms.list_groups(room_id)]

    def get_questions(self, room_id: str):
        room = self.rooms.get(room_id)
        if room is None:
            raise RoomError("找不到房間。", 404)
        return {"room_id": room_id, "status": room["status"], "questions": self.rooms.get_questions(room_id)}

    def require_teacher(self, room_id: str, token: str | None):
        room = self.rooms.get(room_id)
        if room is None:
            raise RoomError("找不到房間。", 404)
        if not token or not hmac.compare_digest(
            room["teacher_token_hash"], self.token_hash(token)
        ):
            raise RoomError("老師會話無效。", 403)
        return room

    def require_group(self, room_id: str, group_id: str, token: str | None):
        group = self.rooms.get_group(group_id)
        if group is None or group["room_id"] != room_id:
            raise RoomError("組別會話無效。", 403)
        if not token or not hmac.compare_digest(
            group["session_token_hash"], self.token_hash(token)
        ):
            raise RoomError("組別會話無效。", 403)
        now = time.time()
        if group["lease_expires_at"] <= now:
            raise RoomError("組別連線已逾時，請重新加入。", 403)
        self.rooms.refresh_group_lease(group_id, now + get_settings().session_ttl_seconds)
        return group

    def require_projection(self, room_id: str, token: str):
        digest = self.token_hash(token)
        with self.rooms.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM rooms WHERE id = ? AND projection_token_hash = ?",
                (room_id, digest),
            ).fetchall()
        if not rows:
            raise RoomError("投影連結無效。", 403)
        return rows[0]

    def change_phase(self, room_id: str, target: str) -> dict:
        expected = "waiting" if target == "active" else "active"
        if target not in {"active", "ended"}:
            raise RoomError("活動階段無效。")
        if not self.rooms.update_room_status(room_id, expected, target):
            room = self.rooms.get(room_id)
            if room is None:
                raise RoomError("找不到房間。", 404)
            raise RoomError("目前活動階段不允許此操作。", 409)
        return {"room_id": room_id, "status": target}

    def snapshot(self, room_id: str, role: str, group_id: str | None = None) -> dict:
        room = self.rooms.get(room_id)
        if room is None:
            raise RoomError("找不到房間。", 404)
        state = {
            "type": "snapshot",
            "room_id": room_id,
            "role": role,
            "status": room["status"],
            "questions": self.rooms.get_questions(room_id),
        }
        if role == "teacher":
            state["groups"] = self.list_groups(room_id)
            state["progress"] = self.progress(room_id)
            if room["status"] == "ended":
                state["results"] = self.results(room_id)
        elif role == "student":
            group = self.rooms.get_group(group_id or "")
            state["group"] = {"id": group["id"], "name": group["name"]}
            state["submitted_bundles"] = self.submitted_bundles(room_id, group_id or "")
            if room["status"] == "ended":
                state["results"] = self.results(room_id)
        elif role == "projection":
            state["results"] = self.results(room_id)
        return state

    def submitted_bundles(self, room_id: str, group_id: str) -> list[str]:
        return self.rooms.submitted_bundles(room_id, group_id)

    def submit(self, room_id: str, group_id: str, token: str | None, bundle_id: str, answers: dict[str, str]) -> dict:
        self.require_group(room_id, group_id, token)
        room = self.rooms.get(room_id)
        if room["status"] != "active":
            raise RoomError("目前不在搶答階段。", 409)
        questions = self.rooms.get_questions(room_id)
        members = [q for q in questions if q["bundle_id"] == bundle_id]
        if not members:
            raise RoomError("題目或題組不存在。", 404)
        expected = {slot["id"] for q in members for slot in q["slots"]}
        if set(answers) != expected or any(not isinstance(v, str) or not v.strip() for v in answers.values()):
            raise RoomError("請填寫題組內所有答案空格。")
        try:
            receipt = self.rooms.submit(room_id, group_id, bundle_id, answers)
        except sqlite3.IntegrityError as exc:
            raise RoomError("此組已送出這道題目或題組。", 409) from exc
        receipt["bundle_id"] = bundle_id
        receipt["received_at"] = self.rooms.submission_received_at(receipt["id"])
        return receipt

    def review(self, room_id: str, submission_id: str, reason: str | None = None):
        if not self.rooms.reject_submission(room_id, submission_id, reason):
            raise RoomError("找不到可駁回的提交。", 404)
        return self.results(room_id)

    def progress(self, room_id: str):
        rows = self.rooms.submissions(room_id)
        by_id: dict[str, dict] = {}
        for row in rows:
            item = by_id.setdefault(row["id"], {"submission_id": row["id"], "group_id": row["group_id"], "group_name": row["group_name"], "bundle_id": row["bundle_id"], "received_at": row["received_at"], "receipt_sequence": row["receipt_sequence"], "review_status": row["review_status"], "answers": []})
            item["answers"].append({"question": row["question_number"], "slot": row["marker"], "coordinate": row["cell_coordinate"], "worksheet": row["worksheet_name"], "answer": row["answer_text"]})
        bundle_counts: dict[str, int] = {}
        for question in self.rooms.get_questions(room_id):
            bundle_counts[question["bundle_id"]] = bundle_counts.get(question["bundle_id"], 0) + 1
        grouped: dict[str, list[dict]] = {}
        for item in by_id.values():
            grouped.setdefault(item["bundle_id"], []).append(item)
        ranked = []
        for submissions in grouped.values():
            submissions.sort(key=lambda item: item["receipt_sequence"])
            for rank, item in enumerate(submissions, 1):
                ranked.append({**item, "rank": rank})
        return ranked

    def results(self, room_id: str):
        questions = self.rooms.get_questions(room_id)
        progress = self.progress(room_id)
        room = self.rooms.get(room_id)
        winners: dict[str, dict] = {}
        wins: dict[str, int] = {}
        bundle_groups: dict[str, list[dict]] = {}
        for question in questions:
            bundle_groups.setdefault(question["bundle_id"], []).append(question)
        def bundle_order(pair):
            bundle_id, members = pair
            candidates = [item for item in progress if item["bundle_id"] == bundle_id and item["review_status"] == "pending"]
            first_candidate_sequence = min((item["receipt_sequence"] for item in candidates), default=float("inf"))
            return first_candidate_sequence, min(q["ordinal"] for q in members)

        for bundle_id, members in sorted(bundle_groups.items(), key=bundle_order):
            candidates = sorted((item for item in progress if item["bundle_id"] == bundle_id and item["review_status"] == "pending"), key=lambda item: item["receipt_sequence"])
            winner = next((item for item in candidates if room["max_wins"] is None or wins.get(item["group_id"], 0) + len(members) <= room["max_wins"]), None)
            if winner:
                wins[winner["group_id"]] = wins.get(winner["group_id"], 0) + len(members)
                for question in members:
                    winners[question["id"]] = {"question": question["id"], "group_id": winner["group_id"], "group_name": winner["group_name"], "answers": [a for a in winner["answers"] if a["question"] == question["id"]], "submission_id": winner["submission_id"]}
        scores = [{"group_id": group["id"], "group_name": group["name"], "wins": wins.get(group["id"], 0)} for group in self.list_groups(room_id)]
        scores.sort(key=lambda entry: (-entry["wins"], entry["group_name"].casefold()))
        return {"questions": questions, "winners": winners, "scores": scores, "progress": progress}

    def export_guided_notes(self, room_id: str) -> bytes:
        room = self.rooms.get(room_id)
        if room is None:
            raise RoomError("找不到房間。", 404)
        results = self.results(room_id)
        answers = {}
        worksheet_name = None
        for winner in results["winners"].values():
            for answer in winner["answers"]:
                answers[answer["coordinate"]] = answer["answer"]
                worksheet_name = answer["worksheet"]
        if worksheet_name is None:
            # Keep an unchanged valid workbook when no question has a winner.
            from openpyxl import load_workbook
            from io import BytesIO
            workbook = load_workbook(BytesIO(room["workbook_blob"]))
            worksheet_name = "學習單" if "學習單" in workbook.sheetnames else workbook.sheetnames[0]
            workbook.close()
        return fill_guided_notes(room["workbook_blob"], worksheet_name, answers)

    def join_room(self, room_id: str, name: str, resume_token: str | None = None) -> dict:
        normalized_name = unicodedata.normalize("NFKC", name).strip()
        if not normalized_name or len(normalized_name) > 40:
            raise RoomError("組名需為 1 至 40 個字元。")
        token = resume_token or secrets.token_urlsafe(32)
        now = time.time()
        result = self.rooms.join_group(
            room_id=room_id,
            name=normalized_name,
            name_key=normalized_name.casefold(),
            session_token_hash=self.token_hash(token),
            lease_expires_at=now + get_settings().session_ttl_seconds,
            joined_at=datetime.now(timezone.utc).isoformat(),
            resume_hash=self.token_hash(resume_token) if resume_token else None,
            now=now,
        )
        if result.get("error") == "room_not_found":
            raise RoomError("找不到房間。", 404)
        if result.get("error") == "already_joined":
            raise RoomError("此組別已在房間中，請使用原視窗重新連線。", 409)
        return {
            "room_id": room_id,
            "group_id": result["id"],
            "group_name": normalized_name,
            "group_token": token,
            "resumed": result["resumed"],
        }

    @staticmethod
    def _new_code(length: int) -> str:
        alphabet = string.ascii_uppercase + "23456789"
        return "".join(secrets.choice(alphabet) for _ in range(length))
