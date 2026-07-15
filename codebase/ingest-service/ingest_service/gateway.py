from typing import Any

import httpx

from .callbacks import PublishStarted, PublishStopped


class UpstreamRejected(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


class UpstreamUnavailable(RuntimeError):
    pass


class HttpApiGateway:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 3.0,
        client: httpx.Client | None = None,
    ):
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._client = client

    def notify_started(self, notification: PublishStarted) -> None:
        self._post(
            "/internal/v1/ingest/published",
            {
                "live_id": str(notification.live_id),
                "stream_secret": notification.stream_secret,
                "ingest_session_id": str(notification.ingest_session_id),
                "correlation_id": str(notification.correlation_id),
                "client_id": notification.client_id,
                "source_ip": notification.remote_address,
            },
        )

    def notify_stopped(self, notification: PublishStopped) -> None:
        self._post(
            "/internal/v1/ingest/publish-done",
            {
                "live_id": str(notification.live_id),
                "ingest_session_id": str(notification.ingest_session_id),
                "correlation_id": str(notification.correlation_id),
                "reason": notification.reason,
            },
        )

    def _post(self, path: str, payload: dict[str, Any]) -> None:
        try:
            request = self._client.post if self._client is not None else httpx.post
            response = request(
                f"{self._base_url.rstrip('/')}{path}",
                json=payload,
                timeout=self._timeout_seconds,
            )
        except httpx.RequestError as error:
            raise UpstreamUnavailable("API service is unavailable") from error

        if response.is_success:
            return
        try:
            detail = str(response.json().get("detail", "API rejected callback"))
        except ValueError:
            detail = "API rejected callback"
        raise UpstreamRejected(response.status_code, detail)