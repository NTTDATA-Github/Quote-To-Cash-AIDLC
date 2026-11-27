"""DeliveryHandler — the `order-delivery` consumer.

Consumes `OrderReadyForDelivery`, resolves the target connection, reads the order
payload, submits via the ERP adapter, and drives the order aggregate:
- success  -> send_to_erp(erp_order_id)
- terminal -> reject
- transient-> mark_retrying + raise (so the queue redrives the message)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from src.shared.types import ConnectionId, OrderId

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.shared.eventsourcing import StoredEvent

    from .ports import ConnectionResolver, ErpAdapter, OrderCommandPort, OrderReader

log = logging.getLogger(__name__)


class DeliveryRetry(Exception):
    """Raised to signal the queue to redrive the message (transient ERP failure)."""


class DeliveryFailureSink(Protocol):
    """Told about every failed delivery so an operator can see it, and told when a later
    delivery succeeds so the conflict closes. Optional: without one, failures are only recorded
    on the order itself."""

    def record(
        self, order_id: OrderId, *, reason_code: str, reason: str, terminal: bool
    ) -> None: ...

    def cleared(self, order_id: OrderId) -> None: ...


class DeliveryHandler:
    def __init__(
        self,
        *,
        connections: ConnectionResolver,
        orders_read: OrderReader,
        orders_cmd: OrderCommandPort,
        adapter_for: Callable[[str], ErpAdapter],
        failures: DeliveryFailureSink | None = None,
    ) -> None:
        self._connections = connections
        self._orders_read = orders_read
        self._orders_cmd = orders_cmd
        self._adapter_for = adapter_for
        self._failures = failures

    def _reject(self, order_id: OrderId, reason_code: str, message: str) -> None:
        self._orders_cmd.reject(order_id, reason_code, message)
        if self._failures is not None:
            self._failures.record(order_id, reason_code=reason_code, reason=message, terminal=True)

    def handle(self, event: StoredEvent) -> None:
        if event.event_type != "OrderReadyForDelivery":
            return
        order_id = OrderId(str(event.payload["order_id"]))
        connection_id = ConnectionId(str(event.payload["owning_connection_id"]))

        target = self._connections.resolve(connection_id)
        if target is None:
            self._reject(order_id, "connection_unavailable", "target ERP connection unavailable")
            return

        payload = self._orders_read.read_payload(order_id)
        if payload is None:
            self._reject(order_id, "order_not_found", "order payload unavailable")
            return

        adapter = self._adapter_for(target.erp_type)
        # Declared, not gated on yet (ADR-0015) — logged so a capability gap (e.g. this
        # ERP doesn't support tax) is visible in context, rather than only inferable
        # from reading the adapter's own source.
        log.debug(
            "submitting via %s, capabilities=%s",
            target.erp_type,
            sorted(getattr(adapter, "capabilities", frozenset())),
        )
        result = adapter.submit(target, payload)
        if result.success:
            assert result.erp_order_id is not None
            self._orders_cmd.send_to_erp(order_id, result.erp_order_id)
            if self._failures is not None:
                self._failures.cleared(order_id)
        elif result.terminal:
            self._reject(order_id, "erp_rejected", result.error or "ERP rejected the order")
        else:
            message = result.error or "transient ERP failure"
            self._orders_cmd.mark_retrying(order_id, attempt=1, next_retry_at="")
            if self._failures is not None:
                self._failures.record(
                    order_id, reason_code="erp_unavailable", reason=message, terminal=False
                )
            raise DeliveryRetry(message)
