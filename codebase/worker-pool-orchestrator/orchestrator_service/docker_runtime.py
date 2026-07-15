from uuid import UUID

from docker.errors import APIError, NotFound

from .models import WorkerContainer, WorkerSpec


class DockerWorkerRuntime:
    def __init__(
        self,
        client,
        *,
        network_name: str,
        hls_volume_name: str,
    ) -> None:
        self._client = client
        self._network_name = network_name
        self._hls_volume_name = hls_volume_name

    def list_workers(self, live_id: UUID) -> tuple[WorkerContainer, ...]:
        containers = self._client.containers.list(
            all=True,
            filters={
                "label": [
                    "streaming.component=worker",
                    f"streaming.live_id={live_id}",
                ]
            },
        )
        workers = []
        for container in containers:
            container.reload()
            labels = container.labels
            health_status = (
                container.attrs.get("State", {})
                .get("Health", {})
                .get("Status", "starting")
            )
            workers.append(
                WorkerContainer(
                    id=container.id,
                    live_id=UUID(labels["streaming.live_id"]),
                    generation=int(labels["streaming.generation"]),
                    healthy=(
                        container.status == "running"
                        and health_status != "unhealthy"
                    ),
                )
            )
        return tuple(workers)

    def start_worker(self, spec: WorkerSpec) -> WorkerContainer:
        container = self._client.containers.run(
            spec.image,
            detach=True,
            name=spec.container_name,
            environment=dict(spec.environment),
            labels=dict(spec.labels),
            network=self._network_name,
            volumes={
                self._hls_volume_name: {"bind": "/var/hls", "mode": "rw"}
            },
            restart_policy={"Name": "unless-stopped"},
        )
        return WorkerContainer(
            id=container.id,
            live_id=spec.live_id,
            generation=spec.generation,
            healthy=True,
        )

    def stop_worker(self, worker_id: str) -> None:
        try:
            container = self._client.containers.get(worker_id)
            container.remove(force=True)
        except NotFound:
            return
        except APIError as error:
            if error.response is not None and error.response.status_code == 409:
                return
            raise