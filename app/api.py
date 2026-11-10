import json
import zipfile
import csv
from io import BytesIO, StringIO

from fastapi import APIRouter, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.config import get_settings
from app.database import Database
from app.guided_notes import GuidedNotesError
from app.repositories.room_repository import RoomRepository
from app.realtime import connections
from app.services.room_service import RoomError, RoomService


def get_room_service() -> RoomService:
    return RoomService(RoomRepository(Database()))


api_router = APIRouter(prefix="/api")


@api_router.get("/rooms/{room_id}")
def read_room(room_id: str, service: RoomService = Depends(get_room_service)):
    room = service.get_room(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="找不到房間。")
    return {"room_id": room["id"], "status": room["status"]}


@api_router.post("/rooms")
async def create_room(
    file: UploadFile = File(...),
    max_wins: int | None = Form(default=None),
    question_bundles: str = Form(default="[]"),
    service: RoomService = Depends(get_room_service),
):
    settings = get_settings()
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="檔案超過上傳大小限制。")
    if not zipfile.is_zipfile(BytesIO(data)):
        raise HTTPException(status_code=400, detail="請上傳有效的 .xlsx 試算表。")
    try:
        with zipfile.ZipFile(BytesIO(data)) as workbook_zip:
            total_expanded = sum(item.file_size for item in workbook_zip.infolist())
            if total_expanded > 50 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="試算表解壓後超過大小限制。")
        bundles = json.loads(question_bundles)
        if not isinstance(bundles, list) or any(not isinstance(group, list) for group in bundles):
            raise ValueError("題組格式錯誤。")
        result = service.create_room(data, file.filename or "notes.xlsx", max_wins, bundles)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="題組設定格式錯誤。") from exc
    except GuidedNotesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RoomError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
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


@api_router.get("/rooms/{room_id}/export/guided-notes.xlsx")
def export_notes(room_id: str, x_teacher_token: str | None = Header(default=None), service: RoomService = Depends(get_room_service)):
    try:
        service.require_teacher(room_id, x_teacher_token)
        data = service.export_guided_notes(room_id)
    except RoomError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{room_id}-guided-notes.xlsx"'})


def include_api(app: FastAPI) -> None:
    app.include_router(api_router)
