import logging
from threading import Event, Thread

import psycopg

from .models import DesiredState
from .service import OrchestratorService
from .store import InMemoryOrchestratorStore


LOGGER = logging.getLogger(__name__)


class PostgresStateLoader:
    def __init__(self, dsn: str, store: InMemoryOrchestratorStore) -> None:
        self._dsn = dsn
        self._store = store

    def load(self) -> int:
        with psycopg.connect(self._dsn) as connection:
            rows = connection.execute(
                """
                SELECT id, desired_state::text, version, worker_generation
                FROM lives
                WHERE status IN ('ingesting', 'provisioning', 'live', 'stopping')
                ORDER BY created_at
                """
            ).fetchall()
        for live_id, desired_state, version, worker_generation in rows:
            self._store.restore(
                live_id,
                DesiredState(desired_state),
                int(version),
                int(worker_generation),
            )
        return len(rows)


class OrchestratorRuntime:
    def __init__(
        self,
        service: OrchestratorService,
        consumer,
        *,
        state_loader: PostgresStateLoader | None = None,
        reconcile_seconds: float = 5.0,
    ) -> None:
        self._service = service
        self._consumer = consumer
        self._state_loader = state_loader
        self._reconcile_seconds = reconcile_seconds
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._state_loader is not None:
            try:
                self._state_loader.load()
            except Exception:
                LOGGER.exception("Could not restore orchestrator state")
        self._consumer.start()
        self._stop.clear()
        self._thread = Thread(target=self._reconcile, name="reconciler", daemon=True)
        self._thread.start()

    def _reconcile(self) -> None:
        while not self._stop.is_set():
            try:
                self._service.reconcile()
            except Exception:
                LOGGER.exception("Worker reconciliation failed")
            self._stop.wait(self._reconcile_seconds)

    def stop(self) -> None:
        self._stop.set()
        self._consumer.stop()
        if self._thread is not None:
            self._thread.join(timeout=max(3.0, self._reconcile_seconds * 2))