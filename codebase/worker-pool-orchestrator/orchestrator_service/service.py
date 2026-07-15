from enum import StrEnum
from threading import RLock
from typing import Protocol
from uuid import UUID

from .events import LifecycleEvent
from .models import DesiredState, LiveRecord, WorkerContainer, WorkerSpec
from .store import InMemoryOrchestratorStore


class WorkerRuntime(Protocol):
    def list_workers(self, live_id: UUID) -> tuple[WorkerContainer, ...]: ...

    def start_worker(self, spec: WorkerSpec) -> WorkerContainer: ...

    def stop_worker(self, worker_id: str) -> None: ...


class HandleResult(StrEnum):
    STARTED = "started"
    STOPPED = "stopped"
    ALREADY_SATISFIED = "already_satisfied"
    ADOPTED = "adopted"
    DUPLICATE = "duplicate"
    STALE = "stale"


class OrchestratorService:
    def __init__(
        self,
        store: InMemoryOrchestratorStore,
        runtime: WorkerRuntime,
        *,
        worker_image: str = "distributed-live-streaming-worker:local",
        ingest_base_url: str = "rtmp://ingest-service:1935/live",
        hls_root: str = "/var/hls",
        api_base_url: str = "http://api-service:8000",
    ) -> None:
        self._store = store
        self._runtime = runtime
        self._worker_image = worker_image
        self._ingest_base_url = ingest_base_url
        self._hls_root = hls_root
        self._api_base_url = api_base_url
        self._operation_lock = RLock()

    def handle(self, event: LifecycleEvent) -> HandleResult:
        with self._operation_lock:
            return self._handle(event)

    def _handle(self, event: LifecycleEvent) -> HandleResult:
        if self._store.is_processed(event.id):
            return HandleResult.DUPLICATE

        desired_state = (
            DesiredState.RUNNING
            if event.type == "live.ingest.started.v1"
            else DesiredState.STOPPED
        )
        record, stale = self._store.apply_desired_state(
            event.live_id, desired_state, event.aggregate_version
        )
        if stale:
            self._store.mark_processed(event.id)
            return HandleResult.STALE

        try:
            result = self._reconcile_record(record)
        except Exception as error:
            self._store.mark_error(event.live_id, error)
            raise
        self._store.mark_processed(event.id)
        return result

    def reconcile(self) -> tuple[HandleResult, ...]:
        with self._operation_lock:
            return tuple(
                self._reconcile_record(record) for record in self._store.records()
            )

    def _reconcile_record(self, record: LiveRecord) -> HandleResult:
        if record.desired_state is DesiredState.STOPPED:
            return self._ensure_stopped(record)
        return self._ensure_running(record)

    def _ensure_running(self, record: LiveRecord) -> HandleResult:
        workers = self._runtime.list_workers(record.live_id)
        healthy = sorted(
            (worker for worker in workers if worker.healthy),
            key=lambda worker: worker.generation,
            reverse=True,
        )
        if healthy and healthy[0].generation >= record.generation:
            selected = healthy[0]
            for worker in workers:
                if worker.id != selected.id:
                    self._runtime.stop_worker(worker.id)
            self._store.mark_worker(record.live_id, selected)
            if record.worker_id == selected.id:
                return HandleResult.ALREADY_SATISFIED
            return HandleResult.ADOPTED

        for worker in workers:
            self._runtime.stop_worker(worker.id)
        next_generation = max(
            [record.generation, *(worker.generation for worker in workers)]
        ) + 1
        spec = self._worker_spec(record.live_id, next_generation)
        worker = self._runtime.start_worker(spec)
        self._store.mark_worker(record.live_id, worker)
        return HandleResult.STARTED

    def _ensure_stopped(self, record: LiveRecord) -> HandleResult:
        workers = self._runtime.list_workers(record.live_id)
        for worker in workers:
            self._runtime.stop_worker(worker.id)
        self._store.mark_stopped(record.live_id)
        if workers or record.worker_id is not None:
            return HandleResult.STOPPED
        return HandleResult.ALREADY_SATISFIED

    def _worker_spec(self, live_id: UUID, generation: int) -> WorkerSpec:
        return WorkerSpec(
            live_id=live_id,
            generation=generation,
            image=self._worker_image,
            container_name=f"worker-{live_id.hex}-g{generation}",
            environment={
                "LIVE_ID": str(live_id),
                "GENERATION": str(generation),
                "INGEST_BASE_URL": self._ingest_base_url,
                "HLS_ROOT": self._hls_root,
                "API_BASE_URL": self._api_base_url,
            },
            labels={
                "streaming.component": "worker",
                "streaming.live_id": str(live_id),
                "streaming.generation": str(generation),
            },
        )