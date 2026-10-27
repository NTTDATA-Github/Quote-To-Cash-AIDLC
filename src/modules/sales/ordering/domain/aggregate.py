"""The Order aggregate — event-sourced via the shared kernel.

Behavior + invariants live here. State changes ONLY by applying events; every public
method guards the current lifecycle state and `emit`s a fact. Terminal transitions and
already-in-target-state calls are handled so at-least-once redelivery is safe.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.shared.eventsourcing import Aggregate
from src.shared.types import ConnectionId, OrderId, TenantId

from .errors import OrderInvalidTransition
from .events import (
    OrderCancelled,
    OrderClosed,
    OrderConfirmed,
    OrderFulfilled,
    OrderLineFulfilled,
    OrderLineInvoiced,
    OrderLineVendorDateSet,
    OrderObserved,
    OrderReadyForDelivery,
    OrderRejected,
    OrderRetrying,
    OrderSentToErp,
    OrderSubmitted,
    OrderValidated,
)
from .models import (
    TERMINAL_STATES,
    DeliveryStatus,
    FulfillmentStatus,
    InvoiceStatus,
    OrderLine,
    OrderState,
    line_is_delivered,
)

# States from which recording a fulfillment/invoice makes sense — can't fulfill/invoice
# before the ERP has even confirmed the order. (No FULFILLED state anymore — FR-A6.)
_RECORDABLE_STATES = frozenset({OrderState.CONFIRMED, OrderState.CLOSED})


class Order(Aggregate):
    aggregate_type = "Order"

    def __init__(self, id: str) -> None:
        super().__init__(id)
        self.tenant_id: TenantId = TenantId("")
        self.client_reference: str = ""
        self.quote_id: str = ""
        self.subsidiary_id: str = ""
        self.end_customer_name: str = ""
        self.ship_to: str = ""
        self.lines: list[OrderLine] = []
        self.product_keys: list[str] = []
        self.state: OrderState | None = None
        self.owning_connection_id: ConnectionId | None = None
        self.erp_order_id: str | None = None
        self.retry_attempt: int = 0
        # Orthogonal to `state` (ADR-0014), all keyed by line_id (FR-A3):
        # - shipped: fulfillment "score" (FulfillmentStatus)
        # - delivered: the delivered fact (DeliveryStatus) — box needs carrier/POD, FR-D2
        # - invoiced: invoice "score" (InvoiceStatus)
        self.shipped_qty_by_line: dict[str, Decimal] = {}
        self.delivered_qty_by_line: dict[str, Decimal] = {}
        self.invoiced_qty_by_line: dict[str, Decimal] = {}
        self.vendor_date_by_line: dict[str, str] = {}

    # --- commands (behavior) ---
    @classmethod
    def submit(
        cls,
        *,
        order_id: OrderId,
        tenant_id: TenantId,
        client_reference: str,
        lines: list[OrderLine],
        quote_id: str = "",
        subsidiary_id: str = "",
        end_customer_name: str = "",
        ship_to: str = "",
        routed_to_connection_id: str = "",
    ) -> Order:
        if not lines:
            raise ValueError("order must have at least one line")
        for line in lines:
            if not line.product_key:
                raise ValueError("line requires a product_key")
            if not line.line_id:
                raise ValueError("line requires a line_id")
            if line.quantity <= 0:
                raise ValueError("line quantity must be positive")

        order = cls(order_id)
        order.emit(
            OrderSubmitted(
                order_id=order_id,
                tenant_id=tenant_id,
                client_reference=client_reference,
                # OrderLine.to_dict() is JSON-safe (Decimal/Money -> str) — this payload
                # lands in a Postgres JSONB column (events/outbox).
                lines=[line.to_dict() for line in lines],
                product_keys=[line.product_key for line in lines],
                quote_id=quote_id,
                subsidiary_id=subsidiary_id,
                end_customer_name=end_customer_name,
                ship_to=ship_to,
                routed_to_connection_id=routed_to_connection_id,
            )
        )
        return order

    @classmethod
    def observe(
        cls,
        *,
        order_id: OrderId,
        tenant_id: TenantId,
        client_reference: str,
        lines: list[OrderLine],
        connection_id: str,
        erp_order_id: str,
        subsidiary_id: str = "",
    ) -> Order:
        """Adopt a sales order that already exists in the ERP. Does not emit
        `OrderReadyForDelivery`, so nothing turns around and creates one."""
        if not lines:
            raise ValueError("order must have at least one line")
        for line in lines:
            if not line.product_key:
                raise ValueError("line requires a product_key")
            if not line.line_id:
                raise ValueError("line requires a line_id")
            if line.quantity <= 0:
                raise ValueError("line quantity must be positive")
        order = cls(order_id)
        order.emit(
            OrderObserved(
                order_id=order_id,
                tenant_id=tenant_id,
                client_reference=client_reference,
                lines=[line.to_dict() for line in lines],
                product_keys=[line.product_key for line in lines],
                routed_to_connection_id=connection_id,
                erp_order_id=erp_order_id,
                subsidiary_id=subsidiary_id,
            )
        )
        return order

    def validate(self) -> None:
        """Marks the tenant's binding to `owning_connection_id` (already known from
        submission, Increment 7) as confirmed verified."""
        self._require(OrderState.SUBMITTED, "validate")
        self.emit(OrderValidated(order_id=self.id))

    def accept(self) -> None:
        """Routed and ready to send to the ERP (was `mark_ready_for_delivery`; the state
        is `ACCEPTED` now, FR-A6). Still emits the historical `OrderReadyForDelivery`."""
        self._require(OrderState.VALIDATED, "accept")
        assert self.owning_connection_id is not None
        self.emit(
            OrderReadyForDelivery(
                order_id=self.id, owning_connection_id=str(self.owning_connection_id)
            )
        )

    def reject(self, reason_code: str, reseller_message: str) -> None:
        # Refused before the ERP took it (SUBMITTED, VALIDATED), or refused by the ERP during
        # delivery (ACCEPTED, or RETRYING after earlier transient failures).
        if self.state not in (
            OrderState.SUBMITTED,
            OrderState.VALIDATED,
            OrderState.ACCEPTED,
            OrderState.RETRYING,
        ):
            raise OrderInvalidTransition(f"cannot reject in state {self.state}")
        self.emit(
            OrderRejected(
                order_id=self.id, reason_code=reason_code, reseller_message=reseller_message
            )
        )

    def send_to_erp(self, erp_order_id: str) -> None:
        if self.state not in (OrderState.ACCEPTED, OrderState.RETRYING):
            raise OrderInvalidTransition(f"cannot send_to_erp in state {self.state}")
        self.emit(OrderSentToErp(order_id=self.id, erp_order_id=erp_order_id))

    def mark_retrying(self, attempt: int, next_retry_at: str) -> None:
        if self.state not in (OrderState.ACCEPTED, OrderState.RETRYING, OrderState.SENT_TO_ERP):
            raise OrderInvalidTransition(f"cannot mark_retrying in state {self.state}")
        self.emit(OrderRetrying(order_id=self.id, attempt=attempt, next_retry_at=next_retry_at))

    def confirm(self) -> None:
        if self.state is OrderState.CONFIRMED:
            return  # idempotent
        self._require(OrderState.SENT_TO_ERP, "confirm")
        self.emit(OrderConfirmed(order_id=self.id))

    def close(self) -> None:
        if self.state is OrderState.CLOSED:
            return
        self._require(OrderState.CONFIRMED, "close")
        self.emit(OrderClosed(order_id=self.id))

    def cancel(self, reason: str) -> None:
        if self.state in TERMINAL_STATES:
            raise OrderInvalidTransition(f"cannot cancel in state {self.state}")
        self.emit(OrderCancelled(order_id=self.id, reason=reason))

    def record_fulfillment(
        self,
        line_id: str,
        quantity: Decimal,
        *,
        carrier: str | None = None,
        proof_of_delivery: str | None = None,
    ) -> None:
        """A `Fulfillment` record shipped `quantity` of `line_id`. Updates the orthogonal
        shipped/delivered facts only — the lifecycle `state` is untouched. The delivered
        fact (FR-D2) is derived here from the line's kind + the evidence."""
        if self.state not in _RECORDABLE_STATES:
            raise OrderInvalidTransition(f"cannot record fulfillment in state {self.state}")
        self.emit(
            OrderLineFulfilled(
                order_id=self.id,
                line_id=line_id,
                product_key=self._product_key_for(line_id),
                quantity=str(quantity),
                carrier=carrier,
                proof_of_delivery=proof_of_delivery,
            )
        )

    def record_invoice(self, line_id: str, quantity: Decimal) -> None:
        if self.state not in _RECORDABLE_STATES:
            raise OrderInvalidTransition(f"cannot record invoice in state {self.state}")
        self.emit(
            OrderLineInvoiced(
                order_id=self.id,
                line_id=line_id,
                product_key=self._product_key_for(line_id),
                quantity=str(quantity),
            )
        )

    def set_vendor_date(self, line_id: str, vendor_date: str) -> None:
        """Purchasing bought the line from the maker on `vendor_date` — "scheduled"
        (FR-E1). Allowed once the order is live (not pre-validation, not terminal-rejected)."""
        if self.state in (None, OrderState.SUBMITTED, OrderState.REJECTED, OrderState.CANCELLED):
            raise OrderInvalidTransition(f"cannot set vendor date in state {self.state}")
        if not any(line.line_id == line_id for line in self.lines):
            raise ValueError(f"no line '{line_id}' on this order")
        self.emit(
            OrderLineVendorDateSet(order_id=self.id, line_id=line_id, vendor_date=vendor_date)
        )

    # --- derived (not stored directly) ---
    @property
    def fulfillment_status(self) -> FulfillmentStatus:
        return self._qty_status(
            self.shipped_qty_by_line,
            FulfillmentStatus.UNFULFILLED,
            FulfillmentStatus.PARTIALLY_FULFILLED,
            FulfillmentStatus.FULFILLED,
        )

    @property
    def delivery_status(self) -> DeliveryStatus:
        return self._qty_status(
            self.delivered_qty_by_line,
            DeliveryStatus.NOT_DELIVERED,
            DeliveryStatus.PARTIALLY_DELIVERED,
            DeliveryStatus.DELIVERED,
        )

    @property
    def invoice_status(self) -> InvoiceStatus:
        return self._qty_status(
            self.invoiced_qty_by_line,
            InvoiceStatus.NOT_INVOICED,
            InvoiceStatus.PARTIALLY_INVOICED,
            InvoiceStatus.INVOICED,
        )

    def _ordered_by_line(self) -> dict[str, Decimal]:
        ordered: dict[str, Decimal] = {}
        for line in self.lines:
            ordered[line.line_id] = ordered.get(line.line_id, Decimal(0)) + line.quantity
        return ordered

    def _qty_status(
        self,
        qty_by_line: dict[str, Decimal],
        none_status: Any,
        partial_status: Any,
        full_status: Any,
    ) -> Any:
        ordered = self._ordered_by_line()
        if not ordered:
            return none_status
        recorded_any = any(qty_by_line.get(key, Decimal(0)) > 0 for key in ordered)
        recorded_all = all(qty_by_line.get(key, Decimal(0)) >= ordered[key] for key in ordered)
        if recorded_all:
            return full_status
        if recorded_any:
            return partial_status
        return none_status

    def _product_key_for(self, line_id: str) -> str:
        for line in self.lines:
            if line.line_id == line_id:
                return line.product_key
        return ""

    def _line_kind(self, line_id: str, product_key: str) -> str:
        for line in self.lines:
            if line.line_id == line_id or (line_id == "" and line.product_key == product_key):
                return line.kind
        return ""

    def _require(self, expected: OrderState, action: str) -> None:
        if self.state is not expected:
            raise OrderInvalidTransition(
                f"cannot {action} in state {self.state} (requires {expected})"
            )

    # --- state transitions (pure applies) ---
    def _apply_OrderSubmitted(self, e: OrderSubmitted) -> None:
        self.tenant_id = TenantId(e.tenant_id)
        self.client_reference = e.client_reference
        self.quote_id = e.quote_id
        self.subsidiary_id = e.subsidiary_id
        self.end_customer_name = e.end_customer_name
        self.ship_to = e.ship_to
        self.lines = [OrderLine.from_dict(line) for line in e.lines]
        self.product_keys = list(e.product_keys)
        # Increment 7: the connection is already decided (by the quote), not derived by
        # routing later — set it here, at submission, not in OrderValidated.
        self.owning_connection_id = ConnectionId(e.routed_to_connection_id)
        self.state = OrderState.SUBMITTED

    def _apply_OrderObserved(self, e: OrderObserved) -> None:
        self.tenant_id = TenantId(e.tenant_id)
        self.client_reference = e.client_reference
        self.lines = [OrderLine.from_dict(line) for line in e.lines]
        self.product_keys = list(e.product_keys)
        self.owning_connection_id = ConnectionId(e.routed_to_connection_id)
        self.erp_order_id = e.erp_order_id
        self.subsidiary_id = e.subsidiary_id
        self.state = OrderState.SENT_TO_ERP

    def _apply_OrderValidated(self, e: OrderValidated) -> None:
        self.state = OrderState.VALIDATED

    def _apply_OrderReadyForDelivery(self, e: OrderReadyForDelivery) -> None:
        self.state = OrderState.ACCEPTED

    def _apply_OrderRejected(self, e: OrderRejected) -> None:
        self.state = OrderState.REJECTED

    def _apply_OrderSentToErp(self, e: OrderSentToErp) -> None:
        self.erp_order_id = e.erp_order_id
        self.state = OrderState.SENT_TO_ERP

    def _apply_OrderRetrying(self, e: OrderRetrying) -> None:
        self.retry_attempt = e.attempt
        self.state = OrderState.RETRYING

    def _apply_OrderConfirmed(self, e: OrderConfirmed) -> None:
        self.state = OrderState.CONFIRMED

    def _apply_OrderFulfilled(self, e: OrderFulfilled) -> None:
        # No-op: FULFILLED left the lifecycle (FR-A6). Kept only so pre-Increment-5
        # streams that contain this event still replay without an UnhandledEvent.
        return

    def _apply_OrderClosed(self, e: OrderClosed) -> None:
        self.state = OrderState.CLOSED

    def _apply_OrderCancelled(self, e: OrderCancelled) -> None:
        self.state = OrderState.CANCELLED

    def _apply_OrderLineFulfilled(self, e: OrderLineFulfilled) -> None:
        key = e.line_id or e.product_key
        qty = Decimal(e.quantity)
        self.shipped_qty_by_line[key] = self.shipped_qty_by_line.get(key, Decimal(0)) + qty
        # Delivered fact (FR-D2) — shared rule so aggregate + projection can't drift.
        if line_is_delivered(
            self._line_kind(e.line_id, e.product_key), e.carrier, e.proof_of_delivery
        ):
            self.delivered_qty_by_line[key] = self.delivered_qty_by_line.get(key, Decimal(0)) + qty

    def _apply_OrderLineInvoiced(self, e: OrderLineInvoiced) -> None:
        key = e.line_id or e.product_key
        self.invoiced_qty_by_line[key] = self.invoiced_qty_by_line.get(key, Decimal(0)) + Decimal(
            e.quantity
        )

    def _apply_OrderLineVendorDateSet(self, e: OrderLineVendorDateSet) -> None:
        self.vendor_date_by_line[e.line_id] = e.vendor_date

    # --- snapshot support ---
    def snapshot_state(self) -> dict[str, Any]:
        return {
            "tenant_id": str(self.tenant_id),
            "client_reference": self.client_reference,
            "quote_id": self.quote_id,
            "subsidiary_id": self.subsidiary_id,
            "end_customer_name": self.end_customer_name,
            "ship_to": self.ship_to,
            "lines": [line.to_dict() for line in self.lines],
            "product_keys": list(self.product_keys),
            "state": self.state.value if self.state else None,
            "owning_connection_id": str(self.owning_connection_id)
            if self.owning_connection_id
            else None,
            "erp_order_id": self.erp_order_id,
            "retry_attempt": self.retry_attempt,
            "shipped_qty_by_line": {k: str(v) for k, v in self.shipped_qty_by_line.items()},
            "delivered_qty_by_line": {k: str(v) for k, v in self.delivered_qty_by_line.items()},
            "invoiced_qty_by_line": {k: str(v) for k, v in self.invoiced_qty_by_line.items()},
            "vendor_date_by_line": dict(self.vendor_date_by_line),
        }

    def restore(self, state: dict[str, Any]) -> None:
        self.tenant_id = TenantId(state["tenant_id"])
        self.client_reference = state["client_reference"]
        self.quote_id = state.get("quote_id", "")
        self.subsidiary_id = state.get("subsidiary_id", "")
        self.end_customer_name = state.get("end_customer_name", "")
        self.ship_to = state.get("ship_to", "")
        self.lines = [OrderLine.from_dict(line) for line in state["lines"]]
        self.product_keys = list(state["product_keys"])
        self.state = self._restore_state(state["state"])
        self.owning_connection_id = (
            ConnectionId(state["owning_connection_id"]) if state["owning_connection_id"] else None
        )
        self.erp_order_id = state["erp_order_id"]
        self.retry_attempt = state["retry_attempt"]
        # Legacy snapshots used `fulfilled_qty_by_line` keyed by product_key — read it as
        # the shipped map so a pre-increment snapshot still restores.
        shipped = state.get("shipped_qty_by_line", state.get("fulfilled_qty_by_line", {}))
        self.shipped_qty_by_line = {k: Decimal(v) for k, v in shipped.items()}
        self.delivered_qty_by_line = {
            k: Decimal(v) for k, v in state.get("delivered_qty_by_line", {}).items()
        }
        self.invoiced_qty_by_line = {
            k: Decimal(v) for k, v in state.get("invoiced_qty_by_line", {}).items()
        }
        self.vendor_date_by_line = dict(state.get("vendor_date_by_line", {}))

    @staticmethod
    def _restore_state(value: str | None) -> OrderState | None:
        if not value:
            return None
        if value in ("READY_FOR_DELIVERY",):  # renamed to ACCEPTED in Increment 5 (Q2=A)
            return OrderState.ACCEPTED
        if value == "FULFILLED":  # left the lifecycle (FR-A6) — map legacy to CONFIRMED
            return OrderState.CONFIRMED
        return OrderState(value)
