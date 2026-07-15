import json
import unittest
from datetime import datetime, timezone
from uuid import UUID

from chat_service.models import MessageDraft
from chat_service.redis_broker import RedisChatBroker


LIVE_ID = UUID("13000000-0000-0000-0000-000000000001")
USER_ID = UUID("13000000-0000-0000-0000-000000000002")
CLIENT_ID = UUID("13000000-0000-0000-0000-000000000003")
MESSAGE_ID = UUID("13000000-0000-0000-0000-000000000004")
NOW = datetime(2026, 7, 15, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self) -> None:
        self.calls = []

    def register_script(self, _script):
        def invoke(*, keys, args):
            self.calls.append((keys, args))
            payload = json.loads(args[1])
            payload["sequence"] = 7
            return [1, json.dumps(payload).encode()]

        return invoke

    def ping(self):
        return True


class RedisBrokerTests(unittest.TestCase):
    def test_publish_uses_live_sequence_dedupe_and_channel(self) -> None:
        client = FakeClient()
        broker = RedisChatBroker(
            "redis://unused",
            client=client,
            clock=lambda: NOW,
            id_factory=lambda: MESSAGE_ID,
        )

        result = broker.publish_once(
            MessageDraft(LIVE_ID, USER_ID, "Alice", CLIENT_ID, "Hello")
        )

        keys, args = client.calls[0]
        self.assertEqual(keys[0], f"chat:live:{LIVE_ID}:sequence")
        self.assertIn(str(CLIENT_ID), keys[1])
        self.assertEqual(args[0], f"chat.live.{LIVE_ID}.v1")
        self.assertEqual(result.message.sequence, 7)
        self.assertTrue(result.created)
        self.assertTrue(broker.is_ready())


if __name__ == "__main__":
    unittest.main()