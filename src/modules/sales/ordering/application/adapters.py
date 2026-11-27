"""Adapters that let other modules drive/read the Order aggregate through narrow ports.

- `OrderCommandAdapter` implements integration's `OrderCommandPort` (delivery outcomes).
- `OrderReaderAdapter` implements integration's `OrderReader` (payload for the ERP request).
- `StatusApplier` implements webhooks_inbound's `OrderStatusPort` (inbound status -> lifecycle),
  advancing through valid intermediate transitions and ignoring stale/out-of-order updates.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, Protocol

from src.shared.canonical_status import CanonicalStatus
from src.shared.money import money_to_payload, tax_rate_to_payload
from src.shared.types import ConnectionId, OrderId, TenantId

from ..domain.errors import OrderInvalidTransition

if TYPE_CHECKING:
    from src.shared.eventsourcing import EventSourcedRepository

    from ..domain.aggregate import Order
    from ..projections.postgres_store import PostgresOrderProjectionStore
    from ..projections.store import OrderProjectionStore


class CustomerDirectory(Protocol):
    """Resolves the reseller's ERP customer id for a connection (from the binding) so the
    order can be sent to the ERP as that customer (FR-A1). Operator-only data — never put
    on a reseller view."""

    def erp_customer_id_for(
        self, tenant_id: TenantId, connection_id: ConnectionId
    ) -> str | None: ...


class OrderCommandAdapter:
    def __init__(self, repository: EventSourcedRepository[Order]) -> None:
        self._repository = repository

    def send_to_erp(self, order_id: OrderId, erp_order_id: str) -> None:
        order = self._repository.get(order_id)
        order.send_to_erp(erp_order_id)
        self._repository.save(order)

    def reject(self, order_id: OrderId, reason_code: str, message: str) -> None:
        order = self._repository.get(order_id)
        order.reject(reason_code, message)
        self._repository.save(order)

    def mark_retrying(self, order_id: OrderId, attempt: int, next_retry_at: str) -> None:
        order = self._repository.get(order_id)
        order.mark_retrying(attempt, next_retry_at)
        self._repository.save(order)


class OrderReaderAdapter:
    def __init__(
        self,
        projections: OrderProjectionStore | PostgresOrderProjectionStore,
        customers: CustomerDirectory | None = None,
    ) -> None:
        self._projections = projections
        self._customers = customers

    def read_payload(self, order_id: OrderId) -> dict[str, Any] | None:
        view = self._projections.get_operator_view(order_id)
        if view is None:
            return None
        erp_customer_id: str | None = None
        if self._customers is not None and view.owning_connection_id:
            erp_customer_id = self._customers.erp_customer_id_for(
                TenantId(view.tenant_id), ConnectionId(view.owning_connection_id)
            )
        return {
            # Idempotency key for the ERP submit is the platform order id, not the
            # reseller's client_reference (FR-A2) — client_reference is not unique.
            "order_id": str(order_id),
            "client_reference": view.client_reference,
            # The customer the order is placed as (FR-A1) — the ERP's own customer id,
            # from the binding. No name-based auto-create downstream.
            "erp_customer_id": erp_customer_id,
            "ship_to": view.parties.ship_to,
            "lines": [
                {
                    "line_id": line.line_id,
                    "product_key": line.product_key,
                    "quantity": line.quantity,
                    "unit_of_measure": line.unit_of_measure,
                    "unit_price": money_to_payload(line.unit_price),
                    "tax_rates": [tax_rate_to_payload(t) for t in line.tax_rates],
                    "line_discount": money_to_payload(line.line_discount),
                }
                for line in view.lines
            ],
        }


class StatusApplier:
    """Drives the order toward the canonical status implied by an ERP update."""

    def __init__(self, repository: EventSourcedRepository[Order]) -> None:
        self._repository = repository

    def apply_status(self, order_id: OrderId, status: CanonicalStatus) -> None:
        order = self._repository.get(order_id)
        if status is CanonicalStatus.CANCELLED:
            self._try(order.cancel, "cancelled in ERP")
        else:
            # FULFILLED left the lifecycle (FR-A6) — the ERP's "fully delivered" is tracked
            # as a shipped/delivered fact via Fulfillment records now, not a lifecycle step.
            progression = [CanonicalStatus.CONFIRMED, CanonicalStatus.CLOSED]
            steps = [order.confirm, order.close]
            for step in steps[: progression.index(status) + 1]:
                self._try(step)
        self._repository.save(order)

    @staticmethod
    def _try(fn: Any, *args: Any) -> None:
        # stale / out-of-order ERP update — lifecycle is monotonic, so a transition that
        # no longer applies is simply ignored.
        with contextlib.suppress(OrderInvalidTransition):
            fn(*args)
