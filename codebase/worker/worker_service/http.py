from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .supervisor import WorkerHealth, WorkerSupervisor


def _payload(health: WorkerHealth) -> dict[str, object]:
    return {
        "live_id": health.live_id,
        "generation": health.generation,
        "process_running": health.process_running,
        "manifest_ready": health.manifest_ready,
    }


def create_app(
    supervisor: WorkerSupervisor, *, manage_lifecycle: bool = False
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app):
        if manage_lifecycle:
            supervisor.start()
        try:
            yield
        finally:
            if manage_lifecycle:
                supervisor.stop()

    app = FastAPI(title="Live Transcoding Worker", version="0.1.0", lifespan=lifespan)

    @app.get("/health/live")
    async def liveness() -> JSONResponse:
        health = supervisor.health()
        return JSONResponse(_payload(health), status_code=200 if health.process_running else 503)

    @app.get("/health/ready")
    async def readiness() -> JSONResponse:
        health = supervisor.health()
        return JSONResponse(_payload(health), status_code=200 if health.manifest_ready else 503)

    return app