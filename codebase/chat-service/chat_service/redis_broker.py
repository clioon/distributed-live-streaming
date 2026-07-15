import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import redis

from .broker import ConflictingClientMessage
from .models import ChatMessage, MessageDraft, PublishResult


class RedisChatBroker:
    def __init__(
        self,
        redis_url: str,
        *,
        client=None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
        deduplication_ttl_seconds: int = 3600,
    ) -> None:
        self._client = client or redis.Redis.from_url(redis_url)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or uuid4
        self._deduplication_ttl_seconds = deduplication_ttl_seconds
        script = Path(__file__).with_name("publish_chat.lua").read_text(
            encoding="utf-8"
        )
        self._publish_script = self._client.register_script(script)

    def publish_once(self, draft: MessageDraft) -> PublishResult:
        message_id = self._id_factory()
        sent_at = self._clock()
        namespace = f"chat:live:{draft.live_id}"
        channel = f"chat.live.{draft.live_id}.v1"
        payload = {
            "type": "chat.message.created",
            "message_id": str(message_id),
            "client_message_id": str(draft.client_message_id),
            "live_id": str(draft.live_id),
            "user": {
                "id": str(draft.user_id),
                "display_name": draft.display_name,
            },
            "sent_at": sent_at.isoformat(),
            "text": draft.text,
        }
        result = self._publish_script(
            keys=[
                f"{namespace}:sequence",
                f"{namespace}:dedupe:{draft.user_id}:{draft.client_message_id}",
            ],
            args=[
                channel,
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                self._deduplication_ttl_seconds,
            ],
        )
        created = bool(int(result[0]))
        encoded = result[1].decode("utf-8") if isinstance(result[1], bytes) else str(result[1])
        stored = json.loads(encoded)
        if (
            stored["text"] != draft.text
            or stored["user"]["id"] != str(draft.user_id)
        ):
            raise ConflictingClientMessage(
                "A client message ID cannot be reused with different content"
            )
        message = ChatMessage(
            message_id=UUID(stored["message_id"]),
            live_id=UUID(stored["live_id"]),
            user_id=UUID(stored["user"]["id"]),
            display_name=str(stored["user"]["display_name"]),
            client_message_id=UUID(stored["client_message_id"]),
            sequence=int(stored["sequence"]),
            sent_at=datetime.fromisoformat(stored["sent_at"]),
            text=str(stored["text"]),
        )
        return PublishResult(message, created=created)

    def is_ready(self) -> bool:
        try:
            return bool(self._client.ping())
        except redis.RedisError:
            return False