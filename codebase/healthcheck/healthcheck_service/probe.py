import httpx


class HttpOrchestratorProbe:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 2.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/health/ready"
        self._timeout_seconds = timeout_seconds
        self._client = client

    def is_healthy(self) -> bool:
        request = self._client.get if self._client is not None else httpx.get
        try:
            response = request(self._url, timeout=self._timeout_seconds)
        except httpx.RequestError:
            return False
        return response.status_code == 200