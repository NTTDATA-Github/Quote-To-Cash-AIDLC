"""InboundWebhookService — verify, attribute, dedupe, then drive order status."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from src.modules.integration.erp.domain.status_mapping import map_native_status

from ..domain.signature import verify_shared_secret, verify_signature

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.shared.types import ConnectionId

    from .ports import DedupStore, EventInbox, OrderLocator, OrderStatusPort, SecretResolver


class IngressOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"  # attributed + status transition applied
    NO_TRANSITION = "NO_TRANSITION"  # attributed, but native status maps to nothing
    UNAUTHORIZED = "UNAUTHORIZED"  # bad/missing signature
    DUPLICATE = "DUPLICATE"  # already processed this delivery
    UNATTRIBUTABLE = "UNATTRIBUTABLE"  # not an order we created -> ignore


class WebhookAuthMode(str, Enum):
    HMAC = "HMAC"  # ERPNext: real signature over the raw body
    SHARED_SECRET = "SHARED_SECRET"  # Odoo: Automation Rules can't sign, so the secret
    # itself travels in the URL path; `signature` below holds that raw secret instead.


@dataclass(frozen=True)
class InboundWebhook:
    connection_id: ConnectionId
    erp_type: str
    erp_order_id: str
    native_fields: dict[str, str]  # whatever this ERP calls its status fields — the
    # per-ERP status mapper (status_mapping.py) picks out the keys it needs; this
    # transport layer doesn't need to know any ERP's specific field names.
    event_ref: str  # provider delivery id, used for dedup
    raw_body: bytes
    signature: str
    auth_mode: WebhookAuthMode = WebhookAuthMode.HMAC


class InboundWebhookService:
    def __init__(
        self,
        *,
        secrets: SecretResolver,
        dedup: DedupStore,
        inbox: EventInbox,
        locator: OrderLocator,
        order_status: OrderStatusPort,
        refresh: Callable[[ConnectionId, str, str], None] | None = None,
    ) -> None:
        self._secrets = secrets
        self._dedup = dedup
        self._inbox = inbox
        self._locator = locator
        self._order_status = order_status
        # After the order is known: pull shipments and invoices. A NetSuite ping
        # carries an id, not the fulfillment lines. None in tests that only check status.
        self._refresh = refresh

    def handle(self, webhook: InboundWebhook) -> IngressOutcome:
        # 1. authenticate
        secret = self._secrets.secret_for(webhook.connection_id)
        if webhook.auth_mode is WebhookAuthMode.SHARED_SECRET:
            authenticated = secret is not None and verify_shared_secret(secret, webhook.signature)
        else:
            authenticated = secret is not None and verify_signature(
                secret, webhook.raw_body, webhook.signature
            )
        if not authenticated:
            return IngressOutcome.UNAUTHORIZED

        # The body is stored before it is parsed, mapped, or matched to an order.
        self._inbox.append(webhook.connection_id, webhook.raw_body)

        # 2. dedupe
        dedup_key = f"{webhook.connection_id}:{webhook.event_ref}"
        if self._dedup.seen(dedup_key):
            return IngressOutcome.DUPLICATE

        # 3. attribute before publication (reverse routing)
        order_id = self._locator.find_order(webhook.connection_id, webhook.erp_order_id)
        if order_id is None:
            # Not an order we created (or not yet recorded): drop, do NOT mark seen so a
            # later redelivery can attribute once the order exists.
            return IngressOutcome.UNATTRIBUTABLE

        # 4. map + apply (only now do we mark the delivery processed)
        status = map_native_status(webhook.erp_type, webhook.native_fields)
        if status is not None:
            self._order_status.apply_status(order_id, status)
        if self._refresh is not None:
            self._refresh(webhook.connection_id, webhook.erp_order_id, str(order_id))
        self._dedup.mark(dedup_key)
        if status is None:
            return IngressOutcome.NO_TRANSITION
        return IngressOutcome.ACCEPTED
