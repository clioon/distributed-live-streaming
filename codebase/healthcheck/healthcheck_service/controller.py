from typing import Protocol


class Container(Protocol):
    labels: dict[str, str]

    def restart(self, *, timeout: int) -> None: ...


class ContainerCollection(Protocol):
    def get(self, name: str) -> Container: ...


class DockerClient(Protocol):
    containers: ContainerCollection


class UnavailableOrchestratorController:
    def __init__(self, reason: str) -> None:
        self._reason = reason

    def restart(self) -> None:
        raise RuntimeError(self._reason)


class DockerOrchestratorController:
    def __init__(
        self,
        client: DockerClient,
        *,
        container_name: str,
        restart_timeout_seconds: int = 10,
    ) -> None:
        if not container_name:
            raise ValueError("Orchestrator container name is required")
        if restart_timeout_seconds < 1:
            raise ValueError("Restart timeout must be greater than zero")
        self._client = client
        self._container_name = container_name
        self._restart_timeout_seconds = restart_timeout_seconds

    def restart(self) -> None:
        container = self._client.containers.get(self._container_name)
        if container.labels.get("streaming.component") != "orchestrator":
            raise PermissionError("Refusing to restart an unmanaged container")
        container.restart(timeout=self._restart_timeout_seconds)