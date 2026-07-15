from typing import Any, Protocol
from uuid import UUID

import httpx


class ApiGatewayError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


class ApiUnavailable(RuntimeError):
    pass


class ApiGateway(Protocol):
    def create_live(
        self, *, owner_id: UUID, title: str, description: str
    ) -> dict[str, Any]: ...

    def list_lives(self, *, status: str) -> list[dict[str, Any]]: ...

    def get_live(self, live_id: UUID) -> dict[str, Any]: ...


class HttpApiGateway:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 3.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client = client

    def create_live(
        self, *, owner_id: UUID, title: str, description: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/lives",
            json={
                "owner_id": str(owner_id),
                "title": title,
                "description": description,
            },
        )

    def list_lives(self, *, status: str) -> list[dict[str, Any]]:
        response = self._request("GET", "/v1/lives", params={"status": status})
        if not isinstance(response, list):
            raise ApiUnavailable("API returned an invalid live list")
        return response

    def get_live(self, live_id: UUID) -> dict[str, Any]:
        response = self._request("GET", f"/v1/lives/{live_id}")
        if not isinstance(response, dict):
            raise ApiUnavailable("API returned an invalid live")
        return response

    def _request(self, method: str, path: str, **kwargs):
        request = self._client.request if self._client is not None else httpx.request
        try:
            response = request(
                method,
                f"{self._base_url}{path}",
                timeout=self._timeout_seconds,
                **kwargs,
            )
        except httpx.RequestError as error:
            raise ApiUnavailable("API service is unavailable") from error
        if not response.is_success:
            try:
                detail = str(response.json().get("detail", "API request failed"))
            except ValueError:
                detail = "API request failed"
            raise ApiGatewayError(response.status_code, detail)
        try:
            return response.json()
        except ValueError as error:
            raise ApiUnavailable("API returned invalid JSON") from error