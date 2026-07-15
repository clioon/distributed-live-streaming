from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import Protocol


class OrchestratorProbe(Protocol):
    def is_healthy(self) -> bool: ...


class OrchestratorController(Protocol):
    def restart(self) -> None: ...


class MonitorOutcome(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RESTARTED = "restarted"
    RESTART_FAILED = "restart_failed"


@dataclass(frozen=True, slots=True)
class MonitorState:
    checks: int
    consecutive_failures: int
    restart_count: int
    cooldown_remaining: int
    last_outcome: MonitorOutcome | None
    last_error: str | None


class HealthMonitor:
    def __init__(
        self,
        probe: OrchestratorProbe,
        controller: OrchestratorController,
        *,
        failure_threshold: int = 3,
        cooldown_checks: int = 2,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("Failure threshold must be greater than zero")
        if cooldown_checks < 0:
            raise ValueError("Cooldown checks cannot be negative")
        self._probe = probe
        self._controller = controller
        self._failure_threshold = failure_threshold
        self._cooldown_checks = cooldown_checks
        self._state = MonitorState(0, 0, 0, 0, None, None)
        self._lock = Lock()

    def check_once(self) -> MonitorOutcome:
        try:
            healthy = self._probe.is_healthy()
            probe_error = None
        except Exception as error:
            healthy = False
            probe_error = str(error)

        with self._lock:
            state = self._state
            checks = state.checks + 1
            if healthy:
                self._state = MonitorState(
                    checks,
                    0,
                    state.restart_count,
                    0,
                    MonitorOutcome.HEALTHY,
                    None,
                )
                return MonitorOutcome.HEALTHY

            if state.cooldown_remaining > 0:
                self._state = MonitorState(
                    checks,
                    state.consecutive_failures,
                    state.restart_count,
                    state.cooldown_remaining - 1,
                    MonitorOutcome.DEGRADED,
                    probe_error or "Orchestrator is unhealthy during cooldown",
                )
                return MonitorOutcome.DEGRADED

            failures = state.consecutive_failures + 1
            if failures < self._failure_threshold:
                self._state = MonitorState(
                    checks,
                    failures,
                    state.restart_count,
                    0,
                    MonitorOutcome.DEGRADED,
                    probe_error or "Orchestrator is unhealthy",
                )
                return MonitorOutcome.DEGRADED

        try:
            self._controller.restart()
        except Exception as error:
            with self._lock:
                state = self._state
                self._state = MonitorState(
                    checks,
                    failures,
                    state.restart_count,
                    max(1, self._cooldown_checks),
                    MonitorOutcome.RESTART_FAILED,
                    str(error),
                )
            return MonitorOutcome.RESTART_FAILED

        with self._lock:
            state = self._state
            self._state = MonitorState(
                checks,
                0,
                state.restart_count + 1,
                self._cooldown_checks,
                MonitorOutcome.RESTARTED,
                None,
            )
        return MonitorOutcome.RESTARTED

    def snapshot(self) -> MonitorState:
        with self._lock:
            return self._state