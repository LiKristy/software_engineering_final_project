from datetime import datetime, timezone
import hashlib
import hmac
import secrets
import string
import time
import unicodedata
import sqlite3
from zipfile import is_zipfile
from io import BytesIO
from openpyxl import load_workbook

from app.guided_notes import fill_guided_notes, parse_guided_notes
from app.config import get_settings
from app.repositories.room_repository import RoomRepository, CooldownActive


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
        *,
        source_type: str = "upload",
        google_spreadsheet_id: str | None = None,
        google_sheet_gid: int | None = None,
        workbook_blob: bytes | None = None,
        cooldown_seconds: int = 30,
    ) -> dict:
        if max_wins is not None and max_wins < 1:
            raise RoomError("每組獲勝上限必須大於 0。")
        if not 0 <= cooldown_seconds <= 3600:
            raise RoomError("冷卻秒數必須介於 0 到 3600。")
        notes = parse_guided_notes(data, filename)
        source_workbook = load_workbook(BytesIO(data), data_only=False)
        baseline_values = {
            (slot.worksheet_name, slot.cell_coordinate): source_workbook[slot.worksheet_name][slot.cell_coordinate].value
            for question in notes.questions for slot in question.slots
        }
        source_workbook.close()
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
            "workbook_blob": workbook_blob if workbook_blob is not None else data,
            "source_type": source_type,
            "google_spreadsheet_id": google_spreadsheet_id,
            "google_sheet_gid": google_sheet_gid,
            "cooldown_seconds": cooldown_seconds,
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
                            "imported_baseline_value": (
                                str(baseline_values[(slot.worksheet_name, slot.cell_coordinate)])
                                if baseline_values[(slot.worksheet_name, slot.cell_coordinate)] is not None
                                else None
                            ),
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
            "source_type": source_type,
            "questions": imported["questions"],
        }

    def create_room_from_google_sheet(
        self, sheet_url: str, question_bundles: list[list[str]] | None = None,
        max_wins: int | None = None, adapter=None,
        cooldown_seconds: int = 30,
    ) -> dict:
        from app.services.google_sheets import GoogleSheetsAdapter, GoogleSheetsError, parse_google_sheet_url

        reference = parse_google_sheet_url(sheet_url)
        try:
            adapter = adapter or GoogleSheetsAdapter()
            parsed_data, title, gid, snapshot = adapter.import_sheet(reference)
            if len(snapshot) > get_settings().max_upload_bytes:
                raise RoomError("Google Sheet 匯出快照超過檔案大小限制。", 413)
            if not is_zipfile(BytesIO(snapshot)):
                raise RoomError("Google Sheet 未能匯出有效的 .xlsx 快照。", 400)
            # Parse the source grid for its live mapping, but keep Drive's full XLSX export for later downloads.
            result = self.create_room(
                parsed_data, "google-guided-notes.xlsx", max_wins, question_bundles,
                source_type="google_sheet", google_spreadsheet_id=reference.spreadsheet_id,
                google_sheet_gid=gid, workbook_blob=snapshot, cooldown_seconds=cooldown_seconds,
            )
            result["source_type"] = "google_sheet"
            return result
        except GoogleSheetsError as exc:
            raise RoomError(str(exc), 403 if exc.code == "permission_denied" else 400) from exc

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
            state["cooldown"] = self.cooldown_state(group_id or "")
            state["submitted_bundles"] = self.submitted_bundles(room_id, group_id or "")
            if room["status"] == "ended":
                state["results"] = self.results(room_id)
        elif role == "projection":
            state["results"] = self.results(room_id)
        return state

    def submitted_bundles(self, room_id: str, group_id: str) -> list[str]:
        return self.rooms.submitted_bundles(room_id, group_id)

    def cooldown_state(self, group_id: str) -> dict:
        group = self.rooms.get_group(group_id)
        until = group["cooldown_until"] if group else None
        remaining = max(0, int(until - time.time() + 0.999)) if until else 0
        return {"active": remaining > 0, "remaining_seconds": remaining, "until": until if remaining else None}

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
        except CooldownActive as exc:
            raise RoomError(f"冷卻中，還需 {exc.remaining} 秒。", 409) from exc
        except sqlite3.IntegrityError as exc:
            raise RoomError("此組已送出這道題目或題組。", 409) from exc
        receipt["bundle_id"] = bundle_id
        receipt["received_at"] = self.rooms.submission_received_at(receipt["id"])
        receipt["cooldown"] = self.cooldown_state(group_id)
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

    def writeback_google_sheet(self, room_id: str, adapter=None) -> dict:
        from app.services.google_sheets import GoogleSheetsAdapter, GoogleSheetsError

        room = self.rooms.get(room_id)
        if room is None:
            raise RoomError("找不到房間。", 404)
        if room["source_type"] != "google_sheet" or not room["google_spreadsheet_id"]:
            raise RoomError("此房間不是由 Google Sheet 建立。", 409)
        results = self.results(room_id)
        winners = results["winners"]
        if not winners:
            raise RoomError("目前沒有可回填的得主答案。", 409)
        with self.rooms.database.connect() as connection:
            slot_rows = [dict(row) for row in connection.execute(
                "SELECT sl.id, q.question_number, sl.worksheet_name, sl.cell_coordinate, "
                "sl.imported_baseline_value, sl.last_written_value FROM answer_slots sl "
                "JOIN questions q ON q.id=sl.question_id WHERE sl.room_id=?",
                (room_id,),
            )]
        winner_values = {}
        for question_id, winner in winners.items():
            for answer in winner["answers"]:
                winner_values[(question_id, answer["coordinate"])] = answer["answer"]
        targets = []
        for slot in slot_rows:
            target = winner_values.get((slot["question_number"], slot["cell_coordinate"]))
            if target is not None:
                targets.append({**slot, "target": str(target)})
        if not targets:
            raise RoomError("得主答案沒有對應的 Guided Notes 儲存格。", 409)
        adapter = adapter or GoogleSheetsAdapter()
        worksheet_name = targets[0]["worksheet_name"]
        try:
            current = adapter.read_cells(
                room["google_spreadsheet_id"], worksheet_name,
                [item["cell_coordinate"] for item in targets],
            )
            conflicts = []
            updates = []
            for item in targets:
                actual = current.get(item["cell_coordinate"])
                actual_text = str(actual) if actual is not None else None
                if actual_text == item["target"]:
                    continue
                allowed = {item["imported_baseline_value"], item["last_written_value"]}
                if actual_text not in allowed:
                    conflicts.append(f"{item['question_number']}!{item['cell_coordinate']}")
                else:
                    updates.append({"coordinate": item["cell_coordinate"], "value": item["target"]})
            if conflicts:
                raise RoomError("來源試算表已有外部修改，未執行回填：" + "、".join(conflicts), 409)
            if updates:
                adapter.write_cells(room["google_spreadsheet_id"], room["google_sheet_gid"], updates)
            with self.rooms.database.transaction() as connection:
                for item in targets:
                    connection.execute(
                        "UPDATE answer_slots SET last_written_value=? WHERE id=?",
                        (item["target"], item["id"]),
                    )
            return {"status": "synced" if updates else "already_synced", "updated_cells": len(updates)}
        except GoogleSheetsError as exc:
            status = 403 if exc.code == "permission_denied" else 502
            raise RoomError(str(exc), status) from exc

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
