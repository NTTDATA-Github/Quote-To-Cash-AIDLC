"""WebhookDispatchService — the `webhook-dispatch` consumer.

Consumes any event in `DISPATCHABLE_EVENT_TYPES`, signs a payload per the design's own
verification spec (WebhookEndpoints.dc.html: `X-Signature: t=<ts>,v1=<hmac>` over
`"{ts}.{body}"`), and POSTs it to every active, subscribed endpoint for the event's tenant.

One Service Bus message can fan out to several endpoints. If ANY of them still needs a retry, the
whole handler raises so Service Bus redelivers the message — which re-sends to every endpoint,
including ones that already succeeded. That's a real tradeoff (a receiver can see the same
event twice), not an oversight: avoiding it needs per-endpoint retry state independent of
the message's own redelivery, which is real, separable follow-up work. Webhook receivers
are expected to handle at-least-once delivery anyway (the signature lets them dedupe on
eventId themselves), same as every other consumer in this system.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Protocol

from src.modules.integration.webhooks_inbound.domain.signature import compute_signature
from src.shared.types import TenantId, generate_id

from ..domain.models import DISPATCHABLE_EVENT_TYPES, DeliveryStatus, WebhookDelivery

if TYPE_CHECKING:
    from src.shared.eventsourcing import StoredEvent
    from src.shared.secrets import SecretStore

    from .ports import WebhookDeliveryRepository, WebhookEndpointRepository, WebhookSender

MAX_ATTEMPTS = 5  # mirrors messaging-topology.md's locked max delivery count


class OrderSummaryReader(Protocol):
    """The one field the webhook body needs beyond what's on the event itself — kept
    narrow so this module doesn't depend on the whole projections store's query surface."""

    def get_operator_view(
        self, order_id: str
    ) -> object | None: ...  # duck-typed: .client_reference, .status


class WebhookDeliveryRetry(Exception):
    """Raised when at least one endpoint still needs a retry, so Service Bus redelivers it."""


class WebhookDispatchService:
    def __init__(
        self,
        *,
        endpoints: WebhookEndpointRepository,
        deliveries: WebhookDeliveryRepository,
        secrets: SecretStore,
        sender: WebhookSender,
        orders: OrderSummaryReader,
    ) -> None:
        self._endpoints = endpoints
        self._deliveries = deliveries
        self._secrets = secrets
        self._sender = sender
        self._orders = orders

    def handle(self, event: StoredEvent) -> None:
        if event.event_type not in DISPATCHABLE_EVENT_TYPES or event.tenant_id is None:
            return

        tenant_id = TenantId(event.tenant_id)
        order_id = str(event.payload.get("order_id") or event.stream_id)
        targets = [
            e
            for e in self._endpoints.list_by_tenant(tenant_id)
            if e.subscribes_to(event.event_type)
        ]
        if not targets:
            return

        body = self._build_body(event, order_id)
        raw_body = json.dumps(body).encode("utf-8")

        still_retrying: list[str] = []
        for endpoint in targets:
            delivery = self._deliveries.find(
                endpoint.endpoint_id, event.event_id
            ) or WebhookDelivery(
                delivery_id=generate_id("whdlv"),
                endpoint_id=endpoint.endpoint_id,
                tenant_id=tenant_id,
                order_id=order_id,
                event_type=event.event_type,
                event_id=event.event_id,
                occurred_at=event.occurred_at,
                status=DeliveryStatus.RETRYING,
                attempts=0,
                last_response=None,
                payload=body,
            )
            self._attempt(endpoint, delivery, raw_body)
            self._deliveries.upsert(delivery)
            if delivery.status is DeliveryStatus.RETRYING:
                still_retrying.append(endpoint.name)

        if still_retrying:
            raise WebhookDeliveryRetry(
                f"{len(still_retrying)} endpoint(s) still retrying: {', '.join(still_retrying)}"
            )

    def _attempt(self, endpoint, delivery: WebhookDelivery, raw_body: bytes) -> None:
        secret = self._secrets.get_secret(endpoint.secret_ref)
        timestamp = str(int(time.time()))
        signature = (
            f"t={timestamp},v1={compute_signature(secret, f'{timestamp}.'.encode() + raw_body)}"
        )
        result = self._sender.send(
            endpoint.url,
            {"Content-Type": "application/json", "X-Signature": signature},
            raw_body,
        )
        delivery.attempts += 1
        if result.success:
            delivery.status = DeliveryStatus.DELIVERED
            delivery.last_response = f"{result.status_code} OK"
            return
        delivery.last_response = result.error or (
            f"HTTP {result.status_code}" if result.status_code is not None else "network error"
        )
        delivery.status = (
            DeliveryStatus.FAILED if delivery.attempts >= MAX_ATTEMPTS else DeliveryStatus.RETRYING
        )

    def _build_body(self, event: StoredEvent, order_id: str) -> dict:
        # order.status is the LATEST known status as of dispatch time, not necessarily
        # the one this specific event set — projections.fifo and webhook-dispatch.fifo
        # are independent consumers racing on the same topic, so a fast-moving order can
        # be one status further along by the time this reads it. event.event / eventId
        # are the authoritative "what happened, and when" signal; order.status is a
        # convenience snapshot, same eventually-consistent tradeoff as the rest of the
        # read side (e.g. the reconcile sweeper).
        view = self._orders.get_operator_view(order_id)
        order_body: dict[str, object] = {"id": order_id}
        if view is not None:
            order_body["number"] = view.client_reference  # type: ignore[attr-defined]
            order_body["status"] = view.status  # type: ignore[attr-defined]
        return {
            "event": event.event_type,
            "eventId": event.event_id,
            "occurredAt": event.occurred_at.isoformat(),
            "order": order_body,
        }
