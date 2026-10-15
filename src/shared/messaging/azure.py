"""Azure Service Bus adapter (ADR-0023) — implements the `EventPublisher` port + a
consumer, the Azure counterpart to `aws.py`'s SNS/SQS adapter.

FIFO equivalence: `session_id=event.stream_id` (today's SNS `MessageGroupId`) plus the
topic's `support_ordering=true` (see `infra/azure/modules/messaging`). Routing:
`eventType` becomes a message application property, matched by each subscription's SQL
filter instead of an SNS filter policy. There is no entity-level dedup (Service Bus
`requires_duplicate_detection=false`, same as SNS's `content_based_deduplication=false`) —
redelivery is handled the same way it already is on the AWS path: the worker's
`_dedupe` wrapper (`src/worker/main.py`) against `processed_events`, not by the transport.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .envelope import from_json, to_json

if TYPE_CHECKING:
    from src.shared.eventsourcing import StoredEvent

    from .bus import MessageHandler

log = logging.getLogger(__name__)


def _credential(credential: Any | None, managed_identity_client_id: str | None) -> Any:
    if credential is not None:
        return credential
    from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

    return (
        ManagedIdentityCredential(client_id=managed_identity_client_id)
        if managed_identity_client_id
        else DefaultAzureCredential()
    )


class ServiceBusPublisher:
    """EventPublisher over a Service Bus topic with sessions enabled."""

    def __init__(
        self,
        namespace_fqdn: str,
        topic_name: str,
        client: Any | None = None,
        credential: Any | None = None,
        managed_identity_client_id: str | None = None,
    ) -> None:
        if client is None:
            from azure.servicebus import ServiceBusClient

            client = ServiceBusClient(
                fully_qualified_namespace=namespace_fqdn,
                credential=_credential(credential, managed_identity_client_id),
            )
        self._client = client
        self._topic_name = topic_name

    def publish(self, events: list[StoredEvent]) -> None:
        from azure.servicebus import ServiceBusMessage

        with self._client.get_topic_sender(self._topic_name) as sender:
            for event in events:
                message = ServiceBusMessage(
                    to_json(event),
                    session_id=event.stream_id,
                    application_properties={"eventType": event.event_type},
                )
                sender.send_messages(message)


class ServiceBusConsumerRunner:
    """Receives from one session-enabled subscription and dispatches to a handler.

    On success the message is completed (deleted); on handler error it is abandoned, left
    for Service Bus to redeliver, and after `max_delivery_count` it lands in that
    subscription's built-in dead-letter sub-queue. Handlers must be idempotent (dedupe on
    event_id) because delivery is at-least-once, same contract as the SQS adapter.
    """

    def __init__(
        self,
        namespace_fqdn: str,
        topic_name: str,
        subscription_name: str,
        handler: MessageHandler,
        client: Any | None = None,
        credential: Any | None = None,
        managed_identity_client_id: str | None = None,
        max_wait_seconds: float = 10,
    ) -> None:
        if client is None:
            from azure.servicebus import ServiceBusClient

            client = ServiceBusClient(
                fully_qualified_namespace=namespace_fqdn,
                credential=_credential(credential, managed_identity_client_id),
            )
        self._client = client
        self._topic_name = topic_name
        self._subscription_name = subscription_name
        self._handler = handler
        self._max_wait_seconds = max_wait_seconds

    def poll_once(self) -> int:
        from azure.servicebus import NEXT_AVAILABLE_SESSION
        from azure.servicebus.exceptions import OperationTimeoutError, ServiceBusError

        try:
            receiver = self._client.get_subscription_receiver(
                topic_name=self._topic_name,
                subscription_name=self._subscription_name,
                session_id=NEXT_AVAILABLE_SESSION,
                max_wait_time=self._max_wait_seconds,
            )
        except (OperationTimeoutError, ServiceBusError):
            return 0  # no session has a message ready right now — same as an empty SQS poll

        processed = 0
        with receiver:
            for message in receiver.receive_messages(max_wait_time=self._max_wait_seconds):
                event = from_json(str(message))
                try:
                    self._handler(event)
                except Exception:
                    log.exception(
                        "handler failed for event_id=%s event_type=%s; left for redrive",
                        event.event_id,
                        event.event_type,
                    )
                    receiver.abandon_message(message)
                    processed += 1
                    continue
                receiver.complete_message(message)
                processed += 1
        return processed

    def run_forever(self) -> None:  # pragma: no cover - long-running loop
        while True:
            self.poll_once()
