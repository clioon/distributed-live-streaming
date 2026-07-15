import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker

from api_service import DomainEvent


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = PROJECT_ROOT / "docs" / "contracts" / "events"
LIVE_ID = UUID("c0000000-0000-0000-0000-000000000001")
SESSION_ID = UUID("c0000000-0000-0000-0000-000000000002")
EVENT_ID = UUID("c0000000-0000-0000-0000-000000000003")
CORRELATION_ID = UUID("c0000000-0000-0000-0000-000000000004")
NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


class EventContractTests(unittest.TestCase):
    def validate(self, event: DomainEvent, schema_name: str) -> dict:
        schema = json.loads((CONTRACTS / schema_name).read_text(encoding="utf-8"))
        payload = json.loads(event.to_json())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
        return payload

    def test_started_event_matches_shared_schema_without_credentials(self) -> None:
        event = DomainEvent(
            id=EVENT_ID,
            type="live.ingest.started.v1",
            source="api-service",
            subject=f"live/{LIVE_ID}",
            occurred_at=NOW,
            correlation_id=CORRELATION_ID,
            aggregate_version=2,
            data={
                "live_id": str(LIVE_ID),
                "ingest_session_id": str(SESSION_ID),
                "aggregate_version": 2,
            },
        )

        payload = self.validate(event, "live.ingest.started.v1.schema.json")

        self.assertNotIn("secret", json.dumps(payload).lower())
        self.assertNotIn("token", json.dumps(payload).lower())

    def test_stopped_event_matches_shared_schema(self) -> None:
        event = DomainEvent(
            id=EVENT_ID,
            type="live.ingest.stopped.v1",
            source="api-service",
            subject=f"live/{LIVE_ID}",
            occurred_at=NOW,
            correlation_id=CORRELATION_ID,
            aggregate_version=3,
            data={
                "live_id": str(LIVE_ID),
                "ingest_session_id": str(SESSION_ID),
                "aggregate_version": 3,
                "reason": "publisher_disconnected",
            },
        )

        self.validate(event, "live.ingest.stopped.v1.schema.json")


if __name__ == "__main__":
    unittest.main()