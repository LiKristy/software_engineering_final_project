import json
import csv
from io import StringIO

from fastapi import APIRouter, Depends, FastAPI, Form, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.database import Database
from app.guided_notes import GuidedNotesError
from app.repositories.room_repository import RoomRepository
from app.realtime import connections
from app.services.room_service import RoomError, RoomService
from app.services.google_sheets import GoogleSheetsAdapter, GoogleSheetsError


def get_room_service() -> RoomService:
    return RoomService(RoomRepository(Database()))


def get_google_sheets_adapter() -> GoogleSheetsAdapter:
    return GoogleSheetsAdapter()


api_router = APIRouter(prefix="/api")


@api_router.get("/rooms/{room_id}")
def read_room(room_id: str, service: RoomService = Depends(get_room_service)):
    room = service.get_room(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="找不到房間。")
    return {"room_id": room["id"], "status": room["status"]}


@api_router.post("/rooms")
async def create_room(
    sheet_url: str = Form(...),
    max_wins: int | None = Form(default=None),
    cooldown_seconds: int = Form(default=30, ge=0, le=3600),
    question_bundles: str = Form(default="[]"),
    service: RoomService = Depends(get_room_service),
    google_adapter: GoogleSheetsAdapter = Depends(get_google_sheets_adapter),
):
    try:
        bundles = json.loads(question_bundles)
        if not isinstance(bundles, list) or any(not isinstance(group, list) for group in bundles):
            raise ValueError("題組格式錯誤。")
        result = service.create_room_from_google_sheet(
            sheet_url, bundles, max_wins, adapter=google_adapter,
            cooldown_seconds=cooldown_seconds,
        )
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="題組設定格式錯誤。") from exc
    except GuidedNotesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RoomError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except GoogleSheetsError as exc:
        raise HTTPException(status_code=403 if exc.code == "permission_denied" else 400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result)


class JoinRoomRequest(BaseModel):
    group_name: str = Field(min_length=1, max_length=80)
    group_token: str | None = None


class SubmitAnswersRequest(BaseModel):
    group_id: str
    group_token: str
    bundle_id: str
    answers: dict[str, str]


class RejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


@api_router.post("/rooms/{room_id}/join")
async def join_room(
    room_id: str,
    payload: JoinRoomRequest,
    service: RoomService = Depends(get_room_service),
):
    try:
        result = service.join_room(room_id, payload.group_name, payload.group_token)
    except RoomError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    await connections.broadcast(
        room_id,
        {"type": "groups.updated", "groups": service.list_groups(room_id)},
        {"teacher"},
    )
    return result


@api_router.get("/rooms/{room_id}/questions")
def read_questions(room_id: str, service: RoomService = Depends(get_room_service)):
    try:
        return service.get_questions(room_id)
    except RoomError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@api_router.get("/rooms/{room_id}/groups")
def read_groups(
    room_id: str,
    x_teacher_token: str | None = Header(default=None),
    service: RoomService = Depends(get_room_service),
):
    try:
        service.require_teacher(room_id, x_teacher_token)
        return {"groups": service.list_groups(room_id)}
    except RoomError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@api_router.post("/rooms/{room_id}/start")
async def start_room(
    room_id: str,
    x_teacher_token: str | None = Header(default=None),
    service: RoomService = Depends(get_room_service),
):
    try:
        service.require_teacher(room_id, x_teacher_token)
        result = service.change_phase(room_id, "active")
    except RoomError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    await connections.broadcast(room_id, {"type": "phase.changed", **result}, {"teacher", "student", "projection"})
    return result


@api_router.post("/rooms/{room_id}/end")
async def end_room(
    room_id: str,
    x_teacher_token: str | None = Header(default=None),
    service: RoomService = Depends(get_room_service),
):
    try:
        service.require_teacher(room_id, x_teacher_token)
        result = service.change_phase(room_id, "ended")
    except RoomError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    await connections.broadcast(room_id, {"type": "phase.changed", **result}, {"teacher", "student", "projection"})
    await connections.broadcast(room_id, {"type": "results.updated", **service.results(room_id)}, {"teacher", "student", "projection"})
    return result


@api_router.post("/rooms/{room_id}/submissions")
async def submit_answers(room_id: str, payload: SubmitAnswersRequest, service: RoomService = Depends(get_room_service)):
    try:
        receipt = service.submit(room_id, payload.group_id, payload.group_token, payload.bundle_id, payload.answers)
        progress = service.progress(room_id)
    except RoomError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    await connections.broadcast(room_id, {"type": "progress.updated", "progress": progress}, {"teacher"})
    await connections.broadcast(room_id, {"type": "results.updated", **service.results(room_id)}, {"teacher", "projection"})
    await connections.broadcast_group(room_id, payload.group_id, {"type": "submission.saved", "bundle_id": payload.bundle_id})
    await connections.broadcast_group(room_id, payload.group_id, {"type": "cooldown.updated", **receipt["cooldown"]})
    return receipt


@api_router.get("/rooms/{room_id}/results")
def read_results(room_id: str, x_teacher_token: str | None = Header(default=None), service: RoomService = Depends(get_room_service)):
    try:
        service.require_teacher(room_id, x_teacher_token)
        return service.results(room_id)
    except RoomError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@api_router.post("/rooms/{room_id}/submissions/{submission_id}/reject")
async def reject_submission(room_id: str, submission_id: str, payload: RejectRequest, x_teacher_token: str | None = Header(default=None), service: RoomService = Depends(get_room_service)):
    try:
        service.require_teacher(room_id, x_teacher_token)
        results = service.review(room_id, submission_id, payload.reason)
    except RoomError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    room = service.get_room(room_id)
    audience = {"teacher", "projection"} | ({"student"} if room["status"] == "ended" else set())
    await connections.broadcast(room_id, {"type": "results.updated", **results}, audience)
    for group in service.list_groups(room_id):
        await connections.broadcast_group(room_id, group["id"], {"type": "cooldown.updated", **service.cooldown_state(group["id"])})
    return results


@api_router.get("/rooms/{room_id}/export/history.csv")
def export_history(room_id: str, x_teacher_token: str | None = Header(default=None), service: RoomService = Depends(get_room_service)):
    try:
        service.require_teacher(room_id, x_teacher_token)
        progress = service.progress(room_id)
    except RoomError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["題號", "空格標記", "組別", "送出答案", "伺服器接收時間", "搶答排名", "題組／提交編號", "審核狀態"])
    for submission in progress:
        for answer in submission["answers"]:
            writer.writerow([answer["question"], answer["slot"], submission["group_name"], answer["answer"], submission["received_at"], submission["rank"], submission["bundle_id"], submission["review_status"]])
    body = ("\ufeff" + output.getvalue()).encode("utf-8")
    return Response(body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{room_id}-history.csv"'})


@api_router.post("/rooms/{room_id}/google-sheet/backfill")
def backfill_google_sheet(
    room_id: str,
    x_teacher_token: str | None = Header(default=None),
    service: RoomService = Depends(get_room_service),
    google_adapter: GoogleSheetsAdapter = Depends(get_google_sheets_adapter),
):
    try:
        service.require_teacher(room_id, x_teacher_token)
        return service.writeback_google_sheet(room_id, google_adapter)
    except RoomError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def include_api(app: FastAPI) -> None:
    app.include_router(api_router)
