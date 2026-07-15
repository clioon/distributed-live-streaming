import asyncio
from uuid import UUID

from fastapi import WebSocket


class ConnectionHub:
    def __init__(
        self,
        *,
        max_connections: int = 1_000,
        max_connections_per_live: int = 250,
        max_connections_per_user: int = 3,
        send_timeout_seconds: float = 2.0,
    ) -> None:
        if min(
            max_connections,
            max_connections_per_live,
            max_connections_per_user,
        ) < 1:
            raise ValueError("Connection limits must be greater than zero")
        self._connections: dict[UUID, set[WebSocket]] = {}
        self._user_connections: dict[tuple[UUID, UUID], set[WebSocket]] = {}
        self._owners: dict[WebSocket, tuple[UUID, UUID]] = {}
        self._max_connections = max_connections
        self._max_connections_per_live = max_connections_per_live
        self._max_connections_per_user = max_connections_per_user
        self._send_timeout_seconds = send_timeout_seconds

    async def connect(
        self, live_id: UUID, user_id: UUID, websocket: WebSocket
    ) -> bool:
        live_connections = self._connections.setdefault(live_id, set())
        user_key = (live_id, user_id)
        user_connections = self._user_connections.setdefault(user_key, set())
        if (
            len(self._owners) >= self._max_connections
            or len(live_connections) >= self._max_connections_per_live
            or len(user_connections) >= self._max_connections_per_user
        ):
            await websocket.close(code=4429, reason="chat connection limit reached")
            return False
        await websocket.accept()
        live_connections.add(websocket)
        user_connections.add(websocket)
        self._owners[websocket] = user_key
        return True

    def disconnect(self, websocket: WebSocket) -> None:
        owner = self._owners.pop(websocket, None)
        if owner is None:
            return
        live_id, user_id = owner
        connections = self._connections.get(live_id)
        if connections is not None:
            connections.discard(websocket)
        if not connections:
            self._connections.pop(live_id, None)
        user_key = (live_id, user_id)
        user_connections = self._user_connections.get(user_key)
        if user_connections is not None:
            user_connections.discard(websocket)
        if not user_connections:
            self._user_connections.pop(user_key, None)

    async def broadcast(self, live_id: UUID, payload: dict[str, object]) -> None:
        async def send(websocket: WebSocket) -> None:
            try:
                await asyncio.wait_for(
                    websocket.send_json(payload),
                    timeout=self._send_timeout_seconds,
                )
            except (TimeoutError, RuntimeError):
                self.disconnect(websocket)

        await asyncio.gather(
            *(send(websocket) for websocket in tuple(self._connections.get(live_id, ())))
        )