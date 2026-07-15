import unittest
from types import SimpleNamespace
from uuid import UUID

from orchestrator_service import DeliveryDecision, WorkerSpec
from orchestrator_service.consumer import RabbitLifecycleConsumer
from orchestrator_service.docker_runtime import DockerWorkerRuntime
from orchestrator_service.health import OrchestratorProbe


LIVE_ID = UUID("12000000-0000-0000-0000-000000000001")


class Containers:
    def __init__(self) -> None:
        self.run_kwargs = None

    def list(self, **_kwargs):
        return []

    def run(self, image, **kwargs):
        self.run_kwargs = {"image": image, **kwargs}
        return SimpleNamespace(id="container-id")


class Client:
    def __init__(self) -> None:
        self.containers = Containers()


class Processor:
    def __init__(self, decision):
        self.decision = decision

    def process(self, _body):
        return self.decision


class Channel:
    def __init__(self) -> None:
        self.actions = []

    def basic_ack(self, **kwargs):
        self.actions.append(("ack", kwargs))

    def basic_nack(self, **kwargs):
        self.actions.append(("nack", kwargs))


class AdapterTests(unittest.TestCase):
    def test_docker_runtime_mounts_shared_hls_volume_and_network(self) -> None:
        client = Client()
        runtime = DockerWorkerRuntime(
            client,
            network_name="streaming-network",
            hls_volume_name="hls-data",
        )
        spec = WorkerSpec(
            live_id=LIVE_ID,
            generation=1,
            image="worker:local",
            container_name="worker-live-g1",
            environment={"LIVE_ID": str(LIVE_ID)},
            labels={"streaming.component": "worker"},
        )

        worker = runtime.start_worker(spec)

        self.assertEqual(worker.id, "container-id")
        self.assertEqual(client.containers.run_kwargs["network"], "streaming-network")
        self.assertEqual(
            client.containers.run_kwargs["volumes"],
            {"hls-data": {"bind": "/var/hls", "mode": "rw"}},
        )

    def test_consumer_maps_processing_decisions_to_acknowledgements(self) -> None:
        expected = {
            DeliveryDecision.ACK: ("ack", {"delivery_tag": 7}),
            DeliveryDecision.REQUEUE: (
                "nack",
                {"delivery_tag": 7, "requeue": True},
            ),
            DeliveryDecision.REJECT: (
                "nack",
                {"delivery_tag": 7, "requeue": False},
            ),
        }
        for decision, action in expected.items():
            with self.subTest(decision=decision):
                channel = Channel()
                consumer = RabbitLifecycleConsumer(
                    "amqp://guest:guest@localhost/%2Fstreaming",
                    Processor(decision),
                    OrchestratorProbe(),
                )
                consumer.handle_delivery(
                    channel,
                    SimpleNamespace(delivery_tag=7),
                    b"{}",
                )
                self.assertEqual(channel.actions, [action])


if __name__ == "__main__":
    unittest.main()