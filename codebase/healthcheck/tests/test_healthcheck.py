import unittest

import httpx
from docker.errors import DockerException
from fastapi.testclient import TestClient

from healthcheck_service import HealthMonitor, HttpOrchestratorProbe, MonitorOutcome
from healthcheck_service.controller import DockerOrchestratorController
from healthcheck_service.http import create_app


class Probe:
    def __init__(self, values):
        self.values = iter(values)

    def is_healthy(self):
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return value


class Controller:
    def __init__(self):
        self.restart_count = 0
        self.error = None

    def restart(self):
        if self.error:
            raise self.error
        self.restart_count += 1


class FakeContainer:
    def __init__(self, labels):
        self.labels = labels
        self.restart_timeouts = []

    def restart(self, *, timeout):
        self.restart_timeouts.append(timeout)


class FakeContainers:
    def __init__(self, container):
        self.container = container

    def get(self, _name):
        return self.container


class FakeDockerClient:
    def __init__(self, container):
        self.containers = FakeContainers(container)


class HealthMonitorTests(unittest.TestCase):
    def test_restart_occurs_only_after_consecutive_failure_threshold(self) -> None:
        controller = Controller()
        monitor = HealthMonitor(
            Probe([False, False, False]), controller, failure_threshold=3
        )

        outcomes = [monitor.check_once(), monitor.check_once(), monitor.check_once()]

        self.assertEqual(
            outcomes,
            [MonitorOutcome.DEGRADED, MonitorOutcome.DEGRADED, MonitorOutcome.RESTARTED],
        )
        self.assertEqual(controller.restart_count, 1)

    def test_success_resets_failures_and_cooldown(self) -> None:
        controller = Controller()
        monitor = HealthMonitor(
            Probe([False, False, True]),
            controller,
            failure_threshold=2,
            cooldown_checks=2,
        )

        self.assertEqual(monitor.check_once(), MonitorOutcome.DEGRADED)
        self.assertEqual(monitor.check_once(), MonitorOutcome.RESTARTED)
        self.assertEqual(monitor.check_once(), MonitorOutcome.HEALTHY)

        state = monitor.snapshot()
        self.assertEqual(state.consecutive_failures, 0)
        self.assertEqual(state.cooldown_remaining, 0)

    def test_cooldown_prevents_restart_storm(self) -> None:
        controller = Controller()
        monitor = HealthMonitor(
            Probe([False, False, False, False]),
            controller,
            failure_threshold=1,
            cooldown_checks=2,
        )

        outcomes = [monitor.check_once() for _ in range(4)]

        self.assertEqual(
            outcomes,
            [
                MonitorOutcome.RESTARTED,
                MonitorOutcome.DEGRADED,
                MonitorOutcome.DEGRADED,
                MonitorOutcome.RESTARTED,
            ],
        )
        self.assertEqual(controller.restart_count, 2)

    def test_restart_failure_is_reported_and_rate_limited(self) -> None:
        controller = Controller()
        controller.error = RuntimeError("Docker API denied restart")
        monitor = HealthMonitor(
            Probe([False, False]),
            controller,
            failure_threshold=1,
            cooldown_checks=1,
        )

        self.assertEqual(monitor.check_once(), MonitorOutcome.RESTART_FAILED)
        self.assertEqual(monitor.check_once(), MonitorOutcome.DEGRADED)
        self.assertEqual(
            monitor.snapshot().last_error,
            "Orchestrator is unhealthy during cooldown",
        )


class ProbeAndHttpTests(unittest.TestCase):
    def test_http_probe_maps_status_and_connection_failure(self) -> None:
        healthy_transport = httpx.MockTransport(
            lambda _request: httpx.Response(200)
        )
        with httpx.Client(transport=healthy_transport) as client:
            self.assertTrue(
                HttpOrchestratorProbe("http://orchestrator", client=client).is_healthy()
            )

        def fail(request):
            raise httpx.ConnectError("refused", request=request)

        with httpx.Client(transport=httpx.MockTransport(fail)) as client:
            self.assertFalse(
                HttpOrchestratorProbe("http://orchestrator", client=client).is_healthy()
            )

    def test_monitor_readiness_requires_first_check(self) -> None:
        monitor = HealthMonitor(Probe([True]), Controller())
        client = TestClient(create_app(monitor))

        self.assertEqual(client.get("/health/ready").status_code, 503)
        monitor.check_once()
        response = client.get("/health/ready")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("last_error", response.json())

    def test_monitor_readiness_is_unavailable_while_degraded(self) -> None:
        monitor = HealthMonitor(Probe([False]), Controller())
        client = TestClient(create_app(monitor))

        monitor.check_once()

        self.assertEqual(client.get("/health/ready").status_code, 503)

    def test_default_app_imports_when_docker_daemon_is_unavailable(self) -> None:
        from healthcheck_service.main import build_app

        def unavailable_docker():
            raise DockerException("daemon is stopped")

        client = TestClient(build_app(unavailable_docker))

        self.assertEqual(client.get("/health/live").status_code, 200)


class DockerControllerTests(unittest.TestCase):
    def test_only_labeled_orchestrator_can_be_restarted(self) -> None:
        container = FakeContainer({"streaming.component": "orchestrator"})
        controller = DockerOrchestratorController(
            FakeDockerClient(container), container_name="orchestrator"
        )

        controller.restart()

        self.assertEqual(container.restart_timeouts, [10])

    def test_unmanaged_container_is_rejected(self) -> None:
        container = FakeContainer({"streaming.component": "worker"})
        controller = DockerOrchestratorController(
            FakeDockerClient(container), container_name="orchestrator"
        )

        with self.assertRaises(PermissionError):
            controller.restart()


if __name__ == "__main__":
    unittest.main()