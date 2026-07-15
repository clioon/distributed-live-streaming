import json
from uuid import UUID, uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .broker import ChatBroker, ChatCapacityExceeded, ConflictingClientMessage
from .hub import ConnectionHub
from .models import ChatIdentity
from .service import ChatService, InvalidChatMessage


def create_app(
    broker: ChatBroker,
    *,
    hub: ConnectionHub | None = None,
) -> FastAPI:
    chat_service = ChatService(broker)
    connection_hub = hub or ConnectionHub()
    app = FastAPI(title="Live Chat Service", version="0.1.0")

    @app.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def readiness() -> JSONResponse:
        ready = broker.is_ready()
        return JSONResponse(
            {"status": "ready" if ready else "unavailable"},
            status_code=200 if ready else 503,
        )

    @app.websocket("/ws/v1/lives/{live_id}")
    async def live_chat(
        websocket: WebSocket,
        live_id: UUID,
        user_id: UUID,
        display_name: str = "Visitante",
    ) -> None:
        display_name = display_name.strip()
        if not display_name or len(display_name) > 80:
            await websocket.close(code=4400, reason="invalid display name")
            return
        identity = ChatIdentity(user_id, display_name, live_id, uuid4())

        if not await connection_hub.connect(live_id, identity.user_id, websocket):
            return
        try:
            while True:
                try:
                    encoded_payload = await websocket.receive_text()
                    payload = json.loads(encoded_payload)
                    if not isinstance(payload, dict):
                        raise InvalidChatMessage("Chat message must be an object")
                    if payload.get("type") != "chat.message.send":
                        raise InvalidChatMessage("Unsupported chat message type")
                    result = chat_service.send(
                        identity=identity,
                        live_id=live_id,
                        client_message_id=UUID(str(payload["client_message_id"])),
                        text=str(payload["text"]),
                    )
                    message_payload = result.message.as_payload()
                    if result.created:
                        await connection_hub.broadcast(live_id, message_payload)
                    else:
                        await websocket.send_json(message_payload)
                except (
                    KeyError,
                    TypeError,
                    ValueError,
                    InvalidChatMessage,
                    ConflictingClientMessage,
                    ChatCapacityExceeded,
                ) as error:
                    await websocket.send_json(
                        {
                            "type": "chat.error",
                            "code": "invalid_message",
                            "detail": str(error),
                        }
                    )
        except WebSocketDisconnect:
            pass
        finally:
            connection_hub.disconnect(websocket)

    return app