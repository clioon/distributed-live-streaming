import unittest
from uuid import UUID

from fastapi.testclient import TestClient

from ingest_service import CallbackService, InvalidCallback
from ingest_service.gateway import UpstreamRejected, UpstreamUnavailable
from ingest_service.http import create_app


LIVE_ID = UUID("30000000-0000-0000-0000-000000000001")


class RecordingGateway:
    def __init__(self) -> None:
        self.started = []
        self.stopped = []
        self.error = None

    def notify_started(self, notification) -> None:
        if self.error:
            raise self.error
        self.started.append(notification)

    def notify_stopped(self, notification) -> None:
        if self.error:
            raise self.error
        self.stopped.append(notification)


def valid_form() -> dict[str, str]:
    return {
        "app": "live",
        "name": str(LIVE_ID),
        "args": "token=stream-secret",
        "clientid": "rtmp-client-7",
        "addr": "192.0.2.10",
    }


class CallbackServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gateway = RecordingGateway()
        self.service = CallbackService(self.gateway)

    def test_start_and_stop_use_the_same_stable_ingest_session(self) -> None:
        started = self.service.on_publish(valid_form())
        stopped = self.service.on_publish_done(valid_form())

        self.assertEqual(started.live_id, LIVE_ID)
        self.assertEqual(started.stream_secret, "stream-secret")
        self.assertEqual(started.ingest_session_id, stopped.ingest_session_id)
        self.assertNotEqual(started.correlation_id, stopped.correlation_id)
        self.assertEqual(len(self.gateway.started), 1)
        self.assertEqual(len(self.gateway.stopped), 1)

    def test_token_can_be_embedded_in_stream_name(self) -> None:
        fields = valid_form()
        fields["name"] = f"{LIVE_ID}?token=stream-secret"
        fields["args"] = ""

        notification = self.service.on_publish(fields)

        self.assertEqual(notification.stream_secret, "stream-secret")

    def test_duplicate_identical_token_from_nginx_is_accepted(self) -> None:
        fields = valid_form()
        fields["name"] = f"{LIVE_ID}?token=stream-secret"

        notification = self.service.on_publish(fields)

        self.assertEqual(notification.stream_secret, "stream-secret")

    def test_nginx_notification_token_field_is_accepted(self) -> None:
        fields = valid_form()
        fields["args"] = ""
        fields["token"] = "stream-secret"

        notification = self.service.on_publish(fields)

        self.assertEqual(notification.stream_secret, "stream-secret")

    def test_conflicting_tokens_are_rejected(self) -> None:
        fields = valid_form()
        fields["name"] = f"{LIVE_ID}?token=other-secret"

        with self.assertRaises(InvalidCallback):
            self.service.on_publish(fields)

    def test_invalid_live_identifier_is_rejected_before_gateway(self) -> None:
        fields = valid_form()
        fields["name"] = "../../other-live"

        with self.assertRaises(InvalidCallback):
            self.service.on_publish(fields)

        self.assertEqual(self.gateway.started, [])

    def test_missing_token_is_rejected_before_gateway(self) -> None:
        fields = valid_form()
        fields["args"] = ""

        with self.assertRaises(InvalidCallback):
            self.service.on_publish(fields)

        self.assertEqual(self.gateway.started, [])


class CallbackHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gateway = RecordingGateway()
        self.client = TestClient(create_app(self.gateway))

    def test_nginx_form_is_accepted_only_after_gateway_accepts(self) -> None:
        response = self.client.post("/callbacks/on-publish", data=valid_form())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "OK")
        self.assertEqual(len(self.gateway.started), 1)

    def test_api_rejection_is_propagated_to_nginx(self) -> None:
        self.gateway.error = UpstreamRejected(403, "invalid stream")

        response = self.client.post("/callbacks/on-publish", data=valid_form())

        self.assertEqual(response.status_code, 403)

    def test_api_unavailability_does_not_silently_accept_stream(self) -> None:
        self.gateway.error = UpstreamUnavailable("API service is unavailable")

        response = self.client.post("/callbacks/on-publish", data=valid_form())

        self.assertEqual(response.status_code, 503)

    def test_malformed_form_returns_bad_request(self) -> None:
        response = self.client.post(
            "/callbacks/on-publish",
            data={"app": "live", "name": "invalid", "clientid": "7"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.gateway.started, [])

    def test_oversized_form_is_rejected_before_gateway(self) -> None:
        response = self.client.post(
            "/callbacks/on-publish",
            content=b"name=" + (b"a" * 5_000),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.gateway.started, [])


if __name__ == "__main__":
    unittest.main()