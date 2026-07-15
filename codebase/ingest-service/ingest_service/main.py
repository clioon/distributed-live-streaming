import os

from .http import create_app


app = create_app(
	api_base_url=os.getenv("API_BASE_URL", "http://api-service:8000"),
)