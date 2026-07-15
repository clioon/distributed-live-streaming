import os

from .broker import InMemoryChatBroker
from .http import create_app
from .redis_broker import RedisChatBroker


redis_url = os.getenv("REDIS_URL")
app = create_app(
	RedisChatBroker(redis_url) if redis_url else InMemoryChatBroker()
)