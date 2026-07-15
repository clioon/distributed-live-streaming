from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ChatIdentity:
    user_id: UUID
    display_name: str
    live_id: UUID
    ticket_id: UUID


@dataclass(frozen=True, slots=True)
class MessageDraft:
    live_id: UUID
    user_id: UUID
    display_name: str
    client_message_id: UUID
    text: str


@dataclass(frozen=True, slots=True)
class ChatMessage:
    message_id: UUID
    live_id: UUID
    user_id: UUID
    display_name: str
    client_message_id: UUID
    sequence: int
    sent_at: datetime
    text: str

    def as_payload(self) -> dict[str, object]:
        return {
            "type": "chat.message.created",
            "message_id": str(self.message_id),
            "client_message_id": str(self.client_message_id),
            "live_id": str(self.live_id),
            "user": {
                "id": str(self.user_id),
                "display_name": self.display_name,
            },
            "sequence": self.sequence,
            "sent_at": self.sent_at.isoformat(),
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class PublishResult:
    message: ChatMessage
    created: bool