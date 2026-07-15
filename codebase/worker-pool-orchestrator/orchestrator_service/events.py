import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID


SUPPORTED_EVENTS = {
    "live.ingest.started.v1",
    "live.ingest.stopped.v1",
}
FORBIDDEN_FIELD_FRAGMENTS = {"secret", "token", "password"}
MAX_EVENT_BYTES = 16_384
EVENT_FIELDS = {
    "id",
    "type",
    "source",
    "subject",
    "occurred_at",
    "correlation_id",
    "aggregate_version",
    "data",
}


class UnsupportedLifecycleEvent(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    id: UUID
    type: str
    source: str
    subject: str
    occurred_at: datetime
    correlation_id: UUID
    aggregate_version: int
    live_id: UUID
    ingest_session_id: UUID
    reason: str | None = None

    @classmethod
    def from_json(cls, body: bytes | str) -> "LifecycleEvent":
        try:
            encoded_body = body.encode("utf-8") if isinstance(body, str) else body
            if len(encoded_body) > MAX_EVENT_BYTES:
                raise ValueError
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError
            if set(payload) != EVENT_FIELDS:
                raise ValueError
            cls._reject_forbidden_fields(payload)
            event_type = str(payload["type"])
            if event_type not in SUPPORTED_EVENTS:
                raise UnsupportedLifecycleEvent(
                    f"Unsupported lifecycle event: {event_type}"
                )
            data = payload["data"]
            if not isinstance(data, dict):
                raise ValueError
            expected_data_fields = {
                "live_id",
                "ingest_session_id",
                "aggregate_version",
            }
            if event_type == "live.ingest.stopped.v1":
                expected_data_fields.add("reason")
            if set(data) != expected_data_fields:
                raise ValueError
            aggregate_version = int(payload["aggregate_version"])
            if aggregate_version < 1:
                raise ValueError
            if int(data["aggregate_version"]) != aggregate_version:
                raise ValueError
            occurred_at = datetime.fromisoformat(
                str(payload["occurred_at"]).replace("Z", "+00:00")
            )
            if occurred_at.tzinfo is None:
                raise ValueError
            live_id = UUID(str(data["live_id"]))
            source = str(payload["source"])
            subject = str(payload["subject"])
            if source != "api-service" or subject != f"live/{live_id}":
                raise ValueError
            reason = str(data["reason"]) if "reason" in data else None
            if reason is not None and not 1 <= len(reason) <= 200:
                raise ValueError
            return cls(
                id=UUID(str(payload["id"])),
                type=event_type,
                source=source,
                subject=subject,
                occurred_at=occurred_at,
                correlation_id=UUID(str(payload["correlation_id"])),
                aggregate_version=aggregate_version,
                live_id=live_id,
                ingest_session_id=UUID(str(data["ingest_session_id"])),
                reason=reason,
            )
        except UnsupportedLifecycleEvent:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("Invalid lifecycle event envelope") from error

    @classmethod
    def _reject_forbidden_fields(cls, value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                normalized_key = str(key).lower()
                if any(fragment in normalized_key for fragment in FORBIDDEN_FIELD_FRAGMENTS):
                    raise ValueError("Lifecycle events cannot contain credentials")
                cls._reject_forbidden_fields(nested)
        elif isinstance(value, list):
            for nested in value:
                cls._reject_forbidden_fields(nested)