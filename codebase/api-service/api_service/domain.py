import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping
from uuid import UUID


class DesiredState(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"


class LiveStatus(StrEnum):
    CREATED = "created"
    INGESTING = "ingesting"
    PROVISIONING = "provisioning"
    LIVE = "live"
    STOPPING = "stopping"
    ENDED = "ended"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Live:
    id: UUID
    owner_id: UUID
    title: str
    description: str
    desired_state: DesiredState
    status: LiveStatus
    stream_secret_hash: str
    version: int
    created_at: datetime
    updated_at: datetime
    current_ingest_session_id: UUID | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    failure_reason: str | None = None
    worker_generation: int = 0
    playback_path: str | None = None
    playback_ready_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DomainEvent:
    id: UUID
    type: str
    source: str
    subject: str
    occurred_at: datetime
    correlation_id: UUID
    aggregate_version: int
    data: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "type": self.type,
            "source": self.source,
            "subject": self.subject,
            "occurred_at": self.occurred_at.isoformat(),
            "correlation_id": str(self.correlation_id),
            "aggregate_version": self.aggregate_version,
            "data": dict(self.data),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), separators=(",", ":"), sort_keys=True)