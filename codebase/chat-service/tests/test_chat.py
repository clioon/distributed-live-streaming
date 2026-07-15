import unittest
from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from chat_service import (
    ChatIdentity,
    ChatService,
    InMemoryChatBroker,
    InvalidChatMessage,
)
from chat_service.broker import ConflictingClientMessage
from chat_service.http import create_app


LIVE_ID = UUID("80000000-0000-0000-0000-000000000001")
OTHER_LIVE_ID = UUID("80000000-0000-0000-0000-000000000002")
USER_ID = UUID("80000000-0000-0000-0000-000000000003")
OTHER_USER_ID = UUID("80000000-0000-0000-0000-000000000004")
MESSAGE_ID_1 = UUID("80000000-0000-0000-0000-000000000005")
MESSAGE_ID_2 = UUID("80000000-0000-0000-0000-000000000006")
CLIENT_MESSAGE_ID = UUID("80000000-0000-0000-0000-000000000007")
OTHER_CLIENT_MESSAGE_ID = UUID("80000000-0000-0000-0000-000000000008")
TICKET_ID = UUID("80000000-0000-0000-0000-000000000009")
NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


class ChatDomainTests(unittest.TestCase):
    def setUp(self) -> None:
        identifiers = iter([MESSAGE_ID_1, MESSAGE_ID_2])
        self.broker = InMemoryChatBroker(
            clock=lambda: NOW,
            id_factory=lambda: next(identifiers),
        )
        self.service = ChatService(self.broker)
        self.identity = ChatIdentity(USER_ID, "Alice", LIVE_ID, TICKET_ID)

    def test_messages_receive_monotonic_sequence_per_live(self) -> None:
        first = self.service.send(
            identity=self.identity,
            live_id=LIVE_ID,
            client_message_id=CLIENT_MESSAGE_ID,
            text="First",
        )
        second = self.service.send(
            identity=self.identity,
            live_id=LIVE_ID,
            client_message_id=OTHER_CLIENT_MESSAGE_ID,
            text="Second",
        )

        self.assertEqual((first.message.sequence, second.message.sequence), (1, 2))

    def test_repeated_client_message_is_deduplicated(self) -> None:
        first = self.service.send(
            identity=self.identity,
            live_id=LIVE_ID,
            client_message_id=CLIENT_MESSAGE_ID,
            text="Hello",
        )
        repeated = self.service.send(
            identity=self.identity,
            live_id=LIVE_ID,
            client_message_id=CLIENT_MESSAGE_ID,
            text="Hello",
        )

        self.assertTrue(first.created)
        self.assertFalse(repeated.created)
        self.assertEqual(first.message, repeated.message)

    def test_reusing_client_id_with_other_content_is_rejected(self) -> None:
        self.service.send(
            identity=self.identity,
            live_id=LIVE_ID,
            client_message_id=CLIENT_MESSAGE_ID,
            text="Hello",
        )

        with self.assertRaises(ConflictingClientMessage):
            self.service.send(
                identity=self.identity,
                live_id=LIVE_ID,
                client_message_id=CLIENT_MESSAGE_ID,
                text="Changed",
            )

    def test_identity_for_another_live_and_invalid_text_are_rejected(self) -> None:
        with self.assertRaises(InvalidChatMessage):
            self.service.send(
                identity=self.identity,
                live_id=OTHER_LIVE_ID,
                client_message_id=CLIENT_MESSAGE_ID,
                text="Hello",
            )
        with self.assertRaises(InvalidChatMessage):
            self.service.send(
                identity=self.identity,
                live_id=LIVE_ID,
                client_message_id=CLIENT_MESSAGE_ID,
                text="   ",
            )

    def test_deduplication_retention_is_bounded(self) -> None:
        identifiers = iter(
            [
                MESSAGE_ID_1,
                MESSAGE_ID_2,
                TICKET_ID,
                UUID("80000000-0000-0000-0000-000000000011"),
            ]
        )
        broker = InMemoryChatBroker(
            clock=lambda: NOW,
            id_factory=lambda: next(identifiers),
            max_deduplication_entries=2,
        )
        service = ChatService(broker)
        client_ids = [
            CLIENT_MESSAGE_ID,
            OTHER_CLIENT_MESSAGE_ID,
            UUID("80000000-0000-0000-0000-000000000010"),
        ]
        for index, client_id in enumerate(client_ids):
            service.send(
                identity=self.identity,
                live_id=LIVE_ID,
                client_message_id=client_id,
                text=f"Message {index}",
            )

        replayed = service.send(
            identity=self.identity,
            live_id=LIVE_ID,
            client_message_id=CLIENT_MESSAGE_ID,
            text="Message 0",
        )
        self.assertTrue(replayed.created)
        self.assertEqual(replayed.message.sequence, 4)


class WebSocketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.broker = InMemoryChatBroker(clock=lambda: NOW)
        self.client = TestClient(create_app(self.broker))

    def url(self, user_id=USER_ID, display_name="Alice") -> str:
        return (
            f"/ws/v1/lives/{LIVE_ID}?user_id={user_id}"
            f"&display_name={display_name}"
        )

    def test_message_is_broadcast_to_connected_viewers(self) -> None:
        with self.client.websocket_connect(self.url()) as alice:
            with self.client.websocket_connect(
                self.url(OTHER_USER_ID, "Bob")
            ) as bob:
                alice.send_json(
                    {
                        "type": "chat.message.send",
                        "client_message_id": str(CLIENT_MESSAGE_ID),
                        "text": "Hello live",
                    }
                )

                alice_message = alice.receive_json()
                bob_message = bob.receive_json()

        self.assertEqual(alice_message, bob_message)
        self.assertEqual(alice_message["sequence"], 1)
        self.assertEqual(alice_message["text"], "Hello live")

    def test_missing_user_id_is_rejected(self) -> None:
        with self.assertRaises(WebSocketDisconnect) as closed:
            with self.client.websocket_connect(
                f"/ws/v1/lives/{LIVE_ID}",
            ):
                pass

        self.assertEqual(closed.exception.code, 1008)

    def test_invalid_message_returns_protocol_error(self) -> None:
        with self.client.websocket_connect(self.url()) as websocket:
            websocket.send_json({"type": "unsupported"})
            error = websocket.receive_json()

        self.assertEqual(error["type"], "chat.error")
        self.assertEqual(error["code"], "invalid_message")

    def test_origin_header_is_not_required(self) -> None:
        with self.client.websocket_connect(self.url()) as websocket:
            websocket.send_json({"type": "unsupported"})
            self.assertEqual(websocket.receive_json()["type"], "chat.error")


if __name__ == "__main__":
    unittest.main()