from uuid import UUID

from .broker import ChatBroker
from .models import ChatIdentity, MessageDraft, PublishResult


class InvalidChatMessage(ValueError):
    pass


class ChatService:
    def __init__(self, broker: ChatBroker):
        self._broker = broker

    def send(
        self,
        *,
        identity: ChatIdentity,
        live_id: UUID,
        client_message_id: UUID,
        text: str,
    ) -> PublishResult:
        if identity.live_id != live_id:
            raise InvalidChatMessage("Chat ticket does not authorize this live")
        normalized_text = text.strip()
        if not normalized_text or len(normalized_text) > 500:
            raise InvalidChatMessage("Message must contain between 1 and 500 characters")
        if any(ord(character) < 32 and character not in "\n\t" for character in normalized_text):
            raise InvalidChatMessage("Message contains unsupported control characters")
        return self._broker.publish_once(
            MessageDraft(
                live_id=live_id,
                user_id=identity.user_id,
                display_name=identity.display_name,
                client_message_id=client_message_id,
                text=normalized_text,
            )
        )