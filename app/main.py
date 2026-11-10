from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import include_api
from app.database import Database
from app.realtime import Client, connections
from app.repositories.room_repository import RoomRepository
from app.services.room_service import RoomError, RoomService

ROOT = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    app.state.database = Database()
    app.state.database.migrate()
    yield


app = FastAPI(title="簡課堂搶答系統", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
include_api(app)


@app.websocket("/ws/{room_id}")
async def room_socket(websocket: WebSocket, room_id: str):
    await websocket.accept()
    service = RoomService(RoomRepository(getattr(app.state, "database", Database())))
    client: Client | None = None
    try:
        auth = await websocket.receive_json()
        role = auth.get("role")
        if role == "teacher":
            service.require_teacher(room_id, auth.get("token"))
            client = Client(websocket=websocket, role="teacher")
        elif role == "student":
            group = service.require_group(room_id, auth.get("group_id", ""), auth.get("token"))
            client = Client(websocket=websocket, role="student", group_id=group["id"])
        elif role == "projection":
            service.require_projection(room_id, auth.get("token", ""))
            client = Client(websocket=websocket, role="projection")
        else:
            await websocket.close(code=1008, reason="Invalid session")
            return
        if not connections.connect(room_id, client):
            await websocket.close(code=1008, reason="Group already connected")
            return
        await websocket.send_json(service.snapshot(room_id, role, client.group_id))
        while True:
            message = await websocket.receive_json()
            if message.get("type") != "ping":
                await websocket.send_json({"type": "error", "detail": "不支援的即時訊息。"})
                continue
            if role == "student":
                service.require_group(room_id, client.group_id or "", auth.get("token"))
            await websocket.send_json({"type": "pong"})
    except RoomError as exc:
        await websocket.send_json({"type": "error", "detail": str(exc)})
        await websocket.close(code=1008, reason="Invalid session")
    except WebSocketDisconnect:
        pass
    finally:
        if client is not None:
            connections.disconnect(room_id, client)


@app.get("/", response_class=FileResponse)
def home() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/teacher", response_class=FileResponse)
def teacher_page() -> FileResponse:
    return FileResponse(ROOT / "static" / "teacher.html")


@app.get("/student", response_class=FileResponse)
def student_page() -> FileResponse:
    return FileResponse(ROOT / "static" / "student.html")


@app.get("/projector/{room_id}", response_class=FileResponse)
def projection_page(room_id: str) -> FileResponse:
    return FileResponse(ROOT / "static" / "projector.html")


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})
