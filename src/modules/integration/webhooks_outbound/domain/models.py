"""Outbound webhook domain models: reseller-registered endpoints and delivery attempts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from src.shared.erp_auth import AuthType

if TYPE_CHECKING:
    from datetime import datetime

    from src.shared.types import TenantId, WebhookEndpointId

# The only event types actually routed to webhook-dispatch.fifo (messaging-topology.md's
# locked subscription filter) — an endpoint's `event_types` is a subset of this, or None
# for "all of these".
DISPATCHABLE_EVENT_TYPES = frozenset(
    {
        "OrderSentToErp",
        "OrderConfirmed",
        "OrderClosed",
        "OrderRejected",
        "OrderRetrying",
        # Previously a documented gap (a cancellation — reseller-initiated or
        # ERP-reported — never reached a reseller's webhook, only visible on next
        # GraphQL read). Closed: resellers now hear about it the same way as every
        # other terminal/near-terminal transition.
        "OrderCancelled",
        # ShipmentRecorded/InvoiceRecorded (not Order-prefixed, but still include
        # order_id in their own payload — see WebhookDispatchService._build_body) carry
        # the shipment/invoice facts resellers previously had no way to be notified of.
        # `OrderFulfilled` was removed: nothing emits it since Increment 5 dropped
        # FULFILLED from the order lifecycle (see its docstring in
        # sales/ordering/domain/events.py) — it was a dead subscription.
        "ShipmentRecorded",
        "InvoiceRecorded",
    }
)


@dataclass
class WebhookEndpoint:
    """One reseller-owned HTTP endpoint. Two separate secrets, for two directions:

    - `secret_ref` resolves the HMAC signing secret. The app generates it and shows it to the
      reseller once; it proves each request came from us (`X-Signature`).
    - `auth_secret_ref` resolves the credential we send *to* the reseller, for receivers that
      require one (an API key header, a bearer token, or basic auth). `auth_type` says how it
      is sent; `auth_params` holds its non-secret settings (header name, username).
    """

    endpoint_id: WebhookEndpointId
    tenant_id: TenantId
    name: str
    url: str
    secret_ref: str
    event_types: frozenset[str] | None  # None = all DISPATCHABLE_EVENT_TYPES
    is_active: bool = True
    auth_type: AuthType = AuthType.NONE
    auth_params: dict[str, str] = field(default_factory=dict)
    auth_secret_ref: str | None = None

    def subscribes_to(self, event_type: str) -> bool:
        return self.is_active and (self.event_types is None or event_type in self.event_types)


class DeliveryStatus(str, Enum):
    DELIVERED = "DELIVERED"
    RETRYING = "RETRYING"
    FAILED = "FAILED"  # exhausted retries (dead-lettered)


@dataclass
class WebhookDelivery:
    """One (endpoint, event) delivery attempt record, updated in place across retries —
    not one row per HTTP attempt. `attempts` mirrors messaging-topology.md's locked
    `maxReceiveCount=5`: once it hits that, the delivery is FAILED even though the
    underlying message also lands in the dead-letter queue around the same
    time — two views of the same limit, not two separate policies to keep in sync."""

    delivery_id: str
    endpoint_id: WebhookEndpointId
    tenant_id: TenantId
    order_id: str
    event_type: str
    event_id: str
    occurred_at: datetime
    status: DeliveryStatus
    attempts: int
    last_response: str | None
    payload: dict
