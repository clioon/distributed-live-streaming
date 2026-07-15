import unittest
from uuid import UUID

from fastapi.testclient import TestClient

from api_service import InMemoryLiveStore, LiveService
from api_service.http import create_app


OWNER_ID = UUID("10000000-0000-0000-0000-000000000001")
SESSION_ID = UUID("10000000-0000-0000-0000-000000000002")


class HttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryLiveStore()
        service = LiveService(self.store, secret_factory=lambda: "http-secret")
        self.client = TestClient(
            create_app(
                service,
                rtmp_server="rtmp://ingest.example/live",
            )
        )

    def create_live(self) -> dict:
        response = self.client.post(
            "/v1/lives",
            json={
                "owner_id": str(OWNER_ID),
                "title": "Systems lecture",
                "description": "An isolated API test",
            },
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_create_and_get_live_without_exposing_secret_hash(self) -> None:
        created = self.create_live()

        self.assertEqual(created["rtmp_server"], "rtmp://ingest.example/live")
        self.assertTrue(created["stream_key"].endswith("?token=http-secret"))
        self.assertNotIn("stream_secret_hash", created["live"])

        response = self.client.get(f"/v1/lives/{created['live']['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "created")
        self.assertNotIn("stream_key", response.json())
        self.assertNotIn("current_ingest_session_id", response.json())

    def test_ingest_callback_is_idempotent_and_filterable(self) -> None:
        created = self.create_live()
        live_id = created["live"]["id"]
        request = {
            "live_id": live_id,
            "stream_secret": "http-secret",
            "ingest_session_id": str(SESSION_ID),
            "client_id": "rtmp-client-7",
            "source_ip": "192.0.2.10",
        }

        first = self.client.post(
            "/internal/v1/ingest/published",
            json=request,
        )
        repeated = self.client.post(
            "/internal/v1/ingest/published",
            json=request,
        )
        filtered = self.client.get("/v1/lives?status=ingesting")

        self.assertEqual(first.status_code, 202)
        self.assertEqual(repeated.status_code, 202)
        self.assertEqual(first.json(), repeated.json())
        self.assertEqual(len(self.store.events()), 1)
        self.assertEqual([item["id"] for item in filtered.json()], [live_id])

    def test_invalid_stream_secret_rejects_ingest(self) -> None:
        created = self.create_live()

        response = self.client.post(
            "/internal/v1/ingest/published",
            json={
                "live_id": created["live"]["id"],
                "stream_secret": "invalid",
                "ingest_session_id": str(SESSION_ID),
                "client_id": "rtmp-client-7",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.store.events(), ())

    def test_unknown_live_returns_not_found(self) -> None:
        response = self.client.get(
            "/v1/lives/20000000-0000-0000-0000-000000000001"
        )

        self.assertEqual(response.status_code, 404)

    def test_service_endpoints_work_without_credentials(self) -> None:
        created = self.create_live()

        self.assertEqual(self.client.get("/v1/lives").status_code, 200)
        response = self.client.post(
            "/internal/v1/ingest/published",
            json={
                "live_id": created["live"]["id"],
                "stream_secret": "http-secret",
                "ingest_session_id": str(SESSION_ID),
                "client_id": "rtmp-client-7",
            },
        )
        self.assertEqual(response.status_code, 202)

    def test_health_endpoint_has_no_external_dependency(self) -> None:
        response = self.client.get("/health/live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()