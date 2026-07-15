import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PublishInvocation:
    sequence_key: str
    deduplication_key: str
    channel: str
    encoded_message: str
    deduplication_ttl_seconds: int

    def redis_arguments(self) -> tuple[object, ...]:
        return (
            2,
            self.sequence_key,
            self.deduplication_key,
            self.channel,
            self.encoded_message,
            self.deduplication_ttl_seconds,
        )


def build_publish_invocation(
    *,
    live_id: UUID,
    user_id: UUID,
    client_message_id: UUID,
    message: dict[str, Any],
    deduplication_ttl_seconds: int = 3600,
) -> PublishInvocation:
    if deduplication_ttl_seconds < 60:
        raise ValueError("Deduplication TTL must be at least 60 seconds")
    if "sequence" in message:
        raise ValueError("Sequence is assigned atomically by Redis")
    namespace = f"chat:live:{live_id}"
    return PublishInvocation(
        sequence_key=f"{namespace}:sequence",
        deduplication_key=(
            f"{namespace}:dedupe:{user_id}:{client_message_id}"
        ),
        channel=f"chat.live.{live_id}.v1",
        encoded_message=json.dumps(
            message, separators=(",", ":"), sort_keys=True
        ),
        deduplication_ttl_seconds=deduplication_ttl_seconds,
    )


def decode_result(result: list[object] | tuple[object, ...]) -> tuple[bool, dict[str, Any]]:
    if len(result) != 2:
        raise ValueError("Redis publish script returned an invalid result")
    created = bool(int(result[0]))
    encoded = result[1].decode("utf-8") if isinstance(result[1], bytes) else str(result[1])
    payload = json.loads(encoded)
    if not isinstance(payload, dict) or not isinstance(payload.get("sequence"), int):
        raise ValueError("Redis publish result lacks a sequence")
    return created, payload