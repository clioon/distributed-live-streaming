import json
import unittest
from pathlib import Path


COMPONENT_ROOT = Path(__file__).resolve().parents[1]


class RabbitTopologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.definition = json.loads(
            (COMPONENT_ROOT / "definitions.json").read_text(encoding="utf-8")
        )

    def queue(self, name):
        return next(item for item in self.definition["queues"] if item["name"] == name)

    def test_topology_has_local_user_with_streaming_vhost_permissions(self) -> None:
        self.assertEqual(self.definition["users"][0]["name"], "guest")
        self.assertTrue(self.definition["users"][0]["password_hash"])
        self.assertNotIn("password", self.definition["users"][0])
        self.assertEqual(
            self.definition["permissions"],
            [
                {
                    "user": "guest",
                    "vhost": "/streaming",
                    "configure": ".*",
                    "write": ".*",
                    "read": ".*",
                }
            ],
        )
        serialized = json.dumps(self.definition).lower()
        self.assertNotIn('"password":', serialized)

    def test_lifecycle_queue_is_durable_quorum_with_dead_letter_exchange(self) -> None:
        queue = self.queue("orchestrator.live-lifecycle.v1")

        self.assertTrue(queue["durable"])
        self.assertFalse(queue["auto_delete"])
        self.assertEqual(queue["arguments"]["x-queue-type"], "quorum")
        self.assertEqual(
            queue["arguments"]["x-dead-letter-exchange"], "streaming.events.dlx"
        )

    def test_retry_queue_returns_messages_after_five_seconds(self) -> None:
        queue = self.queue("orchestrator.live-lifecycle.retry.5s.v1")

        self.assertEqual(queue["arguments"]["x-message-ttl"], 5000)
        self.assertEqual(
            queue["arguments"]["x-dead-letter-exchange"], "streaming.events"
        )
        self.assertEqual(
            queue["arguments"]["x-dead-letter-routing-key"],
            "live.ingest.retry.v1",
        )

    def test_event_and_dead_letter_bindings_are_explicit(self) -> None:
        bindings = {
            (item["source"], item["destination"]): item["routing_key"]
            for item in self.definition["bindings"]
        }

        self.assertEqual(
            bindings[("streaming.events", "orchestrator.live-lifecycle.v1")],
            "live.ingest.*.v1",
        )
        self.assertEqual(
            bindings[("streaming.events.dlx", "orchestrator.live-lifecycle.dlq.v1")],
            "#",
        )

    def test_all_declared_exchanges_are_durable(self) -> None:
        self.assertTrue(all(item["durable"] for item in self.definition["exchanges"]))

    def test_broker_uses_local_development_ports(self) -> None:
        config = (COMPONENT_ROOT / "rabbitmq.conf").read_text(encoding="utf-8")

        self.assertIn("listeners.tcp.default = 5672", config)
        self.assertIn("management.tcp.port = 15672", config)
        self.assertIn("default_user = guest", config)
        self.assertNotIn("ssl_options", config)


if __name__ == "__main__":
    unittest.main()