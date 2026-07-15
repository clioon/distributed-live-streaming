from .config import WorkerConfig
from .http import create_app
from .notifier import HttpWorkerNotifier
from .supervisor import WorkerSupervisor
from .workspace import HlsWorkspace


config = WorkerConfig.from_environment()
supervisor = WorkerSupervisor(
	config,
	HlsWorkspace(config.hls_root),
	notifier=(
		HttpWorkerNotifier(config.api_base_url) if config.api_base_url else None
	),
)
app = create_app(supervisor, manage_lifecycle=True)