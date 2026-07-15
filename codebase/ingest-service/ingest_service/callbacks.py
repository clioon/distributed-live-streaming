from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qs
from uuid import UUID, uuid5


INGEST_SESSION_NAMESPACE = UUID("0e57eae0-40fb-4fb0-a3cf-c5c87458e681")


class InvalidCallback(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PublishStarted:
    live_id: UUID
    stream_secret: str
    ingest_session_id: UUID
    correlation_id: UUID
    client_id: str
    remote_address: str | None


@dataclass(frozen=True, slots=True)
class PublishStopped:
    live_id: UUID
    ingest_session_id: UUID
    correlation_id: UUID
    reason: str


class ApiGateway(Protocol):
    def notify_started(self, notification: PublishStarted) -> None: ...

    def notify_stopped(self, notification: PublishStopped) -> None: ...


class CallbackService:
    def __init__(self, gateway: ApiGateway, *, expected_application: str = "live"):
        self._gateway = gateway
        self._expected_application = expected_application

    def on_publish(self, fields: Mapping[str, str]) -> PublishStarted:
        live_id, stream_secret, client_id = self._publisher(fields)
        notification = PublishStarted(
            live_id=live_id,
            stream_secret=stream_secret,
            ingest_session_id=self._session_id(live_id, client_id),
            correlation_id=self._correlation_id(live_id, client_id, "started"),
            client_id=client_id,
            remote_address=fields.get("addr") or None,
        )
        self._gateway.notify_started(notification)
        return notification

    def on_publish_done(self, fields: Mapping[str, str]) -> PublishStopped:
        live_id, _stream_secret, client_id = self._publisher(fields)
        notification = PublishStopped(
            live_id=live_id,
            ingest_session_id=self._session_id(live_id, client_id),
            correlation_id=self._correlation_id(live_id, client_id, "stopped"),
            reason="publisher_disconnected",
        )
        self._gateway.notify_stopped(notification)
        return notification

    def _publisher(self, fields: Mapping[str, str]) -> tuple[UUID, str, str]:
        application = fields.get("app", "")
        if application != self._expected_application:
            raise InvalidCallback("Unexpected RTMP application")

        raw_name = fields.get("name", "").strip()
        name, separator, embedded_query = raw_name.partition("?")
        try:
            live_id = UUID(name)
        except ValueError as error:
            raise InvalidCallback("Stream name must be a live UUID") from error

        query_parts = [part for part in (fields.get("args", ""), embedded_query) if part]
        query = parse_qs("&".join(query_parts), keep_blank_values=True)
        supplied_tokens = list(query.get("token", []))
        if fields.get("token"):
            supplied_tokens.append(fields["token"])
        tokens = {token for token in supplied_tokens if token}
        if len(tokens) != 1:
            raise InvalidCallback("Exactly one stream token is required")
        stream_token = tokens.pop()
        if len(stream_token) > 256:
            raise InvalidCallback("Exactly one stream token is required")

        client_id = fields.get("clientid", "").strip()
        if not client_id or len(client_id) > 128:
            raise InvalidCallback("A valid RTMP client ID is required")
        return live_id, stream_token, client_id

    @staticmethod
    def _session_id(live_id: UUID, client_id: str) -> UUID:
        return uuid5(INGEST_SESSION_NAMESPACE, f"{live_id}:{client_id}")

    @staticmethod
    def _correlation_id(live_id: UUID, client_id: str, action: str) -> UUID:
        return uuid5(INGEST_SESSION_NAMESPACE, f"{live_id}:{client_id}:{action}")