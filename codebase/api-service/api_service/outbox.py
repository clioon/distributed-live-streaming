import json
import logging
from dataclasses import dataclass
from threading import Event, Thread
from typing import Protocol
from uuid import UUID

import pika
import psycopg
from psycopg.rows import dict_row


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PendingEvent:
    id: UUID
    event_type: str
    payload: dict[str, object]


class OutboxRepository(Protocol):
    def pending(self, limit: int = 50) -> tuple[PendingEvent, ...]: ...

    def mark_published(self, event_id: UUID) -> None: ...

    def record_failure(self, event_id: UUID, error: Exception) -> None: ...


class EventPublisher(Protocol):
    def publish(self, event: PendingEvent) -> None: ...

    def close(self) -> None: ...


class PostgresOutboxRepository:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def pending(self, limit: int = 50) -> tuple[PendingEvent, ...]:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT id, event_type, payload
                FROM outbox_events
                WHERE published_at IS NULL
                ORDER BY occurred_at, id
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return tuple(
            PendingEvent(row["id"], str(row["event_type"]), dict(row["payload"]))
            for row in rows
        )

    def mark_published(self, event_id: UUID) -> None:
        with psycopg.connect(self._dsn) as connection:
            connection.execute(
                """
                UPDATE outbox_events
                SET published_at = now(), attempts = attempts + 1, last_error = NULL
                WHERE id = %s AND published_at IS NULL
                """,
                (event_id,),
            )

    def record_failure(self, event_id: UUID, error: Exception) -> None:
        with psycopg.connect(self._dsn) as connection:
            connection.execute(
                """
                UPDATE outbox_events
                SET attempts = attempts + 1, last_error = %s
                WHERE id = %s AND published_at IS NULL
                """,
                (str(error)[:2000], event_id),
            )


class RabbitEventPublisher:
    def __init__(self, amqp_url: str) -> None:
        self._parameters = pika.URLParameters(amqp_url)
        self._connection = None
        self._channel = None

    def _ensure_channel(self):
        if self._connection is not None and self._connection.is_open:
            return self._channel
        self.close()
        self._connection = pika.BlockingConnection(self._parameters)
        self._channel = self._connection.channel()
        self._channel.confirm_delivery()
        return self._channel

    def publish(self, event: PendingEvent) -> None:
        for attempt in range(2):
            try:
                channel = self._ensure_channel()
                channel.basic_publish(
                    exchange="streaming.events",
                    routing_key=event.event_type,
                    body=json.dumps(event.payload, separators=(",", ":")),
                    properties=pika.BasicProperties(
                        content_type="application/json",
                        delivery_mode=2,
                        message_id=str(event.id),
                    ),
                    mandatory=True,
                )
                self._discard_connection()
                return
            except (
                pika.exceptions.AMQPConnectionError,
                pika.exceptions.ConnectionClosedByBroker,
                pika.exceptions.ConnectionWrongStateError,
                pika.exceptions.StreamLostError,
                pika.exceptions.ChannelWrongStateError,
            ):
                self._discard_connection()
                if attempt == 1:
                    raise

    def _discard_connection(self) -> None:
        connection = self._connection
        self._connection = None
        self._channel = None
        if connection is not None:
            try:
                if connection.is_open:
                    connection.close()
            except (pika.exceptions.AMQPError, OSError):
                pass

    def close(self) -> None:
        self._discard_connection()


class OutboxRelay:
    def __init__(
        self,
        repository: OutboxRepository,
        publisher: EventPublisher,
        *,
        poll_seconds: float = 1.0,
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._poll_seconds = poll_seconds
        self._stop = Event()
        self._thread: Thread | None = None

    def dispatch_once(self) -> int:
        published = 0
        for event in self._repository.pending():
            try:
                self._publisher.publish(event)
                self._repository.mark_published(event.id)
                published += 1
            except Exception as error:
                self._repository.record_failure(event.id, error)
                raise
        return published

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="outbox-relay", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.dispatch_once()
            except pika.exceptions.AMQPError as error:
                LOGGER.warning("Outbox broker unavailable; retrying: %s", error)
            except Exception:
                LOGGER.exception("Outbox dispatch failed; it will be retried")
            self._stop.wait(self._poll_seconds)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self._poll_seconds * 2))
        self._publisher.close()