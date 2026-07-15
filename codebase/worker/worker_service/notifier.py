from typing import Protocol
from uuid import UUID

import httpx


class WorkerNotifier(Protocol):
    def notify_ready(self, live_id: UUID, generation: int) -> None: ...


class HttpWorkerNotifier:
    def __init__(self, api_base_url: str, *, timeout_seconds: float = 3.0) -> None:
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def notify_ready(self, live_id: UUID, generation: int) -> None:
        response = httpx.post(
            f"{self._api_base_url}/internal/v1/workers/ready",
            json={"live_id": str(live_id), "generation": generation},
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()