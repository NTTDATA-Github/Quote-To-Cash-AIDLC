from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from src.modules.integration.erp.application.delivery import DeliveryHandler, DeliveryRetry
from src.modules.integration.erp.application.ports import ErpTarget, SubmissionResult
from src.modules.integration.erp.infrastructure.stub_adapter import StubErpAdapter
from src.shared.eventsourcing import StoredEvent

if TYPE_CHECKING:
    from src.shared.types import ConnectionId, OrderId


def _ready_event(order_id: str = "ord_1", connection_id: str = "conn_1") -> StoredEvent:
    return StoredEvent(
        stream_id=order_id,
        aggregate_type="Order",
        version=3,
        event_type="OrderReadyForDelivery",
        event_id="e1",
        occurred_at=datetime.now(UTC),
        payload={"order_id": order_id, "owning_connection_id": connection_id},
    )


class FakeConnections:
    def resolve(self, connection_id: ConnectionId) -> ErpTarget | None:
        return ErpTarget(
            erp_type="ODOO",
            base_url="http://odoo",
            credentials={"database": "odoo", "username": "admin"},
            secret="x",
        )


class FakeOrders:
    def read_payload(self, order_id: OrderId) -> dict[str, Any] | None:
        return {"client_reference": "PO-1", "lines": [{"product_key": "ANVIL", "quantity": 1}]}


class RecordingCommands:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def send_to_erp(self, order_id: OrderId, erp_order_id: str) -> None:
        self.calls.append(("send_to_erp", (order_id, erp_order_id)))

    def reject(self, order_id: OrderId, reason_code: str, message: str) -> None:
        self.calls.append(("reject", (order_id, reason_code)))

    def mark_retrying(self, order_id: OrderId, attempt: int, next_retry_at: str) -> None:
        self.calls.append(("mark_retrying", (order_id, attempt)))


def _handler(adapter: Any, cmds: RecordingCommands) -> DeliveryHandler:
    return DeliveryHandler(
        connections=FakeConnections(),
        orders_read=FakeOrders(),
        orders_cmd=cmds,
        adapter_for=lambda _erp_type: adapter,
    )


def test_successful_delivery_sends_to_erp() -> None:
    cmds = RecordingCommands()
    _handler(StubErpAdapter(), cmds).handle(_ready_event())
    assert cmds.calls[0][0] == "send_to_erp"


def test_terminal_failure_rejects() -> None:
    class TerminalAdapter:
        def submit(self, target: ErpTarget, payload: dict[str, Any]) -> SubmissionResult:
            return SubmissionResult(success=False, error="bad product", terminal=True)

        def fetch_status(self, target: ErpTarget, erp_order_id: str) -> dict[str, str] | None:
            return None

        def cancel(self, target: ErpTarget, erp_order_id: str) -> SubmissionResult:
            return SubmissionResult(success=False, terminal=True)

    cmds = RecordingCommands()
    _handler(TerminalAdapter(), cmds).handle(_ready_event())
    assert cmds.calls == [("reject", ("ord_1", "erp_rejected"))]


def test_transient_failure_marks_retrying_and_raises() -> None:
    class TransientAdapter:
        def submit(self, target: ErpTarget, payload: dict[str, Any]) -> SubmissionResult:
            return SubmissionResult(success=False, error="timeout", terminal=False)

        def fetch_status(self, target: ErpTarget, erp_order_id: str) -> dict[str, str] | None:
            return None

        def cancel(self, target: ErpTarget, erp_order_id: str) -> SubmissionResult:
            return SubmissionResult(success=False)

    cmds = RecordingCommands()
    with pytest.raises(DeliveryRetry):
        _handler(TransientAdapter(), cmds).handle(_ready_event())
    assert cmds.calls[0][0] == "mark_retrying"


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    def record(self, order_id: OrderId, *, reason_code: str, reason: str, terminal: bool) -> None:
        self.events.append(("record", (str(order_id), reason_code, terminal)))

    def cleared(self, order_id: OrderId) -> None:
        self.events.append(("cleared", str(order_id)))


def _handler_with_sink(
    adapter: Any, cmds: RecordingCommands, sink: RecordingSink
) -> DeliveryHandler:
    return DeliveryHandler(
        connections=FakeConnections(),
        orders_read=FakeOrders(),
        orders_cmd=cmds,
        adapter_for=lambda _erp_type: adapter,
        failures=sink,
    )


def test_rejection_is_reported_to_the_failure_sink_as_terminal() -> None:
    class TerminalAdapter:
        def submit(self, target: ErpTarget, payload: dict[str, Any]) -> SubmissionResult:
            return SubmissionResult(success=False, error="customer on hold", terminal=True)

        def fetch_status(self, target: ErpTarget, erp_order_id: str) -> dict[str, str] | None:
            return None

        def cancel(self, target: ErpTarget, erp_order_id: str) -> SubmissionResult:
            return SubmissionResult(success=False, terminal=True)

    sink = RecordingSink()
    _handler_with_sink(TerminalAdapter(), RecordingCommands(), sink).handle(_ready_event())
    assert sink.events == [("record", ("ord_1", "erp_rejected", True))]


def test_transient_failure_is_reported_as_retryable_before_the_retry() -> None:
    class TransientAdapter:
        def submit(self, target: ErpTarget, payload: dict[str, Any]) -> SubmissionResult:
            return SubmissionResult(success=False, error="timeout", terminal=False)

        def fetch_status(self, target: ErpTarget, erp_order_id: str) -> dict[str, str] | None:
            return None

        def cancel(self, target: ErpTarget, erp_order_id: str) -> SubmissionResult:
            return SubmissionResult(success=False)

    sink = RecordingSink()
    with pytest.raises(DeliveryRetry):
        _handler_with_sink(TransientAdapter(), RecordingCommands(), sink).handle(_ready_event())
    assert sink.events == [("record", ("ord_1", "erp_unavailable", False))]


def test_successful_delivery_clears_the_order_in_the_failure_sink() -> None:
    sink = RecordingSink()
    _handler_with_sink(StubErpAdapter(), RecordingCommands(), sink).handle(_ready_event())
    assert sink.events == [("cleared", "ord_1")]
