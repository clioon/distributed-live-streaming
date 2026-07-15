import json
import unittest
from uuid import UUID

from fastapi.testclient import TestClient

from orchestrator_service import (
    DeliveryDecision,
    InMemoryOrchestratorStore,
    MessageProcessor,
    OrchestratorProbe,
    OrchestratorService,
    WorkerContainer,
)
from orchestrator_service.http import create_app


LIVE_ID = UUID("70000000-0000-0000-0000-000000000001")
SESSION_ID = UUID("70000000-0000-0000-0000-000000000002")
EVENT_ID = UUID("70000000-0000-0000-0000-000000000003")
CORRELATION_ID = UUID("70000000-0000-0000-0000-000000000004")


def body() -> bytes:
    return json.dumps(
        {
            "id": str(EVENT_ID),
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
    ).encode("utf-8")


class Runtime:
    def __init__(self) -> None:
        self.fail = False
        self.workers = {}

    def list_workers(self, live_id):
        return tuple(self.workers.values())

    def start_worker(self, spec):
        if self.fail:
            raise RuntimeError("runtime unavailable")
        worker = WorkerContainer(spec.container_name, spec.live_id, spec.generation, True)
        self.workers[worker.id] = worker
        return worker

    def stop_worker(self, worker_id):
        self.workers.pop(worker_id, None)


class MessageProcessorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = Runtime()
        orchestrator = OrchestratorService(
            InMemoryOrchestratorStore(), self.runtime
        )
        self.processor = MessageProcessor(orchestrator)

    def test_valid_processed_event_is_acknowledged(self) -> None:
        self.assertEqual(self.processor.process(body()), DeliveryDecision.ACK)

    def test_malformed_or_unsupported_event_is_rejected_without_retry(self) -> None:
        self.assertEqual(self.processor.process(b"not-json"), DeliveryDecision.REJECT)
        payload = json.loads(body())
        payload["type"] = "other.event.v1"
        self.assertEqual(
            self.processor.process(json.dumps(payload)), DeliveryDecision.REJECT
        )

    def test_transient_runtime_failure_is_requeued(self) -> None:
        self.runtime.fail = True

        self.assertEqual(self.processor.process(body()), DeliveryDecision.REQUEUE)


class HealthEndpointTests(unittest.TestCase):
    def test_readiness_requires_running_leader_without_error(self) -> None:
        probe = OrchestratorProbe()
        client = TestClient(create_app(probe))

        self.assertEqual(client.get("/health/live").status_code, 503)
        probe.started()
        self.assertEqual(client.get("/health/live").status_code, 200)
        self.assertEqual(client.get("/health/ready").status_code, 503)
        probe.leadership_changed(leader=True)
        self.assertEqual(client.get("/health/ready").status_code, 200)
        probe.failed(RuntimeError("reconcile failed"))
        self.assertEqual(client.get("/health/ready").status_code, 503)

    def test_default_component_waits_for_runtime_dependencies(self) -> None:
        from orchestrator_service.main import app

        client = TestClient(app)

        self.assertEqual(client.get("/health/live").status_code, 503)
        self.assertEqual(client.get("/health/ready").status_code, 503)


if __name__ == "__main__":
    unittest.main()