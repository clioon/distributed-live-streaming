from enum import StrEnum

from .events import LifecycleEvent, UnsupportedLifecycleEvent
from .service import OrchestratorService


class DeliveryDecision(StrEnum):
    ACK = "ack"
    REQUEUE = "requeue"
    REJECT = "reject"


class MessageProcessor:
    def __init__(self, orchestrator: OrchestratorService):
        self._orchestrator = orchestrator

    def process(self, body: bytes | str) -> DeliveryDecision:
        try:
            event = LifecycleEvent.from_json(body)
        except (ValueError, UnsupportedLifecycleEvent):
            return DeliveryDecision.REJECT
        try:
            self._orchestrator.handle(event)
        except Exception:
            return DeliveryDecision.REQUEUE
        return DeliveryDecision.ACK