import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker

from chat_service.models import ChatMessage


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = (
    PROJECT_ROOT
    / "docs"
    / "contracts"
    / "chat"
    / "chat.message.created.v1.schema.json"
)


class ChatMessageContractTests(unittest.TestCase):
    def test_created_message_matches_shared_schema(self) -> None:
        message = ChatMessage(
            message_id=UUID("d0000000-0000-0000-0000-000000000001"),
            live_id=UUID("d0000000-0000-0000-0000-000000000002"),
            user_id=UUID("d0000000-0000-0000-0000-000000000003"),
            display_name="Alice",
            client_message_id=UUID("d0000000-0000-0000-0000-000000000004"),
            sequence=1,
            sent_at=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
            text="Hello",
        )
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).validate(message.as_payload())


if __name__ == "__main__":
    unittest.main()