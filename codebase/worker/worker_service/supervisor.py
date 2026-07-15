import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from .config import WorkerConfig
from .ffmpeg import build_ffmpeg_command
from .notifier import WorkerNotifier
from .workspace import HlsWorkspace


class ManagedProcess(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def kill(self) -> None: ...


class ProcessRunner(Protocol):
    def start(self, command: Sequence[str]) -> ManagedProcess: ...


class SubprocessRunner:
    def start(self, command: Sequence[str]) -> ManagedProcess:
        return subprocess.Popen(command, stdin=subprocess.DEVNULL)


@dataclass(frozen=True, slots=True)
class WorkerHealth:
    live_id: str
    generation: int
    process_running: bool
    manifest_ready: bool


class WorkerSupervisor:
    def __init__(
        self,
        config: WorkerConfig,
        workspace: HlsWorkspace,
        runner: ProcessRunner | None = None,
        notifier: WorkerNotifier | None = None,
    ) -> None:
        self._config = config
        self._workspace = workspace
        self._runner = runner or SubprocessRunner()
        self._notifier = notifier
        self._process: ManagedProcess | None = None
        self._ready_published = False
        self._ready_lock = Lock()

    def start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        output_directory = self._workspace.prepare(
            self._config.live_id, self._config.generation
        )
        self._ready_published = False
        self._process = self._runner.start(
            build_ffmpeg_command(self._config, output_directory)
        )

    def stop(self, *, timeout_seconds: float = 10.0) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=timeout_seconds)
        self._process = None
        self._ready_published = False

    def health(self) -> WorkerHealth:
        process_running = self._process is not None and self._process.poll() is None
        manifest = self._workspace.manifest(
            self._config.live_id, self._config.generation
        )
        manifest_exists = (
            process_running and manifest.is_file() and manifest.stat().st_size > 0
        )
        manifest_ready = manifest_exists
        if manifest_exists and self._notifier is not None:
            with self._ready_lock:
                if not self._ready_published:
                    try:
                        self._workspace.activate(
                            self._config.live_id,
                            self._config.generation,
                        )
                        self._notifier.notify_ready(
                            self._config.live_id,
                            self._config.generation,
                        )
                        self._ready_published = True
                    except Exception:
                        manifest_ready = False
                else:
                    manifest_ready = True
        return WorkerHealth(
            live_id=str(self._config.live_id),
            generation=self._config.generation,
            process_running=process_running,
            manifest_ready=manifest_ready,
        )