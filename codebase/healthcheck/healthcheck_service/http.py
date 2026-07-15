import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .monitor import HealthMonitor, MonitorOutcome


def create_app(
    monitor: HealthMonitor,
    *,
    manage_lifecycle: bool = False,
    check_interval_seconds: float = 5.0,
) -> FastAPI:
    if check_interval_seconds <= 0:
        raise ValueError("Check interval must be greater than zero")

    async def monitor_loop() -> None:
        while True:
            await asyncio.to_thread(monitor.check_once)
            await asyncio.sleep(check_interval_seconds)

    @asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(monitor_loop()) if manage_lifecycle else None
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(
        title="Orchestrator Health Monitor",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def readiness() -> JSONResponse:
        state = monitor.snapshot()
        ready = state.last_outcome in {
            MonitorOutcome.HEALTHY,
            MonitorOutcome.RESTARTED,
        }
        return JSONResponse(
            {
                "checks": state.checks,
                "consecutive_failures": state.consecutive_failures,
                "restart_count": state.restart_count,
                "cooldown_remaining": state.cooldown_remaining,
                "last_outcome": state.last_outcome,
                "has_error": state.last_error is not None,
            },
            status_code=200 if ready else 503,
        )

    return app