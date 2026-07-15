import unittest
from datetime import datetime, timezone
from uuid import UUID

from api_service import (
    InMemoryLiveStore,
    InvalidLiveTransition,
    InvalidStreamSecret,
    LiveService,
    LiveStatus,
)


OWNER_ID = UUID("00000000-0000-0000-0000-000000000001")
LIVE_ID = UUID("00000000-0000-0000-0000-000000000002")
SESSION_ID = UUID("00000000-0000-0000-0000-000000000003")
STALE_SESSION_ID = UUID("00000000-0000-0000-0000-000000000004")
EVENT_ID = UUID("00000000-0000-0000-0000-000000000005")
CORRELATION_ID = UUID("00000000-0000-0000-0000-000000000006")
STOP_EVENT_ID = UUID("00000000-0000-0000-0000-000000000007")
STOP_CORRELATION_ID = UUID("00000000-0000-0000-0000-000000000008")
NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


class LiveServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        identifiers = iter(
            [
                LIVE_ID,
                EVENT_ID,
                CORRELATION_ID,
                STOP_EVENT_ID,
                STOP_CORRELATION_ID,
            ]
        )
        self.store = InMemoryLiveStore()
        self.service = LiveService(
            self.store,
            clock=lambda: NOW,
            id_factory=lambda: next(identifiers),
            secret_factory=lambda: "secret-value",
        )

    def create_live(self):
        return self.service.create_live(
            owner_id=OWNER_ID,
            title="  Distributed Systems Live  ",
            description="  Lecture stream  ",
        )

    def test_create_live_returns_secret_once_and_stores_only_its_hash(self) -> None:
        created = self.create_live()

        self.assertEqual(created.live.status, LiveStatus.CREATED)
        self.assertEqual(created.live.title, "Distributed Systems Live")
        self.assertEqual(created.stream_key, f"{LIVE_ID}?token=secret-value")
        self.assertNotIn("secret-value", created.live.stream_secret_hash)
        self.assertEqual(self.store.events(), ())

    def test_valid_ingest_start_changes_state_and_records_event(self) -> None:
        self.create_live()

        live = self.service.ingest_started(
            live_id=LIVE_ID,
            stream_secret="secret-value",
            ingest_session_id=SESSION_ID,
        )

        self.assertEqual(live.status, LiveStatus.INGESTING)
        self.assertEqual(live.version, 2)
        event = self.store.events()[0]
        self.assertEqual(event.type, "live.ingest.started.v1")
        self.assertEqual(event.data["ingest_session_id"], str(SESSION_ID))
        self.assertNotIn("secret", str(event.data))

    def test_repeated_ingest_start_is_idempotent(self) -> None:
        self.create_live()
        first = self.service.ingest_started(
            live_id=LIVE_ID,
            stream_secret="secret-value",
            ingest_session_id=SESSION_ID,
        )

        repeated = self.service.ingest_started(
            live_id=LIVE_ID,
            stream_secret="secret-value",
            ingest_session_id=SESSION_ID,
        )

        self.assertEqual(repeated, first)
        self.assertEqual(len(self.store.events()), 1)

    def test_invalid_stream_secret_does_not_change_live(self) -> None:
        created = self.create_live()

        with self.assertRaises(InvalidStreamSecret):
            self.service.ingest_started(
                live_id=LIVE_ID,
                stream_secret="wrong-secret",
                ingest_session_id=SESSION_ID,
            )

        self.assertEqual(self.store.get(LIVE_ID), created.live)
        self.assertEqual(self.store.events(), ())

    def test_ingest_stop_is_idempotent_and_emits_one_event(self) -> None:
        self.create_live()
        self.service.ingest_started(
            live_id=LIVE_ID,
            stream_secret="secret-value",
            ingest_session_id=SESSION_ID,
        )

        stopped = self.service.ingest_stopped(
            live_id=LIVE_ID,
            ingest_session_id=SESSION_ID,
        )
        repeated = self.service.ingest_stopped(
            live_id=LIVE_ID,
            ingest_session_id=SESSION_ID,
        )

        self.assertEqual(stopped.status, LiveStatus.ENDED)
        self.assertEqual(stopped.ended_at, NOW)
        self.assertEqual(repeated, stopped)
        self.assertEqual(len(self.store.events()), 2)
        self.assertEqual(self.store.events()[1].type, "live.ingest.stopped.v1")

    def test_stale_stop_does_not_stop_current_ingest_session(self) -> None:
        self.create_live()
        active = self.service.ingest_started(
            live_id=LIVE_ID,
            stream_secret="secret-value",
            ingest_session_id=SESSION_ID,
        )

        result = self.service.ingest_stopped(
            live_id=LIVE_ID,
            ingest_session_id=STALE_SESSION_ID,
        )

        self.assertEqual(result, active)
        self.assertEqual(len(self.store.events()), 1)

    def test_live_cannot_stop_before_ingest_has_started(self) -> None:
        self.create_live()

        with self.assertRaises(InvalidLiveTransition):
            self.service.ingest_stopped(
                live_id=LIVE_ID,
                ingest_session_id=SESSION_ID,
            )

    def test_worker_ready_publishes_playback_and_is_idempotent(self) -> None:
        self.create_live()
        self.service.ingest_started(
            live_id=LIVE_ID,
            stream_secret="secret-value",
            ingest_session_id=SESSION_ID,
        )

        ready = self.service.worker_ready(live_id=LIVE_ID, generation=1)
        repeated = self.service.worker_ready(live_id=LIVE_ID, generation=1)

        self.assertEqual(ready.status, LiveStatus.LIVE)
        self.assertEqual(ready.worker_generation, 1)
        self.assertEqual(
            ready.playback_path,
            f"/hls/{LIVE_ID}/current/index.m3u8",
        )
        self.assertEqual(repeated, ready)

    def test_replacement_worker_advances_generation_without_changing_url(self) -> None:
        self.create_live()
        self.service.ingest_started(
            live_id=LIVE_ID,
            stream_secret="secret-value",
            ingest_session_id=SESSION_ID,
        )
        first = self.service.worker_ready(live_id=LIVE_ID, generation=1)

        replacement = self.service.worker_ready(live_id=LIVE_ID, generation=2)

        self.assertEqual(replacement.status, LiveStatus.LIVE)
        self.assertEqual(replacement.worker_generation, 2)
        self.assertEqual(replacement.playback_path, first.playback_path)
        self.assertEqual(replacement.version, first.version + 1)


if __name__ == "__main__":
    unittest.main()