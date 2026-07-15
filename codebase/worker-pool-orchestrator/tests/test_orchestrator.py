import json
from threading import Event, Lock, Thread
import unittest
from datetime import datetime, timezone
from uuid import UUID

from orchestrator_service import (
    HandleResult,
    InMemoryOrchestratorStore,
    LifecycleEvent,
    OrchestratorService,
    WorkerContainer,
)


LIVE_ID = UUID("60000000-0000-0000-0000-000000000001")
SESSION_ID = UUID("60000000-0000-0000-0000-000000000002")
START_EVENT_ID = UUID("60000000-0000-0000-0000-000000000003")
STOP_EVENT_ID = UUID("60000000-0000-0000-0000-000000000004")
CORRELATION_ID = UUID("60000000-0000-0000-0000-000000000005")
NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


def event(
    event_type: str = "live.ingest.started.v1",
    *,
    event_id: UUID = START_EVENT_ID,
    version: int = 2,
) -> LifecycleEvent:
    return LifecycleEvent(
        id=event_id,
        type=event_type,
        source="api-service",
        subject=f"live/{LIVE_ID}",
        occurred_at=NOW,
        correlation_id=CORRELATION_ID,
        aggregate_version=version,
        live_id=LIVE_ID,
        ingest_session_id=SESSION_ID,
        reason="publisher_disconnected" if "stopped" in event_type else None,
    )


class FakeRuntime:
    def __init__(self) -> None:
        self.workers = {}
        self.started_specs = []
        self.stopped_ids = []
        self.fail_next_start = False

    def list_workers(self, live_id):
        return tuple(
            worker for worker in self.workers.values() if worker.live_id == live_id
        )

    def start_worker(self, spec):
        if self.fail_next_start:
            self.fail_next_start = False
            raise RuntimeError("Docker temporarily unavailable")
        self.started_specs.append(spec)
        worker = WorkerContainer(
            id=spec.container_name,
            live_id=spec.live_id,
            generation=spec.generation,
            healthy=True,
        )
        self.workers[worker.id] = worker
        return worker

    def stop_worker(self, worker_id):
        self.stopped_ids.append(worker_id)
        self.workers.pop(worker_id, None)


class BlockingRuntime(FakeRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.first_entered = Event()
        self.release_first = Event()
        self.second_entered = Event()
        self._call_lock = Lock()
        self._list_calls = 0

    def list_workers(self, live_id):
        with self._call_lock:
            self._list_calls += 1
            call_number = self._list_calls
        if call_number == 1:
            self.first_entered.set()
            self.release_first.wait(timeout=2)
        else:
            self.second_entered.set()
        return super().list_workers(live_id)


class EventContractTests(unittest.TestCase):
    def payload(self):
        return {
            "id": str(START_EVENT_ID),
            "type": "live.ingest.started.v1",
            "source": "api-service",
            "subject": f"live/{LIVE_ID}",
            "occurred_at": "2026-07-13T12:00:00Z",
            "correlation_id": str(CORRELATION_ID),
            "aggregate_version": 2,
            "data": {
                "live_id": str(LIVE_ID),
                "ingest_session_id": str(SESSION_ID),
                "aggregate_version": 2,
            },
        }

    def test_valid_json_event_is_parsed(self) -> None:
        parsed = LifecycleEvent.from_json(json.dumps(self.payload()))

        self.assertEqual(parsed.live_id, LIVE_ID)
        self.assertEqual(parsed.aggregate_version, 2)

    def test_event_with_credentials_is_rejected(self) -> None:
        payload = self.payload()
        payload["data"]["stream_secret"] = "must-not-leak"

        with self.assertRaises(ValueError):
            LifecycleEvent.from_json(json.dumps(payload))

    def test_mismatched_aggregate_versions_are_rejected(self) -> None:
        payload = self.payload()
        payload["data"]["aggregate_version"] = 99

        with self.assertRaises(ValueError):
            LifecycleEvent.from_json(json.dumps(payload))

    def test_source_subject_version_and_extra_fields_are_strict(self) -> None:
        mutations = [
            ("source", "other-service"),
            ("subject", "live/00000000-0000-0000-0000-000000000000"),
            ("aggregate_version", 0),
            ("unexpected", "value"),
        ]
        for field, value in mutations:
            with self.subTest(field=field):
                payload = self.payload()
                payload[field] = value
                if field == "aggregate_version":
                    payload["data"]["aggregate_version"] = value
                with self.assertRaises(ValueError):
                    LifecycleEvent.from_json(json.dumps(payload))

    def test_oversized_event_is_rejected(self) -> None:
        payload = self.payload()
        payload["unexpected"] = "x" * 20_000

        with self.assertRaises(ValueError):
            LifecycleEvent.from_json(json.dumps(payload))


class OrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryOrchestratorStore()
        self.runtime = FakeRuntime()
        self.service = OrchestratorService(self.store, self.runtime)

    def test_start_event_creates_exactly_one_worker(self) -> None:
        result = self.service.handle(event())

        self.assertEqual(result, HandleResult.STARTED)
        self.assertEqual(len(self.runtime.started_specs), 1)
        spec = self.runtime.started_specs[0]
        self.assertEqual(spec.generation, 1)
        self.assertEqual(spec.environment["LIVE_ID"], str(LIVE_ID))
        self.assertEqual(self.store.get(LIVE_ID).worker_id, spec.container_name)

    def test_duplicate_delivery_does_not_create_another_worker(self) -> None:
        self.service.handle(event())

        result = self.service.handle(event())

        self.assertEqual(result, HandleResult.DUPLICATE)
        self.assertEqual(len(self.runtime.started_specs), 1)

    def test_stop_event_stops_all_live_workers(self) -> None:
        self.service.handle(event())

        result = self.service.handle(
            event(
                "live.ingest.stopped.v1",
                event_id=STOP_EVENT_ID,
                version=3,
            )
        )

        self.assertEqual(result, HandleResult.STOPPED)
        self.assertEqual(self.runtime.workers, {})
        self.assertIsNone(self.store.get(LIVE_ID).worker_id)

    def test_out_of_order_start_cannot_revive_stopped_live(self) -> None:
        self.service.handle(
            event(
                "live.ingest.stopped.v1",
                event_id=STOP_EVENT_ID,
                version=3,
            )
        )

        result = self.service.handle(event(version=2))

        self.assertEqual(result, HandleResult.STALE)
        self.assertEqual(self.runtime.workers, {})

    def test_reconcile_respawns_missing_worker_with_new_generation(self) -> None:
        self.service.handle(event())
        first_worker_id = self.store.get(LIVE_ID).worker_id
        self.runtime.workers.clear()

        results = self.service.reconcile()

        self.assertEqual(results, (HandleResult.STARTED,))
        self.assertNotEqual(self.store.get(LIVE_ID).worker_id, first_worker_id)
        self.assertEqual(self.store.get(LIVE_ID).generation, 2)

    def test_existing_newer_worker_is_adopted_and_stale_worker_stopped(self) -> None:
        self.service.handle(event())
        stale_id = self.store.get(LIVE_ID).worker_id
        newer = WorkerContainer("external-g2", LIVE_ID, 2, True)
        self.runtime.workers[newer.id] = newer

        result = self.service.reconcile()[0]

        self.assertEqual(result, HandleResult.ADOPTED)
        self.assertIn(stale_id, self.runtime.stopped_ids)
        self.assertEqual(self.store.get(LIVE_ID).worker_id, newer.id)

    def test_failed_start_is_retried_on_message_redelivery(self) -> None:
        self.runtime.fail_next_start = True
        with self.assertRaises(RuntimeError):
            self.service.handle(event())

        result = self.service.handle(event())

        self.assertEqual(result, HandleResult.STARTED)
        self.assertEqual(len(self.runtime.started_specs), 1)
        self.assertIsNone(self.store.get(LIVE_ID).last_error)

    def test_duplicate_delivery_cannot_race_reconciliation(self) -> None:
        runtime = BlockingRuntime()
        service = OrchestratorService(InMemoryOrchestratorStore(), runtime)
        failures = []

        def handle_event():
            try:
                service.handle(event())
            except Exception as error:
                failures.append(error)

        first = Thread(target=handle_event)
        second = Thread(target=handle_event)
        first.start()
        self.assertTrue(runtime.first_entered.wait(timeout=1))
        second.start()

        self.assertFalse(runtime.second_entered.wait(timeout=0.1))
        runtime.release_first.set()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertEqual(failures, [])
        self.assertEqual(len(runtime.started_specs), 1)


if __name__ == "__main__":
    unittest.main()