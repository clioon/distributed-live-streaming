import os

import docker
from docker.errors import DockerException

from .consumer import RabbitLifecycleConsumer
from .docker_runtime import DockerWorkerRuntime
from .health import OrchestratorProbe
from .http import create_app
from .messages import MessageProcessor
from .runtime import OrchestratorRuntime, PostgresStateLoader
from .service import OrchestratorService
from .store import InMemoryOrchestratorStore


def build_app(docker_client_factory=docker.from_env):
	probe = OrchestratorProbe()
	try:
		docker_client = docker_client_factory()
	except DockerException as error:
		probe.failed(error)
		return create_app(probe)

	store = InMemoryOrchestratorStore()
	service = OrchestratorService(
		store,
		DockerWorkerRuntime(
			docker_client,
			network_name=os.getenv(
				"DOCKER_NETWORK", "distributed-live-streaming-network"
			),
			hls_volume_name=os.getenv(
				"HLS_VOLUME", "distributed-live-hls-data"
			),
		),
		worker_image=os.getenv(
			"WORKER_IMAGE", "distributed-live-streaming-worker:local"
		),
		ingest_base_url=os.getenv(
			"INGEST_BASE_URL", "rtmp://ingest-service:1935/live"
		),
		api_base_url=os.getenv("API_BASE_URL", "http://api-service:8000"),
	)
	consumer = RabbitLifecycleConsumer(
		os.getenv(
			"AMQP_URL", "amqp://guest:guest@rabbitmq:5672/%2Fstreaming"
		),
		MessageProcessor(service),
		probe,
	)
	database_url = os.getenv("DATABASE_URL")
	runtime = OrchestratorRuntime(
		service,
		consumer,
		state_loader=(
			PostgresStateLoader(database_url, store) if database_url else None
		),
	)
	return create_app(probe, runtime)


app = build_app()