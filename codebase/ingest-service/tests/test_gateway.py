import json
import unittest
from uuid import UUID

import httpx

from ingest_service.callbacks import PublishStarted
from ingest_service.gateway import (
    HttpApiGateway,
    UpstreamRejected,
    UpstreamUnavailable,
)


LIVE_ID = UUID("40000000-0000-0000-0000-000000000001")
SESSION_ID = UUID("40000000-0000-0000-0000-000000000002")
CORRELATION_ID = UUID("40000000-0000-0000-0000-000000000003")


def started_notification() -> PublishStarted:
    return PublishStarted(
        live_id=LIVE_ID,
        stream_secret="stream-secret",
        ingest_session_id=SESSION_ID,
        correlation_id=CORRELATION_ID,
        client_id="rtmp-client-7",
        remote_address="192.0.2.10",
    )


class HttpApiGatewayTests(unittest.TestCase):
    def test_started_notification_uses_internal_api_contract(self) -> None:
        received = []

        def handler(request: httpx.Request) -> httpx.Response:
            received.append(request)
            return httpx.Response(202, json={"status": "ingesting"})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            gateway = HttpApiGateway(
                "http://api-service:8000",
                client=client,
            )
            gateway.notify_started(started_notification())

        self.assertEqual(received[0].url.path, "/internal/v1/ingest/published")
        self.assertNotIn("X-Internal-Token", received[0].headers)
        self.assertEqual(
            json.loads(received[0].content),
            {
                "live_id": str(LIVE_ID),
                "stream_secret": "stream-secret",
                "ingest_session_id": str(SESSION_ID),
                "correlation_id": str(CORRELATION_ID),
                "client_id": "rtmp-client-7",
                "source_ip": "192.0.2.10",
            },
        )

    def test_upstream_rejection_preserves_status_and_detail(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"detail": "invalid stream"})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            gateway = HttpApiGateway(
                "http://api-service:8000",
                client=client,
            )
            with self.assertRaises(UpstreamRejected) as raised:
                gateway.notify_started(started_notification())

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(str(raised.exception), "invalid stream")

    def test_connection_failure_becomes_service_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            gateway = HttpApiGateway(
                "http://api-service:8000",
                client=client,
            )
            with self.assertRaises(UpstreamUnavailable):
                gateway.notify_started(started_notification())


if __name__ == "__main__":
    unittest.main()