from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime, timezone
from threading import Lock
from typing import Protocol
from uuid import UUID, uuid4

from .models import ChatMessage, MessageDraft, PublishResult


class ConflictingClientMessage(ValueError):
    pass


class ChatCapacityExceeded(RuntimeError):
    pass


class ChatBroker(Protocol):
    def publish_once(self, draft: MessageDraft) -> PublishResult: ...

    def is_ready(self) -> bool: ...


class InMemoryChatBroker:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
        max_deduplication_entries: int = 10_000,
        max_active_lives: int = 10_000,
    ) -> None:
        if max_deduplication_entries < 1 or max_active_lives < 1:
            raise ValueError("Chat broker limits must be greater than zero")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or uuid4
        self._max_deduplication_entries = max_deduplication_entries
        self._max_active_lives = max_active_lives
        self._sequences: dict[UUID, int] = {}
        self._messages: OrderedDict[tuple[UUID, UUID, UUID], ChatMessage] = (
            OrderedDict()
        )
        self._lock = Lock()

    def publish_once(self, draft: MessageDraft) -> PublishResult:
        key = (draft.live_id, draft.user_id, draft.client_message_id)
        with self._lock:
            existing = self._messages.get(key)
            if existing is not None:
                if (
                    existing.live_id != draft.live_id
                    or existing.text != draft.text
                ):
                    raise ConflictingClientMessage(
                        "A client message ID cannot be reused with different content"
                    )
                self._messages.move_to_end(key)
                return PublishResult(existing, created=False)

            if (
                draft.live_id not in self._sequences
                and len(self._sequences) >= self._max_active_lives
            ):
                raise ChatCapacityExceeded("Chat live capacity has been reached")
            sequence = self._sequences.get(draft.live_id, 0) + 1
            self._sequences[draft.live_id] = sequence
            message = ChatMessage(
                message_id=self._id_factory(),
                live_id=draft.live_id,
                user_id=draft.user_id,
                display_name=draft.display_name,
                client_message_id=draft.client_message_id,
                sequence=sequence,
                sent_at=self._clock(),
                text=draft.text,
            )
            self._messages[key] = message
            while len(self._messages) > self._max_deduplication_entries:
                self._messages.popitem(last=False)
            return PublishResult(message, created=True)

    def is_ready(self) -> bool:
        return True