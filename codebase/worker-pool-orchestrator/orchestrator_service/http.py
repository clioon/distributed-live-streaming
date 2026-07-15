from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .health import OrchestratorProbe


class BackgroundService(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


def create_app(
    probe: OrchestratorProbe,
    background_service: BackgroundService | None = None,
) -> FastAPI:
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
        title="Worker Pool Orchestrator",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health/live")
    async def liveness() -> JSONResponse:
        health = probe.snapshot()
        return JSONResponse(
            {
                "running": health.running,
                "leader": health.leader,
                "last_error": health.last_error,
            },
            status_code=200 if health.running else 503,
        )

    @app.get("/health/ready")
    async def readiness() -> JSONResponse:
        health = probe.snapshot()
        ready = health.running and health.leader and health.last_error is None
        return JSONResponse(
            {
                "running": health.running,
                "leader": health.leader,
                "last_error": health.last_error,
            },
            status_code=200 if ready else 503,
        )

    return app