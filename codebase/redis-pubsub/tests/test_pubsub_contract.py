import json
import unittest
from pathlib import Path
from uuid import UUID

from redis_middleware import build_publish_invocation, decode_result


COMPONENT_ROOT = Path(__file__).resolve().parents[1]
LIVE_ID = UUID("a0000000-0000-0000-0000-000000000001")
USER_ID = UUID("a0000000-0000-0000-0000-000000000002")
CLIENT_MESSAGE_ID = UUID("a0000000-0000-0000-0000-000000000003")


class RedisContractTests(unittest.TestCase):
    def test_invocation_uses_live_scoped_sequence_channel_and_dedupe_key(self) -> None:
        invocation = build_publish_invocation(
            live_id=LIVE_ID,
            user_id=USER_ID,
            client_message_id=CLIENT_MESSAGE_ID,
            message={"type": "chat.message.created", "text": "Hello"},
        )

        self.assertEqual(invocation.sequence_key, f"chat:live:{LIVE_ID}:sequence")
        self.assertEqual(invocation.channel, f"chat.live.{LIVE_ID}.v1")
        self.assertEqual(
            invocation.deduplication_key,
            f"chat:live:{LIVE_ID}:dedupe:{USER_ID}:{CLIENT_MESSAGE_ID}",
        )
        self.assertNotIn("sequence", json.loads(invocation.encoded_message))
        self.assertEqual(invocation.redis_arguments()[0], 2)

    def test_callers_cannot_preassign_sequence(self) -> None:
        with self.assertRaises(ValueError):
            build_publish_invocation(
                live_id=LIVE_ID,
                user_id=USER_ID,
                client_message_id=CLIENT_MESSAGE_ID,
                message={"sequence": 99},
            )

    def test_script_result_decodes_created_and_duplicate_messages(self) -> None:
        encoded = b'{"sequence":7,"text":"Hello"}'

        self.assertEqual(decode_result([1, encoded]), (True, {"sequence": 7, "text": "Hello"}))
        self.assertEqual(decode_result([0, encoded]), (False, {"sequence": 7, "text": "Hello"}))

    def test_lua_script_orders_deduplication_sequence_storage_and_publish(self) -> None:
        script = (COMPONENT_ROOT / "scripts" / "publish_chat.lua").read_text(
            encoding="utf-8"
        )

        operations = [
            script.index('redis.call("GET"'),
            script.index('redis.call("INCR"'),
            script.index('redis.call("SET"'),
            script.index('redis.call("PUBLISH"'),
        ]
        self.assertEqual(operations, sorted(operations))

    def test_redis_configuration_preserves_sequence_and_dedupe_data(self) -> None:
        config = (COMPONENT_ROOT / "redis.conf").read_text(encoding="utf-8")

        self.assertIn("appendonly yes", config)
        self.assertIn("appendfsync everysec", config)
        self.assertIn("maxmemory-policy noeviction", config)
        self.assertIn("protected-mode no", config)
        self.assertIn("maxmemory 512mb", config)

    def test_redis_uses_plain_local_port_without_credentials(self) -> None:
        config = (COMPONENT_ROOT / "redis.conf").read_text(encoding="utf-8")

        self.assertIn("port 6379", config)
        self.assertNotIn("tls-port", config)
        self.assertNotIn("aclfile", config)


if __name__ == "__main__":
    unittest.main()