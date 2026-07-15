from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from .gateway import ApiGateway, ApiGatewayError, ApiUnavailable


DEMO_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


class CreateLiveRequest(BaseModel):
    owner_id: UUID | None = None
    title: str
    description: str = ""


class PublicLive(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    owner_id: UUID
    title: str
    description: str
    status: str
    version: int
    started_at: datetime | None = None


class CreatedLive(BaseModel):
    live: PublicLive
    rtmp_server: str
    stream_key: str


class PlaybackSession(BaseModel):
    live_id: UUID
    manifest_url: str
    chat_websocket_url: str
    chat_user_id: UUID
    chat_display_name: str


def create_app(
    gateway: ApiGateway,
    *,
    hls_base_url: str = "http://localhost/hls",
    chat_websocket_base_url: str = "ws://localhost",
    demo_user_id: UUID = DEMO_USER_ID,
    demo_display_name: str = "Visitante",
) -> FastAPI:
    app = FastAPI(title="Live Streaming BFF", version="0.1.0")

    @app.exception_handler(ApiGatewayError)
    async def api_error_handler(_request, error: ApiGatewayError) -> JSONResponse:
        status_code = error.status_code if 400 <= error.status_code < 500 else 502
        return JSONResponse({"detail": str(error)}, status_code=status_code)

    @app.exception_handler(ApiUnavailable)
    async def api_unavailable_handler(
        _request, error: ApiUnavailable
    ) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=503)

    @app.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/lives", response_model=CreatedLive, status_code=201)
    async def create_live(request: CreateLiveRequest) -> CreatedLive:
        response = gateway.create_live(
            owner_id=request.owner_id or demo_user_id,
            title=request.title,
            description=request.description,
        )
        return CreatedLive.model_validate(response)

    @app.get("/api/v1/lives", response_model=list[PublicLive])
    async def list_lives() -> list[PublicLive]:
        return [PublicLive.model_validate(item) for item in gateway.list_lives(status="live")]

    @app.get("/api/v1/lives/{live_id}", response_model=PublicLive)
    async def get_live(live_id: UUID) -> PublicLive:
        return PublicLive.model_validate(gateway.get_live(live_id))

    @app.post(
        "/api/v1/lives/{live_id}/playback-session",
        response_model=PlaybackSession,
    )
    async def playback_session(
        live_id: UUID,
    ) -> PlaybackSession | JSONResponse:
        live = PublicLive.model_validate(gateway.get_live(live_id))
        if live.status != "live":
            return JSONResponse(
                {"detail": "Live playback is not ready"}, status_code=409
            )
        return PlaybackSession(
            live_id=live_id,
            manifest_url=(
                f"{hls_base_url.rstrip('/')}/{live_id}/current/index.m3u8"
            ),
            chat_websocket_url=(
                f"{chat_websocket_base_url.rstrip('/')}/ws/v1/lives/{live_id}"
            ),
            chat_user_id=demo_user_id,
            chat_display_name=demo_display_name,
        )

    return app