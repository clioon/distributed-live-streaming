from collections.abc import Mapping
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .domain import DesiredState, DomainEvent, Live, LiveStatus
from .service import (
    ConcurrentLiveUpdate,
    IngestSessionStart,
    LiveNotFound,
)


LIVE_COLUMNS = """
    id,
    owner_id,
    title,
    description,
    desired_state::text AS desired_state,
    status::text AS status,
    stream_secret_hash,
    version,
    created_at,
    updated_at,
    current_ingest_session_id,
    started_at,
    ended_at,
    failure_reason
    , worker_generation
    , playback_path
    , playback_ready_at
"""


class PostgresLiveStore:
    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN cannot be empty")
        self._dsn = dsn

    def _connect(self):
        return psycopg.connect(self._dsn, row_factory=dict_row)

    @staticmethod
    def _live(row: Mapping[str, object]) -> Live:
        return Live(
            id=row["id"],
            owner_id=row["owner_id"],
            title=str(row["title"]),
            description=str(row["description"]),
            desired_state=DesiredState(str(row["desired_state"])),
            status=LiveStatus(str(row["status"])),
            stream_secret_hash=str(row["stream_secret_hash"]),
            version=int(row["version"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            current_ingest_session_id=row["current_ingest_session_id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            failure_reason=row["failure_reason"],
            worker_generation=int(row["worker_generation"]),
            playback_path=row["playback_path"],
            playback_ready_at=row["playback_ready_at"],
        )

    def add(self, live: Live) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO lives (
                        id, owner_id, title, description, desired_state, status,
                        stream_secret_hash, version, created_at, updated_at,
                        current_ingest_session_id, started_at, ended_at,
                        failure_reason
                        , worker_generation, playback_path, playback_ready_at
                    ) VALUES (
                        %s, %s, %s, %s, %s::live_desired_state,
                        %s::live_status, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    """,
                    (
                        live.id,
                        live.owner_id,
                        live.title,
                        live.description,
                        live.desired_state.value,
                        live.status.value,
                        live.stream_secret_hash,
                        live.version,
                        live.created_at,
                        live.updated_at,
                        live.current_ingest_session_id,
                        live.started_at,
                        live.ended_at,
                        live.failure_reason,
                        live.worker_generation,
                        live.playback_path,
                        live.playback_ready_at,
                    ),
                )
        except psycopg.errors.UniqueViolation as error:
            raise ConcurrentLiveUpdate(f"Live {live.id} already exists") from error

    def get(self, live_id: UUID) -> Live:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {LIVE_COLUMNS} FROM lives WHERE id = %s",
                (live_id,),
            ).fetchone()
        if row is None:
            raise LiveNotFound(f"Live {live_id} was not found")
        return self._live(row)

    def list(self, *, status: LiveStatus | None = None) -> tuple[Live, ...]:
        query = f"SELECT {LIVE_COLUMNS} FROM lives"
        parameters: tuple[object, ...] = ()
        if status is not None:
            query += " WHERE status = %s::live_status"
            parameters = (status.value,)
        query += " ORDER BY created_at, id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(self._live(row) for row in rows)

    def save_with_event(
        self,
        live: Live,
        event: DomainEvent,
        *,
        expected_version: int,
        session_started: IngestSessionStart | None = None,
        session_stopped_id: UUID | None = None,
    ) -> None:
        with self._connect() as connection:
            if session_started is not None:
                connection.execute(
                    """
                    INSERT INTO ingest_sessions (
                        id, live_id, status, client_id, source_ip, connected_at
                    ) VALUES (%s, %s, 'connected', %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        session_started.id,
                        session_started.live_id,
                        session_started.client_id,
                        session_started.source_ip,
                        session_started.connected_at,
                    ),
                )
            if session_stopped_id is not None:
                connection.execute(
                    """
                    UPDATE ingest_sessions
                    SET status = 'disconnected', disconnected_at = %s
                    WHERE id = %s AND live_id = %s
                    """,
                    (event.occurred_at, session_stopped_id, live.id),
                )

            updated = connection.execute(
                """
                UPDATE lives
                SET owner_id = %s,
                    title = %s,
                    description = %s,
                    desired_state = %s::live_desired_state,
                    status = %s::live_status,
                    stream_secret_hash = %s,
                    version = %s,
                    current_ingest_session_id = %s,
                    started_at = %s,
                    ended_at = %s,
                    failure_reason = %s
                    , worker_generation = %s
                    , playback_path = %s
                    , playback_ready_at = %s
                WHERE id = %s AND version = %s
                RETURNING id
                """,
                (
                    live.owner_id,
                    live.title,
                    live.description,
                    live.desired_state.value,
                    live.status.value,
                    live.stream_secret_hash,
                    live.version,
                    live.current_ingest_session_id,
                    live.started_at,
                    live.ended_at,
                    live.failure_reason,
                    live.worker_generation,
                    live.playback_path,
                    live.playback_ready_at,
                    live.id,
                    expected_version,
                ),
            ).fetchone()
            if updated is None:
                raise ConcurrentLiveUpdate(
                    f"Live {live.id} no longer has version {expected_version}"
                )
            connection.execute(
                """
                INSERT INTO outbox_events (
                    id, aggregate_type, aggregate_id, aggregate_version,
                    event_type, payload, occurred_at
                ) VALUES (%s, 'live', %s, %s, %s, %s, %s)
                """,
                (
                    event.id,
                    live.id,
                    event.aggregate_version,
                    event.type,
                    Jsonb(event.as_dict()),
                    event.occurred_at,
                ),
            )

    def save(self, live: Live, *, expected_version: int) -> None:
        with self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE lives
                SET desired_state = %s::live_desired_state,
                    status = %s::live_status,
                    version = %s,
                    worker_generation = %s,
                    playback_path = %s,
                    playback_ready_at = %s,
                    ended_at = %s,
                    failure_reason = %s
                WHERE id = %s AND version = %s
                RETURNING id
                """,
                (
                    live.desired_state.value,
                    live.status.value,
                    live.version,
                    live.worker_generation,
                    live.playback_path,
                    live.playback_ready_at,
                    live.ended_at,
                    live.failure_reason,
                    live.id,
                    expected_version,
                ),
            ).fetchone()
            if updated is None:
                raise ConcurrentLiveUpdate(
                    f"Live {live.id} no longer has version {expected_version}"
                )

    def is_ready(self) -> bool:
        try:
            with self._connect() as connection:
                connection.execute("SELECT 1 FROM lives LIMIT 1")
            return True
        except psycopg.Error:
            return False