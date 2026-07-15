import os
from collections.abc import Callable

import docker
from docker.errors import DockerException
from fastapi import FastAPI

from .controller import (
    DockerOrchestratorController,
    UnavailableOrchestratorController,
)
from .http import create_app
from .monitor import HealthMonitor
from .probe import HttpOrchestratorProbe


def build_app(
    docker_client_factory: Callable[[], object] = docker.from_env,
) -> FastAPI:
    try:
        controller = DockerOrchestratorController(
            docker_client_factory(),
            container_name=os.getenv(
                "ORCHESTRATOR_CONTAINER_NAME", "worker-pool-orchestrator"
            ),
        )
    except DockerException as error:
        controller = UnavailableOrchestratorController(
            f"Docker daemon is unavailable: {error}"
        )

    monitor = HealthMonitor(
        HttpOrchestratorProbe(
            os.getenv(
                "ORCHESTRATOR_URL", "http://worker-pool-orchestrator:8000"
            )
        ),
        controller,
        failure_threshold=int(os.getenv("FAILURE_THRESHOLD", "3")),
        cooldown_checks=int(os.getenv("COOLDOWN_CHECKS", "2")),
    )
    return create_app(
        monitor,
        manage_lifecycle=True,
        check_interval_seconds=float(os.getenv("CHECK_INTERVAL_SECONDS", "5")),
    )


app = build_app()