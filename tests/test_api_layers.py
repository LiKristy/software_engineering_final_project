from fastapi.testclient import TestClient

from app.api import api_router, get_room_service
from app.main import app


def test_room_endpoint_calls_service_dependency():
    class FakeService:
        def get_room(self, room_id):
            assert room_id == "AB12CD"
            return {"id": room_id, "status": "waiting"}

    app.dependency_overrides[get_room_service] = FakeService
    try:
        response = TestClient(app).get("/api/rooms/AB12CD")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"room_id": "AB12CD", "status": "waiting"}
    assert any(route.path == "/api/rooms/{room_id}" for route in api_router.routes)
