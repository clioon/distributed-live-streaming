from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True, slots=True)
class OrchestratorHealth:
    running: bool
    leader: bool
    last_error: str | None


class OrchestratorProbe:
    def __init__(self) -> None:
        self._running = False
        self._leader = False
        self._last_error: str | None = None
        self._lock = Lock()

    def started(self) -> None:
        with self._lock:
            self._running = True
            self._last_error = None

    def stopped(self) -> None:
        with self._lock:
            self._running = False
            self._leader = False

    def leadership_changed(self, *, leader: bool) -> None:
        with self._lock:
            self._leader = leader

    def failed(self, error: Exception) -> None:
        with self._lock:
            self._last_error = str(error)

    def snapshot(self) -> OrchestratorHealth:
        with self._lock:
            return OrchestratorHealth(
                running=self._running,
                leader=self._leader,
                last_error=self._last_error,
            )