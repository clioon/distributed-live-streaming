import unittest
from unittest.mock import patch
from uuid import UUID

import pika

from api_service.outbox import OutboxRelay, PendingEvent, RabbitEventPublisher


EVENT_ID = UUID("11000000-0000-0000-0000-000000000001")


class Repository:
    def __init__(self) -> None:
        self.event = PendingEvent(EVENT_ID, "live.ingest.started.v1", {"id": str(EVENT_ID)})
        self.published = []
        self.failures = []

    def pending(self, limit=50):
        return () if self.published else (self.event,)

    def mark_published(self, event_id):
        self.published.append(event_id)

    def record_failure(self, event_id, error):
        self.failures.append((event_id, str(error)))


class Publisher:
    def __init__(self) -> None:
        self.events = []
        self.error = None

    def publish(self, event):
        if self.error:
            raise self.error
        self.events.append(event)

    def close(self):
        pass


class ConfirmingChannel:
    def __init__(self) -> None:
        self.calls = []

    def basic_publish(self, **kwargs):
        self.calls.append(kwargs)
        return None


class BrokenChannel:
    def basic_publish(self, **_kwargs):
        raise pika.exceptions.StreamLostError("connection reset")


class OpenConnection:
    is_open = True

    def close(self):
        self.is_open = False


class OutboxRelayTests(unittest.TestCase):
    def test_pika_none_return_means_confirmed_publish(self) -> None:
        publisher = RabbitEventPublisher("amqp://guest:guest@localhost/")
        channel = ConfirmingChannel()
        connection = OpenConnection()
        publisher._connection = connection
        publisher._channel = channel
        event = PendingEvent(
            EVENT_ID,
            "live.ingest.started.v1",
            {"id": str(EVENT_ID)},
        )

        publisher.publish(event)

        self.assertEqual(len(channel.calls), 1)
        self.assertEqual(channel.calls[0]["routing_key"], event.event_type)
        self.assertFalse(connection.is_open)
        self.assertIsNone(publisher._connection)

    def test_transport_loss_reconnects_and_retries_once(self) -> None:
        publisher = RabbitEventPublisher("amqp://guest:guest@localhost/")
        publisher._connection = OpenConnection()
        healthy_channel = ConfirmingChannel()
        event = PendingEvent(
            EVENT_ID,
            "live.ingest.started.v1",
            {"id": str(EVENT_ID)},
        )

        with patch.object(
            publisher,
            "_ensure_channel",
            side_effect=[BrokenChannel(), healthy_channel],
        ) as ensure_channel:
            publisher.publish(event)

        self.assertEqual(ensure_channel.call_count, 2)
        self.assertEqual(len(healthy_channel.calls), 1)

    def test_event_is_marked_only_after_publish_succeeds(self) -> None:
        repository = Repository()
        publisher = Publisher()

        published = OutboxRelay(repository, publisher).dispatch_once()

        self.assertEqual(published, 1)
        self.assertEqual(publisher.events, [repository.event])
        self.assertEqual(repository.published, [EVENT_ID])
        self.assertEqual(repository.failures, [])

    def test_publish_failure_is_recorded_and_event_remains_pending(self) -> None:
        repository = Repository()
        publisher = Publisher()
        publisher.error = RuntimeError("broker unavailable")

        with self.assertRaises(RuntimeError):
            OutboxRelay(repository, publisher).dispatch_once()

        self.assertEqual(repository.published, [])
        self.assertEqual(repository.failures, [(EVENT_ID, "broker unavailable")])


if __name__ == "__main__":
    unittest.main()