from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping
from uuid import UUID


class DesiredState(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class LiveRecord:
    live_id: UUID
    desired_state: DesiredState
    aggregate_version: int
    generation: int = 0
    worker_id: str | None = None
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class WorkerSpec:
    live_id: UUID
    generation: int
    image: str
    container_name: str
    environment: Mapping[str, str]
    labels: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class WorkerContainer:
    id: str
    live_id: UUID
    generation: int
    healthy: bool