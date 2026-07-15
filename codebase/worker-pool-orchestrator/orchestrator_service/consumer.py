import logging
from threading import Event, Thread

import pika

from .health import OrchestratorProbe
from .messages import DeliveryDecision, MessageProcessor


LOGGER = logging.getLogger(__name__)


class RabbitLifecycleConsumer:
    def __init__(
        self,
        amqp_url: str,
        processor: MessageProcessor,
        probe: OrchestratorProbe,
        *,
        queue_name: str = "orchestrator.live-lifecycle.v1",
        retry_seconds: float = 2.0,
    ) -> None:
        self._parameters = pika.URLParameters(amqp_url)
        self._processor = processor
        self._probe = probe
        self._queue_name = queue_name
        self._retry_seconds = retry_seconds
        self._stop = Event()
        self._thread: Thread | None = None
        self._connection = None
        self._channel = None

    def handle_delivery(self, channel, method, body: bytes) -> DeliveryDecision:
        decision = self._processor.process(body)
        if decision is DeliveryDecision.ACK:
            channel.basic_ack(delivery_tag=method.delivery_tag)
        elif decision is DeliveryDecision.REQUEUE:
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        else:
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return decision

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(
            target=self._run,
            name="rabbit-lifecycle-consumer",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._connection = pika.BlockingConnection(self._parameters)
                self._channel = self._connection.channel()
                self._channel.basic_qos(prefetch_count=1)
                self._channel.basic_consume(
                    queue=self._queue_name,
                    on_message_callback=(
                        lambda channel, method, _properties, body: self.handle_delivery(
                            channel, method, body
                        )
                    ),
                )
                self._probe.started()
                self._probe.leadership_changed(leader=True)
                self._channel.start_consuming()
            except Exception as error:
                if not self._stop.is_set():
                    self._probe.failed(error)
                    if isinstance(error, pika.exceptions.AMQPError):
                        LOGGER.warning(
                            "RabbitMQ consumer unavailable; reconnecting: %s",
                            error,
                        )
                    else:
                        LOGGER.exception("RabbitMQ consumer failed; reconnecting")
            finally:
                self._probe.stopped()
                self._connection = None
                self._channel = None
            self._stop.wait(self._retry_seconds)

    def stop(self) -> None:
        self._stop.set()
        connection = self._connection
        channel = self._channel
        if connection is not None and connection.is_open and channel is not None:
            connection.add_callback_threadsafe(channel.stop_consuming)
        if self._thread is not None:
            self._thread.join(timeout=max(3.0, self._retry_seconds * 2))