import unittest
from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from bff_service import create_app


LIVE_ID = UUID("90000000-0000-0000-0000-000000000001")
USER_ID = UUID("90000000-0000-0000-0000-000000000002")
NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


def live(status="live"):
    return {
        "id": str(LIVE_ID),
        "owner_id": str(USER_ID),
        "title": "Distributed live",
        "description": "Lecture",
        "status": status,
        "version": 3,
        "started_at": NOW.isoformat(),
        "stream_secret_hash": "must-not-leak",
    }


class FakeGateway:
    def __init__(self) -> None:
        self.created_with = None
        self.live = live()

    def create_live(self, *, owner_id, title, description):
        self.created_with = (owner_id, title, description)
        return {
            "live": {**live("created"), "owner_id": str(owner_id)},
            "rtmp_server": "rtmp://localhost/live",
            "stream_key": f"{LIVE_ID}?token=one-time-secret",
        }

    def list_lives(self, *, status):
        self.list_status = status
        return [self.live]

    def get_live(self, live_id):
        self.requested_live_id = live_id
        return self.live


class BffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gateway = FakeGateway()
        self.client = TestClient(
            create_app(
                self.gateway,
                hls_base_url="https://media.example/hls",
                chat_websocket_base_url="wss://chat.example",
                demo_user_id=USER_ID,
                demo_display_name="Alice",
            )
        )

    def test_create_live_uses_demo_owner(self) -> None:
        response = self.client.post(
            "/api/v1/lives",
            json={"title": "Distributed live", "description": "Lecture"},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.gateway.created_with[0], USER_ID)
        self.assertNotIn("stream_secret_hash", response.json()["live"])
        self.assertIn("stream_key", response.json())

    def test_create_live_accepts_explicit_owner(self) -> None:
        owner_id = UUID("90000000-0000-0000-0000-000000000003")
        response = self.client.post(
            "/api/v1/lives",
            json={
                "owner_id": str(owner_id),
                "title": "Live",
                "description": "",
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.gateway.created_with[0], owner_id)

    def test_catalog_only_requests_live_streams_and_hides_internal_fields(self) -> None:
        response = self.client.get("/api/v1/lives")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.gateway.list_status, "live")
        self.assertNotIn("stream_secret_hash", response.json()[0])

    def test_playback_session_aggregates_stable_urls_and_demo_chat_user(self) -> None:
        response = self.client.post(
            f"/api/v1/lives/{LIVE_ID}/playback-session",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["manifest_url"],
            f"https://media.example/hls/{LIVE_ID}/current/index.m3u8",
        )
        self.assertEqual(
            payload["chat_websocket_url"],
            f"wss://chat.example/ws/v1/lives/{LIVE_ID}",
        )
        self.assertEqual(payload["chat_user_id"], str(USER_ID))
        self.assertEqual(payload["chat_display_name"], "Alice")
        self.assertNotIn("set-cookie", response.headers)

    def test_playback_session_rejects_live_that_is_not_ready(self) -> None:
        self.gateway.live = live("provisioning")

        response = self.client.post(
            f"/api/v1/lives/{LIVE_ID}/playback-session",
        )

        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()