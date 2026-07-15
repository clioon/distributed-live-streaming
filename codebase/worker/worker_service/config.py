import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    live_id: UUID
    generation: int
    ingest_base_url: str
    hls_root: Path
    api_base_url: str | None = None
    segment_seconds: int = 2
    playlist_size: int = 6

    def __post_init__(self) -> None:
        parsed_url = urlparse(self.ingest_base_url)
        if parsed_url.scheme != "rtmp" or not parsed_url.netloc:
            raise ValueError("INGEST_BASE_URL must be an absolute RTMP URL")
        if self.api_base_url is not None:
            parsed_api_url = urlparse(self.api_base_url)
            if parsed_api_url.scheme not in {"http", "https"} or not parsed_api_url.netloc:
                raise ValueError("API_BASE_URL must be an absolute HTTP URL")
        if self.generation < 1:
            raise ValueError("GENERATION must be greater than zero")
        if not 1 <= self.segment_seconds <= 10:
            raise ValueError("SEGMENT_SECONDS must be between 1 and 10")
        if self.playlist_size < 3:
            raise ValueError("PLAYLIST_SIZE must be at least 3")

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> "WorkerConfig":
        values = environment or os.environ
        try:
            return cls(
                live_id=UUID(values["LIVE_ID"]),
                generation=int(values["GENERATION"]),
                ingest_base_url=values.get(
                    "INGEST_BASE_URL", "rtmp://ingest-service:1935/live"
                ),
                hls_root=Path(values.get("HLS_ROOT", "/var/hls")),
                api_base_url=values.get("API_BASE_URL", "http://api-service:8000"),
                segment_seconds=int(values.get("SEGMENT_SECONDS", "2")),
                playlist_size=int(values.get("PLAYLIST_SIZE", "6")),
            )
        except (KeyError, ValueError) as error:
            raise ValueError("Invalid worker environment configuration") from error

    @property
    def input_url(self) -> str:
        return f"{self.ingest_base_url.rstrip('/')}/{self.live_id}"