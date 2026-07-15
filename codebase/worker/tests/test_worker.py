import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

from worker_service import HlsWorkspace, WorkerConfig, WorkerSupervisor
from worker_service.http import create_app


LIVE_ID = UUID("50000000-0000-0000-0000-000000000001")


class FakeProcess:
    def __init__(self, *, timeout_on_wait: bool = False) -> None:
        self.return_code = None
        self.timeout_on_wait = timeout_on_wait
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.return_code

    def terminate(self) -> None:
        self.terminated = True
        if not self.timeout_on_wait:
            self.return_code = 0

    def wait(self, timeout=None) -> int:
        if self.timeout_on_wait and not self.killed:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        self.return_code = -9 if self.killed else 0
        return self.return_code

    def kill(self) -> None:
        self.killed = True
        self.return_code = -9


class FakeRunner:
    def __init__(self, process: FakeProcess | None = None) -> None:
        self.process = process or FakeProcess()
        self.commands = []

    def start(self, command):
        self.commands.append(tuple(command))
        return self.process


class RecordingNotifier:
    def __init__(self) -> None:
        self.ready = []

    def notify_ready(self, live_id, generation):
        self.ready.append((live_id, generation))


class WorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.config = WorkerConfig(
            live_id=LIVE_ID,
            generation=3,
            ingest_base_url="rtmp://ingest-service:1935/live",
            hls_root=self.root,
        )
        self.workspace = HlsWorkspace(self.root)
        self.runner = FakeRunner()
        self.supervisor = WorkerSupervisor(
            self.config, self.workspace, self.runner
        )

    def test_configuration_rejects_invalid_generation_and_protocol(self) -> None:
        with self.assertRaises(ValueError):
            WorkerConfig(
                live_id=LIVE_ID,
                generation=0,
                ingest_base_url="rtmp://ingest/live",
                hls_root=self.root,
            )
        with self.assertRaises(ValueError):
            WorkerConfig(
                live_id=LIVE_ID,
                generation=1,
                ingest_base_url="http://ingest/live",
                hls_root=self.root,
            )

    def test_start_builds_true_transcoding_command_and_is_idempotent(self) -> None:
        self.supervisor.start()
        self.supervisor.start()

        self.assertEqual(len(self.runner.commands), 1)
        command = self.runner.commands[0]
        self.assertEqual(command[0], "ffmpeg")
        self.assertIn("libx264", command)
        self.assertIn("aac", command)
        self.assertIn(f"rtmp://ingest-service:1935/live/{LIVE_ID}", command)
        self.assertEqual(Path(command[-1]), self.workspace.manifest(LIVE_ID, 3))

    def test_readiness_requires_running_process_and_nonempty_manifest(self) -> None:
        self.supervisor.start()
        self.assertFalse(self.supervisor.health().manifest_ready)

        manifest = self.workspace.manifest(LIVE_ID, 3)
        manifest.write_text("#EXTM3U", encoding="ascii")

        self.assertTrue(self.supervisor.health().process_running)
        self.assertTrue(self.supervisor.health().manifest_ready)

    def test_process_exit_makes_worker_unhealthy(self) -> None:
        self.supervisor.start()
        self.runner.process.return_code = 1

        health = self.supervisor.health()

        self.assertFalse(health.process_running)
        self.assertFalse(health.manifest_ready)

    def test_ready_manifest_is_activated_and_notified_once(self) -> None:
        notifier = RecordingNotifier()
        supervisor = WorkerSupervisor(
            self.config,
            self.workspace,
            self.runner,
            notifier=notifier,
        )
        supervisor.start()
        self.workspace.manifest(LIVE_ID, 3).write_text("#EXTM3U", encoding="ascii")

        with patch.object(self.workspace, "activate") as activate:
            first = supervisor.health()
            second = supervisor.health()

        self.assertTrue(first.manifest_ready)
        self.assertTrue(second.manifest_ready)
        activate.assert_called_once_with(LIVE_ID, 3)
        self.assertEqual(notifier.ready, [(LIVE_ID, 3)])

    def test_stop_kills_process_after_graceful_timeout(self) -> None:
        process = FakeProcess(timeout_on_wait=True)
        supervisor = WorkerSupervisor(
            self.config, self.workspace, FakeRunner(process)
        )
        supervisor.start()

        supervisor.stop(timeout_seconds=0.01)

        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertFalse(supervisor.health().process_running)

    def test_preparing_generation_keeps_other_generations(self) -> None:
        previous = self.workspace.prepare(LIVE_ID, 2)
        (previous / "index.m3u8").write_text("old", encoding="ascii")

        current = self.workspace.prepare(LIVE_ID, 3)

        self.assertTrue(previous.exists())
        self.assertTrue(current.exists())

    def test_symlinked_output_is_rejected_before_cleanup(self) -> None:
        with patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaises(ValueError):
                self.workspace.prepare(LIVE_ID, 3)

    def test_health_endpoints_reflect_supervisor_state(self) -> None:
        client = TestClient(create_app(self.supervisor))
        self.assertEqual(client.get("/health/live").status_code, 503)

        self.supervisor.start()
        self.assertEqual(client.get("/health/live").status_code, 200)
        self.assertEqual(client.get("/health/ready").status_code, 503)

        self.workspace.manifest(LIVE_ID, 3).write_text("#EXTM3U", encoding="ascii")
        self.assertEqual(client.get("/health/ready").status_code, 200)


if __name__ == "__main__":
    unittest.main()