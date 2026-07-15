import os

from .http import create_app
from .outbox import OutboxRelay, PostgresOutboxRepository, RabbitEventPublisher
from .postgres import PostgresLiveStore
from .service import InMemoryLiveStore, LiveService


database_url = os.getenv("DATABASE_URL")
store = PostgresLiveStore(database_url) if database_url else InMemoryLiveStore()
amqp_url = os.getenv("AMQP_URL")
relay = (
	OutboxRelay(
		PostgresOutboxRepository(database_url),
		RabbitEventPublisher(amqp_url),
	)
	if database_url and amqp_url
	else None
)
app = create_app(
	LiveService(store),
	rtmp_server=os.getenv("RTMP_SERVER", "rtmp://localhost:1935/live"),
	background_service=relay,
)