import unittest
from unittest.mock import patch
from uuid import UUID

from orchestrator_service import InMemoryOrchestratorStore, OrchestratorService
from orchestrator_service.runtime import PostgresStateLoader


LIVE_ID = UUID("14000000-0000-0000-0000-000000000001")


class Result:
    def fetchall(self):
        return [(LIVE_ID, "running", 7, 4)]


class Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query):
        self.query = query
        return Result()


class Runtime:
    def __init__(self):
        self.started_specs = []

    def list_workers(self, _live_id):
        return ()

    def start_worker(self, spec):
        from orchestrator_service import WorkerContainer

        self.started_specs.append(spec)
        return WorkerContainer(spec.container_name, spec.live_id, spec.generation, True)

    def stop_worker(self, _worker_id):
        pass


class StateLoaderTests(unittest.TestCase):
    def test_restart_restores_generation_and_starts_next_worker_without_event(self):
        store = InMemoryOrchestratorStore()
        connection = Connection()
        loader = PostgresStateLoader("postgresql://unused", store)

        with patch(
            "orchestrator_service.runtime.psycopg.connect",
            return_value=connection,
        ):
            loaded = loader.load()

        runtime = Runtime()
        service = OrchestratorService(store, runtime)
        service.reconcile()

        self.assertEqual(loaded, 1)
        self.assertIn("worker_generation", connection.query)
        self.assertEqual(store.get(LIVE_ID).aggregate_version, 7)
        self.assertEqual(runtime.started_specs[0].generation, 5)


if __name__ == "__main__":
    unittest.main()