from contextlib import asynccontextmanager
from datetime import datetime
from typing import Protocol
from uuid import UUID

from fastapi import FastAPI, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .domain import DesiredState, Live, LiveStatus
from .service import (
    InMemoryLiveStore,
    InvalidLiveTransition,
    InvalidStreamSecret,
    LiveNotFound,
    LiveService,
)


class BackgroundService(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


class CreateLiveRequest(BaseModel):
    owner_id: UUID
    title: str
    description: str = ""


class LiveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    title: str
    description: str
    desired_state: DesiredState
    status: LiveStatus
    version: int
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    failure_reason: str | None


class CreatedLiveResponse(BaseModel):
    live: LiveResponse
    rtmp_server: str
    stream_key: str


class IngestStartedRequest(BaseModel):
    live_id: UUID
    stream_secret: str = Field(min_length=1, max_length=256)
    ingest_session_id: UUID
    correlation_id: UUID | None = None
    client_id: str = Field(min_length=1, max_length=128)
    source_ip: str | None = Field(default=None, max_length=45)


class IngestStoppedRequest(BaseModel):
    live_id: UUID
    ingest_session_id: UUID
    reason: str = Field(default="publisher_disconnected", max_length=200)
    correlation_id: UUID | None = None


class WorkerReadyRequest(BaseModel):
    live_id: UUID
    generation: int = Field(ge=1)


def _live_response(live: Live) -> LiveResponse:
    return LiveResponse.model_validate(live)


def create_app(
    service: LiveService | None = None,
    *,
    rtmp_server: str = "rtmp://localhost/live",
    background_service: BackgroundService | None = None,
) -> FastAPI:
    live_service = service or LiveService(InMemoryLiveStore())

    @asynccontextmanager
    async def lifespan(_app):
        if background_service is not None:
            background_service.start()
        try:
            yield
        finally:
            if background_service is not None:
                background_service.stop()

    app = FastAPI(
        title="Distributed Live Streaming API",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.exception_handler(LiveNotFound)
    async def live_not_found_handler(_request, error: LiveNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(InvalidStreamSecret)
    async def invalid_secret_handler(
        _request, error: InvalidStreamSecret
    ) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(error)})

    @app.exception_handler(InvalidLiveTransition)
    async def invalid_transition_handler(
        _request, error: InvalidLiveTransition
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(ValueError)
    async def value_error_handler(_request, error: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.get("/health/live", status_code=status.HTTP_200_OK)
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def readiness() -> JSONResponse:
        ready = live_service.is_ready()
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ready" if ready else "unavailable"},
        )

    @app.post(
        "/v1/lives",
        response_model=CreatedLiveResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_live(request: CreateLiveRequest) -> CreatedLiveResponse:
        created = live_service.create_live(
            owner_id=request.owner_id,
            title=request.title,
            description=request.description,
        )
        return CreatedLiveResponse(
            live=_live_response(created.live),
            rtmp_server=rtmp_server,
            stream_key=created.stream_key,
        )

    @app.get("/v1/lives", response_model=list[LiveResponse])
    async def list_lives(
        live_status: LiveStatus | None = Query(default=None, alias="status"),
    ) -> list[LiveResponse]:
        return [
            _live_response(live)
            for live in live_service.list_lives(status=live_status)
        ]

    @app.get("/v1/lives/{live_id}", response_model=LiveResponse)
    async def get_live(live_id: UUID) -> LiveResponse:
        return _live_response(live_service.get_live(live_id))

    @app.post(
        "/internal/v1/ingest/published",
        response_model=LiveResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def ingest_published(request: IngestStartedRequest) -> LiveResponse:
        live = live_service.ingest_started(
            live_id=request.live_id,
            stream_secret=request.stream_secret,
            ingest_session_id=request.ingest_session_id,
            correlation_id=request.correlation_id,
            client_id=request.client_id,
            source_ip=request.source_ip,
        )
        return _live_response(live)

    @app.post(
        "/internal/v1/ingest/publish-done",
        response_model=LiveResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def ingest_publish_done(request: IngestStoppedRequest) -> LiveResponse:
        live = live_service.ingest_stopped(
            live_id=request.live_id,
            ingest_session_id=request.ingest_session_id,
            reason=request.reason,
            correlation_id=request.correlation_id,
        )
        return _live_response(live)

    @app.post(
        "/internal/v1/workers/ready",
        response_model=LiveResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def worker_ready(request: WorkerReadyRequest) -> LiveResponse:
        return _live_response(
            live_service.worker_ready(
                live_id=request.live_id,
                generation=request.generation,
            )
        )

    return app