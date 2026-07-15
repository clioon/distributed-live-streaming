from dataclasses import replace
from threading import Lock
from uuid import UUID

from .models import DesiredState, LiveRecord, WorkerContainer


class ConflictingAggregateVersion(ValueError):
    pass


class InMemoryOrchestratorStore:
    def __init__(self) -> None:
        self._records: dict[UUID, LiveRecord] = {}
        self._processed_events: set[UUID] = set()
        self._lock = Lock()

    def is_processed(self, event_id: UUID) -> bool:
        with self._lock:
            return event_id in self._processed_events

    def mark_processed(self, event_id: UUID) -> None:
        with self._lock:
            self._processed_events.add(event_id)

    def restore(
        self,
        live_id: UUID,
        desired_state: DesiredState,
        aggregate_version: int,
        generation: int,
    ) -> LiveRecord:
        if aggregate_version < 1:
            raise ValueError("Aggregate version must be greater than zero")
        if generation < 0:
            raise ValueError("Worker generation cannot be negative")
        with self._lock:
            current = self._records.get(live_id)
            if current is not None and current.aggregate_version > aggregate_version:
                return current
            record = LiveRecord(
                live_id=live_id,
                desired_state=desired_state,
                aggregate_version=aggregate_version,
                generation=max(generation, current.generation if current else 0),
            )
            self._records[live_id] = record
            return record

    def apply_desired_state(
        self,
        live_id: UUID,
        desired_state: DesiredState,
        aggregate_version: int,
    ) -> tuple[LiveRecord, bool]:
        with self._lock:
            current = self._records.get(live_id)
            if current is None:
                record = LiveRecord(
                    live_id=live_id,
                    desired_state=desired_state,
                    aggregate_version=aggregate_version,
                )
                self._records[live_id] = record
                return record, False
            if aggregate_version < current.aggregate_version:
                return current, True
            if (
                aggregate_version == current.aggregate_version
                and desired_state is not current.desired_state
            ):
                raise ConflictingAggregateVersion(
                    "One aggregate version cannot represent two desired states"
                )
            record = replace(
                current,
                desired_state=desired_state,
                aggregate_version=aggregate_version,
            )
            self._records[live_id] = record
            return record, False

    def mark_worker(self, live_id: UUID, worker: WorkerContainer) -> LiveRecord:
        with self._lock:
            current = self._records[live_id]
            updated = replace(
                current,
                generation=worker.generation,
                worker_id=worker.id,
                last_error=None,
            )
            self._records[live_id] = updated
            return updated

    def mark_stopped(self, live_id: UUID) -> LiveRecord:
        with self._lock:
            current = self._records[live_id]
            updated = replace(current, worker_id=None, last_error=None)
            self._records[live_id] = updated
            return updated

    def mark_error(self, live_id: UUID, error: Exception) -> LiveRecord:
        with self._lock:
            current = self._records[live_id]
            updated = replace(current, last_error=str(error))
            self._records[live_id] = updated
            return updated

    def get(self, live_id: UUID) -> LiveRecord:
        with self._lock:
            return self._records[live_id]

    def records(self) -> tuple[LiveRecord, ...]:
        with self._lock:
            return tuple(sorted(self._records.values(), key=lambda item: item.live_id))