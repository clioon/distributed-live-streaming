from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from secrets import token_urlsafe
from threading import Lock
from typing import Protocol
from uuid import UUID, uuid4

from .domain import DesiredState, DomainEvent, Live, LiveStatus


class LiveNotFound(LookupError):
    pass


class InvalidStreamSecret(ValueError):
    pass


class InvalidLiveTransition(ValueError):
    pass


class ConcurrentLiveUpdate(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IngestSessionStart:
    id: UUID
    live_id: UUID
    client_id: str
    source_ip: str | None
    connected_at: datetime


class LiveStore(Protocol):
    def add(self, live: Live) -> None: ...

    def get(self, live_id: UUID) -> Live: ...

    def list(self, *, status: LiveStatus | None = None) -> tuple[Live, ...]: ...

    def save_with_event(
        self,
        live: Live,
        event: DomainEvent,
        *,
        expected_version: int,
        session_started: IngestSessionStart | None = None,
        session_stopped_id: UUID | None = None,
    ) -> None: ...

    def save(self, live: Live, *, expected_version: int) -> None: ...

    def is_ready(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class CreatedLive:
    live: Live
    stream_key: str


class InMemoryLiveStore:
    def __init__(self) -> None:
        self._lives: dict[UUID, Live] = {}
        self._events: list[DomainEvent] = []
        self._lock = Lock()

    def add(self, live: Live) -> None:
        with self._lock:
            if live.id in self._lives:
                raise ConcurrentLiveUpdate(f"Live {live.id} already exists")
            self._lives[live.id] = live

    def get(self, live_id: UUID) -> Live:
        with self._lock:
            try:
                return self._lives[live_id]
            except KeyError as error:
                raise LiveNotFound(f"Live {live_id} was not found") from error

    def list(self, *, status: LiveStatus | None = None) -> tuple[Live, ...]:
        with self._lock:
            lives = self._lives.values()
            if status is not None:
                lives = (live for live in lives if live.status is status)
            return tuple(sorted(lives, key=lambda live: (live.created_at, live.id)))

    def save_with_event(
        self,
        live: Live,
        event: DomainEvent,
        *,
        expected_version: int,
        session_started: IngestSessionStart | None = None,
        session_stopped_id: UUID | None = None,
    ) -> None:
        with self._lock:
            current = self._lives.get(live.id)
            if current is None:
                raise LiveNotFound(f"Live {live.id} was not found")
            if current.version != expected_version:
                raise ConcurrentLiveUpdate(
                    f"Expected live version {expected_version}, found {current.version}"
                )
            self._lives[live.id] = live
            self._events.append(event)

    def save(self, live: Live, *, expected_version: int) -> None:
        with self._lock:
            current = self._lives.get(live.id)
            if current is None:
                raise LiveNotFound(f"Live {live.id} was not found")
            if current.version != expected_version:
                raise ConcurrentLiveUpdate(
                    f"Expected live version {expected_version}, found {current.version}"
                )
            self._lives[live.id] = live

    def is_ready(self) -> bool:
        return True

    def events(self) -> tuple[DomainEvent, ...]:
        with self._lock:
            return tuple(self._events)


class LiveService:
    def __init__(
        self,
        store: LiveStore,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
        secret_factory: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or uuid4
        self._secret_factory = secret_factory or (lambda: token_urlsafe(32))

    def create_live(
        self,
        *,
        owner_id: UUID,
        title: str,
        description: str = "",
    ) -> CreatedLive:
        normalized_title = title.strip()
        normalized_description = description.strip()
        if not normalized_title or len(normalized_title) > 120:
            raise ValueError("Title must contain between 1 and 120 characters")
        if len(normalized_description) > 1_000:
            raise ValueError("Description must contain at most 1000 characters")

        now = self._clock()
        live_id = self._id_factory()
        stream_secret = self._secret_factory()
        live = Live(
            id=live_id,
            owner_id=owner_id,
            title=normalized_title,
            description=normalized_description,
            desired_state=DesiredState.RUNNING,
            status=LiveStatus.CREATED,
            stream_secret_hash=self._hash_secret(stream_secret),
            version=1,
            created_at=now,
            updated_at=now,
        )
        self._store.add(live)
        return CreatedLive(live=live, stream_key=f"{live_id}?token={stream_secret}")

    def get_live(self, live_id: UUID) -> Live:
        return self._store.get(live_id)

    def list_lives(self, *, status: LiveStatus | None = None) -> tuple[Live, ...]:
        return self._store.list(status=status)

    def is_ready(self) -> bool:
        return self._store.is_ready()

    def worker_ready(self, *, live_id: UUID, generation: int) -> Live:
        if generation < 1:
            raise ValueError("Worker generation must be greater than zero")
        live = self._store.get(live_id)
        if live.status is LiveStatus.LIVE and live.worker_generation >= generation:
            return live
        if live.status not in {
            LiveStatus.INGESTING,
            LiveStatus.PROVISIONING,
            LiveStatus.LIVE,
        }:
            raise InvalidLiveTransition(
                f"Cannot mark playback ready while live is {live.status.value}"
            )
        now = self._clock()
        updated = replace(
            live,
            status=LiveStatus.LIVE,
            worker_generation=generation,
            playback_path=f"/hls/{live_id}/current/index.m3u8",
            playback_ready_at=now,
            updated_at=now,
            version=live.version + 1,
        )
        self._store.save(updated, expected_version=live.version)
        return updated

    def ingest_started(
        self,
        *,
        live_id: UUID,
        stream_secret: str,
        ingest_session_id: UUID,
        correlation_id: UUID | None = None,
        client_id: str = "unknown",
        source_ip: str | None = None,
    ) -> Live:
        live = self._store.get(live_id)
        if not self._secret_matches(stream_secret, live.stream_secret_hash):
            raise InvalidStreamSecret("The stream secret is invalid")

        if (
            live.current_ingest_session_id == ingest_session_id
            and live.status
            in {LiveStatus.INGESTING, LiveStatus.PROVISIONING, LiveStatus.LIVE}
        ):
            return live
        if live.status is not LiveStatus.CREATED:
            raise InvalidLiveTransition(
                f"Cannot start ingest while live is {live.status.value}"
            )

        now = self._clock()
        normalized_client_id = client_id.strip()
        if not normalized_client_id or len(normalized_client_id) > 128:
            raise ValueError("Client ID must contain between 1 and 128 characters")
        updated = replace(
            live,
            status=LiveStatus.INGESTING,
            current_ingest_session_id=ingest_session_id,
            started_at=now,
            updated_at=now,
            version=live.version + 1,
        )
        event = self._event(
            event_type="live.ingest.started.v1",
            live=updated,
            correlation_id=correlation_id,
            data={
                "live_id": str(live_id),
                "ingest_session_id": str(ingest_session_id),
                "aggregate_version": updated.version,
            },
        )
        self._store.save_with_event(
            updated,
            event,
            expected_version=live.version,
            session_started=IngestSessionStart(
                id=ingest_session_id,
                live_id=live_id,
                client_id=normalized_client_id,
                source_ip=source_ip,
                connected_at=now,
            ),
        )
        return updated

    def ingest_stopped(
        self,
        *,
        live_id: UUID,
        ingest_session_id: UUID,
        reason: str = "publisher_disconnected",
        correlation_id: UUID | None = None,
    ) -> Live:
        live = self._store.get(live_id)
        if live.current_ingest_session_id is None:
            raise InvalidLiveTransition(
                f"Cannot stop ingest while live is {live.status.value}"
            )
        if live.current_ingest_session_id != ingest_session_id:
            return live
        if live.status in {LiveStatus.STOPPING, LiveStatus.ENDED}:
            return live
        if live.status not in {
            LiveStatus.INGESTING,
            LiveStatus.PROVISIONING,
            LiveStatus.LIVE,
            LiveStatus.FAILED,
        }:
            raise InvalidLiveTransition(
                f"Cannot stop ingest while live is {live.status.value}"
            )

        normalized_reason = reason.strip() or "publisher_disconnected"
        now = self._clock()
        updated = replace(
            live,
            desired_state=DesiredState.STOPPED,
            status=LiveStatus.ENDED,
            updated_at=now,
            ended_at=now,
            version=live.version + 1,
        )
        event = self._event(
            event_type="live.ingest.stopped.v1",
            live=updated,
            correlation_id=correlation_id,
            data={
                "live_id": str(live_id),
                "ingest_session_id": str(ingest_session_id),
                "aggregate_version": updated.version,
                "reason": normalized_reason,
            },
        )
        self._store.save_with_event(
            updated,
            event,
            expected_version=live.version,
            session_stopped_id=ingest_session_id,
        )
        return updated

    def _event(
        self,
        *,
        event_type: str,
        live: Live,
        correlation_id: UUID | None,
        data: dict[str, object],
    ) -> DomainEvent:
        return DomainEvent(
            id=self._id_factory(),
            type=event_type,
            source="api-service",
            subject=f"live/{live.id}",
            occurred_at=self._clock(),
            correlation_id=correlation_id or self._id_factory(),
            aggregate_version=live.version,
            data=data,
        )

    @staticmethod
    def _hash_secret(secret: str) -> str:
        return sha256(secret.encode("utf-8")).hexdigest()

    @classmethod
    def _secret_matches(cls, secret: str, expected_hash: str) -> bool:
        return cls._hash_secret(secret) == expected_hash