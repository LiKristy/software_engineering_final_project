from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket


@dataclass(eq=False)
class Client:
    websocket: WebSocket
    role: str
    group_id: str | None = None


class ConnectionManager:
    """Single-process WebSocket fan-out; authorization is decided per event."""

    def __init__(self):
        self._rooms: dict[str, set[Client]] = defaultdict(set)

    def connect(self, room_id: str, client: Client) -> bool:
        if client.role == "student" and any(
            existing.role == "student" and existing.group_id == client.group_id
            for existing in self._rooms[room_id]
        ):
            return False
        self._rooms[room_id].add(client)
        return True

    def disconnect(self, room_id: str, client: Client) -> None:
        self._rooms[room_id].discard(client)

    async def broadcast(
        self, room_id: str, event: dict[str, Any], audience: set[str]
    ) -> None:
        stale: list[Client] = []
        for client in tuple(self._rooms[room_id]):
            if client.role not in audience:
                continue
            try:
                await client.websocket.send_json(event)
            except Exception:
                stale.append(client)
        for client in stale:
            self.disconnect(room_id, client)

    async def broadcast_group(self, room_id: str, group_id: str, event: dict[str, Any]) -> None:
        for client in tuple(self._rooms[room_id]):
            if client.role == "student" and client.group_id == group_id:
                try:
                    await client.websocket.send_json(event)
                except Exception:
                    self.disconnect(room_id, client)


connections = ConnectionManager()
