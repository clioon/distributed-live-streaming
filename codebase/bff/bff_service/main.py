import os

from .gateway import HttpApiGateway
from .http import create_app


app = create_app(
    HttpApiGateway(os.getenv("API_BASE_URL", "http://api-service:8000")),
    hls_base_url=os.getenv("HLS_BASE_URL", "http://localhost/hls"),
    chat_websocket_base_url=os.getenv("CHAT_WS_BASE_URL", "ws://localhost"),
)